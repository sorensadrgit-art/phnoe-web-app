"""Run local Pose2Sim stages only on validated, session-bound inputs."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path

from session_contract import load_session, sha256_file

STAGES = ("calibration", "poseEstimation", "synchronization", "personAssociation", "triangulation", "filtering", "markerAugmentation", "kinematics")
OUTPUTS = {
    "calibration": ("calibration/*.toml",), "poseEstimation": ("pose/**/*.json",),
    "synchronization": ("pose-sync/**/*.json",), "personAssociation": ("pose-associated/**/*.json",),
    "triangulation": ("pose-3d/*.trc",), "filtering": ("pose-3d/*filt*.trc",),
    "markerAugmentation": ("pose-3d/*LSTM*.trc",), "kinematics": ("kinematics/*.mot",),
}


def _read_json(path, code):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("expected an object")
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


def _verify_normalized(project, identity):
    from normalize_capture import ROLES
    normalized = _read_json(project / "normalization.json", "PREFLIGHT_INVALID")
    if normalized.get("schema") != "kinelab.normalization.v1" or any(normalized.get(key) != value for key, value in identity.items()):
        raise ValueError("INPUT_CHANGED: normalized data belongs to different session/configuration")
    outputs = normalized.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != set(ROLES):
        raise ValueError("INPUT_CHANGED: incomplete normalized output bindings")
    for role, relative in ROLES.items():
        item = outputs[role]
        path = (project / relative).resolve()
        if not isinstance(item, dict) or item.get("path") != relative or not path.is_relative_to(project) or not path.is_file() or sha256_file(path) != item.get("sha256"):
            raise ValueError("INPUT_CHANGED: normalized output changed for " + role)


def _validate_artifacts(project, stage, artifacts):
    from export_motion import parse_trc, parse_mot
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
    from Pose2Sim import Pose2Sim
    config = {"project": {"project_dir": str(project)}}
    if stage == "triangulation":
        config["triangulation"] = {"interpolation": "none", "fill_large_gaps_with": "nan"}
    getattr(Pose2Sim, stage)(config=config)


def _validate_stage_quality(stage, project, session):
    if stage not in ("calibration", "synchronization", "triangulation"):
        return {"ok": True}
    from pipeline_quality import validate_calibration, validate_sync, validate_reconstruction
    if stage == "calibration":
        return validate_calibration(project, session)
    if stage == "synchronization":
        return validate_sync(project, session, _read_json(project / "sync-observations.json", "SYNC_UNCERTAIN"))
    return validate_reconstruction(project, session)


def run_stages(project: Path, start: str, stop: str) -> dict:
    project = Path(project).resolve()
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
    _verify_normalized(project, identity)
    record = {"schema": "kinelab.run.v1", "coordinateSystem": "opensim_y_up", **identity,
              "native_triangulation_policy": {"interpolation": "none", "fill_large_gaps_with": "nan"},
              "stages": [{"name": stage, "status": "not-run", "artifacts": []} for stage in STAGES]}
    first, last = STAGES.index(start), STAGES.index(stop)
    if first:
        previous = _read_json(project / "run.json", "ARTIFACT_MISMATCH")
        if previous.get("schema") != record["schema"] or any(previous.get(key) != value for key, value in identity.items()):
            raise ValueError("ARTIFACT_MISMATCH: prior run belongs to different inputs")
        prior = previous.get("stages")
        if not isinstance(prior, list) or len(prior) != len(STAGES):
            raise ValueError("ARTIFACT_MISMATCH: invalid prior stages")
        for index in range(first):
            item = prior[index]
            if item.get("name") != STAGES[index] or item.get("status") != "passed" or not item.get("artifacts"):
                raise ValueError("ARTIFACT_MISMATCH: missing validated prior stage " + STAGES[index])
            for artifact in item["artifacts"]:
                relative = Path(artifact.get("path", "")); path = (project / relative).resolve()
                if relative.is_absolute() or not path.is_relative_to(project) or not path.is_file() or sha256_file(path) != artifact.get("sha256"):
                    raise ValueError("ARTIFACT_MISMATCH: changed prior output")
            if set(_artifacts(project, STAGES[index])) != {artifact["path"] for artifact in item["artifacts"]}:
                raise ValueError("ARTIFACT_MISMATCH: unrecorded prior output; use a clean session or restore its recorded inventory")
            record["stages"][index] = item
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
            before = _artifacts(project, stage)
            item.update(status="running", started_at=datetime.now(timezone.utc).isoformat())
            _write_run(project, record)
            try:
                print("STAGE_START=" + stage, flush=True)
                _invoke_stage(stage, project)
                load_session(project)
                if sha256_file(config) != identity["config_sha256"]:
                    raise ValueError("INPUT_CHANGED: configuration changed during processing")
                _verify_normalized(project, identity)
                after = _artifacts(project, stage)
                fresh = {path: info for path, info in after.items() if before.get(path) != info}
                if not fresh or any((project / path).stat().st_size == 0 for path in fresh):
                    raise ValueError("ARTIFACT_MISMATCH: no fresh nonempty output for " + stage)
                if set(fresh) != set(after):
                    raise ValueError("ARTIFACT_MISMATCH: mixed fresh/stale outputs; preserve old results and rerun in a clean session")
                _validate_artifacts(project, stage, fresh)
                quality = _validate_stage_quality(stage, project, session)
                if not isinstance(quality, dict) or quality.get("ok") is not True:
                    raise ValueError("QUALITY_REJECTED: " + stage + ": " + str(quality.get("errors", "missing measured evidence") if isinstance(quality, dict) else "invalid quality report"))
                item.update(status="passed", artifacts=[{"path": path, "sha256": info[0]} for path, info in sorted(fresh.items())], quality=quality)
                print("STAGE_OK=" + stage, flush=True)
            except BaseException as error:
                item.update(status="failed", error=type(error).__name__ + ": " + str(error))
                _write_run(project, record)
                raise
            item["completed_at"] = datetime.now(timezone.utc).isoformat()
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
