"""Verify decoded normalized trial extent and native frame derivation without project writes.

Only normalized media is decoded. Original camera frame equality remains UNVERIFIED.
Private temporary media snapshots bind the decoder input to already verified bytes.
"""
import copy
import hashlib
import json
import math
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise
from pathlib import Path

from session_contract import sha256_file, strict_json_loads
from take_acceptance import TakeAcceptanceError, checked_path

POLICY = "kinelab.pipeline-quality.v4"
NATIVE_FRAME_POLICY = {
    "schema": "kinelab.native-frame-policy.v1",
    "raw": "all-decoded-trial-frames",
    "synchronization": "native-source-minus-offset-positive",
    "association": "derived-common-positive-range",
    "triangulation": "derived-common-positive-range",
    "frame_rate": 30,
}
CAMERAS = ("cam01", "cam02")
NATIVE_STAGES = ("poseEstimation", "synchronization", "personAssociation")


def _refuse(detail):
    raise ValueError("QUALITY_UNVERIFIED: decoded source coverage: " + detail)


def _safe_path(project, relative):
    project = Path(project).absolute()
    if (not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative
            or Path(relative).is_absolute() or ".." in Path(relative).parts):
        _refuse("unsafe source path")
    path = project / relative
    try:
        checked_path(path)
    except TakeAcceptanceError:
        _refuse("source path is not a contained non-link")
    if (not path.resolve().is_relative_to(project)
            or any(p.is_symlink() or getattr(p, "is_junction", lambda: False)()
                   for p in (path, *path.parents) if p.is_relative_to(project) and p != project)):
        _refuse("source path is not a contained non-link")
    return path


def _buffer(project, relative):
    from pipeline_quality import _read_frame_bytes
    return _read_frame_bytes(_safe_path(project, relative))


def _object(raw):
    value = strict_json_loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        _refuse("source object required")
    return value


def reject_configured_crop(project):
    """Native raw pose must cover all decoded frames before any synchronization crop."""
    import tomllib
    config = tomllib.loads(_buffer(project, "Config.toml").decode("utf-8-sig"))
    value = config.get("project", {}).get("frame_range", [])
    if value not in ([], "all", "auto"):
        _refuse("configured frame_range crop is unsupported; full raw decoded range required")


