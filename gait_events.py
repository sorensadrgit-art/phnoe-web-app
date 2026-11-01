"""Conservative, versioned 2D gait *candidate* extraction and manual comparison.

Operates exclusively on recorded 2D image points + raw model scores. No ground-
truth, identity, patient, 3D triangulation, clinical or diagnostic claim. The
camera's on-screen forward direction is unknown until the operator specifies it.

No file/network writes and no hardware interactions in this module.
"""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from statistics import median
from typing import Any

GAIT_ALGORITHM_VERSION = "kinelab-t5-foot-extrema-2d-v1"
SOURCE_SCHEMA = "kinelab.testonly.fullseq.halpe26.v1"
CANDIDATES_SCHEMA = "kinelab.2d-gait-candidates.v1"
REFERENCE_SCHEMA = "kinelab.manual-gait-reference.v1"
SCORE_THRESHOLD = 0.43
SMOOTH_HALF_WINDOW = 3             # 7 original source frames; no interpolation.
PROMINENCE_WINDOW = 16             # local geometric excursion, not a contact measurement
MIN_PROMINENCE = 0.0075             # video-height-normalized image x movement
MIN_SPACING = 18                    # 0.60 s between same-kind extrema
EXPECTED_FPS = 30
LANDMARKS = 26
LANDMARK_INDICES = {
    "left_heel": 24, "right_heel": 25,
    "left_big_toe": 20, "right_big_toe": 21,
}
PELVIS_INDEX = 19
SOURCE_HASH = re.compile(r"[a-f0-9]{64}\Z")
EVIDENCE_CLASSIFICATION = "GENERATED_OR_TEST_ONLY_NOT_PHYSICAL_VALIDATION"
UNSUPPORTED_GAIT_METRICS = (
    ("cadence", "No validated step detection, timing reference or walking-bout segmentation."),
    ("stride_length", "2D image pixels without calibration or scale; metric length is not measurable."),
    ("step_length", "2D image pixels without calibration or scale; metric length is not measurable."),
    ("gait_speed", "No physical scale or calibrated time-distance reference."),
    ("stance_swing_durations", "Extrema are unvalidated contact/toe-off hypotheses, not measured phases."),
)


class GaitEvidenceError(ValueError):
    """Fail closed rather than presenting unsupported movement claims."""


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise GaitEvidenceError(message)


def validate_2d_trajectories(
    evidence: dict, expected_role: str, expected_source_sha256: str
) -> list[dict]:
    """Reject mixed, changed, missing, or non-monotonic frame observations."""
    _require(isinstance(evidence, dict), "Missing 2D source evidence")
    _require(evidence.get("schema") == SOURCE_SCHEMA and evidence.get("test_only") is True,
             "Only explicitly test-only HALPE26 2D observations accepted")
    _require(evidence.get("role") == expected_role and expected_role in (
        "cam01_trial", "cam02_trial"), "Wrong original camera/role")
    _require(type(expected_source_sha256) is str and
             SOURCE_HASH.fullmatch(expected_source_sha256) is not None and
             evidence.get("source_sha256") == expected_source_sha256,
             "Original registered test-video hash mismatch")
    _require(evidence.get("fps") == EXPECTED_FPS and
             evidence.get("coordinates") == "unscaled source-video 2D image pixels; not meters",
             "Only exact 30 FPS and raw 2D image coordinates accepted")
    _require(evidence.get("model_score_threshold") == SCORE_THRESHOLD,
             "Unexpected model-score threshold")
    frames = evidence.get("frames")
    if not isinstance(frames, list) or not 40 <= len(frames) <= 24000:
        raise GaitEvidenceError("Video observations must be complete and bounded")
    for index, row in enumerate(frames):
        _require(isinstance(row, dict) and row.get("frame_index") == index
                 and type(row.get("frame_index")) is int,
                 "Missing, duplicate, or out-of-order video frame")
        _require(_finite(row.get("time_seconds")) and
                 abs(row["time_seconds"] - index / EXPECTED_FPS) <= .0002,
                 "Frame timeline must preserve original video frame time")
        n = row.get("people_detected")
        _require(type(n) is int and n >= 0, "Invalid detected-person count")
        xy = row.get("xy_pixels")
        scores = row.get("confidence")
        if n == 0:
            _require(xy is None and scores is None,
                     "Missing person must not have invented marker coordinates")
            continue
        _require(isinstance(xy, list) and isinstance(scores, list) and
                 len(xy) == LANDMARKS and len(scores) == LANDMARKS,
                 "Missing HALPE26 coordinates or model scores")
        for point, score in zip(xy, scores):
            _require(_finite(score), "Model scores must be finite; scores may exceed 1")
            if point is None:
                continue
            _require(isinstance(point, list) and len(point) == 2 and
                     all(_finite(v) for v in point),
                     "Each observed marker must have finite 2D pixel coordinates")
    return frames


