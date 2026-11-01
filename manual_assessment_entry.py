"""Guided, explicitly declared TEST_ONLY reference entry over existing producers.

The audit is the commit authority. Retained files without a matching audited entry
are not receipts. This module neither authenticates a reviewer nor measures or
validates physical/clinical accuracy, and never publishes a report.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import NoReturn

import manual_assessment as manual
import session_metadata_revision as metadata
import take_acceptance as takes
from gait_events import make_manual_reference, orient_event_candidates, propose_extrema, score_manual_reference
from session_contract import strict_json_loads
from session_index import SessionIndex
from squat_events import analyze_squats, compare_manual_reps, make_manual_rep_reference

CONTEXT_SCHEMA = "kinelab.manual-assessment-context.v1"
RECEIPT_SCHEMA = "kinelab.manual-assessment-entry-receipt.v1"
EVENT = "MANUAL_ASSESSMENT_ENTRY_PUBLISHED"
JSON_LIMIT = 4 * 1024 * 1024
TOTAL_LIMIT = 8 * 1024 * 1024
ENTRY_LIMIT = 512
FIELDS = {"operation_id", "context_sha256", "metadata_context_sha256", "input_id", "source_sha256",
          "reviewer", "annotation_origin", "labels", "tolerance_frames", "confirm"}


class ManualAssessmentEntryError(ValueError):
    """Public, relative-path-free business refusal."""


def _fail(code: str) -> NoReturn:
    raise ManualAssessmentEntryError("MANUAL_ASSESSMENT_" + code)


def _raw(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_raw(value)).hexdigest()


def _document(path: Path, *, limit: int = JSON_LIMIT) -> tuple[dict, str, tuple]:
    before = takes.checked_path(path).stat(follow_symlinks=False)
    raw, digest = metadata._read_file(path, limit=limit)
    after = takes.checked_path(path).stat(follow_symlinks=False)
    identity = (*metadata._identity(before), before.st_ctime_ns)
    if identity != (*metadata._identity(after), after.st_ctime_ns):
        _fail("UNAVAILABLE")
    value = strict_json_loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        _fail("UNAVAILABLE")
    return value, digest, identity


def _request(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != FIELDS:
        _fail("INVALID")
    try:
        if len(_raw(value)) > 65536:
            _fail("INVALID")
    except (TypeError, ValueError, OverflowError) as error:
        raise ManualAssessmentEntryError("MANUAL_ASSESSMENT_INVALID") from error
    for name, length in (("operation_id", 32), ("context_sha256", 64), ("metadata_context_sha256", 64),
                         ("input_id", 64), ("source_sha256", 64)):
        if not isinstance(value[name], str) or re.fullmatch("[0-9a-f]{" + str(length) + "}", value[name]) is None:
            _fail("INVALID")
    reviewer = value["reviewer"]
    if (not isinstance(reviewer, str) or not 2 <= len(reviewer.strip()) <= 90
            or reviewer != reviewer.strip() or any(ord(char) < 32 for char in reviewer)
            or value["confirm"] is not True or value["annotation_origin"] != "human_observed_video_frames"
            or type(value["tolerance_frames"]) is not int or not 0 <= value["tolerance_frames"] <= 15
            or not isinstance(value["labels"], list) or not 1 <= len(value["labels"]) <= 256):
        _fail("INVALID")
    # Copy through canonical JSON, retaining exact request semantics for replay.
    return strict_json_loads(_raw(value).decode("utf-8"))


def _project(index: SessionIndex, session_id: str) -> Path:
    if not isinstance(session_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", session_id) is None:
        _fail("UNAVAILABLE")
    project = takes.local_path(index.projects_root, session_id)
    if not project.is_dir():
        _fail("UNAVAILABLE")
    return project


def _no_report(index: SessionIndex, session_id: str) -> None:
    if index.conn.execute("SELECT 1 FROM audit_events WHERE session_id=? AND event_type='REPORT_PUBLISHED' LIMIT 1",
                          (session_id,)).fetchone() is not None:
        _fail("REPORT_IMMUTABLE")


def _input_sets(project: Path, session: dict) -> list[dict]:
    directory = takes.local_path(project, "assessment-inputs")
    if not directory.is_dir():
        _fail("UNAVAILABLE")
    children: list[Path] = []
    with os.scandir(directory) as scan:
        for entry in scan:
            if len(children) >= 16:
                _fail("UNAVAILABLE")
            child = takes.local_path(directory, entry.name)
            if not child.is_dir():
                _fail("UNAVAILABLE")
            children.append(child)
    total = 0
    result = []
    for child in sorted(children):
        with os.scandir(child) as scan:
            names: list[str] = []
            for entry in scan:
                if len(names) >= 2:
                    _fail("UNAVAILABLE")
                names.append(entry.name)
        if set(names) != {"trajectory.json", "candidates.json"}:
            _fail("UNAVAILABLE")
        documents, bindings = {}, {}
        for name in ("trajectory", "candidates"):
            path = takes.local_path(child, name + ".json")
            file_size = path.stat(follow_symlinks=False).st_size
            total += file_size
            if total > TOTAL_LIMIT:
                _fail("UNAVAILABLE")
            document, digest, identity = _document(path)
            documents[name] = document
            bindings[name] = {"path": path.relative_to(project).as_posix(), "sha256": digest,
                              "identity": identity}
        candidates, trajectory = documents["candidates"], documents["trajectory"]
        role = candidates.get("role")
        source = session["captures"].get(role)
        size = candidates.get("image_size")
        if (not isinstance(role, str) or role not in ("cam01_trial", "cam02_trial") or not isinstance(source, dict)
                or candidates.get("source_sha256") != source["sha256"]
                or not isinstance(size, list) or len(size) != 2
                or any(type(number) is not int or not 80 <= number <= 16384 for number in size)):
            _fail("UNAVAILABLE")
        if candidates.get("schema") == "kinelab.2d-gait-candidates.v1":
            screen_forward = candidates.get("screen_forward")
            if not isinstance(screen_forward, str):
                _fail("UNAVAILABLE")
            kind = "gait"
            reproduced = orient_event_candidates(propose_extrema(
                trajectory, role, source["sha256"], image_width=size[0], image_height=size[1]),
                screen_forward=screen_forward)
            assumptions = {"screen_forward": screen_forward}
        elif candidates.get("schema") == "kinelab.2d-squat-candidates.v1":
            kind = "squat"
            if (candidates.get("activity_assumption") != "operator_confirmed_squat"
                    or candidates.get("camera_view_assumption") != "side"):
                _fail("UNAVAILABLE")
            reproduced = analyze_squats(trajectory, role, source["sha256"], camera_view="side",
                                       activity_confirmed=True, image_width=size[0], image_height=size[1])
            assumptions = {"activity": "operator_confirmed_squat", "camera_view": "side"}
        else:
            _fail("UNAVAILABLE")
        if _raw(reproduced) != _raw(candidates) or type(candidates.get("observed_frames")) is not int:
            _fail("UNAVAILABLE")
        public = {"input_id": _digest(bindings), "kind": kind, "source_role": role,
                  "source_sha256": source["sha256"], "frames": candidates["observed_frames"],
                  "trajectory_sha256": bindings["trajectory"]["sha256"],
                  "candidates_sha256": bindings["candidates"]["sha256"],
                  "image_size": size, "assumptions": assumptions}
        result.append({"public": public, "bindings": bindings, "candidates": candidates})
    if not result:
        _fail("UNAVAILABLE")
    return result


def _reference(item: dict, request: dict) -> dict:
    kind, candidates = item["public"]["kind"], item["candidates"]
    fields = ({"frame_index", "side", "event_type"} if kind == "gait"
              else {"start_frame", "bottom_frame", "end_frame"})
    labels = request["labels"]
    if len(labels) > (256 if kind == "gait" else 128) or any(
            not isinstance(label, dict) or set(label) != fields for label in labels):
        _fail("INVALID")
    try:
        if kind == "gait":
            reference = make_manual_reference(candidates, labels, reviewer=request["reviewer"], confirmed=True)
            score_manual_reference(candidates, reference, tolerance_frames=request["tolerance_frames"])
        else:
            reference = make_manual_rep_reference(candidates, labels, reviewer=request["reviewer"], confirmed=True)
            compare_manual_reps(candidates, reference, tolerance_frames=request["tolerance_frames"])
    except (ValueError, TypeError, KeyError) as error:
        raise ManualAssessmentEntryError("MANUAL_ASSESSMENT_INVALID") from error
    return reference


def _events(index: SessionIndex, session_id: str) -> dict[str, dict]:
    index.verify_audit()
    records: dict[str, dict] = {}
    rows = index.conn.execute("SELECT details_json FROM audit_events WHERE session_id=? AND event_type=? ORDER BY id",
                              (session_id, EVENT))
    for row in rows:
        if len(records) >= ENTRY_LIMIT or len(row[0].encode("utf-8")) > 131072:
            _fail("UNAVAILABLE")
        record = strict_json_loads(row[0])
        if not isinstance(record, dict) or set(record) != {"request", "receipt"}:
            _fail("UNAVAILABLE")
        request = _request(record["request"])
        operation = request["operation_id"]
        if operation in records:
            _fail("UNAVAILABLE")
        records[operation] = record
    return records


def _verify_entry(project: Path, session_id: str, record: dict, session: dict) -> dict:
    request, receipt = record["request"], record["receipt"]
    operation = request["operation_id"]
    relative = f"exports/manual-entry-{operation}.manual-assessment.json"
    document, digest, _ = _document(takes.local_path(project, relative))
    expected = {"schema": RECEIPT_SCHEMA, "session_id": session_id, "operation_id": operation,
                "metadata_context_sha256": request["metadata_context_sha256"],
                "descriptor": {"path": relative, "sha256": digest},
                "test_only": True, "clinical_accuracy_validated": False}
    if receipt != expected:
        _fail("UNAVAILABLE")
    passport = {"session_id": session_id, "sources": {role: {
        "sha256": source["sha256"], "observed_sha256": source["sha256"], "integrity_state": "unchanged"}
        for role, source in session["captures"].items()}}
    manual.validate_manual_assessment(project, takes.local_path(project, relative), passport)
    _generated_provenance(project, session, document["inputs"]["config"]["sha256"])
    reference_path = f"assessment-entries/entry-{operation}/reference.json"
    if document["inputs"]["reference"]["path"] != reference_path:
        _fail("UNAVAILABLE")
    reference, _, _ = _document(takes.local_path(project, reference_path))
    candidates_path = document["inputs"]["candidates"]["path"]
    candidates, _, _ = _document(takes.local_path(project, candidates_path))
    expected_reference = _reference({"public": {"kind": document["kind"]}, "candidates": candidates}, request)
    expected_reference.pop("recorded_at_utc")
    observed = dict(reference)
    observed.pop("recorded_at_utc", None)
    if (_raw(observed) != _raw(expected_reference) or document["source"]["sha256"] != request["source_sha256"]
            or document["tolerance_frames"] != request["tolerance_frames"]):
        _fail("UNAVAILABLE")
    return receipt


def _generated_provenance(project: Path, session: dict, config_sha256: str) -> dict | None:
    """Demo declarations remain generated; their hashes prove consistency only."""
    if session.get("kind") == "real":
        return None
    if session.get("kind") != "demo" or not session["session_id"].startswith("TEST_ONLY-"):
        _fail("UNAVAILABLE")
    relative = "generated-fixture-provenance.json"
    value, digest, _ = _document(takes.local_path(project, relative), limit=16384)
    producers = value.get("producers_sha256")
    expected = {
        "schema": "kinelab.generated-assessment-fixture.v1", "session_id": session["session_id"],
        "kind": "demo", "test_only": True, "source_video_decoded": False,
        "human_observation": "NOT_PERFORMED", "native_compute": "NOT_PERFORMED",
        "physical_accuracy": "UNVERIFIED", "clinical_validation": "UNVERIFIED",
        "captures_sha256": {role: source["sha256"] for role, source in session["captures"].items()},
        "producers_sha256": producers,
    }
    if (value != expected or value.get("test_only") is not True
            or value.get("source_video_decoded") is not False or not isinstance(producers, dict)
            or set(producers) != {"tools/verify_report_browser.py", "tests/native_evidence_fixture.py",
                                 "tests/test_manual_assessment_provenance.py", "tests/test_squat_events.py"}
            or any(not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None
                   for item in producers.values())):
        _fail("UNAVAILABLE")
    raw, observed_config = metadata._read_file(takes.local_path(project, "Config.toml"), limit=JSON_LIMIT)
    prefix = b"# kinelab-generated-provenance-sha256="
    if (observed_config != config_sha256
            or [line for line in raw.splitlines() if line.startswith(prefix)] != [prefix + digest.encode("ascii")]):
        _fail("UNAVAILABLE")
    return {"path": relative, "sha256": digest}


def _context(index: SessionIndex, session_id: str, project: Path) -> tuple[dict, list[dict], dict]:
    takes.require_no_pending(project)
    state = metadata.read_metadata_state(index, session_id)
    if state["status"] != "AVAILABLE":
        _fail("UNAVAILABLE")
    for relative in manual.CONTEXT_INPUTS.values():
        metadata._read_file(takes.local_path(project, relative), limit=JSON_LIMIT)
    inputs, dependencies, session = manual._context(project)
    if state["origin"]["sha256"] != inputs["session"]["sha256"]:
        _fail("UNAVAILABLE")
    generated = _generated_provenance(project, session, inputs["config"]["sha256"])
    if generated is not None:
        dependencies[generated["path"]] = generated["sha256"]
    items = _input_sets(project, session)
    public = {"schema": CONTEXT_SCHEMA, "status": "AVAILABLE", "session_id": session_id,
              "metadata_context_sha256": state["context_sha256"], "origin_sha256": inputs["session"]["sha256"],
              "run_sha256": inputs["run"]["sha256"], "test_only": True, "clinical_accuracy_validated": False,
              "input_sets": [item["public"] for item in items]}
    identities = {}
    for relative in dependencies:
        observed = takes.local_path(project, relative).stat(follow_symlinks=False)
        identities[relative] = (*metadata._identity(observed), observed.st_ctime_ns)
    public["context_sha256"] = _digest({"context": public, "dependencies": dependencies,
                                        "identities": identities})
    public["assessments"] = []
    public["unavailable_assessments"] = []
    for record in _events(index, session_id).values():
        receipt = _verify_entry(project, session_id, record, session)
        if receipt["metadata_context_sha256"] == state["context_sha256"]:
            public["assessments"].append(receipt)
        else:
            public["unavailable_assessments"].append({"operation_id": receipt["operation_id"],
                                                       "reason": "METADATA_CONTEXT_CHANGED"})
    return public, items, session


def _selected(context: dict, items: list[dict], request: dict) -> dict:
    selected = next((item for item in items if item["public"]["input_id"] == request["input_id"]), None)
    if (context["context_sha256"] != request["context_sha256"]
            or context["metadata_context_sha256"] != request["metadata_context_sha256"] or selected is None
            or selected["public"]["source_sha256"] != request["source_sha256"]):
        _fail("CONTEXT_CHANGED")
    return selected


def _new_paths(project: Path, operation: str) -> tuple[Path, Path]:
    reference = takes.local_path(project, f"assessment-entries/entry-{operation}/reference.json")
    descriptor = takes.local_path(project, f"exports/manual-entry-{operation}.manual-assessment.json")
    revision = takes.local_path(project, f"exports/manual-entry-{operation}.manual-assessment-inputs")
    if reference.parent.exists() or descriptor.exists() or revision.exists():
        _fail("OPERATION_CONFLICT")
    for parent in (reference.parent.parent, descriptor.parent):
        if parent.exists() and not parent.is_dir():
            _fail("UNAVAILABLE")
    return reference, descriptor


def _translate(error: Exception) -> ManualAssessmentEntryError:
    if isinstance(error, ManualAssessmentEntryError):
        return error
    code = "BUSY" if isinstance(error, takes.TakeAcceptanceError) else "UNAVAILABLE"
    return ManualAssessmentEntryError("MANUAL_ASSESSMENT_" + code)


def manual_assessment_context(index: SessionIndex, session_id: str) -> dict:
    """Read only: no directory, administrative anchor, reference or audit writes."""
    try:
        project = _project(index, session_id)
        with index.read_snapshot():
            return _context(index, session_id, project)[0]
    except (ValueError, OSError, KeyError, TypeError, sqlite3.DatabaseError) as error:
        raise _translate(error) from error


def publish_manual_assessment_entry(index: SessionIndex, session_id: str, request: dict) -> dict:
    """Validate before writes; one session lease and one serial audit transaction.

    Service callers must independently fence active capture/jobs under their mutex.
    Interrupted/uncommitted output is retained, never promoted by path existence.
    """
    try:
        request = _request(request)
        project = _project(index, session_id)
        with index.transaction():
            records = _events(index, session_id)
            operation = request["operation_id"]
            if operation in records:
                record = records[operation]
                if _raw(record["request"]) != _raw(request):
                    _fail("OPERATION_CONFLICT")
                # Replay precedes current-context CAS, but never trusts files alone.
                _, _, session = manual._context(project)
                return _verify_entry(project, session_id, record, session)
            _no_report(index, session_id)
            if len(records) >= ENTRY_LIMIT:
                _fail("UNAVAILABLE")
            context, items, _ = _context(index, session_id, project)
            item = _selected(context, items, request)
            _reference(item, request)
            _new_paths(project, operation)
            with takes.acceptance_lease(project):
                _no_report(index, session_id)
                context, items, _ = _context(index, session_id, project)
                item = _selected(context, items, request)
                reference = _reference(item, request)
                reference_path, descriptor = _new_paths(project, operation)
                reference_path.parent.mkdir(parents=True)
                reference_raw = _raw(reference)
                identity = metadata._write_new(reference_path, reference_raw)
                manual.publish_manual_assessment(
                    project, trajectory_path=item["bindings"]["trajectory"]["path"],
                    candidates_path=item["bindings"]["candidates"]["path"],
                    reference_path=reference_path.relative_to(project).as_posix(),
                    output_name="manual-entry-" + operation, tolerance_frames=request["tolerance_frames"])
                metadata._verify_new(reference_path, reference_raw, identity)
                # The new reference is outside the discovery catalog: CAS remains stable.
                current, _, session = _context(index, session_id, project)
                if current["context_sha256"] != request["context_sha256"]:
                    _fail("CONTEXT_CHANGED")
                _, descriptor_digest, _ = _document(descriptor)
                receipt = {"schema": RECEIPT_SCHEMA, "session_id": session_id, "operation_id": operation,
                           "metadata_context_sha256": request["metadata_context_sha256"],
                           "descriptor": {"path": descriptor.relative_to(project).as_posix(),
                                          "sha256": descriptor_digest},
                           "test_only": True, "clinical_accuracy_validated": False}
                record = {"request": request, "receipt": receipt}
                _verify_entry(project, session_id, record, session)
                index._append_audit(session_id, EVENT, record)
            return receipt
    except (ValueError, OSError, KeyError, TypeError, sqlite3.DatabaseError) as error:
        raise _translate(error) from error