def _decoded_snapshot(project, relative, digest):
    """Inspect a private snapshot of the exact pinned media bytes, never a mutable path alias."""
    from normalize_capture import _validate_output, inspect_video
    path = _safe_path(project, relative)
    before = path.stat(follow_symlinks=False)
    observed = hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix="kinelab-decoded-source-") as temporary:
        target = Path(temporary) / path.name
        with path.open("rb") as source, target.open("xb") as output:
            opened = os.fstat(source.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                    before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
                _refuse("media changed before capture")
            while block := source.read(1024 * 1024):
                observed.update(block)
                output.write(block)
            closed = os.fstat(source.fileno())
        after = path.stat(follow_symlinks=False)
        if (observed.hexdigest() != digest
                or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                != (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns)
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            _refuse("media changed during capture")
        metadata = inspect_video(target)
        _validate_output(metadata, relative)
        if sha256_file(path) != digest or sha256_file(target) != digest:
            _refuse("media changed during independent decode")
    return metadata


def capture_normalization(project, identity, expected=None, *, decode=False):
    from normalize_capture import ROLES
    project = Path(project).absolute()
    raw = _buffer(project, "normalization.json")
    binding = {"path": "normalization.json", "sha256": hashlib.sha256(raw).hexdigest()}
    if expected is not None and expected != binding:
        _refuse("captured normalization bytes changed")
    if not isinstance(identity.get("inputs"), dict) or set(identity["inputs"]) != set(ROLES):
        _refuse("all six original capture identities required")
    normalized = _object(raw)
    if (normalized.get("schema") != "kinelab.normalization.v1"
            or any(normalized.get(key) != value for key, value in identity.items())):
        _refuse("normalization identity differs")
    outputs = normalized.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != set(ROLES):
        _refuse("all six normalized captures required")
    def validate(role, relative):
        item = outputs[role]
        if (not isinstance(item, dict) or item.get("path") != relative
                or not isinstance(item.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
                or sha256_file(_safe_path(project, relative)) != item["sha256"]):
            _refuse("normalized media binding differs")
        if role.endswith("_trial") and decode:
            observed = _decoded_snapshot(project, relative, item["sha256"])
            count, times = item.get("frame_count"), item.get("timestamps")
            if (type(count) is not int or count <= 0 or count != observed["frame_count"]
                    or not isinstance(times, list) or len(times) != count
                    or any(type(t) not in (int, float) or not math.isfinite(t) for t in times)
                    or times != observed["timestamps"]
                    or any(item.get(key) != observed[key] for key in ("width", "height", "fps"))):
                _refuse("normalization count/timestamps/geometry differ from independent decode")
            return count

    counts = {}
    trials = []
    for role, relative in ROLES.items():
        if decode and role.endswith("_trial"):
            trials.append((role, relative))
        else:
            validate(role, relative)
    if decode:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = []
            try:
                for role, relative in trials:
                    futures.append((role, pool.submit(validate, role, relative)))
                for role, future in futures:
                    counts[role.removesuffix("_trial")] = future.result()
            except BaseException:
                pool.shutdown(wait=False, cancel_futures=True)
                raise
        for role, relative in trials:
            if sha256_file(_safe_path(project, relative)) != outputs[role]["sha256"]:
                _refuse("normalized media binding differs")
    if hashlib.sha256(_buffer(project, "normalization.json")).hexdigest() != binding["sha256"]:
        _refuse("normalization changed during verification")
    return {"binding": binding, "outputs": outputs, "counts": counts}


def native_pose_index(camera, name):
    match = re.fullmatch(re.escape(camera) + r"_([0-9]{6,})\.json", name)
    if match is None:
        _refuse("non-native pose filename")
    index = int(match.group(1))
    if name != f"{camera}_{index:06d}.json":
        _refuse("noncanonical native pose padding")
    return index


def _pose(raw):
    value = _object(raw)
    people = value.get("people")
    if not isinstance(people, list):
        _refuse("OpenPose people list required")
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _stage_files(project, record, stage, override=None):
    item = next((s for s in record.get("stages", []) if isinstance(s, dict) and s.get("name") == stage), None)
    if override is None:
        if (not isinstance(item, dict) or item.get("status") != "passed"
                or not isinstance(item.get("quality"), dict) or item["quality"].get("ok") is not True):
            _refuse("accepted upstream stage required: " + stage)
        references = item.get("artifacts")
    else:
        references = override
    if not isinstance(references, list) or not references:
        _refuse("stage artifact bindings required")
    folder = {"poseEstimation": "pose", "synchronization": "pose-sync", "personAssociation": "pose-associated"}[stage]
    actual = {p.relative_to(project).as_posix() for p in (project / folder).rglob("*.json")}
    bound = {}
    by_camera = {camera: {} for camera in CAMERAS}
    for ref in references:
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                or not isinstance(ref.get("path"), str) or ref["path"] in bound):
            _refuse("ambiguous stage artifact binding")
        relative = ref.get("path")
        if not isinstance(relative, str):
            _refuse("stage artifact path required")
        parts = Path(relative).parts
        camera = parts[1].removesuffix("_json") if len(parts) == 3 else None
        if camera not in CAMERAS or parts[:2] != (folder, camera + "_json"):
            _refuse("non-native camera artifact path")
        index = native_pose_index(camera, parts[2])
        raw = _buffer(project, relative)
        if hashlib.sha256(raw).hexdigest() != ref.get("sha256") or index in by_camera[camera]:
            _refuse("stage content changed or index duplicated")
        bound[relative] = raw
        by_camera[camera][index] = raw
    if set(bound) != actual:
        _refuse("stage artifact membership changed")
    return by_camera, item


def _offsets(project, report, counts):
    from pipeline_quality import _log_range, verify_log_binding
    if not isinstance(report, dict) or report.get("ok") is not True or report.get("policy") != POLICY:
        _refuse("accepted synchronization quality required")
    verify_log_binding(project, report.get("log"))
    binding = report["log"]
    log, _ = _log_range(project, [binding["start"], binding["end"], binding["sha256"]])
    matches = re.findall(r"Camera (cam0[12]) and (cam0[12]):\s*(-?\d+) frames offset[^\n]*correlation\s+([-\d.]+)", log)
    cameras, reference = report.get("cameras"), report.get("reference")
    if not matches or not isinstance(cameras, dict) or set(cameras) != set(CAMERAS) or reference not in CAMERAS:
        _refuse("native synchronization evidence required")
    offsets = {}
    for camera in CAMERAS:
        entry = cameras[camera]
        if not isinstance(entry, dict) or type(entry.get("offset_frames")) is not int:
            _refuse("integer native offset required")
        offsets[camera] = entry["offset_frames"]
        residuals = [entry.get("start_residual_frames"), entry.get("end_residual_frames")]
        if (any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1 for v in residuals)
                or abs(residuals[1] - residuals[0]) > 1):
            _refuse("synchronization residual/drift exceeds existing threshold")
    native_ref, other, offset, correlation = matches[-1]
    if (native_ref != reference or native_ref == other or offsets[reference] != 0
            or int(offset) != offsets[other] or not 0.85 <= float(correlation.rstrip(".")) <= 1):
        _refuse("accepted offset differs from native log")
    pairs = report.get("source_frame_pairs")
    if not isinstance(pairs, list):
        _refuse("source frame pairs required")
    observed = {camera: [] for camera in CAMERAS}
    for pair in pairs:
        if not isinstance(pair, dict) or pair.get("camera") not in CAMERAS:
            _refuse("invalid source frame pair")
        camera = pair["camera"]
        source, synchronized = pair.get("source_frame_index"), pair.get("synchronized_frame_index")
        if (type(source) is not int or type(synchronized) is not int or not 0 <= source < counts[camera]
                or synchronized < 0 or not 0 <= synchronized + offsets[camera] < counts[camera]
                or abs(source - synchronized - offsets[camera]) > 1):
            _refuse("source frame pair outside decoded extent")
        observed[camera].append((synchronized, source, source - synchronized - offsets[camera]))
    for camera, values in observed.items():
        values.sort()
        if (len(values) < 2 or any(b[0] <= a[0] or b[1] <= a[1] for a, b in pairwise(values))
                or abs(values[-1][2] - values[0][2]) > 1):
            _refuse("ordered independent start/end source pairs required")
        if (values[0][2] != cameras[camera]["start_residual_frames"]
                or values[-1][2] != cameras[camera]["end_residual_frames"]):
            _refuse("declared synchronization residuals disagree with observed source pairs")
    return offsets


def verify_source_coverage(project, identity, record, *, through, artifacts=None, quality=None):
    """Recompute decoded/native membership on every call; stored summaries are never authority."""
    project = Path(project).absolute()
    reject_configured_crop(project)
    if record.get("quality_policy") != POLICY or record.get("native_frame_policy") != NATIVE_FRAME_POLICY:
        _refuse("current native frame policy required")
    binding = record.get("normalization")
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        _refuse("captured normalization binding required")
    captured = capture_normalization(project, identity, binding, decode=True)
    counts = captured["counts"]
    summary = {
        "schema": "kinelab.decoded-source-coverage.v1", "normalization": captured["binding"],
        "native_frame_policy": copy.deepcopy(NATIVE_FRAME_POLICY),
        "cameras": {camera: {"path": captured["outputs"][camera + "_trial"]["path"],
                             "sha256": captured["outputs"][camera + "_trial"]["sha256"],
                             "decoded_frame_count": counts[camera], "source_range": [0, counts[camera]],
                             "offset_frames": None, "synchronized_range": None} for camera in CAMERAS},
        "common_range": None, "associated_missing_frames": {camera: [] for camera in CAMERAS},
        "physical_source_frame_equality": "UNVERIFIED",
    }
    if through not in (*NATIVE_STAGES, "triangulation", "filtering", "markerAugmentation", "kinematics"):
        _refuse("unsupported source coverage stage")
    stop = NATIVE_STAGES.index(through) if through in NATIVE_STAGES else 2
    raw_files = sync_files = None
    for index, stage in enumerate(NATIVE_STAGES[:stop + 1]):
        current = stage == through and artifacts is not None
        files, item = _stage_files(project, record, stage, artifacts if current else None)
        if stage == "poseEstimation":
            raw_files = files
            for camera in CAMERAS:
                if set(files[camera]) != set(range(counts[camera])):
                    _refuse("raw pose membership differs from decoded extent")
                for raw in files[camera].values():
                    for person in _pose(raw)["people"]:
                        values = person.get("pose_keypoints_2d") if isinstance(person, dict) else None
                        if (not isinstance(values, list) or not values or len(values) % 3
                                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
                                or any(not 0 <= v <= 1 for v in values[2::3])):
                            _refuse("invalid raw pose keypoints/confidence")
        elif stage == "synchronization":
            report = quality if current else item.get("quality")
            offsets = _offsets(project, report, counts)
            sync_files = files
            for camera in CAMERAS:
                offset = offsets[camera]
                first, end = max(1, -offset), counts[camera] - offset
                summary["cameras"][camera].update(offset_frames=offset, synchronized_range=[first, end])
                expected = {i - offset: raw for i, raw in raw_files[camera].items() if i - offset > 0}
                if files[camera] != expected:
                    _refuse("synchronized membership/content differs from native raw-to-sync mapping")
            first = max(summary["cameras"][camera]["synchronized_range"][0] for camera in CAMERAS)
            end = min(summary["cameras"][camera]["synchronized_range"][1] for camera in CAMERAS)
            if first >= end:
                _refuse("native synchronized intersection is empty")
            summary["common_range"] = [first, end]
        else:
            first, end = summary["common_range"]
            allowed = set(range(first, end))
            for camera in CAMERAS:
                present = set(files[camera])
                if not present <= allowed or not {first, end - 1} <= present:
                    _refuse("associated endpoints/membership differ from decoded common range")
                summary["associated_missing_frames"][camera] = sorted(allowed - present)
                for frame, raw in files[camera].items():
                    source, selected = _pose(sync_files[camera][frame]), _pose(raw)
                    if _canonical({k: v for k, v in selected.items() if k != "people"}) != _canonical({k: v for k, v in source.items() if k != "people"}):
                        _refuse("associated envelope differs from synchronized source")
                    people = selected["people"]
                    if people == [{}]:
                        continue
                    if len(people) > 1 or any(_canonical(p) not in {_canonical(p) for p in source["people"]} for p in people):
                        _refuse("associated person is not an unchanged synchronized selection")
        stored = quality if current else item.get("quality")
        if not current and (not isinstance(stored, dict) or stored.get("source_coverage") != summary):
            _refuse("stored source coverage differs from independently decoded derivation: " + stage)
    if hashlib.sha256(_buffer(project, "normalization.json")).hexdigest() != binding["sha256"]:
        _refuse("normalization changed after native verification")
    return summary


def verify_trc_extent(project, reference, summary):
    """Use the existing parser on one pinned TRC buffer and enforce the derived native range."""
    from export_motion import parse_trc
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        _refuse("one bound unfiltered TRC required")
    raw = _buffer(project, reference.get("path"))
    if hashlib.sha256(raw).hexdigest() != reference.get("sha256"):
        _refuse("TRC bytes changed")
    with tempfile.TemporaryDirectory(prefix="kinelab-trc-extent-") as temporary:
        captured = Path(temporary) / "captured.trc"
        captured.write_bytes(raw)
        _, frames, fps = parse_trc(captured)
    indexes = [round(frame["t"] * 30) for frame in frames]
    if (fps != 30 or not indexes
            or any(not math.isclose(frame["t"], index / 30, rel_tol=0, abs_tol=1e-6)
                   for frame, index in zip(frames, indexes))
            or [indexes[0], indexes[-1] + 1] != summary.get("common_range")):
        _refuse("TRC endpoints/grid differ from decoded common range")
    if hashlib.sha256(_buffer(project, reference["path"])).hexdigest() != reference["sha256"]:
        _refuse("TRC changed during verification")


def stage_frame_overrides(project, identity, record, stage):
    reject_configured_crop(project)
    if stage == "poseEstimation":
        capture_normalization(project, identity, record.get("normalization"), decode=True)
        return {"frame_range": [], "frame_rate": 30}
    if stage in ("personAssociation", "triangulation"):
        summary = verify_source_coverage(project, identity, record, through="synchronization")
        return {"frame_range": summary["common_range"], "frame_rate": 30}
    return {}
