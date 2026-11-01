"""B14 extent/grid regression tests; generated TEST_ONLY inputs, no decoded-video or physical-accuracy proof."""

import importlib
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# Module import only: binding the TestCase class here would make unittest rerun the existing suite.
grid = importlib.import_module("test_reconstruction_frame_grid")


class ReconstructionExtentTests(unittest.TestCase):
    sample = staticmethod(grid.ReconstructionFrameGridTests.sample)
    assess = grid.ReconstructionFrameGridTests.assess
    assert_accounting = grid.ReconstructionFrameGridTests.assert_accounting
    assert_refused = grid.ReconstructionFrameGridTests.assert_refused
    native_fixture = grid.ReconstructionFrameGridTests.native_fixture
    fixture_hashes = staticmethod(grid.ReconstructionFrameGridTests.fixture_hashes)
    validate_fixture = grid.ReconstructionFrameGridTests.validate_fixture

    def setUp(self):
        self.quality = importlib.import_module("pipeline_quality")

    @staticmethod
    def pose_folder(project, camera):
        return project / "pose-associated" / (camera + "_json")

    def write_pose_indexes(self, project, indexes):
        """Replace each camera folder with copies of one generated pose at exactly these indexes."""
        for camera in ("cam01", "cam02"):
            folder = self.pose_folder(project, camera)
            template = min(folder.glob("*.json")).read_bytes()
            for path in folder.glob("*.json"):
                path.unlink()
            for index in indexes:
                (folder / f"{camera}_{index:06d}.json").write_bytes(template)

    def validate_without_raising(self, project, session):
        try:
            return self.validate_fixture(project, session)
        except Exception as error:  # noqa: BLE001 - the contract is a saved refusal, never an exception
            self.fail(f"validate_reconstruction must return a refusal, not raise {type(error).__name__}: {error}")

    def errors_text(self, result):
        return " ".join(result["errors"]).lower()

    def test_B14_EXT_00_positive_control_contiguous_hundred_frames_pass(self):
        project, session, required = self.native_fixture(tuple(range(100)))
        result = self.validate_fixture(project, session)
        self.assertTrue(result["ok"], result["errors"])
        for marker in required:
            self.assert_accounting(result, observed=100, total=100, gap=0, marker=marker)

    def test_B14_EXT_01_trc_rows_400_450_inside_pose_extent_0_999_refused(self):
        project, session, required = self.native_fixture(tuple(range(400, 451)))
        self.write_pose_indexes(project, range(1000))
        result = self.validate_without_raising(project, session)
        self.assertFalse(result["ok"], "TRC rows 400..450 must not pass against associated poses 0..999")
        self.assertTrue(result["errors"])
        markers = result.get("markers", {})
        if all(marker in markers for marker in required):
            for marker in required:
                self.assertEqual(markers[marker]["total"], 1000,
                                 "Missing leading/trailing pose-associated frames must be counted")
        else:
            self.assertRegex(self.errors_text(result), "extent|coverage|missing|range")

    def test_B14_EXT_02_unequal_per_camera_index_range_refused(self):
        project, session, _ = self.native_fixture(tuple(range(100)))
        folder = self.pose_folder(project, "cam02")
        shutil.copyfile(folder / "cam02_000099.json", folder / "cam02_000100.json")
        (folder / "cam02_000099.json").unlink()
        result = self.validate_without_raising(project, session)
        self.assertFalse(result["ok"], "cam01 0..99 and cam02 0..98,100 have different min/max and must refuse")
        self.assertRegex(self.errors_text(result), "extent|align|range|camera")

    def test_B14_EXT_03_off_grid_trc_time_at_30fps_refused(self):
        project, session, _ = self.native_fixture((0, 1), times=(0, 0.02))
        result = self.validate_without_raising(project, session)
        self.assertFalse(result["ok"], "t=0.02 s is 0.6 frames at 30 fps and must not round onto index 1")
        self.assertRegex(self.errors_text(result), "grid|time|frame|trc_invalid")

    def test_B14_EXT_04_consistent_trc_datarate_25_refused_against_sync_30(self):
        count = 10
        project, session, _ = self.native_fixture(tuple(range(count)), times=tuple(i / 25 for i in range(count)))
        trc = next((project / "pose-3d").glob("*.trc"))
        lines = trc.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines[2].startswith("30\t30\t"), "fixture header layout changed")
        lines[2] = f"25\t25\t{count}\t7\tm\t25\t0\t{count}"
        trc.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Poses at round(t * 25) so the only defect is the rate disagreeing with validate_sync's 30 fps.
        self.write_pose_indexes(project, range(count))
        result = self.validate_without_raising(project, session)
        self.assertFalse(result["ok"], "TRC DataRate 25 must not pass when synchronization requires 30 fps")
        self.assertRegex(self.errors_text(result), "rate|fps|30|sync|grid")

    def test_B14_EXT_05_invalid_required_marker_frame_returns_explicit_refusal(self):
        invalid_rows = {
            "negative": dict(self.sample(0), frame=-1),
            "bool": dict(self.sample(0), frame=True),
            "float": dict(self.sample(0), frame=5.0),
            "string": dict(self.sample(0), frame="5"),
            "missing": {key: value for key, value in self.sample(0).items() if key != "frame"},
        }
        for label, row in invalid_rows.items():
            with self.subTest(frame=label):
                samples = [self.sample(frame) for frame in range(100)] + [row]
                try:
                    result = self.assess(samples)
                except Exception as error:  # noqa: BLE001
                    self.fail(f"invalid frame ({label}) must be refused, not raise {type(error).__name__}")
                self.assertFalse(result["ok"], f"invalid frame ({label}) must not pass beside valid rows")
                self.assertTrue(result["errors"], "refusal must name the unbound frame value")

    def test_B14_EXT_06_malformed_pose_json_saves_quality_false(self):
        for label, payload in (("top_level_list", "[]"), ("person_not_object", '{"people": [5]}')):
            with self.subTest(payload=label):
                project, session, _ = self.native_fixture((0, 1))
                (self.pose_folder(project, "cam01") / "cam01_000001.json").write_text(payload, encoding="utf-8")
                result = self.validate_without_raising(project, session)
                self.assertFalse(result["ok"])
                self.assertTrue(result["errors"])
                saved = [path for path in project.rglob("quality.json")]
                self.assertEqual(len(saved), 1, "a rejected quality.json report must be saved")
                self.assertIs(json.loads(saved[0].read_text(encoding="utf-8"))["ok"], False)

    def test_B14_EXT_07_thresholds_come_from_reconstruction_criteria(self):
        # 97/100 coverage with a 3-frame gap passes the current published criteria (existing test).
        samples = [self.sample(frame, frame != 21) for frame in range(100) if frame not in (20, 22)]
        self.assertTrue(self.assess(samples)["ok"])
        for key, stricter in (("coverage_min", 0.99), ("longest_gap_frames_max", 2)):
            with self.subTest(criterion=key), mock.patch.dict(self.quality.RECONSTRUCTION_CRITERIA, {key: stricter}):
                result = self.assess(samples)
                self.assertFalse(result["ok"], f"assess_reconstruction must read {key} from RECONSTRUCTION_CRITERIA")


if __name__ == "__main__":
    unittest.main()
