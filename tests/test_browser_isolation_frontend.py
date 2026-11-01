"""Generated staged-build contract; no actual browser/device or shared build writes."""
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

from tools import verify_browser_isolation as harness


class BrowserIsolationFrontendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="TEST_ONLY-isolation-frontend-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.build = self.root / "dist" / "TEST_ONLY-fresh-build"
        self.build.mkdir(parents=True)
        (self.build / "index.html").write_bytes(b"<!doctype html><p>TEST_ONLY_FRESH</p>")
        (self.build / "favicon.svg").write_bytes(b"<svg>TEST_ONLY</svg>")
        self.legacy = self.root / "viewer" / "dist"
        self.legacy.mkdir(parents=True)
        (self.legacy / "index.html").write_bytes(b"<!doctype html><p>TEST_ONLY_STALE</p>")
        self.output = self.root / "dist" / "TEST_ONLY-receipt"
        self.served = []
        self.commands = []
        self.origin = None
        self.real_make_server = harness.make_server
        self.real_subprocess_run = subprocess.run

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()}

    def server(self, *args, **kwargs):
        self.served.append(Path(kwargs["dist"]).resolve())
        server = self.real_make_server(*args, **kwargs)
        self.origin = f"http://127.0.0.1:{server.server_port}"
        return server

    def browser(self, command, **kwargs):
        if not command or command[0] != "TEST_ONLY-agent-browser":
            return self.real_subprocess_run(command, **kwargs)
        self.commands.append(command)
        data = {"result": True, "errors": [], "messages": []}
        return subprocess.CompletedProcess(command, 0, json.dumps({"success": True, "data": data}), "")

    def invoke(self, build, scenario=None, output=None):
        with (patch.object(harness, "ROOT", self.root),
              patch.object(harness.shutil, "which", return_value="TEST_ONLY-agent-browser"),
              patch.object(harness.subprocess, "run", side_effect=self.browser),
              patch.object(harness, "make_server", side_effect=self.server)):
            try:
                harness.verify(output or self.output, scenario or self.assert_fresh_served,
                               frontend_dist=build)
            except TypeError as error:
                if "unexpected keyword argument 'frontend_dist'" in str(error):
                    self.fail("Staged frontend selection is absent; generated fixture reached verify: " + str(error))
                raise

    def assert_fresh_served(self, *_args):
        with urlopen(self.origin, timeout=5) as response:
            self.assertEqual(response.read(), (self.build / "index.html").read_bytes())

    def test_explicit_staged_build_is_served_and_receipt_hashes_exact_bytes(self):
        expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.build.iterdir()}
        self.invoke(self.build)
        self.assertEqual(self.served, [self.build])
        receipt = json.loads((self.output / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["build_sha256"], expected)
        self.assertIn(b"TEST_ONLY_STALE", (self.legacy / "index.html").read_bytes())

    def test_missing_index_never_falls_back_to_legacy(self):
        (self.build / "index.html").unlink()
        before = self.snapshot()
        with self.assertRaises((ValueError, RuntimeError, FileNotFoundError)):
            self.invoke(self.build)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.served, [])
        self.assertEqual(self.commands, [])

    def test_outside_dist_and_output_overlap_refuse_before_server_or_browser(self):
        outside = self.root / "TEST_ONLY-outside"
        outside.mkdir()
        (outside / "index.html").write_bytes(b"<!doctype html>")
        for build, output in ((outside, self.output), (self.build, self.build),
                              (self.build, self.build / "receipts"),
                              (self.build, self.root / "dist")):
            with self.subTest(build=build.name, output=output.name):
                before = self.snapshot()
                with self.assertRaises((ValueError, RuntimeError, FileExistsError)):
                    self.invoke(build, output=output)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.served, [])
                self.assertEqual(self.commands, [])

    def test_escaping_build_symlink_refuses_before_server_or_browser(self):
        outside = self.root / "TEST_ONLY-outside"
        outside.mkdir()
        (outside / "index.html").write_bytes(b"<!doctype html>")
        alias = self.root / "dist" / "TEST_ONLY-escape"
        try:
            alias.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest("Real symlink creation unavailable: " + str(error))
        before = self.snapshot()
        with self.assertRaises((ValueError, RuntimeError)):
            self.invoke(alias)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.served, [])
        self.assertEqual(self.commands, [])

    def test_build_mutation_cannot_finish_with_pass_receipt(self):
        def mutation(*args):
            self.assert_fresh_served(*args)
            (self.build / "index.html").write_bytes(b"<!doctype html>TEST_ONLY_CHANGED")
        with self.assertRaises((ValueError, RuntimeError)):
            self.invoke(self.build, scenario=mutation)
        self.assertEqual((self.build / "index.html").read_bytes(), b"<!doctype html>TEST_ONLY_CHANGED")
        if (self.output / "receipt.json").exists():
            self.assertEqual(json.loads((self.output / "receipt.json").read_text())["status"], "FAIL")

    def test_setup_failure_closes_real_sqlite_and_preserves_original_error(self):
        original_error = RuntimeError("TEST_ONLY generated setup failure")
        real_service = harness.IntegratedService
        services = []
        runtime_paths = []
        closed_before_test_cleanup = []
        caught = None

        def create_real_service(projects):
            service = real_service(projects)
            services.append((service, service.index.conn))
            runtime_paths.append(Path(projects).parent)
            return service

        with (patch.object(harness, "IntegratedService", side_effect=create_real_service),
              patch.object(real_service, "create_session", side_effect=original_error)):
            try:
                self.invoke(self.build)
            except RuntimeError as error:
                caught = error
            finally:
                for service, connection in services:
                    try:
                        connection.execute("SELECT 1")
                    except sqlite3.ProgrammingError:
                        closed_before_test_cleanup.append(True)
                    else:
                        closed_before_test_cleanup.append(False)
                    finally:
                        # Safety cleanup follows the actual close observation.
                        service.close()

        self.assertIs(caught, original_error)
        self.assertEqual(closed_before_test_cleanup, [True])
        self.assertEqual(self.served, [])
        self.assertEqual(self.commands, [])
        self.assertTrue(all(not path.exists() for path in runtime_paths))
        receipt = json.loads((self.output / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "FAIL")
        self.assertEqual(receipt["error"], {"code": "VERIFICATION_FAILED", "exception_type": "RuntimeError"})
        self.assertNotIn(str(original_error), json.dumps(receipt))

    def test_live_thread_after_join_fails_receipt_and_continues_cleanup(self):
        real_thread = harness.threading.Thread
        real_service = harness.IntegratedService
        workers = []
        services = []
        runtime_paths = []
        original_error = RuntimeError("TEST_ONLY scenario failed before cleanup")
        cleanup_error = "thread.join: server thread still alive after 5-second join"

        class StuckAfterJoin:
            """Real server worker; only the post-join liveness result is a test double."""
            def __init__(self, *args, **kwargs):
                self.actual = real_thread(*args, **kwargs)
                self.join_calls = []
                self.join_returned = False
                workers.append(self)

            @property
            def ident(self):
                return self.actual.ident

            def start(self):
                self.actual.start()

            def is_alive(self):
                return self.join_returned or self.actual.is_alive()

            def join(self, timeout):
                self.join_calls.append(timeout)
                self.actual.join(timeout)
                self.join_returned = True

        def create_real_service(projects):
            service = real_service(projects)
            services.append((service, service.index.conn))
            runtime_paths.append(Path(projects).parent)
            self.addCleanup(service.close)
            return service

        for primary in (None, original_error):
            with self.subTest(primary_error=primary is not None):
                output = self.root / "dist" / ("TEST_ONLY-primary" if primary else "TEST_ONLY-join-only")
                caught = None

                def scenario(*args, error=primary):
                    self.assert_fresh_served(*args)
                    self.assertTrue((runtime_paths[-1] / "init.js").is_file())
                    if error is not None:
                        raise error

                # Patch only the harness binding, not the shared threading module:
                # real HTTP request workers and real SQLite cleanup remain active.
                with (patch.object(harness, "threading") as isolated_threading,
                      patch.object(harness, "IntegratedService", side_effect=create_real_service)):
                    isolated_threading.Thread.side_effect = StuckAfterJoin
                    try:
                        self.invoke(self.build, scenario=scenario, output=output)
                    except RuntimeError as error:
                        caught = error

                worker = workers[-1]
                self.assertEqual(worker.join_calls, [5])
                self.assertFalse(worker.actual.is_alive(), "Real TEST_ONLY server worker leaked")
                self.assertTrue(worker.join_returned)
                # These actions follow thread.join in the production cleanup list.
                # Observe their actual effects even when the join diagnostic fails.
                with self.assertRaises(sqlite3.ProgrammingError):
                    services[-1][1].execute("SELECT 1")
                self.assertFalse(runtime_paths[-1].exists())
                self.assertFalse((runtime_paths[-1] / "init.js").exists())
                self.assertEqual(self.commands[-1][-1], "close")
                receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(receipt["status"], "FAIL")
                self.assertEqual(receipt.get("cleanup_errors"), [{
                    "action": "thread.join", "code": "CLEANUP_ACTION_FAILED",
                    "exception_type": "RuntimeError",
                }])
                serialized_receipt = json.dumps(receipt)
                self.assertNotIn(cleanup_error, serialized_receipt)
                self.assertNotIn(str(original_error), serialized_receipt)
                self.assertEqual(receipt["build_inventory_after"], receipt["build_inventory_before"])
                if primary is None:
                    self.assertIsInstance(caught, RuntimeError)
                    self.assertEqual(str(caught), "CLEANUP_OR_BUILD_FAILED")
                else:
                    self.assertIs(caught, primary)
                    self.assertEqual(receipt["error"], {"code": "VERIFICATION_FAILED", "exception_type": "RuntimeError"})


    def test_repeated_reopen_uses_numbered_fresh_sessions_and_closes_current(self):
        for reopen_count in (0, 2):
            with self.subTest(reopen_count=reopen_count):
                self.commands.clear()
                output = self.root / "dist" / f"TEST_ONLY-reopen-{reopen_count}"

                def scenario(*args, count=reopen_count):
                    self.assert_fresh_served(*args)
                    reopen = args[-1]
                    for _ in range(count):
                        reopen()

                self.invoke(self.build, scenario=scenario, output=output)
                events = [
                    (command[command.index("--session") + 1],
                     "open" if "open" in command else "close")
                    for command in self.commands
                    if "open" in command or "close" in command
                ]
                opened = [session for session, action in events if action == "open"]
                closed = [session for session, action in events if action == "close"]
                self.assertEqual(len(opened), reopen_count + 1)
                self.assertEqual(len(set(opened)), len(opened))
                self.assertEqual(
                    opened[1:],
                    [f"{opened[0]}-restart-{number}" for number in range(1, reopen_count + 1)],
                )
                self.assertEqual(closed, opened)
                self.assertEqual(
                    events,
                    [event for session in opened for event in ((session, "open"), (session, "close"))],
                )
                receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(receipt["status"], "PASS")
                self.assertNotIn("cleanup_errors", receipt)
                self.assertEqual(receipt["build_inventory_after"], receipt["build_inventory_before"])

    def test_ambiguous_second_reopen_is_not_retried_and_cleanup_preserves_error(self):
        """A transport test double checks refusal; it does not reproduce a native IPC race."""
        real_service = harness.IntegratedService
        original_browser = self.browser
        services = []
        runtime_paths = []
        opened = []
        error_text = json.dumps({
            "code": "outcome_unknown",
            "error": "TEST_ONLY command reached daemon; no response; not retried",
            "success": False,
        }) + "\n"

        def create_real_service(projects):
            service = real_service(projects)
            services.append(service.index.conn)
            runtime_paths.append(Path(projects).parent)
            self.addCleanup(service.close)
            return service

        def fail_third_open(command, **kwargs):
            if command and command[0] == "TEST_ONLY-agent-browser" and "open" in command:
                opened.append(command[command.index("--session") + 1])
                if len(opened) == 3:
                    self.commands.append(command)
                    return subprocess.CompletedProcess(command, 1, "", error_text)
            return original_browser(command, **kwargs)

        def scenario(_browser, _evaluate, _wait_for, _service, _output, checks, reopen):
            self.assert_fresh_served()
            reopen()
            checks["first_reopen_completed"] = True
            reopen()
            checks["second_reopen_completed"] = True

        with (patch.object(self, "browser", side_effect=fail_third_open),
              patch.object(harness, "IntegratedService", side_effect=create_real_service),
              self.assertRaises(RuntimeError) as caught):
            self.invoke(self.build, scenario=scenario)

        self.assertEqual(str(caught.exception), "BROWSER_CLI_NONZERO_EXIT")
        self.assertEqual(len(opened), 3, "An ambiguous open must never be sent again")
        closed = [
            command[command.index("--session") + 1]
            for command in self.commands if "close" in command
        ]
        self.assertEqual(closed, opened)
        self.assertEqual(self.commands[-1][-1], "close")
        self.assertEqual(len(services), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            services[0].execute("SELECT 1")
        self.assertTrue(all(not path.exists() for path in runtime_paths))
        with self.assertRaises(OSError), urlopen(self.origin, timeout=1):
            self.fail("Generated server remained reachable after failed reopen cleanup")
        receipt = json.loads((self.output / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "FAIL")
        self.assertEqual(receipt["error"], {"code": "VERIFICATION_FAILED", "exception_type": "RuntimeError"})
        self.assertNotIn("TEST_ONLY command reached daemon; no response; not retried", json.dumps(receipt))
        self.assertNotIn("outcome_unknown", json.dumps(receipt))
        self.assertEqual(receipt["checks"], {"first_reopen_completed": True})
        self.assertNotIn("cleanup_errors", receipt)
        self.assertNotIn("build_error", receipt)
        self.assertNotIn("diagnostics_error", receipt)
        self.assertEqual(receipt["build_inventory_after"], receipt["build_inventory_before"])
