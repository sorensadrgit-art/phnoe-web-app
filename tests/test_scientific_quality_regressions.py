"""Generated numeric fixtures; no physical accuracy or clinical acceptance."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
import rtoml

import pipeline_quality as quality


class ScientificQualityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.session = {"session_id": "generated", "camera_ids": ["cam01", "cam02"]}
        self.cameras = {name: {"name": name, "size": [1280, 720],
                              "matrix": [[1000, 0, 640], [0, 1000, 360], [0, 0, 1]],
                              "distortions": [0, 0, 0, 0], "rotation": [0, 0, 0],
                              "translation": [index, 0, 2], "fisheye": False}
                        for index, name in enumerate(self.session["camera_ids"])}
        (self.project / "calibration").mkdir()
        self.write_calibration()

    def window(self):
        import hashlib
        data = (self.project / "logs.txt").read_bytes()
        return [0, len(data), hashlib.sha256(data).hexdigest()]

    def write_calibration(self):
        (self.project / "calibration/Calib.toml").write_text(rtoml.dumps(self.cameras), encoding="utf-8")

    def test_calibration_enforces_documented_1_5_pixel_limit(self):
        for residual, expected in ((1.5, True), (1.5001, False), (1.9, False)):
            with self.subTest(residual=residual):
                (self.project / "logs.txt").write_text(
                    f"Residual (RMS) calibration errors for each camera are respectively [0.3, {residual}] px,\n")
                self.assertEqual(quality.validate_calibration(self.project, self.session, self.window())["ok"], expected)

    def test_sync_enforces_documented_correlation_minimum(self):
        observations = {"session_id": "generated", "reference": "cam01", "fps": 30,
                        "cameras": {camera: {"offset_frames": 0, "start_residual_frames": 0, "end_residual_frames": 0}
                                    for camera in self.session["camera_ids"]},
                        "source_frame_pairs": [{"camera": camera, "synchronized_frame_index": frame,
                                                "source_frame_index": frame}
                                               for camera in self.session["camera_ids"] for frame in (10, 100)]}
        for correlation, expected in ((.85, True), (.849, False), (.6, False)):
            with self.subTest(correlation=correlation):
                (self.project / "logs.txt").write_text(
                    f"Camera cam01 and cam02: 0 frames offset, correlation {correlation}.\n")
                self.assertEqual(quality.validate_sync(self.project, self.session, observations, self.window())["ok"], expected)

    def reconstruction_fixture(self, world_point, distortion):
        from anytree import RenderTree
        from Pose2Sim.skeletons import HALPE_26
        required = ["Hip", "RHip", "RKnee", "RAnkle", "LHip", "LKnee", "LAnkle"]
        ids = {node.name: node.id for _, _, node in RenderTree(HALPE_26) if node.id is not None}
        for camera in self.cameras.values():
            camera["distortions"] = distortion
        self.write_calibration()
        (self.project / "Config.toml").write_text('[pose]\npose_model="Body_with_feet"\n')
        (self.project / "run.json").write_text(json.dumps({"native_triangulation_policy": {
            "interpolation": "none", "fill_large_gaps_with": "nan"}}))
        folder = self.project / "pose-3d"
        folder.mkdir()
        header = ["Frame#", "Time"] + [part for name in required for part in (name, "", "")]
        axes = ["", ""] + [axis + str(index) for index in range(1, len(required) + 1) for axis in "XYZ"]
        lines = ["PathFileType\t4\t(X/Y/Z)\tgenerated.trc", "DataRate\tNumFrames\tNumMarkers\tUnits",
                 f"30\t2\t{len(required)}\tm", "\t".join(header), "\t".join(axes)]
        y_up = [world_point[1], world_point[2], world_point[0]]
        for frame in range(1, 3):
            lines.append("\t".join(map(str, [frame, frame / 30] + y_up * len(required))))
        (folder / "generated.trc").write_text("\n".join(lines) + "\n")
        native_people = {}
        for name, camera in self.cameras.items():
            folder = self.project / "pose-associated" / (name + "_json")
            folder.mkdir(parents=True)
            points, _ = cv2.projectPoints(np.asarray([world_point], dtype=float), np.zeros(3),
                                         np.asarray(camera["translation"], dtype=float),
                                         np.asarray(camera["matrix"], dtype=float), np.asarray(distortion, dtype=float))
            x, y = points.reshape(-1)
            keypoints = [0.] * ((max(ids.values()) + 1) * 3)
            for marker in required:
                keypoints[ids[marker] * 3:ids[marker] * 3 + 3] = [float(x), float(y), .9]
            for frame in range(1, 3):
                (folder / f"{name}_{frame:06d}.json").write_text(json.dumps({"people": [{"pose_keypoints_2d": keypoints}]}))
            native_people[name] = [{"pose_keypoints_2d": keypoints}]

        # TEST_ONLY codec/native contract, with the actual projected keypoints.
        # No decoder/source gate mock: geometry is reached only after provenance.
        from native_evidence_fixture import _generated_clip, native_chain_fixture
        from normalize_capture import ROLES
        source_sha = hashlib.sha256(_generated_clip(3)).hexdigest()
        self.session["captures"] = {role: {"sha256": source_sha} for role in ROLES}
        identity = {"session_id": self.session["session_id"],
                    "config_sha256": hashlib.sha256((self.project / "Config.toml").read_bytes()).hexdigest(),
                    "inputs": {role: source_sha for role in ROLES}}
        record = native_chain_fixture(
            self.project, identity, counts={"cam01": 3, "cam02": 3}, people=native_people)
        record["native_triangulation_policy"] = {"interpolation": "none", "fill_large_gaps_with": "nan"}
        (self.project / "run.json").write_text(json.dumps(record), encoding="utf-8")

    def test_matching_projection_behind_both_cameras_is_rejected(self):
        self.reconstruction_fixture([0., 0., -4.], [0., 0., 0., 0.])
        result = quality.validate_reconstruction(self.project, self.session)
        self.assertFalse(result["ok"])
        self.assertEqual(result["source_coverage"]["common_range"], [1, 3])
        document = json.loads((self.project / result["frame_diagnostics"]["path"]).read_text(encoding="utf-8"))
        cells = [cell for frame in document["frames"] for marker in frame["markers"].values()
                 for cell in marker["cameras"].values()]
        self.assertEqual(len(cells), 28)
        self.assertTrue(all(cell["status"] == "behind_camera" for cell in cells), cells)

    def test_reprojection_uses_actual_nonzero_lens_distortion(self):
        self.reconstruction_fixture([1., .5, 2.], [.4, .1, .01, .01])
        result = quality.validate_reconstruction(self.project, self.session)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["source_coverage"]["common_range"], [1, 3])
        document = json.loads((self.project / result["frame_diagnostics"]["path"]).read_text(encoding="utf-8"))
        cells = [cell for frame in document["frames"] for marker in frame["markers"].values()
                 for cell in marker["cameras"].values()]
        self.assertEqual(len(cells), 28)
        self.assertTrue(all(cell["status"] == "supported" for cell in cells), cells)
        self.assertLess(max(cell["reprojection_px"] for cell in cells), 1e-6)


if __name__ == "__main__":
    unittest.main()

