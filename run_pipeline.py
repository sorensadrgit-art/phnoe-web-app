"""Run local Pose2Sim stages only on validated, session-bound inputs."""
import argparse
import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

from session_contract import load_session, sha256_file, strict_json_loads
from take_acceptance import TakeAcceptanceError, checked_path

STAGES = ("calibration", "poseEstimation", "synchronization", "personAssociation", "triangulation", "filtering", "markerAugmentation", "kinematics")
OUTPUTS = {
    "calibration": ("calibration/*.toml",), "poseEstimation": ("pose/**/*.json",),
    "synchronization": ("pose-sync/**/*.json",), "personAssociation": ("pose-associated/**/*.json",),
    "triangulation": ("pose-3d/*.trc",), "filtering": ("pose-3d/*filt*.trc",),
    "markerAugmentation": ("pose-3d/*LSTM*.trc",), "kinematics": ("kinematics/*.mot", "kinematics/*.osim"),
}
# Older run records predate log-window and downstream gates and must not be accepted.
QUALITY_POLICY = "kinelab.pipeline-quality.v4"
KINEMATICS_POLICY = "kinelab.kinematics-quality.v1"
REJECTED_SCHEMA = "kinelab.rejected-triangulation.v1"
REJECTED_LABEL = "REJECTED / NOT USABLE FOR MEASUREMENT"
REJECTED_QUALITY_SCHEMA = "kinelab.quality.v1"
_REJECTED_KEYS = frozenset({"schema", "session_id", "quality", "frame_diagnostics", "source_trc", "calibration",
                            "bound_inputs", "reasons", "usable_for_measurement"})


def _checked_project(project, code):
    try:
        return checked_path(project).resolve()
    except TakeAcceptanceError as error:
        raise ValueError(code + ": project path is not a plain non-link") from error


def _read_json(path, code):
    try:
        value = strict_json_loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("expected an object")  # noqa: TRY004  caught as ValueError below and re-raised with the stage code
        return value
    except (OSError, ValueError) as error:
        raise ValueError(code + ": missing or invalid " + path.name) from error


