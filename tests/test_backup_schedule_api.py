"""Proposed R18 first slice: generated roots, actual authenticated handler, no scheduler activation."""
from __future__ import annotations

import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backup_schedule import BackupSchedulePump
from t6_server import make_server
from t6_service import IntegratedService


class BackupScheduleAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="TEST_ONLY-R18-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dist = self.root / "dist"
        self.dist.mkdir()
        (self.dist / "index.html").write_text("TEST_ONLY R18", encoding="utf-8")
        self.samples = self.root / "samples"
        self.samples.mkdir()
        self.service = IntegratedService(self.root / "projects")
        self.addCleanup(self.service.close)
        self.server = make_server(self.service, token="a" * 50, dist=self.dist, samples=self.samples, port=0)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())

    def snapshot(self):
        result = {}
        for path in sorted(self.service.projects_root.rglob("*")):
            info = path.lstat()
            result[path.relative_to(self.service.projects_root).as_posix()] = (
                info.st_dev, info.st_ino, info.st_mode,
                hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
            )
        return result

    def request(self, method, path, body=None, *, authenticated=True, origin=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Host": f"127.0.0.1:{self.server.server_port}"}
        if authenticated:
            headers["Authorization"] = "Bearer " + "a" * 50
        if origin is not None:
            headers["Origin"] = origin
        payload = None if body is None else json.dumps(body).encode("utf-8")
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, payload, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_00_schedule_status_is_disabled_and_read_only(self):
        before = self.snapshot()
        status, body = self.request("GET", "/api/v1/backup/schedule")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["schema"], "kinelab.backup-schedule-status.v1")
        self.assertIs(body["enabled"], False)
        self.assertEqual(body["state"], "DISABLED")
        self.assertEqual(body["policy_status"], "OPEN")
        self.assertIsNone(body["next_due_at_utc"])
        self.assertIsNone(body["last_job"])
        self.assertIsNone(body["last_verified_archive"])
        self.assertIsNone(body["last_verified_recovery_point"])
        self.assertEqual(body["missed_count"], 0)
        self.assertEqual(body["pruning"], {"enabled": False, "reason": "POLICY_NOT_APPROVED"})
        self.assertNotIn(str(self.root), json.dumps(body))
        self.assertEqual(self.snapshot(), before)

    def test_01_enable_remains_refused_without_policy_and_without_writes(self):
        before = self.snapshot()
        status, body = self.request("POST", "/api/v1/backup/schedule", {"enabled": True, "confirm": True})
        self.assertEqual(status, 409, body)
        self.assertIn("BACKUP_SCHEDULE_POLICY_REQUIRED", json.dumps(body))
        self.assertEqual(self.snapshot(), before)

    def test_02_disable_is_idempotent_and_never_creates_control_state(self):
        before = self.snapshot()
        for _ in range(2):
            status, body = self.request("POST", "/api/v1/backup/schedule", {"enabled": False, "confirm": True})
            self.assertEqual(status, 200, body)
            self.assertIs(body["enabled"], False)
            self.assertEqual(self.snapshot(), before)

    def test_03_pruning_refuses_without_touching_any_existing_copy(self):
        directory = self.service.projects_root / "backups"
        directory.mkdir()
        (directory / "TEST_ONLY-protected.zip").write_bytes(b"TEST_ONLY generated sentinel; not a valid backup")
        before = self.snapshot()
        for confirm in (False, True):
            with self.subTest(confirm=confirm):
                status, body = self.request("POST", "/api/v1/backup/prune", {"confirm": confirm})
                self.assertEqual(status, 409, body)
                self.assertIn("BACKUP_PRUNING_UNAVAILABLE", json.dumps(body))
                self.assertEqual(self.snapshot(), before)

    def test_04_authentication_origin_and_strict_schedule_envelope_preserve_sources(self):
        before = self.snapshot()
        status, _ = self.request("GET", "/api/v1/backup/schedule", authenticated=False)
        self.assertEqual(status, 401)
        status, _ = self.request("GET", "/api/v1/backup/schedule", origin="https://invalid.example")
        self.assertEqual(status, 403)
        for body in ({}, {"enabled": False}, {"enabled": 0, "confirm": True},
                     {"enabled": False, "confirm": 1}, {"enabled": False, "confirm": False},
                     {"enabled": False, "confirm": True, "destination": "elsewhere"}):
            with self.subTest(body=body):
                status, response = self.request("POST", "/api/v1/backup/schedule", body)
                self.assertEqual(status, 400, response)
                self.assertIn("BACKUP_SCHEDULE_REQUEST_INVALID", json.dumps(response))
                self.assertEqual(self.snapshot(), before)

    def test_05_actual_get_exposes_failed_pump_without_private_text_or_writes(self):
        before = self.snapshot()
        pump = BackupSchedulePump(self.service.backup_schedule_tick)
        pump.failure = ValueError("TEST_ONLY-private-path-token-canary")
        with patch.object(self.service, "backup_pump", pump):
            status, body = self.request("GET", "/api/v1/backup/schedule")
            self.assertEqual(status, 200, body)
            self.assertEqual(body["engine_health"], "REVIEW_REQUIRED")
            self.assertEqual(body["pump_status"], "TICK_FAILED")
            self.assertIsNone(body["pump_health"])
            self.assertNotIn("TEST_ONLY-private-path-token-canary", json.dumps(body))
            self.assertEqual(self.snapshot(), before)
            self.assertFalse(pump.thread.is_alive())

    def test_06_actual_get_and_disable_ack_expose_unrecorded_health_failure(self):
        before = self.snapshot()
        pump = BackupSchedulePump(self.service.backup_schedule_tick)
        pump.failure = ValueError("TEST_ONLY-private-primary")
        pump.health_failure = OSError("TEST_ONLY-private-journal-failure")
        with patch.object(self.service, "backup_pump", pump):
            for method, payload in (("GET", None), ("POST", {"enabled": False, "confirm": True})):
                with self.subTest(method=method):
                    status, body = self.request(method, "/api/v1/backup/schedule", payload)
                    self.assertEqual(status, 200, body)
                    self.assertEqual(body["engine_health"], "REVIEW_REQUIRED")
                    self.assertEqual(body["pump_status"], "HEALTH_UNRECORDED")
                    self.assertEqual(body["journal_health"], "VALIDATED")
                    self.assertIsNone(body["pump_health"])
                    self.assertNotIn("TEST_ONLY-private", json.dumps(body))
                    self.assertEqual(self.snapshot(), before)
                    self.assertFalse(pump.thread.is_alive())