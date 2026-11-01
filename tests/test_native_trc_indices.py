import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from export_motion import parse_trc


class NativeTrcIndexTests(unittest.TestCase):
    def test_native_zero_based_frame_and_original_start_are_valid(self):
        data = ("PathFileType\t4\t(X/Y/Z)\tnative.trc\n"
                "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames\n"
                "30\t30\t2\t1\tm\t30\t0\t2\n"
                "Frame#\tTime\tHip\t\t\n\t\tX1\tY1\tZ1\n"
                "0\t0\t1\t2\t3\n1\t0.03333333333333333\t1\t2\t3\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.trc"; path.write_text(data)
            names, frames, fps = parse_trc(path)
        self.assertEqual(names, ["Hip"])
        self.assertEqual(frames[0]["t"], 0)
        self.assertEqual(fps, 30)