def _write_run(project, record):
    temporary = project / "run.building.json"
    temporary.write_text(json.dumps(record, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(project / "run.json")


def _artifacts(project, stage):
    paths = {path for pattern in OUTPUTS[stage] for path in project.glob(pattern) if path.is_file()}
    if stage == "triangulation":
        paths = {path for path in paths if "filt" not in path.name and "LSTM" not in path.name}
    elif stage == "filtering":
        paths = {path for path in paths if "LSTM" not in path.name}
    return {path.relative_to(project).as_posix(): (sha256_file(path), path.stat().st_mtime_ns) for path in sorted(paths)}


def _verify_normalized(project, identity, expected=None):
    from source_coverage import capture_normalization
    try:
        return capture_normalization(project, identity, expected)["binding"]
    except ValueError as error:
        if str(error) == "QUALITY_UNVERIFIED: decoded source coverage: normalized media binding differs":
            raise ValueError("INPUT_CHANGED: normalized media binding differs") from error
        raise

def _validate_artifacts(project, stage, artifacts):
    from export_motion import parse_mot, parse_trc
    for relative in artifacts:
        path = (project / relative).resolve()
        if not path.is_relative_to(project):
            raise ValueError("ARTIFACT_MISMATCH: output escaped the session")
        if path.suffix == ".json":
            data = _read_json(path, "ARTIFACT_MISMATCH")
            people = data.get("people")
            if not isinstance(people, list) or (stage == "personAssociation" and len(people) > 1):
                raise ValueError("ARTIFACT_MISMATCH: invalid OpenPose people/association")
            for person in people:
                if stage == "personAssociation" and people == [{}]:
                    continue  # Exact native missing-person sentinel; never a measured selection.
                values = person.get("pose_keypoints_2d") if isinstance(person, dict) else None
                if not isinstance(values, list) or not values or len(values) % 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values) or any(not 0 <= v <= 1 for v in values[2::3]):
                    raise ValueError("ARTIFACT_MISMATCH: invalid pose keypoints/confidence")
        elif path.suffix == ".trc":
            parse_trc(path)
        elif path.suffix == ".mot":
            parse_mot(path)


def _invoke_stage(stage, project):
    for name, value in (("MPLBACKEND", "Agg"), ("QT_QPA_PLATFORM", "offscreen"), ("OMP_NUM_THREADS", "2"), ("OPENBLAS_NUM_THREADS", "2"), ("MKL_NUM_THREADS", "2")):
        os.environ.setdefault(name, value)
    from source_coverage import stage_frame_overrides
    record = _read_json(project / "run.json", "QUALITY_UNVERIFIED")
    identity = {key: record[key] for key in ("session_id", "config_sha256", "inputs")}
    overrides = stage_frame_overrides(project, identity, record, stage)
    from Pose2Sim import Pose2Sim
    config = {"project": {"project_dir": str(project), **overrides}}
    if stage == "triangulation":
        config["triangulation"] = {"interpolation": "none", "fill_large_gaps_with": "nan"}
    getattr(Pose2Sim, stage)(config=config)


def _log_mark(project):
    data = (project / "logs.txt").read_bytes() if (project / "logs.txt").is_file() else b""
    return len(data), hashlib.sha256(data).hexdigest()


def _log_window(project, mark):
    """Byte window appended by one native call; rotation or rewrite of earlier bytes yields no window."""
    data = (project / "logs.txt").read_bytes() if (project / "logs.txt").is_file() else b""
    if len(data) <= mark[0] or hashlib.sha256(data[:mark[0]]).hexdigest() != mark[1]:
        return None
    return [mark[0], len(data), hashlib.sha256(data[mark[0]:]).hexdigest()]


def _bound_trc(record, stage):
    item = record["stages"][STAGES.index(stage)] if isinstance(record, dict) else {}
    paths = [a for a in item.get("artifacts", []) if isinstance(a, dict) and str(a.get("path", "")).endswith(".trc")] if item.get("status") == "passed" else []
    if len(paths) != 1:
        raise ValueError("QUALITY_REJECTED: exactly one bound " + stage + " TRC required as stage input")
    return paths[0]


def _validate_kinematics(project, record, fresh):
    models = [path for path in fresh if path.endswith(".osim")]
    mots = [path for path in fresh if path.endswith(".mot")]
    if len(models) != 1 or mots != [models[0][:-5] + ".mot"]:
        raise ValueError("KINEMATICS_QUALITY_REJECTED: exactly one fitted model and its IK .mot required; other IK outputs are unverified")
    import tomllib
    config = tomllib.loads((project / "Config.toml").read_text(encoding="utf-8-sig"))
    # Pose2Sim kinematics consumes LSTM TRCs unless use_augmentation is false, naming outputs by the TRC stem.
    source = _bound_trc(record, "filtering" if config.get("kinematics", {}).get("use_augmentation", True) is False else "markerAugmentation")
    trc = "pose-3d/" + Path(models[0]).stem + ".trc"
    if source["path"] != trc or not (project / trc).is_file() or sha256_file(project / trc) != source.get("sha256"):
        raise ValueError("KINEMATICS_QUALITY_REJECTED: consumed TRC is not the unchanged bound stage input")
    try:
        from kinematics_quality import KINEMATICS_QUALITY_POLICY, validate_kinematics_stage
    except ImportError as error:
        raise ValueError("KINEMATICS_QUALITY_UNAVAILABLE: kinematics quality helper missing") from error
    result = validate_kinematics_stage(project, model_path=project / models[0], mot_path=project / mots[0], trc_path=project / trc)
    if KINEMATICS_QUALITY_POLICY != KINEMATICS_POLICY or not isinstance(result, dict) or result.get("ok") is not True or result.get("policy") != KINEMATICS_POLICY:
        raise ValueError("KINEMATICS_QUALITY_REJECTED: " + str(result.get("errors") if isinstance(result, dict) else "invalid helper result"))
    return {**result, "consumed_trc": {"path": trc, "sha256": source["sha256"]}}


def _validate_stage_quality(stage, project, session, record=None, fresh=(), log_window=None):
    if stage in ("poseEstimation", "personAssociation"):
        from source_coverage import verify_source_coverage
        identity = {key: record[key] for key in ("session_id", "config_sha256", "inputs")}
        artifacts = [{"path": path, "sha256": sha256_file(project / path)} for path in fresh]
        coverage = verify_source_coverage(project, identity, record, through=stage, artifacts=artifacts)
        return {"ok": True, "policy": QUALITY_POLICY, "source_coverage": coverage}
    import pipeline_quality as quality
    if stage == "calibration":
        return quality.validate_calibration(project, session, log_window)
    if stage == "synchronization":
        report = quality.validate_sync(project, session, _read_json(project / "sync-observations.json", "SYNC_UNCERTAIN"), log_window)
        if report.get("ok") is True:
            from source_coverage import verify_source_coverage
            identity = {key: record[key] for key in ("session_id", "config_sha256", "inputs")}
            artifacts = [{"path": path, "sha256": sha256_file(project / path)} for path in fresh]
            report["source_coverage"] = verify_source_coverage(
                project, identity, record, through=stage, artifacts=artifacts, quality=report)
        return report
    if stage == "triangulation":
        return quality.validate_reconstruction(project, session)
    try:
        if stage == "kinematics":
            return _validate_kinematics(project, record, list(fresh))
        outputs = [path for path in fresh if path.endswith(".trc")]
        if len(outputs) != 1 or stage not in ("filtering", "markerAugmentation"):
            raise ValueError("QUALITY_REJECTED: unsupported or ambiguous " + stage + " output")
        source = _bound_trc(record, STAGES[STAGES.index(stage) - 1])
        if not (project / source["path"]).is_file() or sha256_file(project / source["path"]) != source.get("sha256"):
            raise ValueError("QUALITY_REJECTED: " + stage + " input TRC changed since it was bound")
        validate = quality.validate_filtering if stage == "filtering" else quality.validate_augmentation
        return validate(project, source["path"], outputs[0])
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"ok": False, "errors": [str(error)]}


