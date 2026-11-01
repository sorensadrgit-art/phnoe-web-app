"""Software quality checks for the native OpenSim kinematics stage.

``validate_kinematics_stage`` re-runs the fitted model's own forward kinematics
for every IK frame and compares the resulting model marker positions with the
TRC markers that inverse kinematics consumed.  The result is a software
consistency check of derived research data; it is not clinical accuracy,
physical calibration, or diagnostic validation.

Decisions encoded here (see ``limitations`` in every result):

* Units.  MOT rotational coordinates (``Coordinate.Rotational``) are converted
  from degrees when ``inDegrees=yes``; translational coordinates are always
  metres.  This mirrors OpenSim's degree conversion, which only rescales
  rotational coordinates.  ``Coupled`` coordinates have no unambiguous degree
  rule, so a degree-valued MOT containing one is rejected (fail closed).
* Ranges.  Each value must lie within the model-declared ``range`` of its
  coordinate (plus ``RANGE_TOLERANCE`` for file rounding), whether or not the
  coordinate is clamped.  No generic clinical joint limits are used.  For a
  clamped coordinate an excursion means the solution contradicts the solver
  bounds; for an unclamped one it means the solution left the range the fitted
  model itself declares plausible.  Both fail closed.
* Locked coordinates must stay at their model default value.
* Times.  MOT and TRC times must be finite and strictly increasing, TRC
  intervals must agree with the declared DataRate, and every MOT row must pair
  one-to-one with a TRC frame within a quarter of the shortest TRC interval
  (same frame count, same span).  IK over a sub-range is therefore rejected.
* Markers.  ``DEFAULT_MIN_MATCHED_MARKERS = 3``: three non-collinear points are
  the minimum that determines a rigid segment's 6-DoF pose.  With fewer
  matched finite markers in a frame the residual can be made arbitrarily small
  and says nothing about the fit, so every frame must reach the minimum.
* Residuals.  The gate is the overall RMS over all matched finite
  (frame, marker) pairs, default 0.020 m (the existing software policy
  target).  A single residual above ``IMPOSSIBLE_RESIDUAL_FACTOR`` times that
  threshold is also rejected as an impossible fit for a fitted model.
"""
from __future__ import annotations

import hashlib
import math
import re
from itertools import pairwise
from pathlib import Path

KINEMATICS_QUALITY_POLICY = "kinelab.kinematics-quality.v1"
CLASSIFICATION = "derived_research_only"
UNAVAILABLE = "KINEMATICS_QUALITY_UNAVAILABLE"
REJECTED = "KINEMATICS_QUALITY_REJECTED"

DEFAULT_MAX_RMS_MARKER_ERROR_M = 0.020
DEFAULT_MIN_MATCHED_MARKERS = 3
IMPOSSIBLE_RESIDUAL_FACTOR = 10.0
RANGE_TOLERANCE = 1e-5          # rad or m; absorbs fixed-precision MOT text
DATA_RATE_RELATIVE_TOLERANCE = 0.01
TIME_PAIRING_FRACTION = 0.25

LIMITATIONS = [
    "software residual check only; not clinical accuracy, physical calibration, or diagnostic validation",
    ("residuals compare the fitted model's own forward kinematics with the supplied TRC; "
     "they cannot detect errors shared by the TRC and the model (triangulation, calibration, scaling)"),
    "coordinate bounds are the fitted model's declared ranges, not clinical joint limits",
    "classification derived_research_only; CLINICAL_VALIDATION: UNVERIFIED",
]

_ROTATIONAL, _TRANSLATIONAL, _COUPLED = 1, 2, 3


class _Reject(Exception):
    pass


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(project, value, label, errors):
    """Return (resolved path or None, source entry)."""
    entry = {"path": None, "sha256": None}
    if value is None or (isinstance(value, str) and not value.strip()):
        errors.append(f"{label}: path is required")
        return None, entry
    try:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = project / candidate
        resolved = candidate.resolve()
        relative = resolved.relative_to(project)
    except ValueError:
        errors.append(f"{label}: path resolves outside project")
        return None, entry
    except (OSError, TypeError) as exc:
        errors.append(f"{label}: path cannot be resolved ({exc})")
        return None, entry
    entry["path"] = relative.as_posix()
    if not resolved.is_file():
        errors.append(f"{label}: file is missing: {entry['path']}")
        return None, entry
    try:
        entry["sha256"] = _sha256(resolved)
    except OSError as exc:
        errors.append(f"{label}: file cannot be read ({exc})")
        return None, entry
    return resolved, entry


