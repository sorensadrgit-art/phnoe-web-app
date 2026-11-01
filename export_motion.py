"""Export Pose2Sim TRC/OpenSim MOT to validated, local KineLab motion JSON."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from bisect import bisect_left
from itertools import pairwise
from pathlib import Path

SEGMENTS = [
    ("Hip", "RHip"), ("RHip", "RKnee"), ("RKnee", "RAnkle"), ("RAnkle", "RHeel"),
    ("RAnkle", "RBigToe"), ("Hip", "LHip"), ("LHip", "LKnee"), ("LKnee", "LAnkle"),
    ("LAnkle", "LHeel"), ("LAnkle", "LBigToe"), ("Hip", "Neck"), ("Neck", "Head"),
    ("Head", "Nose"), ("Neck", "RShoulder"), ("RShoulder", "RElbow"),
    ("RElbow", "RWrist"), ("Neck", "LShoulder"), ("LShoulder", "LElbow"),
    ("LElbow", "LWrist"),
]
ROOT = Path(__file__).resolve().parent / "projects" / "kinelab-dualcam"
# OpenSim coordinate names, not a heuristic that treats every non-time column as an angle.
ANGULAR = {
    "pelvis_tilt", "pelvis_list", "pelvis_rotation", "lumbar_extension",
    "lumbar_bending", "lumbar_rotation", "neck_flexion", "neck_bending", "neck_rotation",
    "Abs_r1", "Abs_r2", "Abs_r3", "knee_angle_r_beta", "knee_angle_l_beta",
} | {
    f"{joint}_{axis}" for joint in ("L5_S1", "L4_L5", "L3_L4", "L2_L3", "L1_L2", "L1_T12")
    for axis in ("Flex_Ext", "Lat_Bending", "axial_rotation")
} | {f"{name}_{side}" for side in ("r", "l") for name in (
    "hip_flexion", "hip_adduction", "hip_rotation", "knee_angle", "ankle_angle",
    "subtalar_angle", "mtp_angle", "arm_flex", "arm_add", "arm_rot", "elbow_flex",
    "pro_sup", "wrist_flex", "wrist_dev",
)}
TRANSLATIONS = {"pelvis_tx", "pelvis_ty", "pelvis_tz", "Abs_t1", "Abs_t2"}
# Native coupled patellar coordinates are NOT converted by OpenSim's
# convertRadiansToDegrees, even when the MOT inDegrees header is yes.
NATIVE_RADIANS = {"knee_angle_r_beta", "knee_angle_l_beta"}


def fail(code, message):
    raise ValueError(f"{code}: {message}")


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def num(value):
    """Legacy helper: return a finite float, or None."""
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def positive_int(value, code, *, minimum=1):
    if not isinstance(value, str) or not re.fullmatch(r"\d+", value) or int(value) < minimum:
        fail(code, "Expected a positive integer count/index")
    return int(value)


def series_times(times, code):
    if not times or any(not finite(t) for t in times):
        fail(code, "Empty or nonfinite timestamps")
    if any(b <= a for a, b in pairwise(times)):
        fail(code, "Timestamps must strictly increase")


def tab_row(row, width, code):
    # Pose2Sim appends a delimiter. Only surplus *empty* fields are permitted.
    if len(row) < width or any(x.strip() for x in row[width:]):
        fail(code, "Row length does not match declared shape")
    return [x.strip() for x in row[:width]]


def parse_trc(path):
    """Return (marker names, frames in meters, nominal rate). Blank triples are missing."""
    code = "TRC_INVALID"
    rows = [line.split("\t") for line in Path(path).read_text(encoding="utf-8-sig").splitlines()]
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
    return names, frames, rate


def column_types(columns):
    types = {}
    for name in columns[1:]:
        if name in ANGULAR:
            types[name] = "angular"
        elif name in TRANSLATIONS:
            types[name] = "translation"
        else:
            fail("MOT_INVALID", f"Unsupported coordinate {name!r}; an explicit unit mapping is required")
    return types


def column_units(types, in_degrees):
    return {name: "m" if kind == "translation" else
            "deg" if in_degrees and name not in NATIVE_RADIANS else "rad"
            for name, kind in types.items()}


def validate_kinematics(kin):
    code = "MOT_INVALID"
    if not isinstance(kin, dict) or type(kin.get("inDegrees")) is not bool:
        fail(code, "inDegrees must explicitly be true or false")
    columns, rows = kin.get("columns"), kin.get("rows")
    if (not isinstance(columns, list) or len(columns) < 2 or columns[0] != "time"
            or any(not isinstance(c, str) or not c.strip() or c != c.strip() for c in columns)
            or len(set(columns)) != len(columns)):
        fail(code, "Unique columns starting with time are required")
    types = column_types(columns)
    if "columnTypes" in kin and kin["columnTypes"] != types:
        fail(code, "Coordinate type mapping disagrees with supported OpenSim units")
    if "columnUnits" in kin and kin["columnUnits"] != column_units(types, kin["inDegrees"]):
        fail(code, "Coordinate unit mapping disagrees with native OpenSim units")
    if "timeTolerance" in kin and (not finite(kin["timeTolerance"]) or kin["timeTolerance"] <= 0):
        fail(code, "Invalid kinematics time tolerance")
    if not isinstance(rows, list) or not rows:
        fail(code, "No kinematics rows")
    if any(not isinstance(r, list) or len(r) != len(columns) or not all(finite(v) for v in r) for r in rows):
        fail(code, "Rows must have the declared shape and finite numeric values")
    series_times([r[0] for r in rows], code)
    return types


def parse_mot(path):
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    stop = next((i for i, line in enumerate(lines) if line.strip().lower() == "endheader"), None)
    if stop is None:
        fail("MOT_INVALID", "Missing endheader")
    head = {}
    for line in lines[:stop]:
        match = re.fullmatch(r"\s*(\w+)\s*(?:=|\s)\s*(.*?)\s*", line)
        if match:
            key, value = match[1].lower(), match[2]
            if key in head:
                fail("MOT_INVALID", "Duplicate header declaration")
            head[key] = value
    if head.get("indegrees", "").lower() not in ("yes", "no"):
        fail("MOT_INVALID", "inDegrees must be yes or no")
    body = [line.split() for line in lines[stop + 1:] if line.strip()]
    if len(body) < 2:
        fail("MOT_INVALID", "Missing columns or rows")
    rows = [[num(x) for x in row] for row in body[1:]]
    kin = {"columns": body[0], "rows": rows, "inDegrees": head["indegrees"].lower() == "yes"}
    kin["columnTypes"] = validate_kinematics(kin)
    kin["columnUnits"] = column_units(kin["columnTypes"], kin["inDegrees"])
    for key, expected in (("nrows", len(rows)), ("datarows", len(rows)),
                          ("ncolumns", len(body[0])), ("datacolumns", len(body[0]))):
        if key in head and positive_int(head[key], "MOT_INVALID") != expected:
            fail("MOT_INVALID", f"{key} disagrees with data")
    return kin


def time_tolerance(frames, fps):
    return min((b["t"] - a["t"] for a, b in pairwise(frames)), default=1 / fps)


def validate_coverage(frames, kin, fps):
    tolerance = time_tolerance(frames, fps)
    times = [row[0] for row in kin["rows"]]
    if abs(times[0] - frames[0]["t"]) > tolerance + 1e-9 or abs(times[-1] - frames[-1]["t"]) > tolerance + 1e-9:
        fail("MOT_INVALID", "MOT endpoints must match the TRC range within one TRC interval")
    for frame in frames:
        i = bisect_left(times, frame["t"])
        candidates = times[max(0, i - 1):i + 1]
        if min(abs(t - frame["t"]) for t in candidates) > tolerance + 1e-9:
            fail("MOT_INVALID", "No nearby MOT sample for a TRC timestamp")
    return tolerance


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_motion(data):
    """Same numeric/schema boundary for the exporter and Blender; no fabricated provenance."""
    code = "MOTION_INVALID"
    if not isinstance(data, dict) or data.get("schema") not in ("kinelab.motion.v1", "kinelab.motion.v2"):
        fail(code, "Unsupported motion schema")
    if data.get("units") != "m" or data.get("coordinateSystem") != "opensim_y_up":
        fail(code, "Expected OpenSim Y-up coordinates in meters")
    if not finite(data.get("fps")) or data["fps"] <= 0:
        fail(code, "fps must be finite and positive")
    names, frames, bones = data.get("markers"), data.get("frames"), data.get("bones")
    if (not isinstance(names, list) or not names or
            any(not isinstance(n, str) or not n.strip() or n != n.strip() for n in names) or len(set(names)) != len(names)):
        fail(code, "Expected unique nonempty marker names")
    if not isinstance(frames, list) or not frames:
        fail(code, "No motion frames")
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get("xyz"), list) or len(frame["xyz"]) != len(names):
            fail(code, "Frame marker count mismatch")
        for p in frame["xyz"]:
            if p is not None and (not isinstance(p, list) or len(p) != 3 or not all(finite(v) for v in p)):
                fail(code, "Markers must be finite triples or null")
    series_times([f.get("t") for f in frames], code)
    if not isinstance(bones, list):
        fail(code, "Expected bone index pairs")
    seen = set()
    for bone in bones:
        if (not isinstance(bone, list) or len(bone) != 2 or
                any(type(i) is not int or i < 0 or i >= len(names) for i in bone) or bone[0] == bone[1]):
            fail(code, "Invalid bone reference")
        key = tuple(sorted(bone))
        if key in seen:
            fail(code, "Duplicate bone")
        seen.add(key)
    kin = data.get("kinematics")
    if kin is not None:
        validate_kinematics(kin)
        validate_coverage(frames, kin, data["fps"])
    if data["schema"] == "kinelab.motion.v2":
        if not isinstance(data.get("sessionId"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", data["sessionId"]):
            fail(code, "Invalid sessionId")
        if data.get("kind") not in ("real", "demo"):
            fail(code, "kind must be real or demo")
        if data.get("time") != {"unit": "s", "origin": "synchronized_trial_start"}:
            fail(code, "Unsupported time declaration")
        prov = data.get("provenance")
        if not isinstance(prov, dict) or any(not valid_hash(prov.get(k)) for k in (
                "runManifestSha256", "trcSha256", "calibrationSha256")):
            fail(code, "Missing/invalid provenance hashes")
        if "motSha256" not in prov or (not valid_hash(prov["motSha256"]) if kin is not None else prov["motSha256"] is not None):
            fail(code, "MOT hash must match kinematics availability")
        mode = "kinematics" if kin is not None else "marker-only"
        if data.get("quality") != {"status": "passed", "mode": mode}:
            fail(code, "Missing passed stage quality/mode declaration")
    return data


def sha256_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_json(path):
    from session_contract import strict_json_loads
    try:
        return strict_json_loads(Path(path).read_text(encoding="utf-8-sig"))
    except ValueError as error:
        fail("ARTIFACT_MISMATCH", str(error))


def bound_path(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        fail("ARTIFACT_MISMATCH", "Artifact paths must be session-relative POSIX paths")
    part = Path(relative)
    if part.is_absolute() or ".." in part.parts or ":" in relative:
        fail("ARTIFACT_MISMATCH", "Artifact path escapes session")
    path = (root / part).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        fail("ARTIFACT_MISMATCH", "Artifact is missing or outside session")
    return path


def bind_run(manifest, trc, mot):
    from take_acceptance import TakeAcceptanceError, checked_path
    try:
        manifest = checked_path(manifest).resolve()
        trc = checked_path(trc)
        mot = checked_path(mot) if mot is not None else None
    except TakeAcceptanceError as error:
        fail("ARTIFACT_MISMATCH", "Explicit export path must be a plain non-link: " + str(error))
    root = manifest.parent
    before = sha256_file(manifest)
    run = load_json(manifest)
    # The shared session contract owns all six source hashes and safe role paths.
    from session_contract import load_session
    session = load_session(root)
    from run_pipeline import validate_run_evidence
    try:
        verified = validate_run_evidence(root, "kinematics" if mot else "filtering", session=session)
    except (ValueError, OSError) as error:
        fail("ARTIFACT_MISMATCH", str(error))
    if verified["run"] != run:
        fail("ARTIFACT_MISMATCH", "Run manifest changed during validation")
    if (not isinstance(run, dict) or run.get("schema") != "kinelab.run.v1"
            or run.get("session_id") != session["session_id"]
            or run.get("config_sha256") != sha256_file(root / "Config.toml")
            or run.get("inputs") != {r: v["sha256"] for r, v in session["captures"].items()}
            or run.get("coordinateSystem") != "opensim_y_up"):
        fail("ARTIFACT_MISMATCH", "Run session/config/input/frame binding is missing or stale")
    stages = run.get("stages")
    if not isinstance(stages, list) or not stages:
        fail("ARTIFACT_MISMATCH", "No run stages")
    artifacts, stage_names = [], set()
    for stage in stages:
        if not isinstance(stage, dict) or not isinstance(stage.get("name"), str) or stage["name"] in stage_names:
            fail("ARTIFACT_MISMATCH", "Invalid or duplicate stage")
        stage_names.add(stage["name"])
        if stage.get("status") not in ("not-run", "running", "passed", "failed", "skipped"):
            fail("ARTIFACT_MISMATCH", "Invalid stage status")
        if stage["status"] != "passed":
            continue
        if not isinstance(stage.get("artifacts"), list):
            fail("ARTIFACT_MISMATCH", "Passed stage lacks artifact bindings")
        for artifact in stage["artifacts"]:
            if not isinstance(artifact, dict) or not valid_hash(artifact.get("sha256")):
                fail("ARTIFACT_MISMATCH", "Invalid artifact binding")
            path = bound_path(root, artifact.get("path"))
            if sha256_file(path) != artifact["sha256"]:
                fail("ARTIFACT_MISMATCH", "A passed artifact has changed")
            artifacts.append((stage["name"], path, artifact["sha256"]))
    def select(path, stages):
        matches = [a for a in artifacts if a[1] == Path(path).resolve() and a[0] in stages]
        if not matches or len({a[2] for a in matches}) != 1:
            fail("ARTIFACT_MISMATCH", "Explicit input is not bound to the required passed stage")
        return matches[0][2]
    trc_hash = select(trc, ("filtering", "markerAugmentation"))
    mot_hash = select(mot, ("kinematics",)) if mot else None
    calibrations = {(p, h) for stage, p, h in artifacts if stage == "calibration" and p.suffix.lower() == ".toml"}
    if len(calibrations) != 1:
        fail("ARTIFACT_MISMATCH", "Expected one passed native calibration TOML")
    if sha256_file(manifest) != before:
        fail("ARTIFACT_MISMATCH", "Run manifest changed during export")
    return {
        "sessionId": session["session_id"], "kind": session["kind"],
        "provenance": {"runManifestSha256": before, "trcSha256": trc_hash,
                       "motSha256": mot_hash, "calibrationSha256": next(iter(calibrations))[1]},
        "quality": {"status": "passed", "mode": "kinematics" if mot else "marker-only"},
        "time": {"unit": "s", "origin": "synchronized_trial_start"},
    }


def motion(trc, mot=None, *, run_manifest=None):
    trc, mot = Path(trc), Path(mot) if mot is not None else None
    binding = bind_run(run_manifest, trc, mot) if run_manifest is not None else {}
    names, frames, fps = parse_trc(trc)
    idx = {name: i for i, name in enumerate(names)}
    kin = parse_mot(mot) if mot else None
    if kin is not None:
        kin["timeTolerance"] = validate_coverage(frames, kin, fps)
    data = {
        "schema": "kinelab.motion.v2" if binding else "kinelab.motion.v1",
        "units": "m", "coordinateSystem": "opensim_y_up",
        "source": {"trc": trc.name, "mot": mot.name if mot else None},
        "fps": fps, "markers": names,
        "bones": [[idx[a], idx[b]] for a, b in SEGMENTS if a in idx and b in idx],
        "frames": frames, "kinematics": kin,
        "notes": ["Exploratory only; not clinically validated",
                  "OpenSim model-based angles are not naive 2D geometric angles.",
                  "Legacy explicit TRC input assumes native Pose2Sim OpenSim Y-up coordinates."
                  if not binding else "Quality status reflects recorded passed stages, not clinical validation."],
        **binding,
    }
    if binding and (sha256_file(trc) != binding["provenance"]["trcSha256"]
            or mot and sha256_file(mot) != binding["provenance"]["motSha256"]
            or sha256_file(run_manifest) != binding["provenance"]["runManifestSha256"]):
        fail("ARTIFACT_MISMATCH", "Inputs/manifest changed while parsing")
    return validate_motion(data)


def load_verified_motion(project, path):
    """Verify served frame values against their immutable native source inputs."""
    project, path = Path(project).resolve(), Path(path)
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(project):
            raise ValueError("motion path outside session")
        data = validate_motion(load_json(path))
        if data["schema"] != "kinelab.motion.v2":
            from session_library import _read_json, _test_only
            kind = (_read_json(project / "session-template.json") or {}).get("kind")
            if not _test_only(project) and kind != "demo":
                raise ValueError("unbound exploratory data cannot enter measured session")
            return data
        run = load_json(project / "run.json")
        provenance = data["provenance"]
        def source(stages, digest):
            matches = [bound_path(project, artifact["path"]) for stage in run["stages"]
                       if stage["name"] in stages for artifact in stage["artifacts"] if artifact["sha256"] == digest]
            if len(matches) != 1:
                raise ValueError("source binding missing or ambiguous")
            return matches[0]
        trc = source(("filtering", "markerAugmentation"), provenance["trcSha256"])
        mot = source(("kinematics",), provenance["motSha256"]) if provenance["motSha256"] else None
        expected = motion(trc, mot, run_manifest=project / "run.json")
        if data != expected:
            raise ValueError("export values differ from bound source revision")
        return data
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError("EVIDENCE_INVALID: " + str(error)) from error


def latest(folder, glob):
    found = sorted(folder.glob(glob), key=lambda x: x.stat().st_mtime)
    return found[-1] if found else None


def write_motion(out, data):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=out.parent, suffix=".building.json", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, allow_nan=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        # Same-volume hard link publishes a complete file without overwriting a destination.
        os.link(temporary, out)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)



def _bounded_export_sha256(path: Path, expected_size: int) -> str:
    """Hash exactly the intended output bytes; refuse aliases, growth or replacement."""
    import stat

    from take_acceptance import checked_path

    path = checked_path(path)
    before = path.stat(follow_symlinks=False)
    def identity(item):
        return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_mode)
    if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
        raise ValueError("EXPORT_OUTPUT_CHANGED")
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("EXPORT_OUTPUT_CHANGED")
        while count <= expected_size:
            block = stream.read(min(1024 * 1024, expected_size + 1 - count))
            if not block:
                break
            count += len(block)
            digest.update(block)
        if count != expected_size or identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("EXPORT_OUTPUT_CHANGED")
    if identity(path.stat(follow_symlinks=False)) != identity(before):
        raise ValueError("EXPORT_OUTPUT_CHANGED")
    checked_path(path)
    return digest.hexdigest()



def _require_closed_motion_exports(index, session_id: str) -> None:
    """An unresolved intent cannot be bypassed by choosing another output filename."""
    pending = {}
    for row in index.conn.execute(
            "SELECT event_id,event_type,details_json FROM audit_events "
            "WHERE session_id=? AND event_type IN (?,?) ORDER BY id",
            (session_id, "motion_export_started", "motion_export_published")):
        details = json.loads(row["details_json"])
        if (not isinstance(details, dict)
                or details.get("schema") != "kinelab.motion-export-audit.v1"
                or details.get("session_id") != session_id
                or not isinstance(details.get("operation_id"), str)
                or re.fullmatch(r"[0-9a-f]{32}", details["operation_id"]) is None):
            raise ValueError("EXPORT_AUDIT_UNAVAILABLE")
        operation = details["operation_id"]
        if row["event_type"] == "motion_export_started":
            if operation in pending:
                raise ValueError("EXPORT_AUDIT_UNAVAILABLE")
            pending[operation] = (row["event_id"], details)
        else:
            prior = pending.pop(operation, None)
            if prior is None or details != {**prior[1], "started_event_id": prior[0]}:
                raise ValueError("EXPORT_AUDIT_UNAVAILABLE")
    if pending:
        raise ValueError("EXPORT_PENDING_PUBLICATION")

def _publish_audited_motion(project: Path, trc: Path, mot: Path | None,
                            manifest: Path, out: Path, data_root: Path | None) -> dict:
    """Native-v2 publication: existing index only, durable intent, then exact-byte receipt.

    An interrupted publication is retained, never rolled back or silently healed.
    This does not authenticate the operator or establish physical/clinical validity.
    """
    from uuid import uuid4

    from runtime_config import resolve_data_root
    from session_contract import load_session
    from session_index import SessionIndex
    from session_metadata_revision import read_metadata_state
    from take_acceptance import acceptance_lease, checked_path, local_path

    project = checked_path(project)
    root = resolve_data_root(data_root if data_root is not None else project.parent)
    if project.parent != root:
        raise ValueError("EXPORT_INDEX_ROOT_MISMATCH")
    database = local_path(root, ".kinelab_index.db")
    if not database.is_file():
        raise ValueError("EXPORT_INDEX_REQUIRED")
    manifest = checked_path(manifest)
    if manifest.parent != project:
        raise ValueError("EXPORT_SESSION_MISMATCH")
    out = checked_path(out)
    if out.parent != local_path(project, "exports") or not out.name.endswith(".motion.json"):
        raise ValueError("EXPORT_OUTPUT_LOCATION")
    if out.exists():
        raise ValueError("OUTPUT_EXISTS")
    operation_id = uuid4().hex
    # This is the same cooperative OS lease used by capture acceptance/metadata edits.
    with acceptance_lease(project):
        index = SessionIndex(database, root, existing_only=True)
        try:
            session = load_session(project)
            session_id = session["session_id"]
            if session_id != project.name:
                raise ValueError("EXPORT_SESSION_MISMATCH")
            with index.transaction():
                state = read_metadata_state(index, session_id)
                if state["status"] != "AVAILABLE":
                    raise ValueError("EXPORT_CONTEXT_UNAVAILABLE")
                _require_closed_motion_exports(index, session_id)
                data = motion(trc, mot, run_manifest=manifest)
                if data["schema"] != "kinelab.motion.v2" or data["sessionId"] != session_id:
                    raise ValueError("EXPORT_SESSION_MISMATCH")
                raw = json.dumps(data, allow_nan=False, separators=(",", ":")).encode("utf-8")
                output_sha256 = hashlib.sha256(raw).hexdigest()
                details = {
                    "schema": "kinelab.motion-export-audit.v1",
                    "operation_id": operation_id,
                    "session_id": session_id,
                    "origin": state["origin"],
                    "metadata_context_sha256": state["context_sha256"],
                    "native_provenance": data["provenance"],
                    "output": {"path": out.relative_to(project).as_posix(),
                               "sha256": output_sha256, "bytes": len(raw)},
                    "motion_schema": data["schema"],
                    "units": data["units"], "coordinate_system": data["coordinateSystem"],
                    "operator_authentication": "UNVERIFIED",
                    "physical_validation": "UNVERIFIED", "clinical_validation": "UNVERIFIED",
                }
                index._append_audit(
                    session_id, "motion_export_started", details,
                    actor="local_cli", outcome="started")
                intent_id = index.conn.execute(
                    "SELECT event_id FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()[0]
            # No file publication is attempted unless the intent transaction committed.
            write_motion(out, data)
            with index.transaction():
                current = read_metadata_state(index, session_id)
                if (current["status"] != "AVAILABLE"
                        or current["origin"] != state["origin"]
                        or current["context_sha256"] != state["context_sha256"]):
                    raise ValueError("EXPORT_CONTEXT_CHANGED")
                if bind_run(manifest, trc, mot)["provenance"] != data["provenance"]:
                    raise ValueError("EXPORT_SOURCE_CHANGED")
                if _bounded_export_sha256(out, len(raw)) != output_sha256:
                    raise ValueError("EXPORT_OUTPUT_CHANGED")
                index._append_audit(
                    session_id, "motion_export_published",
                    {**details, "started_event_id": intent_id},
                    actor="local_cli", outcome="published")
            return data
        finally:
            index.close()

_EXPORT_REFUSALS = {
    "TRC_INVALID": "Filtered marker input is invalid.",
    "MOT_INVALID": "Selected motion input is invalid.",
    "ARTIFACT_MISMATCH": "Native source binding does not match.",
    "MOTION_INVALID": "Motion export data is invalid.",
    "SCHEMA_UNSUPPORTED": "The existing local index schema is unsupported.",
    "AUDIT_INVALID": "The existing local audit chain is invalid.",
    "EVIDENCE_INVALID": "Verified source evidence is unavailable.",
    "EXPORT_OUTPUT_CHANGED": "Published output verification failed; preserve the output.",
    "EXPORT_AUDIT_UNAVAILABLE": "The existing local audit transaction is unavailable; preserve any output.",
    "EXPORT_PENDING_PUBLICATION": "An earlier publication remains unresolved; preserve its evidence.",
    "EXPORT_INDEX_ROOT_MISMATCH": "The project must belong to the selected local library root.",
    "EXPORT_INDEX_REQUIRED": "An existing local audit index is required.",
    "EXPORT_SESSION_MISMATCH": "The selected session and native run do not match.",
    "EXPORT_OUTPUT_LOCATION": "Native exports require a session exports motion JSON destination.",
    "OUTPUT_EXISTS": "The destination already exists; overwrite is refused.",
    "EXPORT_CONTEXT_UNAVAILABLE": "Verified current session metadata is unavailable.",
    "EXPORT_CONTEXT_CHANGED": "Current session metadata changed; preserve any published output.",
    "EXPORT_SOURCE_CHANGED": "Native source evidence changed; preserve any published output.",
    "EXPORT_CONTEXT_REQUIRES_MANIFEST": "An audit root requires an explicitly bound native run.",
    "EXPORT_IO_UNAVAILABLE": "Local export input or publication is unavailable; preserve any output.",
    "EXPORT_RUNTIME_UNAVAILABLE": "The required export runtime is unavailable.",
    "EXPORT_REFUSED": "Export verification or publication is unavailable; preserve any output.",
}


def _safe_export_refusal(error):
    """Return only a closed code and constant explanation, never exception text."""
    code = "EXPORT_REFUSED"
    if type(error) is ValueError and len(error.args) == 1 and type(error.args[0]) is str:
        prefix = error.args[0].partition(":")[0]
        if prefix in _EXPORT_REFUSALS:
            code = prefix
    elif isinstance(error, FileExistsError):
        code = "OUTPUT_EXISTS"
    elif isinstance(error, sqlite3.Error):
        code = "EXPORT_AUDIT_UNAVAILABLE"
    elif isinstance(error, OSError):
        code = "EXPORT_IO_UNAVAILABLE"
    elif isinstance(error, ImportError):
        code = "EXPORT_RUNTIME_UNAVAILABLE"
    return code + ": " + _EXPORT_REFUSALS[code]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", type=Path, default=ROOT)
    p.add_argument("--trc", type=Path)
    p.add_argument("--mot", type=Path)
    p.add_argument("--run-manifest", type=Path)
    p.add_argument("--data-root", type=Path, help="Existing local library root; native-v2 default is the project parent")
    p.add_argument("--out", type=Path)
    p.add_argument("--no-mot", action="store_true")
    a = p.parse_args()
    root = a.project.resolve()
    if a.no_mot and a.mot:
        p.error("--mot and --no-mot conflict")
    if a.run_manifest and (not a.trc or not (a.mot or a.no_mot)):
        p.error("Manifest exports require --trc and either --mot or --no-mot; no implicit discovery")
    trc = a.trc or latest(root / "pose-3d", "*_LSTM.trc") or latest(root / "pose-3d", "*filt*.trc")
    if not trc or not trc.is_file():
        p.error("TRC_INVALID: Filtered TRC not found")
    mot = None if a.no_mot else a.mot or latest(root / "kinematics", "*.mot")
    if mot is not None and not mot.is_file():
        p.error("MOT_INVALID: MOT path is invalid")
    out = a.out or root / "exports" / "kinelab.motion.json"
    if out.exists():
        p.error("OUTPUT_EXISTS: Refusing overwrite")
    try:
        if a.run_manifest:
            data = _publish_audited_motion(a.project.absolute(), trc, mot, a.run_manifest, out, a.data_root)
        else:
            if a.data_root is not None:
                raise ValueError("EXPORT_CONTEXT_REQUIRES_MANIFEST")
            data = motion(trc, mot)
            write_motion(out, data)
    except (ValueError, OSError, ImportError, sqlite3.Error) as error:
        # Preserve any intent/output after an ambiguous write; no sensitive exception text.
        p.error(_safe_export_refusal(error))
    print(f"EXPORT_OK=1 frames={len(data['frames'])} markers={len(data['markers'])} mot={mot is not None}")


if __name__ == "__main__":
    main()