def _verify_quality_binding(project, item, stages, *, session_id=None):
    name, quality = item["name"], item["quality"]
    from pipeline_quality import QUALITY_POLICY as measured
    from pipeline_quality import verify_log_binding
    if quality.get("policy") != (KINEMATICS_POLICY if name == "kinematics" else measured):
        raise ValueError("QUALITY_UNVERIFIED: stage quality policy missing or outdated: " + name)
    if name in ("calibration", "synchronization"):
        verify_log_binding(project, quality.get("log"))
    if name in ("filtering", "markerAugmentation", "kinematics"):
        source = quality.get("consumed_trc" if name == "kinematics" else "source")
        inputs = [a for previous in stages for a in previous.get("artifacts", []) if previous["name"] in ("triangulation", "filtering", "markerAugmentation")
                  and STAGES.index(previous["name"]) < STAGES.index(name)]
        if not isinstance(source, dict) or source not in inputs:
            raise ValueError("QUALITY_UNVERIFIED: stage quality is not bound to a recorded stage input: " + name)
    if name == "triangulation" and "frame_diagnostics" in quality:
        from pipeline_quality import verify_frame_diagnostics
        binding = quality["frame_diagnostics"]

        def recorded(stage, suffix):
            return [a for s in stages if isinstance(s, dict) and s.get("name") == stage for a in s.get("artifacts", [])
                    if isinstance(a, dict) and str(a.get("path", "")).endswith(suffix)]
        if (not isinstance(binding, dict) or binding.get("source_trc") not in recorded("triangulation", ".trc")
                or binding.get("calibration") not in recorded("calibration", ".toml")):
            raise ValueError("QUALITY_UNVERIFIED: frame diagnostics not bound to the recorded triangulation TRC and calibration")
        verify_frame_diagnostics(project, binding, session_id=session_id)