def _single_person(frame: dict) -> bool:
    return frame["people_detected"] == 1 and frame["confidence"] is not None and frame["xy_pixels"] is not None


def _observed(frame: dict, index: int) -> bool:
    """One unambiguous person with pelvis and the landmark above the raw-score gate."""
    if not _single_person(frame):
        return False
    conf, pts = frame["confidence"], frame["xy_pixels"]
    return (conf[PELVIS_INDEX] >= SCORE_THRESHOLD and conf[index] >= SCORE_THRESHOLD and
            pts[PELVIS_INDEX] is not None and pts[index] is not None)


def _raw_foot_signal(frames: list[dict], index: int, height: int) -> tuple[list[float | None], list[float | None]]:
    """Per-frame signal and the weakest raw score (pelvis or landmark) that supports it."""
    values: list[float | None] = []
    scores: list[float | None] = []
    for f in frames:
        if _observed(f, index):
            conf, pts = f["confidence"], f["xy_pixels"]
            values.append(float((pts[index][0] - pts[PELVIS_INDEX][0]) / height))
            scores.append(float(min(conf[PELVIS_INDEX], conf[index])))
        else:
            values.append(None)
            scores.append(None)
    return values, scores


def _complete(values: list[float | None]) -> list[float] | None:
    observed = [v for v in values if v is not None and math.isfinite(v)]
    return observed if len(observed) == len(values) else None


def _smoothed(values: list[float | None]) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    for index in range(SMOOTH_HALF_WINDOW, len(values)-SMOOTH_HALF_WINDOW):
        window = _complete(values[index-SMOOTH_HALF_WINDOW:index+SMOOTH_HALF_WINDOW+1])
        if window is not None:
            result[index] = sum(window) / len(window)
    return result


def _detectable(values: list[float | None], i: int) -> bool:
    """True only where the full two-sided prominence window is observed."""
    return (PROMINENCE_WINDOW <= i < len(values) - PROMINENCE_WINDOW and
            _complete(values[i-PROMINENCE_WINDOW:i+PROMINENCE_WINDOW+1]) is not None)


def _extrema(values: list[float | None], kind: str) -> list[dict]:
    """Two-sided prominence, conservative within contiguous observed segments."""
    candidates = []
    size = len(values)
    for i in range(PROMINENCE_WINDOW, size-PROMINENCE_WINDOW):
        before = _complete(values[i-PROMINENCE_WINDOW:i])
        after = _complete(values[i+1:i+PROMINENCE_WINDOW+1])
        center = values[i]
        if before is None or after is None or center is None:
            continue
        left, right = before[-1], after[0]
        if kind == "max":
            is_turn = center > left and center >= right
            prominence = min(center - min(before), center - min(after))
        else:
            is_turn = center < left and center <= right
            prominence = min(max(before) - center, max(after) - center)
        if is_turn and prominence >= MIN_PROMINENCE:
            candidates.append({"frame_index": i, "prominence": round(prominence, 7)})
    # Keep strongest independent extrema; proximity-based suppression is per kind.
    selected: list[dict] = []
    for row in sorted(candidates, key=lambda item: (-item["prominence"], item["frame_index"])):
        if all(abs(row["frame_index"] - existing["frame_index"]) >= MIN_SPACING for existing in selected):
            selected.append(row)
    return sorted(selected, key=lambda item: item["frame_index"])


