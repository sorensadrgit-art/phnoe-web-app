"""T6 integrated local service must delegate to already tested KineLab guards."""
from __future__ import annotations
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from t6_service import IntegratedService, IntegrationBlocked
from session_contract import ROLES


class T6ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "projects").mkdir()
        self.service = IntegratedService(projects_root=self.root / "projects")

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_empty_library_lists_without_creating_real_files(self):
        self.assertEqual(self.service.sessions(), [])
        self.assertFalse((self.root / "projects" / "session.json").exists())

    def test_create_choose_and_inspect_two_sessions(self):
        a=self.service.create_session("t6-capture-a")
        b=self.service.create_session("t6-capture-b")
        self.assertEqual(a["id"],"t6-capture-a")
        self.assertEqual(b["id"],"t6-capture-b")
        self.assertEqual(len(self.service.sessions()),2)
        detail=self.service.session_detail("t6-capture-a")
        self.assertEqual(detail["captured_roles"],0)
        self.assertEqual(len(detail["roles"]),6)
        self.assertFalse(detail["ready_to_register"])
        self.assertFalse((self.root/"projects"/"t6-capture-a"/"session.json").exists())

    def test_test_only_sample_never_registers_or_mutates(self):
        self.service.create_session("external-sample")
        folder=self.root/"projects"/"external-sample"
        (folder/"SAMPLE-PROVENANCE.json").write_text("{}")
        detail=self.service.session_detail("external-sample")
        self.assertEqual(detail["kind"],"test-only")
        self.assertFalse(detail["can_register"])
        with self.assertRaises((IntegrationBlocked,ValueError)):
            self.service.register("external-sample",confirm=True)
        self.assertFalse((folder/"session.json").exists())

    def test_registration_requires_explicit_confirmation_and_six_roles(self):
        self.service.create_session("incomplete")
        with self.assertRaisesRegex(IntegrationBlocked,"confirm"):
            self.service.register("incomplete",confirm=False)
        with self.assertRaises((IntegrationBlocked,ValueError)):
            self.service.register("incomplete",confirm=True)

    def test_webcam_rejects_test_only_existing_files_and_no_consent(self):
        self.service.create_session("webcam")
        with self.assertRaisesRegex(IntegrationBlocked,"consent"):
            self.service.record_webcam("webcam","cam02_trial",seconds=12,confirm=False)
        with self.assertRaisesRegex((IntegrationBlocked,ValueError),"webcam|role|cam02"):
            self.service.record_webcam("webcam","cam01_trial",seconds=12,confirm=True)
        project=self.root/"projects"/"webcam"
        (project/"raw"/"cam02_trial.mp4").write_bytes(b"existing")
        with self.assertRaises((FileExistsError,ValueError)):
            self.service.record_webcam("webcam","cam02_trial",seconds=12,confirm=True)
        self.assertEqual((project/"raw"/"cam02_trial.mp4").read_bytes(),b"existing")

    def test_incomplete_session_rejects_processing_and_no_job_side_effect(self):
        self.service.create_session("unregistered")
        with self.assertRaisesRegex(IntegrationBlocked,"confirm"):
            self.service.start_processing("unregistered","normalize",confirm=False)
        with self.assertRaises((IntegrationBlocked,ValueError)):
            self.service.start_processing("unregistered","normalize",confirm=True)
        self.assertFalse((self.root/"projects"/"unregistered"/"workflow.lock").exists())

    def test_safe_report_listing_never_lists_arbitrary_project_files(self):
        self.service.create_session("reports")
        project=self.root/"projects"/"reports"
        (project/"secret.txt").write_text("sensitive")
        (project/"preflight.json").write_text("{}")
        (project/"exports").mkdir(exist_ok=True)
        (project/"exports"/"approved.motion.json").write_text("{}")
        files=self.service.reports("reports")
        self.assertIn("preflight.json",[i["filename"] for i in files])
        self.assertIn("approved.motion.json",[i["filename"] for i in files])
        self.assertNotIn("secret.txt",[i["filename"] for i in files])
        with self.assertRaises((IntegrationBlocked,ValueError,FileNotFoundError)):
            self.service.artifact("reports","../secret.txt")

    def test_existing_legacy_and_demo_present_but_not_marked_real(self):
        self.service.library.create_session("demo-a",kind="demo")
        sample=self.service.session_detail("demo-a")
        self.assertEqual(sample["kind"],"demo")
        with self.assertRaises((IntegrationBlocked,ValueError)):
            self.service.record_webcam("demo-a","cam02_board",seconds=10,confirm=True)

    def test_only_allow_explicit_native_capture_open_request(self):
        self.service.create_session("cam-a")
        with patch("t6_service.subprocess.Popen") as popen:
            self.service.open_native("cam-a","capture",confirm=True)
            argv=popen.call_args.args[0]
            self.assertIn("capture_station_gui.py", " ".join(argv))
            self.assertIn("cam-a", argv)
        with self.assertRaises((IntegrationBlocked,ValueError)):
            self.service.open_native("cam-a","unknown",confirm=True)

    def test_passport_and_comparison_apis(self):
        self.service.create_session("pass-1")
        self.service.create_session("pass-2")
        p1 = self.service.passport("pass-1")
        self.assertEqual(p1["session_id"], "pass-1")
        self.assertEqual(p1["state"], "EMPTY")
        self.assertEqual(len(p1["missing_roles"]), 6)
        comp = self.service.compare("pass-1", "pass-2")
        self.assertTrue(comp["compatible"])

    def test_generate_reports_and_artifacts(self):
        self.service.create_session("rep-gen")
        res = self.service.generate_reports("rep-gen", confirm=True)
        self.assertTrue(res["ok"])
        self.assertIn("rep-gen-research-report.pdf", res["generated"])
        reps = self.service.reports("rep-gen")
        filenames = [r["filename"] for r in reps]
        self.assertIn("rep-gen-research-report.pdf", filenames)
        self.assertIn("rep-gen-metrics.csv", filenames)
        self.assertIn("rep-gen-research-summary.json", filenames)

    def test_backup_and_restore_workflow(self):
        self.service.create_session("bk-sess")
        b_res = self.service.create_backup(confirm=True, session_ids=["bk-sess"])
        self.assertTrue(b_res["ok"])
        bk_file = b_res["backup_file"]
        backups = self.service.backups()
        self.assertTrue(any(b["filename"] == bk_file for b in backups))
        # Restore with overwrite
        r_res = self.service.restore_backup(bk_file, confirm=True, overwrite=True)
        self.assertTrue(r_res["ok"])

    def test_session_metadata_never_exposes_user_windows_filesystem_paths(self):
        self.service.create_session("private-pilot")
        listing=self.service.sessions()
        detail=self.service.session_detail("private-pilot")
        self.assertEqual(listing[0]["id"],"private-pilot")
        self.assertNotIn("path",listing[0])
        self.assertNotIn("path",detail)
        self.assertNotIn(str(self.root),str(listing))
        self.assertNotIn(str(self.root),str(detail))

    def test_recovery_status_never_exposes_private_project_windows_path(self):
        self.service.create_session("recovery-privacy")
        record=self.service.recovery("recovery-privacy")
        self.assertNotIn("session",record)
        self.assertNotIn(str(self.root),str(record))
        self.assertIn("locks",record)

    def test_missing_real_squat_not_assumed_valid(self):
        analysis=self.service.analysis()
        self.assertEqual(analysis["squat"]["status"],"synthetic_tests_only")
        self.assertFalse(analysis["squat"]["clinical_accuracy_verified"])


if __name__=="__main__":
    unittest.main()
