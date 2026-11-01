"""TEST_ONLY detached main/real loopback shutdown; no subprocess, browser or devices."""
from __future__ import annotations

import http.client
import io
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import t6_launcher
import t6_server
from runtime_config import runtime_identity, startup_lock


class DetachedStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="TEST_ONLY-detached-state-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.local = self.root / "TEST_ONLY-runtime"
        self.local.mkdir()
        self.state = self.local / "t6-instance.json"
        self.data = self.root / "TEST_ONLY-data"
        self.dist = self.root / "TEST_ONLY-dist"
        self.dist.mkdir()
        (self.dist / "index.html").write_text("<title>TEST_ONLY</title>", encoding="utf-8")
        self.samples = self.root / "TEST_ONLY-samples"
        self.samples.mkdir()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.doc = {"schema": "kinelab.t6.instance.v2", "port": self.port,
                    "token": "a" * 64, "runtime_id": runtime_identity(self.data),
                    "created_by": "local_single_icon_launcher"}
        self.state.write_text(json.dumps(self.doc), encoding="utf-8")
        with startup_lock(self.local):
            pass  # Explicit existing anchor: tests never count its creation as deletion.
        self.anchor = self.local / "t6-startup.lock"
        self.anchor_identity = self.identity(self.anchor)

    @staticmethod
    def identity(path):
        info = path.stat()
        return info.st_dev, info.st_ino

    def request(self, method, path, body=None, *, authorized=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        headers = {"Host": f"127.0.0.1:{self.port}",
                   "Origin": f"http://127.0.0.1:{self.port}"}
        if authorized:
            headers["Authorization"] = "Bearer " + self.doc["token"]
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            return response.status, response.read(65536)
        finally:
            connection.close()

    @contextmanager
    def running(self, *, state_path=None, close_error=None, retirement_error=None):
        state_path = self.state if state_path is None else state_path
        real_factory = t6_server.make_server
        holder = {}
        errors = []
        local_sys = SimpleNamespace(stdout=io.StringIO(), stderr=io.StringIO(),
                                    exc_info=sys.exc_info)

        def factory(service, **kwargs):
            server = real_factory(service, **kwargs, dist=self.dist, samples=self.samples)
            holder["server"] = server
            holder["real_close"] = server.server_close
            holder["service"] = service
            holder["closed"] = threading.Event()
            def observed_close():
                try:
                    holder["real_close"]()
                    if close_error is not None:
                        raise close_error
                finally:
                    holder["closed"].set()
            server.server_close = observed_close
            return server

        def invoke():
            try:
                t6_server.main()
            except BaseException as error:  # noqa: BLE001 - retain cancellation and primary cleanup failures for caller
                errors.append(error)

        with ExitStack() as stack:
            stack.enter_context(patch.object(t6_launcher, "LOCAL", self.local))
            stack.enter_context(patch.object(t6_launcher, "STATE", self.state))
            stack.enter_context(patch.object(t6_server, "sys", local_sys))
            stack.enter_context(patch("t6_server.argparse.ArgumentParser.parse_args",
                                      return_value=SimpleNamespace(port=self.port,
                                      state=state_path, data_root=self.data)))
            stack.enter_context(patch.object(t6_server, "make_server", side_effect=factory))
            if retirement_error is not None:
                stack.enter_context(patch.object(t6_launcher, "_remove_owned_state",
                                                 side_effect=retirement_error))
            thread = threading.Thread(target=invoke, name="TEST_ONLY-detached-main")
            thread.start()
            try:
                deadline = time.monotonic() + 8
                while True:
                    if errors:
                        raise RuntimeError("TEST_ONLY detached-main setup failed") from errors[0]
                    try:
                        status, body = self.request("GET", "/api/v1/health")
                        if status == 200:
                            self.assertEqual(json.loads(body)["runtime_id"], self.doc["runtime_id"])
                            break
                    except OSError:
                        pass
                    if time.monotonic() >= deadline:
                        self.fail("TEST_ONLY loopback server did not become ready")
                    time.sleep(0.02)
                yield thread, errors, holder
            finally:
                if thread.is_alive() and "server" in holder:
                    holder["server"].shutdown()
                thread.join(timeout=10)
                if "real_close" in holder:
                    holder["real_close"]()  # Test emergency cleanup after observed result.
                if local_sys.stdout is not local_sys.stderr:
                    local_sys.stderr.close()
                local_sys.stdout.close()  # main currently owns an unclosed generated log stream.
                self.assertFalse(thread.is_alive(), "TEST_ONLY server thread leaked")

    def finish(self, thread):
        self.assertEqual(self.request("POST", "/api/v1/system/shutdown", {"confirm": True})[0], 200)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "Confirmed shutdown did not finish")

    def test_authenticated_shutdown_retires_only_matching_state_and_keeps_anchor(self):
        before = self.state.read_bytes()
        with self.running() as (thread, errors, holder):
            self.assertEqual(self.request("POST", "/api/v1/system/shutdown", {"confirm": True},
                                          authorized=False)[0], 401)
            self.assertEqual(self.request("POST", "/api/v1/system/shutdown", {"confirm": False})[0], 400)
            self.assertEqual(self.state.read_bytes(), before)
            self.finish(thread)
            self.assertEqual(errors, [])
            self.assertIsNone(holder["service"].index.conn)
            self.assertFalse(self.state.exists(), "Detached shutdown retained matching instance state")
            self.assertEqual(self.identity(self.anchor), self.anchor_identity)

    def test_new_generation_state_is_preserved(self):
        with self.running() as (thread, errors, _holder):
            replacement = self.local / "TEST_ONLY-new-generation.json"
            replacement.write_text(json.dumps({**self.doc, "token": "b" * 64}), encoding="utf-8")
            replacement.replace(self.state)
            before = self.state.read_bytes(), self.identity(self.state)
            self.finish(thread)
            self.assertEqual(errors, [])
            self.assertEqual((self.state.read_bytes(), self.identity(self.state)), before)
            self.assertEqual(self.identity(self.anchor), self.anchor_identity)

    def test_foreign_cli_state_path_is_never_retired(self):
        foreign = self.root / "TEST_ONLY-foreign-state.json"
        foreign.write_bytes(self.state.read_bytes())
        before = foreign.read_bytes(), self.identity(foreign), self.state.read_bytes()
        with self.running(state_path=foreign) as (thread, errors, _holder):
            self.finish(thread)
            self.assertEqual(errors, [])
        self.assertEqual((foreign.read_bytes(), self.identity(foreign), self.state.read_bytes()), before)

    def test_link_replacement_and_target_are_preserved(self):
        target = self.root / "TEST_ONLY-link-target.json"
        target.write_bytes(self.state.read_bytes())
        link = self.local / "TEST_ONLY-link"
        try:
            link.symlink_to(target)
        except OSError as error:
            self.skipTest("Generated symlink creation unavailable: " + type(error).__name__)
        with self.running() as (thread, errors, _holder):
            self.state.unlink()
            link.replace(self.state)
            before = target.read_bytes(), self.identity(target)
            self.finish(thread)
            self.assertEqual(errors, [])
            self.assertTrue(self.state.is_symlink())
            self.assertEqual((target.read_bytes(), self.identity(target)), before)

    def test_retirement_waits_for_start_transaction_and_preserves_new_generation(self):
        with self.running() as (thread, errors, holder):
            with startup_lock(self.local):
                self.assertEqual(self.request("POST", "/api/v1/system/shutdown", {"confirm": True})[0], 200)
                self.assertTrue(holder["closed"].wait(4), "Server close was not reached")
                thread.join(timeout=0.1)
                self.assertTrue(thread.is_alive(), "Retirement bypassed active startup lease")
                self.state.write_text(json.dumps({**self.doc, "token": "c" * 64}), encoding="utf-8")
                before = self.state.read_bytes(), self.identity(self.state)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual((self.state.read_bytes(), self.identity(self.state)), before)
            self.assertEqual(self.identity(self.anchor), self.anchor_identity)

    def test_primary_close_error_is_retained_and_state_not_retired(self):
        primary = RuntimeError("TEST_ONLY primary server-close failure")
        before = self.state.read_bytes(), self.identity(self.state)
        with self.running(close_error=primary) as (thread, errors, holder):
            self.finish(thread)
            self.assertEqual(len(errors), 1)
            self.assertIs(errors[0], primary)
            self.assertIsNone(holder["service"].index.conn)
            self.assertEqual((self.state.read_bytes(), self.identity(self.state)), before)

    def test_retirement_failure_keeps_state_and_bounded_diagnostic(self):
        private = "TEST_ONLY-secret-not-for-diagnostic"
        before = self.state.read_bytes(), self.identity(self.state)
        with self.assertLogs("t6_server", level="ERROR") as diagnostic, self.running(retirement_error=PermissionError(private)) as (thread, errors, holder):
            self.finish(thread)
            self.assertEqual(errors, [])
            self.assertIsNone(holder["service"].index.conn)
        self.assertEqual((self.state.read_bytes(), self.identity(self.state)), before)
        text = "\n".join(diagnostic.output)
        self.assertIn("event=local_server_failed", text)
        self.assertIn("exception_type=PermissionError", text)
        self.assertNotIn(private, text)
        self.assertNotIn(str(self.root), text)
