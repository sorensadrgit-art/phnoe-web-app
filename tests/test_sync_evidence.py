"""Evidence-first T3: manually observed video cue pairs, never synthetic clinical sync."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from session_contract import ROLES, sha256_file
from session_library import SessionLibrary
from setup_project import register_captures
from sync_evidence import SyncEvidenceError, prepare_sync, save_sync, suggested_reference


class SyncEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "projects"
        self.root.mkdir()
        self.project = SessionLibrary(self.root).create_session("real-pilot")
        for role in ROLES:
            (self.project / "raw" / (role + ".mp4")).write_bytes(("raw:" + role).encode())
        self.session = register_captures(self.project, "real-pilot", "real")
        (self.project / "videos").mkdir(exist_ok=True)
        normalized = {"schema": "kinelab.normalization.v1", "session_id": "real-pilot",
                      "config_sha256": sha256_file(self.project / "Config.toml"),
                      "inputs": {k: v["sha256"] for k, v in self.session["captures"].items()},
                      "outputs": {}}
        for role in ROLES:
            relative = ("videos/" + role[:5] + ".mp4") if role.endswith("trial") else (
                "calibration/intrinsics/" + role[:5] + "/intrinsics.mp4"
                if role.endswith("intrinsics") else "calibration/extrinsics/" + role[:5] + ".mp4"
            )
            target = self.project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(("processed:" + role).encode())
            count = 500 if role == "cam01_trial" else 450 if role == "cam02_trial" else 120
            normalized["outputs"][role] = {
                "path": relative, "sha256": sha256_file(target),
                "width": 1280, "height": 720, "fps": "30/1", "frame_count": count,
                "timestamps": [i / 30 for i in range(count)],
            }
        (self.project / "normalization.json").write_text(json.dumps(normalized))
        (self.project / "preflight.json").write_text(json.dumps({
            "schema": "kinelab.preflight.v1", "ok": True, "errors": [],
            "session_id": "real-pilot", "config_sha256": normalized["config_sha256"],
            "inputs": normalized["inputs"],
        }))
        self.cues = {"cam01": {"start": 56, "end": 390},
                     "cam02": {"start": 42, "end": 376}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_suggests_shorter_recording_without_fabricating_cues(self):
        self.assertEqual(suggested_reference(self.project), "cam02")
        with self.assertRaisesRegex(SyncEvidenceError, "four"):
            prepare_sync(self.project, {}, reference="cam02", operator_confirmed=True)

    def test_operator_frames_produce_signed_offset_and_all_four_measured_pairs(self):
        record = prepare_sync(self.project, self.cues, reference="cam02", operator_confirmed=True)
        self.assertEqual(record["reference"], "cam02")
        self.assertEqual(record["cameras"]["cam02"]["offset_frames"], 0)
        self.assertEqual(record["cameras"]["cam01"]["offset_frames"], 14)
        self.assertEqual(record["cameras"]["cam01"]["start_residual_frames"], 0)
        self.assertEqual(record["cameras"]["cam01"]["end_residual_frames"], 0)
        self.assertEqual(record["fps"], 30)
        self.assertEqual(len(record["source_frame_pairs"]), 4)
        self.assertEqual(record["inputs"], {k: v["sha256"] for k, v in self.session["captures"].items()})
        self.assertEqual(record["measurement_source"], "operator_marked_normalized_video_frames")
        self.assertFalse((self.project / "sync-observations.json").exists())

    def test_detects_at_most_one_frame_drift(self):
        cues = {"cam01": {"start": 56, "end": 391}, "cam02": {"start": 42, "end": 376}}
        record = prepare_sync(self.project, cues, reference="cam02", operator_confirmed=True)
        self.assertEqual(record["cameras"]["cam01"]["end_residual_frames"], 1)
        cues["cam01"]["end"] = 393
        with self.assertRaisesRegex(SyncEvidenceError, "drift"):
            prepare_sync(self.project, cues, reference="cam02", operator_confirmed=True)

    def test_reversed_camera_reference_gives_negative_signed_offset(self):
        record = prepare_sync(self.project, self.cues, reference="cam01", operator_confirmed=True)
        self.assertEqual(record["cameras"]["cam02"]["offset_frames"], -14)
        self.assertEqual(record["cameras"]["cam01"]["offset_frames"], 0)

    def test_wrong_cue_frame_indices_are_rejected(self):
        for cues in [
            {"cam01": {"start": -1, "end": 390}, "cam02": {"start": 42, "end": 376}},
            {"cam01": {"start": 56, "end": 500}, "cam02": {"start": 42, "end": 376}},
            {"cam01": {"start": 390, "end": 56}, "cam02": {"start": 42, "end": 376}},
            {"cam01": {"start": 56, "end": 60}, "cam02": {"start": 42, "end": 46}},
            {"cam01": {"start": 56.5, "end": 390}, "cam02": {"start": 42, "end": 376}},
        ]:
            with self.subTest(cues=cues), self.assertRaises(SyncEvidenceError):
                prepare_sync(self.project, cues, reference="cam02", operator_confirmed=True)

    def test_cues_only_saved_when_operator_explicitly_confirms(self):
        with self.assertRaisesRegex(SyncEvidenceError, "operator"):
            prepare_sync(self.project, self.cues, reference="cam02", operator_confirmed=False)
        self.assertFalse((self.project / "sync-observations.json").exists())

    def test_no_overwrite_of_previous_marked_evidence(self):
        path = save_sync(self.project, self.cues, reference="cam02", operator_confirmed=True)
        before = path.read_bytes()
        self.assertEqual(json.loads(before)["session_id"], "real-pilot")
        with self.assertRaises(FileExistsError):
            save_sync(self.project, self.cues, reference="cam02", operator_confirmed=True)
        self.assertEqual(before, path.read_bytes())

    def test_changed_source_clip_blocks_all_observations(self):
        (self.project / "raw" / "cam01_trial.mp4").write_bytes(b"altered")
        with self.assertRaisesRegex(SyncEvidenceError, "source|changed|registered"):
            prepare_sync(self.project, self.cues, reference="cam02", operator_confirmed=True)

    def test_changed_normalized_outputs_block_observations(self):
        (self.project / "videos" / "cam01.mp4").write_bytes(b"altered")
        with self.assertRaisesRegex(SyncEvidenceError, "normalized|changed|preflight"):
            prepare_sync(self.project, self.cues, reference="cam02", operator_confirmed=True)

    def test_unregistered_and_mixed_sample_sessions_not_accepted(self):
        (self.project / "SAMPLE-PROVENANCE.json").write_text("{}")
        with self.assertRaisesRegex(SyncEvidenceError, "test-only"):
            prepare_sync(self.project, self.cues, reference="cam02", operator_confirmed=True)

    def test_generated_evidence_matches_native_validator_with_synthetic_log(self):
        from pipeline_quality import validate_sync
        record = prepare_sync(self.project, self.cues, reference="cam02", operator_confirmed=True)
        (self.project / "logs.txt").write_text(
            "Camera cam02 and cam01: 14 frames offset correlation 0.95\n", encoding="utf-8")
        result = validate_sync(self.project, self.session, record, [0, len(data := (self.project / "logs.txt").read_bytes()), hashlib.sha256(data).hexdigest()])
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["reference"], "cam02")
        self.assertEqual(result["cameras"]["cam01"]["offset_frames"], 14)
        # A fabricated native log is used *only* in this test fixture; never actual validation.
        (self.project / "logs.txt").write_text(
            "Camera cam02 and cam01: 15 frames offset correlation 0.95\n", encoding="utf-8")
        rejected = validate_sync(self.project, self.session, record, [0, len(data := (self.project / "logs.txt").read_bytes()), hashlib.sha256(data).hexdigest()])
        self.assertFalse(rejected["ok"])

    def test_existing_passing_data_remains_labelled_unvalidated_until_native_sync(self):
        record = prepare_sync(self.project, self.cues, reference="cam02", operator_confirmed=True)
        self.assertEqual(record["native_sync_verified"], False)
        self.assertEqual(record["status"], "pending_native_pose2sim_validation")
        self.assertFalse((self.project / "sync.json").exists())


if __name__ == "__main__":
    unittest.main()
