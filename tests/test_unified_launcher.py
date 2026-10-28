"""T6 desktop launch validation without starting a browser or altering Windows."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launch_kinelab_unified import find_free_port, read_state, write_state, PORTS


class UnifiedLauncherTests(unittest.TestCase):
    def test_keeps_port_range_distinct_from_existing_4173_4174_viewer(self):
        self.assertTrue(all(p>4182 for p in PORTS))
        self.assertEqual(find_free_port([4190,4191],is_busy=lambda p:p==4190),4191)

    def test_does_not_hijack_existing_service_port(self):
        with self.assertRaises(RuntimeError):
            find_free_port([4190,4191],is_busy=lambda p:True)

    def test_state_roundtrip_requires_bounded_127_0_0_1_port_and_random_key(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/"session.json"
            state={"port":4190,"key":"Ab_cdEF0123456789Ab_cdEF0123456789"}
            write_state(f,state)
            self.assertEqual(read_state(f),state)
            self.assertNotIn("http://",f.read_text())
            with patch("launch_kinelab_unified.is_verified_service",return_value=True):
                self.assertTrue(read_state(f)["port"])

    def test_invalid_state_is_ignored_not_used_as_remote_navigation(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/"current.json"
            for malformed in [
                {"port":80,"key":"Ab_cdEF0123456789Ab_cdEF0123456789"},
                {"port":4190,"key":"short"},
                {"port":"https://evil.example","key":"Ab_cdEF0123456789Ab_cdEF0123456789"},
                {"port":4190,"key":"key\ninjectionxxxxxxxxxxxxxxxxx"},
                {"port":4190,"key":"Ab_cdEF0123456789Ab_cdEF0123456789","url":"https://evil"},
            ]:
                file.write_text(__import__("json").dumps(malformed))
                self.assertIsNone(read_state(file))

    def test_missing_state_does_not_open_anything(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(read_state(Path(temp)/"absent.json"))

if __name__=="__main__":
    unittest.main()
