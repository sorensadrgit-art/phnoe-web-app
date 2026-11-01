"""Unit tests for live session ingestion, presets API, and motion persistence."""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from t6_server import make_server
from t6_service import IntegratedService


class LiveSessionApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()
        self.dist = self.root / "dist"
        self.dist.mkdir()
        (self.dist / "index.html").write_text("<title>KineLab PT | Live</title>", encoding="utf-8")
        self.samples = self.root / "samples"
        self.samples.mkdir()

        self.svc = IntegratedService(projects_root=self.root / "projects")
        self.token = "b" * 50
        self.server = make_server(self.svc, token=self.token, dist=self.dist, samples=self.samples, port=0)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.svc.close()
        self.thread.join(timeout=4)
        self.tmp.cleanup()

    def auth_headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Host": f"127.0.0.1:{self.port}",
            "Origin": f"http://127.0.0.1:{self.port}",
        }

    def request(self, method: str, path: str, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=6)
        payload = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body
        headers = self.auth_headers()
        if isinstance(body, dict):
            headers["Content-Type"] = "application/json"
        conn.request(method, path, payload, headers)
        resp = conn.getresponse()
        data = resp.read()
        status = resp.status
        conn.close()
        parsed = json.loads(data.decode("utf-8")) if data else {}
        return status, parsed

    def test_get_exercise_presets(self):
        status, data = self.request("GET", "/api/v1/exercises/presets")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        presets = data.get("presets", {})
        self.assertIn("squats", presets)
        self.assertIn("lunges", presets)
        self.assertIn("knee-extension", presets)
        self.assertIn("balance", presets)

        squat = presets["squats"]
        self.assertEqual(squat["name"], "Squat")
        self.assertEqual(squat["target_rom_deg"], 80)
        self.assertIn("fault_tolerances", squat)
        self.assertIn("max_trunk_lean", squat["fault_tolerances"])

    def test_save_live_session_validation(self):
        # Missing exercise_type
        status, data = self.request("POST", "/api/v1/sessions/live-set", {"reps": []})
        self.assertEqual(status, 409)
        self.assertFalse(data.get("ok"))
        self.assertIn("LIVE_ACQUISITION_UNVERIFIED", data.get("error", ""))

    def test_live_write_is_blocked_instead_of_creating_synthetic_motion(self):
        payload = {
            "session_id": "live-test-squat-01", "exercise_type": "squats",
            "patient_id": "PT-TEST-001", "reps": [{"valid": True}],
            "summary_metrics": {"totalReps": 1, "validReps": 1},
        }
        status, resp = self.request("POST", "/api/v1/sessions/live-set", payload)
        self.assertEqual(status, 409)
        self.assertIn("LIVE_ACQUISITION_UNVERIFIED", resp["error"])
        self.assertFalse((self.root / "projects" / payload["session_id"]).exists())

    def test_all_exercises_fail_closed_until_measured_acquisition(self):
        for etype in ["squats", "lunges", "knee-extension", "balance"]:
            sid = f"live-test-traj-{etype}"
            payload = {
                "session_id": sid, "exercise_type": etype,
                "reps": [{"valid": True}],
                "summary_metrics": {"totalReps": 1},
            }
            status, resp = self.request("POST", "/api/v1/sessions/live-set", payload)
            self.assertEqual(status, 409)
            self.assertIn("LIVE_ACQUISITION_UNVERIFIED", resp.get("error", ""))
            self.assertFalse((self.root / "projects" / sid).exists())


if __name__ == "__main__":
    unittest.main()
