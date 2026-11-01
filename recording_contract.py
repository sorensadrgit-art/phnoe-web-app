"""Versioned raw-frame contract for explicitly synthetic, local software recording."""
import hashlib
import json
import math
import re
import sys

MAX_CHUNK_FRAMES = 16
MAX_CHUNK_BYTES = 48 * 1024
MAX_FRAMES = 54_000
MAX_DURATION_MS = 30 * 60 * 1000
SYNTHETIC_MODEL_SHA256 = "143e89f07ab2fbedb23ca2008c78f58913bc1ff12c67c81b64664307fcfc4b24"
PROTOCOLS = {name: name + "-research-v1" for name in ("squat", "lunge", "knee-extension", "balance")}
REASONS = {"NO_POSE", "LOW_CONFIDENCE", "OCCLUDED", "STALE", "DEVICE_LOST", "GAP", "MODEL_UNAVAILABLE",
           "INVALID_GEOMETRY", "MULTIPLE_PEOPLE", "PAUSED", "BACKPRESSURE", "INFERENCE_ERROR"}
REQUIRED_JOINTS = (11, 12, 23, 24, 25, 26, 27, 28)


def invalid(field, reason):
    raise ValueError(f"MEASUREMENT_INVALID: {field}: {reason}")


def canonical_json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("MEASUREMENT_INVALID: not finite standard JSON") from error


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _object(value, keys, field):
    if not isinstance(value, dict) or set(value) != set(keys):
        invalid(field, "expected exactly " + ", ".join(keys))


def _number(value, field, minimum=None, maximum=None, integer=False, *, joint=None, axis=None):
    # Landmark field names are formatted only on failure; the message text is unchanged.
    if (type(value) not in ((int,) if integer else (int, float)) or
            abs(value) > sys.float_info.max or (type(value) is float and not math.isfinite(value))):
        invalid(field if joint is None else f"{field}.landmarks[{joint}][{axis}]",
                "expected finite " + ("integer" if integer else "number"))
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        invalid(field if joint is None else f"{field}.landmarks[{joint}][{axis}]", "outside supported range")


def _text(value, pattern, field):
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        invalid(field, "unsupported identifier or format")


def validate_header(value):
    _object(value, ("schema", "session_id", "operation_id", "subject_id", "operator_id", "source", "protocol", "coordinates"), "header")
    if value["schema"] != "kinelab.recording.v1":
        invalid("schema", "expected kinelab.recording.v1")
    for key in ("session_id", "subject_id", "operator_id"):
        _text(value[key], r"synthetic-[A-Za-z0-9][A-Za-z0-9_-]{0,70}", key)
    _text(value["operation_id"], r"[a-f0-9]{32}", "operation_id")
    source = value["source"]
    _object(source, ("kind", "capture_id", "model_id", "model_version", "model_sha256"), "source")
    if source["kind"] != "synthetic":
        invalid("source.kind", "participant and measured recording remain blocked")
    if source["model_id"] != "kinelab-synthetic-33" or source["model_version"] != "1":
        invalid("source.model_id/version", "unsupported model; migration/revalidation required")
    _text(source["capture_id"], r"[a-f0-9]{32}", "source.capture_id")
    _text(source["model_sha256"], r"[a-f0-9]{64}", "source.model_sha256")
    if source["model_sha256"] != SYNTHETIC_MODEL_SHA256:
        invalid("source.model_sha256", "generator digest differs from the registered version")
    protocol = value["protocol"]
    _object(protocol, ("id", "version", "exercise", "side", "target_angle_degrees", "target_hold_ms"), "protocol")
    if not isinstance(protocol["exercise"], str) or PROTOCOLS.get(protocol["exercise"]) != protocol["id"]:
        invalid("protocol.id/exercise", "unsupported protocol")
    if type(protocol["version"]) is not int or protocol["version"] != 1:
        invalid("protocol.version", "unsupported version")
    allowed_sides = ("left", "right", "bilateral") if protocol["exercise"] == "squat" else ("left", "right")
    if protocol["side"] not in allowed_sides:
        invalid("protocol.side", "explicit supported laterality required")
    if protocol["exercise"] == "balance":
        if protocol["target_angle_degrees"] is not None:
            invalid("protocol.target_angle_degrees", "balance uses elapsed time")
        _number(protocol["target_hold_ms"], "protocol.target_hold_ms", 1, MAX_DURATION_MS, integer=True)
    else:
        _number(protocol["target_angle_degrees"], "protocol.target_angle_degrees", 0, 180)
        if protocol["target_hold_ms"] is not None:
            invalid("protocol.target_hold_ms", "repetition protocol uses angle target")
    coordinates = value["coordinates"]
    _object(coordinates, ("space", "units", "z_units", "width", "height", "mirrored"), "coordinates")
    if (coordinates["space"], coordinates["units"], coordinates["z_units"]) != ("image-normalized", "normalized", "relative"):
        invalid("coordinates", "image-normalized x/y and relative z required; not measured metres")
    for key in ("width", "height"):
        _number(coordinates[key], "coordinates." + key, 1, 16384, integer=True)
    if type(coordinates["mirrored"]) is not bool:
        invalid("coordinates.mirrored", "explicit boolean required")
    canonical_json(value)
    return value