def _check_times(times, label):
    if not times or any(not _finite(t) for t in times):
        raise _Reject(f"{label}: empty or nonfinite time values")
    if any(b <= a for a, b in pairwise(times)):
        raise _Reject(f"{label}: time values must strictly increase")


def _row(raw, width, label):
    # Pose2Sim appends a trailing delimiter; only surplus empty fields are allowed.
    if len(raw) < width or any(x.strip() for x in raw[width:]):
        raise _Reject(f"{label}: row length does not match the declared shape")
    return [x.strip() for x in raw[:width]]


def _parse_trc(path):
    label = "TRC"
    rows = [line.split("\t") for line in Path(path).read_text(encoding="utf-8-sig").splitlines()]
    if len(rows) < 6 or [x.strip() for x in rows[0][:3]] != ["PathFileType", "4", "(X/Y/Z)"]:
        raise _Reject("TRC: expected a tab-delimited PathFileType 4 (X/Y/Z) file")
    keys = [x.strip() for x in rows[1]]
    while keys and not keys[-1]:
        keys.pop()
    head = dict(zip(keys, _row(rows[2], len(keys), label)))
    try:
        count = int(head.get("NumMarkers", ""))
        declared_frames = int(head.get("NumFrames", ""))
    except ValueError:
        raise _Reject("TRC: NumMarkers and NumFrames must be integers") from None
    rate = _number(head.get("DataRate"))
    if count < 1 or declared_frames < 1 or rate is None or rate <= 0:
        raise _Reject("TRC: NumMarkers, NumFrames and DataRate must be positive")
    units = head.get("Units")
    if units not in ("m", "mm"):
        raise _Reject(f"TRC: Units must be m or mm, got {units!r}")
    scale = 0.001 if units == "mm" else 1.0
    width = 2 + 3 * count
    header = _row(rows[3], width, label)
    if header[:2] != ["Frame#", "Time"]:
        raise _Reject("TRC: expected Frame# and Time columns")
    names = [header[2 + 3 * i] for i in range(count)]
    if not all(names) or len(set(names)) != count:
        raise _Reject("TRC: missing or duplicate marker names")
    frames = []
    for raw in rows[5:]:
        if not any(x.strip() for x in raw):
            continue
        cells = _row(raw, width, label)
        time = _number(cells[1])
        if time is None:
            raise _Reject("TRC: nonfinite or malformed time value")
        points = []
        for i in range(count):
            triple = cells[2 + 3 * i:5 + 3 * i]
            if triple == ["", "", ""] or all(x.lower() == "nan" for x in triple):
                points.append(None)
                continue
            xyz = [_number(x) for x in triple]
            if any(v is None for v in xyz):
                raise _Reject("TRC: marker coordinates must be finite triples or entirely blank")
            points.append(tuple(v * scale for v in xyz))
        frames.append((time, points))
    if len(frames) != declared_frames:
        raise _Reject(f"TRC: NumFrames={declared_frames} but {len(frames)} data frames were found")
    times = [t for t, _ in frames]
    _check_times(times, label)
    expected = 1.0 / rate
    if any(abs((b - a) - expected) > DATA_RATE_RELATIVE_TOLERANCE * expected for a, b in pairwise(times)):
        raise _Reject("TRC: time intervals disagree with the declared DataRate")
    return {"names": names, "frames": frames, "rate": rate, "units": units}


