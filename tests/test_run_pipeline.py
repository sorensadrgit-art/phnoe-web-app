import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
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
        # Real generated media; no production decoder/provenance override.
        from native_evidence_fixture import generated_normalization
        generated_normalization(self.project, {
            "session_id": "test", "config_sha256": self.preflight["config_sha256"],
            "inputs": self.inputs,
        })
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
        with (patch.object(self.runner, "_invoke_stage"),
                patch.object(self.runner, "_validate_stage_quality", return_value={"ok": True}),
                self.assertRaisesRegex(ValueError, "ARTIFACT")):
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
        with (patch.object(self.runner, "_invoke_stage", side_effect=RuntimeError("native failure")) as native,
                self.assertRaisesRegex(RuntimeError, "native failure")):
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
            before = {path.relative_to(self.project).as_posix(): path.read_bytes()
                      for path in self.project.rglob("*") if path.is_file()}
            with self.assertRaisesRegex(ValueError, "INPUT_CHANGED") as caught:
                self.runner.run_stages(self.project, "calibration", "calibration")
            native.assert_not_called()
            self.assertEqual(str(caught.exception.__cause__),
                             "QUALITY_UNVERIFIED: decoded source coverage: normalized media binding differs")
            self.assertEqual({path.relative_to(self.project).as_posix(): path.read_bytes()
                              for path in self.project.rglob("*") if path.is_file()}, before)

    def test_normalization_adapter_preserves_unrelated_failure_identity(self):
        # Isolated error-adapter unit seam; never a successful decode substitute.
        for failure in (
            ValueError("QUALITY_UNVERIFIED: decoded source coverage: normalization identity differs"),
            ValueError("QUALITY_UNVERIFIED: decoded source coverage: independent decode required"),
            OSError("TEST_ONLY media read failure"),
        ):
            with (self.subTest(failure=str(failure)),
                  patch("source_coverage.capture_normalization", side_effect=failure),
                  self.assertRaises(type(failure)) as caught):
                self.runner._verify_normalized(self.project, {})
            self.assertIs(caught.exception, failure)

    def test_fresh_but_invalid_pose_json_is_not_a_passed_stage(self):
        calibration = self.project / "calibration/Calib.toml"; calibration.write_text("prior calibration")
        stages = [{"name": name, "status": "not-run", "artifacts": []} for name in self.runner.STAGES]
        stages[0].update(status="passed", artifacts=[{"path": "calibration/Calib.toml", "sha256": hashlib.sha256(calibration.read_bytes()).hexdigest()}])
        previous = {"schema": "kinelab.run.v1", "session_id": "test", "config_sha256": self.preflight["config_sha256"], "inputs": self.inputs, "stages": stages}
        (self.project / "run.json").write_text(json.dumps(previous))
        def invalid_pose(stage, project):
            path = project / "pose/cam01_json/cam01_000000.json"; path.parent.mkdir(parents=True); path.write_text("{}")
        with (patch.object(self.runner, "_invoke_stage", side_effect=invalid_pose),
                patch.object(self.runner, "_validate_stage_quality", return_value={"ok": True}),
                self.assertRaisesRegex(ValueError, "ARTIFACT")):
            self.runner.run_stages(self.project, "poseEstimation", "poseEstimation")

    def _passed_calibration(self):
        return self._native_calibration(append_log=True)

    def test_mixed_fresh_and_stale_pose_files_fail(self):
        self._passed_calibration()
        stale = self.project / "pose/cam02_json/cam02_000900.json"
        stale.parent.mkdir(parents=True); stale.write_text('{"people": []}')
        def generate(stage, project):
            fresh = project / "pose/cam01_json/cam01_000000.json"
            fresh.parent.mkdir(parents=True); fresh.write_text('{"people": []}')
        with (patch.object(self.runner, "_invoke_stage", side_effect=generate),
                patch.object(self.runner, "_validate_stage_quality", return_value={"ok": True}),
                self.assertRaisesRegex(ValueError, "ARTIFACT")):
            self.runner.run_stages(self.project, "poseEstimation", "poseEstimation")

    def test_added_unrecorded_prior_output_fails_before_resume(self):
        self._passed_calibration()
        (self.project / "calibration/Other.toml").write_text("unrecorded")
        with patch.object(self.runner, "_invoke_stage") as native:
            with self.assertRaisesRegex(ValueError, "ARTIFACT"):
                self.runner.run_stages(self.project, "poseEstimation", "poseEstimation")
            native.assert_not_called()

    def test_resume_refuses_missing_prior_quality_before_native_work(self):
        record = self._passed_calibration()
        record["stages"][0].pop("quality")
        (self.project / "run.json").write_text(json.dumps(record))
        def generate(stage, project):
            path = project / "pose/cam01_json/cam01_000000.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"people": []}')
        with patch.object(self.runner, "_invoke_stage", side_effect=generate) as native, patch.object(self.runner, "_validate_stage_quality", return_value={"ok": True}):
            with self.assertRaisesRegex(ValueError, "QUALITY"):
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

    def _trc(self, relative, names, rows):
        lines = ["PathFileType\t4\t(X/Y/Z)\t" + Path(relative).name, "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits",
                 f"30\t30\t{len(rows)}\t{len(names)}\tm", "\t".join(["Frame#", "Time"] + [p for n in names for p in (n, "", "")]),
                 "\t".join(["", ""] + [a + str(i) for i in range(1, len(names) + 1) for a in "XYZ"])]
        for index, (time, points) in enumerate(rows):
            lines.append("\t".join([str(index), str(time)] + [v for p in points for v in (["", "", ""] if p is None else map(str, p))]))
        path = self.project / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("\n".join(lines) + "\n")
        return relative

    def _record(self, **stages):
        record = {"stages": [{"name": name, "status": "not-run", "artifacts": []} for name in self.runner.STAGES]}
        for name, paths in stages.items():
            record["stages"][self.runner.STAGES.index(name)].update(status="passed", artifacts=[
                {"path": p, "sha256": hashlib.sha256((self.project / p).read_bytes()).hexdigest()} for p in paths])
        return record

    def _calibration_toml(self):
        import rtoml
        cameras = {name: {"name": name, "size": [1280, 720], "matrix": [[1000, 0, 640], [0, 1000, 360], [0, 0, 1]], "distortions": [0, 0, 0, 0],
                          "rotation": [0, 0, 0], "translation": [index, 0, 2], "fisheye": False} for index, name in enumerate(["cam01", "cam02"])}
        return rtoml.dumps(cameras)

    def _native_calibration(self, append_log):
        self.session["camera_ids"] = ["cam01", "cam02"]
        def generate(stage, project):
            (project / "calibration/Calib.toml").write_text(self._calibration_toml())
            if append_log:
                with (project / "logs.txt").open("a", encoding="utf-8") as log:
                    log.write("Residual (RMS) calibration errors for each camera are respectively [0.2, 0.3] px,\n")
        with patch.object(self.runner, "_invoke_stage", side_effect=generate):
            return self.runner.run_stages(self.project, "calibration", "calibration")

    def test_stale_previous_log_rms_cannot_accept_fresh_calibration(self):
        (self.project / "logs.txt").write_text("Residual (RMS) calibration errors for each camera are respectively [0.2, 0.3] px,\n")
        with self.assertRaisesRegex(ValueError, "QUALITY_REJECTED"):
            self._native_calibration(append_log=False)

    def test_calibration_quality_bound_to_this_invocation_log_window(self):
        log = self.project / "logs.txt"
        log.write_text("Residual (RMS) calibration errors for each camera are respectively [9.0, 9.0] px,\n")
        start = log.stat().st_size
        record = self._native_calibration(append_log=True)
        binding = record["stages"][0]["quality"]["log"]
        data = log.read_bytes()
        self.assertEqual((binding["path"], binding["start"], binding["end"]), ("logs.txt", start, len(data)))
        self.assertEqual(binding["sha256"], hashlib.sha256(data[start:]).hexdigest())
        self.assertEqual(record["quality_policy"], self.runner.QUALITY_POLICY)
        with log.open("ab") as stream:
            stream.write(b"later appended native log line\n")
        self.runner.validate_run_evidence(self.project, "calibration", session=self.session)
        log.write_bytes(data[:start] + data[start:].replace(b"0.2", b"0.9") + b"later appended native log line\n")
        with self.assertRaisesRegex(ValueError, "QUALITY_UNVERIFIED"):
            self.runner.validate_run_evidence(self.project, "calibration", session=self.session)
        log.write_bytes(data[:start])
        with self.assertRaisesRegex(ValueError, "QUALITY_UNVERIFIED"):
            self.runner.validate_run_evidence(self.project, "calibration", session=self.session)

    def test_same_length_log_rewrite_after_native_call_is_rejected(self):
        real = self.runner._log_window
        def rewrite_after_capture(project, mark):
            window = real(project, mark)
            log = project / "logs.txt"
            log.write_bytes(log.read_bytes().replace(b"[0.2, 0.3]", b"[0.9, 0.9]"))
            return window
        with patch.object(self.runner, "_log_window", side_effect=rewrite_after_capture), self.assertRaisesRegex(ValueError, "QUALITY_REJECTED"):
            self._native_calibration(append_log=True)
    def test_log_rotation_during_invocation_fails_closed(self):
        self.session["camera_ids"] = ["cam01", "cam02"]
        (self.project / "logs.txt").write_text("previous week of native logs\n" * 4)
        def rotate(stage, project):
            (project / "calibration/Calib.toml").write_text(self._calibration_toml())
            (project / "logs.txt").write_text("Residual (RMS) calibration errors for each camera are respectively [0.2, 0.3] px,\n" * 3)
        with patch.object(self.runner, "_invoke_stage", side_effect=rotate), self.assertRaisesRegex(ValueError, "QUALITY_REJECTED"):
            self.runner.run_stages(self.project, "calibration", "calibration")

    def test_missing_or_older_quality_policy_is_rejected(self):
        self._native_calibration(append_log=True)
        run = json.loads((self.project / "run.json").read_text())
        for policy in (None, "kinelab.pipeline-quality.v1", "kinelab.pipeline-quality.v2", "kinelab.pipeline-quality.v3"):
            with self.subTest(policy=policy):
                changed = dict(run)
                changed.pop("quality_policy")
                if policy:
                    changed["quality_policy"] = policy
                (self.project / "run.json").write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "QUALITY_POLICY"):
                    self.runner.validate_run_evidence(self.project, "calibration", session=self.session)

    def test_filtering_must_preserve_source_frames_markers_and_gaps(self):
        source = self._trc("pose-3d/t_0-3.trc", ["Hip", "RKnee"], [(0, [(0, 1, 2), (1, 1, 1)]), (1 / 30, [(0, 1, 2), None]), (2 / 30, [(0, 1, 2), (1, 1, 1)])])
        record = self._record(triangulation=[source])
        cases = {
            "preserved gap, native last-frame crop": ([(0, [(0, 1, 2), (1, 1, 1)]), (1 / 30, [(0.1, 1, 2), None])], True),
            "fabricated gap fill": ([(0, [(0, 1, 2), (1, 1, 1)]), (1 / 30, [(0, 1, 2), (1, 1, 1)]), (2 / 30, [(0, 1, 2), (1, 1, 1)])], False),
            "dropped observation": ([(0, [(0, 1, 2), None]), (1 / 30, [(0, 1, 2), None])], False),
            "times not from source": ([(0.5, [(0, 1, 2), (1, 1, 1)])], False),
        }
        for label, (rows, expected) in cases.items():
            with self.subTest(label):
                output = self._trc("pose-3d/t_0-3_filt_butterworth.trc", ["Hip", "RKnee"], rows)
                quality = self.runner._validate_stage_quality("filtering", self.project, self.session, record, [output], None)
                self.assertIs(quality["ok"], expected, quality.get("errors"))
                if expected:
                    self.assertEqual(quality["source"]["sha256"], record["stages"][4]["artifacts"][0]["sha256"])
                    self.assertEqual(quality["policy"], self.runner.QUALITY_POLICY)
        output = self._trc("pose-3d/t_0-3_filt_butterworth.trc", ["Hip", "LKnee"], [(0, [(0, 1, 2), (1, 1, 1)])])
        self.assertFalse(self.runner._validate_stage_quality("filtering", self.project, self.session, record, [output], None)["ok"])

    def test_augmentation_preserves_originals_and_labels_model_markers_derived(self):
        rows = [(0, [(0, 1, 2), (1, 1, 1)]), (1 / 30, [(0, 1, 2), None])]
        source = self._trc("pose-3d/t_filt.trc", ["Hip", "RKnee"], rows)
        record = self._record(filtering=[source])
        good = self._trc("pose-3d/t_filt_LSTM.trc", ["Hip", "RKnee", "r_knee_study"], [(t, p + [(1, 2, 3)]) for t, p in rows])
        quality = self.runner._validate_stage_quality("markerAugmentation", self.project, self.session, record, [good], None)
        self.assertTrue(quality["ok"], quality.get("errors"))
        self.assertEqual(quality["derived_markers"], ["r_knee_study"])
        self.assertIn("derived", quality["derived_classification"])
        for label, names, changed in (("moved original (feet on floor)", ["Hip", "RKnee", "r_knee_study"], [(t, [(0, 0.9, 2), p[1], (1, 2, 3)]) for t, p in rows]),
                                      ("no model-derived markers", ["Hip", "RKnee"], rows),
                                      ("original marker removed", ["Hip", "r_knee_study"], [(t, [p[0], (1, 2, 3)]) for t, p in rows])):
            with self.subTest(label):
                output = self._trc("pose-3d/t_filt_LSTM.trc", names, changed)
                self.assertFalse(self.runner._validate_stage_quality("markerAugmentation", self.project, self.session, record, [output], None)["ok"])

    def test_unsupported_stage_quality_is_never_a_placeholder_success(self):
        quality = self.runner._validate_stage_quality("markerAugmentation", self.project, self.session, self._record(), [], None)
        self.assertFalse(quality["ok"])

    def _kinematics_fixture(self):
        rows = [(0, [(0, 1, 2)]), (1 / 30, [(0, 1, 2)])]
        filt = self._trc("pose-3d/t_filt.trc", ["Hip"], rows)
        lstm = self._trc("pose-3d/t_filt_LSTM.trc", ["Hip", "C7_study"], [(t, p + [(1, 1, 1)]) for t, p in rows])
        (self.project / "kinematics").mkdir()
        (self.project / "kinematics/t_filt_LSTM.mot").write_text("generated")
        (self.project / "kinematics/t_filt_LSTM.osim").write_text("<OpenSimDocument/>")
        return self._record(filtering=[filt], markerAugmentation=[lstm]), ["kinematics/t_filt_LSTM.mot", "kinematics/t_filt_LSTM.osim"]

    def test_kinematics_requires_fitted_model_and_helper_policy(self):
        import types
        record, fresh = self._kinematics_fixture()
        self.assertEqual(set(self.runner._artifacts(self.project, "kinematics")), set(fresh))
        calls = []
        def helper(project, *, model_path, mot_path, trc_path, **_):
            calls.append((Path(model_path), Path(mot_path), Path(trc_path)))
            return result
        module = types.SimpleNamespace(KINEMATICS_QUALITY_POLICY="kinelab.kinematics-quality.v1", validate_kinematics_stage=helper)
        result = {"ok": True, "policy": "kinelab.kinematics-quality.v1", "code": None, "errors": []}
        with patch.dict(sys.modules, {"kinematics_quality": module}):
            quality = self.runner._validate_stage_quality("kinematics", self.project, self.session, record, fresh, None)
            self.assertTrue(quality["ok"], quality.get("errors"))
            self.assertEqual(calls[-1], (self.project / fresh[1], self.project / fresh[0], self.project / "pose-3d/t_filt_LSTM.trc"))
            self.assertEqual(quality["consumed_trc"]["path"], "pose-3d/t_filt_LSTM.trc")
            for bad in ({"ok": True, "policy": "kinelab.kinematics-quality.v0"}, {"ok": "true", "policy": "kinelab.kinematics-quality.v1"},
                        {"ok": False, "policy": "kinelab.kinematics-quality.v1", "code": "KINEMATICS_QUALITY_UNAVAILABLE"}, None):
                with self.subTest(result=bad):
                    result = bad
                    self.assertFalse(self.runner._validate_stage_quality("kinematics", self.project, self.session, record, fresh, None)["ok"])
            result = {"ok": True, "policy": "kinelab.kinematics-quality.v1"}
            self.assertFalse(self.runner._validate_stage_quality("kinematics", self.project, self.session, record, fresh[:1], None)["ok"])
            (self.project / "pose-3d/t_filt_LSTM.trc").write_text((self.project / "pose-3d/t_filt_LSTM.trc").read_text().replace("\t1\t1\t1", "\t1\t1\t2"))
            self.assertFalse(self.runner._validate_stage_quality("kinematics", self.project, self.session, record, fresh, None)["ok"])
        with patch.dict(sys.modules, {"kinematics_quality": None}):
            self.assertFalse(self.runner._validate_stage_quality("kinematics", self.project, self.session, record, fresh, None)["ok"])

    def test_kinematics_gate_with_real_helper_on_generated_opensim_fixture(self):
        import test_kinematics_quality as generated
        (self.project / "kinematics").mkdir(); (self.project / "pose-3d").mkdir()
        model = generated.build_model(self.project / "kinematics/t_filt_LSTM.osim")
        rows = generated.trajectories()
        mot = generated.write_mot(self.project / "kinematics/t_filt_LSTM.mot", rows)
        generated.write_trc(self.project / "pose-3d/t_filt_LSTM.trc", [r[0] for r in rows], generated.forward_markers(model, rows))
        record = self._record(markerAugmentation=["pose-3d/t_filt_LSTM.trc"])
        fresh = ["kinematics/t_filt_LSTM.mot", "kinematics/t_filt_LSTM.osim"]
        quality = self.runner._validate_stage_quality("kinematics", self.project, self.session, record, fresh, None)
        self.assertTrue(quality["ok"], quality.get("errors"))
        self.assertEqual(quality["policy"], self.runner.KINEMATICS_POLICY)
        self.assertEqual(quality["sources"]["trc"]["path"], "pose-3d/t_filt_LSTM.trc")
        generated.write_mot(mot, rows, times=[r[0] + 0.5 for r in rows])
        self.assertFalse(self.runner._validate_stage_quality("kinematics", self.project, self.session, record, fresh, None)["ok"])


if __name__ == "__main__":
    unittest.main()