def validate_run_evidence(project: Path, through: str, *, session=None) -> dict:
    """One ordered prerequisite check for resume, GUI, index and bound export."""
    project = _checked_project(project, "ARTIFACT_MISMATCH")
    if through not in STAGES:
        raise ValueError("ARTIFACT_MISMATCH: unknown required stage")
    session = load_session(project) if session is None else session
    identity = {"session_id": session["session_id"], "config_sha256": sha256_file(project / "Config.toml"),
                "inputs": {role: entry["sha256"] for role, entry in session["captures"].items()}}
    record = _read_json(project / "run.json", "ARTIFACT_MISMATCH")
    if (record.get("schema") != "kinelab.run.v1" or record.get("coordinateSystem") != "opensim_y_up"
            or any(record.get(key) != value for key, value in identity.items())):
        raise ValueError("ARTIFACT_MISMATCH: native run belongs to changed inputs or unsupported coordinates")
    if record.get("quality_policy") != QUALITY_POLICY:
        raise ValueError("QUALITY_POLICY: run evidence predates the current quality policy; rerun native stages")
    from source_coverage import NATIVE_FRAME_POLICY
    if (record.get("native_frame_policy") != NATIVE_FRAME_POLICY
            or not isinstance(record.get("normalization"), dict)
            or set(record["normalization"]) != {"path", "sha256"}):
        raise ValueError("QUALITY_UNVERIFIED: captured normalization/native frame policy required")
    stages = record.get("stages")
    if (not isinstance(stages, list) or len(stages) != len(STAGES)
            or any(not isinstance(item, dict) or item.get("name") != name for item, name in zip(stages, STAGES))):
        raise ValueError("ARTIFACT_MISMATCH: complete ordered stages required")
    # Rejected evidence is valid only on the failed triangulation it describes.
    if any("rejected_evidence" in item and (item["name"] != "triangulation" or item.get("status") != "failed") for item in stages):
        raise ValueError("ARTIFACT_MISMATCH: rejected evidence recorded on a passed or non-triangulation stage")
    accepted = {}
    for item in stages[:STAGES.index(through) + 1]:
        name = item["name"]
        if item.get("status") != "passed" or not isinstance(item.get("artifacts"), list) or not item["artifacts"]:
            raise ValueError("ARTIFACT_MISMATCH: required stage not passed: " + name)
        if not isinstance(item.get("quality"), dict) or item["quality"].get("ok") is not True:
            raise ValueError("QUALITY_UNVERIFIED: required stage quality missing or rejected: " + name)
        _verify_quality_binding(project, item, stages, session_id=session["session_id"])
        observed = _artifacts(project, name)
        bound = {}
        for artifact in item["artifacts"]:
            if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
                raise ValueError("ARTIFACT_MISMATCH: invalid output binding")  # noqa: TRY004  the pipeline contract raises coded ValueError; callers and tests assert ValueError
            relative = artifact["path"]
            path = project / relative
            if (relative in bound or "\\" in relative or ":" in relative or ".." in Path(relative).parts
                    or Path(relative).is_absolute() or not path.resolve().is_relative_to(project)
                    or any(p.is_symlink() or getattr(p, "is_junction", lambda: False)()
                           for p in (path, *path.parents) if p.is_relative_to(project) and p != project)):
                raise ValueError("ARTIFACT_MISMATCH: duplicate or unsafe output path")
            bound[relative] = artifact.get("sha256")
        if set(observed) != set(bound) or any(observed[path][0] != digest for path, digest in bound.items()):
            raise ValueError("ARTIFACT_MISMATCH: changed, missing or unrecorded output for " + name)
        _validate_artifacts(project, name, bound)
        accepted[name] = item
    preflight = _read_json(project / "preflight.json", "PREFLIGHT_INVALID")
    if (preflight.get("schema") != "kinelab.preflight.v1" or preflight.get("ok") is not True
            or preflight.get("errors") or any(preflight.get(key) != value for key, value in identity.items())):
        raise ValueError("PREFLIGHT_INVALID: evidence does not match this run")
    _verify_normalized(project, identity, record.get("normalization"))
    if STAGES.index(through) >= STAGES.index("poseEstimation"):
        from source_coverage import verify_source_coverage, verify_trc_extent
        coverage = verify_source_coverage(project, identity, record, through=through)
        if STAGES.index(through) >= STAGES.index("triangulation"):
            stage = stages[STAGES.index("triangulation")]
            if stage["quality"].get("source_coverage") != coverage:
                raise ValueError("QUALITY_UNVERIFIED: triangulation source coverage differs")
            trcs = [a for a in stage["artifacts"] if a["path"].endswith(".trc")]
            if len(trcs) != 1:
                raise ValueError("QUALITY_UNVERIFIED: one unfiltered TRC required")
            verify_trc_extent(project, trcs[0], coverage)
    return {"run": record, "session": session, "stages": accepted}


