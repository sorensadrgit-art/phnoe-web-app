"""T6 launcher reuses only authenticated KineLab local server, never another app."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from t6_launcher import choose_available_port, verified_running, read_state


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.file=Path(self.temp.name)/"instance.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_free_port_uses_only_allowed_loopback_port(self):
        with patch("t6_launcher.port_free", side_effect=lambda n:n==4188):
            self.assertEqual(choose_available_port(range(4184,4191)),4188)
        with patch("t6_launcher.port_free", return_value=False):
            with self.assertRaisesRegex(RuntimeError,"port"):
                choose_available_port(range(4184,4187))

    def test_invalid_state_does_not_expose_token_or_reuse(self):
        self.assertIsNone(read_state(self.file))
        self.file.write_text('{"token":"wrong","port":"4184"}')
        self.assertIsNone(read_state(self.file))
        self.file.write_text(json.dumps({"port":4184,"token":"a"*64,"schema":"kinelab.t6.instance.v1"}))
        self.assertEqual(read_state(self.file)["port"],4184)

    def test_only_matching_bearer_health_reuses_server(self):
        candidate={"port":4184,"token":"a"*64,"schema":"kinelab.t6.instance.v1"}
        with patch("t6_launcher.get_health", return_value={"app":"unified_t6","local_only":True,"name":"KineLab PT"}):
            self.assertTrue(verified_running(candidate))
        with patch("t6_launcher.get_health", return_value={"app":"not_kinelab","local_only":True,"name":"KineLab PT"}):
            self.assertFalse(verified_running(candidate))
        with patch("t6_launcher.get_health", side_effect=TimeoutError):
            self.assertFalse(verified_running(candidate))

    def test_stale_instance_archival(self):
        # Stale state where server is dead is cleanly handled
        stale_data = {"port": 4184, "token": "b" * 64, "schema": "kinelab.t6.instance.v1"}
        self.file.write_text(json.dumps(stale_data))
        state = read_state(self.file)
        self.assertIsNotNone(state)
        with patch("t6_launcher.get_health", side_effect=OSError("Connection refused")):
            self.assertFalse(verified_running(state))

    def test_ensure_running_reuses_existing_verified_instance(self):
        with patch("t6_launcher.read_state", return_value={"port": 4184, "token": "c"*64, "schema": "kinelab.t6.instance.v1"}):
            with patch("t6_launcher.verified_running", return_value=True):
                from t6_launcher import ensure_running
                url, fresh = ensure_running()
                self.assertFalse(fresh)
                self.assertEqual(url, f"http://127.0.0.1:4184/#access={'c'*64}")


if __name__=="__main__":
    unittest.main()
