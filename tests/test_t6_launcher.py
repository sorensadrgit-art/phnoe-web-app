"""T6 launcher reuses only authenticated KineLab local server, never another app."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from t6_launcher import choose_available_port, read_state, verified_running


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.file=Path(self.temp.name)/"instance.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_wrong_runtime_identity_never_reuses_or_probes_instance(self):
        candidate={"port":4184,"token":"a"*64,"schema":"kinelab.t6.instance.v2", "runtime_id":"b"*64}
        with patch("t6_launcher.get_health") as health:
            self.assertFalse(verified_running(candidate, expected_runtime_id="c"*64))
        health.assert_not_called()

    def test_free_port_uses_only_allowed_loopback_port(self):
        with patch("t6_launcher.port_free", side_effect=lambda n:n==4188):
            self.assertEqual(choose_available_port(range(4184,4191)),4188)
        with patch("t6_launcher.port_free", return_value=False), self.assertRaisesRegex(RuntimeError,"port"):
            choose_available_port(range(4184,4187))

    def test_invalid_state_does_not_expose_token_or_reuse(self):
        self.assertIsNone(read_state(self.file))
        self.file.write_text('{"token":"wrong","port":"4184"}')
        self.assertIsNone(read_state(self.file))
        self.file.write_text(json.dumps({"port":4184,"token":"a"*64,"schema":"kinelab.t6.instance.v2","runtime_id":"b"*64}))
        self.assertEqual(read_state(self.file)["port"],4184)

    def test_only_matching_bearer_health_reuses_server(self):
        candidate={"port":4184,"token":"a"*64,"schema":"kinelab.t6.instance.v2","runtime_id":"b"*64}
        with patch("t6_launcher.get_health", return_value={"app":"unified_t6","local_only":True,"name":"KineLab PT","runtime_id":"b"*64}):
            self.assertTrue(verified_running(candidate, expected_runtime_id="b"*64))
        with patch("t6_launcher.get_health", return_value={"app":"not_kinelab","local_only":True,"name":"KineLab PT","runtime_id":"b"*64}):
            self.assertFalse(verified_running(candidate, expected_runtime_id="b"*64))
        with patch("t6_launcher.get_health", side_effect=TimeoutError):
            self.assertFalse(verified_running(candidate, expected_runtime_id="b"*64))

    def test_stale_instance_archival(self):
        # Stale state where server is dead is cleanly handled
        stale_data = {"port": 4184, "token": "b" * 64, "schema": "kinelab.t6.instance.v2", "runtime_id":"b"*64}
        self.file.write_text(json.dumps(stale_data))
        state = read_state(self.file)
        self.assertIsNotNone(state)
        with patch("t6_launcher.get_health", side_effect=OSError("Connection refused")):
            self.assertFalse(verified_running(state, expected_runtime_id="b"*64))

    def test_ensure_running_reuses_existing_verified_instance(self):
        from runtime_config import runtime_identity
        from t6_launcher import ensure_running
        root=Path(self.temp.name)/"data"
        local=Path(self.temp.name)/"runtime"
        state={"port":4184,"token":"c"*64,"schema":"kinelab.t6.instance.v2","runtime_id":runtime_identity(root)}
        with patch("t6_launcher.LOCAL",local), patch("t6_launcher.STATE",local/"state.json"), patch("t6_launcher.read_state",return_value=state), patch("t6_launcher.verified_running",return_value=True):
            url,fresh=ensure_running(data_root=root)
        self.assertFalse(fresh)
        self.assertEqual(url,f"http://127.0.0.1:4184/#access={'c'*64}")

    def test_mismatched_existing_state_is_preserved_without_starting(self):
        from t6_launcher import ensure_running
        local=Path(self.temp.name)/"runtime"
        local.mkdir()
        state_path=local/"state.json"
        state={"port":4184,"token":"a"*64,"schema":"kinelab.t6.instance.v2","runtime_id":"b"*64}
        payload=json.dumps(state)
        state_path.write_text(payload,encoding="utf-8")
        with patch("t6_launcher.LOCAL",local), patch("t6_launcher.STATE",state_path), patch("t6_launcher.choose_available_port") as choose, patch("t6_launcher.get_health") as health, self.assertRaisesRegex(RuntimeError,"different candidate"):
            ensure_running(data_root=Path(self.temp.name)/"data")
        choose.assert_not_called()
        health.assert_not_called()
        self.assertEqual(state_path.read_text(encoding="utf-8"),payload)

    def test_owned_state_cleanup_waits_for_start_transaction(self):
        from runtime_config import startup_lock
        from t6_launcher import _remove_owned_state
        local=Path(self.temp.name)/"runtime"
        local.mkdir()
        state_path=local/"state.json"
        old={"port":4184,"token":"a"*64,"schema":"kinelab.t6.instance.v2","runtime_id":"b"*64}
        new={**old,"token":"c"*64}
        state_path.write_text(json.dumps(old),encoding="utf-8")
        done=threading.Event()
        def cleanup():
            _remove_owned_state(old)
            done.set()
        with patch("t6_launcher.LOCAL",local), patch("t6_launcher.STATE",state_path):
            with startup_lock(local):
                worker=threading.Thread(target=cleanup)
                worker.start()
                premature=done.wait(0.15)
                state_path.write_text(json.dumps(new),encoding="utf-8")
            worker.join(timeout=5)
        self.assertFalse(premature,"Cleanup raced the startup transaction")
        self.assertFalse(worker.is_alive())
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")),new)


if __name__=="__main__":
    unittest.main()
