from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("launch_motion_lab", ROOT / "launch_motion_lab.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_existing_kinelab_server_reused(self):
        with patch.object(launcher, "serving_kinelab", return_value=True):
            with patch.object(launcher, "port_in_use") as busy:
                self.assertEqual(launcher.choose_port([4173]), (4173, False))
                busy.assert_not_called()

    def test_busy_other_service_uses_next_port(self):
        with patch.object(launcher, "serving_kinelab", return_value=False):
            with patch.object(launcher, "port_in_use", side_effect=[True, False]):
                self.assertEqual(launcher.choose_port([4173, 4174]), (4174, True))

    def test_all_ports_busy_fails_instead_of_opening_wrong_app(self):
        with patch.object(launcher, "serving_kinelab", return_value=False):
            with patch.object(launcher, "port_in_use", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "available"):
                    launcher.choose_port([4173, 4174])

    def test_launcher_requires_existing_dist_assets(self):
        self.assertTrue((ROOT / "viewer" / "dist" / "index.html").is_file())
        self.assertTrue((ROOT / "viewer" / "dist" / "motion" / "demo.motion.json").is_file())


if __name__ == "__main__":
    unittest.main()
