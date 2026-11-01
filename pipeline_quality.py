"""Measured local calibration, synchronization, reconstruction and downstream TRC gates."""
import copy
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import tomllib
from itertools import pairwise
from pathlib import Path
from typing import TypedDict, TypeGuard

from session_contract import sha256_file, strict_json_loads

QUALITY_POLICY = "kinelab.pipeline-quality.v4"
FRAME_DIAGNOSTICS_SCHEMA = "kinelab.reconstruction-frames.v1"
FRAME_DIAGNOSTICS_MAX_BYTES = 32 * 1024 * 1024
FRAME_CAMERAS = ("cam01", "cam02")
FRAME_MARKERS = ("Hip", "RHip", "RKnee", "RAnkle", "LHip", "LKnee", "LAnkle")
FRAME_STATUSES = frozenset({"supported", "projection_non_finite", "behind_camera", "trc_point_missing",
                            "no_pose_file", "people_count_not_one", "keypoint_missing"})


class ReconstructionCriteria(TypedDict):
    views: int
    likelihood: list[float]
    reprojection_px_max: int
    coverage_min: float
    longest_gap_frames_max: int


RECONSTRUCTION_CRITERIA: ReconstructionCriteria = {"views": 2, "likelihood": [0.3, 1], "reprojection_px_max": 15,
                           "coverage_min": 0.95, "longest_gap_frames_max": 3}
_SYNC_FPS = 30
# The TRC time-serialization tolerance _aligned_trc already applies (about 3e-5 frame at 30 fps).
_TRC_TIME_TOL_S = 1e-6
_MIN_DEPTH = 1e-12
_FRAME_FILE = re.compile(r"^diagnostics/reconstruction-frames\.([0-9a-f]{64})\.json$")
_FRAME_TEXT = {"classification": "native_triangulated_unfiltered",
               "value_kind": "reconstruction estimate; research diagnostic; not measured physical truth",
               "physical_accuracy": "not validated", "clinical_validation": "UNVERIFIED",
               "camera_depth_units": "calibration translation units; physical scale UNVERIFIED",
               "frame_index_basis": "round(trc_time_s * trc_fps) = pose-associated file index; equality with decoded source video frame UNVERIFIED"}
_FRAME_KEYS = frozenset({"schema", "policy", "session_id", "source_trc", "calibration", "camera_ids", "required_markers",
                         "criteria", "frames", *_FRAME_TEXT})

