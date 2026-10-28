"""Frame review must not silently label the wrong decoded frame as an observed cue."""
import unittest
import cv2
import numpy as np

from sync_review_gui import read_exact_frame, FrameReviewError


class FakeVideo:
    def __init__(self, actual: int):
        self.position = 0
        self.actual = actual

    def isOpened(self):
        return True

    def set(self, key, position):
        self.position = position
        return True

    def read(self):
        return True, np.zeros((32, 48, 3), dtype=np.uint8)

    def get(self, key):
        if key == cv2.CAP_PROP_POS_FRAMES:
            return self.actual + 1
        return 0


class FrameReviewTests(unittest.TestCase):
    def test_exact_seek_uses_actual_decoded_position(self):
        image = read_exact_frame(FakeVideo(25), 25)
        self.assertEqual(image.shape, (32, 48, 3))

    def test_wrong_decoded_frame_blocks_operator_mark(self):
        with self.assertRaisesRegex(FrameReviewError, "decoded"):
            read_exact_frame(FakeVideo(24), 25)

    def test_actual_ffmpeg_mp4_seek_exact_frame(self):
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path
        if not shutil.which("ffmpeg"):
            self.skipTest("FFmpeg not available")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "sample.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc2=size=160x120:rate=30:duration=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
            ], check=True, capture_output=True)
            cap = cv2.VideoCapture(str(path))
            try:
                self.assertTrue(cap.isOpened())
                self.assertEqual(read_exact_frame(cap, 0).shape[:2], (120, 160))
                self.assertEqual(read_exact_frame(cap, 30).shape[:2], (120, 160))
                self.assertEqual(read_exact_frame(cap, 59).shape[:2], (120, 160))
            finally:
                cap.release()

    def test_offline_two_video_gui_frame_marking_without_file_writes(self):
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import tkinter as tk
        from sync_review_gui import SyncReviewWindow
        if not shutil.which("ffmpeg"):
            self.skipTest("FFmpeg not available")
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            files = {}
            for cam in ("cam01", "cam02"):
                path = folder / (cam + ".mp4")
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
                ], check=True, capture_output=True)
                files[cam] = {"path": path, "frames": 60, "timestamps": [i / 30 for i in range(60)]}
            tkroot = tk.Tk()
            tkroot.withdraw()
            dialog = None
            try:
                with patch("sync_review_gui.normalized_videos", return_value=({"session_id": "synthetic-fixture"}, files)), \
                     patch("sync_review_gui.suggested_reference", return_value="cam01"):
                    dialog = SyncReviewWindow(tkroot, folder)
                dialog.withdraw()
                self.assertEqual(dialog.frame_verified, {"cam01": 0, "cam02": 0})
                # A withdrawn Tk window does not reliably dispatch Scale commands
                # without mainloop; exercise the exact decoder directly here.
                dialog._show("cam01", 13)
                self.assertEqual(dialog.frame_verified["cam01"], 13)
                dialog._mark("cam01", "start")
                dialog._show("cam01", 52)
                self.assertEqual(dialog.frame_verified["cam01"], 52)
                dialog._mark("cam01", "end")
                self.assertEqual(dialog.marks["cam01"], {"start": 13, "end": 52})
                self.assertFalse((folder / "sync-observations.json").exists())
            finally:
                if dialog is not None and dialog.winfo_exists():
                    dialog.close()
                tkroot.destroy()

    def test_negative_frame_index_rejected(self):
        with self.assertRaises(FrameReviewError):
            read_exact_frame(FakeVideo(0), -1)


if __name__ == "__main__":
    unittest.main()
