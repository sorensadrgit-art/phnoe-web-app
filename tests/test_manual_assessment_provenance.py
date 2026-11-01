"""PROPOSED R06 contract: generated files only, no human/physical evidence.

Publisher/collector implementation is authorized after an observed RED.
These tests invoke the actual publisher; no envelope is manufactured by the test.
Fixture labels are analytic test inputs, never real independent annotations.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import math
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gait_events import (
    make_manual_reference,
    orient_event_candidates,
    propose_extrema,
    score_manual_reference,
)
from native_evidence_fixture import complete_native_fixture
from report_builder import _collect_event_analysis
from run_pipeline import validate_run_evidence
from session_contract import ROLES, sha256_file
from setup_project import register_captures
from squat_events import analyze_squats, compare_manual_reps, make_manual_rep_reference
from test_squat_events import fixture_reps

BOUND_STATUS = "BOUND_TEST_ONLY_MANUAL_AGREEMENT_NOT_CLINICAL_VALIDATION"


def generated_trajectory(source_sha256: str) -> dict:
    """Closed-form pixels and scores; no camera, video decoder or inference."""
    frames = []
    for frame in range(240):
        phase = 2 * math.pi * frame / 40
        points = [[255.0, 190.0] for _ in range(26)]
        points[19] = [300.0, 320.0]
        points[24] = [300 + 26 * math.sin(phase), 460.0]
        points[20] = [300 + 22 * math.sin(phase - math.pi / 2), 468.0]
        points[25] = [300 + 26 * math.sin(phase + math.pi), 461.0]
        points[21] = [300 + 22 * math.sin(phase + math.pi / 2), 466.0]
        frames.append({
            "frame_index": frame, "time_seconds": round(frame / 30, 6),
            "people_detected": 1, "selected_person_index": 0,
            "xy_pixels": points, "confidence": [0.92] * 26,
        })
    return {
        "schema": "kinelab.testonly.fullseq.halpe26.v1", "test_only": True,
        "role": "cam01_trial", "fps": 30, "source_sha256": source_sha256,
        "model_score_threshold": 0.43,
        "coordinates": "unscaled source-video 2D image pixels; not meters",
        "frames": frames,
    }


class ManualAssessmentProvenanceTests(unittest.TestCase):
    """Real local publisher/collector integration on generated contract files."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="generated-assessment-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name) / "generated-assessment"
        (self.folder / "raw").mkdir(parents=True)
        (self.folder / "Config.toml").write_text("[project]\n", encoding="utf-8")
        for role in ROLES:
            (self.folder / "raw" / f"{role}.mp4").write_bytes(
                f"GENERATED_CONTRACT_FIXTURE_ONLY {role}".encode()
            )
        self.session = register_captures(self.folder, self.folder.name)
        complete_native_fixture(self.folder, "", through="poseEstimation")
        validate_run_evidence(self.folder, "poseEstimation")
        self.inputs = self.folder / "assessment-inputs"
        self.inputs.mkdir()
        self.source_sha256 = self.session["captures"]["cam01_trial"]["sha256"]
        self.passport = {
            "session_id": self.session["session_id"], "kind": "test-only",
            "is_test_only": True,
            "sources": {"cam01_trial": {
                "sha256": self.source_sha256, "observed_sha256": self.source_sha256,
                "integrity_state": "unchanged",
            }},
        }
        self.prepare_gait()

    def write_inputs(self, trajectory, candidates, reference, score):
        for name, document in (
            ("trajectory.json", trajectory), ("candidates.json", candidates),
            ("reference.json", reference),
        ):
            (self.inputs / name).write_text(json.dumps(document, allow_nan=False), encoding="utf-8")
        self.score = score

    def prepare_gait(self):
        trajectory = generated_trajectory(self.source_sha256)
        base = propose_extrema(
            trajectory, "cam01_trial", self.source_sha256,
            image_width=1024, image_height=576,
        )
        candidates = orient_event_candidates(base, screen_forward="right")
        labels = [
            {"frame_index": 50, "side": "left", "event_type": "initial_contact"},
            {"frame_index": 70, "side": "left", "event_type": "toe_off"},
        ]
        reference = make_manual_reference(
            base, labels, reviewer="GENERATED analytic fixture; no human reviewer", confirmed=True,
        )
        score = score_manual_reference(candidates, reference, tolerance_frames=3)
        self.write_inputs(trajectory, candidates, reference, score)

    def prepare_squat(self):
        trajectory = fixture_reps(1)
        trajectory["source_sha256"] = self.source_sha256
        candidates = analyze_squats(
            trajectory, "cam01_trial", self.source_sha256,
            camera_view="side", activity_confirmed=True, image_width=1024, image_height=576,
        )
        # Analytic input phase timing, not copied from detected repetitions.
        reference = make_manual_rep_reference(
            candidates, [{"start_frame": 50, "bottom_frame": 73, "end_frame": 97}],
            reviewer="GENERATED analytic fixture; no human reviewer", confirmed=True,
        )
        score = compare_manual_reps(candidates, reference, tolerance_frames=3)
        self.write_inputs(trajectory, candidates, reference, score)

    def publisher(self):
        self.assertIsNotNone(importlib.util.find_spec("manual_assessment"),
                             "RED: actual immutable manual assessment publisher is absent")
        return importlib.import_module("manual_assessment")

    def publish(self, **overrides):
        arguments = {
            "trajectory_path": "assessment-inputs/trajectory.json",
            "candidates_path": "assessment-inputs/candidates.json",
            "reference_path": "assessment-inputs/reference.json",
            "output_name": "generated-first", "tolerance_frames": 3,
        }
        arguments.update(overrides)
        return self.publisher().publish_manual_assessment(self.folder, **arguments)

    def collect(self):
        return _collect_event_analysis(self.folder, self.passport)

    def assert_blocked(self, report):
        self.assertTrue(report["status"].startswith("BLOCKED"), report)
        self.assertIsInstance(report["manual_scoring"], list)
        for entry in report["manual_scoring"]:
            self.assertTrue(entry["status"].startswith("BLOCKED"), entry)
            for field in ("missed_reference_count", "unscorable_reference_count", "false_candidate_count"):
                self.assertEqual(entry[field], "UNAVAILABLE")

    def assert_bound(self, report, published):
        assessment = report["manual_scoring"][0]
        self.assertEqual(assessment["status"], BOUND_STATUS)
        fields = ("missed_reference_count", "unscorable_reference_count", "false_candidate_count")
        for field in fields:
            self.assertEqual(assessment[field], self.score[field])
        self.assertEqual(assessment["session_id"], self.session["session_id"])
        self.assertEqual(assessment["source_sha256"], self.source_sha256)
        self.assertEqual(assessment["artifact_sha256"], sha256_file(published))
        self.assertEqual(assessment["run_sha256"], sha256_file(self.folder / "run.json"))
        for name in ("candidates", "reference"):
            self.assertEqual(assessment[f"{name}_sha256"], sha256_file(self.inputs / f"{name}.json"))
        self.assertIs(assessment["test_only"], True)
        self.assertIs(assessment["clinical_accuracy_validated"], False)
        return assessment

    def test_actual_gait_publication_is_bound_and_preserves_every_input_byte(self):
        before = {p: p.read_bytes() for p in self.folder.rglob("*") if p.is_file()}
        published = self.publish()
        assessment = self.assert_bound(self.collect(), published)
        self.assertEqual(assessment["by_event_type"], self.score["by_event_type"])
        self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))
        after = {p: p.read_bytes() for p in self.folder.rglob("*") if p.is_file()}
        self.collect()
        self.assertEqual(after, {p: p.read_bytes() for p in self.folder.rglob("*") if p.is_file()})

    def test_actual_squat_publication_preserves_incomplete_and_phase_disagreements(self):
        self.prepare_squat()
        published = self.publish()
        assessment = self.assert_bound(self.collect(), published)
        for field in ("phase_boundary_disagreement_count", "incomplete_attempts"):
            self.assertEqual(assessment[field], self.score[field])

    def test_legacy_unbound_score_stays_unavailable(self):
        exports = self.folder / "exports"
        exports.mkdir()
        (exports / "legacy-scoring.json").write_text(json.dumps(self.score), encoding="utf-8")
        self.assert_blocked(self.collect())

    def test_reference_for_another_source_refuses_publication(self):
        path = self.inputs / "reference.json"
        reference = json.loads(path.read_text(encoding="utf-8"))
        reference["source_sha256"] = "0" * 64
        path.write_text(json.dumps(reference), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(list(self.folder.glob("exports/*.manual-assessment.json")), [])

    def test_candidates_must_reproduce_from_bound_trajectory(self):
        path = self.inputs / "candidates.json"
        candidates = json.loads(path.read_text(encoding="utf-8"))
        candidates["candidate_count"] += 1
        path.write_text(json.dumps(candidates), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.publish()

    def test_missing_run_or_unpassed_actual_stage_refuses_publication(self):
        path = self.folder / "run.json"
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            self.publish()
        path.write_bytes(original)
        run = json.loads(original)
        run["stages"][1]["status"] = "not-run"
        path.write_text(json.dumps(run), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.publish()

    def test_changed_current_source_makes_committed_assessment_unavailable(self):
        self.publish()
        (self.folder / "raw/cam01_trial.mp4").write_bytes(b"GENERATED changed capture")
        self.assert_blocked(self.collect())

    def test_changed_reference_candidate_run_or_snapshot_is_unavailable(self):
        published = self.publish()
        document = json.loads(published.read_text(encoding="utf-8"))
        for name in ("reference", "candidates", "trajectory", "run", "session"):
            binding = document["inputs"][name]
            for relative in (binding["path"], binding["snapshot"]["path"]):
                with self.subTest(input=name, path=relative):
                    path = self.folder / relative
                    original = path.read_bytes()
                    try:
                        path.write_bytes(original + b"\n ")
                        self.assert_blocked(self.collect())
                    finally:
                        path.write_bytes(original)

    def test_descriptor_forgery_is_not_accepted_as_recomputed_agreement(self):
        published = self.publish()
        document = json.loads(published.read_text(encoding="utf-8"))
        for field, value in (("session_id", "another-generated-session"),
                             ("test_only", False), ("clinical_accuracy_validated", True)):
            with self.subTest(field=field):
                modified = dict(document)
                modified[field] = value
                published.write_text(json.dumps(modified), encoding="utf-8")
                self.assert_blocked(self.collect())
        modified = dict(document)
        modified["score"] = {**document["score"], "missed_reference_count": 12345}
        published.write_text(json.dumps(modified), encoding="utf-8")
        self.assert_blocked(self.collect())

    def test_duplicate_publication_refuses_overwrite(self):
        published = self.publish()
        original = published.read_bytes()
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(published.read_bytes(), original)

    def test_parent_absolute_and_noncanonical_paths_refuse_publication(self):
        for relative in ("../outside.json", str(self.inputs / "reference.json"),
                         "assessment-inputs/../assessment-inputs/reference.json",
                         "assessment-inputs//reference.json"):
            with self.subTest(path=relative), self.assertRaises(ValueError):
                self.publish(reference_path=relative)

    def test_reparse_directory_is_refused_even_for_contained_target(self):
        target = self.inputs
        link = self.folder / "linked-inputs"
        if os.name == "nt":
            result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.publish(reference_path="linked-inputs/reference.json")

    def test_input_change_during_snapshotting_prevents_descriptor_commit(self):
        module = self.publisher()
        fsync = module.os.fsync
        changed = False

        def mutate_once(descriptor):
            nonlocal changed
            fsync(descriptor)
            if not changed:
                changed = True
                (self.inputs / "reference.json").write_bytes(b"GENERATED changed reference")

        with patch("manual_assessment.os.fsync", side_effect=mutate_once), self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(list(self.folder.glob("exports/*.manual-assessment.json")), [])
        self.assertEqual(self.collect()["manual_scoring"], "UNAVAILABLE")

    def test_failed_snapshot_never_publishes_an_accepted_descriptor(self):
        self.publisher()
        before = {p: p.read_bytes() for p in self.folder.rglob("*") if p.is_file()}
        with patch("manual_assessment.os.fsync", side_effect=OSError("GENERATED disk failure")), \
                self.assertRaises((OSError, ValueError)):
            self.publish()
        self.assertEqual(list(self.folder.glob("exports/*.manual-assessment.json")), [])
        self.assertEqual(self.collect()["manual_scoring"], "UNAVAILABLE")
        self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))


if __name__ == "__main__":
    unittest.main()
