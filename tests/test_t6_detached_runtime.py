"""Generated detached-start identity checks; no real process, browser, port or media."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import t6_launcher as launcher
from runtime_config import runtime_identity


class DetachedRuntimeIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="TEST_ONLY-detached-runtime-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root / "TEST_ONLY-app"
        self.data = self.root / "TEST_ONLY-data"
        self.local = self.root / "TEST_ONLY-runtime"
        frontend = self.app / "viewer/dist/index.html"
        frontend.parent.mkdir(parents=True)
        frontend.write_text("TEST_ONLY generated frontend", encoding="utf-8")
        self.state = self.local / "instance.json"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (("ROOT", self.app), ("LOCAL", self.local),
                            ("STATE", self.state), ("LOG", self.local / "server.log")):
            self.stack.enter_context(patch.object(launcher, name, value))
        self.read_state = self.stack.enter_context(patch.object(launcher, "read_state", return_value=None))
        self.health = self.stack.enter_context(patch.object(launcher, "verified_running", return_value=True))
        self.choose = self.stack.enter_context(patch.object(launcher, "choose_available_port", return_value=4188))
        self.spawn = self.stack.enter_context(patch.object(launcher.subprocess, "Popen"))
        self.browser = self.stack.enter_context(patch.object(launcher.webbrowser, "open"))

    def assert_detached_contract(self):
        url, fresh = launcher.ensure_running(detached=True, data_root=self.data)
        self.assertIs(fresh, True)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["schema"], launcher.SCHEMA)
        self.assertEqual(state["runtime_id"], runtime_identity(self.data))
        self.assertEqual(state["port"], 4188)
        self.assertEqual(len(state["token"]), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in state["token"]))
        self.assertEqual(url, "http://127.0.0.1:4188/#access=" + state["token"])
        self.spawn.assert_called_once()
        args, kwargs = self.spawn.call_args
        self.assertEqual(args[0], [sys.executable, "-B", str(self.app / "t6_server.py"),
                                   "--port", "4188", "--state", str(self.state),
                                   "--data-root", str(self.data)])
        self.assertEqual(kwargs["cwd"], str(self.app))
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                 | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
        self.assertEqual(kwargs["creationflags"], flags)
        self.health.assert_called_once_with(state, expected_runtime_id=state["runtime_id"])
        self.browser.assert_not_called()

    def test_00_detached_ignores_unrelated_app_virtualenv(self):
        unrelated = self.app / ".venv/Scripts/pythonw.exe"
        unrelated.parent.mkdir(parents=True)
        payload = b"TEST_ONLY not an executable or approved runtime"
        unrelated.write_bytes(payload)
        self.assert_detached_contract()
        self.assertEqual(unrelated.read_bytes(), payload)

    def test_01_detached_without_app_virtualenv_preserves_current_identity_and_flags(self):
        self.assertFalse((self.app / ".venv").exists())
        self.assert_detached_contract()
        self.assertFalse((self.app / ".venv").exists())

    def test_02_verified_existing_instance_reuses_without_any_process(self):
        state = {"schema": launcher.SCHEMA, "port": 4188, "token": "a" * 64,
                 "runtime_id": runtime_identity(self.data)}
        self.read_state.return_value = state
        url, fresh = launcher.ensure_running(detached=True, data_root=self.data)
        self.assertIs(fresh, False)
        self.assertEqual(url, "http://127.0.0.1:4188/#access=" + "a" * 64)
        self.health.assert_called_once_with(state, expected_runtime_id=state["runtime_id"])
        self.spawn.assert_not_called()
        self.choose.assert_not_called()
        self.browser.assert_not_called()
        self.assertFalse(self.state.exists())
