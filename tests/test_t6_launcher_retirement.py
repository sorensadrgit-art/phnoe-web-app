"""Generated launcher retirement controls; no real HTTP, child, device or browser."""
from __future__ import annotations

import io
import logging
import sys
import tempfile
import threading
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import t6_launcher as launcher
from runtime_config import startup_lock

LOGGER = logging.getLogger(__name__)


class LauncherRetirementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="TEST_ONLY-launcher-retirement-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        frontend = self.root / "app/viewer/dist/index.html"
        frontend.parent.mkdir(parents=True)
        frontend.write_bytes(b"TEST_ONLY generated build")
        self.local = self.root / "runtime"
        self.state = self.local / "instance.json"
        self.data = self.root / "data"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.running = threading.Event()
        self.entered = threading.Event()
        self.stopped = threading.Event()
        self.release_close = threading.Event()
        self.release_close.set()
        self.close_entered = threading.Event()
        self.retire_entered = threading.Event()
        self.close_threads = []
        self.uncaught = []
        self.worker = None
        self.close_error = None
        self.serve_error = None
        self.service = Mock()
        self.server = types.SimpleNamespace(
            serve_forever=self.serve, shutdown=self.stopped.set, server_close=self.close,
        )
        server_module = types.ModuleType("t6_server")
        server_module.make_server = Mock(return_value=self.server)
        service_module = types.ModuleType("t6_service")
        service_module.IntegratedService = Mock(return_value=self.service)
        self.stack.enter_context(patch.dict(sys.modules, {
            "t6_server": server_module, "t6_service": service_module,
        }))
        for name, value in (
            ("ROOT", self.root / "app"), ("LOCAL", self.local), ("STATE", self.state),
            ("LOG", self.local / "launcher.log"), ("_SERVER_RUNNING", self.running),
            ("_SERVER_INSTANCE", None), ("_SERVER_THREAD", None), ("_SERVER_ERRORS", []),
        ):
            self.stack.enter_context(patch.object(launcher, name, value, create=True))
        self.stack.enter_context(patch.object(launcher, "choose_available_port", return_value=4188))
        self.stack.enter_context(patch.object(launcher, "verified_running", side_effect=self.ready))
        self.stack.enter_context(patch.object(threading, "excepthook", side_effect=self.uncaught.append))
        self.stack.enter_context(patch.object(sys, "argv", [
            "t6_launcher.py", "--no-browser", "--data-root", str(self.data),
        ]))
        self.stack.enter_context(patch("sys.stdout", new=io.StringIO()))
        self.stderr = self.stack.enter_context(patch("sys.stderr", new=io.StringIO()))
        self.addCleanup(self.finish_worker)

    def serve(self, *, poll_interval):
        self.worker = threading.current_thread()
        self.entered.set()
        if not self.stopped.wait(3):
            raise TimeoutError("TEST_ONLY server stop not supplied")
        if self.serve_error is not None:
            raise self.serve_error

    def ready(self, *_args, **_kwargs):
        if not self.entered.wait(1):
            raise TimeoutError("TEST_ONLY worker did not enter")
        return True

    def close(self):
        self.close_threads.append(threading.current_thread().ident)
        self.close_entered.set()
        if not self.release_close.wait(3):
            raise TimeoutError("TEST_ONLY close not released")
        self.service.close()
        if self.close_error is not None:
            raise self.close_error

    def finish_worker(self):
        self.release_close.set()
        self.stopped.set()
        if self.worker is not None:
            self.worker.join(timeout=4)
            self.assertFalse(self.worker.is_alive(), "Owned generated worker did not finish")

    def start(self):
        url, fresh = launcher.ensure_running(data_root=self.data)
        self.assertTrue(fresh)
        self.assertTrue(self.entered.is_set())
        return url

    def test_00_completion_event_waits_for_server_close(self):
        self.release_close.clear()
        self.start()
        self.stopped.set()
        self.assertTrue(self.close_entered.wait(1))
        self.assertTrue(self.running.is_set(), "Completion exposed while server_close is blocked")
        self.release_close.set()
        self.finish_worker()
        self.assertFalse(self.running.is_set())
        self.assertFalse(self.state.exists())
        self.service.close.assert_called_once()

    def test_01_completion_event_waits_for_locked_owned_state_retirement(self):
        self.start()
        remove_owned = launcher._remove_owned_state

        def observed_retirement(instance, *, _locked=False):
            if not _locked:
                self.retire_entered.set()
            return remove_owned(instance, _locked=_locked)

        with patch.object(launcher, "_remove_owned_state", side_effect=observed_retirement):
            with startup_lock(self.local):
                self.stopped.set()
                self.assertTrue(self.retire_entered.wait(1))
                self.assertTrue(self.state.exists())
                self.assertTrue(self.running.is_set(), "Completion exposed before the startup lease retired state")
            self.finish_worker()
        self.assertFalse(self.state.exists())
        self.assertFalse(self.running.is_set())
        self.assertTrue((self.local / "t6-startup.lock").exists())

    def test_02_foreground_main_joins_blocked_retirement_before_success(self):
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        join_entered = threading.Event()
        results = []
        failures = []

        def retiring():
            entered.set()
            if not release.wait(3):
                failures.append(TimeoutError("TEST_ONLY retirement was not released"))

        worker = threading.Thread(target=retiring, name="TEST_ONLY-retirement")

        def create_owned_worker(**_kwargs):
            launcher._SERVER_THREAD = worker
            return "http://127.0.0.1:4188/#access=TEST_ONLY", True

        actual_join = worker.join

        def observed_join(*args, **kwargs):
            join_entered.set()
            return actual_join(*args, **kwargs)

        def run_main():
            try:
                results.append(launcher.main())
            except BaseException as error:
                LOGGER.exception("TEST_ONLY launcher main failed")
                failures.append(error)
            finally:
                finished.set()

        main = threading.Thread(target=run_main, name="TEST_ONLY-launcher-main")
        try:
            worker.start()
            self.assertTrue(entered.wait(1))
            with (
                patch.object(launcher, "ensure_running", side_effect=create_owned_worker),
                patch.object(worker, "join", side_effect=observed_join),
            ):
                main.start()
                self.assertTrue(join_entered.wait(1), "Foreground main did not join its owned retirement worker")
                self.assertFalse(finished.wait(0.15), "Foreground returned while owned retirement was blocked")
                release.set()
                main.join(timeout=2)
        finally:
            release.set()
            if worker.ident is not None:
                worker.join(timeout=2)
            if main.ident is not None:
                main.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(main.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(results, [0])

    def test_03_close_failure_still_retires_and_preserves_first_worker_error(self):
        primary = LookupError("TEST_ONLY close failure")
        secondary = OSError("TEST_ONLY retirement failure")
        self.close_error = primary
        self.start()
        with patch.object(launcher, "_remove_owned_state", side_effect=secondary) as retire:
            self.stopped.set()
            self.finish_worker()
        retire.assert_called_once()
        self.assertEqual(len(launcher._SERVER_ERRORS), 2)
        self.assertIs(launcher._SERVER_ERRORS[0], primary)
        self.assertIs(launcher._SERVER_ERRORS[1], secondary)
        self.assertFalse(self.running.is_set())
        self.assertTrue(self.state.exists(), "A failed retirement must preserve its state artifact")
        self.assertEqual(self.uncaught, [])

    def test_04_serve_failure_is_primary_and_both_cleanup_actions_still_finish(self):
        primary = RuntimeError("TEST_ONLY serve failure")
        self.serve_error = primary
        self.close_error = LookupError("TEST_ONLY close failure")
        self.start()
        self.stopped.set()
        self.finish_worker()
        self.assertFalse(self.state.exists())
        self.service.close.assert_called_once()
        self.assertEqual(len(launcher._SERVER_ERRORS), 2)
        self.assertIs(launcher._SERVER_ERRORS[0], primary)
        self.assertIs(launcher._SERVER_ERRORS[1], self.close_error)
        self.assertEqual(self.uncaught, [])

    def test_05_ctrl_c_requests_shutdown_and_only_worker_closes_service(self):
        actual_start = launcher.ensure_running
        ready = threading.Event()

        def create_owned_worker(**kwargs):
            result = actual_start(**kwargs)
            ready.set()
            return result

        def interrupt(_seconds):
            raise KeyboardInterrupt

        with (
            patch.object(launcher, "ensure_running", side_effect=create_owned_worker),
            patch.object(launcher, "time", types.SimpleNamespace(sleep=interrupt)),
        ):
            result = launcher.main()
        self.assertTrue(ready.is_set())
        self.finish_worker()
        self.assertEqual(result, 0)
        self.assertEqual(self.close_threads, [self.worker.ident])
        self.service.close.assert_called_once()
        self.assertFalse(self.state.exists())
        self.assertFalse(self.running.is_set())
        self.assertEqual(self.uncaught, [])


    def test_06_worker_cleanup_failure_cannot_be_reported_as_foreground_success(self):
        primary = LookupError("TEST_ONLY worker cleanup failure")
        worker = Mock()
        worker.is_alive.return_value = False

        def create_owned_worker(**_kwargs):
            launcher._SERVER_THREAD = worker
            launcher._SERVER_ERRORS.append(primary)
            return "http://127.0.0.1:4188/#access=TEST_ONLY", True

        with patch.object(launcher, "ensure_running", side_effect=create_owned_worker):
            result = launcher.main()
        self.assertEqual(result, 1)
        worker.join.assert_called_once()
        self.assertIn("TEST_ONLY worker cleanup failure", self.stderr.getvalue())
        self.assertIn("LookupError", (self.local / "launcher.log").read_text(encoding="utf-8"))

    def test_07_startup_primary_is_not_replaced_by_join_cleanup_failure(self):
        primary = LookupError("TEST_ONLY primary startup failure")
        secondary = OSError("TEST_ONLY secondary join failure")
        worker = Mock()
        worker.join.side_effect = secondary
        observed = []
        ensure_directory = launcher.ensure_directory

        def failed_start(**_kwargs):
            launcher._SERVER_THREAD = worker
            raise primary

        def observe_primary(path):
            observed.append(sys.exc_info()[1])
            return ensure_directory(path)

        with (
            patch.object(launcher, "ensure_running", side_effect=failed_start),
            patch.object(launcher, "ensure_directory", side_effect=observe_primary),
        ):
            result = launcher.main()
        self.assertEqual(result, 1)
        self.assertEqual(observed, [primary])
        self.assertIs(primary.__cause__, secondary)
        worker.join.assert_called_once()
        self.assertIn("TEST_ONLY primary startup failure", self.stderr.getvalue())
        self.assertNotIn("TEST_ONLY secondary join failure", self.stderr.getvalue())

    def assert_browser_failure_retires_owned_worker(self, shutdown_error=None):
        actual_start = launcher.ensure_running
        ensure_directory = launcher.ensure_directory
        joins = []
        observed = []
        fake_ctypes = types.ModuleType("ctypes")
        fake_ctypes.windll = types.SimpleNamespace(
            user32=types.SimpleNamespace(MessageBoxW=Mock()),
        )

        def shutdown():
            self.stopped.set()
            if shutdown_error is not None:
                raise shutdown_error

        def create_owned_worker(**kwargs):
            result = actual_start(**kwargs)
            actual_join = self.worker.join

            def observed_join(*args, **kwargs):
                joins.append(self.stopped.is_set())
                return actual_join(*args, **kwargs)

            self.stack.enter_context(patch.object(self.worker, "join", side_effect=observed_join))
            return result

        def observe_primary(path):
            error = sys.exc_info()[1]
            if error is not None:
                observed.append(error)
            return ensure_directory(path)

        with (
            patch.object(sys, "argv", ["t6_launcher.py", "--data-root", str(self.data)]),
            patch.object(launcher, "ensure_running", side_effect=create_owned_worker),
            patch.object(launcher, "ensure_directory", side_effect=observe_primary),
            patch.object(launcher.webbrowser, "open", return_value=False) as browser,
            patch.object(self.server, "shutdown", side_effect=shutdown) as stop,
            patch.dict(sys.modules, {"ctypes": fake_ctypes}),
        ):
            result = launcher.main()
        self.assertEqual(result, 1)
        browser.assert_called_once()
        stop.assert_called_once()
        self.assertEqual(joins, [True], "Shutdown must precede the real owned-worker join")
        self.assertFalse(self.worker.is_alive())
        self.service.close.assert_called_once()
        self.assertFalse(self.state.exists())
        self.assertFalse(self.running.is_set())
        self.assertEqual(self.uncaught, [])
        self.assertEqual(len(observed), 1)
        self.assertIsInstance(observed[0], RuntimeError)
        self.assertEqual(str(observed[0]), "Unable to open default browser to the local KineLab app")
        self.assertIs(observed[0].__cause__, shutdown_error)

    def test_08_browser_open_failure_shuts_down_and_joins_owned_worker(self):
        self.assert_browser_failure_retires_owned_worker()

    def test_09_shutdown_failure_still_joins_and_preserves_browser_error(self):
        self.assert_browser_failure_retires_owned_worker(OSError("TEST_ONLY shutdown failure"))


if __name__ == "__main__":
    unittest.main()
