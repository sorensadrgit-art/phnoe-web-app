"""Additive, source-bound TEST_ONLY manual agreement artifacts.

This binds stored arithmetic to current local bytes. It does not authenticate a
reviewer, prove native derivation of 2D trajectories, or validate clinical accuracy.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

from gait_events import (
    EVIDENCE_CLASSIFICATION,
    orient_event_candidates,
    propose_extrema,
    score_manual_reference,
)
from run_pipeline import validate_run_evidence
from session_contract import load_session, sha256_file, strict_json_loads
from squat_events import analyze_squats, compare_manual_reps

SCHEMA = "kinelab.manual-assessment.v1"
BOUND_STATUS = "BOUND_TEST_ONLY_MANUAL_AGREEMENT_NOT_CLINICAL_VALIDATION"
LIMITATIONS = (
    "TEST_ONLY source-byte association and reproducible stored arithmetic only. "
    "Reviewer, confirmation and blinding fields are declarations, not authenticated identity. "
    "No proof of native trajectory derivation, independent annotation, physical accuracy or clinical validity."
)
CONTEXT_INPUTS = {
    "session": "session.json", "config": "Config.toml", "run": "run.json",
    "preflight": "preflight.json", "normalization": "normalization.json",
}
DESCRIPTOR_FIELDS = {
    "schema", "kind", "test_only", "evidence_classification", "clinical_accuracy_validated",
    "session_id", "source", "inputs", "dependencies", "run", "tolerance_frames", "score",
    "recorded_at_utc", "limitations",
}


def _require(condition, message):
    if not condition:
        raise ValueError("MANUAL_ASSESSMENT_UNAVAILABLE: " + message)


def _no_reparse(path):
    attributes = path.lstat()
    _require(not stat.S_ISLNK(attributes.st_mode)
             and not getattr(attributes, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
             "reparse points and symbolic links are refused: " + path.name)


def _root(project):
    root = Path(os.path.abspath(project))
    for path in (*reversed(root.parents), root):
        _no_reparse(path)
    _require(root.is_dir(), "selected project is not a directory")
    return root


def _component(value):
    return (bool(value) and value not in (".", "..") and not value.endswith((".", " "))
            and not any(ord(c) < 32 or c in '\\:<>"|?*' for c in value)
            and re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value, re.IGNORECASE) is None)


def _path(root, relative, *, missing=False):
    _require(isinstance(relative, str) and not relative.startswith("/")
             and all(_component(part) for part in relative.split("/")), "noncanonical relative path")
    path = root
    for part in relative.split("/"):
        path /= part
        try:
            _no_reparse(path)
        except FileNotFoundError:
            _require(missing, "missing input: " + relative)
    _require(path.is_relative_to(root), "path escaped the selected project")
    return path


def _read(root, relative):
    path = _path(root, relative)
    _require(path.is_file(), "input must be a regular file: " + relative)
    data = path.read_bytes()
    _path(root, relative)
    return {"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": data}


def _document(binding):
    value = strict_json_loads(binding["bytes"].decode("utf-8-sig"))
    _require(isinstance(value, dict), "input must contain a JSON object: " + binding["path"])
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _unchanged(root, dependencies):
    for relative, digest in dependencies.items():
        path = _path(root, relative)
        _require(path.is_file() and sha256_file(path) == digest, "current input changed: " + relative)


def _context(root):
    inputs = {name: _read(root, relative) for name, relative in CONTEXT_INPUTS.items()}
    session = _document(inputs["session"])
    run = _document(inputs["run"])
    normalized = _document(inputs["normalization"])
    dependencies = {item["path"]: item["sha256"] for item in inputs.values()}

    def dependency(relative):
        path = _path(root, relative)
        _require(path.is_file(), "missing prerequisite file")
        digest = sha256_file(path)
        _require(relative not in dependencies or dependencies[relative] == digest, "input changed during validation")
        dependencies[relative] = digest

    captures = session.get("captures")
    _require(isinstance(captures, dict), "registered captures are missing")
    for entry in captures.values():
        _require(isinstance(entry, dict), "invalid capture binding")
        dependency(entry.get("path"))
    outputs = normalized.get("outputs")
    _require(isinstance(outputs, dict), "normalized output bindings are missing")
    for entry in outputs.values():
        _require(isinstance(entry, dict), "invalid normalized binding")
        dependency(entry.get("path"))
    stages = run.get("stages")
    _require(isinstance(stages, list) and len(stages) >= 2, "ordered native stages are missing")
    for stage in stages[:2]:
        _require(isinstance(stage, dict) and isinstance(stage.get("artifacts"), list), "invalid stage binding")
        for item in stage["artifacts"]:
            _require(isinstance(item, dict), "invalid artifact binding")
            dependency(item.get("path"))
        quality = stage.get("quality")
        if isinstance(quality, dict) and isinstance(quality.get("log"), dict):
            dependency(quality["log"].get("path"))
    # Refuse links before the existing validator traverses calibration/pose globs.
    for relative in ("calibration", "pose"):
        directory = _path(root, relative)
        for current, directories, files in os.walk(directory, followlinks=False):
            for name in (*directories, *files):
                _path(root, (Path(current) / name).relative_to(root).as_posix())
    observed_session = load_session(root)
    _require(_canonical(observed_session) == _canonical(session)
             and session.get("session_id") == root.name, "registered session identity changed")
    validated = validate_run_evidence(root, "poseEstimation", session=observed_session)
    _require(_canonical(validated["run"]) == _canonical(run), "native run changed during validation")
    _unchanged(root, dependencies)
    return inputs, dependencies, session


def _prepare(root, trajectory_path, candidates_path, reference_path, tolerance_frames):
    _require(type(tolerance_frames) is int and 0 <= tolerance_frames <= 15, "explicit frame tolerance is invalid")
    inputs, dependencies, session = _context(root)
    for name, relative in (("trajectory", trajectory_path), ("candidates", candidates_path), ("reference", reference_path)):
        inputs[name] = _read(root, relative)
        _require(relative not in dependencies, "assessment inputs must be distinct from prerequisites")
        dependencies[relative] = inputs[name]["sha256"]
    trajectory, candidates, reference = (_document(inputs[name]) for name in ("trajectory", "candidates", "reference"))
    role = candidates.get("role")
    _require(role in ("cam01_trial", "cam02_trial"), "select an actual registered trial camera role")
    source = session["captures"][role]
    _require(candidates.get("source_sha256") == source["sha256"], "selected capture hash differs from candidates")
    image_size = candidates.get("image_size")
    _require(isinstance(image_size, list) and len(image_size) == 2
             and all(type(n) is int and n > 0 for n in image_size), "explicit source image size is required")
    if candidates.get("schema") == "kinelab.2d-gait-candidates.v1":
        kind = "gait"
        reproduced = orient_event_candidates(propose_extrema(
            trajectory, role, source["sha256"], image_width=image_size[0], image_height=image_size[1],
        ), screen_forward=candidates.get("screen_forward"))
        score = score_manual_reference(reproduced, reference, tolerance_frames=tolerance_frames)
    elif candidates.get("schema") == "kinelab.2d-squat-candidates.v1":
        kind = "squat"
        _require(candidates.get("activity_assumption") == "operator_confirmed_squat"
                 and candidates.get("camera_view_assumption") == "side", "explicit squat/view assumptions required")
        reproduced = analyze_squats(
            trajectory, role, source["sha256"], camera_view="side", activity_confirmed=True,
            image_width=image_size[0], image_height=image_size[1],
        )
        score = compare_manual_reps(reproduced, reference, tolerance_frames=tolerance_frames)
    else:
        raise ValueError("MANUAL_ASSESSMENT_UNAVAILABLE: unsupported candidate schema")
    _require(_canonical(reproduced) == _canonical(candidates), "candidates do not reproduce from the bound trajectory")
    _unchanged(root, dependencies)
    return inputs, dependencies, session, {"role": role, "path": source["path"], "sha256": source["sha256"]}, kind, score


def publish_manual_assessment(
    project: Path | str, *, trajectory_path: str, candidates_path: str, reference_path: str,
    output_name: str, tolerance_frames: int,
) -> Path:
    """Publish a new revision; preserve all current inputs and prior revisions.

    No default labels, identity, run, clinical score or legacy backfill is created.
    Hard-link publication is exclusive and atomic; unsupported filesystems refuse.
    Failed, uncommitted revision directories are retained for local inspection.
    """
    root = _root(project)
    _require(isinstance(output_name, str) and _component(output_name)
             and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", output_name) is not None,
             "output_name must be a safe new revision name")
    inputs, dependencies, session, source, kind, score = _prepare(
        root, trajectory_path, candidates_path, reference_path, tolerance_frames,
    )
    exports = _path(root, "exports", missing=True)
    exports.mkdir(exist_ok=True)
    revision_relative = f"exports/{output_name}.manual-assessment-inputs"
    revision = _path(root, revision_relative, missing=True)
    descriptor_relative = f"exports/{output_name}.manual-assessment.json"
    descriptor = _path(root, descriptor_relative, missing=True)
    _require(not revision.exists() and not descriptor.exists(), "revision already exists; replacement refused")
    revision.mkdir()
    bindings = {}
    for name, item in inputs.items():
        snapshot_relative = f"{revision_relative}/{name}{Path(item['path']).suffix}"
        snapshot = _path(root, snapshot_relative, missing=True)
        with snapshot.open("xb") as stream:
            stream.write(item["bytes"])
            stream.flush()
            os.fsync(stream.fileno())
        bindings[name] = {"path": item["path"], "sha256": item["sha256"],
                          "snapshot": {"path": snapshot_relative, "sha256": item["sha256"]}}
    record = {
        "schema": SCHEMA, "kind": kind, "test_only": True,
        "evidence_classification": EVIDENCE_CLASSIFICATION, "clinical_accuracy_validated": False,
        "session_id": session["session_id"], "source": source, "inputs": bindings, "dependencies": dependencies,
        "run": {"schema": "kinelab.run.v1", "through": "poseEstimation", "sha256": inputs["run"]["sha256"]},
        "tolerance_frames": tolerance_frames, "score": score,
        "recorded_at_utc": datetime.now(UTC).isoformat(), "limitations": LIMITATIONS,
    }
    staged = _path(root, f"{revision_relative}/descriptor.json", missing=True)
    with staged.open("xb") as stream:
        stream.write((json.dumps(record, indent=2, allow_nan=False) + "\n").encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    _unchanged(root, dependencies)
    for binding in bindings.values():
        _unchanged(root, {binding["snapshot"]["path"]: binding["sha256"]})
    _path(root, descriptor_relative, missing=True)
    # Atomic no-replacement commit after every input/snapshot and descriptor fsync.
    os.link(staged, descriptor, follow_symlinks=False)
    return descriptor


def validate_manual_assessment(project: Path | str, descriptor_path: Path, passport: dict) -> dict:
    """Recheck current bytes and pure producers before exposing agreement fields."""
    root = _root(project)
    relative = Path(descriptor_path).absolute().relative_to(root).as_posix()
    artifact = _read(root, relative)
    record = _document(artifact)
    _require(set(record) == DESCRIPTOR_FIELDS and record.get("schema") == SCHEMA, "unsupported descriptor contract")
    _require(record.get("test_only") is True and record.get("clinical_accuracy_validated") is False
             and record.get("evidence_classification") == EVIDENCE_CLASSIFICATION
             and record.get("limitations") == LIMITATIONS, "contradictory evidence classification")
    _require(relative.startswith("exports/") and relative.endswith(".manual-assessment.json")
             and len(relative.split("/")) == 2, "descriptor must be a committed export revision")
    bindings = record.get("inputs")
    expected_names = {*CONTEXT_INPUTS, "trajectory", "candidates", "reference"}
    _require(isinstance(bindings, dict) and set(bindings) == expected_names, "incomplete input bindings")
    for name, binding in bindings.items():
        _require(isinstance(binding, dict) and set(binding) == {"path", "sha256", "snapshot"}, "invalid input binding")
        if name in CONTEXT_INPUTS:
            _require(binding["path"] == CONTEXT_INPUTS[name], "incorrect native prerequisite path")
    inputs, dependencies, session, source, kind, score = _prepare(
        root, bindings["trajectory"]["path"], bindings["candidates"]["path"], bindings["reference"]["path"],
        record.get("tolerance_frames"),
    )
    _require(record.get("session_id") == session["session_id"] == passport.get("session_id"), "session identity differs")
    passport_sources = passport.get("sources")
    if not isinstance(passport_sources, dict):
        raise TypeError("MANUAL_ASSESSMENT_UNAVAILABLE: current passport source bindings missing")
    passport_source = passport_sources.get(source["role"])
    _require(isinstance(passport_source, dict) and passport_source.get("sha256") == source["sha256"]
             and passport_source.get("observed_sha256") == source["sha256"]
             and passport_source.get("integrity_state") == "unchanged", "current passport source differs")
    expected_run = {"schema": "kinelab.run.v1", "through": "poseEstimation", "sha256": inputs["run"]["sha256"]}
    for actual, expected in ((record.get("kind"), kind), (record.get("source"), source),
                             (record.get("run"), expected_run), (record.get("dependencies"), dependencies),
                             (record.get("score"), score)):
        _require(_canonical(actual) == _canonical(expected), "descriptor differs from current recomputed evidence")
    revision_relative = relative.removesuffix(".manual-assessment.json") + ".manual-assessment-inputs"
    for name, item in inputs.items():
        binding = bindings[name]
        snapshot = binding.get("snapshot")
        expected_snapshot = {"path": f"{revision_relative}/{name}{Path(item['path']).suffix}", "sha256": item["sha256"]}
        _require(binding["sha256"] == item["sha256"] and _canonical(snapshot) == _canonical(expected_snapshot),
                 "input/snapshot binding differs from current input")
        observed_snapshot = _read(root, expected_snapshot["path"])
        _require(observed_snapshot["bytes"] == item["bytes"], "saved snapshot bytes differ from current input")
    _unchanged(root, {**dependencies, relative: artifact["sha256"]})
    fields = ("missed_reference_count", "unscorable_reference_count", "false_candidate_count",
              "by_event_type", "phase_boundary_disagreement_count", "incomplete_attempts")
    result = {field: score[field] if score.get(field) is not None else "UNAVAILABLE" for field in fields}
    result.update(status=BOUND_STATUS, session_id=session["session_id"], source_sha256=source["sha256"],
                  candidates_sha256=inputs["candidates"]["sha256"], reference_sha256=inputs["reference"]["sha256"],
                  run_sha256=inputs["run"]["sha256"], artifact=relative, artifact_sha256=artifact["sha256"],
                  test_only=True, clinical_accuracy_validated=False, limitations=LIMITATIONS)
    return result