def _finite(value: object) -> TypeGuard[float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return math.isfinite(value)


def _log_range(project, window):
    """Return only the log bytes written by one native invocation, plus their binding.

    window is [start, end, sha256] with the hash captured right after the native call,
    so bytes rewritten before this read are rejected rather than parsed.
    """
    path = Path(project) / "logs.txt"
    if (not isinstance(window, (list, tuple)) or len(window) != 3 or not all(type(v) is int for v in window[:2])
            or not isinstance(window[2], str) or not 0 <= window[0] < window[1] or not path.is_file()):
        raise ValueError("LOG_UNBOUND: native log byte window for this invocation required")
    with path.open("rb") as stream:
        stream.seek(window[0])
        data = stream.read(window[1] - window[0])
    if len(data) != window[1] - window[0]:
        raise ValueError("LOG_UNBOUND: native log truncated or rotated")
    if hashlib.sha256(data).hexdigest() != window[2]:
        raise ValueError("LOG_UNBOUND: native log bytes changed after the invocation window was captured")
    return data.decode("utf-8", errors="replace"), {"path": "logs.txt", "start": window[0], "end": window[1], "sha256": hashlib.sha256(data).hexdigest()}


def verify_log_binding(project, binding):
    """Later appends are allowed; truncation, rotation or changed bytes fail closed."""
    if not isinstance(binding, dict) or binding.get("path") != "logs.txt":
        raise ValueError("QUALITY_UNVERIFIED: native log binding missing")
    try:
        _, observed = _log_range(project, [binding.get("start"), binding.get("end"), binding.get("sha256")])
    except (OSError, ValueError) as error:
        raise ValueError("QUALITY_UNVERIFIED: " + str(error)) from error
    if observed != binding:
        raise ValueError("QUALITY_UNVERIFIED: native log bytes changed since validation")

def _save(project, name, report):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=project, suffix=".json", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(report, stream, indent=2, allow_nan=False)
    try:
        temporary.replace(Path(project) / name)
    finally:
        temporary.unlink(missing_ok=True)
    return report


def _calibration_file(project):
    paths = list((project / "calibration").glob("*.toml"))
    if len(paths) != 1:
        raise ValueError("CALIBRATION_INVALID: require exactly one calibration TOML in this session")
    return paths[0]


def validate_calibration(project: Path, session: dict, log_window=None) -> dict:
    project = Path(project)
    report = {"schema": "kinelab.calibration-quality.v1", "session_id": session["session_id"], "ok": False, "errors": []}
    try:
        path = _calibration_file(project)
        calibration = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        names = [key for key in calibration if key not in ("metadata", "capture_volume", "charuco", "checkerboard")]
        if set(names) != set(session["camera_ids"]):
            raise ValueError("CALIBRATION_INVALID: expected exactly cam01/cam02")
        positions = []
        for name in session["camera_ids"]:
            camera = calibration[name]
            if camera.get("name", name) != name or camera.get("size") != [1280, 720]:
                raise ValueError("CALIBRATION_INVALID: camera name or normalized image size mismatch")
            matrix = camera.get("matrix", [])
            if len(matrix) != 3 or any(not isinstance(row, list) or len(row) != 3 or not all(_finite(v) for v in row) for row in matrix):
                raise ValueError("CALIBRATION_INVALID: finite 3x3 matrix required")
            if matrix[0][0] <= 0 or matrix[1][1] <= 0 or matrix[2] != [0, 0, 1]:
                raise ValueError("CALIBRATION_INVALID: invalid intrinsic matrix")
            for key, count in (("rotation", 3), ("translation", 3)):
                if len(camera.get(key, [])) != count or not all(_finite(v) for v in camera[key]):
                    raise ValueError("CALIBRATION_INVALID: invalid " + key)
            if len(camera.get("distortions", [])) < 4 or not all(_finite(v) for v in camera["distortions"]):
                raise ValueError("CALIBRATION_INVALID: invalid distortion vector")
            import cv2
            import numpy as np
            rotation, _ = cv2.Rodrigues(np.asarray(camera["rotation"], dtype=float))
            positions.append(-rotation.T @ np.asarray(camera["translation"], dtype=float))
        if float(np.linalg.norm(positions[0] - positions[1])) <= 1e-9:
            raise ValueError("CALIBRATION_INVALID: coincident camera centers")
        log, binding = _log_range(project, log_window)
        matches = re.findall(r"Residual \(RMS\) calibration errors.*?respectively\s*(\[[^\]]+\])\s*px", log, re.DOTALL)
        if not matches:
            raise ValueError("CALIBRATION_INVALID: measured RMS residuals unavailable; metadata.error is a Pose2Sim placeholder")
        numbers = re.sub(r"np\.float(?:32|64)\(([^)]+)\)", r"\1", matches[-1])
        rms = json.loads(numbers)
        if not isinstance(rms, list) or len(rms) != 2 or not all(_finite(v) and 0 <= v <= 1.5 for v in rms):
            raise ValueError("CALIBRATION_INVALID: fitted RMS must be finite and <=1.5 px per camera")
        report.update(ok=True, policy=QUALITY_POLICY, log=binding, calibration={"path": path.relative_to(project).as_posix(), "sha256": sha256_file(path)},
                      rms_px=dict(zip(names, rms)), residual_source="Pose2Sim calibration log, not metadata.error", physical_scale="unverified until the printed board is measured")
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
    return _save(project, "calibration-quality.json", report)


def validate_sync(project: Path, session: dict, cue_observations: dict, log_window=None) -> dict:
    project = Path(project)
    report = {"schema": "kinelab.sync.v1", "session_id": session["session_id"], "ok": False, "errors": []}
    try:
        data = cue_observations
        if not isinstance(data, dict) or data.get("session_id") != session["session_id"] or data.get("reference") not in ("cam01", "cam02") or data.get("fps") != _SYNC_FPS:
            raise ValueError("SYNC_UNCERTAIN: require this session, native camera reference and 30 fps")
        cameras = data["cameras"]
        if not isinstance(cameras, dict) or set(cameras) != {"cam01", "cam02"}:
            raise ValueError("SYNC_UNCERTAIN: both camera observations required")
        for name, camera in cameras.items():
            if not isinstance(camera, dict) or type(camera.get("offset_frames")) is not int or (name == data["reference"] and camera["offset_frames"] != 0):
                raise ValueError("SYNC_UNCERTAIN: invalid offset sign/reference")
            start, end = camera.get("start_residual_frames"), camera.get("end_residual_frames")
            if not (_finite(start) and _finite(end) and abs(start) <= 1 and abs(end) <= 1
                    and abs(end - start) <= 1):
                raise ValueError("SYNC_UNCERTAIN: independent cue residual/drift exceeds one frame")
        pairs = data.get("source_frame_pairs", [])
        if not isinstance(pairs, list) or not pairs:
            raise ValueError("SYNC_UNCERTAIN: independent source/synchronized frame pairs required")
        measured: dict[str, list[tuple]] = {name: [] for name in cameras}
        for pair in pairs:
            if not isinstance(pair, dict) or pair.get("camera") not in cameras:
                raise ValueError("SYNC_UNCERTAIN: invalid camera observation")
            camera = cameras[pair["camera"]]
            source, synchronized = pair["source_frame_index"], pair["synchronized_frame_index"]
            if not all(type(v) is int and v >= 0 for v in (source, synchronized)) or abs(source - synchronized - camera["offset_frames"]) > 1:
                raise ValueError("SYNC_UNCERTAIN: source = synchronized + offset sign mismatch")
            measured[pair["camera"]].append((synchronized, source, source - synchronized - camera["offset_frames"]))
        for name, observations in measured.items():
            observations.sort()
            if len(observations) < 2 or any(right[0] <= left[0] or right[1] <= left[1] for left, right in pairwise(observations)):
                raise ValueError("SYNC_UNCERTAIN: distinct ordered start/end frame pairs required for each camera")
            start, end = observations[0][2], observations[-1][2]
            if abs(end - start) > 1 or start != cameras[name]["start_residual_frames"] or end != cameras[name]["end_residual_frames"]:
                raise ValueError("SYNC_UNCERTAIN: declared residuals disagree with observed cues or measured drift exceeds one frame")
        if (session.get("captures")
                and data.get("inputs") != {role: item["sha256"] for role, item in session["captures"].items()}):
            raise ValueError("SYNC_UNCERTAIN: cue observations are not bound to these recordings")
        log, binding = _log_range(project, log_window)
        matches = re.findall(r"Camera (cam0[12]) and (cam0[12]):\s*(-?\d+) frames offset[^\n]*correlation\s+([-\d.]+)", log)
        if not matches:
            raise ValueError("SYNC_UNCERTAIN: native Pose2Sim offset/correlation evidence missing")
        reference, other, offset, correlation = matches[-1]
        if reference != data["reference"] or reference == other or int(offset) != cameras[other]["offset_frames"] or not 0.85 <= float(correlation.rstrip(".")) <= 1:
            raise ValueError("SYNC_UNCERTAIN: independent cues disagree with native alignment or correlation is ambiguous")
        report.update(ok=True, policy=QUALITY_POLICY, log=binding, reference=reference, cameras=cameras, source_frame_pairs=pairs,
                      convention="source_frame_index = synchronized_frame_index + offset_frames", native_correlation=float(correlation.rstrip(".")))
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
    return _save(project, "sync.json", report)


def assess_reconstruction(samples: list, required_markers: list) -> dict:
    errors, markers = [], {}
    if not samples or not required_markers:
        return {"ok": False, "errors": ["RECONSTRUCTION_REJECTED: no observed samples/required markers"], "markers": {}}
    if any(not isinstance(row, dict) or type(row.get("frame")) is not int or row["frame"] < 0 for row in samples):
        return {"ok": False, "errors": ["RECONSTRUCTION_REJECTED: observation lacks a non-negative integer frame index"], "markers": {}}
    frames = sorted({row["frame"] for row in samples})
    # This interior envelope does not establish the decoded source's leading/trailing extent.
    total = frames[-1] - frames[0] + 1 if frames else 0
    for name in required_markers:
        rows = {}
        for row in samples:
            if row.get("marker") == name:
                if row["frame"] in rows:
                    return {"ok": False, "errors": ["RECONSTRUCTION_REJECTED: duplicate marker/frame observation for " + name], "markers": {}}
                rows[row["frame"]] = row
        observed, residuals, gap, longest = 0, [], 0, 0
        previous = None
        for frame in frames:
            if previous is not None:
                gap += frame - previous - 1
                longest = max(longest, gap)
            previous = frame
            row = rows.get(frame, {})
            residual = row.get("reprojection_px")
            valid = _sample_valid(row)
            if valid:
                observed += 1; residuals.append(residual); gap = 0
            else:
                gap += 1; longest = max(longest, gap)
        coverage = observed / total if total else 0
        p95 = sorted(residuals)[max(0, math.ceil(len(residuals) * .95) - 1)] if residuals else None
        markers[name] = {"observed": observed, "total": total, "coverage": coverage, "p95_reprojection_px": p95, "longest_gap_frames": longest}
        coverage_min = RECONSTRUCTION_CRITERIA["coverage_min"]
        longest_gap_max = RECONSTRUCTION_CRITERIA["longest_gap_frames_max"]
        if (not isinstance(coverage_min, (int, float))
                or not isinstance(longest_gap_max, (int, float))
                or coverage < coverage_min or longest > longest_gap_max):
            errors.append("RECONSTRUCTION_REJECTED: insufficient two-view support for " + name)
    return {"ok": not errors, "errors": errors, "markers": markers}


def _sample_valid(row):
    residual, likelihoods = row.get("reprojection_px"), row.get("likelihoods", [])
    return (row.get("views") == 2 and len(likelihoods) == 2 and all(_finite(v) and 0.3 <= v <= 1 for v in likelihoods)
            and _finite(residual) and 0 <= residual <= 15 and row.get("interpolated") is False)


def _frame_cell(cell):
    status = cell.get("status") if isinstance(cell, dict) else None
    values = [cell.get(k) if isinstance(cell, dict) else None for k in ("likelihood", "reprojection_px", "camera_depth")]
    if status not in FRAME_STATUSES or any(v is not None and not _finite(v) for v in values):
        raise ValueError("FRAME_DIAGNOSTICS_INVALID: unknown status or non-finite stored value")
    likelihood, residual, depth = values
    deep = depth is not None and depth > _MIN_DEPTH
    shape = {"supported": likelihood is not None and residual is not None and residual >= 0 and deep,
             "projection_non_finite": likelihood is not None and residual is None and deep,
             "behind_camera": likelihood is not None and residual is None and not deep,
             "trc_point_missing": residual is None and depth is None}.get(status, values == [None, None, None])
    if not shape or (likelihood is not None and not 0 <= likelihood <= 1):
        raise ValueError("FRAME_DIAGNOSTICS_INVALID: values contradict camera status " + status)
    return {"status": status, **{k: None if v is None else float(v) for k, v in zip(("likelihood", "reprojection_px", "camera_depth"), values)}}


def _frame_marker(cameras):
    if not isinstance(cameras, dict) or set(cameras) != set(FRAME_CAMERAS):
        raise ValueError("FRAME_DIAGNOSTICS_INVALID: camera set")
    cells = {name: _frame_cell(cameras[name]) for name in FRAME_CAMERAS}
    supported = [cells[n] for n in FRAME_CAMERAS if cells[n]["status"] == "supported"]
    errors = [c["reprojection_px"] for c in supported]
    sample = {"views": len(supported), "likelihoods": [c["likelihood"] for c in supported],
              "reprojection_px": max(errors) if errors else None, "interpolated": False}
    return {"valid": _sample_valid(sample), "views": len(supported), "cameras": cells}, sample


def _validate_frame_document(document):
    """Recompute every derived field; refuse contradictions in either direction."""
    # Canonical JSON comparison keeps true from passing as 1 inside the criteria literal.
    if (not isinstance(document, dict) or set(document) != _FRAME_KEYS or document.get("schema") != FRAME_DIAGNOSTICS_SCHEMA
            or document.get("policy") != QUALITY_POLICY
            or json.dumps(document.get("criteria"), sort_keys=True) != json.dumps(RECONSTRUCTION_CRITERIA, sort_keys=True)
            or document.get("camera_ids") != list(FRAME_CAMERAS) or document.get("required_markers") != list(FRAME_MARKERS)
            or any(document.get(k) != v for k, v in _FRAME_TEXT.items())
            or not isinstance(document.get("session_id"), str) or not isinstance(document.get("frames"), list) or not document["frames"]):
        raise ValueError("FRAME_DIAGNOSTICS_INVALID: identity, policy or criteria")
    for key in ("source_trc", "calibration"):
        item = document.get(key)
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"} or not isinstance(item["path"], str)
                or not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise ValueError("FRAME_DIAGNOSTICS_INVALID: source identity")
    last = -1
    for frame in document["frames"]:
        index = frame.get("synchronized_frame_index") if isinstance(frame, dict) else None
        markers = frame.get("markers") if isinstance(frame, dict) else None
        # Membership, not order: published sidecars are written with sorted keys.
        if type(index) is not int or index <= last or not isinstance(markers, dict) or set(markers) != set(FRAME_MARKERS):
            raise ValueError("FRAME_DIAGNOSTICS_INVALID: frame order or marker set")
        last = index
        for stored in markers.values():
            if not isinstance(stored, dict) or set(stored) != {"valid", "views", "cameras"}:
                raise ValueError("FRAME_DIAGNOSTICS_INVALID: marker record")
            expected, _ = _frame_marker(stored["cameras"])
            if type(stored["valid"]) is not bool or type(stored["views"]) is not int or stored != expected:
                raise ValueError("FRAME_DIAGNOSTICS_INVALID: stored validity contradicts camera support")
        if (set(frame) != {"synchronized_frame_index", "rejected", "markers"} or type(frame.get("rejected")) is not bool
                or frame["rejected"] != (not all(m["valid"] for m in markers.values()))):
            raise ValueError("FRAME_DIAGNOSTICS_INVALID: stored rejection contradicts marker validity")
    return document


def build_frame_diagnostics(observations, required_markers, identity):
    if list(required_markers) != list(FRAME_MARKERS) or list(identity.get("camera_ids", [])) != list(FRAME_CAMERAS):
        raise ValueError("FRAME_DIAGNOSTICS_INVALID: unexpected marker or camera set")
    by_frame = {}
    for row in observations:
        frame, marker = row.get("frame"), row.get("marker")
        if type(frame) is not int or frame < 0 or marker not in FRAME_MARKERS or marker in by_frame.get(frame, {}):
            raise ValueError("FRAME_DIAGNOSTICS_INVALID: unbound or duplicate observation")
        cameras = {}
        for name, cell in (row.get("cameras") or {}).items():
            cell = dict(cell) if isinstance(cell, dict) else cell
            # Only these two producer outcomes carry an already non-finite native value.
            if (isinstance(cell, dict) and cell.get("status") == "projection_non_finite"
                    and isinstance(cell.get("reprojection_px"), float) and not _finite(cell["reprojection_px"])):
                cell["reprojection_px"] = None
            if (isinstance(cell, dict) and cell.get("status") == "behind_camera"
                    and isinstance(cell.get("camera_depth"), float) and not _finite(cell["camera_depth"])):
                cell["camera_depth"] = None
            cameras[name] = cell
        by_frame.setdefault(frame, {})[marker] = _frame_marker(cameras)[0]
    frames = []
    for frame in sorted(by_frame):
        if set(by_frame[frame]) != set(FRAME_MARKERS):
            raise ValueError("FRAME_DIAGNOSTICS_INVALID: frame lacks a required marker record")
        markers = {name: by_frame[frame][name] for name in FRAME_MARKERS}
        frames.append({"synchronized_frame_index": frame, "rejected": not all(m["valid"] for m in markers.values()), "markers": markers})
    document = {"schema": FRAME_DIAGNOSTICS_SCHEMA, "policy": QUALITY_POLICY, "session_id": identity["session_id"],
                "source_trc": dict(identity["source_trc"]), "calibration": dict(identity["calibration"]),
                "camera_ids": list(FRAME_CAMERAS), "required_markers": list(FRAME_MARKERS),
                "criteria": copy.deepcopy(RECONSTRUCTION_CRITERIA), **_FRAME_TEXT, "frames": frames}
    return _validate_frame_document(document)


def _is_link(path):
    from runtime_config import is_reparse
    return is_reparse(path)


def _frame_path(project, relative):
    project = Path(project).resolve()
    match = _FRAME_FILE.match(relative) if isinstance(relative, str) else None
    path = project / relative if match else None
    if not match or _is_link(path) or _is_link(path.parent) or (path.exists() and path.resolve() != path):
        raise ValueError("QUALITY_UNVERIFIED: frame diagnostics path is not a plain content-addressed session file")
    return path, match.group(1)


def _file_identity(item):
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns


def _reparse(item):
    return bool(getattr(item, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _read_frame_bytes(path):
    """One bounded read of a regular non-link file whose identity holds from path check to close."""
    path = Path(path)
    cap = FRAME_DIAGNOSTICS_MAX_BYTES
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or _reparse(before) or _is_link(path):
        raise ValueError("QUALITY_UNVERIFIED: frame diagnostics must be a regular file, not a link or reparse point")
    if before.st_size > cap:
        raise ValueError("QUALITY_UNVERIFIED: frame diagnostics exceed the byte cap")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        # Refuse a swapped descriptor before any of its bytes are read.
        if not stat.S_ISREG(opened.st_mode) or _file_identity(opened) != _file_identity(before):
            raise ValueError("QUALITY_UNVERIFIED: frame diagnostics changed before read")
        data = stream.read(min(cap, max(0, before.st_size)) + 1)
        closed = os.fstat(stream.fileno())
    after = path.stat(follow_symlinks=False)
    if len(data) > cap or closed.st_size > cap or after.st_size > cap:
        raise ValueError("QUALITY_UNVERIFIED: frame diagnostics exceed the byte cap")
    # As in the house file proof, ctime is compared only within one stat interface;
    # Windows path and descriptor ctime precision can legitimately differ.
    if (_file_identity(opened) != _file_identity(closed) or _file_identity(before) != _file_identity(after)
            or before.st_ctime_ns != after.st_ctime_ns or opened.st_ctime_ns != closed.st_ctime_ns
            or len(data) != before.st_size or _reparse(after) or _is_link(path)):
        raise ValueError("QUALITY_UNVERIFIED: frame diagnostics changed while read")
    return data


def write_frame_diagnostics(project, document):
    """Content-addressed, fsynced, create-if-absent; a published sidecar is never rewritten."""
    data = json.dumps(_validate_frame_document(document), indent=2, allow_nan=False, sort_keys=True).encode("utf-8")
    if len(data) > FRAME_DIAGNOSTICS_MAX_BYTES:
        raise ValueError("FRAME_DIAGNOSTICS_UNAVAILABLE: document exceeds the byte cap; nothing published")
    digest = hashlib.sha256(data).hexdigest()
    relative = "diagnostics/reconstruction-frames." + digest + ".json"
    folder = Path(project).resolve() / "diagnostics"
    if _is_link(folder):
        raise ValueError("FRAME_DIAGNOSTICS_UNAVAILABLE: diagnostics folder is a link")
    folder.mkdir(exist_ok=True)
    target, _ = _frame_path(project, relative)
    if not target.exists():
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".partial-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
        except OSError as error:
            raise ValueError("FRAME_DIAGNOSTICS_UNAVAILABLE: create-if-absent publication unsupported") from error
        finally:
            temporary.unlink(missing_ok=True)
    if _read_frame_bytes(_frame_path(project, relative)[0]) != data:
        raise ValueError("FRAME_DIAGNOSTICS_CONFLICT: existing content-addressed sidecar differs; not rewritten")
    return {"path": relative, "sha256": digest, "schema": FRAME_DIAGNOSTICS_SCHEMA, "source_trc": dict(document["source_trc"]),
            "calibration": dict(document["calibration"]), "frames": len(document["frames"])}


def verify_frame_diagnostics(project, binding, *, session_id):
    """session_id must come from the caller's validated session, never from the sidecar or its name."""
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("QUALITY_UNVERIFIED: frame diagnostics require the validated session identity")
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "schema", "source_trc", "calibration", "frames"}:
        raise ValueError("QUALITY_UNVERIFIED: frame diagnostics binding malformed")
    path, named = _frame_path(project, binding["path"])
    if named != binding["sha256"] or not path.is_file():
        raise ValueError("QUALITY_UNVERIFIED: frame diagnostics missing or not content-addressed")
    data = _read_frame_bytes(path)  # one read: the hash and the parse cover these same bytes
    if hashlib.sha256(data).hexdigest() != binding["sha256"]:
        raise ValueError("QUALITY_UNVERIFIED: frame diagnostics bytes changed")
    try:
        document = _validate_frame_document(strict_json_loads(data.decode("utf-8")))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("QUALITY_UNVERIFIED: " + str(error)) from error
    if (binding["schema"] != FRAME_DIAGNOSTICS_SCHEMA or document["session_id"] != session_id
            or document["source_trc"] != binding["source_trc"]
            or document["calibration"] != binding["calibration"] or type(binding["frames"]) is not int
            or len(document["frames"]) != binding["frames"]):
        raise ValueError("QUALITY_UNVERIFIED: frame diagnostics content disagrees with its binding")
    return document

def _timing_trc_times(data):
    """Parse exactly the already-bound bytes under the existing strict TRC row rules."""
    from export_motion import fail, num, positive_int, series_times, tab_row
    code = "TIMING_GRID_MISMATCH"
    rows = [line.split("\t") for line in data.decode("utf-8-sig").splitlines()]
    if len(rows) < 6 or rows[0][:3] != ["PathFileType", "4", "(X/Y/Z)"]:
        fail(code, "Expected a tab-delimited XYZ TRC")
    keys = [x.strip() for x in rows[1]]
    while keys and not keys[-1]:
        keys.pop()
    values = tab_row(rows[2], len(keys), code)
    if len(set(keys)) != len(keys):
        fail(code, "Duplicate header fields")
    head = dict(zip(keys, values))
    count = positive_int(head.get("NumMarkers"), code)
    count_frames = positive_int(head.get("NumFrames"), code)
    if count_frames > 4096:
        fail("TIMING_LIMIT_EXCEEDED", "At most 4096 TRC samples per timing response")
    rate = num(head.get("DataRate"))
    if rate is None or rate <= 0:
        fail(code, "DataRate must be finite and positive")
    for key in ("CameraRate", "OrigDataRate"):
        if key in head and (num(head[key]) is None or num(head[key]) <= 0):
            fail(code, f"{key} must be finite and positive")
    for key in ("OrigDataStartFrame", "OrigNumFrames"):
        if key in head:
            positive_int(head[key], code, minimum=0 if key == "OrigDataStartFrame" else 1)
    units = head.get("Units")
    if units not in ("m", "mm"):
        fail(code, "Units must be m or mm")
    width = 2 + 3 * count
    header = tab_row(rows[3], width, code)
    if header[:2] != ["Frame#", "Time"]:
        fail(code, "Expected Frame# and Time")
    names = [header[2 + 3 * i] for i in range(count)]
    if not all(names) or len(set(names)) != count:
        fail(code, "Missing or duplicate marker names")
    if any(header[3 + 3 * i] or header[4 + 3 * i] for i in range(count)):
        fail(code, "Misaligned marker header")
    axes = ["", ""] + [f"{axis}{i}" for i in range(1, count + 1) for axis in "XYZ"]
    if tab_row(rows[4], width, code) != axes:
        fail(code, "Coordinate columns must be X/Y/Z for each marker")
    frames, indices = [], []
    scale = .001 if units == "mm" else 1.0
    for raw in rows[5:]:
        if not any(x.strip() for x in raw):
            continue
        row = tab_row(raw, width, code)
        indices.append(positive_int(row[0], code, minimum=0))
        time = num(row[1])
        if time is None:
            fail(code, "Nonfinite or malformed time")
        coords = []
        for i in range(count):
            triple = row[2 + 3 * i:5 + 3 * i]
            if triple == ["", "", ""]:
                coords.append(None)
            else:
                point = [num(x) for x in triple]
                if any(x is None for x in point):
                    fail(code, "Coordinates must be finite triples or entirely blank")
                coords.append([x * scale for x in point])
        frames.append({"t": time, "xyz": coords})
    if len(frames) != count_frames:
        fail(code, "Declared frame count does not match data")
    series_times([f["t"] for f in frames], code)
    series_times(indices, code)
    if rate != _SYNC_FPS:
        fail(code, "Current reconstruction timing requires the existing 30 fps grid")
    return [frame["t"] for frame in frames]


def project_reconstruction_timing(document, times_s, *, session_id, source_trc, calibration):
    """Observed software grid only; not continuous physical/clinical valid time."""
    if (isinstance(document, dict) and isinstance(document.get("frames"), list)
            and len(document["frames"]) > 4096):
        raise ValueError("TIMING_LIMIT_EXCEEDED: at most 4096 diagnostic samples per response")
    _validate_frame_document(document)
    if (document["session_id"] != session_id or document["source_trc"] != source_trc
            or document["calibration"] != calibration):
        raise ValueError("TIMING_SOURCE_MISMATCH: diagnostics identity does not match verified source")
    frames = document["frames"]

    if not isinstance(times_s, list) or len(times_s) != len(frames):
        raise ValueError("TIMING_GRID_MISMATCH: TRC and diagnostics row counts differ")
    previous = None
    for frame, value in zip(frames, times_s, strict=True):
        index = frame["synchronized_frame_index"]
        try:
            valid_time = _finite(value) and value >= 0 and (previous is None or value > previous)
            expected_time = index / _SYNC_FPS
        except OverflowError as error:
            raise ValueError("TIMING_GRID_MISMATCH: time or frame index exceeds finite arithmetic") from error
        if not valid_time:
            raise ValueError("TIMING_GRID_MISMATCH: finite increasing times required")
        if not math.isclose(value, expected_time, rel_tol=0, abs_tol=_TRC_TIME_TOL_S):
            raise ValueError("TIMING_GRID_MISMATCH: exact synchronized TRC grid required")
        previous = value
    segments, gaps, intervals = [], [], []
    duration_parts = {"valid_adjacent": [], "rejected_or_transition_adjacent": [], "unknown_gap": []}
    valid_count = sum(not frame["rejected"] for frame in frames)
    for position, frame in enumerate(frames):
        index, time = frame["synchronized_frame_index"], times_s[position]
        classification = "rejected" if frame["rejected"] else "valid"
        if (segments and segments[-1]["classification"] == classification
                and segments[-1]["last_frame"] + 1 == index):
            segments[-1].update(last_frame=index, last_time_s=time, samples=segments[-1]["samples"] + 1)
        else:
            segments.append({"classification": classification, "first_frame": index, "last_frame": index,
                             "first_time_s": time, "last_time_s": time, "samples": 1})
        if not position:
            continue
        prior, start = frames[position - 1], times_s[position - 1]
        prior_index = prior["synchronized_frame_index"]
        if index > prior_index + 1:
            category = "unknown_gap"
            gaps.append({"first_missing_frame": prior_index + 1, "last_missing_frame": index - 1,
                         "missing_samples": index - prior_index - 1,
                         "left_time_s": start, "right_time_s": time})
        elif prior["rejected"] or frame["rejected"]:
            category = "rejected_or_transition_adjacent"
        else:
            category = "valid_adjacent"
        delta = time - start
        duration_parts[category].append(delta)
        intervals.append({"left_frame": prior_index, "right_frame": index,
                          "start_time_s": start, "end_time_s": time, "category": category})
    first, last = frames[0]["synchronized_frame_index"], frames[-1]["synchronized_frame_index"]
    durations = {key: math.fsum(values) for key, values in duration_parts.items()}
    span = times_s[-1] - times_s[0]
    if not math.isclose(math.fsum(durations.values()), span, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("TIMING_ACCOUNTING_INVALID: intervals do not exhaust observed span")
    return {"schema": "kinelab.reconstruction-timing.v1", "status": "AVAILABLE",
            "session_id": session_id, "source_trc": source_trc, "calibration": calibration,
            "sample_counts": {"observed": len(frames), "valid": valid_count,
                              "rejected": len(frames) - valid_count, "missing_interior": last - first + 1 - len(frames)},
            "segments": segments, "gaps": gaps, "intervals": intervals,
            "duration_s": {**durations, "observed_span": span},
            "duration_policy": "adjacent_observed_endpoints_v1; [start,end) partition; rejected includes transitions; no endpoint extrapolation",
            "source_extent": "leading/trailing and decoded source video extent UNVERIFIED",
            "physical_accuracy_verified": False, "clinical_accuracy_verified": False,
            "clinical_validation": "UNVERIFIED"}


def validate_reconstruction(project: Path, session: dict) -> dict:
    project = Path(project)
    report = {"schema": "kinelab.quality.v1", "policy": QUALITY_POLICY, "session_id": session["session_id"], "ok": False, "errors": []}
    try:
        import cv2
        import numpy as np
        from anytree import RenderTree
        from Pose2Sim.skeletons import HALPE_26

        from export_motion import parse_trc
        config = tomllib.loads((project / "Config.toml").read_text(encoding="utf-8-sig"))
        if config.get("pose", {}).get("pose_model") != "Body_with_feet":
            raise ValueError("RECONSTRUCTION_REJECTED: first pilot supports configured Body_with_feet only")
        run = json.loads((project / "run.json").read_text(encoding="utf-8"))
        if run.get("native_triangulation_policy") != {"interpolation": "none", "fill_large_gaps_with": "nan"}:
            raise ValueError("RECONSTRUCTION_REJECTED: unfiltered no-gap-fill provenance required")
        paths = [path for path in (project / "pose-3d").glob("*.trc") if "filt" not in path.name and "LSTM" not in path.name]
        if len(paths) != 1:
            raise ValueError("RECONSTRUCTION_REJECTED: exactly one current unfiltered TRC required")
        names, frames, fps = parse_trc(paths[0])
        if fps != _SYNC_FPS:
            raise ValueError("RECONSTRUCTION_REJECTED: TRC DataRate must equal the 30 fps synchronization rate")
        indexes = []
        for frame in frames:
            index = round(frame["t"] * fps)
            if index < 0 or not math.isclose(frame["t"], index / fps, rel_tol=0, abs_tol=_TRC_TIME_TOL_S):
                raise ValueError("RECONSTRUCTION_REJECTED: TRC time is off the 30 fps synchronized frame grid")
            indexes.append(index)
        ids = {node.name: node.id for _, _, node in RenderTree(HALPE_26) if node.id is not None}
        required = ["Hip", "RHip", "RKnee", "RAnkle", "LHip", "LKnee", "LAnkle"]
        if any(name not in names or name not in ids for name in required):
            raise ValueError("RECONSTRUCTION_REJECTED: required lower-limb landmarks absent")
        calibration = _calibration_file(project)
        cal = tomllib.loads(calibration.read_text(encoding="utf-8-sig"))
        camera_names = [name for name in cal if name in session["camera_ids"]]
        if set(camera_names) != {"cam01", "cam02"}:
            raise ValueError("RECONSTRUCTION_REJECTED: expected two calibrated cameras")
        extrinsics = []
        for camera_name in camera_names:
            camera = cal[camera_name]
            if camera.get("fisheye") is not False:
                raise ValueError("RECONSTRUCTION_REJECTED: verified pinhole distortion model required")
            rotation, _ = cv2.Rodrigues(np.asarray(camera["rotation"], dtype=float))
            extrinsics.append(np.column_stack((rotation, np.asarray(camera["translation"], dtype=float))))
        files: dict[str, dict[int, Path]] = {}
        for camera in camera_names:
            folder = project / "pose-associated" / (camera + "_json")
            files[camera] = {}
            for path in folder.glob("*.json"):
                match = re.fullmatch(re.escape(camera) + r"_([0-9]{6,})\.json", path.name)
                if match is None:
                    raise ValueError("RECONSTRUCTION_REJECTED: ambiguous or non-native pose filename for " + camera)
                index = int(match.group(1))
                if path.name != f"{camera}_{index:06d}.json":
                    raise ValueError("RECONSTRUCTION_REJECTED: ambiguous or non-native pose filename for " + camera)
                if index in files[camera]:
                    raise ValueError("RECONSTRUCTION_REJECTED: ambiguous duplicate pose frame index for " + camera)
                files[camera][index] = path
        extents = {camera: (min(found), max(found)) for camera, found in files.items() if found}
        if set(extents) != set(camera_names) or len(set(extents.values())) != 1:
            raise ValueError("RECONSTRUCTION_REJECTED: cam01/cam02 associated pose frame extents must be nonempty and equal")
        first, last = extents[camera_names[0]]
        from source_coverage import _stage_files, verify_source_coverage
        identity = {"session_id": session["session_id"], "config_sha256": sha256_file(project / "Config.toml"),
                    "inputs": {role: entry["sha256"] for role, entry in session.get("captures", {}).items()}}
        coverage = verify_source_coverage(project, identity, run, through="personAssociation")
        if [first, last + 1] != coverage["common_range"]:
            raise ValueError("RECONSTRUCTION_REJECTED: associated extent differs from decoded native common range")
        report["source_coverage"] = coverage
        associated_buffers, _ = _stage_files(project.resolve(), run, "personAssociation")
        # Associated endpoints now derive from independently decoded normalized trial extent.
        # Original camera frame equality and physical measurement remain UNVERIFIED.
        if (indexes[0], indexes[-1]) != (first, last):
            raise ValueError(f"RECONSTRUCTION_REJECTED: TRC frame extent {indexes[0]}..{indexes[-1]} differs from associated pose extent {first}..{last}")
        samples, observations = [], []
        for frame, index in zip(frames, indexes):
            poses, pose_status = {}, {}
            for camera in camera_names:
                pose_path = files[camera].get(index)
                data = strict_json_loads(associated_buffers[camera][index].decode("utf-8-sig")) if pose_path else {}
                people = data.get("people", []) if isinstance(data, dict) else None
                if not isinstance(people, list) or not all(isinstance(person, dict) for person in people):
                    raise ValueError("RECONSTRUCTION_REJECTED: malformed associated pose JSON for " + camera)
                poses[camera] = people[0].get("pose_keypoints_2d", []) if len(people) == 1 else []
                if not isinstance(poses[camera], list):
                    raise TypeError("RECONSTRUCTION_REJECTED: malformed associated pose keypoints for " + camera)
                pose_status[camera] = "no_pose_file" if pose_path is None else "people_count_not_one" if len(people) != 1 else None
            for name in required:
                point = frame["xyz"][names.index(name)]
                likelihoods, errors, cells = [], [], {}
                for camera, transform in zip(camera_names, extrinsics):
                    keypoint = poses[camera][ids[name] * 3:ids[name] * 3 + 3]
                    detected = len(keypoint) == 3 and all(_finite(value) for value in keypoint)
                    cell = cells[camera] = {"status": pose_status[camera], "likelihood": keypoint[2] if detected and not pose_status[camera] else None,
                                            "reprojection_px": None, "camera_depth": None}
                    if pose_status[camera]:
                        continue
                    if point is None or not detected:
                        cell["status"] = "trc_point_missing" if point is None else "keypoint_missing"
                        continue
                    # Pose2Sim zup2yup permutes native (x,y,z) to (y,z,x).
                    world_point = np.asarray([point[2], point[0], point[1]], dtype=float)
                    camera_point = transform @ np.append(world_point, 1.0)
                    depth = float(camera_point[2])
                    if not np.isfinite(camera_point).all() or camera_point[2] <= 1e-12:
                        deep = math.isfinite(depth) and depth > _MIN_DEPTH
                        cell.update(status="projection_non_finite" if deep else "behind_camera", camera_depth=depth if math.isfinite(depth) else None)
                        continue
                    calibration_camera = cal[camera]
                    projected, _ = cv2.projectPoints(world_point.reshape(1, 3),
                        np.asarray(calibration_camera["rotation"], dtype=float),
                        np.asarray(calibration_camera["translation"], dtype=float),
                        np.asarray(calibration_camera["matrix"], dtype=float),
                        np.asarray(calibration_camera["distortions"], dtype=float))
                    if not np.isfinite(projected).all():
                        cell.update(status="projection_non_finite", camera_depth=depth)
                        continue
                    likelihoods.append(keypoint[2]); errors.append(float(np.linalg.norm(projected.reshape(2) - keypoint[:2])))
                    cell.update(status="supported", reprojection_px=errors[-1], camera_depth=depth)
                samples.append({"marker": name, "frame": index, "views": len(likelihoods), "likelihoods": likelihoods,
                                "reprojection_px": max(errors) if errors else None, "interpolated": False})
                observations.append({"frame": index, "marker": name, "cameras": cells})
        report.update(assess_reconstruction(samples, required))
        report.update(method="native unfiltered TRC reprojected into associated two-camera poses; no gap filling", source_trc=paths[0].name,
                      accepted_time_range_s=[frames[0]["t"], frames[-1]["t"]], physical_accuracy="not validated")
        try:
            document = build_frame_diagnostics(observations, required, {
                "session_id": session["session_id"], "camera_ids": sorted(camera_names),
                "source_trc": {"path": "pose-3d/" + paths[0].name, "sha256": sha256_file(paths[0])},
                "calibration": {"path": calibration.relative_to(project).as_posix(), "sha256": sha256_file(calibration)}})
            report["frame_diagnostics"] = write_frame_diagnostics(project, document)
        except (OSError, ValueError, KeyError, TypeError) as error:
            report["ok"] = False
            report["errors"].append("FRAME_DIAGNOSTICS_UNAVAILABLE: " + str(error))
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        report["errors"].append(str(error))
    return _save(project, "quality.json", report)


def _aligned_trc(project, source, output, code):
    """Parse a native output TRC and map it onto one contiguous run of its exact source frames."""
    from export_motion import parse_trc
    project = Path(project)
    paths = [(project / relative).resolve() for relative in (source, output)]
    if any(not path.is_relative_to(project.resolve()) or not path.is_file() for path in paths):
        raise ValueError(code + ": stage input/output TRC missing or outside session")
    (names, frames, _), (out_names, out_frames, _) = parse_trc(paths[0]), parse_trc(paths[1])
    start = next((i for i, frame in enumerate(frames) if out_frames and math.isclose(frame["t"], out_frames[0]["t"], rel_tol=0, abs_tol=1e-6)), None)
    if (start is None or start + len(out_frames) > len(frames)
            or any(not math.isclose(a["t"], b["t"], rel_tol=0, abs_tol=1e-6) for a, b in zip(frames[start:], out_frames))):
        raise ValueError(code + ": output frames/times are not a contiguous run of the source TRC")
    binding = {"source": {"path": source, "sha256": sha256_file(paths[0])}, "output": {"path": output, "sha256": sha256_file(paths[1])}}
    return names, frames[start:start + len(out_frames)], out_names, out_frames, binding, len(frames) - len(out_frames)


def _coverage(names, frames):
    return {name: sum(frame["xyz"][index] is not None for frame in frames) / len(frames) for index, name in enumerate(names)}


def validate_filtering(project, source, output):
    report = {"schema": "kinelab.filtering-quality.v1", "policy": QUALITY_POLICY, "ok": False, "errors": []}
    try:
        names, frames, out_names, out_frames, binding, dropped = _aligned_trc(project, source, output, "FILTERING_REJECTED")
        if out_names != names:
            raise ValueError("FILTERING_REJECTED: filtered marker set differs from triangulated source")
        if any((a is None) != (b is None) for left, right in zip(frames, out_frames) for a, b in zip(left["xyz"], right["xyz"])):
            raise ValueError("FILTERING_REJECTED: filtered TRC filled or dropped samples relative to triangulated source gaps")
        if not any(point is not None for frame in out_frames for point in frame["xyz"]):
            raise ValueError("FILTERING_REJECTED: no observed samples")
        report.update(ok=True, **binding, frames=len(out_frames), source_frames_not_in_output=dropped, coverage=_coverage(names, out_frames),
                      accepted_time_range_s=[out_frames[0]["t"], out_frames[-1]["t"]], missing_data="source gaps preserved; no gap filling",
                      classification="native_filtered_research_only")
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
    return _save(project, "filtering-quality.json", report)


def validate_augmentation(project, source, output):
    report = {"schema": "kinelab.augmentation-quality.v1", "policy": QUALITY_POLICY, "ok": False, "errors": []}
    try:
        names, frames, out_names, out_frames, binding, dropped = _aligned_trc(project, source, output, "AUGMENTATION_REJECTED")
        if out_names[:len(names)] != names:
            raise ValueError("AUGMENTATION_REJECTED: original filtered markers not preserved in order")
        derived = out_names[len(names):]
        if not derived:
            raise ValueError("AUGMENTATION_REJECTED: no model-derived markers produced")
        for left, right in zip(frames, out_frames):
            for a, b in zip(left["xyz"], right["xyz"][:len(names)]):
                if (a is None) != (b is None) or (a is not None and not all(math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-9) for x, y in zip(a, b))):
                    raise ValueError("AUGMENTATION_REJECTED: original marker values or gaps changed by augmentation")
        report.update(ok=True, **binding, frames=len(out_frames), source_frames_not_in_output=dropped, original_markers=names,
                      derived_markers=derived, derived_classification="model_derived_LSTM_estimate_not_observed",
                      derived_coverage={name: value for name, value in _coverage(out_names, out_frames).items() if name in derived})
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
    return _save(project, "augmentation-quality.json", report)
