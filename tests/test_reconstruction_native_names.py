"""TEST_ONLY native pose-name binding; no inference, decoded media, or physical proof."""

import importlib
import json
import unittest

grid = importlib.import_module("test_reconstruction_frame_grid")


class ReconstructionNativeNameTests(unittest.TestCase):
    native_fixture = grid.ReconstructionFrameGridTests.native_fixture
    fixture_hashes = staticmethod(grid.ReconstructionFrameGridTests.fixture_hashes)
    validate_fixture = grid.ReconstructionFrameGridTests.validate_fixture

    def setUp(self):
        self.quality = importlib.import_module("pipeline_quality")

    def test_B14_NAME_00_foreign_camera_prefix_cannot_replace_native_pose_files(self):
        for prefix in ("cam02", "intrinsics", "TEST_ONLY-unrelated"):
            with self.subTest(prefix=prefix):
                project, session, _ = self.native_fixture((0, 1))
                folder = project / "pose-associated" / "cam01_json"
                for path in tuple(folder.glob("*.json")):
                    path.rename(folder / path.name.replace("cam01_", prefix + "_", 1))
                result = self.validate_fixture(project, session)
                self.assertFalse(result["ok"], "Equal pose bytes and numeric suffix do not bind a camera")
                self.assertIn("non-native pose filename", " ".join(result["errors"]))

    def test_B14_NAME_01_only_exact_native_padding_and_prefix_are_admitted(self):
        for filename in ("cam01_extra_000000.json", "cam01_0.json", "cam01_0000000.json"):
            with self.subTest(filename=filename):
                project, session, _ = self.native_fixture((0, 1))
                folder = project / "pose-associated" / "cam01_json"
                (folder / "cam01_000000.json").rename(folder / filename)
                result = self.validate_fixture(project, session)
                self.assertFalse(result["ok"], "Only the actual native frame filename is admissible")
                self.assertIn("non-native pose filename", " ".join(result["errors"]))

    def test_B14_NAME_02_unrecognized_json_is_refused_rather_than_ignored(self):
        project, session, _ = self.native_fixture((0, 1))
        folder = project / "pose-associated" / "cam01_json"
        (folder / "TEST_ONLY-unbound.json").write_bytes((folder / "cam01_000000.json").read_bytes())
        result = self.validate_fixture(project, session)
        self.assertFalse(result["ok"], "Unexpected pose JSON must not silently escape the binding")
        self.assertIn("non-native pose filename", " ".join(result["errors"]))

    def test_B14_NAME_03_native_positive_retains_unverified_decoded_source_disclosure(self):
        # Geometry-only positive retains its disclosure; it is no decoder proof.
        project, session, _ = self.native_fixture((0, 1))
        result = self.validate_fixture(project, session)
        self.assertTrue(result["ok"], result["errors"])
        document = json.loads((project / result["frame_diagnostics"]["path"]).read_text(encoding="utf-8"))
        self.assertIn("decoded source video frame UNVERIFIED", document["frame_index_basis"])
        self.assertEqual(document["clinical_validation"], "UNVERIFIED")
        self.assertEqual(document["physical_accuracy"], "not validated")
        for media in (None, b"TEST_ONLY generated noncodec bytes; not a video"):
            with self.subTest(media="absent" if media is None else "noncodec"):
                project, session, _ = self.native_fixture((0, 1))
                if media is not None:
                    (project / "videos").mkdir()
                    for camera in ("cam01", "cam02"):
                        (project / "videos" / (camera + ".mp4")).write_bytes(media)
                result = self.quality.validate_reconstruction(project, session)
                self.assertFalse(result["ok"], "v4 requires bound independently decoded source media")
                if media is not None:
                    for camera in ("cam01", "cam02"):
                        self.assertEqual((project / "videos" / (camera + ".mp4")).read_bytes(), media)

    def test_B14_NAME_04_native_indices_cross_six_digit_width(self):
        # Pure filename grammar; do not generate or pretend to decode a million frames.
        from source_coverage import native_pose_index
        for camera in ("cam01", "cam02"):
            self.assertEqual([native_pose_index(camera, camera + suffix) for suffix in
                              ("_999999.json", "_1000000.json")], [999999, 1000000])

    def test_B14_NAME_05_high_indices_reject_noncanonical_extra_padding(self):
        from source_coverage import native_pose_index
        for index, filename in ((999999, "cam01_0999999.json"),
                                (1000000, "cam01_01000000.json")):
            with (self.subTest(index=index, filename=filename),
                  self.assertRaisesRegex(ValueError, "pose|padding")):
                native_pose_index("cam01", filename)


if __name__ == "__main__":
    unittest.main()

