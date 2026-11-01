"""Every advertised local entry point either serves the supported contract or refuses safely.

Uses generated data roots, synthetic frontend files and a loopback server on an ephemeral port.
No browser, camera, native GUI or existing user data is touched.
"""
from __future__ import annotations

import contextlib
import http.client
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import t6_service
from t6_server import make_server
from t6_service import IntegratedService

TOKEN = "e" * 64


class SupportedDesktopEntryPoint(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kinelab-entrypoint-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data_root = self.root / "generated-data-root"
        dist = self.root / "synthetic-frontend"
        dist.mkdir()
        (dist / "index.html").write_text("<title>SYNTHETIC ENTRYPOINT FIXTURE</title>", encoding="utf-8")
        self.service = IntegratedService(projects_root=self.data_root, pose_models=self.root / "absent-models")
        self.addCleanup(self.service.close)
        self.server = make_server(self.service, token=TOKEN, dist=dist, port=0)
        self.port = self.server.server_port
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        def stop():
            self.server.shutdown()
            self.server.server_close()
            thread.join(timeout=5)
        self.addCleanup(stop)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=6)
        payload = json.dumps(body).encode() if body is not None else None
        merged = {"Host": f"127.0.0.1:{self.port}", **({"Content-Type": "application/json"} if body is not None else {}),
                  **(headers or {})}
        connection.request(method, path, payload, merged)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, data

    def auth(self):
        return {"Authorization": "Bearer " + TOKEN, "Origin": f"http://127.0.0.1:{self.port}"}

    def test_server_binds_loopback_with_ephemeral_port(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertNotIn(self.port, (0, 4184))

    def test_v1_api_requires_bearer_and_rejects_legacy_contract(self):
        self.assertEqual(self.request("GET", "/api/v1/sessions")[0], 401)
        self.assertEqual(self.request("GET", "/api/v1/sessions", headers={"Authorization": "Bearer " + "x" * 64})[0], 401)
        for legacy in ("/api/sessions", "/api/health"):
            status, _ = self.request("GET", legacy, headers={"X-KineLab-Key": TOKEN})
            self.assertNotEqual(status, 200, legacy)
        status, body = self.request("GET", "/api/v1/sessions", headers=self.auth())
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["sessions"], [])

    def test_selected_session_lives_only_in_generated_data_root(self):
        self.service.create_session("entrypoint-fixture")
        status, body = self.request("GET", "/api/v1/sessions", headers=self.auth())
        self.assertEqual(status, 200, body)
        self.assertEqual([item["id"] for item in json.loads(body)["sessions"]], ["entrypoint-fixture"])
        self.assertTrue((self.data_root / "entrypoint-fixture").is_dir())
        self.assertFalse((t6_service.ROOT / "projects" / "entrypoint-fixture").exists())

    def test_sync_review_tool_receives_the_service_data_root(self):
        self.service.create_session("sync-fixture")
        install = self.root / "install"
        (install / ".venv/Scripts").mkdir(parents=True)
        (install / ".venv/Scripts/pythonw.exe").write_bytes(b"synthetic stand-in, never executed")
        with patch.object(t6_service, "ROOT", install), patch("sync_evidence.normalized_videos"), \
                patch("t6_service.subprocess.Popen") as process:
            self.service.open_native("sync-fixture", "sync", confirm=True)
        arguments = process.call_args.args[0]
        self.assertIn("--data-root", arguments)
        self.assertEqual(Path(arguments[arguments.index("--data-root") + 1]), self.service.projects_root)


class SyncReviewEntryPoint(unittest.TestCase):
    def run_main(self, *arguments):
        import launch_sync_review
        error = io.StringIO()
        with patch.object(sys, "argv", ["launch_sync_review.py", *arguments]), \
                contextlib.redirect_stderr(error), patch("tkinter.Tk") as window:
            try:
                code = launch_sync_review.main()
            except SystemExit as exit_:
                code = exit_.code
        window.assert_not_called()
        return code, error.getvalue()

    def test_requires_explicit_data_root(self):
        code, error = self.run_main("--session-id", "absent", "--check")
        self.assertEqual(code, 2)
        self.assertIn("--data-root", error)

    def test_rejects_installation_projects_directory(self):
        import launch_sync_review
        code, error = self.run_main("--session-id", "absent", "--check",
                                    "--data-root", str(launch_sync_review.ROOT / "projects"))
        self.assertEqual(code, 2)
        self.assertIn("DATA_ROOT_UNSAFE", error)

    def test_linked_data_root_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="kinelab-sync-link-") as directory:
            real = Path(directory) / "real"
            real.mkdir()
            link = Path(directory) / "link"
            if os.name == "nt":
                result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(real)],
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            else:
                link.symlink_to(real, target_is_directory=True)
            code, error = self.run_main("--session-id", "absent", "--check", "--data-root", str(link))
            self.assertEqual(code, 2)
            self.assertIn("DATA_ROOT_UNSAFE", error)

    def test_missing_session_in_generated_root_reports_repair_guidance(self):
        with tempfile.TemporaryDirectory(prefix="kinelab-sync-entry-") as directory:
            root = Path(directory) / "data"
            root.mkdir()
            code, error = self.run_main("--session-id", "absent", "--check", "--data-root", str(root))
            self.assertEqual(code, 2)
            self.assertIn("SYNC_NOT_READY", error)


class RetiredEntryPoints(unittest.TestCase):
    RETIRED = ("launch_kinelab_unified", "launch_motion_lab", "unified_service", "kinelab_hub")

    def test_retired_entry_points_start_nothing_and_redirect(self):
        for name in self.RETIRED:
            with self.subTest(entrypoint=name):
                module = importlib.import_module(name)
                error = io.StringIO()
                with patch("subprocess.Popen", side_effect=AssertionError("process started")), \
                        patch("webbrowser.open", side_effect=AssertionError("browser opened")), \
                        patch("socket.socket.bind", side_effect=AssertionError("socket bound")), \
                        patch("tkinter.Tk", side_effect=AssertionError("window opened")), \
                        patch.object(sys, "argv", [name + ".py"]), contextlib.redirect_stderr(error):
                    self.assertEqual(module.main(), 2)
                text = error.getvalue()
                self.assertIn("RETIRED_ENTRYPOINT=" + name + ".py", text)
                self.assertIn("t6_launcher.py --data-root", text)
                self.assertIn("/api/v1", text)
                self.assertIn("build:cloud", text)


if __name__ == "__main__":
    unittest.main()