def _parse_mot(path):
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    stop = next((i for i, line in enumerate(lines) if line.strip().lower() == "endheader"), None)
    if stop is None:
        raise _Reject("MOT: missing endheader")
    head = {}
    for line in lines[:stop]:
        match = re.fullmatch(r"\s*(\w+)\s*=\s*(.*?)\s*", line)
        if match:
            key = match[1].lower()
            if key in head:
                raise _Reject(f"MOT: duplicate header key {match[1]!r}")
            head[key] = match[2]
    in_degrees = head.get("indegrees", "").lower()
    if in_degrees not in ("yes", "no"):
        raise _Reject("MOT: inDegrees header must explicitly be yes or no")
    body = [line.split() for line in lines[stop + 1:] if line.strip()]
    if len(body) < 2:
        raise _Reject("MOT: missing column labels or data rows")
    columns = body[0]
    if columns[0].lower() != "time" or len(set(columns)) != len(columns) or len(columns) < 2:
        raise _Reject("MOT: expected unique column labels starting with time")
    rows = []
    for raw in body[1:]:
        if len(raw) != len(columns):
            raise _Reject("MOT: row length does not match column labels")
        values = [_number(x) for x in raw]
        if any(v is None for v in values):
            raise _Reject("MOT: every time and coordinate value must be finite")
        rows.append(values)
    for key, expected in (("nrows", len(rows)), ("datarows", len(rows)),
                          ("ncolumns", len(columns)), ("datacolumns", len(columns))):
        if key in head and head[key].strip() != str(expected):
            raise _Reject(f"MOT: header {key}={head[key]} disagrees with the data ({expected})")
    _check_times([r[0] for r in rows], "MOT")
    return {"columns": columns[1:], "rows": rows, "in_degrees": in_degrees == "yes"}


def _pair_times(mot_times, trc_times):
    if len(mot_times) != len(trc_times):
        raise _Reject(f"time: MOT has {len(mot_times)} frames but TRC has {len(trc_times)} frames")
    tolerance = TIME_PAIRING_FRACTION * min((b - a for a, b in pairwise(trc_times)), default=1.0)
    worst = max(abs(a - b) for a, b in zip(mot_times, trc_times))
    if worst > tolerance + 1e-12:
        raise _Reject(f"time: MOT timestamps do not match TRC frames (max offset {worst:.6g} s > {tolerance:.6g} s)")
    return worst


def _empty_metrics():
    return {"frames": 0, "coordinates": 0, "matched_markers": 0, "rms_marker_error_m": None,
            "max_marker_error_m": None, "max_frame_rms_marker_error_m": None,
            "min_matched_markers_required": None, "min_matched_markers_in_frame": None,
            "max_rms_marker_error_m": None, "trc_units": None, "mot_in_degrees": None,
            "max_time_offset_s": None, "model_markers": [], "matched_marker_names": [],
            "unmatched_trc_markers": [], "model_markers_absent_from_trc": [],
            "range_violations": 0, "range_policy": "model-declared range, clamped or not",
            "residual_label": "software forward-kinematics marker residual, not clinical accuracy"}


