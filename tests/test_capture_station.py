"""Behavioral tests for the optional local-first, explicit-recording capture station."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capture_station import (
    ROLE_GUIDE, RAW_ROLES, check_readiness, clip_path, ffmpeg_command,
    prepare_recording, save_board_measurement, probe_clip
)


class CaptureStationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / "raw").mkdir()
        (self.project / "Config.toml").write_text("[project]\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_six_roles_and_separate_cameras(self):
        self.assertEqual(len(RAW_ROLES), 6)
        self.assertEqual(sum(r.startswith("cam01_") for r in RAW_ROLES), 3)
        self.assertEqual(sum(r.startswith("cam02_") for r in RAW_ROLES), 3)
        self.assertEqual(set(ROLE_GUIDE), set(RAW_ROLES))

    def test_paths_are_safe_and_refuse_unknown_camera(self):
        self.assertEqual(clip_path(self.project, "cam02_trial"),
                         self.project / "raw" / "cam02_trial.mp4")
        for invalid in ("../../escape", "cam01_trial", "cam02_hack", ""):
            if invalid == "cam01_trial":
                with self.assertRaisesRegex(ValueError, "webcam"):
                    prepare_recording(self.project, invalid, 10)
            else:
                with self.assertRaises(ValueError):
                    clip_path(self.project, invalid) if invalid != "cam01_trial" else None

    def test_recording_never_overwrites_originals_or_partial(self):
        dest = clip_path(self.project, "cam02_trial")
        dest.write_bytes(b"original")
        with self.assertRaisesRegex(FileExistsError, "exists"):
            prepare_recording(self.project, "cam02_trial", 30)
        dest.unlink()
        (self.project / "raw" / "cam02_trial.part.mp4").write_bytes(b"partial")
        with self.assertRaises(FileExistsError):
            prepare_recording(self.project, "cam02_trial", 30)

    def test_rejects_wrong_duration(self):
        for duration in (0, -2, 1000, 3.5, True):
            with self.assertRaises(ValueError):
                prepare_recording(self.project, "cam02_board", duration)

    def test_ffmpeg_only_uses_local_webcam_and_expected_geometry(self):
        target = self.project / "raw" / "cam02_trial.part.mp4"
        command = ffmpeg_command(target, 36, device="Integrated Webcam")
        joined = " ".join(command)
        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("video=Integrated Webcam", command)
        self.assertIn("1280x720", command)
        self.assertIn("30", command)
        self.assertIn("-an", command)
        self.assertIn("-f mp4", joined)
        self.assertEqual(command[-1], str(target))
        self.assertNotIn("-y", command)

    def test_check_readiness_reports_missing_without_registering(self):
        report = check_readiness(self.project, inspect_existing=False)
        self.assertFalse(report["ready_to_register"])
        self.assertEqual(len(report["missing"]), 6)
        self.assertFalse((self.project / "session.json").exists())
        self.assertFalse((self.project / "capture-readiness.json").exists())

    def test_check_readiness_rejects_invalid_or_mismatched_source(self):
        for role in RAW_ROLES:
            clip_path(self.project, role).write_bytes(b"fixture")
        meta = {"width": 1280, "height": 720, "rotation": 0,
                "fps": "30/1", "duration": 16.0, "frame_count": 480}
        def fake_probe(path):
            data = dict(meta)
            if path.name == "cam01_board.mp4":
                data["width"] = 1920
            return data
        with patch("capture_station.probe_clip", side_effect=fake_probe):
            report = check_readiness(self.project, inspect_existing=True)
        self.assertFalse(report["ready_to_register"])
        self.assertTrue(any("cam01" in e for e in report["issues"]))

    def test_phone_import_refuses_wrong_extensions_and_preserves_existing(self):
        from capture_station import import_phone_mp4
        source = self.project / "phone.mov"
        source.write_bytes(b"example")
        with self.assertRaisesRegex(ValueError, "MP4"):
            import_phone_mp4(self.project, "cam01_trial", source)
        source = self.project / "phone.mp4"
        source.write_bytes(b"example")
        target = clip_path(self.project, "cam01_trial")
        target.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            import_phone_mp4(self.project, "cam01_trial", source)
        self.assertEqual(target.read_bytes(), b"existing")

    def test_phone_import_copies_bytes_without_changing_source(self):
        from capture_station import import_phone_mp4
        source = self.project / "source.mp4"
        source.write_bytes(b"real-footage-placeholder")
        with patch("capture_station.probe_clip", return_value={
            "width": 1280, "height": 720, "rotation": 0,
            "fps": "30/1", "duration": 12, "frame_count": 360
        }):
            target = import_phone_mp4(self.project, "cam01_trial", source)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertEqual(target.name, "cam01_trial.mp4")
        self.assertFalse((self.project / "raw" / "cam01_trial.copying.mp4").exists())

    def test_completed_webcam_temp_only_publishes_if_valid(self):
        from capture_station import finalize_recording
        temp = self.project / "raw" / "cam02_trial.part.mp4"
        temp.write_bytes(b"webcam-bytes")
        with patch("capture_station.probe_clip", return_value={
            "width": 1280, "height": 720, "rotation": 0,
            "fps": "30/1", "duration": 10
        }):
            target = finalize_recording(self.project, "cam02_trial")
        self.assertEqual(target.read_bytes(), b"webcam-bytes")
        self.assertFalse(temp.exists())

    def test_real_mp4_import_preserves_actual_demo_bytes(self):
        from capture_station import import_phone_mp4
        from session_contract import sha256_file
        source = Path(__file__).resolve().parents[1] / "projects" / "demo-local" / "videos" / "cam01.mp4"
        if not source.is_file():
            self.skipTest("Existing demo source is unavailable")
        target = import_phone_mp4(self.project, "cam01_board", source)
        self.assertEqual(sha256_file(target), sha256_file(source))
        self.assertGreater(target.stat().st_size, 100)

    def test_ffmpeg_encoded_temp_can_be_finalized_without_camera(self):
        import subprocess
        from capture_station import finalize_recording, probe_clip
        path = self.project / "raw" / "cam02_board.part.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30:d=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-f", "mp4",
                        str(path)], capture_output=True, check=True)
        target = finalize_recording(self.project, "cam02_board")
        self.assertEqual((probe_clip(target)["width"], probe_clip(target)["height"]), (1280, 720))
        self.assertFalse(path.exists())

    def test_board_measurements_require_operator_entry_not_assumption(self):
        with self.assertRaises(ValueError):
            save_board_measurement(self.project, None, "soren")
        with self.assertRaises(ValueError):
            save_board_measurement(self.project, 0.0, "soren")
        with self.assertRaises(ValueError):
            save_board_measurement(self.project, 20.0, "  ")
        result = save_board_measurement(self.project, 19.9, "operator")
        self.assertEqual(result["measured_square_mm"], 19.9)
        self.assertEqual(result["source"], "operator_measured_not_independently_verified")
        self.assertTrue((self.project / "board-measurement.json").is_file())
        with self.assertRaises(FileExistsError):
            save_board_measurement(self.project, 20.0, "operator")


if __name__ == "__main__":
    unittest.main()
