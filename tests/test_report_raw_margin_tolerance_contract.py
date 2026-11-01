"""TEST_ONLY raw-score margin consistency; no cameras, models or clinical claims."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from gait_events import orient_event_candidates, propose_extrema
from report_builder import _collect_event_analysis
from test_gait_events import fixture


class ReportRawMarginToleranceContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="TEST_ONLY_report_raw_margin_")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        if self.folder.resolve().is_relative_to(Path.cwd().resolve()):
            raise RuntimeError("TEST_ONLY temporary parent must be outside the checkout")
        self.passport = {"sources": {"cam01_trial": {
            "sha256": "a" * 64, "observed_sha256": "a" * 64,
            "integrity_state": "unchanged",
        }}}

    def producer(self):
        source = fixture()
        for frame in source["frames"]:
            frame["confidence"] = [1_000_000_000.0] * len(frame["confidence"])
        document = orient_event_candidates(propose_extrema(
            source, "cam01_trial", "a" * 64,
            image_width=1024, image_height=576), screen_forward="right")
        self.assertGreater(len(document["candidates"]), 0)
        return document

    def collect(self, document):
        (self.folder / "gait-candidates.json").write_text(
            json.dumps(document, allow_nan=False), encoding="utf-8")
        return _collect_event_analysis(self.folder, self.passport)

    def assert_intact(self, document):
        result = self.collect(document)
        self.assertEqual(result["artifact_issues"], [])
        self.assertEqual(result["status"], "TEST_ONLY_CANDIDATE_EVIDENCE_NOT_PHYSICAL_VALIDATION")
        reported = result["gait_candidates"][0]
        self.assertIs(reported["test_only"], True)
        self.assertEqual(reported["evidence_classification"], document["evidence_classification"])
        self.assertEqual(reported["candidates"], [
            {field: event[field] for field in reported["candidates"][0]}
            for event in document["candidates"]
        ])
        for event in reported["candidates"]:
            self.assertEqual(event["window_min_raw_landmark_score"], 1_000_000_000.0)
            self.assertEqual(event["window_min_score_margin_over_threshold"], 999_999_999.57)
            self.assertIs(event["model_score_is_probability"], False)

    def test_generated_large_finite_raw_score_preserves_its_true_margin(self):
        self.assert_intact(self.producer())

    def test_relative_tolerance_cannot_hide_missing_threshold_margin(self):
        document = self.producer()
        self.assert_intact(document)
        forged = copy.deepcopy(document)
        event = forged["candidates"][0]
        event["window_min_score_margin_over_threshold"] = event["window_min_raw_landmark_score"]
        self.assertGreater(abs(event["window_min_score_margin_over_threshold"] -
                               (event["window_min_raw_landmark_score"] - .43)), .4)
        result = self.collect(forged)
        self.assertEqual(result["status"], "BLOCKED_INVALID_OR_UNBOUND_EVENT_EVIDENCE")
        self.assertEqual(result["gait_candidates"], "UNAVAILABLE")
        self.assertTrue(any("threshold margin is contradictory" in issue["reason"]
                            for issue in result["artifact_issues"]))


if __name__ == "__main__":
    unittest.main()
