"""T6 integrated local service must delegate to already tested KineLab guards."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backup_manager import BackupConflictError
from t6_service import IntegratedService, IntegrationBlocked


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

    def test_native_capture_stays_blocked_even_with_explicit_request(self):
        self.service.create_session("cam-a")
        with patch("t6_service.subprocess.Popen") as popen:
            with self.assertRaisesRegex(IntegrationBlocked, "PARTICIPANT_RECORDING_BLOCKED"):
                self.service.open_native("cam-a","capture",confirm=True)
            popen.assert_not_called()
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
        self.assertFalse(comp["compatible"])
        self.assertIn("Insufficient verified reconstruction evidence", comp["reason"])

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
        original = self.service._project("bk-sess")
        before = (original / "Config.toml").read_bytes()
        with self.assertRaisesRegex(BackupConflictError, "RESTORE_OVERWRITE_UNAVAILABLE"):
            self.service.restore_backup(bk_file, confirm=True, overwrite=True)
        self.assertEqual((original / "Config.toml").read_bytes(), before)
        # Complete v2 recovery is isolated; it must not merge or replace the active index.
        active_db = self.service.index.db_path.read_bytes()
        r_res = self.service.restore_backup(bk_file, confirm=True, overwrite=False)
        self.assertTrue(r_res["ok"])
        self.assertTrue(r_res["database_restored"])
        self.assertFalse(r_res["active_workspace_changed"])
        recovered = self.service.projects_root / r_res["recovery_directory"]
        self.assertTrue((recovered / ".kinelab_index.db").is_file())
        self.assertEqual((recovered / "bk-sess/Config.toml").read_bytes(), before)
        self.assertEqual(self.service.index.db_path.read_bytes(), active_db)
        self.assertEqual((original / "Config.toml").read_bytes(), before)

    def test_session_metadata_never_exposes_user_windows_filesystem_paths(self):
        self.service.create_session("private-pilot")
        listing=self.service.sessions()
        detail=self.service.session_detail("private-pilot")
        self.assertEqual(listing[0]["id"],"private-pilot")
        self.assertNotIn("path",listing[0])
        self.assertNotIn("path",detail)
        self.assertNotIn(str(self.root),str(listing))
        self.assertNotIn(str(self.root),str(detail))

    def test_backup_waits_for_native_capture_and_processing(self):
        self.service.create_session("backup-busy")
        self.service.webcam = {"session": "backup-busy"}
        with self.assertRaisesRegex(IntegrationBlocked, "BACKUP_BUSY"):
            self.service.create_backup(confirm=True)
        self.service.webcam = None
        self.service.jobs["backup-busy"] = SimpleNamespace(poll=lambda: SimpleNamespace(state="running"))
        with self.assertRaisesRegex(IntegrationBlocked, "BACKUP_BUSY"):
            self.service.create_backup(confirm=True)
        self.assertFalse((self.service.projects_root / "backups").exists())

    def test_backup_requests_in_same_second_create_distinct_preserved_archives(self):
        self.service.create_session("backup-unique")
        with patch("datetime.datetime") as clock:
            clock.now.return_value.strftime.return_value = "20261028-120000"
            first = self.service.create_backup(confirm=True)["backup_file"]
            original = (self.service.projects_root / "backups" / first).read_bytes()
            second = self.service.create_backup(confirm=True)["backup_file"]
        self.assertNotEqual(first, second)
        self.assertEqual((self.service.projects_root / "backups" / first).read_bytes(), original)

    def test_backup_listing_and_creation_refuse_linked_storage(self):
        external = self.root / "external-backups"; external.mkdir()
        try:
            os.symlink(external, self.service.projects_root / "backups", target_is_directory=True)
        except OSError as error:
            self.skipTest("Directory symlinks unavailable: " + str(error))
        for operation in (self.service.backups, lambda: self.service.create_backup(confirm=True)):
            with self.subTest(operation=operation), self.assertRaisesRegex(IntegrationBlocked, "BACKUP_NAME_INVALID"):
                operation()
        self.assertEqual(list(external.iterdir()), [])

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
