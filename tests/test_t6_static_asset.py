"""Real local HTTP static routing using generated files, without a handler patch."""
from __future__ import annotations

import http.client
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from t6_server import make_server


class StaticAssetTests(unittest.TestCase):
    token = "generated-static-asset-test-token-00000000000"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kinelab-static-asset-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dist = self.root / "frontend"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "motion").mkdir()
        (self.dist / "index.html").write_text(
            '<title>GENERATED FIXTURE</title><link rel="icon" href="/favicon.svg">', encoding="utf-8",
        )
        self.favicon = (Path(__file__).resolve().parents[1] / "viewer/public/favicon.svg").read_bytes()
        (self.dist / "favicon.svg").write_bytes(self.favicon)
        (self.dist / "favicon.ico").write_bytes(b"GENERATED LEGACY ICON")
        (self.dist / "assets/bundle.js").write_bytes(b"window.GENERATED_FIXTURE=true;")
        (self.dist / "motion/demo.motion.json").write_bytes(b'{"synthetic_fixture":true}')
        (self.dist / "private.txt").write_bytes(b"GENERATED ROOT FILE MUST NOT BE PUBLIC")
        (self.dist / "extra.svg").write_bytes(b"GENERATED NONALLOWLISTED SVG")
        self.outside = self.root / "outside"
        self.outside.mkdir()
        (self.outside / "secret.txt").write_bytes(b"GENERATED OUTSIDE FILE MUST NOT BE PUBLIC")
        service = SimpleNamespace(sessions=list)
        self.server = make_server(
            service, token=self.token, dist=self.dist, samples=self.root / "absent-samples", port=0,
        )
        self.port = self.server.server_port
        thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True,
        )
        thread.start()

        def stop():
            self.server.shutdown()
            self.server.server_close()
            thread.join(timeout=3)

        self.addCleanup(stop)

    def request(self, path, *, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request("GET", path, headers={
                "Host": f"127.0.0.1:{self.port}", **(headers or {}),
            })
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_bundled_favicon_svg_is_served_with_correct_bytes_and_mime(self):
        for path in ("/favicon.svg", "/favicon.svg?v=generated-fixture"):
            with self.subTest(path=path):
                status, body, headers = self.request(path)
                self.assertEqual(status, 200, body)
                self.assertEqual(body, self.favicon)
                self.assertEqual(headers["Content-Type"], "image/svg+xml")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(int(headers["Content-Length"]), len(self.favicon))

    def test_existing_exact_routes_and_normal_assets_stay_available(self):
        for path, expected in (
            ("/", b"GENERATED FIXTURE"),
            ("/assets/bundle.js", b"window.GENERATED_FIXTURE=true;"),
            ("/motion/demo.motion.json", b'{"synthetic_fixture":true}'),
            ("/favicon.ico", b"GENERATED LEGACY ICON"),
        ):
            with self.subTest(path=path):
                status, body, _ = self.request(path)
                self.assertEqual(status, 200, body)
                self.assertIn(expected, body)

    def test_arbitrary_root_files_and_nearby_svg_routes_are_refused(self):
        for path in ("/private.txt", "/extra.svg", "/nested/favicon.svg", "/favicon.svg/extra"):
            with self.subTest(path=path):
                status, body, _ = self.request(path)
                self.assertEqual(status, 404, body)
                self.assertNotIn(b"GENERATED ROOT FILE", body)

    def test_encoded_and_literal_traversal_cannot_reach_bundle_root_or_outside(self):
        for path in (
            "/assets/%2e%2e/private.txt",
            "/assets/%2E%2E/private.txt",
            "/assets/../private.txt",
            "/assets/%2e%2e/%2e%2e/outside/secret.txt",
        ):
            with self.subTest(path=path):
                status, body, _ = self.request(path)
                self.assertEqual(status, 404, body)
                self.assertNotIn(b"MUST NOT BE PUBLIC", body)

    def test_filesystem_link_cannot_escape_bundle(self):
        link = self.dist / "assets" / "outside-link"
        if os.name == "nt":
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(self.outside)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            link.symlink_to(self.outside, target_is_directory=True)
        status, body, _ = self.request("/assets/outside-link/secret.txt")
        self.assertEqual(status, 404, body)
        self.assertNotIn(b"MUST NOT BE PUBLIC", body)

    def test_loopback_host_and_api_token_gates_stay_enforced(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(self.request("/favicon.svg", headers={"Host": "foreign.invalid"})[0], 400)
        self.assertEqual(self.request("/api/v1/sessions")[0], 401)
        self.assertEqual(self.request("/api/v1/sessions", headers={
            "Authorization": "Bearer invalid-generated-token",
        })[0], 401)
        authorization = {"Authorization": "Bearer " + self.token}
        self.assertEqual(self.request("/api/v1/sessions", headers=authorization)[0], 200)
        self.assertEqual(self.request("/api/v1/sessions", headers={
            **authorization, "Origin": "https://foreign.invalid",
        })[0], 403)


if __name__ == "__main__":
    unittest.main()