def _bound_bytes(project, relative):
    """Bounded identity-preserving read of one contained, non-link session file."""
    from pipeline_quality import _read_frame_bytes
    path = project / relative if isinstance(relative, str) and relative else None
    if (path is None or "\\" in relative or ":" in relative or ".." in Path(relative).parts or Path(relative).is_absolute()
            or not path.resolve().is_relative_to(project)
            or any(p.is_symlink() or getattr(p, "is_junction", lambda: False)()
                   for p in (path, *path.parents) if p.is_relative_to(project) and p != project)):
        raise ValueError("REJECTED_EVIDENCE_UNVERIFIED: unsafe evidence path " + str(relative))
    try:
        # The frame-diagnostics reader is the house bounded, link-refusing, identity-checked read.
        return _read_frame_bytes(path)
    except (OSError, ValueError) as error:
        raise ValueError("REJECTED_EVIDENCE_UNVERIFIED: " + relative + " is not one stable regular file within the byte cap") from error


def _bound_reference(project, reference, expected_path=None):
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"} or not isinstance(reference["path"], str)
            or (expected_path is not None and reference["path"] != expected_path)):
        raise ValueError("REJECTED_EVIDENCE_UNVERIFIED: malformed byte binding")
    data = _bound_bytes(project, reference["path"])
    if hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise ValueError("REJECTED_EVIDENCE_UNVERIFIED: bound bytes changed: " + reference["path"])
    return data