def _validate(project, model_path, mot_path, trc_path, max_rms, min_markers, result):
    errors, metrics, sources = result["errors"], result["metrics"], result["sources"]
    if not _finite(max_rms) or max_rms <= 0:
        errors.append("max_rms_marker_error_m must be a finite positive number")
    metrics["max_rms_marker_error_m"] = max_rms if _finite(max_rms) else None
    if min_markers is None:
        min_markers = DEFAULT_MIN_MATCHED_MARKERS
    if isinstance(min_markers, bool) or not isinstance(min_markers, int) or min_markers < 1:
        errors.append("min_matched_markers must be an integer >= 1 (None selects the documented default)")
        min_markers = None
    metrics["min_matched_markers_required"] = min_markers

    try:
        project = Path(project).resolve()
    except (OSError, TypeError) as exc:
        errors.append(f"project: cannot be resolved ({exc})")
        return None
    if not project.is_dir():
        errors.append("project: directory does not exist")
    paths = {}
    for key, value in (("model", model_path), ("mot", mot_path), ("trc", trc_path)):
        paths[key], sources[key] = _resolve(project, value, key, errors)

    trc = mot = None
    if paths["trc"] is not None:
        try:
            trc = _parse_trc(paths["trc"])
            metrics["trc_units"] = trc["units"]
        except (_Reject, OSError, UnicodeDecodeError) as exc:
            errors.append(str(exc))
    if paths["mot"] is not None:
        try:
            mot = _parse_mot(paths["mot"])
            metrics["mot_in_degrees"] = mot["in_degrees"]
            metrics["frames"] = len(mot["rows"])
        except (_Reject, OSError, UnicodeDecodeError) as exc:
            errors.append(str(exc))
    if trc is not None and mot is not None:
        try:
            metrics["max_time_offset_s"] = _pair_times([r[0] for r in mot["rows"]], [t for t, _ in trc["frames"]])
        except _Reject as exc:
            errors.append(str(exc))

    try:
        import opensim as osim
    except Exception as exc:  # noqa: BLE001  ImportError or a broken native extension; reported as unavailable
        result["unavailable"] = f"opensim import failed: {type(exc).__name__}: {exc}"
        return None
    if errors or paths["model"] is None:
        return None

    try:
        model = osim.Model(str(paths["model"]))
        state = model.initSystem()
    except Exception as exc:  # noqa: BLE001  OpenSim native calls can raise any exception type; fail-closed into errors
        errors.append(f"model: OpenSim could not load the fitted model ({type(exc).__name__}: {exc})")
        return None

    coord_set = model.getCoordinateSet()
    coords, aliases = [], {}
    for i in range(coord_set.getSize()):
        coord = coord_set.get(i)
        coords.append(coord)
        aliases[coord.getName()] = coord
        aliases[coord.getAbsolutePathString() + "/value"] = coord
    metrics["coordinates"] = len(coords)
    if not coords:
        errors.append("model: fitted model declares no coordinates")
    column_coord = []
    unknown = [c for c in mot["columns"] if c not in aliases]
    if unknown:
        errors.append(f"MOT: unknown coordinate column(s) not in model: {unknown}")
    mapped = [aliases[c].getName() for c in mot["columns"] if c in aliases]
    if len(set(mapped)) != len(mapped):
        errors.append("MOT: more than one column maps to the same model coordinate")
    missing = [c.getName() for c in coords if c.getName() not in mapped]
    if missing:
        errors.append(f"MOT: missing model coordinate(s): {missing}")
    if errors:
        return None
    for name in mot["columns"]:
        coord = aliases[name]
        kind = coord.getMotionType()
        if kind == _ROTATIONAL:
            factor = math.pi / 180.0 if mot["in_degrees"] else 1.0
        elif kind == _TRANSLATIONAL or kind == _COUPLED and not mot["in_degrees"]:
            factor = 1.0
        else:
            errors.append(f"MOT: coordinate {coord.getName()!r} has motion type {kind} with no unambiguous "
                          "degree conversion")
            continue
        column_coord.append((coord, factor))
    if errors:
        return None

    violations = []
    frames_q = []
    for row in mot["rows"]:
        values = []
        for (coord, factor), raw in zip(column_coord, row[1:]):
            value = raw * factor
            lo, hi = coord.getRangeMin(), coord.getRangeMax()
            if value < lo - RANGE_TOLERANCE or value > hi + RANGE_TOLERANCE:
                violations.append((coord.getName(), row[0], value, lo, hi, bool(coord.get_clamped())))
            if coord.getLocked(state) and abs(value - coord.getDefaultValue()) > RANGE_TOLERANCE:
                errors.append(f"MOT: locked coordinate {coord.getName()!r} departs from its model default "
                              f"at t={row[0]:.6g}")
            values.append(value)
        frames_q.append(values)
    metrics["range_violations"] = len(violations)
    for name in sorted({v[0] for v in violations}):
        first = next(v for v in violations if v[0] == name)
        count = sum(1 for v in violations if v[0] == name)
        errors.append(f"MOT: coordinate {name!r} outside model range [{first[3]:.6g}, {first[4]:.6g}] "
                      f"(clamped={first[5]}) in {count} frame(s), first t={first[1]:.6g} value={first[2]:.6g}")

    marker_set = model.getMarkerSet()
    model_markers = [marker_set.get(i).getName() for i in range(marker_set.getSize())]
    metrics["model_markers"] = model_markers
    trc_index = {name: i for i, name in enumerate(trc["names"])}
    matched = [n for n in model_markers if n in trc_index]
    metrics["matched_markers"] = len(matched)
    metrics["matched_marker_names"] = matched
    metrics["unmatched_trc_markers"] = [n for n in trc["names"] if n not in set(model_markers)]
    metrics["model_markers_absent_from_trc"] = [n for n in model_markers if n not in trc_index]
    if min_markers is None:
        return None
    if len(matched) < min_markers:
        errors.append(f"markers: only {len(matched)} TRC marker name(s) matched model markers; "
                      f"at least {min_markers} required")
        return None

    sq_sum, count, worst, worst_frame_rms, fewest = 0.0, 0, 0.0, 0.0, None
    short_frames = []
    for f, values in enumerate(frames_q):
        for (coord, _), value in zip(column_coord, values):
            if not coord.getLocked(state):
                coord.setValue(state, value, False)
        model.realizePosition(state)
        _, points = trc["frames"][f]
        frame_sq, frame_n = 0.0, 0
        for name in matched:
            observed = points[trc_index[name]]
            if observed is None:
                continue
            loc = marker_set.get(name).getLocationInGround(state)
            predicted = (loc.get(0), loc.get(1), loc.get(2))
            if not all(math.isfinite(v) for v in predicted):
                errors.append(f"markers: nonfinite model marker {name!r} at frame {f}")
                return None
            d2 = sum((p - o) ** 2 for p, o in zip(predicted, observed))
            frame_sq += d2
            frame_n += 1
            worst = max(worst, math.sqrt(d2))
        fewest = frame_n if fewest is None else min(fewest, frame_n)
        if frame_n < min_markers:
            short_frames.append(f)
        if frame_n:
            worst_frame_rms = max(worst_frame_rms, math.sqrt(frame_sq / frame_n))
        sq_sum += frame_sq
        count += frame_n
    metrics["min_matched_markers_in_frame"] = fewest
    if short_frames:
        errors.append(f"markers: {len(short_frames)} frame(s) have fewer than {min_markers} matched finite "
                      f"markers (first frame {short_frames[0]})")
    if count == 0:
        errors.append("markers: no matched finite marker observations")
        return None
    rms = math.sqrt(sq_sum / count)
    metrics["rms_marker_error_m"] = rms
    metrics["max_marker_error_m"] = worst
    metrics["max_frame_rms_marker_error_m"] = worst_frame_rms
    metrics["marker_observations"] = count
    if _finite(max_rms) and max_rms > 0:
        if rms > max_rms:
            errors.append(f"markers: RMS marker residual {rms:.6g} m exceeds {max_rms:.6g} m "
                          "(software residual, not clinical accuracy)")
        if worst > IMPOSSIBLE_RESIDUAL_FACTOR * max_rms:
            errors.append(f"markers: single marker residual {worst:.6g} m exceeds "
                          f"{IMPOSSIBLE_RESIDUAL_FACTOR:g}x the RMS limit; impossible for a fitted model")
    return True


