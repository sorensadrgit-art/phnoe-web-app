"""TEST_ONLY generated HTTP/filesystem failures; candidate, not yet installed/run."""
from __future__ import annotations

import http.client
import io
import json
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from session_library import SessionError, SessionLibrary, _copy_verified
from t6_server import make_server
from t6_service import IntegratedService


class B19ErrorBoundaryTests(unittest.TestCase):
    token = "generated-b19-http-token-000000000000000000000000"
    private = ("B19_PRIVATE_SYNTHETIC token=generated-private-token "
               "body=generated-private-body session=generated-private-session.zip "
               r"C:\Users\GeneratedPrivateUser\generated-private-recording.mp4")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="b19-generated-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dist = self.root / "ui"
        self.dist.mkdir()
        (self.dist / "index.html").write_text("TEST_ONLY", encoding="utf-8")
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.library = SessionLibrary(self.projects)

    def private_error(self, kind):
        error = kind(self.private)
        error.add_note("B19_PRIVATE_SYNTHETIC_NOTE")
        error.__cause__ = ValueError("B19_PRIVATE_SYNTHETIC_CAUSE")
        return error

    @contextmanager
    def server(self, service=None, *, owned=False):
        service = service or SimpleNamespace(sessions=Mock(return_value=[]), close=Mock())
        server = make_server(service, token=self.token, dist=self.dist,
                             samples=self.dist, port=0, owns_service=owned)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive(), "Owned generated HTTP fixture must stop")

    def request(self, server, *, method="GET", path="/api/v1/sessions", auth=True):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
        headers = {"Host": f"127.0.0.1:{server.server_port}", "Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer " + self.token
        try:
            connection.request(method, path, b"{}" if method == "POST" else None, headers)
            response = connection.getresponse()
            return response.status, response.read().decode("utf-8")
        except http.client.RemoteDisconnected:
            # Turn the known current missing-response defect into a business assertion.
            return None, ""
        finally:
            connection.close()

    def redacted(self, value):
        for forbidden in ("B19_PRIVATE_SYNTHETIC", "generated-private-token",
                          "generated-private-body", "generated-private-session.zip",
                          "GeneratedPrivateUser", "generated-private-recording.mp4",
                          str(self.root), "Traceback (most recent call last)"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, value)

    def diagnostic(self, records, event, exception_type, module="t6_server"):
        self.assertTrue(records)
        self.assertIn("event=" + event, records[0].getMessage())
        self.assertIn("exception_type=" + exception_type, records[0].getMessage())
        for record in records:
            self.redacted(str(record.__dict__))
            self.assertIsNone(record.exc_info)
            self.assertIsNone(record.stack_info)
            self.assertEqual(record.pathname, module + ".py")

    def test_01_actual_http_get_unexpected_is_generic_500(self):
        service = SimpleNamespace(sessions=Mock(side_effect=self.private_error(RuntimeError)))
        with self.server(service) as server, patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertLogs("t6_server", level="ERROR") as log:
                status, body = self.request(server)
                self.assertEqual(status, 500)
            self.assertEqual(json.loads(body)["error"],
                             "Unexpected local API error; inspect the local application log")
            self.redacted(body + stderr.getvalue())
            self.diagnostic(log.records, "unexpected_local_get_error", "RuntimeError")

    def test_02_actual_http_get_oserror_is_generic_409(self):
        service = SimpleNamespace(sessions=Mock(side_effect=self.private_error(PermissionError)))
        with self.server(service) as server, self.assertLogs("t6_server", level="WARNING") as log:
            status, body = self.request(server)
            self.assertEqual(status, 409)
            self.redacted(body)
        self.assertIn("LOCAL_STORAGE_ERROR:", body)
        self.diagnostic(log.records, "local_get_storage_error", "PermissionError")

    def test_03_actual_http_post_oserror_is_generic_409(self):
        service = SimpleNamespace(pose_inference=SimpleNamespace(
            infer=Mock(side_effect=self.private_error(OSError))))
        with self.server(service) as server, self.assertLogs("t6_server", level="WARNING") as log:
            status, body = self.request(server, method="POST", path="/api/v1/inference/frame")
            self.assertEqual(status, 409)
            self.redacted(body)
        self.assertIn("LOCAL_STORAGE_ERROR:", body)
        self.diagnostic(log.records, "local_post_storage_error", "OSError")

    def test_04_business_validation_remains_detailed_409(self):
        service = SimpleNamespace(sessions=Mock(side_effect=ValueError("SESSION_LOCKED: generated refusal")))
        with self.server(service) as server:
            status, body = self.request(server)
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"], "SESSION_LOCKED: generated refusal")

    def test_05_sqlite_failure_remains_503_without_ack(self):
        service = SimpleNamespace(sessions=Mock(side_effect=sqlite3.OperationalError(self.private)))
        with self.server(service) as server:
            status, body = self.request(server)
        self.assertEqual(status, 503)
        self.assertIn("no saved acknowledgment", body)
        self.redacted(body)

    def test_06_pre_api_static_failure_is_bounded_for_both_server_ownerships(self):
        for owned in (False, True):
            with self.subTest(owned=owned), self.server(owned=owned) as server:
                with (patch.object(server.RequestHandlerClass, "_safe_static",
                                   side_effect=self.private_error(RuntimeError)),
                      patch("sys.stderr", new_callable=io.StringIO) as stderr,
                      self.assertLogs("t6_server", level="ERROR") as log):
                    status, body = self.request(server, path="/")
                    self.assertEqual(status, 500)
                    self.assertEqual(json.loads(body)["error"],
                                     "Unexpected local request error; inspect the local application log")
                    self.redacted(body + stderr.getvalue())
                self.diagnostic(log.records, "unexpected_local_get_error", "RuntimeError")

    def test_07_auth_and_unknown_route_behavior_is_preserved(self):
        service = SimpleNamespace(sessions=Mock(return_value=[]))
        with self.server(service) as server:
            self.assertEqual(self.request(server, auth=False)[0], 401)
            service.sessions.assert_not_called()
            self.assertEqual(self.request(server, path="/api/v1/generated-unknown")[0], 404)

    def test_08_registration_readiness_oserror_is_fixed_and_preserves_files(self):
        project = self.projects / "draft"
        project.mkdir()
        config = project / "Config.toml"
        config.write_bytes(b"# TEST_ONLY generated draft\n")
        before = config.read_bytes()
        with patch.object(self.library, "_registration_readiness_locked",
                          side_effect=self.private_error(OSError)):
            result = self.library.registration_readiness("draft")
        self.assertFalse(result["ready_to_register"])
        self.assertEqual(result["issues"], ["READINESS_UNAVAILABLE: local storage error"])
        self.redacted(json.dumps(result["issues"]))
        self.assertEqual(config.read_bytes(), before)

    def test_09_existing_copy_destination_is_fixed_and_unchanged(self):
        source = self.root / "source.mp4"
        destination = self.root / "generated-private-session.zip"
        source.write_bytes(b"TEST_ONLY source")
        destination.write_bytes(b"TEST_ONLY immutable prior destination")
        with self.assertRaises(FileExistsError) as caught:
            _copy_verified(source, destination)
        self.assertEqual(str(caught.exception), "Destination exists; original preserved")
        self.assertEqual(destination.read_bytes(), b"TEST_ONLY immutable prior destination")
        self.assertEqual(source.read_bytes(), b"TEST_ONLY source")

    def test_10_setup_failure_omits_child_tail_and_preserves_partial_folder(self):
        marker = self.projects / "partial" / "partial.txt"
        def failed_setup(*_args, **_kwargs):
            marker.parent.mkdir()
            marker.write_bytes(b"TEST_ONLY partial data must remain")
            return subprocess.CompletedProcess([], 7, self.private, self.private)
        with (patch("session_library.subprocess.run", side_effect=failed_setup),
              self.assertRaises(SessionError) as caught):
            self.library.create_session("partial")
        self.assertEqual(str(caught.exception),
                         "SESSION_CREATE_FAILED: setup exited with code 7; partial folder preserved")
        self.redacted(str(caught.exception))
        self.assertEqual(marker.read_bytes(), b"TEST_ONLY partial data must remain")


    def test_11_library_oserror_wrappers_are_fixed_and_preserve_originals(self):
        project = self.projects / "draft"
        project.mkdir()
        (project / "Config.toml").write_bytes(b"# TEST_ONLY\n")
        original = project / "generated-original.mp4"
        original.write_bytes(b"TEST_ONLY immutable original")
        operations = (
            ("register_session", ("draft",), "SESSION_REGISTER_FAILED", "library_register_storage_error"),
            ("stage_take", ("draft", "cam02_board", original), "TAKE_STAGE_REFUSED", "library_stage_storage_error"),
            ("accept_take", ("draft", "cam02_board", original), "TAKE_ACCEPT_REFUSED", "library_accept_storage_error"),
        )
        for method, args, prefix, event in operations:
            with self.subTest(method=method):
                before = {p.relative_to(project).as_posix(): p.read_bytes()
                          for p in project.rglob("*") if p.is_file()}
                with (patch.object(self.library, "_require_editable", return_value=project),
                      patch("session_library.takes.acceptance_lease", side_effect=self.private_error(OSError)),
                      self.assertLogs("session_library", level="WARNING") as log,
                      self.assertRaises(SessionError) as caught):
                    getattr(self.library, method)(*args)
                self.assertEqual(str(caught.exception), prefix + ": local storage error; source files preserved")
                self.redacted(str(caught.exception))
                self.diagnostic(log.records, event, "OSError", module="session_library")
                after = {p.relative_to(project).as_posix(): p.read_bytes()
                         for p in project.rglob("*") if p.is_file()}
                self.assertEqual(after, before)

    def test_12_camera_status_oserror_is_fixed_and_partial_recording_survives(self):
        project = self.projects / "draft"
        project.mkdir()
        (project / "Config.toml").write_bytes(b"# TEST_ONLY\n")
        partial = project / "generated.part.mp4"
        partial.write_bytes(b"TEST_ONLY unverified partial")
        service = IntegratedService(projects_root=self.projects)
        self.addCleanup(service.close)
        process = SimpleNamespace(poll=Mock(return_value=0), stdin=Mock())
        service.webcam = {"session": "draft", "role": "cam02_board", "process": process}
        with (patch("t6_service.finalize_recording", side_effect=self.private_error(OSError)),
              self.assertLogs("t6_service", level="WARNING") as log):
            result = service.camera_status("draft")
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["message"],
                         "CAPTURE_FINALIZE_FAILED: local storage error; unverified recording preserved")
        self.redacted(json.dumps(result))
        self.diagnostic(log.records, "capture_status_storage_error", "OSError", module="t6_service")
        self.assertEqual(partial.read_bytes(), b"TEST_ONLY unverified partial")
        self.assertIsNone(service.webcam)
        self.assertEqual(service.webcam_latest["draft"], result)
        process.stdin.close.assert_called_once()

    def test_13_copy_destination_race_is_fixed_and_preserves_both_files(self):
        source = self.root / "source.mp4"
        destination = self.root / "generated-private-session.zip"
        source_bytes = b"TEST_ONLY immutable source"
        destination_bytes = b"TEST_ONLY prior destination created by competing writer"
        source.write_bytes(source_bytes)
        self.assertFalse(destination.exists())

        def competing_writer(_staged, target):
            self.assertEqual(Path(target), destination)
            with destination.open("xb") as stream:
                stream.write(destination_bytes)
            raise self.private_error(FileExistsError)

        with (patch("session_library.os.link", side_effect=competing_writer) as link,
              self.assertRaises(FileExistsError) as caught):
            _copy_verified(source, destination)
        link.assert_called_once()
        self.assertEqual(str(caught.exception), "Destination exists; original preserved")
        self.redacted(str(caught.exception))
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertEqual(destination.read_bytes(), destination_bytes)
        self.assertEqual(list(self.root.glob("*.partial")), [], "Owned staged copy must be retired")

    def test_14_extended_backup_conflict_prefix_remains_redacted_over_http(self):
        from backup_manager import BackupConflictError

        error = self.private_error(BackupConflictError)
        error.args = (
            "RESTORE_OVERWRITE_UNAVAILABLE: existing sessions cannot be replaced; " + self.private,
        )
        service = SimpleNamespace(pose_inference=SimpleNamespace(infer=Mock(side_effect=error)))
        with self.server(service) as server, patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertLogs("t6_server", level="WARNING") as log:
                status, body = self.request(server, method="POST", path="/api/v1/inference/frame")
            self.assertEqual(status, 409)
            self.assertEqual(json.loads(body)["error"],
                             "LOCAL_STORAGE_ERROR: local file operation failed; inspect the local application log")
            self.redacted(body + stderr.getvalue())
            self.diagnostic(log.records, "local_post_storage_error", "OtherException")


    def test_15_post_header_static_runtime_failure_never_sends_second_response(self):
        payload = b"TEST_ONLY complete generated body"
        error = self.private_error(RuntimeError)

        def fail_after_response(handler, *args, **kwargs):
            handler._header(200, "application/octet-stream", len(payload))
            handler._write_response(payload)
            raise error

        for owned in (False, True):
            with self.subTest(owned=owned), self.server(owned=owned) as server:
                with (patch.object(server.RequestHandlerClass, "_file", new=fail_after_response),
                      patch("sys.stderr", new_callable=io.StringIO) as stderr,
                      self.assertLogs("t6_server", level="ERROR") as log):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
                    try:
                        connection.request("GET", "/", headers={"Host": f"127.0.0.1:{server.server_port}"})
                        with connection.sock.makefile("rb") as stream:
                            wire = stream.read(4096)
                    finally:
                        connection.close()
                self.assertIn(b" 200 ", wire.splitlines()[0])
                self.assertEqual(wire.count(b"HTTP/"), 1)
                self.assertTrue(wire.endswith(payload))
                self.assertNotIn(b"Unexpected local request error", wire)
                self.redacted(wire.decode("utf-8") + stderr.getvalue())
                self.diagnostic(log.records, "unexpected_local_get_error", "RuntimeError")

    def test_16_static_response_disconnected_never_sends_second_response(self):
        from t6_server import _ResponseDisconnected

        payload = b"TEST_ONLY generated peer-disconnect control"

        def disconnect_after_response(handler, *args, **kwargs):
            handler._header(200, "application/octet-stream", len(payload))
            handler._write_response(payload)
            raise _ResponseDisconnected()

        for owned in (False, True):
            with self.subTest(owned=owned), self.server(owned=owned) as server:
                with (patch.object(server.RequestHandlerClass, "_file", new=disconnect_after_response),
                      patch("sys.stderr", new_callable=io.StringIO) as stderr,
                      patch("t6_server.log_local_failure") as diagnostic):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
                    try:
                        connection.request("GET", "/", headers={"Host": f"127.0.0.1:{server.server_port}"})
                        with connection.sock.makefile("rb") as stream:
                            wire = stream.read(4096)
                    finally:
                        connection.close()
                self.assertIn(b" 200 ", wire.splitlines()[0])
                self.assertEqual(wire.count(b"HTTP/"), 1)
                self.assertTrue(wire.endswith(payload))
                self.assertNotIn(b"Unexpected local request error", wire)
                self.redacted(wire.decode("utf-8") + stderr.getvalue())
                diagnostic.assert_not_called()

    def test_17_post_header_known_static_failures_never_send_second_response(self):
        payload = b"TEST_ONLY complete generated body"
        for owned in (False, True):
            for error_kind in (OSError, ValueError, FileNotFoundError):
                error = self.private_error(error_kind)

                def fail_after_response(handler, *args, _error=error, **kwargs):
                    handler._header(200, "application/octet-stream", len(payload))
                    handler._write_response(payload)
                    raise _error

                with self.subTest(owned=owned, kind=error_kind.__name__), self.server(owned=owned) as server:
                    with (patch.object(server.RequestHandlerClass, "_file", new=fail_after_response),
                          patch("sys.stderr", new_callable=io.StringIO) as stderr,
                          self.assertLogs("t6_server", level="ERROR") as log):
                        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
                        try:
                            connection.request("GET", "/", headers={"Host": f"127.0.0.1:{server.server_port}"})
                            with connection.sock.makefile("rb") as stream:
                                wire = stream.read(4096)
                        finally:
                            connection.close()
                    self.assertIn(b" 200 ", wire.splitlines()[0])
                    self.assertEqual(wire.count(b"HTTP/"), 1)
                    self.assertTrue(wire.endswith(payload))
                    self.assertNotIn(b"Unexpected local request error", wire)
                    self.redacted(wire.decode("utf-8") + stderr.getvalue())
                    self.diagnostic(log.records, "unexpected_local_get_error", error_kind.__name__)


if __name__ == "__main__":
    unittest.main()