def _rejected_evidence(project, session, record, quality, fresh):
    """Envelope for a returned ok-is-False triangulation report; None whenever any binding is unavailable."""
    from pipeline_quality import verify_frame_diagnostics
    try:
        session_id = session["session_id"]
        errors = quality.get("errors") if type(quality) is dict else None
        if (type(quality) is not dict or quality.get("schema") != REJECTED_QUALITY_SCHEMA
                or quality.get("ok") is not False or quality.get("session_id") != session_id
                or quality.get("policy") != QUALITY_POLICY or not isinstance(errors, list) or not errors
                or not all(isinstance(reason, str) for reason in errors)):
            return None
        calibration_stage = record["stages"][0]
        trcs = [path for path in fresh if path.endswith(".trc")]
        calibrations = [a for a in calibration_stage.get("artifacts", []) if isinstance(a, dict) and str(a.get("path", "")).endswith(".toml")]
        if len(trcs) != 1 or len(calibrations) != 1 or calibration_stage.get("status") != "passed":
            return None
        source_trc = {"path": trcs[0], "sha256": fresh[trcs[0]][0]}
        calibration = {"path": calibrations[0].get("path"), "sha256": calibrations[0].get("sha256")}
        binding = quality.get("frame_diagnostics")
        if not isinstance(binding, dict) or binding.get("source_trc") != source_trc or binding.get("calibration") != calibration:
            return None
        verify_frame_diagnostics(project, binding, session_id=session_id)
        _bound_reference(project, source_trc)
        _bound_reference(project, calibration)
        stored = _bound_bytes(project, "quality.json")
        if strict_json_loads(stored.decode("utf-8")) != quality:
            return None
        bound = {name: {"path": name + ".json", "sha256": hashlib.sha256(_bound_bytes(project, name + ".json")).hexdigest()}
                 for name in ("preflight", "normalization")}
        return {"schema": REJECTED_SCHEMA, "session_id": session_id,
                "quality": {"path": "quality.json", "sha256": hashlib.sha256(stored).hexdigest()},
                "frame_diagnostics": dict(binding), "source_trc": source_trc, "calibration": calibration,
                "bound_inputs": bound, "reasons": list(errors), "usable_for_measurement": False}
    except Exception:  # noqa: BLE001  any unavailable or contradictory binding publishes nothing
        return None


