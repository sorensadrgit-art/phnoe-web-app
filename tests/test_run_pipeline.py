import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class RunPipelineTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("audited_pipeline", ROOT / "run_pipeline.py")
        self.runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.runner)
        self.assertTrue(callable(getattr(self.runner, "run_stages", None)), "run_stages implementation missing")
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        (self.project / "Config.toml").write_text('[project]\nframe_rate=30\n', encoding="utf-8")
        self.inputs = {role: "a" * 64 for role in ("cam01_intrinsics", "cam02_intrinsics", "cam01_board", "cam02_board", "cam01_trial", "cam02_trial")}
        self.session = {"session_id": "test", "captures": {k: {"sha256": v} for k, v in self.inputs.items()}}
        self.preflight = {"schema": "kinelab.preflight.v1", "session_id": "test", "ok": True, "errors": [], "inputs": self.inputs,
                          "config_sha256": hashlib.sha256((self.project / "Config.toml").read_bytes()).hexdigest()}
        (self.project / "preflight.json").write_text(json.dumps(self.preflight), encoding="utf-8")
        from normalize_capture import ROLES
        outputs = {}
        for role, relative in ROLES.items():
            path = self.project / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"normalized")
            outputs[role] = {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        (self.project / "normalization.json").write_text(json.dumps({**self.preflight, "schema": "kinelab.normalization.v1", "outputs": outputs}))
        self.session_patch = patch.object(self.runner, "load_session", return_value=self.session)
        self.session_patch.start(); self.addCleanup(self.session_patch.stop)

    def test_missing_preflight_fails_before_native_call(self):
        (self.project / "preflight.json").unlink()
        with patch.object(self.runner, "_invoke_stage") as native:
            with self.assertRaisesRegex(ValueError, "PREFLIGHT"):
                self.runner.run_stages(self.project, "calibration", "calibration")
            native.assert_not_called()

    def test_stale_output_fails_and_records_no_success(self):
        path = self.project / "calibration" / "Calib.toml"; path.parent.mkdir(exist_ok=True); path.write_text("old")
        with patch.object(self.runner, "_invoke_stage"), patch.object(self.runner, "_validate_stage_quality", return_value={"ok": True}):
            with self.assertRaisesRegex(ValueError, "ARTIFACT"):
                self.runner.run_stages(self.project, "calibration", "calibration")
        record = json.loads((self.project / "run.json").read_text())
        self.assertEqual(record["stages"][0]["status"], "failed")
        self.assertFalse((self.project / "run.lock").exists())

    def test_fresh_output_passes_and_is_hashed(self):
        def generate(stage, project):
            path = project / "calibration" / "Calib.toml"; path.parent.mkdir(exist_ok=True); path.write_text("new")
        with patch.object(self.runner, "_invoke_stage", side_effect=generate), patch.object(self.runner, "_validate_stage_quality", return_value={"ok": True}):
            record = self.runner.run_stages(self.project, "calibration", "calibration")
        self.assertEqual(record["stages"][0]["status"], "passed")
        self.assertEqual(record["stages"][0]["artifacts"][0]["sha256"], hashlib.sha256(b"new").hexdigest())
        self.assertEqual(record["stages"][1]["status"], "not-run")

    def test_failure_stops_following_stages(self):
        with patch.object(self.runner, "_invoke_stage", side_effect=RuntimeError("native failure")) as native:
            with self.assertRaisesRegex(RuntimeError, "native failure"):
                self.runner.run_stages(self.project, "calibration", "poseEstimation")
        self.assertEqual(native.call_count, 1)
        record = json.loads((self.project / "run.json").read_text())
        self.assertEqual(record["stages"][0]["status"], "failed")
        self.assertEqual(record["stages"][1]["status"], "not-run")

    def test_changed_preflight_and_missing_prior_stage_rejected(self):
        self.preflight["inputs"]["cam01_trial"] = "b" * 64
        (self.project / "preflight.json").write_text(json.dumps(self.preflight))
        with patch.object(self.runner, "_invoke_stage") as native:
            with self.assertRaisesRegex(ValueError, "PREFLIGHT"):
                self.runner.run_stages(self.project, "calibration", "calibration")
            native.assert_not_called()
        self.preflight["inputs"]["cam01_trial"] = "a" * 64
        (self.project / "preflight.json").write_text(json.dumps(self.preflight))
        with self.assertRaisesRegex(ValueError, "ARTIFACT"):
            self.runner.run_stages(self.project, "filtering", "filtering")

    def test_changed_normalized_video_fails_before_processing(self):
        (self.project / "videos/cam01.mp4").write_bytes(b"changed")
        with patch.object(self.runner, "_invoke_stage") as native:
            with self.assertRaisesRegex(ValueError, "INPUT_CHANGED"):
                self.runner.run_stages(self.project, "calibration", "calibration")
            native.assert_not_called()

    def test_fresh_but_invalid_pose_json_is_not_a_passed_stage(self):
        calibration = self.project / "calibration/Calib.toml"; calibration.write_text("prior calibration")
        stages = [{"name": name, "status": "not-run", "artifacts": []} for name in self.runner.STAGES]
        stages[0].update(status="passed", artifacts=[{"path": "calibration/Calib.toml", "sha256": hashlib.sha256(calibration.read_bytes()).hexdigest()}])
        previous = {"schema": "kinelab.run.v1", "session_id": "test", "config_sha256": self.preflight["config_sha256"], "inputs": self.inputs, "stages": stages}
        (self.project / "run.json").write_text(json.dumps(previous))
        def invalid_pose(stage, project):
            path = project / "pose/cam01_json/cam01_000000.json"; path.parent.mkdir(parents=True); path.write_text("{}")
        with patch.object(self.runner, "_invoke_stage", side_effect=invalid_pose), patch.object(self.runner, "_validate_stage_quality", return_value={"ok": True}):
            with self.assertRaisesRegex(ValueError, "ARTIFACT"):
                self.runner.run_stages(self.project, "poseEstimation", "poseEstimation")

    def _passed_calibration(self):
        def generate(stage, project):
            (project / "calibration/Calib.toml").write_text("new")
        with patch.object(self.runner, "_invoke_stage", side_effect=generate), patch.object(self.runner, "_validate_stage_quality", return_value={"ok": True}):
            return self.runner.run_stages(self.project, "calibration", "calibration")

    def test_mixed_fresh_and_stale_pose_files_fail(self):
        self._passed_calibration()
        stale = self.project / "pose/cam02_json/cam02_000900.json"
        stale.parent.mkdir(parents=True); stale.write_text('{"people": []}')
        def generate(stage, project):
            fresh = project / "pose/cam01_json/cam01_000000.json"
            fresh.parent.mkdir(parents=True); fresh.write_text('{"people": []}')
        with patch.object(self.runner, "_invoke_stage", side_effect=generate), patch.object(self.runner, "_validate_stage_quality", return_value={"ok": True}):
            with self.assertRaisesRegex(ValueError, "ARTIFACT"):
                self.runner.run_stages(self.project, "poseEstimation", "poseEstimation")

    def test_added_unrecorded_prior_output_fails_before_resume(self):
        self._passed_calibration()
        (self.project / "calibration/Other.toml").write_text("unrecorded")
        with patch.object(self.runner, "_invoke_stage") as native:
            with self.assertRaisesRegex(ValueError, "ARTIFACT"):
                self.runner.run_stages(self.project, "poseEstimation", "poseEstimation")
            native.assert_not_called()

    def test_raw_pose_may_contain_multiple_people_before_association(self):
        path = self.project / "pose.json"
        path.write_text(json.dumps({"people": [{"pose_keypoints_2d": [1, 2, .9]}] * 2}))
        self.runner._validate_artifacts(self.project, "poseEstimation", ["pose.json"])
        with self.assertRaisesRegex(ValueError, "ARTIFACT"):
            self.runner._validate_artifacts(self.project, "personAssociation", ["pose.json"])

    def test_augmented_trc_does_not_change_filtering_inventory(self):
        folder = self.project / "pose-3d"; folder.mkdir()
        for name in ("trial.trc", "trial_filt.trc", "trial_filt_LSTM.trc"):
            (folder / name).write_text("ownership fixture")
        self.assertEqual(set(self.runner._artifacts(self.project, "filtering")), {"pose-3d/trial_filt.trc"})


if __name__ == "__main__":
    unittest.main()