def validate_frames(frames):
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_CHUNK_FRAMES:
        invalid("frames", f"expected 1..{MAX_CHUNK_FRAMES} frames")
    previous_sequence, previous_time = None, None
    for index, frame in enumerate(frames):
        field = f"frames[{index}]"
        _object(frame, ("sequence", "time_ms", "valid", "reasons", "landmarks"), field)
        _number(frame["sequence"], field + ".sequence", 1, MAX_FRAMES, integer=True)
        _number(frame["time_ms"], field + ".time_ms", 0, MAX_DURATION_MS)
        if previous_sequence is not None and frame["sequence"] != previous_sequence + 1:
            invalid(field + ".sequence", "noncontiguous or duplicate sequence")
        if previous_time is not None and frame["time_ms"] <= previous_time:
            invalid(field + ".time_ms", "timestamps must strictly increase")
        previous_sequence, previous_time = frame["sequence"], frame["time_ms"]
        if type(frame["valid"]) is not bool:
            invalid(field + ".valid", "boolean required")
        reasons = frame["reasons"]
        if (not isinstance(reasons, list) or any(not isinstance(reason, str) or reason not in REASONS for reason in reasons)
                or len(set(reasons)) != len(reasons) or bool(reasons) == frame["valid"]):
            invalid(field + ".reasons", "invalid, missing or contradictory validity reasons")
        points = frame["landmarks"]
        if points is None:
            if frame["valid"]:
                invalid(field + ".landmarks", "missing observation cannot be valid")
            continue
        if not isinstance(points, list) or len(points) != 33:
            invalid(field + ".landmarks", "expected 33 points or null")
        for joint, point in enumerate(points):
            if point is None:
                continue
            if not isinstance(point, list) or len(point) != 4:
                invalid(f"{field}.landmarks[{joint}]", "expected x,y,z,confidence or null")
            for axis, number in enumerate(point):
                _number(number, field, None if axis == 2 else 0, None if axis == 2 else 1, joint=joint, axis=axis)
        if frame["valid"]:
            if any(points[joint] is None or points[joint][3] < .5 for joint in REQUIRED_JOINTS):
                invalid(field + ".valid", "required joint missing or confidence below 0.5")
            for a, b in ((11, 23), (12, 24), (23, 25), (24, 26), (25, 27), (26, 28)):
                if points[a][:2] == points[b][:2]:
                    invalid(field + ".valid", "degenerate image geometry")
    if len(canonical_json(frames).encode("utf-8")) > MAX_CHUNK_BYTES:
        invalid("frames", "encoded chunk exceeds 48 KiB")
    return frames
