"""Independent human-observed two-camera synchronization cue evidence.

The operator marks the same visible start and end cues in both *normalized*
videos (zero-based frames). The native Pose2Sim sync stage must independently
confirm the selected reference and offset before the data can pass its gate.
Creating this file alone NEVER establishes synchronized reconstruction quality.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from session_contract import load_session
from take_acceptance import TakeAcceptanceError, checked_path
from workflow_controller import WorkflowBlocked, WorkflowController


class SyncEvidenceError(ValueError):
    """Refuse missing, stale, fabricated, or unbounded synchronization input."""


CAMERAS = ("cam01", "cam02")
MIN_SEPARATION_FRAMES = 30  # Separate start/end events by at least one second.


def _checked_project(project: Path) -> Path:
    try:
        return checked_path(project).resolve()
    except TakeAcceptanceError as error:
        raise SyncEvidenceError("Project path must be a plain non-link") from error


def normalized_videos(project: Path) -> tuple[dict, dict]:
    """Return registered identity and exact normalized-video metadata."""
    project = _checked_project(project)
    try:
        workflow = WorkflowController(project)
        workflow._verify_preflight()
        session = load_session(project)
        if session.get("kind") != "real":
            raise SyncEvidenceError("Registered REAL camera data is required")
        if (project / "SAMPLE-PROVENANCE.json").exists():
            raise SyncEvidenceError("test-only mixed-source recordings cannot yield sync evidence")
        data = json.loads((project / "normalization.json").read_text(encoding="utf-8-sig"))
        videos = {}
        for camera in CAMERAS:
            role = camera + "_trial"
            meta = data.get("outputs", {}).get(role)
            if not isinstance(meta, dict):
                raise SyncEvidenceError("Missing normalized trial for " + camera)
            relative = Path(meta.get("path", ""))
            if relative.as_posix() != f"videos/{camera}.mp4":
                raise SyncEvidenceError("Expected canonical normalized trial path for " + camera)
            if meta.get("width") != 1280 or meta.get("height") != 720 or str(meta.get("fps")) != "30/1":
                raise SyncEvidenceError("Normalized trial must be 1280x720 CFR 30fps")
            n = meta.get("frame_count")
            ts = meta.get("timestamps")
            if type(n) is not int or n < 2 or n > 300000 or not isinstance(ts, list) or len(ts) != n:
                raise SyncEvidenceError("Invalid normalized frame count/timestamps for " + camera)
            if any(type(t) not in (int, float) for t in ts):
                raise SyncEvidenceError("Invalid timestamp representation")
            # Timestamp/geometry already originate from FFmpeg normalized preflight;
            # still verify the serialized frame indices are consistent with 30fps.
            if abs(ts[0]) > .001 or any(abs(float(t) - i / 30) > .002 for i, t in enumerate(ts)):
                raise SyncEvidenceError("Normalized video timestamp mapping is not CFR 30fps")
            file = (project / relative).resolve()
            if not file.is_file() or not file.is_relative_to(project):
                raise SyncEvidenceError("Normalized video escaped or is missing")
            videos[camera] = {"path": file, "frames": n, "timestamps": ts}
        return session, videos
    except (WorkflowBlocked, OSError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, SyncEvidenceError):
            raise
        raise SyncEvidenceError("Registered/normalized video evidence missing or changed: " + str(error)) from error


def suggested_reference(project: Path) -> str:
    """Suggest shorter video; Pose2Sim's native reference remains authoritative."""
    _, videos = normalized_videos(project)
    return min(CAMERAS, key=lambda camera: videos[camera]["frames"])


def prepare_sync(project: Path, cues: dict, *, reference: str, operator_confirmed: bool) -> dict:
    """Compute offsets/residuals from four independently marked visible cues."""
    session, videos = normalized_videos(project)
    if operator_confirmed is not True:
        raise SyncEvidenceError("Explicit operator confirmation of both visible cues is required")
    if reference not in CAMERAS:
        raise SyncEvidenceError("Invalid camera reference; choose cam01 or cam02")
    if not isinstance(cues, dict) or set(cues) != set(CAMERAS):
        raise SyncEvidenceError("All four cue frames must be marked by the operator")
    parsed = {}
    for camera in CAMERAS:
        marks = cues[camera]
        if not isinstance(marks, dict) or set(marks) != {"start", "end"}:
            raise SyncEvidenceError("All four start/end cue observations must be present")
        start, end = marks["start"], marks["end"]
        if any(type(v) is not int or v < 0 for v in (start, end)):
            raise SyncEvidenceError("Cue frames must be nonnegative integer normalized frame indices")
        if end >= videos[camera]["frames"] or start >= videos[camera]["frames"]:
            raise SyncEvidenceError("Cue frame is outside the normalized video")
        if end - start < MIN_SEPARATION_FRAMES:
            raise SyncEvidenceError("Start and end cues must be separate events at least one second apart")
        parsed[camera] = {"start": start, "end": end}

    other = next(camera for camera in CAMERAS if camera != reference)
    sync_start = parsed[reference]["start"]
    sync_end = parsed[reference]["end"]
    offset = parsed[other]["start"] - sync_start
    drift = (parsed[other]["end"] - sync_end) - offset
    if abs(drift) > 1:
        raise SyncEvidenceError(f"Measured start/end cue drift exceeds one frame: {drift:+d} frames")
    cameras = {
        reference: {"offset_frames": 0, "start_residual_frames": 0, "end_residual_frames": 0},
        other: {"offset_frames": offset, "start_residual_frames": 0, "end_residual_frames": drift},
    }
    pairs = [
        {
            "camera": camera,
            "synchronized_frame_index": parsed[reference][event],
            "source_frame_index": parsed[camera][event],
        }
        for camera in CAMERAS for event in ("start", "end")
    ]
    return {
        "session_id": session["session_id"],
        "fps": 30,
        "reference": reference,
        "inputs": {role: item["sha256"] for role, item in session["captures"].items()},
        "cameras": cameras,
        "source_frame_pairs": pairs,
        "measurement_source": "operator_marked_normalized_video_frames",
        "observed_cues": parsed,
        "status": "pending_native_pose2sim_validation",
        "native_sync_verified": False,
        "notes": [
            "Reference and offset calculated from observed video cue pairs, not from camera wall clocks.",
            "Reference-camera zero offset and first-pair zero residual are mathematical definitions, not independent accuracy claims.",
            "Only a later Pose2Sim native synchronization/quality stage can confirm reference and offset.",
        ],
        "recorded_utc": datetime.now(UTC).isoformat(),
    }


def save_sync(project: Path, cues: dict, *, reference: str, operator_confirmed: bool) -> Path:
    """Publish one complete cue manifest with no overwrite and no source changes."""
    project = _checked_project(project)
    output = project / "sync-observations.json"
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Sync evidence already exists and must not be overwritten: {output}")
    record = prepare_sync(project, cues, reference=reference,
                          operator_confirmed=operator_confirmed)
    temporary = project / (".sync-observations." + uuid4().hex + ".partial")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        # Recheck all inputs and preflight. If the session changed, never publish.
        check = prepare_sync(project, cues, reference=reference, operator_confirmed=True)
        if check["inputs"] != record["inputs"]:
            raise SyncEvidenceError("Session sources changed while cue observations were prepared")
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output
