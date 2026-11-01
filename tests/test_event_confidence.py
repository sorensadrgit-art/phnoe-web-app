"""R06 contract tests: event candidates against analytically constructed labels.

Every expected label below is derived from the closed-form generator geometry
(sinusoid phase or piecewise squat schedule), never from the detector output.
These are generated TEST-ONLY sources; agreement here is software verification,
not physical or clinical validation.
"""
import copy
import json
import math
import unittest

from gait_events import (
    PROMINENCE_WINDOW,
    SMOOTH_HALF_WINDOW,
    make_manual_reference,
    orient_event_candidates,
    propose_extrema,
    score_manual_reference,
)
from squat_events import analyze_squats, compare_manual_reps, make_manual_rep_reference

HASH = "c" * 64
ROLE = "cam01_trial"
N = 240
PERIOD = 40


def gait_source(n=N, occluded=(), ambiguous=(), absent=(), score=.9):
    frames = []
    for i in range(n):
        phase = 2 * math.pi * i / PERIOD
        points = [[255., 190.] for _ in range(26)]
        scores = [score] * 26
        points[19] = [300., 320.]
        points[24] = [300 + 26 * math.sin(phase), 460.]
        points[20] = [300 + 22 * math.sin(phase - math.pi / 2), 468.]
        points[25] = [300 + 26 * math.sin(phase + math.pi), 461.]
        points[21] = [300 + 22 * math.sin(phase + math.pi / 2), 466.]
        if i in occluded:
            scores[24] = .1
        people = 0 if i in absent else 2 if i in ambiguous else 1
        frames.append({"frame_index": i, "time_seconds": round(i / 30, 6),
                       "people_detected": people, "selected_person_index": 0 if people else None,
                       "xy_pixels": points if people else None,
                       "confidence": scores if people else None})
    return {"schema": "kinelab.testonly.fullseq.halpe26.v1", "test_only": True, "role": ROLE,
            "fps": 30, "source_sha256": HASH, "model_score_threshold": .43,
            "coordinates": "unscaled source-video 2D image pixels; not meters", "frames": frames}