def propose_extrema(
    evidence: dict, role: str, source_sha256: str,
    *, image_width: int, image_height: int,
) -> dict:
    """Generate *unassigned* 2D foot-displacement extrema without labeling events."""
    _require(type(image_width) is int and 80 <= image_width <= 16384 and
             type(image_height) is int and 80 <= image_height <= 16384,
             "Invalid original image geometry")
    frames = validate_2d_trajectories(evidence, role, source_sha256)
    names = {
        "left": {"heel": "left_heel", "big_toe": "left_big_toe"},
        "right": {"heel": "right_heel", "big_toe": "right_big_toe"},
    }
    signals: dict[str, list] = {}
    quality: dict[str, float] = {}
    candidates = []
    n = len(frames)
    support = PROMINENCE_WINDOW + SMOOTH_HALF_WINDOW
    single = [_single_person(f) for f in frames]
    low_score: dict[str, int] = {}
    for side, points in names.items():
        for foot_point, label in points.items():
            raw, scores = _raw_foot_signal(frames, LANDMARK_INDICES[label], image_height)
            smooth = _smoothed(raw)
            signals[label] = [round(v, 7) if v is not None else None for v in smooth]
            quality[label] = sum(v is not None for v in raw) / n
            low_score[label] = sum(ok and v is None for ok, v in zip(single, raw, strict=True))
            for kind in ("max", "min"):
                for result in _extrema(smooth, kind):
                    index = result["frame_index"]
                    window = [s for s in scores[max(0, index-support):index+support+1] if s is not None]
                    candidates.append({
                        "id": f"{role}:{side}:{foot_point}:{kind}:{index}",
                        "role": role, "side": side, "foot_point": foot_point,
                        "extremum": kind, "event_type": "unassigned_extremum",
                        "frame_index": index, "time_seconds": round(index / EXPECTED_FPS, 6),
                        "prominence_image_height_units": result["prominence"],
                        "image_x_relative_hip_height_units": signals[label][index],
                        "mean_raw_landmark_score": scores[index],
                        "window_min_raw_landmark_score": min(window),
                        "window_min_score_margin_over_threshold": round(min(window) - SCORE_THRESHOLD, 7),
                        "window_observed_frames": len(window),
                        "model_score_is_probability": False,
                        "method": "image-x-relative-to-hip",
                        "interpolated": False,
                    })
    candidates.sort(key=lambda row: (row["frame_index"], row["side"], row["foot_point"], row["extremum"]))
    return {
        "schema": CANDIDATES_SCHEMA,
        "algorithm_version": GAIT_ALGORITHM_VERSION,
        "source_schema": SOURCE_SCHEMA,
        "classification": "UNVALIDATED_EVENT_CANDIDATES",
        "evidence_classification": EVIDENCE_CLASSIFICATION,
        "test_only": True, "role": role, "source_sha256": source_sha256,
        "fps": EXPECTED_FPS, "image_size": [image_width, image_height],
        "observed_frames": n, "duration_seconds": n / EXPECTED_FPS,
        "screen_forward": None, "manual_validation_status": "not_reviewed",
        "has_manually_validated_events": False,
        "frames_with_required_hip_and_both_feet": sum(
            all(_observed(f, idx) for idx in (20, 21, 24, 25)) for f in frames
        ),
        "required_landmark_coverage": quality,
        "sample_exclusions": {
            "no_person_frames": sum(f["people_detected"] == 0 for f in frames),
            "ambiguous_person_frames": sum(f["people_detected"] > 1 for f in frames),
            "low_score_or_occluded_frames": low_score,
            "policy": "Frames without exactly one detected person, or below the raw-score gate, "
                      "are excluded from every signal; nothing is interpolated.",
        },
        "unsupported_metrics": _unsupported_metrics(),
        "event_confidence_description": (
            "window_min_raw_landmark_score is the weakest raw pelvis/landmark score over the "
            "frames supporting the smoothed prominence window; raw scores are not probabilities"
        ),
        "signal_description": (
            "strict seven-frame local average of observed heel or big-toe "
            "horizontal image displacement relative to pelvis; divided by image height"
        ),
        "signals": signals,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "limitations": [
            "No native calibration, physical scale, 3D trajectories or force-plate reference.",
            "Frame-extrema are periodic 2D foot motion, not independently observed initial contact/toe-off.",
            "Forward direction in each camera is unknown until the reviewer chooses it.",
            "Raw RTMPose scores are not probabilities; low-score gaps are not interpolated.",
            "No stride length, clinical gait cadence, diagnosis, accuracy, or patient identifiers.",
        ],
    }


