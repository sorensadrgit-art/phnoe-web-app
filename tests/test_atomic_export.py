import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import export_motion


class AtomicExportTests(unittest.TestCase):
    def test_failed_serialization_leaves_no_partial_output_and_retry_works(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "motion.json"
            def interrupted(data, stream, **kwargs):
                stream.write('{"partial":'); raise OSError("disk write failed")
            with patch.object(export_motion.json, "dump", side_effect=interrupted), self.assertRaises(OSError):
                export_motion.write_motion(out, {"frames": []})
            self.assertFalse(out.exists())
            self.assertEqual(list(Path(folder).iterdir()), [])
            export_motion.write_motion(out, {"frames": []})
            self.assertEqual(json.loads(out.read_text()), {"frames": []})
            with self.assertRaises(FileExistsError):
                export_motion.write_motion(out, {"frames": [1]})
            self.assertEqual(json.loads(out.read_text()), {"frames": []})


if __name__ == "__main__":
    unittest.main()
