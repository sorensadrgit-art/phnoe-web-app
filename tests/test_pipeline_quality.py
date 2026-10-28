import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import rtoml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class QualityTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / "pipeline_quality.py"
        self.assertTrue(source.is_file(), "pipeline_quality.py implementation missing")
        spec = importlib.util.spec_from_file_location("quality_under_test", source)
        self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name); self.session = {"session_id": "test", "camera_ids": ["cam01", "cam02"]}

    def test_sync_known_offset_and_independent_cues(self):
        (self.project / "logs.txt").write_text("--> Camera cam01 and cam02: 5 frames offset, correlation 0.99.\n")
        data = {"session_id": "test", "reference": "cam01", "fps": 30, "cameras": {
            "cam01": {"offset_frames": 0, "start_residual_frames": 0, "end_residual_frames": 0},
            "cam02": {"offset_frames": 5, "start_residual_frames": 0, "end_residual_frames": 0}},
            "source_frame_pairs": [{"camera": name, "synchronized_frame_index": frame, "source_frame_index": frame + offset}
                                   for name, offset in (("cam01", 0), ("cam02", 5)) for frame in (10, 100)]}
        result = self.module.validate_sync(self.project, self.session, data)
        self.assertTrue(result["ok"])
        data["cameras"]["cam02"]["offset_frames"] = -5
        self.assertFalse(self.module.validate_sync(self.project, self.session, data)["ok"])
        data["cameras"]["cam02"]["offset_frames"] = 5
        data["cameras"]["cam02"]["end_residual_frames"] = 2
        self.assertFalse(self.module.validate_sync(self.project, self.session, data)["ok"])

    def test_missing_sync_evidence_is_not_zero_residual(self):
        result = self.module.validate_sync(self.project, self.session, {})
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])

    def test_native_cam02_reference_preserves_actual_frame_indices(self):
        (self.project / "logs.txt").write_text("--> Camera cam02 and cam01: -5 frames offset, correlation 0.99.\n")
        observations = {"session_id": "test", "reference": "cam02", "fps": 30, "cameras": {
            "cam01": {"offset_frames": -5, "start_residual_frames": 0, "end_residual_frames": 0},
            "cam02": {"offset_frames": 0, "start_residual_frames": 0, "end_residual_frames": 0}},
            "source_frame_pairs": [{"camera": name, "synchronized_frame_index": frame, "source_frame_index": frame + offset}
                                   for name, offset in (("cam01", -5), ("cam02", 0)) for frame in (10, 100)]}
        result = self.module.validate_sync(self.project, self.session, observations)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["reference"], "cam02")

    def test_cue_pairs_cannot_conceal_drift_with_claimed_zero_residuals(self):
        (self.project / "logs.txt").write_text("--> Camera cam01 and cam02: 5 frames offset, correlation 0.99.\n")
        observations = {"session_id": "test", "reference": "cam01", "fps": 30, "cameras": {
            "cam01": {"offset_frames": 0, "start_residual_frames": 0, "end_residual_frames": 0},
            "cam02": {"offset_frames": 5, "start_residual_frames": 0, "end_residual_frames": 0}},
            "source_frame_pairs": [{"camera": "cam01", "synchronized_frame_index": 10, "source_frame_index": 10},
                                   {"camera": "cam01", "synchronized_frame_index": 20, "source_frame_index": 20},
                                   {"camera": "cam02", "synchronized_frame_index": 10, "source_frame_index": 16},
                                   {"camera": "cam02", "synchronized_frame_index": 20, "source_frame_index": 24}]}
        self.assertFalse(self.module.validate_sync(self.project, self.session, observations)["ok"])

    def test_reconstruction_interpolation_does_not_count_as_observed(self):
        samples = [{"marker": "RKnee", "frame": index, "views": 2, "likelihoods": [0.9, 0.9], "reprojection_px": 1.0, "interpolated": False} for index in range(100)]
        self.assertTrue(self.module.assess_reconstruction(samples, ["RKnee"])["ok"])
        for row in samples[:6]: row["interpolated"] = True
        result = self.module.assess_reconstruction(samples, ["RKnee"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["markers"]["RKnee"]["observed"], 94)

    def test_calibration_placeholder_zero_does_not_prove_fit(self):
        calibration = self.project / "calibration"; calibration.mkdir()
        cameras = {name: {"name": name, "size": [1280, 720], "matrix": [[1000, 0, 640], [0, 1000, 360], [0, 0, 1]], "distortions": [0, 0, 0, 0], "rotation": [0, 0, 0], "translation": [index, 0, 2], "fisheye": False} for index, name in enumerate(["cam01", "cam02"])}
        cameras["metadata"] = {"error": 0.0, "adjusted": False}
        (calibration / "Calib.toml").write_text(rtoml.dumps(cameras))
        self.assertFalse(self.module.validate_calibration(self.project, self.session)["ok"])
        (self.project / "logs.txt").write_text("Residual (RMS) calibration errors for each camera are respectively [0.2, 0.3] px,\n")
        self.assertTrue(self.module.validate_calibration(self.project, self.session)["ok"])

    def test_native_reprojection_adapter_checks_actual_pose_files(self):
        import cv2
        import numpy as np
        from anytree import RenderTree
        from Pose2Sim.skeletons import HALPE_26
        required = ["Hip", "RHip", "RKnee", "RAnkle", "LHip", "LKnee", "LAnkle"]
        ids = {node.name: node.id for _, _, node in RenderTree(HALPE_26) if node.id is not None}
        calibration = self.project / "calibration"; calibration.mkdir()
        cameras = {name: {"name": name, "size": [1280, 720], "matrix": [[1000, 0, 640], [0, 1000, 360], [0, 0, 1]],
                         "distortions": [0, 0, 0, 0], "rotation": [0, 0, 0], "translation": [index, 0, 2], "fisheye": False} for index, name in enumerate(["cam01", "cam02"])}
        (calibration / "Calib.toml").write_text(rtoml.dumps(cameras))
        (self.project / "Config.toml").write_text('[pose]\npose_model="Body_with_feet"\n')
        (self.project / "run.json").write_text(json.dumps({"native_triangulation_policy": {"interpolation": "none", "fill_large_gaps_with": "nan"}}))
        pose3d = self.project / "pose-3d"; pose3d.mkdir()
        header = ["Frame#", "Time"] + [part for name in required for part in (name, "", "")]
        axes = ["", ""] + [axis + str(i) for i in range(1, len(required) + 1) for axis in "XYZ"]
        lines = ["PathFileType\t4\t(X/Y/Z)\tsynthetic.trc", "DataRate\tNumFrames\tNumMarkers\tUnits", f"30\t2\t{len(required)}\tm", "\t".join(header), "\t".join(axes)]
        for frame in range(2):
            lines.append("\t".join([str(frame), str(frame / 30)] + [value for _ in required for value in ("0", "2", "0")]))
        (pose3d / "synthetic_0-1.trc").write_text("\n".join(lines) + "\n")
        for name, camera in cameras.items():
            folder = self.project / "pose-associated" / (name + "_json"); folder.mkdir(parents=True)
            projected, _ = cv2.projectPoints(np.asarray([[0., 0., 2.]]), np.zeros(3), np.asarray(camera["translation"], dtype=float), np.asarray(camera["matrix"], dtype=float), np.zeros(4))
            x, y = projected.reshape(-1)
            keypoints = [0.] * ((max(ids.values()) + 1) * 3)
            for marker in required: keypoints[ids[marker]*3:ids[marker]*3+3] = [float(x), float(y), .9]
            for frame in range(2): (folder / f"{name}_{frame:06d}.json").write_text(json.dumps({"people": [{"pose_keypoints_2d": keypoints}]}))
        self.assertTrue(self.module.validate_reconstruction(self.project, self.session)["ok"])
        (self.project / "pose-associated/cam02_json/cam02_000001.json").unlink()
        self.assertFalse(self.module.validate_reconstruction(self.project, self.session)["ok"])


if __name__ == "__main__":
    unittest.main()
