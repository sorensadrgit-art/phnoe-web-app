"""Candidate-only runtime paths; generated temporary roots and fake dependencies."""
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from t6_service import IntegratedService


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "index.html").write_text("synthetic test UI", encoding="utf-8")

    def test_default_storage_uses_candidate_namespace(self):
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"LOCALAPPDATA": str(self.root), "KINELAB_CANDIDATE_DATA_ROOT": ""}))
            for name in ("SessionLibrary", "SessionIndex", "RecordingStore", "ReportBuilder", "BackupManager", "PoseInference"):
                stack.enter_context(patch("t6_service." + name))
            service = IntegratedService()
            self.assertEqual(service.projects_root, self.root / "KineLabPT-Candidate-M1" / "data")
            service.close()
        self.assertFalse((self.root / "KineLabPT").exists())

    def test_explicit_missing_root_bootstraps_without_importing_sessions(self):
        target = self.root / "new" / "data"
        service = IntegratedService(projects_root=target)
        self.addCleanup(service.close)
        self.assertEqual(service.projects_root, target)
        self.assertEqual(service.sessions(), [])

    def test_program_tree_refused_before_library_access(self):
        from t6_service import ROOT
        with ExitStack() as stack:
            library = stack.enter_context(patch("t6_service.SessionLibrary"))
            for name in ("SessionIndex", "RecordingStore", "ReportBuilder", "BackupManager", "PoseInference"):
                stack.enter_context(patch("t6_service." + name))
            with self.assertRaisesRegex(ValueError, "DATA_ROOT"):
                IntegratedService(projects_root=ROOT / "projects")
        library.assert_not_called()

    def test_configured_root_precedence_and_identity(self):
        from runtime_config import resolve_data_root, runtime_identity
        with patch.dict(os.environ, {"KINELAB_CANDIDATE_DATA_ROOT": str(self.root / "configured")}):
            self.assertEqual(resolve_data_root(), self.root / "configured")
            self.assertEqual(resolve_data_root(self.root / "explicit"), self.root / "explicit")
        first = runtime_identity(self.root / "one", installation=self.root / "app")
        self.assertEqual(first, runtime_identity(self.root / "one", installation=self.root / "app"))
        self.assertNotEqual(first, runtime_identity(self.root / "two", installation=self.root / "app"))
        self.assertNotEqual(first, runtime_identity(self.root / "one", installation=self.root / "app2"))

    def test_relative_parent_and_reparse_roots_fail_closed(self):
        from runtime_config import ensure_data_root
        for target in (Path("relative"), self.root / ".." / "escape", Path(self.root.anchor)):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "DATA_ROOT"):
                ensure_data_root(target)
        with patch("runtime_config.is_reparse", return_value=True), self.assertRaisesRegex(ValueError, "DATA_ROOT"):
            ensure_data_root(self.root / "junction")

    def test_owned_server_closes_service_once_without_listening(self):
        from t6_server import make_server
        service = Mock()
        with patch("t6_server.ThreadingHTTPServer.server_bind"), patch("t6_server.ThreadingHTTPServer.server_activate"):
            server = make_server(service, token="a" * 64, dist=self.root, samples=self.root, owns_service=True)
        server.server_close()
        server.server_close()
        service.close.assert_called_once_with()

    def test_startup_lock_serializes_independent_python_processes(self):
        from runtime_config import startup_lock
        directory = self.root / "locks"
        code = "from pathlib import Path; from runtime_config import startup_lock; import sys\ntry:\n with startup_lock(Path(sys.argv[1]), timeout=0.1): pass\nexcept TimeoutError:\n raise SystemExit(23)\n"
        command = [sys.executable, "-X", "utf8", "-B", "-c", code, str(directory)]
        with startup_lock(directory):
            busy = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        free = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(busy.returncode, 23, busy.stderr)
        self.assertEqual(free.returncode, 0, free.stderr)

    def test_authenticated_health_exposes_identity_without_paths(self):
        import json
        from types import SimpleNamespace

        from t6_server import make_server
        from test_http_disconnect import MemorySocket
        service = SimpleNamespace(runtime_id="d" * 64)
        with patch("t6_server.ThreadingHTTPServer", side_effect=lambda address, handler: SimpleNamespace(server_port=address[1], RequestHandlerClass=handler)):
            server = make_server(service, token="a" * 64, dist=self.root, samples=self.root, port=18444)
        request = ("GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1:18444\r\nAuthorization: Bearer " + "a" * 64 + "\r\nConnection: close\r\n\r\n").encode()
        sock = MemorySocket(request)
        server.RequestHandlerClass(sock, ("127.0.0.1", 12345), server)
        response = b"".join(sock.writes)
        self.assertIn(b"200 OK", response)
        payload = json.loads(response.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(payload["runtime_id"], "d" * 64)
        self.assertNotIn(str(self.root), response.decode())
