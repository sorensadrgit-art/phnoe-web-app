"""TEST_ONLY scheduling/fault tests. Mocked snapshots are not decoder evidence.

Run from repository root with tests and this directory on PYTHONPATH.
"""
import copy
import hashlib
import os
import tempfile
import threading
import unittest
from concurrent import futures
from pathlib import Path
from unittest import mock

import native_evidence_fixture as fixtures
import normalize_capture
import source_coverage as gate


WAIT = 5
TRIALS = ("cam01_trial", "cam02_trial")


class TrialSchedulingTests(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory(prefix="TEST_ONLY-trial-scheduling-")
        self.addCleanup(owned.cleanup)
        self.project = Path(owned.name).resolve()
        self.identity = {"session_id": "TEST_ONLY-scheduling", "inputs": {
            role: hashlib.sha256(("TEST_ONLY original " + role).encode()).hexdigest()
            for role in normalize_capture.ROLES}}
        self.binding, self.outputs = fixtures.generated_normalization(
            self.project, self.identity, counts={"cam01": 3, "cam02": 4})
        self.paths = {role: self.project / normalize_capture.ROLES[role] for role in TRIALS}

    def metadata(self, relative):
        role = next(role for role in TRIALS if normalize_capture.ROLES[role] == relative)
        return copy.deepcopy(self.outputs[role])

    def capture(self, decode=True):
        return gate.capture_normalization(self.project, self.identity, self.binding, decode=decode)

    def wait(self, event):
        if not event.wait(WAIT):
            raise AssertionError("TEST_ONLY bounded synchronization timed out")

    def test_complete_trial_hash_and_decode_work_overlap(self):
        # A pool around decoding alone does not satisfy complete-role scheduling.
        hashes = threading.Barrier(2, timeout=WAIT)
        decodes = threading.Barrier(2, timeout=WAIT)
        original = gate.sha256_file
        seen = set()
        lock = threading.Lock()

        def hash_trial(path):
            with lock:
                first = Path(path) in self.paths.values() and Path(path) not in seen
                seen.add(Path(path))
            if first:
                hashes.wait()
            return original(path)

        def decode(project, relative, digest):
            decodes.wait()
            return self.metadata(relative)

        try:
            with mock.patch.object(gate, "sha256_file", side_effect=hash_trial), mock.patch.object(
                    gate, "_decoded_snapshot", side_effect=decode):
                result = self.capture()
            self.assertEqual(result["counts"], {"cam01": 3, "cam02": 4})
        finally:
            hashes.abort()
            decodes.abort()

    def observed_executor(self, completed, release_first=None):
        """Observe actual role futures; keep wrong-order collectors distinguishable."""
        active = threading.local()
        real_executor = futures.ThreadPoolExecutor
        wait = self.wait

        def identify(relative):
            token = getattr(active, "token", None)
            if token is None:
                raise AssertionError("TEST_ONLY complete role must run in observed executor")
            token["role"] = next(role for role in TRIALS
                                 if normalize_capture.ROLES[role] == relative)
            token["identified"].set()

        class ObservedExecutor(real_executor):
            def submit(self, function, /, *args, **kwargs):
                token = {"identified": threading.Event()}

                def run():
                    active.token = token
                    return function(*args, **kwargs)

                future = super().submit(run)
                original_result = future.result

                def result(timeout=None):
                    if release_first is not None:
                        wait(token["identified"])
                        if token["role"] == TRIALS[0]:
                            release_first.set()
                    return original_result(timeout=WAIT * 2 if timeout is None else timeout)

                future.result = result

                def finished(done):
                    role = token.get("role")
                    if role is not None:
                        # Callback runs only after the complete callable settles.
                        completed[role]["error"] = done.exception()
                        completed[role]["event"].set()

                future.add_done_callback(finished)
                return future

            def __exit__(self, *exception):
                if release_first is not None:
                    release_first.set()
                return super().__exit__(*exception)

        return ObservedExecutor, identify

    def test_original_role_failure_wins_when_second_fails_first(self):
        completed = {role: {"event": threading.Event()} for role in TRIALS}
        release_first = threading.Event()
        executor, identify = self.observed_executor(completed, release_first)

        def decode(project, relative, digest):
            identify(relative)
            if relative == normalize_capture.ROLES[TRIALS[0]]:
                self.wait(completed[TRIALS[1]]["event"])
                self.wait(release_first)
                raise ValueError("TEST_ONLY first role failure")
            raise ValueError("TEST_ONLY second role failure")

        try:
            with mock.patch.object(futures, "ThreadPoolExecutor", executor), mock.patch.object(
                    gate, "ThreadPoolExecutor", executor, create=True), mock.patch.object(
                    gate, "_decoded_snapshot", side_effect=decode):
                with self.assertRaisesRegex(ValueError, "TEST_ONLY first role failure"):
                    self.capture()
        finally:
            release_first.set()
        for role, message in zip(TRIALS, ("first", "second")):
            self.assertTrue(completed[role]["event"].is_set())
            self.assertEqual(str(completed[role]["error"]), "TEST_ONLY " + message + " role failure")

    def test_failure_waits_for_running_peer_cleanup(self):
        peer_started = threading.Event()
        first_failed = threading.Event()
        release = threading.Event()
        peer_cleaned = threading.Event()
        returned = threading.Event()
        errors = []
        cleaned_at_return = []

        def decode(project, relative, digest):
            if relative == normalize_capture.ROLES[TRIALS[0]]:
                self.wait(peer_started)
                first_failed.set()
                raise ValueError("TEST_ONLY first role failure")
            peer_started.set()
            try:
                self.wait(release)
                return self.metadata(relative)
            finally:
                peer_cleaned.set()

        def call():
            try:
                self.capture()
            except BaseException as error:
                errors.append(error)
            finally:
                cleaned_at_return.append(peer_cleaned.is_set())
                returned.set()

        with mock.patch.object(gate, "_decoded_snapshot", side_effect=decode):
            caller = threading.Thread(target=call, daemon=True)
            caller.start()
            try:
                self.wait(first_failed)
                self.assertFalse(returned.wait(.1), "failure escaped before running peer drained")
            finally:
                release.set()
                caller.join(WAIT * 2)
            self.assertFalse(caller.is_alive(), "owned call must terminate after release")
        self.assertTrue(peer_cleaned.is_set())
        self.assertEqual(cleaned_at_return, [True])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)
        self.assertEqual(str(errors[0]), "TEST_ONLY first role failure")

    def test_second_worker_start_failure_cancels_unreturned_queued_trial(self):
        """Real CPython executor enqueue/start failure; no Future replacement."""
        release = threading.Event()
        first_started = threading.Event()
        first_cleaned = threading.Event()
        second_entered = threading.Event()
        start_failed = threading.Event()
        queued_cancelled = threading.Event()
        returned = threading.Event()
        prefix = "TEST_ONLY-partial-submit-" + format(id(release), "x")
        sentinel = RuntimeError("TEST_ONLY second worker start failed")
        real_executor = futures.ThreadPoolExecutor
        real_start = threading.Thread.start
        real_future_init = futures.Future.__init__
        real_hash = gate.sha256_file
        executors, constructed, queued, errors, cleaned_at_error = [], [], [], [], []

        def owned_executor(*args, **kwargs):
            kwargs["thread_name_prefix"] = prefix
            executor = real_executor(*args, **kwargs)
            executors.append(executor)
            return executor

        def observe_future(future):
            real_future_init(future)
            if threading.current_thread() is caller:
                constructed.append(future)
                if len(constructed) == 2:
                    future.add_done_callback(
                        lambda done: queued_cancelled.set() if done.cancelled() else None)

        def start_thread(worker):
            if worker.name == prefix + "_1":
                self.wait(first_started)
                self.assertEqual(len(constructed), 2)
                self.assertTrue(constructed[0].running())
                self.assertFalse(constructed[1].done())
                self.assertEqual(executors[0]._work_queue.qsize(), 1)
                queued.append(constructed[1])
                start_failed.set()
                raise sentinel
            return real_start(worker)

        def hash_source(path):
            if (Path(path) == self.paths[TRIALS[1]]
                    and threading.current_thread().name.startswith(prefix + "_")):
                second_entered.set()
            return real_hash(path)

        def decode(project, relative, digest):
            if relative == normalize_capture.ROLES[TRIALS[0]]:
                first_started.set()
                try:
                    if not release.wait(WAIT * 4):
                        raise AssertionError("TEST_ONLY first role release timed out")
                    return self.metadata(relative)
                finally:
                    first_cleaned.set()
            second_entered.set()
            return self.metadata(relative)

        def call():
            try:
                self.capture()
            except BaseException as error:
                cleaned_at_error.append(first_cleaned.is_set())
                errors.append(error)
            finally:
                returned.set()

        caller = threading.Thread(target=call, daemon=True)
        with (mock.patch.object(futures, "ThreadPoolExecutor", owned_executor),
              mock.patch.object(gate, "ThreadPoolExecutor", owned_executor, create=True),
              mock.patch.object(futures.Future, "__init__", observe_future),
              mock.patch.object(threading.Thread, "start", start_thread),
              mock.patch.object(gate, "sha256_file", side_effect=hash_source),
              mock.patch.object(gate, "_decoded_snapshot", side_effect=decode)):
            caller.start()
            try:
                self.wait(start_failed)
                cancelled_while_held = queued_cancelled.wait(WAIT)
                cleaned_while_held = first_cleaned.is_set()
                returned_while_held = returned.is_set()
            finally:
                release.set()
                caller.join(WAIT * 2)
            self.assertFalse(caller.is_alive(), "owned caller must drain after first release")
        self.assertEqual(errors, [sentinel])
        self.assertIs(errors[0], sentinel)
        self.assertEqual(cleaned_at_error, [True])
        self.assertTrue(first_cleaned.is_set())
        self.assertTrue(constructed[0].done())
        self.assertFalse(cleaned_while_held, "first role must remain active during cancellation")
        self.assertFalse(returned_while_held, "submission error must wait for active cleanup")
        self.assertTrue(cancelled_while_held, "unreturned queued Future was not cancelled while first held")
        self.assertTrue(queued[0].cancelled())
        self.assertFalse(second_entered.is_set(), "pending second complete-role validation entered")

    @staticmethod
    def mutate_same_size(path):
        before = path.stat()
        content = bytearray(path.read_bytes())
        content[-1] ^= 1
        path.write_bytes(content)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = path.stat()
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise AssertionError("TEST_ONLY mutation must preserve size and mtime")

    def test_mutation_after_first_complete_role_while_peer_runs_is_refused(self):
        for target in ("source", "normalization"):
            with self.subTest(target=target):
                path = self.paths[TRIALS[0]] if target == "source" else self.project / "normalization.json"
                original, before = path.read_bytes(), path.stat()
                completed = {role: {"event": threading.Event()} for role in TRIALS}
                executor, identify = self.observed_executor(completed)
                mutated = threading.Event()

                def decode(project, relative, digest):
                    identify(relative)
                    if relative == normalize_capture.ROLES[TRIALS[1]]:
                        self.wait(completed[TRIALS[0]]["event"])
                        self.assertIsNone(completed[TRIALS[0]]["error"])
                        self.assertFalse(completed[TRIALS[1]]["event"].is_set())
                        self.mutate_same_size(path)
                        mutated.set()
                    return self.metadata(relative)

                try:
                    with mock.patch.object(futures, "ThreadPoolExecutor", executor), mock.patch.object(
                            gate, "ThreadPoolExecutor", executor, create=True), mock.patch.object(
                            gate, "_decoded_snapshot", side_effect=decode):
                        with self.assertRaisesRegex(ValueError, "QUALITY_UNVERIFIED:"):
                            self.capture()
                    self.assertTrue(mutated.is_set())
                    self.assertTrue(completed[TRIALS[1]]["event"].is_set())
                finally:
                    path.write_bytes(original)
                    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    def test_linked_trial_is_refused_even_when_bytes_match(self):
        path = self.paths[TRIALS[0]]
        target = self.project / "TEST_ONLY-original.mp4"
        path.rename(target)
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError) as error:
            target.rename(path)
            self.skipTest("actual symlink unavailable: " + str(error))
        with mock.patch.object(gate, "_decoded_snapshot", side_effect=lambda p, r, d: self.metadata(r)):
            with self.assertRaisesRegex(ValueError, "QUALITY_UNVERIFIED:"):
                self.capture()
        self.assertTrue(path.is_symlink())

    def test_escaping_trial_path_is_refused(self):
        # Exact role binding is itself a trust boundary, before any outside read.
        import json
        path = self.project / "normalization.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["outputs"][TRIALS[0]]["path"] = "../TEST_ONLY-outside.mp4"
        path.write_text(json.dumps(value), encoding="utf-8")
        with mock.patch.object(gate, "_decoded_snapshot", side_effect=lambda p, r, d: self.metadata(r)) as decoder:
            with self.assertRaisesRegex(ValueError, "normalized media binding differs"):
                gate.capture_normalization(self.project, self.identity, decode=True)
        self.assertNotIn("../TEST_ONLY-outside.mp4", [call.args[1] for call in decoder.call_args_list])

    def test_decode_false_creates_no_executor_or_probe(self):
        with mock.patch.object(futures, "ThreadPoolExecutor", side_effect=AssertionError("executor forbidden")), \
                mock.patch.object(gate, "ThreadPoolExecutor", create=True,
                                  side_effect=AssertionError("executor forbidden")), \
                mock.patch.object(normalize_capture, "_probe_output", side_effect=AssertionError("probe forbidden")), \
                mock.patch.object(gate, "_decoded_snapshot", side_effect=AssertionError("decode forbidden")):
            result = self.capture(decode=False)
        self.assertEqual(result, {"binding": self.binding, "outputs": self.outputs, "counts": {}})

    def test_repeated_decode_checks_each_trial_every_time(self):
        calls = []
        lock = threading.Lock()

        def decode(project, relative, digest):
            with lock:
                calls.append((relative, digest))
            return self.metadata(relative)

        expected = [(normalize_capture.ROLES[role], self.outputs[role]["sha256"]) for role in TRIALS]
        with mock.patch.object(gate, "_decoded_snapshot", side_effect=decode):
            for _ in range(2):
                start = len(calls)
                self.assertEqual(self.capture()["counts"], {"cam01": 3, "cam02": 4})
                self.assertCountEqual(calls[start:], expected)


if __name__ == "__main__":
    unittest.main()