def _unsupported_metrics() -> list[dict]:
    return [{"metric": name, "status": "UNSUPPORTED", "value": None, "reason": reason}
            for name, reason in UNSUPPORTED_GAIT_METRICS]


def orient_event_candidates(base: dict, *, screen_forward: str) -> dict:
    """Only an explicit operator-chosen on-screen forward direction assigns proposals."""
    _require(screen_forward in ("left", "right"), "Choose visible on-screen forward direction")
    _require(isinstance(base, dict) and base.get("schema") == CANDIDATES_SCHEMA and
             base.get("test_only") is True,
             "Invalid unvalidated extrema report")
    sign = "max" if screen_forward == "right" else "min"
    other = "min" if sign == "max" else "max"
    events = []
    for event in base.get("candidates", []):
        row = dict(event)
        row["event_type"] = (
            "candidate_initial_contact" if row["foot_point"] == "heel" and row["extremum"] == sign
            else "candidate_toe_off" if row["foot_point"] == "big_toe" and row["extremum"] == other
            else "unassigned_extremum"
        )
        events.append(row)
    return {
        **base, "screen_forward": screen_forward, "candidates": events,
        "unsupported_metrics": _unsupported_metrics(),
        "manual_validation_status": "not_reviewed",
        "has_manually_validated_events": False,
        "interpretation": "Operator-selected screen direction is an assumption. Gait event names are hypotheses, not measured contacts.",
    }


def make_manual_reference(
    base: dict, labels: list[dict], *,
    reviewer: str, confirmed: bool,
) -> dict:
    """Accept only explicit human-observed source-frame labels, never autopopulate."""
    _require(isinstance(base, dict) and base.get("schema") == CANDIDATES_SCHEMA,
             "Unrecognized trajectory evidence")
    _require(isinstance(reviewer, str) and 2 <= len(reviewer.strip()) <= 90,
             "A named operator/reviewer is required")
    _require(confirmed is True, "The operator must explicitly confirm observed video frames")
    _require(isinstance(labels, list) and 1 <= len(labels) <= 1000,
             "Human reference requires one or more actually reviewed events")
    cleaned = []
    used = set()
    n = base["observed_frames"]
    for item in labels:
        _require(isinstance(item, dict), "Invalid manual event entry")
        frame, side, kind = item.get("frame_index"), item.get("side"), item.get("event_type")
        if not (type(frame) is int and 0 <= frame < n and
                side in ("left", "right") and kind in ("initial_contact", "toe_off")):
            raise GaitEvidenceError("Manual events require exact source frame, side and event type")
        key = (side, kind, frame)
        _require(key not in used, "Duplicate manual reference event")
        used.add(key)
        cleaned.append({"frame_index": frame,
                        "time_seconds": round(frame / EXPECTED_FPS, 6),
                        "side": side, "event_type": kind})
    cleaned.sort(key=lambda e: (e["frame_index"], e["side"], e["event_type"]))
    return {
        "schema": REFERENCE_SCHEMA, "test_only": True,
        "status": "MANUAL_OBSERVATIONS_NOT_CLINICAL_GROUND_TRUTH",
        "role": base["role"], "source_sha256": base["source_sha256"],
        "fps": EXPECTED_FPS, "frames": n,
        "annotation_origin": "human_observed_video_frames",
        "operator_confirmed": True, "reviewer": reviewer.strip(),
        "algorithm_events_shown_during_annotation": False,
        "clinical_accuracy_validated": False,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "labels": cleaned,
        "limitations": (
            "Human review in browser player, without frame-exact external ground truth. "
            "No instrumented gait-event or clinical accuracy validation."
        ),
    }


