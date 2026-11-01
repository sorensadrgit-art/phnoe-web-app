"""T6 local service HTTP security, API routing, and no unsafe static paths."""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from t6_server import make_server
from t6_service import IntegratedService


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/"projects").mkdir()
        self.dist=self.root/"dist"
        self.dist.mkdir()
        (self.dist/"index.html").write_text("<title>KineLab PT | Unified</title>")
        (self.dist/"assets").mkdir()
        (self.dist/"assets"/"bundle.js").write_text("window.KINELAB=true;")
        self.sample=self.root/"sample"
        (self.root/"TEST-ONLY-NOT-CALIBRATED.txt").write_text("TEST-ONLY")
        (self.sample/"gait-t5").mkdir(parents=True)
        (self.sample/"gait-t5"/"index.html").write_text("<h1>TEST ONLY</h1>")
        (self.sample/"gait-t5"/"gait-t5-summary.json").write_text('{"status":"UNVALIDATED"}')
        (self.sample/"pose2d-fullseq").mkdir()
        (self.sample/"pose2d-fullseq"/"cam01_trial_tracked.mp4").write_bytes(b"x"*120)
        self.svc=IntegratedService(projects_root=self.root/"projects")
        self.server=make_server(self.svc,token="a"*50,dist=self.dist,samples=self.sample,port=0)
        self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.svc.close()
        self.thread.join(timeout=4)
        self.tmp.cleanup()

    def request(self,method,path,body=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.port,timeout=6)
        payload=json.dumps(body).encode() if isinstance(body,dict) else body
        base={"Host":f"127.0.0.1:{self.port}"}
        if isinstance(body,dict):base["Content-Type"]="application/json"
        base.update(headers or {})
        conn.request(method,path,payload,base)
        r=conn.getresponse()
        data=r.read()
        status=r.status
        out=dict(r.getheaders())
        conn.close()
        return status,data,out

    def auth(self):
        return {"Authorization":"Bearer "+"a"*50,
                "Origin":f"http://127.0.0.1:{self.port}"}

    def test_confirmed_camera_and_native_capture_remain_blocked(self):
        from unittest.mock import patch
        self.svc.create_session('capture-blocked')
        with patch('t6_service.subprocess.Popen') as process:
            for action, data in [('capture', {'role': 'cam02_trial', 'seconds': 12}),
                                 ('open', {'target': 'capture'})]:
                code, body, _ = self.request('POST', '/api/v1/sessions/capture-blocked/' + action,
                    {**data, 'confirm': True}, self.auth())
                self.assertEqual(code, 409, body)
                self.assertIn(b'PARTICIPANT_RECORDING_BLOCKED', body)
            process.assert_not_called()

    def test_ephemeral_pose_endpoint_obeys_auth_bounds_and_does_not_save(self):
        from unittest.mock import patch

        from test_pose_inference import request
        endpoint = '/api/v1/inference/frame'
        payload = request()
        self.assertEqual(self.request('POST', endpoint, payload)[0], 401)
        self.assertEqual(self.request('POST', endpoint, payload, {**self.auth(), 'Origin': 'https://example.invalid'})[0], 403)
        self.assertEqual(self.request('POST', endpoint, {**payload, 'extra': 'x'*70000}, self.auth())[0], 413)
        with patch('pose_inference.PoseInference._load', side_effect=FileNotFoundError):
            code, body, _ = self.request('POST', endpoint, payload, self.auth())
        self.assertEqual(code, 200, body)
        self.assertEqual(json.loads(body)['reason'], 'MODELS_UNAVAILABLE')
        self.assertEqual(self.svc.sessions(), [])
        self.assertEqual(self.request('POST', endpoint, {}, self.auth())[0], 409)

    def test_incremental_synthetic_recording_exceeds_bulk_limit_without_larger_requests(self):
        from recording_contract import canonical_json, digest
        from test_recording_contract import frame, header
        from test_recording_store import chunk
        data = header(); endpoint = "/api/v1/recordings"
        status, body, _ = self.request("POST", endpoint, data, self.auth())
        self.assertEqual(status, 201, body)
        sid = data["session_id"]; total = 0
        for start in range(1, 129, 16):
            frames = [frame(i, (i - 1) * 30) for i in range(start, start + 16)]
            payload = chunk(start); payload.update(frames_json=canonical_json(frames), sha256=digest(frames))
            length = len(json.dumps(payload).encode()); total += length
            self.assertLess(length, 64 * 1024)
            status, body, _ = self.request("POST", endpoint + "/" + sid + "/chunks", payload, self.auth())
            self.assertEqual(status, 200, body)
            self.assertEqual(json.loads(body)["saved_through"], start + 15)
        self.assertGreater(total, 64 * 1024)
        status, body, _ = self.request("POST", endpoint + "/" + sid + "/finalize",
            {"operation_id": data["operation_id"], "last_sequence": 128}, self.auth())
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["manifest"]["frame_count"], 128)
        status, body, _ = self.request("GET", endpoint + "/" + sid, headers=self.auth())
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["state"], "FINALIZED")
        self.assertFalse((self.root / "projects" / sid).exists())
        status, body, _ = self.request("GET", endpoint, headers=self.auth())
        self.assertEqual(json.loads(body)["recordings"][0]["source_kind"], "synthetic")

    def test_recording_api_retains_auth_source_and_identity_boundaries(self):
        from test_recording_contract import header
        for method in ("GET", "POST"):
            status, _, _ = self.request(method, "/api/v1/recordings", header() if method == "POST" else None)
            self.assertEqual(status, 401)
        data = header(); data["source"]["kind"] = "camera"
        status, body, _ = self.request("POST", "/api/v1/recordings", data, self.auth())
        self.assertEqual(status, 409, body)
        self.assertEqual(self.svc.index.conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 0)
        self.request("POST", "/api/v1/recordings", header(), self.auth())
        status, body, _ = self.request("POST", "/api/v1/sessions", {"id": header()["session_id"]}, self.auth())
        self.assertEqual(status, 409, body)
        self.assertFalse((self.root / "projects" / header()["session_id"]).exists())

    def test_recording_storage_failure_returns_no_saved_ack(self):
        import sqlite3
        from unittest.mock import patch

        from test_recording_contract import header
        with patch.object(self.svc.index, "_append_audit", side_effect=sqlite3.OperationalError("disk full")):
            status, body, _ = self.request("POST", "/api/v1/recordings", header(), self.auth())
        self.assertEqual(status, 503, body)
        self.assertNotIn("saved_through", json.loads(body))
        self.assertEqual(self.svc.index.conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 0)

    def test_ambiguous_or_nonfinite_json_rejected_before_creating_session(self):
        for payload in (b'{"id":"strict-a","id":"strict-b"}',
                        b'{"id":"strict-a","ignored":NaN}',
                        b'{"id":"strict-a","ignored":1e999}'):
            with self.subTest(payload=payload):
                status, _, _ = self.request("POST", "/api/v1/sessions", payload,
                    {**self.auth(), "Content-Type": "application/json"})
                self.assertEqual(status, 409)
                self.assertFalse((self.root/"projects"/"strict-a").exists())
                self.assertFalse((self.root/"projects"/"strict-b").exists())

    def test_no_auth_denied_even_from_localhost_and_no_cors_open(self):
        status,_,headers=self.request("GET","/api/v1/sessions")
        self.assertEqual(status,401)
        self.assertNotIn("Access-Control-Allow-Origin",headers)
        status,_,_=self.request("GET","/api/v1/sessions",headers=self.auth())
        self.assertEqual(status,200)

    def test_foreign_origin_and_wrong_host_cannot_write(self):
        status,_,_=self.request("POST","/api/v1/sessions",
             {"id":"foreign"},headers={**self.auth(),"Origin":"https://example.org"})
        self.assertEqual(status,403)
        self.assertFalse((self.root/"projects"/"foreign").exists())
        status,_,_=self.request("POST","/api/v1/sessions",
             {"id":"badhost"},headers={**self.auth(),"Host":"evil.local"})
        self.assertIn(status,(400,403))
        self.assertFalse((self.root/"projects"/"badhost").exists())

    def test_authenticated_session_creation_and_status_refuses_incomplete_registration(self):
        status,data,_=self.request("POST","/api/v1/sessions",
                                   {"id":"session-one"},headers=self.auth())
        self.assertEqual(status,201,data)
        status,data,_=self.request("GET","/api/v1/sessions/session-one",headers=self.auth())
        info=json.loads(data)
        self.assertEqual(info["captured_roles"],0)
        self.assertEqual(len(info["roles"]),6)
        self.assertFalse(info["ready_to_register"])
        status,_,_=self.request("POST","/api/v1/sessions/session-one/register",
                                  {"confirm":True},headers=self.auth())
        self.assertEqual(status,409)
        self.assertFalse((self.root/"projects"/"session-one"/"session.json").exists())

    def test_http_path_traversal_and_unsafe_sources_denied(self):
        for path in ("/.venv/Scripts/python.exe","/../secrets.txt",
                     "/samples/../index.html","/samples/../../private.txt",
                     "/api/v1/sessions/%2e%2e","/samples/gait-t5/private.key"):
            with self.subTest(path=path):
                status,_,_=self.request("GET",path)
                self.assertIn(status,(400,401,403,404))
        status,data,_=self.request("GET","/samples/gait-t5/index.html")
        self.assertEqual(status,200)
        self.assertIn(b"TEST ONLY",data)

    def test_byte_range_video_playback_is_bounded_and_read_only(self):
        video="/samples/pose2d-fullseq/cam01_trial_tracked.mp4"
        status,data,headers=self.request("GET",video,headers={"Range":"bytes=3-12"})
        self.assertEqual(status,206)
        self.assertEqual(len(data),10)
        self.assertEqual(headers.get("Content-Range"),"bytes 3-12/120")
        status,_,_=self.request("GET",video,headers={"Range":"bytes=1000-2000"})
        self.assertEqual(status,416)

    def test_rejects_oversize_json_and_non_json_mutations(self):
        status,_,_=self.request("POST","/api/v1/sessions",b"X"*70000,
                                 headers={**self.auth(),"Content-Type":"application/json"})
        self.assertEqual(status,413)
        status,_,_=self.request("POST","/api/v1/sessions",b"no-json",
                                 headers={**self.auth(),"Content-Type":"text/plain"})
        self.assertEqual(status,415)

    def test_actual_phone_mp4_upload_is_source_safe_and_non_overwriting(self):
        import hashlib
        import subprocess
        source=self.root/"valid-source.mp4"
        subprocess.run([
            "ffmpeg","-hide_banner","-loglevel","error","-f","lavfi",
            "-i","color=c=black:s=320x240:r=30:d=1",
            "-c:v","libx264","-pix_fmt","yuv420p","-f","mp4",str(source),
        ],capture_output=True,check=True,timeout=20)
        data=source.read_bytes()
        self.svc.create_session("upload-a")
        route="/api/v1/sessions/upload-a/import/cam01_board"
        status,_,_=self.request("POST",route,data,headers={
            **self.auth(),"Content-Type":"video/mp4"})
        self.assertEqual(status,409)  # Must explicitly consent.
        self.assertFalse((self.root/"projects"/"upload-a"/"raw"/"cam01_board.mp4").exists())
        status,result,_=self.request("POST",route,data,headers={
            **self.auth(),"Content-Type":"video/mp4","X-KineLab-Consent":"yes"})
        self.assertEqual(status,201,result)
        stored=self.root/"projects"/"upload-a"/"raw"/"cam01_board.mp4"
        self.assertEqual(hashlib.sha256(stored.read_bytes()).hexdigest(),
                         hashlib.sha256(data).hexdigest())
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         hashlib.sha256(data).hexdigest())
        status,_,_=self.request("POST",route,data,headers={
            **self.auth(),"Content-Type":"video/mp4","X-KineLab-Consent":"yes"})
        self.assertEqual(status,409)
        self.assertEqual(stored.read_bytes(),data)

    def test_participant_trial_upload_refused_before_staging(self):
        self.svc.create_session("upload-trial")
        project=self.root/"projects"/"upload-trial"
        before=sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))
        data=b"generated-not-participant-footage"
        route="/api/v1/sessions/upload-trial/import/cam01_trial"
        for headers in ({**self.auth(),"Content-Type":"video/mp4","X-KineLab-Consent":"yes"},
                        {**self.auth(),"Content-Type":"video/mp4"}):
            status,body,_=self.request("POST",route,data,headers=headers)
            self.assertEqual(status,409)
            self.assertIn(b"PARTICIPANT_RECORDING_BLOCKED",body)
        self.assertFalse((project/"raw"/"cam01_trial.mp4").exists())
        self.assertFalse((project/"import-staging").exists())
        self.assertEqual(sorted(p.relative_to(project).as_posix() for p in project.rglob("*")),before)

    def test_report_download_requires_bearer_and_exact_named_file(self):
        self.svc.create_session("download-a")
        project=self.root/"projects"/"download-a"
        (project/"preflight.json").write_text('{"status":"not a pass"}',encoding="utf-8")
        url="/api/v1/sessions/download-a/artifact/preflight.json"
        code,_,_=self.request("GET",url)
        self.assertEqual(code,401)
        code,body,headers=self.request("GET",url,headers=self.auth())
        self.assertEqual(code,200)
        self.assertIn(b"not a pass",body)
        self.assertIn("attachment",headers.get("Content-Disposition",""))
        code,_,_=self.request("GET","/api/v1/sessions/download-a/artifact/secret.txt",
                              headers=self.auth())
        self.assertEqual(code,409)

    def test_open_api_contains_no_clinical_success_on_test_only(self):
        self.svc.library.create_session("smoke",kind="demo")
        status,data,_=self.request("GET","/api/v1/sessions/smoke",headers=self.auth())
        self.assertEqual(status,200)
        body=json.loads(data)
        self.assertFalse(body["ready_to_register"])
        self.assertNotEqual(body["kind"],"real")

    def test_concurrent_uploads_preserve_first_and_reject_second(self):
        import hashlib
        import subprocess
        source=self.root/"valid-source-concurrent.mp4"
        subprocess.run([
            "ffmpeg","-hide_banner","-loglevel","error","-f","lavfi",
            "-i","color=c=black:s=320x240:r=30:d=1",
            "-c:v","libx264","-pix_fmt","yuv420p","-f","mp4",str(source),
        ],capture_output=True,check=True,timeout=20)
        valid_data=source.read_bytes()
        self.svc.create_session("upload-concurrent")
        route="/api/v1/sessions/upload-concurrent/import/cam01_board"

        results=[]
        def do_upload(payload):
            st,body,_=self.request("POST",route,payload,headers={
                **self.auth(),"Content-Type":"video/mp4","X-KineLab-Consent":"yes"})
            results.append((st,body))

        t1=threading.Thread(target=do_upload,args=(valid_data,))
        t2=threading.Thread(target=do_upload,args=(valid_data,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        statuses=[r[0] for r in results]
        self.assertIn(201, statuses)
        self.assertIn(409, statuses)
        stored=self.root/"projects"/"upload-concurrent"/"raw"/"cam01_board.mp4"
        self.assertTrue(stored.is_file())
        self.assertEqual(hashlib.sha256(stored.read_bytes()).hexdigest(),
                         hashlib.sha256(valid_data).hexdigest())
        staging=self.root/"projects"/"upload-concurrent"/"import-staging"
        if staging.exists():
            self.assertEqual(list(staging.glob("*.mp4")), [])

    def test_dns_rebinding_and_evil_host_rejected(self):
        for evil in ("127.0.0.1.attacker.com", "evil.com", "localhost", "192.168.1.5", f"127.0.0.1:{self.port}.attacker.com"):
            with self.subTest(host=evil):
                st,_body,_=self.request("GET","/api/v1/sessions",headers={**self.auth(),"Host":evil})
                self.assertIn(st,(400,403))

    def test_artifact_traversal_attempts_refused(self):
        self.svc.create_session("trav-a")
        for bad_key in ("..%2fConfig.toml", "..%5cConfig.toml", "session.json%00"):
            with self.subTest(key=bad_key):
                st,_,_=self.request("GET",f"/api/v1/sessions/trav-a/artifact/{bad_key}",headers=self.auth())
                self.assertIn(st,(404,409))

    def test_token_never_reflected_in_errors(self):
        token_str="a"*50
        _st,body,_=self.request("POST","/api/v1/sessions/nonexistent/register",{"confirm":True},headers=self.auth())
        self.assertNotIn(token_str.encode(), body)
        _st,body,_=self.request("GET","/api/v1/nonexistent",headers=self.auth())
        self.assertNotIn(token_str.encode(), body)

    def test_passport_and_comparison_http_endpoints(self):
        self.svc.create_session("http-s1")
        self.svc.create_session("http-s2")
        st,data,_ = self.request("GET", "/api/v1/sessions/http-s1/passport", headers=self.auth())
        self.assertEqual(st, 200)
        p1 = json.loads(data)
        self.assertEqual(p1["session_id"], "http-s1")
        self.assertEqual(p1["state"], "EMPTY")

        st,data,_ = self.request("GET", "/api/v1/compare?s1=http-s1&s2=http-s2", headers=self.auth())
        self.assertEqual(st, 200)
        comp = json.loads(data)
        self.assertFalse(comp["compatible"])
        self.assertIn("Insufficient verified reconstruction evidence", comp["reason"])

    def test_report_generation_and_download_http_workflow(self):
        self.svc.create_session("http-rep")
        st,data,_ = self.request("POST", "/api/v1/sessions/http-rep/reports/generate", {"confirm": True}, headers=self.auth())
        self.assertEqual(st, 201)
        res = json.loads(data)
        self.assertTrue(res["ok"])

        # Check artifact download of generated PDF
        pdf_key = next(item['key'] for item in self.svc.reports('http-rep')
                       if item['filename'] == 'http-rep-research-report.pdf')
        st,pdf_bytes,headers = self.request("GET", f"/api/v1/sessions/http-rep/artifact/{pdf_key}", headers=self.auth())
        self.assertEqual(st, 200)
        self.assertEqual(headers.get("Content-Type"), "application/pdf")
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_backup_and_restore_http_endpoints(self):
        self.svc.create_session("http-bk")
        st,data,_ = self.request("POST", "/api/v1/backup/create", {"confirm": True, "session_ids": ["http-bk"]}, headers=self.auth())
        self.assertEqual(st, 201)
        b_res = json.loads(data)
        self.assertTrue(b_res["ok"])
        bk_file = b_res["backup_file"]

        st,data,_ = self.request("GET", "/api/v1/backups", headers=self.auth())
        self.assertEqual(st, 200)
        backups = json.loads(data).get("backups", [])
        self.assertTrue(any(b["filename"] == bk_file for b in backups))

        original = self.svc._project("http-bk")
        before = (original / "Config.toml").read_bytes()
        st,data,_ = self.request("POST", "/api/v1/backup/restore", {"confirm": True, "backup_name": bk_file, "overwrite": True}, headers=self.auth())
        self.assertEqual(st, 409)
        self.assertIn("RESTORE_OVERWRITE_UNAVAILABLE", json.loads(data)["error"])
        self.assertEqual((original / "Config.toml").read_bytes(), before)
        active_db = self.svc.index.db_path.read_bytes()
        st,data,_ = self.request("POST", "/api/v1/backup/restore", {"confirm": True, "backup_name": bk_file, "overwrite": False}, headers=self.auth())
        self.assertEqual(st, 200)
        r_res = json.loads(data)
        self.assertTrue(r_res["ok"])
        self.assertTrue(r_res["database_restored"])
        self.assertFalse(r_res["active_workspace_changed"])
        recovered = self.svc.projects_root / r_res["recovery_directory"]
        self.assertTrue((recovered / ".kinelab_index.db").is_file())
        self.assertEqual((recovered / "http-bk/Config.toml").read_bytes(), before)
        self.assertEqual(self.svc.index.db_path.read_bytes(), active_db)
        self.assertEqual((original / "Config.toml").read_bytes(), before)

    def test_session_motion_endpoint(self):
        self.svc.create_session("http-mot")
        session_folder = self.svc._project("http-mot")
        exports_dir = session_folder / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        motion_file = exports_dir / "http-mot.motion.json"
        from export_motion import motion
        from native_evidence_fixture import complete_native_fixture
        from session_contract import ROLES
        from setup_project import register_captures
        from test_export_motion import trc_text
        for role in ROLES:
            (session_folder / "raw" / (role + ".mp4")).write_bytes(("generated " + role).encode())
        register_captures(session_folder, "http-mot", "real")
        manifest, trc, _ = complete_native_fixture(session_folder, trc_text())
        document = motion(trc, run_manifest=manifest)
        motion_file.write_text(json.dumps(document), encoding="utf-8")

        st, data, _ = self.request("GET", "/api/v1/sessions/http-mot/motion", headers=self.auth())
        self.assertEqual(st, 200)
        mot = json.loads(data)
        self.assertEqual(mot.get("schema"), "kinelab.motion.v2")
        document["frames"][0]["xyz"][0][0] += 1
        motion_file.write_text(json.dumps(document), encoding="utf-8")
        st, _, _ = self.request("GET", "/api/v1/sessions/http-mot/motion", headers=self.auth())
        self.assertEqual(st, 409)

        # Session without motion returns 409
        self.svc.create_session("http-no-mot")
        st, _, _ = self.request("GET", "/api/v1/sessions/http-no-mot/motion", headers=self.auth())
        self.assertEqual(st, 409)

    def test_system_shutdown_endpoint(self):
        # Unconfirmed shutdown returns 400
        st, _, _ = self.request("POST", "/api/v1/system/shutdown", {}, headers=self.auth())
        self.assertEqual(st, 400)

        # Confirmed shutdown returns 200
        st, data, _ = self.request("POST", "/api/v1/system/shutdown", {"confirm": True}, headers=self.auth())
        self.assertEqual(st, 200)
        res = json.loads(data)
        self.assertEqual(res.get("status"), "shutting_down")


if __name__=="__main__":
    unittest.main()
