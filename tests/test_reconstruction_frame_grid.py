"""Generated B14 interval tests; no decoded-video or physical-accuracy proof."""

import builtins
import copy
import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ReconstructionFrameGridTests(unittest.TestCase):
    def setUp(self):
        self.quality = importlib.import_module("pipeline_quality")

    @staticmethod
    def sample(frame, supported=True):
        return {
            "marker": "RKnee",
            "frame": frame,
            "views": 2 if supported else 0,
            "likelihoods": [.9, .9] if supported else [],
            "reprojection_px": 1.0 if supported else None,
            "interpolated": False,
        }

    def assess(self, samples):
        original = copy.deepcopy(samples)
        result = self.quality.assess_reconstruction(samples, ["RKnee"])
        self.assertEqual(samples, original, "Quality assessment must preserve its input observations")
        return result

    def assert_accounting(self, result, *, observed, total, gap, marker="RKnee"):
        summary = result["markers"][marker]
        self.assertEqual(summary["observed"], observed)
        self.assertEqual(summary["total"], total)
        self.assertAlmostEqual(summary["coverage"], observed / total)
        self.assertEqual(summary["longest_gap_frames"], gap)

    def assert_refused(self, result):
        self.assertFalse(result["ok"], "Incomplete or ambiguous interval must not pass reconstruction quality")
        self.assertTrue(result["errors"], "Refusal must retain a useful diagnostic reason")

    def test_sparse_frames_zero_and_1000_cannot_report_uninterrupted_coverage(self):
        result = self.assess([self.sample(0), self.sample(1000)])
        self.assert_refused(result)
        self.assert_accounting(result, observed=2, total=1001, gap=999)

    def test_contiguous_zero_based_observations_keep_existing_quality(self):
        result = self.assess([self.sample(frame) for frame in range(100)])
        self.assertTrue(result["ok"], result["errors"])
        self.assert_accounting(result, observed=100, total=100, gap=0)

    def test_shifted_contiguous_envelope_does_not_invent_leading_frames(self):
        # This envelope says nothing about decoded source frames before index 100.
        result = self.assess([self.sample(frame) for frame in range(100, 200)])
        self.assertTrue(result["ok"], result["errors"])
        self.assert_accounting(result, observed=100, total=100, gap=0)

    def test_absent_and_unsupported_rows_form_one_four_frame_gap(self):
        # 20 and 22 are absent; 21 and 23 exist but have no two-view support.
        samples = [self.sample(frame, frame not in (21, 23))
                   for frame in range(100) if frame not in (20, 22)]
        result = self.assess(samples)
        self.assert_refused(result)
        self.assert_accounting(result, observed=96, total=100, gap=4)

    def test_three_frame_combined_gap_preserves_existing_allowed_threshold(self):
        samples = [self.sample(frame, frame != 21)
                   for frame in range(100) if frame not in (20, 22)]
        result = self.assess(samples)
        self.assertTrue(result["ok"], result["errors"])
        self.assert_accounting(result, observed=97, total=100, gap=3)

    def test_duplicate_marker_frame_is_refused_in_both_input_orders(self):
        for duplicate_first in (False, True):
            with self.subTest(duplicate_first=duplicate_first):
                samples = [self.sample(frame) for frame in range(100)]
                duplicate = self.sample(50, supported=False)
                samples.insert(0 if duplicate_first else len(samples), duplicate)
                result = self.assess(samples)
                self.assert_refused(result)
                self.assertRegex(" ".join(result["errors"]).lower(), "duplicat|ambig")

    def test_huge_sparse_span_uses_arithmetic_or_explicit_bounded_refusal(self):
        last = 10**12

        def bounded_range(*arguments):
            value = builtins.range(*arguments)
            self.assertLessEqual(
                len(value), 10000,
                "Do not enumerate the missing interval to assess two observations",
            )
            return value

        # Guard the common range/list(range) expansion before it allocates.
        # This is a functional guard, not a general memory/performance benchmark.
        with mock.patch.object(self.quality, "range", side_effect=bounded_range, create=True):
            result = self.assess([self.sample(0), self.sample(last)])
        self.assert_refused(result)
        if "RKnee" in result["markers"]:
            self.assert_accounting(result, observed=2, total=last + 1, gap=last - 1)
        else:
            self.assertRegex(" ".join(result["errors"]).lower(), "span|grid|interval|limit|bound|frame")

    def native_fixture(self, frame_indices, *, times=None):
        """Real validator input bytes, generated geometry; no native pipeline run."""
        import cv2
        import numpy as np
        import rtoml
        from anytree import RenderTree
        from Pose2Sim.skeletons import HALPE_26

        temporary = tempfile.TemporaryDirectory(prefix="kinelab-B14-TEST_ONLY-")
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name)
        session = {"session_id": "TEST_ONLY-B14-generated", "camera_ids": ["cam01", "cam02"]}
        required = ["Hip", "RHip", "RKnee", "RAnkle", "LHip", "LKnee", "LAnkle"]
        ids = {node.name: node.id for _, _, node in RenderTree(HALPE_26) if node.id is not None}
        world_points = {
            "Hip": [0., 0., 1.8], "RHip": [-.15, 0., 1.8],
            "RKnee": [-.15, .05, 1.35], "RAnkle": [-.15, 0., .9],
            "LHip": [.15, 0., 1.8], "LKnee": [.15, -.05, 1.35],
            "LAnkle": [.15, 0., .9],
        }
        times = tuple(index / 30 for index in frame_indices) if times is None else tuple(times)
        self.assertEqual(len(times), len(frame_indices))
        cameras = {
            name: {
                "name": name, "size": [1280, 720],
                "matrix": [[1000, 0, 640], [0, 1000, 360], [0, 0, 1]],
                "distortions": [0, 0, 0, 0], "rotation": [0, 0, 0],
                "translation": [index, 0, 2], "fisheye": False,
            }
            for index, name in enumerate(session["camera_ids"])
        }
        calibration = project / "calibration"
        calibration.mkdir()
        (calibration / "Calib.toml").write_text(rtoml.dumps(cameras), encoding="utf-8")
        (project / "Config.toml").write_text('[pose]\npose_model="Body_with_feet"\n', encoding="utf-8")
        (project / "run.json").write_text(json.dumps({"native_triangulation_policy": {
            "interpolation": "none", "fill_large_gaps_with": "nan",
        }}), encoding="utf-8")
        pose3d = project / "pose-3d"
        pose3d.mkdir()
        header = ["Frame#", "Time"] + [part for name in required for part in (name, "", "")]
        axes = ["", ""] + [axis + str(index) for index in range(1, len(required) + 1) for axis in "XYZ"]
        lines = [
            "PathFileType\t4\t(X/Y/Z)\tTEST_ONLY-B14-generated.trc",
            "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames",
            f"30\t30\t{len(frame_indices)}\t{len(required)}\tm\t30\t0\t{max(frame_indices) + 1}",
            "\t".join(header), "\t".join(axes),
        ]
        # Generated TRC header values are not a decoded-source coverage binding.
        # Pose2Sim's z-up to y-up permutation maps world (x,y,z) to (y,z,x).
        coordinates = [str(value) for marker in required
                       for value in (world_points[marker][1], world_points[marker][2], world_points[marker][0])]
        for frame, timestamp in zip(frame_indices, times):
            lines.append("\t".join([str(frame), str(timestamp)] + coordinates))
        (pose3d / "TEST_ONLY-B14-generated.trc").write_text("\n".join(lines) + "\n", encoding="utf-8")
        for name, camera in cameras.items():
            folder = project / "pose-associated" / (name + "_json")
            folder.mkdir(parents=True)
            projected, _ = cv2.projectPoints(
                np.asarray([world_points[marker] for marker in required]), np.zeros(3),
                np.asarray(camera["translation"], dtype=float),
                np.asarray(camera["matrix"], dtype=float), np.zeros(4),
            )
            keypoints = [0.] * ((max(ids.values()) + 1) * 3)
            for marker, (x, y) in zip(required, projected.reshape(-1, 2)):
                keypoints[ids[marker] * 3:ids[marker] * 3 + 3] = [float(x), float(y), .9]
            for timestamp in times:
                pose_index = round(timestamp * 30)
                (folder / f"{name}_{pose_index:06d}.json").write_text(
                    json.dumps({"people": [{"pose_keypoints_2d": keypoints}]}), encoding="utf-8",
                )
        # Geometry-only unit receipt: bind the exact generated association bytes.
        # Decoded provenance remains the explicit validate_fixture seam below.
        run = json.loads((project / "run.json").read_text(encoding="utf-8"))
        run["stages"] = [{
            "name": "personAssociation", "status": "passed",
            "quality": {"ok": True, "TEST_ONLY_geometry_unit": True},
            "artifacts": [
                {"path": path.relative_to(project).as_posix(),
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in sorted((project / "pose-associated").rglob("*.json"))
            ],
        }]
        (project / "run.json").write_text(json.dumps(run), encoding="utf-8")
        return project, session, required

    @staticmethod
    def fixture_hashes(project):
        # Generated input paths only; exclude the validator's quality/diagnostics outputs.
        inputs = [project / "Config.toml", project / "run.json"]
        for directory in ("calibration", "pose-3d", "pose-associated"):
            inputs.extend(path for path in (project / directory).rglob("*") if path.is_file())
        return {path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in inputs}

    def validate_fixture(self, project, session):
        before = self.fixture_hashes(project)
        # Isolated geometry/grid unit seam. This is not decoded-source proof.
        # The new decoded-source suite uses real generated clips without this mock.
        indexes = [int(path.stem.rsplit("_", 1)[1])
                   for path in (project / "pose-associated").rglob("*.json")
                   if path.stem.rsplit("_", 1)[-1].isdigit()]
        coverage = {"schema": "kinelab.decoded-source-coverage.v1",
                    "common_range": [min(indexes), max(indexes) + 1],
                    "physical_source_frame_equality": "UNVERIFIED",
                    "TEST_ONLY_geometry_unit": True}
        with mock.patch("source_coverage.verify_source_coverage", return_value=coverage):
            result = self.quality.validate_reconstruction(project, session)
        self.assertEqual(self.fixture_hashes(project), before, "Generated source fixture bytes must remain immutable")
        return result

    def test_native_generated_sparse_trc_cannot_pass_reconstruction_quality(self):
        project, session, required = self.native_fixture((0, 1000))
        result = self.validate_fixture(project, session)
        self.assert_refused(result)
        for marker in required:
            self.assert_accounting(result, observed=2, total=1001, gap=999, marker=marker)

    def test_native_contiguous_zero_based_trc_and_poses_remain_compatible(self):
        project, session, required = self.native_fixture((0, 1))
        result = self.validate_fixture(project, session)
        self.assertTrue(result["ok"], result["errors"])
        for marker in required:
            self.assert_accounting(result, observed=2, total=2, gap=0, marker=marker)

    def test_native_duplicate_pose_numeric_suffix_is_ambiguous_even_with_equal_bytes(self):
        project, session, _ = self.native_fixture((0, 1))
        folder = project / "pose-associated" / "cam01_json"
        original = folder / "cam01_000001.json"
        alias = folder / "alternate_000001.json"
        alias.write_bytes(original.read_bytes())
        result = self.validate_fixture(project, session)
        self.assert_refused(result)
        self.assertRegex(" ".join(result["errors"]).lower(), "duplicat|ambig")

    def test_native_duplicate_and_out_of_order_trc_ids_remain_rejected(self):
        for indices in ((0, 0), (1, 0)):
            with self.subTest(indices=indices):
                project, session, _ = self.native_fixture(indices, times=(0, 1 / 30))
                result = self.validate_fixture(project, session)
                self.assert_refused(result)
                self.assertRegex(" ".join(result["errors"]), "TRC_INVALID")


if __name__ == "__main__":
    unittest.main()

