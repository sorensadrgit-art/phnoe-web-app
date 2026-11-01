"""Tests for truthful offline research PDF, CSV, and JSON report generation."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from report_builder import ReportBuilder, _collect_event_analysis
from session_index import SessionIndex
from session_library import SessionLibrary


class ReportBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.db_path = self.root / "index.db"
        self.index = SessionIndex(self.db_path, self.projects)
        self.library = SessionLibrary(self.projects)
        self.builder = ReportBuilder(self.projects, self.index)

    def tearDown(self):
        self.index.close()
        self.tmp.cleanup()

    def test_generate_reports_for_draft_session(self):
        self.library.create_session("report-draft", kind="real")
        self.index.reindex()

        artifacts = self.builder.generate_reports("report-draft")
        self.assertTrue(artifacts["pdf"].is_file())
        self.assertTrue(artifacts["json"].is_file())
        self.assertTrue(artifacts["csv"].is_file())

        # Check JSON content
        doc = json.loads(artifacts["json"].read_text(encoding="utf-8"))
        self.assertEqual(doc["session_id"], "report-draft")
        self.assertFalse(doc["clinical_accuracy_verified"])
        self.assertIn("internal research software only", doc["limitations"].lower())

        # Check CSV content
        csv_text = artifacts["csv"].read_text(encoding="utf-8")
        self.assertIn("session_id", csv_text)
        self.assertIn("report-draft", csv_text)

        # Check PDF file size > 0 and header
        pdf_bytes = artifacts["pdf"].read_bytes()
        self.assertTrue(len(pdf_bytes) > 500)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_test_only_session_receives_test_only_watermark(self):
        self.library.create_session("report-demo", kind="demo")
        self.index.reindex()

        artifacts = self.builder.generate_reports("report-demo")
        doc = json.loads(artifacts["json"].read_text(encoding="utf-8"))
        self.assertTrue(doc["is_test_only"])
        self.assertEqual(doc["watermark"], "TEST ONLY - NOT PHYSICAL VALIDATION")

    def test_corrupt_motion_blocks_report_without_publishing_files(self):
        folder = self.library.create_session("corrupt-report", kind="real")
        exports = folder / "exports"
        exports.mkdir(exist_ok=True)
        source = exports / "corrupt.motion.json"
        source.write_text('{"schema":"kinelab.motion.v2","frames":[]}')
        self.index.reindex()
        with self.assertRaisesRegex(ValueError, "EVIDENCE_INVALID"):
            self.builder.generate_reports("corrupt-report")
        self.assertEqual(sorted(p.name for p in exports.iterdir()), [source.name])

    def test_empty_report_says_no_valid_measurements_and_does_not_invent_host_or_versions(self):
        self.library.create_session("empty-report", kind="real")
        self.index.reindex()
        files = self.builder.generate_reports("empty-report")
        doc = json.loads(files["json"].read_text())
        self.assertEqual(doc.get("measurement_status"), "No valid measurements")
        self.assertNotIn("host", doc["provenance"])
        self.assertEqual(doc["measurement_count"], 0)

    def test_repeated_report_publication_preserves_existing_revision(self):
        self.library.create_session("repeat-report", kind="demo")
        self.index.reindex()
        files = self.builder.generate_reports("repeat-report")
        before = {key: path.read_bytes() for key, path in files.items()}
        with self.assertRaisesRegex(ValueError, "OUTPUT_EXISTS"):
            self.builder.generate_reports("repeat-report")
        self.assertEqual({key: path.read_bytes() for key, path in files.items()}, before)

    def test_generate_reports_for_live_session(self):
        s_folder = self.projects / "live-report-01"
        s_folder.mkdir(parents=True)
        (s_folder / "Config.toml").write_text("# KineLab Live Session\n", encoding="utf-8")
        session_meta = {
            "schema": "kinelab.live-session.v1",
            "id": "live-report-01",
            "kind": "live",
            "status": "completed",
            "exercise_type": "squats",
            "patient_id": "PT-REPORT-001",
            "total_reps": 3,
            "valid_reps": 2,
            "summary": {
                "totalReps": 3,
                "validReps": 2,
                "averageDepth": 82.5,
                "targetDepth": 80,
                "averageSymmetry": 88.0,
                "durationSeconds": 20,
                "faultsLog": [{"fault": "KNEE_VALGUS", "count": 1, "percentage": 33}],
            },
        }
        (s_folder / "session.json").write_text(json.dumps(session_meta), encoding="utf-8")
        telemetry = {
            "exercise_type": "squats",
            "patient_id": "PT-REPORT-001",
            "reps": [
                {"repNumber": 1, "durationMs": 1400, "peakDepth": 85.0, "targetDepth": 80, "minSymmetry": 90.0, "valid": True, "faults": []},
                {"repNumber": 2, "durationMs": 1300, "peakDepth": 75.0, "targetDepth": 80, "minSymmetry": 80.0, "valid": False, "faults": ["KNEE_VALGUS"]},
                {"repNumber": 3, "durationMs": 1500, "peakDepth": 87.5, "targetDepth": 80, "minSymmetry": 94.0, "valid": True, "faults": []},
            ],
            "summary_metrics": session_meta["summary"],
        }
        (s_folder / "live_telemetry.json").write_text(json.dumps(telemetry), encoding="utf-8")
        self.index.reindex()

        with self.assertRaisesRegex(ValueError, "EVIDENCE_UNVERIFIED"):
            self.builder.generate_reports("live-report-01")
        self.assertFalse((s_folder / "exports").exists())
        self.assertEqual(json.loads((s_folder / "session.json").read_text())["kind"], "live")
        self.assertTrue((s_folder / "live_telemetry.json").is_file())

    def test_live_metadata_under_test_only_marker_cannot_render_live_report(self):
        folder = self.projects / "marked-live"
        folder.mkdir()
        (folder / "Config.toml").write_text("# test\n", encoding="utf-8")
        (folder / "SAMPLE-PROVENANCE.json").write_text("{}", encoding="utf-8")
        (folder / "session.json").write_text(json.dumps({"kind": "live"}), encoding="utf-8")
        self.index.reindex()
        self.assertEqual(self.index.get_passport("marked-live")["state"], "EVIDENCE_UNVERIFIED")
        with self.assertRaisesRegex(ValueError, "EVIDENCE_UNVERIFIED"):
            self.builder.generate_reports("marked-live")
        self.assertFalse((folder / "exports").exists() and any((folder / "exports").iterdir()))

GAIT_CANDIDATES_DOC: dict = {
    "schema": "kinelab.2d-gait-candidates.v1",
    "test_only": True,
    "role": "cam01_trial",
    "algorithm_version": "kinelab-t5-foot-extrema-2d-v1",
    "source_schema": "kinelab.testonly.fullseq.halpe26.v1",
    "classification": "UNVALIDATED_EVENT_CANDIDATES",
    "evidence_classification": "GENERATED_OR_TEST_ONLY_NOT_PHYSICAL_VALIDATION",
    "source_sha256": "a" * 64,
    "observed_frames": 100,
    "candidate_count": 1,
    "sample_exclusions": {"ambiguous_person_frames": 3,
                          "low_score_or_occluded_frames": {"left_heel": 5}},
    "unsupported_metrics": [{"metric": "cadence", "status": "UNSUPPORTED", "value": None,
                             "reason": "No validated step detection."}],
    "candidates": [{"frame_index": 50, "side": "left",
                    "event_type": "candidate_initial_contact", "foot_point": "heel",
                    "window_min_raw_landmark_score": 0.5,
                    "window_min_score_margin_over_threshold": 0.07,
                    "window_observed_frames": 41,
                    "model_score_is_probability": False}],
}

SQUAT_CANDIDATES_DOC: dict = {
    "schema": "kinelab.2d-squat-candidates.v1",
    "algorithm_version": "kinelab-t5-squat-2d-phase-v1",
    "classification": "UNVALIDATED_2D_SQUAT_CANDIDATES",
    "evidence_classification": "GENERATED_OR_TEST_ONLY_NOT_PHYSICAL_VALIDATION",
    "test_only": True,
    "role": "cam01_trial",
    "source_sha256": "a" * 64,
    "observed_frames": 100,
    "candidate_repetition_count": 1,
    "incomplete_attempts": 2,
    "repetitions": [{"start_frame": 24, "bottom_frame": 44, "end_frame": 76,
                     "min_required_landmark_raw_score": 0.77,
                     "unmeasured_frames_within_rep": 0,
                     "model_score_is_probability": False}],
    "quality": {"exclusion_reasons": {"ambiguous_person": 1, "no_person": 0,
                                      "low_score_or_occluded": 2}},
    "unsupported_metrics": [{"metric": "squat_depth_meters", "status": "UNSUPPORTED",
                             "value": None, "reason": "No physical scale."}],
}

SCORING_DOC: dict = {
    "status": "COMPARED",
    "missed_reference_count": 1,
    "unscorable_reference_count": 2,
    "false_candidate_count": 0,
    "by_event_type": {"left:initial_contact": {"reference": 5, "matched": 4, "missed": 1,
                                               "unscorable": 0, "false_candidates": 1}},
    "evidence_classification": "GENERATED_OR_TEST_ONLY_NOT_PHYSICAL_VALIDATION",
    "test_only": True,
    "reference_outcomes": [],
}


class EventAnalysisReportTests(unittest.TestCase):
    """R06 handoff: stored event-confidence artifacts surface additively; absent is UNAVAILABLE."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.index = SessionIndex(self.root / "index.db", self.projects)
        self.library = SessionLibrary(self.projects)
        self.builder = ReportBuilder(self.projects, self.index)

    def tearDown(self):
        self.index.close()
        self.tmp.cleanup()

    def _generate(self, session_id):
        self.index.reindex()
        return self.builder.generate_reports(session_id)

    def test_absent_event_analysis_renders_unavailable_never_zero(self):
        self.library.create_session("ea-absent", kind="demo")
        artifacts = self._generate("ea-absent")
        doc = json.loads(artifacts["json"].read_text(encoding="utf-8"))
        section = doc["event_analysis"]
        self.assertEqual(section["status"], "UNAVAILABLE")
        self.assertEqual(section["gait_candidates"], "UNAVAILABLE")
        self.assertEqual(section["squat_candidates"], "UNAVAILABLE")
        self.assertEqual(section["manual_scoring"], "UNAVAILABLE")
        raw = artifacts["json"].read_text(encoding="utf-8")
        self.assertNotIn('"missed_reference_count": 0', raw)
        csv_text = artifacts["csv"].read_text(encoding="utf-8")
        self.assertIn("UNAVAILABLE", csv_text)
        self.assertEqual(doc["session_id"], "ea-absent")  # existing consumers unchanged

    def test_present_event_analysis_is_surfaced_additively(self):
        folder = self.library.create_session("ea-present", kind="demo")
        (folder / "gait-candidates.json").write_text(json.dumps(GAIT_CANDIDATES_DOC), encoding="utf-8")
        (folder / "squat-candidates.json").write_text(json.dumps(SQUAT_CANDIDATES_DOC), encoding="utf-8")
        from session_contract import sha256_file
        source = folder / "raw" / "cam01_trial.mp4"
        source.parent.mkdir(exist_ok=True)
        source.write_bytes(b"generated source identity fixture; not video")
        for name in ("gait-candidates.json", "squat-candidates.json"):
            candidate = json.loads((folder / name).read_text(encoding="utf-8"))
            candidate["source_sha256"] = sha256_file(source)
            (folder / name).write_text(json.dumps(candidate), encoding="utf-8")
        artifacts = self._generate("ea-present")
        doc = json.loads(artifacts["json"].read_text(encoding="utf-8"))
        section = doc["event_analysis"]
        self.assertEqual(section["status"], "TEST_ONLY_CANDIDATE_EVIDENCE_NOT_PHYSICAL_VALIDATION")
        gait = section["gait_candidates"][0]
        event = gait["candidates"][0]
        self.assertEqual(event["window_min_raw_landmark_score"], 0.5)
        self.assertEqual(event["window_min_score_margin_over_threshold"], 0.07)
        self.assertEqual(event["window_observed_frames"], 41)
        self.assertIs(event["model_score_is_probability"], False)
        self.assertEqual(gait["sample_exclusions"]["ambiguous_person_frames"], 3)
        self.assertEqual(gait["unsupported_metrics"][0]["status"], "UNSUPPORTED")
        self.assertIsNone(gait["unsupported_metrics"][0]["value"])
        squat = section["squat_candidates"][0]
        rep = squat["repetitions"][0]
        self.assertEqual(rep["min_required_landmark_raw_score"], 0.77)
        self.assertEqual(rep["unmeasured_frames_within_rep"], 0)
        self.assertEqual(squat["quality_exclusion_reasons"]["low_score_or_occluded"], 2)
        self.assertEqual(squat["incomplete_attempts"], 2)
        self.assertEqual(section["manual_scoring"], "UNAVAILABLE")
        self.assertEqual(gait["source_sha256"], sha256_file(source))
        self.assertTrue(doc["is_test_only"])
        self.assertFalse(doc["clinical_accuracy_verified"])

    def test_unknown_scoring_field_renders_unavailable_not_zero(self):
        folder = self.library.create_session("ea-partial", kind="demo")
        partial = {key: value for key, value in SCORING_DOC.items() if key != "by_event_type"}
        (folder / "manual-scoring.json").write_text(json.dumps(partial), encoding="utf-8")
        artifacts = self._generate("ea-partial")
        doc = json.loads(artifacts["json"].read_text(encoding="utf-8"))
        section = doc["event_analysis"]
        self.assertEqual(section["manual_scoring"][0]["missed_reference_count"], "UNAVAILABLE")
        self.assertEqual(section["manual_scoring"][0]["phase_boundary_disagreement_count"], "UNAVAILABLE")
        self.assertEqual(section["manual_scoring"][0]["status"], "BLOCKED_UNBOUND_SCORING")
        self.assertIn("source/reference binding", section["manual_scoring"][0]["reason"])
        self.assertIn("BLOCKED", section["status"])


class EventAnalysisValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.passport = {"sources": {"cam01_trial": {"sha256": "a" * 64,
                         "observed_sha256": "a" * 64, "integrity_state": "unchanged"}}}

    def collect(self, data, filename="gait-candidates.json"):
        (self.folder / filename).write_text(json.dumps(data), encoding="utf-8")
        return _collect_event_analysis(self.folder, self.passport)

    def assert_rejected(self, data, fragment):
        section = self.collect(data)
        self.assertIn("BLOCKED", section["status"])
        self.assertEqual(section["gait_candidates"], "UNAVAILABLE")
        self.assertIn(fragment, str(section["artifact_issues"]))

    def test_source_and_classification_are_required(self):
        for key, value, reason in (("source_sha256", "b" * 64, "source"),
                                    ("test_only", False, "test_only"),
                                    ("classification", "CLINICALLY_VALIDATED", "classification"),
                                    ("algorithm_version", "unknown", "algorithm_version")):
            with self.subTest(key=key):
                doc = copy.deepcopy(GAIT_CANDIDATES_DOC)
                doc[key] = value
                self.assert_rejected(doc, reason)

    def test_missing_or_non_list_candidates_is_invalid_not_zero(self):
        invalid_candidates: list = [None, 42, {}, [False]]
        for value in invalid_candidates:
            with self.subTest(value=value):
                doc = copy.deepcopy(GAIT_CANDIDATES_DOC)
                if value is None:
                    del doc["candidates"]
                else:
                    doc["candidates"] = value
                self.assert_rejected(doc, "candidates")

    def test_nonfinite_negative_boolean_and_malformed_values_are_rejected(self):
        for key, value in (("frame_index", False), ("frame_index", -1),
                           ("frame_index", 100), ("window_min_raw_landmark_score", "certain"),
                           ("window_min_raw_landmark_score", float("nan")),
                           ("window_min_raw_landmark_score", float("inf")),
                           ("window_observed_frames", -3),
                           ("model_score_is_probability", True)):
            with self.subTest(key=key, value=value):
                doc = copy.deepcopy(GAIT_CANDIDATES_DOC)
                doc["candidates"][0][key] = value
                section = self.collect(doc)
                self.assertIn("BLOCKED", section["status"])
                self.assertEqual(section["gait_candidates"], "UNAVAILABLE")

    def test_count_and_exclusion_mismatches_are_invalid(self):
        doc = copy.deepcopy(GAIT_CANDIDATES_DOC)
        doc["candidate_count"] = 0
        self.assert_rejected(doc, "candidate_count")
        doc = copy.deepcopy(GAIT_CANDIDATES_DOC)
        doc["sample_exclusions"]["ambiguous_person_frames"] = -1
        self.assert_rejected(doc, "sample_exclusions")

    def test_corrupt_and_incompatible_artifacts_are_not_absence(self):
        (self.folder / "gait-candidates.json").write_text("{", encoding="utf-8")
        section = _collect_event_analysis(self.folder, self.passport)
        self.assertIn("BLOCKED", section["status"])
        self.assertEqual(section["artifact_issues"][0]["status"], "INVALID")
        doc = copy.deepcopy(GAIT_CANDIDATES_DOC)
        doc["schema"] = "kinelab.2d-gait-candidates.v99"
        self.assert_rejected(doc, "schema")

    def test_current_generated_producer_outputs_are_accepted(self):
        from gait_events import orient_event_candidates, propose_extrema
        from test_gait_events import fixture
        from test_squat_events import fixture_reps, run

        gait = orient_event_candidates(propose_extrema(
            fixture(), "cam01_trial", "a" * 64, image_width=1024, image_height=576),
            screen_forward="right")
        section = self.collect(gait)
        self.assertEqual(section["artifact_issues"], [])
        self.assertEqual(section["gait_candidates"][0]["candidate_count"], gait["candidate_count"])
        squat = run(fixture_reps(1))
        section = self.collect(squat, "squat-candidates.json")
        self.assertEqual(section["artifact_issues"], [])
        self.assertEqual(section["squat_candidates"][0]["incomplete_attempts"], squat["incomplete_attempts"])

    def test_unbound_manual_scoring_never_promotes_counts(self):
        for value in (1, -7, True, "certain", float("nan")):
            with self.subTest(value=value):
                doc = copy.deepcopy(SCORING_DOC)
                doc["missed_reference_count"] = value
                section = self.collect(doc, "manual-scoring.json")
                self.assertIn("BLOCKED", section["status"])
                if section["manual_scoring"] == "UNAVAILABLE":
                    self.assertEqual(section["artifact_issues"][0]["status"], "INVALID")
                else:
                    self.assertEqual(section["manual_scoring"][0]["missed_reference_count"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