def _reference_observable(oriented: dict, side: str, kind: str, frame: int, tolerance: int) -> bool:
    label = f"{side}_{'heel' if kind == 'initial_contact' else 'big_toe'}"
    signal = oriented.get("signals", {}).get(label)
    if not isinstance(signal, list) or len(signal) != oriented["observed_frames"]:
        raise GaitEvidenceError("Oriented candidates lack the source-bound signal needed to score references")
    return any(_detectable(signal, i) for i in range(frame - tolerance, frame + tolerance + 1))


def score_manual_reference(
    oriented: dict, reference: dict | None, *, tolerance_frames: int = 3
) -> dict:
    """One-to-one exploratory reviewer agreement, never clinical accuracy.

    Reference events the source could not support (no detectable prominence window
    within tolerance because of occlusion, low score, ambiguous person or video edge)
    are reported as unscorable rather than as detector misses.
    """
    _require(type(tolerance_frames) is int and 0 <= tolerance_frames <= 15,
             "Invalid manual-event tolerance")
    _require(isinstance(oriented, dict) and oriented.get("schema") == CANDIDATES_SCHEMA and
             oriented.get("screen_forward") in ("left", "right"),
             "Event comparison requires explicitly oriented candidate proposals")
    proposed = [p for p in oriented["candidates"]
                if p["event_type"] in ("candidate_initial_contact", "candidate_toe_off")]
    provenance = {"test_only": oriented.get("test_only") is True,
                  "evidence_classification": EVIDENCE_CLASSIFICATION}
    if reference is None:
        return {"status": "NO_MANUAL_REFERENCE", "reference_count": 0,
                "candidate_count": len(proposed), "matched_count": 0,
                "precision": None, "recall": None,
                "missed_reference_count": None, "false_candidate_count": None,
                "unscorable_reference_count": None,
                "absolute_frame_errors": [], "tolerance_frames": tolerance_frames, **provenance,
                "claim": "Manual events have not been provided; no agreement can be measured."}
    _require(isinstance(reference, dict) and reference.get("schema") == REFERENCE_SCHEMA and
             reference.get("test_only") is True and reference.get("operator_confirmed") is True and
             reference.get("status") == "MANUAL_OBSERVATIONS_NOT_CLINICAL_GROUND_TRUTH" and
             reference.get("algorithm_events_shown_during_annotation") is False and
             reference.get("clinical_accuracy_validated") is False and
             reference.get("annotation_origin") == "human_observed_video_frames" and
             reference.get("source_sha256") == oriented.get("source_sha256") and
             reference.get("role") == oriented.get("role") and
             reference.get("fps") == EXPECTED_FPS and
             reference.get("frames") == oriented.get("observed_frames") and
             isinstance(reference.get("reviewer"), str) and
             len(reference["reviewer"].strip()) >= 2,
             "Manual reference does not belong to this exact video session")
    refs = reference.get("labels")
    if not isinstance(refs, list) or not 1 <= len(refs) <= 1000:
        raise GaitEvidenceError("Manual reference contains no bounded reviewed events")
    seen = set()
    for label in refs:
        _require(isinstance(label, dict) and
                 type(label.get("frame_index")) is int and
                 0 <= label["frame_index"] < oriented["observed_frames"] and
                 label.get("side") in ("left", "right") and
                 label.get("event_type") in ("initial_contact", "toe_off") and
                 _finite(label.get("time_seconds")) and
                 abs(label["time_seconds"] - round(label["frame_index"] / EXPECTED_FPS, 6)) < .0001,
                 "Manual reference contains invalid source frames or event time")
        key = (label["frame_index"], label["side"], label["event_type"])
        _require(key not in seen, "Duplicate human reference label")
        seen.add(key)
    candidates = [(p["frame_index"], p["side"], p["event_type"].removeprefix("candidate_"))
                  for p in proposed]
    comparison = []
    for i, ref in enumerate(refs):
        for j, (frame, side, kind) in enumerate(candidates):
            if side == ref["side"] and kind == ref["event_type"]:
                error = abs(ref["frame_index"]-frame)
                if error <= tolerance_frames:
                    comparison.append((error, i, j))
    matched: dict[int, tuple[int, int]] = {}
    matched_candidate: set[int] = set()
    for error, i, j in sorted(comparison):
        if i not in matched and j not in matched_candidate:
            matched[i] = (j, error)
            matched_candidate.add(j)
    errors = [error for _, error in matched.values()]
    outcomes = []
    by_type: dict[str, dict[str, int]] = {}
    for i, ref in enumerate(refs):
        side, kind, frame = ref["side"], ref["event_type"], ref["frame_index"]
        if i in matched:
            outcome = "matched"
        elif _reference_observable(oriented, side, kind, frame, tolerance_frames):
            outcome = "missed"
        else:
            outcome = "unscorable_unobserved_source"
        outcomes.append({"frame_index": frame, "side": side, "event_type": kind, "outcome": outcome,
                         "absolute_frame_error": matched[i][1] if i in matched else None})
        counts = by_type.setdefault(f"{side}:{kind}", {"reference": 0, "matched": 0, "missed": 0,
                                                       "unscorable": 0, "false_candidates": 0})
        counts["reference"] += 1
        counts["unscorable" if outcome.startswith("unscorable") else outcome] += 1
    false_candidates = []
    for j, (frame, side, kind) in enumerate(candidates):
        if j not in matched_candidate:
            false_candidates.append({"id": proposed[j]["id"], "frame_index": frame,
                                     "side": side, "event_type": kind})
            by_type.setdefault(f"{side}:{kind}", {"reference": 0, "matched": 0, "missed": 0,
                                                  "unscorable": 0, "false_candidates": 0})
            by_type[f"{side}:{kind}"]["false_candidates"] += 1
    return {
        "status": "EXPLORATORY_REVIEWER_AGREEMENT_ONLY",
        "reference_count": len(refs), "candidate_count": len(candidates),
        "matched_count": len(errors), "precision": len(errors)/len(candidates) if candidates else None,
        "recall": len(errors)/len(refs),
        "unmatched_reference_count": len(refs)-len(errors),
        "unmatched_candidate_count": len(candidates)-len(errors),
        "missed_reference_count": sum(o["outcome"] == "missed" for o in outcomes),
        "unscorable_reference_count": sum(o["outcome"] == "unscorable_unobserved_source" for o in outcomes),
        "false_candidate_count": len(false_candidates),
        "reference_outcomes": outcomes, "false_candidates": false_candidates,
        "by_event_type": by_type,
        "tolerance_frames": tolerance_frames, "absolute_frame_errors": sorted(errors),
        "median_absolute_error_frames": median(errors) if errors else None,
        **provenance,
        "claim": "Agreement with unvalidated human video annotations only; not instrumented ground truth or clinical accuracy.",
    }