def analytic_gait_labels(n=N):
    """Closed-form extrema of the generator for screen_forward='right'.

    Heel max: sin(phase + offset) == 1; big-toe min: sin(phase + offset) == -1.
    Only frames whose full two-sided prominence window lies inside the video are
    observable by any extremum method with that window.
    """
    def frames(first):
        return [f for f in range(first, n, PERIOD)
                if PROMINENCE_WINDOW <= f < n - PROMINENCE_WINDOW]
    labels = []
    for frame in frames(PERIOD // 4):            # left heel: phase = pi/2
        labels.append({"frame_index": frame, "side": "left", "event_type": "initial_contact"})
    for frame in frames(3 * PERIOD // 4):        # right heel: phase + pi = pi/2 (mod 2pi)
        labels.append({"frame_index": frame, "side": "right", "event_type": "initial_contact"})
    for frame in frames(0):                      # left toe: phase - pi/2 = -pi/2
        labels.append({"frame_index": frame, "side": "left", "event_type": "toe_off"})
    for frame in frames(PERIOD // 2):            # right toe: phase + pi/2 = 3pi/2
        labels.append({"frame_index": frame, "side": "right", "event_type": "toe_off"})
    return labels


def oriented(source):
    base = propose_extrema(source, ROLE, HASH, image_width=1024, image_height=576)
    return base, orient_event_candidates(base, screen_forward="right")


class GaitEventConfidenceTests(unittest.TestCase):
    def test_analytic_labels_agree_exactly_on_clean_generated_source(self):
        base, events = oriented(gait_source())
        labels = analytic_gait_labels()
        reference = make_manual_reference(base, labels, reviewer="analytic generator", confirmed=True)
        outcome = score_manual_reference(events, reference, tolerance_frames=0)
        self.assertEqual(outcome["matched_count"], len(labels))
        self.assertEqual(outcome["missed_reference_count"], 0)
        self.assertEqual(outcome["false_candidate_count"], 0)
        self.assertEqual(outcome["unscorable_reference_count"], 0)
        self.assertEqual(outcome["absolute_frame_errors"], [0] * len(labels))
        self.assertTrue(outcome["test_only"])
        self.assertEqual(outcome["evidence_classification"], "GENERATED_OR_TEST_ONLY_NOT_PHYSICAL_VALIDATION")

    def test_ambiguous_person_frames_never_feed_events(self):
        ambiguous = set(range(120, 141))
        base, events = oriented(gait_source(ambiguous=ambiguous))
        self.assertEqual(base["frames_with_required_hip_and_both_feet"], N - len(ambiguous))
        self.assertEqual(base["sample_exclusions"]["ambiguous_person_frames"], len(ambiguous))
        for label in ("left_heel", "right_heel", "left_big_toe", "right_big_toe"):
            self.assertEqual(base["required_landmark_coverage"][label], (N - len(ambiguous)) / N)
            self.assertTrue(all(base["signals"][label][i] is None for i in ambiguous))
        self.assertFalse(any(117 <= c["frame_index"] <= 143 for c in events["candidates"]))

    def test_occluded_reference_is_unscorable_not_missed_or_fabricated(self):
        occluded = set(range(80, 101))
        base, events = oriented(gait_source(occluded=occluded))
        self.assertEqual(base["sample_exclusions"]["low_score_or_occluded_frames"]["left_heel"], len(occluded))
        reference = make_manual_reference(base, analytic_gait_labels(), reviewer="analytic generator",
                                          confirmed=True)
        outcome = score_manual_reference(events, reference, tolerance_frames=2)
        by_key = {(r["frame_index"], r["side"], r["event_type"]): r for r in outcome["reference_outcomes"]}
        self.assertEqual(by_key[(90, "left", "initial_contact")]["outcome"], "unscorable_unobserved_source")
        self.assertIsNone(by_key[(90, "left", "initial_contact")]["absolute_frame_error"])
        self.assertEqual(by_key[(80, "left", "toe_off")]["outcome"], "matched")
        self.assertEqual(outcome["unscorable_reference_count"], 1)
        self.assertEqual(outcome["missed_reference_count"], 0)
        self.assertEqual(outcome["false_candidate_count"], 0)

    def test_missed_and_false_events_are_reported_separately(self):
        base, events = oriented(gait_source())
        labels = [label for label in analytic_gait_labels()
                  if not (label["frame_index"] == 210 and label["event_type"] == "initial_contact")]
        # A heel minimum (sin == -1) is observable but is not an initial-contact extremum.
        labels.append({"frame_index": 70, "side": "left", "event_type": "initial_contact"})
        reference = make_manual_reference(base, labels, reviewer="analytic generator", confirmed=True)
        outcome = score_manual_reference(events, reference, tolerance_frames=3)
        self.assertEqual(outcome["missed_reference_count"], 1)
        self.assertEqual(outcome["false_candidate_count"], 1)
        self.assertEqual([c["frame_index"] for c in outcome["false_candidates"]], [210])
        missed = [r for r in outcome["reference_outcomes"] if r["outcome"] == "missed"]
        self.assertEqual([(r["frame_index"], r["side"]) for r in missed], [(70, "left")])
        per_type = outcome["by_event_type"]["left:initial_contact"]
        self.assertEqual(per_type, {"reference": 5, "matched": 4, "missed": 1, "unscorable": 0,
                                    "false_candidates": 1})

    def test_event_confidence_is_derived_from_window_scores_not_defaulted(self):
        source = gait_source(score=.8)
        for i in range(44, 57):                       # inside the frame-50 window only
            source["frames"][i]["confidence"][19] = .5
        base, _ = oriented(source)
        event = next(c for c in base["candidates"]
                     if c["frame_index"] == 50 and c["side"] == "left" and c["foot_point"] == "heel")
        self.assertAlmostEqual(event["window_min_raw_landmark_score"], .5)
        self.assertAlmostEqual(event["window_min_score_margin_over_threshold"], .5 - .43)
        # Smoothed prominence window plus the raw frames each smoothed sample averages.
        self.assertEqual(event["window_observed_frames"], 2 * (PROMINENCE_WINDOW + SMOOTH_HALF_WINDOW) + 1)
        self.assertFalse(event["model_score_is_probability"])
        clean = next(c for c in base["candidates"]
                     if c["frame_index"] == 130 and c["side"] == "left" and c["foot_point"] == "heel")
        self.assertAlmostEqual(clean["window_min_raw_landmark_score"], .8)

    def test_unsupported_gait_metrics_are_explicit_and_never_numeric(self):
        base, events = oriented(gait_source())
        for result in (base, events):
            names = {row["metric"] for row in result["unsupported_metrics"]}
            self.assertTrue({"cadence", "stride_length", "step_length", "gait_speed"} <= names)
            self.assertTrue(all(row["status"] == "UNSUPPORTED" and row["value"] is None
                                for row in result["unsupported_metrics"]))
        text = json.dumps(base)
        for forbidden in ("cadence_spm", "stride_length_m", "steps_per_minute\":"):
            self.assertNotIn(forbidden, text)


def squat_frame(i, bend, drop, people=1, score=.91):
    points = [[100., 90.] for _ in range(26)]
    scores = [score] * 26
    for dx, sh, hi, kn, an in ((0., 5, 11, 13, 15), (130., 6, 12, 14, 16)):
        points[sh] = [100. + dx, 60. + drop * 40.]
        points[hi] = [100. + dx, 100. + drop * 40.]
        points[kn] = [100. + dx + bend * .70, 150. + drop * 20.]
        points[an] = [100. + dx, 205.]
    return {"frame_index": i, "time_seconds": round(i / 30., 6), "people_detected": people,
            "selected_person_index": 0 if people else None,
            "xy_pixels": points if people else None, "confidence": scores if people else None}


LEAD, STAND, DESCENT, HOLD, ASCENT = 25, 25, 20, 7, 20
REP = STAND + DESCENT + HOLD + ASCENT + STAND


def squat_schedule(reps):
    poses = [(0., 0.)] * LEAD
    for _ in range(reps):
        poses += [(0., 0.)] * STAND
        poses += [(60. * i / (DESCENT - 1), .62 * i / (DESCENT - 1)) for i in range(DESCENT)]
        poses += [(60., .62)] * HOLD
        poses += [(60. * (1 - i / (ASCENT - 1)), .62 * (1 - i / (ASCENT - 1))) for i in range(ASCENT)]
        poses += [(0., 0.)] * STAND
    return poses + [(0., 0.)] * 10


def analytic_rep(k):
    """Generator schedule: last standing frame, first frame of deepest pose, first standing frame."""
    offset = LEAD + k * REP
    return {"start_frame": offset + STAND - 1,
            "bottom_frame": offset + STAND + DESCENT - 1,
            "end_frame": offset + STAND + DESCENT + HOLD + ASCENT}


def squat_source(reps=2, people=None, low=None, score=.91):
    people, low = people or {}, low or {}
    frames = [squat_frame(i, b, d, people.get(i, 1), score) for i, (b, d) in enumerate(squat_schedule(reps))]
    for i, joints in low.items():
        for joint in joints:
            frames[i]["confidence"][joint] = .1
    return {"schema": "kinelab.testonly.fullseq.halpe26.v1", "test_only": True, "role": ROLE,
            "source_sha256": HASH, "fps": 30, "model_score_threshold": .43,
            "coordinates": "unscaled source-video 2D image pixels; not meters", "frames": frames}


def squats(source):
    return analyze_squats(source, ROLE, HASH, camera_view="side", activity_confirmed=True,
                          image_width=1024, image_height=576)


class SquatEventConfidenceTests(unittest.TestCase):
    def test_exclusion_reasons_are_explicit_per_frame(self):
        source = squat_source(1, people={30: 2, 31: 0}, low={32: (13,)})
        source["frames"][31]["xy_pixels"] = source["frames"][31]["confidence"] = None
        result = squats(source)
        reasons = [result["frame_features"][i]["unavailable_reason"] for i in (30, 31, 32, 33)]
        self.assertEqual(reasons, ["ambiguous_person", "no_person", "low_score_or_occluded", None])
        counts = result["quality"]["exclusion_reasons"]
        self.assertEqual((counts["ambiguous_person"], counts["no_person"], counts["low_score_or_occluded"]),
                         (1, 1, 1))

    def test_ambiguous_person_inside_rep_aborts_instead_of_counting(self):
        bottom = analytic_rep(0)["bottom_frame"]
        result = squats(squat_source(1, people={i: 2 for i in range(bottom - 2, bottom + 3)}))
        self.assertEqual(result["candidate_repetition_count"], 0)
        self.assertGreaterEqual(result["incomplete_attempts"], 1)

    def test_rep_confidence_is_minimum_observed_required_score(self):
        source = squat_source(1, score=.77)
        result = squats(source)
        rep = result["repetitions"][0]
        self.assertAlmostEqual(rep["min_required_landmark_raw_score"], .77)
        self.assertFalse(rep["model_score_is_probability"])
        self.assertEqual(rep["unmeasured_frames_within_rep"], 0)

    def test_boundaries_scored_against_analytic_schedule_and_outcomes_separated(self):
        result = squats(squat_source(2))
        self.assertEqual(result["candidate_repetition_count"], 2)
        first = analytic_rep(0)
        missed = {"start_frame": 3, "bottom_frame": 10, "end_frame": 18}   # standing-only interval
        reference = make_manual_rep_reference(result, [first, missed], reviewer="analytic generator",
                                              confirmed=True)
        score = compare_manual_reps(result, reference, tolerance_frames=3)
        self.assertEqual(score["matched_count"], 1)
        self.assertEqual(score["missed_reference_count"], 1)
        self.assertEqual(score["false_candidate_count"], 1)
        self.assertEqual(score["incomplete_attempts"], result["incomplete_attempts"])
        pair = score["matched_pairs"][0]
        rep = result["repetitions"][0]
        self.assertEqual(pair["start_frame_error"], abs(rep["start_frame"] - first["start_frame"]))
        self.assertEqual(pair["end_frame_error"], abs(rep["end_frame"] - first["end_frame"]))
        self.assertEqual(pair["phase_boundaries_within_tolerance"],
                         pair["start_frame_error"] <= 3 and pair["end_frame_error"] <= 3)
        self.assertTrue(score["test_only"])
        self.assertEqual(score["evidence_classification"], "GENERATED_OR_TEST_ONLY_NOT_PHYSICAL_VALIDATION")

    def test_occluded_reference_rep_is_unscorable_not_missed(self):
        first = analytic_rep(0)
        low = {i: (16,) for i in range(first["bottom_frame"] - 3, first["bottom_frame"] + 4)}
        result = squats(squat_source(1, low=low))
        reference = make_manual_rep_reference(result, [first], reviewer="analytic generator", confirmed=True)
        score = compare_manual_reps(result, reference, tolerance_frames=3)
        self.assertEqual(score["unscorable_reference_count"], 1)
        self.assertEqual(score["missed_reference_count"], 0)
        self.assertEqual(score["reference_outcomes"][0]["outcome"], "unscorable_unobserved_source")

    def test_unsupported_squat_metrics_are_explicit(self):
        result = squats(squat_source(1))
        names = {row["metric"] for row in result["unsupported_metrics"]}
        self.assertTrue({"physical_knee_flexion_rom", "squat_depth_meters", "clinical_repetition_quality"} <= names)
        self.assertTrue(all(row["status"] == "UNSUPPORTED" and row["value"] is None
                            for row in result["unsupported_metrics"]))
        self.assertEqual(copy.deepcopy(result)["test_only"], True)


if __name__ == "__main__":
    unittest.main()
