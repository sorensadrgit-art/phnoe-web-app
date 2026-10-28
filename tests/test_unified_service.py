"""T6 local unified application: loopback/auth, fail-closed core, scoped workflow API."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from session_library import SessionLibrary
from unified_service import AppCore, make_server, AppError


class UnifiedServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        work=Path(self.tmp.name)
        self.projects=work/"projects";self.projects.mkdir()
        self.dist=work/"dist";self.dist.mkdir()
        (self.dist/"index.html").write_text("<!doctype html><title>KineLab PT | Motion Lab</title>")
        self.samples=work/"samples";self.samples.mkdir()
        self.lib=SessionLibrary(self.projects)
        self.real=self.lib.create_session("real-test")
        self.demo=self.lib.create_session("demo-test",kind="demo")
        (self.demo/"TEST-ONLY-NOT-CALIBRATED.txt").write_text("TEST ONLY")
        self.core=AppCore(self.projects,self.dist,self.samples,token="test-session-token")
        self.server=make_server(self.core,host="127.0.0.1",port=0)
        self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
        self.tmp.cleanup()

    def request(self,method,path,body=None,token="test-session-token",origin=None,host=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.port,timeout=7)
        hdr={"Host":host or f"127.0.0.1:{self.port}"}
        if token is not None:hdr["X-KineLab-Key"]=token
        if origin is not None:hdr["Origin"]=origin
        hdr.update(headers or {})
        if isinstance(body,dict):
            body=json.dumps(body).encode()
            hdr["Content-Type"]="application/json"
        conn.request(method,path,body=body,headers=hdr)
        rsp=conn.getresponse()
        raw=rsp.read()
        result=(rsp.status,dict(rsp.getheaders()),raw)
        conn.close()
        return result

    def payload(self,*args,**kwargs):
        status,headers,raw=self.request(*args,**kwargs)
        try:result=json.loads(raw)
        except (ValueError,UnicodeError):result=raw
        return status,headers,result

    def test_public_health_does_not_expose_file_paths_or_token(self):
        status,_,data=self.payload("GET","/api/health",token=None)
        self.assertEqual(status,200)
        self.assertEqual(data["app"],"KineLab PT")
        self.assertNotIn("test-session-token",json.dumps(data))
        self.assertNotIn(str(self.projects),json.dumps(data))

    def test_api_requires_secret_for_reads_and_mutations(self):
        for path in ("/api/sessions","/api/session?id=real-test","/api/research",
                     "/api/reports?id=real-test"):
            with self.subTest(path=path):
                status,*_=self.request("GET",path,token=None)
                self.assertEqual(status,403)
        status,*_=self.request("POST","/api/session/create",{"id":"forbidden"},token=None)
        self.assertEqual(status,403)
        self.assertFalse((self.projects/"forbidden").exists())

    def test_rejects_wrong_host_and_cross_origin_before_processing(self):
        status,*_=self.request("GET","/api/sessions",host="evil.example:3000")
        self.assertEqual(status,403)
        status,*_=self.request("POST","/api/session/create",{"id":"evil"},
                               origin="https://evil.example")
        self.assertEqual(status,403)
        self.assertFalse((self.projects/"evil").exists())

    def test_sessions_are_sanitized_and_sample_cannot_register(self):
        status,_,data=self.payload("GET","/api/sessions")
        self.assertEqual(status,200)
        names={entry["id"]:entry for entry in data["sessions"]}
        self.assertEqual(names["demo-test"]["kind"],"test-only")
        self.assertFalse(names["demo-test"]["can_register"])
        self.assertNotIn("path",names["real-test"])
        self.assertNotIn(str(self.projects),json.dumps(data))
        status,_,result=self.payload("POST","/api/session/register",
                                     {"id":"demo-test","confirmed":True})
        self.assertEqual(status,409)
        self.assertIn("test",json.dumps(result).lower())
        self.assertFalse((self.demo/"session.json").exists())

    def test_session_create_and_reopen_existing_without_overwrite(self):
        status,_,data=self.payload("POST","/api/session/create",{"id":"new-real"})
        self.assertEqual(status,201)
        self.assertEqual(data["session"]["id"],"new-real")
        self.assertEqual(data["session"]["status"],"draft")
        status,_,again=self.payload("POST","/api/session/create",{"id":"new-real"})
        self.assertEqual(status,409)
        self.assertTrue((self.projects/"new-real"/"Config.toml").is_file())

    def test_path_traversal_and_unsupported_endpoints_never_read_files(self):
        for url in ("/api/session?id=../../outside", "/api/report?id=real-test&file=../raw/cam01_trial.mp4",
                    "/api/report?id=real-test&file=C:%5CWindows", "/api/unknown"):
            with self.subTest(url=url):
                status,*_=self.request("GET",url)
                self.assertIn(status,(400,404,409))
        status,*_=self.request("GET","/projects/real-test/raw/cam01_trial.mp4")
        self.assertEqual(status,404)

    def test_actual_draft_readiness_refuses_registration_and_job_start(self):
        status,_,s=self.payload("GET","/api/session?id=real-test")
        self.assertEqual(status,200)
        self.assertEqual(s["detail"]["captured_roles"],0)
        status,_,r=self.payload("GET","/api/readiness?id=real-test")
        self.assertEqual(status,200)
        self.assertFalse(r["readiness"]["ready_to_register"])
        self.assertEqual(len(r["readiness"]["missing"]),6)
        status,*_=self.request("POST","/api/job/start",
                                {"id":"real-test","action":"normalize","confirmed":True})
        self.assertEqual(status,409)
        self.assertFalse((self.real/"workflow.lock").exists())

    def test_source_files_can_be_uploaded_only_with_real_recording_checks(self):
        status,*_=self.request("POST","/api/upload?id=demo-test&role=cam01_trial",
                                body=b"fakevideo",headers={"Content-Type":"video/mp4",
                                                           "X-KineLab-Confirm":"yes"})
        self.assertEqual(status,409)
        status,*_=self.request("POST","/api/upload?id=real-test&role=../../escape",
                                body=b"fakevideo",headers={"Content-Type":"video/mp4",
                                                           "X-KineLab-Confirm":"yes"})
        self.assertIn(status,(400,409))
        self.assertFalse((self.real/"raw"/"cam01_trial.mp4").exists())
        status,*_=self.request("POST","/api/upload?id=real-test&role=cam01_trial",
                                body=b"garbage",headers={"Content-Type":"video/mp4"})
        self.assertIn(status,(400,409))

    def test_locks_and_samples_cannot_be_rewritten_from_report_route(self):
        (self.real/"run.lock").write_text("123")
        status,*_=self.request("GET","/api/report?id=real-test&file=run.lock")
        self.assertEqual(status,400)
        status,*_=self.request("GET","/api/report?id=real-test&file=cam01_trial.mp4")
        self.assertEqual(status,400)
        self.assertEqual((self.real/"run.lock").read_text(),"123")

    def test_denies_unconfirmed_webcam_and_board_actions(self):
        status,*_=self.request("POST","/api/record/start",{
            "id":"real-test","role":"cam02_trial","seconds":10,"confirmed":False})
        self.assertEqual(status,409)
        status,*_=self.request("POST","/api/board",{
            "id":"real-test","measured_square_mm":20,"operator":"PT","confirmed":False})
        self.assertEqual(status,409)
        self.assertFalse((self.real/"board-measurement.json").exists())

    def test_research_route_never_serves_user_recordings(self):
        status,*_=self.request("GET","/research/gait-t5/index.html")
        self.assertEqual(status,404)
        status,*_=self.request("GET","/research/../../projects/real-test/raw/cam01_trial.mp4")
        self.assertEqual(status,404)

    def test_strict_range_and_static_site(self):
        status,headers,data=self.request("GET","/")
        self.assertEqual(status,200)
        self.assertIn(b"KineLab PT",data)
        self.assertEqual(headers.get("X-Content-Type-Options"),"nosniff")
        self.assertIn("Content-Security-Policy",headers)
        status,*_=self.request("GET","/.env")
        self.assertEqual(status,404)

    def test_squat_analysis_requires_operator_confirmation_and_test_only_input(self):
        status,*_=self.request("POST","/api/squat/analyze",
                               {"activity_confirmed":False,"camera_view":"side",
                                "evidence":{},"source_sha256":"a"*64,"role":"cam01_trial"})
        self.assertEqual(status,409)
        self.assertFalse((self.real/"squat-events.json").exists())


if __name__=="__main__":
    unittest.main()
