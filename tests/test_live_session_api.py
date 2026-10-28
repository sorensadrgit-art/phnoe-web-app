"""Unit tests for live session ingestion, presets API, and motion persistence."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

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
        self.assertIn("exercise_type is required", data.get("error", ""))

    def test_save_live_session_success_and_motion_query(self):
        payload = {
            "session_id": "live-test-squat-01",
            "exercise_type": "squats",
            "patient_id": "PT-TEST-001",
            "reps": [
                {
                    "repNumber": 1,
                    "durationMs": 1400,
                    "peakDepth": 84.5,
                    "targetDepth": 80,
                    "minSymmetry": 92.0,
                    "valid": True,
                    "faults": [],
                },
                {
                    "repNumber": 2,
                    "durationMs": 1300,
                    "peakDepth": 88.0,
                    "targetDepth": 80,
                    "minSymmetry": 78.0,
                    "valid": False,
                    "faults": ["KNEE_VALGUS"],
                },
            ],
            "summary_metrics": {
                "totalReps": 2,
                "validReps": 1,
                "averageDepth": 86.2,
                "bestDepth": 88.0,
                "targetDepth": 80,
                "averageSymmetry": 85.0,
                "durationSeconds": 15,
                "faultsLog": [{"fault": "KNEE_VALGUS", "count": 1, "percentage": 50}],
            },
        }

        status, resp = self.request("POST", "/api/v1/sessions/live-set", payload)
        self.assertEqual(status, 201)
        self.assertTrue(resp.get("ok"))
        self.assertEqual(resp.get("session_id"), "live-test-squat-01")
        self.assertEqual(resp.get("total_reps"), 2)
        self.assertEqual(resp.get("valid_reps"), 1)

        # Check folder structure created on disk
        session_folder = self.root / "projects" / "live-test-squat-01"
        self.assertTrue(session_folder.is_dir())
        self.assertTrue((session_folder / "Config.toml").is_file())
        self.assertTrue((session_folder / "session.json").is_file())
        self.assertTrue((session_folder / "live_telemetry.json").is_file())

        motion_file = session_folder / "exports" / "live-test-squat-01.motion.json"
        self.assertTrue(motion_file.is_file())
        motion_data = json.loads(motion_file.read_text(encoding="utf-8"))
        self.assertEqual(motion_data.get("schema"), "kinelab.motion.v1")
        self.assertEqual(motion_data.get("coordinateSystem"), "opensim_y_up")
        self.assertTrue(len(motion_data.get("frames", [])) > 0)

        csv_file = session_folder / "exports" / "live-test-squat-01-metrics.csv"
        self.assertTrue(csv_file.is_file())
        csv_text = csv_file.read_text(encoding="utf-8")
        self.assertIn("rep_number,duration_ms", csv_text)
        self.assertIn("KNEE_VALGUS", csv_text)

        # Verify motion endpoint serves the generated motion JSON
        m_status, m_resp = self.request("GET", "/api/v1/sessions/live-test-squat-01/motion")
        self.assertEqual(m_status, 200)
        self.assertEqual(m_resp.get("schema"), "kinelab.motion.v1")

        # Verify session listing includes the live session
        s_status, s_resp = self.request("GET", "/api/v1/sessions")
        self.assertEqual(s_status, 200)
        sessions = s_resp.get("sessions", [])
        live_sess = next((s for s in sessions if s.get("id") == "live-test-squat-01"), None)
        self.assertIsNotNone(live_sess)
        self.assertEqual(live_sess.get("kind"), "live")
        self.assertEqual(live_sess.get("status"), "completed")


if __name__ == "__main__":
    unittest.main()
