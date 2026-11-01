"""TEST_ONLY producer-to-report raw-score compatibility; no cameras or weights."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from gait_events import orient_event_candidates, propose_extrema
from report_builder import _collect_event_analysis, _event_score
from test_gait_events import fixture
from test_squat_events import fixture_reps, run


class ReportRawConfidenceContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="TEST_ONLY_report_raw_confidence_")
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        if self.folder.resolve().is_relative_to(Path.cwd().resolve()):
            raise RuntimeError("TEST_ONLY temporary parent must be outside the checkout")
        self.passport = {"sources": {"cam01_trial": {
            "sha256": "a" * 64, "observed_sha256": "a" * 64,
            "integrity_state": "unchanged",
        }}}

    def producer(self, kind, score):
        source = fixture() if kind == "gait" else fixture_reps(1)
        for frame in source["frames"]:
            if frame["confidence"] is not None:
                frame["confidence"] = [score] * len(frame["confidence"])
        if kind == "gait":
            return orient_event_candidates(propose_extrema(
                source, "cam01_trial", "a" * 64,
                image_width=1024, image_height=576), screen_forward="right")
        return run(source)

    def collect(self, doc, kind):
        for path in self.folder.glob("*-candidates.json"):
            path.unlink()
        (self.folder / f"{kind}-candidates.json").write_text(
            json.dumps(doc), encoding="utf-8")
        return _collect_event_analysis(self.folder, self.passport)

    def assert_rejected(self, doc, kind):
        section = self.collect(doc, kind)
        self.assertIn("BLOCKED", section["status"])
        self.assertEqual(section[f"{kind}_candidates"], "UNAVAILABLE")
        self.assertTrue(section["artifact_issues"])

    def test_gait_actual_producer_score_above_one_survives_report(self):
        doc = self.producer("gait", 1.05)
        self.assertGreater(len(doc["candidates"]), 0)
        for event in doc["candidates"]:
            self.assertEqual(event["window_min_raw_landmark_score"], 1.05)
            self.assertAlmostEqual(event["window_min_score_margin_over_threshold"], .62)
            self.assertIs(event["model_score_is_probability"], False)
        section = self.collect(doc, "gait")
        self.assertEqual(section["artifact_issues"], [])
        report = section["gait_candidates"][0]
        self.assertIs(report["test_only"], True)
        self.assertEqual(report["evidence_classification"], doc["evidence_classification"])
        self.assertEqual(report["candidate_count"], doc["candidate_count"])
        for event in report["candidates"]:
            self.assertEqual(event["window_min_raw_landmark_score"], 1.05)
            self.assertAlmostEqual(event["window_min_score_margin_over_threshold"], .62)
            self.assertIs(event["model_score_is_probability"], False)

    def test_squat_actual_producer_score_above_one_survives_report(self):
        doc = self.producer("squat", 1.05)
        self.assertGreater(len(doc["repetitions"]), 0)
        for rep in doc["repetitions"]:
            self.assertEqual(rep["min_required_landmark_raw_score"], 1.05)
            self.assertIs(rep["model_score_is_probability"], False)
        section = self.collect(doc, "squat")
        self.assertEqual(section["artifact_issues"], [])
        report = section["squat_candidates"][0]
        self.assertIs(report["test_only"], True)
        self.assertEqual(report["evidence_classification"], doc["evidence_classification"])
        self.assertEqual(report["candidate_repetition_count"], doc["candidate_repetition_count"])
        for rep in report["repetitions"]:
            self.assertEqual(rep["min_required_landmark_raw_score"], 1.05)
            self.assertIs(rep["model_score_is_probability"], False)

    def test_invalid_raw_scores_still_block_both_actual_producer_artifacts(self):
        for kind, items, field in (
            ("gait", "candidates", "window_min_raw_landmark_score"),
            ("squat", "repetitions", "min_required_landmark_raw_score"),
        ):
            original = self.producer(kind, .9)
            self.assertGreater(len(original[items]), 0)
            for bad in (float("nan"), float("inf"), -float("inf"), True, -1, .42):
                with self.subTest(kind=kind, bad=repr(bad)):
                    doc = copy.deepcopy(original)
                    doc[items][0][field] = bad
                    self.assert_rejected(doc, kind)

    def test_invalid_margins_and_contradictions_still_block(self):
        original = self.producer("gait", .9)
        self.assertGreater(len(original["candidates"]), 0)
        for bad in (float("nan"), float("inf"), True, -1, .1):
            with self.subTest(bad=repr(bad)):
                doc = copy.deepcopy(original)
                doc["candidates"][0]["window_min_score_margin_over_threshold"] = bad
                self.assert_rejected(doc, "gait")

    def test_provenance_and_classification_checks_remain_required(self):
        original = self.producer("gait", .9)
        for key, bad in (("test_only", False), ("source_sha256", "b" * 64),
                         ("classification", "MEASURED"), ("candidate_count", -1)):
            with self.subTest(key=key):
                doc = copy.deepcopy(original)
                doc[key] = bad
                self.assert_rejected(doc, "gait")

    def test_precision_recall_default_bounds_still_reject_above_one(self):
        for field in ("scoring.precision", "scoring.recall"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    _event_score(1.05, field)
                _event_score(1.0, field)


if __name__ == "__main__":
    unittest.main()