def validate_kinematics_stage(project, *, model_path, mot_path, trc_path,
                              max_rms_marker_error_m=DEFAULT_MAX_RMS_MARKER_ERROR_M, min_matched_markers=None):
    """Validate native IK output against the fitted model and the consumed TRC. Never raises."""
    result = {
        "ok": False,
        "policy": KINEMATICS_QUALITY_POLICY,
        "classification": CLASSIFICATION,
        "code": REJECTED,
        "errors": [],
        "metrics": _empty_metrics(),
        "sources": {key: {"path": None, "sha256": None} for key in ("model", "mot", "trc")},
        "limitations": list(LIMITATIONS),
    }
    completed = None
    try:
        completed = _validate(project, model_path, mot_path, trc_path,
                              max_rms_marker_error_m, min_matched_markers, result)
    except Exception as exc:  # noqa: BLE001  the contract is fail-closed, never raise
        result["errors"].append(f"internal: check aborted ({type(exc).__name__}: {exc})")
        completed = None
    unavailable = result.pop("unavailable", None)
    if result["errors"]:
        result["code"] = REJECTED
        if unavailable:
            result["errors"].append(unavailable)
    elif unavailable:
        result["code"] = UNAVAILABLE
        result["errors"].append(unavailable)
    elif completed is True:
        result["ok"] = True
        result["code"] = None
    else:
        result["errors"].append("internal: checks did not complete")
    return result
