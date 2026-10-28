import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("capture_under_test", ROOT / "normalize_capture.py")
        self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        self.assertTrue(callable(getattr(self.module, "normalize_session", None)), "normalize_session implementation missing")
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name); (self.project / "Config.toml").write_text("[project]\nframe_rate=30\n")
        captures = {}
        for role in self.module.ROLES:
            source = self.project / "raw" / (role + ".mp4"); source.parent.mkdir(exist_ok=True); source.write_bytes(role.encode())
            captures[role] = {"path": source.relative_to(self.project).as_posix(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        self.session = {"schema": "kinelab.session.v1", "session_id": "test", "kind": "real", "subject_count": 1,
                        "camera_ids": ["cam01", "cam02"], "created_at": "2026-10-26T10:00:00-04:00", "captures": captures}
        self.video = {"width": 1280, "height": 720, "rotation": 0, "fps": "30/1", "timestamps": [0, 1/30, 2/30], "frame_count": 3, "duration": 0.1}

    def test_missing_sixth_input_causes_no_conversions(self):
        (self.project / self.session["captures"]["cam02_trial"]["path"]).unlink()
        with patch.object(self.module, "inspect_video", return_value=self.video), patch.object(self.module, "_convert") as convert:
            with self.assertRaisesRegex(ValueError, "INPUT_MISSING"):
                self.module.normalize_session(self.session, self.project)
            convert.assert_not_called()
        self.assertFalse((self.project / "videos").exists())

    def test_nonmonotonic_pts_and_geometry_mismatch_rejected(self):
        bad = dict(self.video, timestamps=[0, 0, 0.03])
        with patch.object(self.module, "inspect_video", return_value=bad):
            with self.assertRaisesRegex(ValueError, "TIMING"):
                self.module.validate_sources(self.session, self.project)
        videos = [self.video] * 5 + [dict(self.video, width=1920)]
        with patch.object(self.module, "inspect_video", side_effect=videos):
            with self.assertRaisesRegex(ValueError, "GEOMETRY"):
                self.module.validate_sources(self.session, self.project)

    def test_conversion_failure_preserves_all_existing_outputs(self):
        destinations = []
        for relative in self.module.ROLES.values():
            path = self.project / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"old"); destinations.append(path)
        with patch.object(self.module, "inspect_video", return_value=self.video), patch.object(self.module, "_convert", side_effect=RuntimeError("encoder failed")):
            with self.assertRaisesRegex(RuntimeError, "encoder failed"):
                self.module.normalize_session(self.session, self.project, overwrite=True)
        self.assertTrue(all(path.read_bytes() == b"old" for path in destinations))

    def test_existing_destination_rejected_before_conversion(self):
        path = self.project / next(iter(self.module.ROLES.values())); path.parent.mkdir(parents=True); path.write_bytes(b"old")
        with patch.object(self.module, "inspect_video", return_value=self.video), patch.object(self.module, "_convert") as convert:
            with self.assertRaisesRegex(ValueError, "OUTPUT_EXISTS"):
                self.module.normalize_session(self.session, self.project)
            convert.assert_not_called()

    def test_real_ffmpeg_pts_reset_and_frame_mapping(self):
        import cv2
        import numpy as np
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("FFmpeg/FFprobe unavailable")
        base = self.project / "base.mp4"
        writer = cv2.VideoWriter(str(base), cv2.VideoWriter_fourcc(*"mp4v"), 25, (160, 90))
        self.assertTrue(writer.isOpened())
        for value in range(10): writer.write(np.full((90, 160, 3), value * 20, dtype=np.uint8))
        writer.release()
        shifted = self.project / "shifted.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(base), "-c", "copy", "-output_ts_offset", "2", str(shifted)], check=True)
        for role, entry in self.session["captures"].items():
            path = self.project / entry["path"]; shutil.copy2(shifted, path)
            entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.session["kind"] = "demo"
        with patch.object(self.module, "_check_board", return_value={"fixture": "timing-only synthetic video; board validation excluded"}):
            report = self.module.normalize_session(self.session, self.project)
        self.assertTrue(report["ok"])
        record = json.loads((self.project / "normalization.json").read_text())
        role = "cam01_trial"; item = record["outputs"][role]
        self.assertAlmostEqual(item["source"]["timestamps"][0], 2.0, places=3)
        self.assertAlmostEqual(item["timestamps"][0], 0.0, places=3)
        self.assertTrue(all(abs(b - a - 1/30) <= .001 for a, b in zip(item["timestamps"], item["timestamps"][1:])))
        def means(path):
            capture = cv2.VideoCapture(str(path)); values = []
            while True:
                ok, frame = capture.read()
                if not ok: break
                values.append(float(frame.mean()))
            capture.release(); return values
        source_values = means(self.project / self.session["captures"][role]["path"])
        output_values = means(self.project / self.module.ROLES[role])
        measured = [min(range(len(source_values)), key=lambda index: abs(source_values[index] - value)) for value in output_values]
        self.assertEqual(item["output_to_source_frame"], measured)
        for entry in self.session["captures"].values():
            self.assertEqual(hashlib.sha256((self.project / entry["path"]).read_bytes()).hexdigest(), entry["sha256"])


if __name__ == "__main__":
    unittest.main()