def validate_rejected_triangulation(project: Path, *, session=None) -> dict:
    """Read-only review of published rejected triangulation evidence; never measurement evidence.

    run.json is revalidated structurally (it cannot carry its own digest); every other
    advertised file is re-read with bounded, non-link reads and compared with its bound digest.
    """
    from pipeline_quality import verify_frame_diagnostics
    project = _checked_project(project, "REJECTED_EVIDENCE_UNVERIFIED")
    session = load_session(project) if session is None else session
    session_id = session["session_id"]
    identity = {"session_id": session_id, "config_sha256": hashlib.sha256(_bound_bytes(project, "Config.toml")).hexdigest(),
                "inputs": {role: entry["sha256"] for role, entry in session["captures"].items()}}

    def refuse(why):
        raise ValueError("REJECTED_EVIDENCE_UNVERIFIED: " + why)
    try:
        record = strict_json_loads(_bound_bytes(project, "run.json").decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("REJECTED_EVIDENCE_UNVERIFIED: run.json unreadable") from error
    if (not isinstance(record, dict) or record.get("schema") != "kinelab.run.v1" or record.get("coordinateSystem") != "opensim_y_up"
            or record.get("quality_policy") != QUALITY_POLICY or any(record.get(key) != value for key, value in identity.items())):
        refuse("run belongs to another session, configuration or protocol")
    from source_coverage import NATIVE_FRAME_POLICY
    if (record.get("native_frame_policy") != NATIVE_FRAME_POLICY
            or not isinstance(record.get("normalization"), dict)
            or set(record["normalization"]) != {"path", "sha256"}):
        raise ValueError("QUALITY_UNVERIFIED: captured normalization/native frame policy required")
    stages = record.get("stages")
    if (not isinstance(stages, list) or len(stages) != len(STAGES)
            or any(not isinstance(item, dict) or item.get("name") != name for item, name in zip(stages, STAGES))):
        refuse("complete ordered stages required")
    position = STAGES.index("triangulation")
    if (any(item.get("status") != "passed" or "rejected_evidence" in item for item in stages[:position])
            or any(item.get("status") == "passed" or "rejected_evidence" in item for item in stages[position + 1:])):
        refuse("stages around the rejected triangulation contradict a failed run")
    item = stages[position]
    evidence = item.get("rejected_evidence")
    if (item.get("status") != "failed" or item.get("artifacts") != [] or "quality" in item
            or not isinstance(evidence, dict) or set(evidence) != _REJECTED_KEYS or evidence.get("schema") != REJECTED_SCHEMA
            or evidence.get("session_id") != session_id or evidence.get("usable_for_measurement") is not False
            or not isinstance(evidence.get("reasons"), list) or not evidence["reasons"]):
        refuse("triangulation is not a failed stage carrying one exact rejected-evidence envelope")
    calibrations = [a for a in stages[0].get("artifacts", []) if isinstance(a, dict) and str(a.get("path", "")).endswith(".toml")]
    if evidence["calibration"] not in calibrations:
        refuse("calibration is not the recorded calibration artifact")
    try:
        report = strict_json_loads(_bound_reference(project, evidence["quality"], "quality.json").decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ValueError("REJECTED_EVIDENCE_UNVERIFIED: quality.json unreadable") from error
    if (not isinstance(report, dict) or report.get("schema") != REJECTED_QUALITY_SCHEMA
            or report.get("ok") is not False or report.get("policy") != QUALITY_POLICY
            or report.get("session_id") != session_id or report.get("errors") != evidence["reasons"]
            or report.get("frame_diagnostics") != evidence["frame_diagnostics"]):
        refuse("quality report disagrees with the rejected-evidence envelope")
    binding = evidence["frame_diagnostics"]
    if (not isinstance(binding, dict) or binding.get("source_trc") != evidence["source_trc"]
            or binding.get("calibration") != evidence["calibration"]):
        refuse("frame diagnostics are not bound to the rejected TRC and calibration")
    document = verify_frame_diagnostics(project, binding, session_id=session_id)
    _bound_reference(project, evidence["source_trc"])
    _bound_reference(project, evidence["calibration"])
    bound = evidence["bound_inputs"]
    if not isinstance(bound, dict) or set(bound) != {"preflight", "normalization"}:
        refuse("preflight and normalization digests required")
    try:
        preflight = strict_json_loads(_bound_reference(project, bound["preflight"], "preflight.json").decode("utf-8-sig"))
    except UnicodeDecodeError as error:
        raise ValueError("REJECTED_EVIDENCE_UNVERIFIED: preflight.json unreadable") from error
    if (not isinstance(preflight, dict) or preflight.get("schema") != "kinelab.preflight.v1" or preflight.get("ok") is not True
            or preflight.get("errors") or any(preflight.get(key) != value for key, value in identity.items())):
        refuse("preflight does not match this run")
    _bound_reference(project, bound["normalization"], "normalization.json")
    _verify_normalized(project, identity, record.get("normalization"))
    from source_coverage import verify_source_coverage, verify_trc_extent
    # Reuse accepted predecessor guards, including the exact native missing sentinel.
    validate_run_evidence(project, "personAssociation", session=session)
    coverage = verify_source_coverage(project, identity, record, through="personAssociation")
    if report.get("source_coverage") != coverage:
        refuse("rejected source coverage differs")
    verify_trc_extent(project, evidence["source_trc"], coverage)
    return {"status": "REJECTED", "label": REJECTED_LABEL, "usable_for_measurement": False, "session_id": session_id,
            "reasons": list(evidence["reasons"]), "frame_diagnostics": document, "evidence": evidence}


def run_stages(project: Path, start: str, stop: str) -> dict:
    project = _checked_project(project, "QUALITY_UNVERIFIED")
    if start not in STAGES or stop not in STAGES or STAGES.index(stop) < STAGES.index(start):
        raise ValueError("STAGE_INVALID: invalid stage range")
    session = load_session(project)
    config = project / "Config.toml"
    if not config.is_file():
        raise ValueError("INPUT_MISSING: Config.toml")
    identity = {"session_id": session["session_id"], "config_sha256": sha256_file(config),
                "inputs": {role: entry["sha256"] for role, entry in session["captures"].items()}}
    preflight = _read_json(project / "preflight.json", "PREFLIGHT_INVALID")
    if preflight.get("schema") != "kinelab.preflight.v1" or preflight.get("ok") is not True or preflight.get("errors") or any(preflight.get(key) != value for key, value in identity.items()):
        raise ValueError("PREFLIGHT_INVALID: rerun capture preflight for these exact inputs and configuration")
    from source_coverage import NATIVE_FRAME_POLICY, reject_configured_crop
    reject_configured_crop(project)
    normalization = _verify_normalized(project, identity)
    record = {"schema": "kinelab.run.v1", "coordinateSystem": "opensim_y_up", "quality_policy": QUALITY_POLICY, **identity,
              "normalization": normalization, "native_frame_policy": dict(NATIVE_FRAME_POLICY),
        "native_triangulation_policy": {"interpolation": "none", "fill_large_gaps_with": "nan"},
              "stages": [{"name": stage, "status": "not-run", "artifacts": []} for stage in STAGES]}
    first, last = STAGES.index(start), STAGES.index(stop)
    if first:
        previous = validate_run_evidence(project, STAGES[first - 1], session=session)["run"]
        prior = previous["stages"]
        for index in range(first):
            record["stages"][index] = prior[index]
    lock = project / "run.lock"
    try:
        with lock.open("x", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
    except FileExistsError as error:
        raise ValueError("RUN_BUSY: run.lock exists; inspect the previous process before removing it") from error
    try:
        for index in range(first, last + 1):
            stage = STAGES[index]
            item = record["stages"][index]
            rejected = fresh = None
            before = _artifacts(project, stage)
            log_mark = _log_mark(project)
            item.update(status="running", started_at=datetime.now(UTC).isoformat())
            _write_run(project, record)
            try:
                print("STAGE_START=" + stage, flush=True)
                _invoke_stage(stage, project)
                log_window = _log_window(project, log_mark)
                load_session(project)
                if sha256_file(config) != identity["config_sha256"]:
                    raise ValueError("INPUT_CHANGED: configuration changed during processing")
                _verify_normalized(project, identity, record["normalization"])
                after = _artifacts(project, stage)
                fresh = {path: info for path, info in after.items() if before.get(path) != info}
                if not fresh or any((project / path).stat().st_size == 0 for path in fresh):
                    raise ValueError("ARTIFACT_MISMATCH: no fresh nonempty output for " + stage)
                if set(fresh) != set(after):
                    raise ValueError("ARTIFACT_MISMATCH: mixed fresh/stale outputs; preserve old results and rerun in a clean session")
                _validate_artifacts(project, stage, fresh)
                quality = _validate_stage_quality(stage, project, session, record, sorted(fresh), log_window)
                if not isinstance(quality, dict) or quality.get("ok") is not True:
                    rejected = quality if stage == "triangulation" else None
                    raise ValueError("QUALITY_REJECTED: " + stage + ": " + str(quality.get("errors", "missing measured evidence") if isinstance(quality, dict) else "invalid quality report"))
                item.update(status="passed", artifacts=[{"path": path, "sha256": info[0]} for path, info in sorted(fresh.items())], quality=quality)
                print("STAGE_OK=" + stage, flush=True)
            except BaseException as error:
                item.update(status="failed", error=type(error).__name__ + ": " + str(error))
                evidence = _rejected_evidence(project, session, record, rejected, fresh) if rejected is not None and isinstance(error, ValueError) else None
                if evidence is not None:
                    item["rejected_evidence"] = evidence
                _write_run(project, record)
                raise
            item["completed_at"] = datetime.now(UTC).isoformat()
            _write_run(project, record)
    finally:
        lock.unlink(missing_ok=True)
    print("POSE2SIM_PIPELINE_COMPLETE", flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parent / "projects/kinelab-dualcam")
    parser.add_argument("--start", choices=STAGES, default=STAGES[0])
    parser.add_argument("--stop", choices=STAGES, default=STAGES[-1])
    args = parser.parse_args()
    try:
        run_stages(args.project, args.start, args.stop)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
