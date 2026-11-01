"""M1 containment acceptance tests: disposable synthetic fixtures only.

New tests start RED against the 2026-10-28 baseline and must pass after
the approved refusal/preflight fixes. No private recordings are accessed.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from backup_manager import BackupConflictError, BackupCorruptError, BackupManager
from t6_server import make_server
from t6_service import IntegratedService, IntegrationBlocked


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_archive(path: Path, sessions: dict[str, dict[str, bytes]], *, extra: dict[str, bytes] | None = None,
                 manifest_override: dict | None = None):
    entries = {}
    for sid, files in sessions.items():
        for filename, content in files.items():
            entries[f"sessions/{sid}/{filename}"] = content
    entries.update(extra or {})
    manifest = {"schema": "kinelab.backup.v1", "sessions": list(sessions),
                "database_included": False, "file_count": len(entries),
                "files": [{"path": name, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}
                          for name, blob in entries.items()]}
    if manifest_override:
        manifest.update(manifest_override)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("backup_manifest.json", json.dumps(manifest))
        for name, blob in entries.items():
            archive.writestr(name, blob)


class ContainmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="kinelab-m1-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.svc = IntegratedService(projects_root=self.projects)
        self.addCleanup(self.svc.close)

    def test_live_write_unverified_rejects_before_files(self):
        payload = {"session_id": "live-refuse-01", "exercise_type": "squats",
                   "reps": [{"valid": True}], "summary_metrics": {"totalReps": 1}}
        before = sorted(x.name for x in self.projects.iterdir())
        with self.assertRaisesRegex(IntegrationBlocked, "LIVE_ACQUISITION_UNVERIFIED"):
            self.svc.save_live_session(payload)
        self.assertEqual(sorted(x.name for x in self.projects.iterdir()), before)
        self.assertFalse((self.projects / "live-refuse-01").exists())

    def test_forged_source_cannot_enable_live_write(self):
        for index, spoof in enumerate([
            {"source": "camera", "is_simulated": False},
            {"source_type": "measured", "is_test_only": False},
            {"verified": True, "clinical_accuracy_verified": True},
            {"frames": [{"t": 0.0, "xyz": [[0.0, 0.0, 0.0]] * 22}]},
            {"frames": [], "reps": [{"valid": "false"}], "summary_metrics": {"fps": -1.0}},
            {"frames": [{"t": -1, "xyz": [[float('nan'), 0, 0]] * 22}]},
        ]):
            sid = f"live-spoof-{index}"
            payload = {"session_id": sid, "exercise_type": "squats", **spoof}
            with self.subTest(spoof=spoof):
                with self.assertRaisesRegex(IntegrationBlocked, "LIVE_ACQUISITION_UNVERIFIED"):
                    self.svc.save_live_session(payload)
                self.assertFalse((self.projects / sid).exists())

    def test_direct_http_cannot_save_even_with_forged_source(self):
        dist = self.root / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<h1>Test</h1>", encoding="utf-8")
        samples = self.root / "samples"
        samples.mkdir()
        token = "s" * 50
        server = make_server(self.svc, token=token, dist=dist, samples=samples, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            data = json.dumps({"session_id": "live-http-forged", "exercise_type": "squats",
                               "source": "physical_camera", "verified": True}).encode()
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=6)
            conn.request("POST", "/api/v1/sessions/live-set", data, {
                "Host": f"127.0.0.1:{server.server_port}",
                "Origin": f"http://127.0.0.1:{server.server_port}",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            })
            response = conn.getresponse()
            result = json.loads(response.read().decode())
            conn.close()
            self.assertEqual(response.status, 409)
            self.assertIn("LIVE_ACQUISITION_UNVERIFIED", result.get("error", ""))
            self.assertFalse((self.projects / "live-http-forged").exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_legacy_live_evidence_never_promotes_or_generates_valid_report(self):
        sid = "live-legacy-01"
        folder = self.projects / sid
        (folder / "exports").mkdir(parents=True)
        (folder / "Config.toml").write_text("[session]\nkind='live'\n")
        (folder / "session.json").write_text(json.dumps({
            "id": sid, "schema": "kinelab.live-session.v1",
            "kind": "live", "status": "completed", "valid_reps": 2}), encoding="utf-8")
        (folder / "live_telemetry.json").write_text('{"source":"camera","reps":[{"valid":true}]}')
        motion = folder / "exports" / f"{sid}.motion.json"
        motion.write_text('{"schema":"kinelab.motion.v1","frames":[{"t":0}]}', encoding="utf-8")
        original = {p.name: file_digest(p) for p in folder.rglob("*") if p.is_file()}
        self.svc.index.reindex()
        passport = self.svc.passport(sid)
        self.assertEqual(passport["state"], "EVIDENCE_UNVERIFIED")
        self.assertEqual(passport["badge"], "UNVERIFIED")
        self.assertFalse(passport["clinically_validated"])
        self.assertFalse(passport["physical_accuracy_verified"])
        with self.assertRaisesRegex(ValueError, "EVIDENCE_UNVERIFIED"):
            self.svc.generate_reports(sid, confirm=True)
        with self.assertRaisesRegex(ValueError, "EVIDENCE_UNVERIFIED"):
            self.svc.motion_data(sid)
        with self.assertRaisesRegex(ValueError, "EVIDENCE_UNVERIFIED"):
            self.svc.artifact(sid, f"exports/{sid}.motion.json")
        self.assertEqual(original, {p.name: file_digest(p) for p in folder.rglob("*") if p.is_file()})

    def test_valid_non_conflicting_restore(self):
        archive = self.root / "valid.zip"
        make_archive(archive, {"valid01": {"Config.toml": b"[session]\n", "session.json": b'{"id":"valid01"}'}})
        result = BackupManager(self.projects, self.svc.index).restore_backup(archive)
        self.assertTrue(result["ok"])
        self.assertIn("valid01", result["restored_sessions"])
        self.assertEqual((self.projects / "valid01" / "Config.toml").read_bytes(), b"[session]\n")

    def test_overwrite_is_unavailable_even_with_confirmed_archive(self):
        folder = self.projects / "protected"
        folder.mkdir()
        doc = folder / "Config.toml"
        doc.write_text("ORIGINAL", encoding="utf-8")
        old_hash = file_digest(doc)
        archive = self.root / "overwrite.zip"
        make_archive(archive, {"protected": {"Config.toml": b"ATTACKER"}})
        with self.assertRaisesRegex(BackupConflictError, "RESTORE_OVERWRITE_UNAVAILABLE"):
            BackupManager(self.projects, self.svc.index).restore_backup(archive, overwrite=True)
        self.assertEqual(file_digest(doc), old_hash)

    def test_unlisted_member_rejected_with_no_destination_change(self):
        archive = self.root / "unlisted.zip"
        make_archive(archive, {"unlisted01": {"Config.toml": b"[session]\n"}},
                     extra={"sessions/unlisted01/evil.txt": b"UNLISTED"},
                     manifest_override={"files": [{"path":"sessions/unlisted01/Config.toml",
                                                   "sha256":hashlib.sha256(b"[session]\n").hexdigest(),
                                                   "bytes":len(b"[session]\n")}],
                                        "file_count":1})
        with self.assertRaises(BackupCorruptError):
            BackupManager(self.projects, self.svc.index).restore_backup(archive)
        self.assertFalse((self.projects / "unlisted01").exists())

    def test_traversal_session_rejected_without_touching_sibling(self):
        sibling = self.root / "sibling"
        sibling.mkdir()
        marker = sibling / "original.txt"
        marker.write_text("NO-DELETE")
        original = file_digest(marker)
        archive = self.root / "traversal.zip"
        make_archive(archive, {"../sibling": {"Config.toml": b"bad"}})
        with self.assertRaises(BackupCorruptError):
            BackupManager(self.projects, self.svc.index).restore_backup(archive)
        self.assertEqual(file_digest(marker), original)
        self.assertFalse((sibling / "Config.toml").exists())

    def test_absent_required_file_rejected_without_deleting_existing(self):
        folder = self.projects / "existing01"
        folder.mkdir()
        doc = folder / "Config.toml"
        doc.write_text("ORIGINAL")
        original = file_digest(doc)
        archive = self.root / "missing.zip"
        manifest = {"schema":"kinelab.backup.v1", "sessions":["existing01"],
                    "database_included":False, "file_count":1,
                    "files":[{"path":"sessions/existing01/Config.toml",
                              "sha256":hashlib.sha256(b"UNPRESENT").hexdigest(), "bytes":9}]}
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("backup_manifest.json", json.dumps(manifest))
        with self.assertRaises(BackupCorruptError):
            BackupManager(self.projects, self.svc.index).restore_backup(archive)
        self.assertEqual(file_digest(doc), original)

    def test_case_alias_and_duplicate_member_rejected(self):
        archive = self.root / "alias.zip"
        manifest = {"schema":"kinelab.backup.v1","sessions":["alias01"],
                    "database_included":False,"file_count":2,"files":[]}
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("backup_manifest.json",json.dumps(manifest))
            z.writestr("sessions/alias01/Config.toml",b"VERSION A")
            z.writestr("sessions/alias01/config.toml",b"VERSION B")
        with self.assertRaises(BackupCorruptError):
            BackupManager(self.projects, self.svc.index).restore_backup(archive)
        self.assertFalse((self.projects / "alias01").exists())

    def test_drive_and_unc_members_rejected(self):
        for index, filename in enumerate(["C:/outside.txt", "//server/share/file.txt",
                                          r"sessions\s01\Config.toml", "sessions/s01/../steal.txt"]):
            archive = self.root / f"unsafe-{index}.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("backup_manifest.json",json.dumps({
                    "schema":"kinelab.backup.v1","sessions":["s01"],
                    "database_included":False,"file_count":0,"files":[]}))
                z.writestr(filename,b"attack")
            with self.subTest(filename=filename), self.assertRaises(BackupCorruptError):
                BackupManager(self.projects, self.svc.index).restore_backup(archive)

    def test_partial_publication_rolls_back_new_sessions(self):
        archive = self.root / "rollback.zip"
        make_archive(archive, {"rollback01":{"Config.toml":b"one"},
                               "rollback02":{"Config.toml":b"two"}})
        class BrokenIndex:
            def reindex(self):
                raise RuntimeError("simulated_index_failure")
        with self.assertRaisesRegex(RuntimeError, "simulated_index_failure"):
            BackupManager(self.projects, BrokenIndex()).restore_backup(archive)
        self.assertFalse((self.projects / "rollback01").exists())
        self.assertFalse((self.projects / "rollback02").exists())

    def test_backup_filename_path_components_rejected(self):
        for bad in ("../outside.zip", r"..\outside.zip", r"C:\outside.zip", "//server/x.zip", "valid.txt"):
            with self.subTest(name=bad), self.assertRaisesRegex(ValueError, "BACKUP_NAME_INVALID"):
                self.svc.restore_backup(bad, confirm=True)


    def test_duplicate_manifest_json_keys_rejected(self):
        archive = self.root / "duplicate-json.zip"
        raw = '{"schema":"kinelab.backup.v1","sessions":[],"sessions":["spoof"],"database_included":false,"file_count":0,"files":[]}'
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("backup_manifest.json", raw)
        with self.assertRaises(BackupCorruptError):
            BackupManager(self.projects, self.svc.index).restore_backup(archive)

    def test_symlink_zip_member_rejected(self):
        archive = self.root / "link.zip"
        payload = b"../../somewhere"
        name = "sessions/symlink01/Config.toml"
        manifest = {"schema":"kinelab.backup.v1", "sessions":["symlink01"],
                    "database_included":False, "file_count":1,
                    "files":[{"path":name, "sha256":hashlib.sha256(payload).hexdigest(),
                              "bytes":len(payload)}]}
        zi = zipfile.ZipInfo(name)
        zi.create_system = 3
        zi.external_attr = 0o120777 << 16
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("backup_manifest.json", json.dumps(manifest))
            z.writestr(zi, payload)
        with self.assertRaises(BackupCorruptError):
            BackupManager(self.projects, self.svc.index).restore_backup(archive)
        self.assertFalse((self.projects / "symlink01").exists())

    def test_expansion_ratio_limit_rejects_bomb(self):
        archive = self.root / "large-ratio.zip"
        make_archive(archive, {"ratio01": {"Config.toml":b"A" * 200_000}})
        with self.assertRaises(BackupCorruptError):
            BackupManager(self.projects, self.svc.index).restore_backup(archive)
        self.assertFalse((self.projects / "ratio01").exists())

    def test_duplicate_session_case_alias_rejected(self):
        archive = self.root / "duplicate-session.zip"
        make_archive(archive, {"aliasone":{"Config.toml":b"ONE"}},
                     manifest_override={"sessions":["aliasone", "ALIASONE"]})
        with self.assertRaises(BackupCorruptError):
            BackupManager(self.projects, self.svc.index).restore_backup(archive)

    def test_missing_session_config_fails_before_publish(self):
        archive = self.root / "no-config.zip"
        make_archive(archive, {"noconfig01":{"data.txt":b"DATA"}})
        with self.assertRaises(BackupCorruptError):
            BackupManager(self.projects, self.svc.index).restore_backup(archive)
        self.assertFalse((self.projects / "noconfig01").exists())

    def test_session_destination_symlink_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        marker = outside / "marker.txt"
        marker.write_text("PRESERVE")
        dest = self.projects / "symdest"
        try:
            import os
            os.symlink(outside, dest, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlink unavailable for this test account: {exc}")
        archive = self.root / "symdest.zip"
        make_archive(archive, {"symdest":{"Config.toml":b"MALICIOUS"}})
        with self.assertRaises((BackupConflictError, BackupCorruptError)):
            BackupManager(self.projects, self.svc.index).restore_backup(archive)
        self.assertEqual(marker.read_text(), "PRESERVE")


if __name__ == "__main__":
    unittest.main()
