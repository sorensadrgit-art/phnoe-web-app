"""Exercise HTTP disconnects with synthetic requests and an in-memory socket."""
import errno
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from t6_server import make_server


class MemorySocket:
    def __init__(self, request, *, fail_at=None, error=None):
        self.request = request
        self.fail_at = fail_at
        self.error = error
        self.writes = []
        self.attempts = 0

    def makefile(self, _mode, _buffering):
        return io.BytesIO(self.request)

    def sendall(self, data):
        self.attempts += 1
        if self.fail_at is not None and self.attempts >= self.fail_at:
            raise self.error
        self.writes.append(bytes(data))


class HTTPDisconnectTests(unittest.TestCase):
    token = "synthetic-disconnect-test-token-00000000000"
    port = 18371  # In-memory server metadata only; no port is opened.

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "index.html").write_text("synthetic test", encoding="utf-8")
        self.infer = Mock(return_value={"synthetic_test": True})
        service = SimpleNamespace(pose_inference=SimpleNamespace(infer=self.infer))
        with patch("t6_server.ThreadingHTTPServer", side_effect=lambda address, handler:
                   SimpleNamespace(server_port=address[1], RequestHandlerClass=handler)):
            self.server = make_server(service, token=self.token, dist=self.root,
                                      samples=self.root, port=self.port)

    def request(self, *, method="POST", path="/api/v1/inference/frame",
                auth=True, body=b"{}", fail_at=None, error=None):
        headers = [f"{method} {path} HTTP/1.1", f"Host: 127.0.0.1:{self.port}",
                   "Content-Type: application/json", f"Content-Length: {len(body)}"]
        if auth:
            headers.append("Authorization: Bearer " + self.token)
        request = ("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body
        sock = MemorySocket(request, fail_at=fail_at, error=error)
        self.server.RequestHandlerClass(sock, ("127.0.0.1", 1), self.server)
        return sock

    def response(self, sock):
        headers, body = b"".join(sock.writes).split(b"\r\n\r\n", 1)
        return int(headers.split(b" ", 2)[1]), json.loads(body)

    def test_peer_disconnect_during_headers_or_body_stops_without_retry(self):
        for kind in (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            for fail_at in (1, 2):
                with self.subTest(kind=kind.__name__, write=fail_at):
                    sock = self.request(fail_at=fail_at, error=kind("synthetic peer disconnect"))
                    self.assertEqual(sock.attempts, fail_at, "must not retry an HTTP error response")

    def test_disconnect_during_static_and_unauthorized_responses_is_quiet(self):
        for request in ({"method": "GET", "path": "/"}, {"auth": False}):
            with self.subTest(request=request):
                sock = self.request(**request, fail_at=1,
                                    error=ConnectionAbortedError("synthetic peer disconnect"))
                self.assertEqual(sock.attempts, 1)
        self.infer.assert_not_called()

    def test_success_and_auth_statuses_are_preserved(self):
        status, body = self.response(self.request())
        self.assertEqual((status, body), (200, {"synthetic_test": True}))
        self.infer.reset_mock()
        status, body = self.response(self.request(auth=False))
        self.assertEqual(status, 401)
        self.assertFalse(body["ok"])
        self.infer.assert_not_called()

    def test_invalid_response_and_service_errors_are_not_suppressed(self):
        for error in (ValueError("synthetic invalid response"),
                      OSError(errno.EACCES, "synthetic access denied"),
                      ConnectionResetError("service error, not an HTTP write")):
            with self.subTest(error=type(error).__name__):
                self.infer.side_effect = error
                status, body = self.response(self.request())
                self.assertEqual(status, 409)
                self.assertFalse(body["ok"])
        self.infer.side_effect = None
        self.infer.return_value = {"invalid": float("nan")}
        status, body = self.response(self.request())
        self.assertEqual(status, 409)
        self.assertFalse(body["ok"])

    def test_unexpected_service_error_still_logs_and_returns_500(self):
        self.infer.side_effect = RuntimeError("synthetic unexpected error")
        with patch("sys.stderr", new_callable=io.StringIO) as log:
            status, body = self.response(self.request())
        self.assertEqual(status, 500)
        self.assertFalse(body["ok"])
        self.assertIn("RuntimeError", log.getvalue())

    def test_unrelated_response_io_error_is_not_suppressed(self):
        with self.assertRaisesRegex(OSError, "synthetic I/O error"):
            self.request(fail_at=1, error=OSError(errno.EIO, "synthetic I/O error"))


if __name__ == "__main__":
    unittest.main()
