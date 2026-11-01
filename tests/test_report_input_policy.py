"""Declared report input policies on disposable generated sessions only."""
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from backup_manager import BackupManager
from report_builder import ReportBuilder
from report_generation import capture_inputs, committed_reports
from session_index import SessionIndex
from session_library import SessionLibrary
from tools.verify_evidence import VerifyError, _verify_reports, verify_archive

ANCHOR = "takes/.acceptance-lease/t6-startup.lock"
POLICY_V2 = "kinelab.report-inputs.v2"
ABSENT = object()


class ReportInputPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kinelab-report-policy-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.projects = self.root / "generated-projects"
        self.projects.mkdir()
        self.library = SessionLibrary(self.projects)
        self.index = SessionIndex(self.root / "generated-index.db", self.projects)
        self.addCleanup(self.index.close)
        self.sequence = 0
        self.folder = self._new_session()

    def _new_session(self):
        self.sequence += 1
        folder = self.library.create_session(f"policy-{self.sequence}", kind="demo")
        self.index.reindex()
        return folder

    @staticmethod
    def _write(folder, relative, content):
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    @staticmethod
    def _reference(content):
        return {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}

    def _fixture(self, policy=ABSENT, *, folder=None, record_anchor=False):
        """Author one coherent fixture before commit; never repair an old receipt."""
        folder = folder or self.folder
        sid = folder.name
        inputs = {}
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                relative = path.relative_to(folder).as_posix()
                if policy == POLICY_V2 and relative == ANCHOR and not record_anchor:
                    continue
                inputs[relative] = self._reference(path.read_bytes())
        generation = "report-" + "a" * 32
        directory = folder / "exports" / generation
        directory.mkdir(parents=True)
        artifacts = {
            f"{sid}-research-report.pdf": b"%PDF-generated-policy-fixture",
            f"{sid}-research-summary.json": b'{"fixture":"generated"}',
            f"{sid}-metrics.csv": b"fixture,value\ngenerated,1\n",
        }
        document = {
            "schema": "kinelab.report-generation.v1", "generation": generation,
            "session_id": sid, "inputs": inputs,
            "files": {name: self._reference(content) for name, content in artifacts.items()},
        }
        if policy is not ABSENT:
            document["input_policy"] = policy
        artifacts["manifest.json"] = json.dumps(document, sort_keys=True).encode("utf-8")
        for name, content in artifacts.items():
            (directory / name).write_bytes(content)
        now = datetime.now(UTC).isoformat()
        with self.index.transaction():
            for name, content in artifacts.items():
                reference = self._reference(content)
                self.index.conn.execute(
                    """INSERT INTO artifacts
                    (session_id,artifact_key,filename,artifact_type,bytes,sha256,created_at_utc,
                     observed_sha256,integrity_state) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (sid, f"exports/{generation}/{name}", name, "research_report",
                     reference["bytes"], reference["sha256"], now, reference["sha256"], "unchanged"),
                )
            self.index._append_audit(sid, "REPORT_PUBLISHED", {
                "generation": generation,
                "manifest_sha256": self._reference(artifacts["manifest.json"])["sha256"],
            })
        return directory, document

    def _offline(self):
        """Exercise the real standalone lineage reader with a real ZIP and index."""
        contents = {}
        for path in sorted(self.projects.rglob("*")):
            if path.is_file():
                contents[f"sessions/{path.relative_to(self.projects).as_posix()}"] = path.read_bytes()
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            for relative, content in contents.items():
                archive.writestr(relative, content)
        data.seek(0)
        with zipfile.ZipFile(data) as archive:
            members = {info.filename: info for info in archive.infolist()}
            digests = {relative: self._reference(content) for relative, content in contents.items()}
            return _verify_reports(self.index.conn, archive, members, digests)

    def _authority(self, directory):
        return (
            {path.name: path.read_bytes() for path in directory.iterdir()},
            [tuple(row) for row in self.index.conn.execute(
                "SELECT session_id,artifact_key,sha256,bytes FROM artifacts ORDER BY session_id,artifact_key")],
            [tuple(row) for row in self.index.conn.execute(
                "SELECT id,details_json,event_hash FROM audit_events ORDER BY id")],
        )

    def _assert_valid(self, folder=None):
        folder = folder or self.folder
        self.assertEqual(len(committed_reports(self.index, folder.name)), 3)
        self.assertGreaterEqual(self._offline(), 1)

    def _assert_rejected(self, pattern, folder=None):
        folder = folder or self.folder
        with self.subTest(reader="candidate"), self.assertRaisesRegex(ValueError, pattern):
            committed_reports(self.index, folder.name)
        with self.subTest(reader="standalone-lineage"), self.assertRaisesRegex(VerifyError, pattern):
            self._offline()

    def _generate(self):
        builder = ReportBuilder(self.projects, self.index)
        with patch.object(builder, "_build_pdf", side_effect=lambda path, _doc: path.write_bytes(
                b"%PDF-generated-policy-test")):
            return builder.generate_reports(self.folder.name)

    def test_new_producer_declares_v2_and_omits_only_administrative_anchor(self):
        anchor = self._write(self.folder, ANCHOR, b"existing-administrative-bytes")
        neighbor = "takes/.acceptance-lease/other.lock"
        self._write(self.folder, neighbor, b"bound-neighbor")
        reports = self._generate()
        document = json.loads((reports["json"].parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(document.get("input_policy"), POLICY_V2)
        self.assertNotIn(ANCHOR, document["inputs"])
        self.assertIn(neighbor, document["inputs"])
        self.assertEqual(anchor.read_bytes(), b"existing-administrative-bytes")
        self._assert_valid()

    def test_new_report_first_backup_preserves_full_anchor_inventory_and_readback(self):
        self._generate()
        archive = self.root / "generated-with-reports.zip"
        BackupManager(self.projects, self.index).create_backup(archive)
        before = archive.read_bytes()
        with zipfile.ZipFile(archive) as zipped:
            self.assertEqual(zipped.read(f"sessions/{self.folder.name}/{ANCHOR}"),
                             (self.folder / ANCHOR).read_bytes())
        self.assertEqual(len(committed_reports(self.index, self.folder.name)), 3)
        result = verify_archive(archive)
        self.assertTrue(result["ok"], result["failures"])
        self.assertEqual(archive.read_bytes(), before)

    def test_capture_omits_exact_anchor_but_binds_neighbors_and_pending_markers(self):
        self._write(self.folder, ANCHOR, b"administrative")
        neighbors = [ANCHOR + ".old", "takes/.acceptance-lease/other.lock", "takes/accept.lock",
                     "takes/.acceptance-lease-history/journal.json", "raw/.cam01_trial-replacement"]
        for relative in neighbors:
            self._write(self.folder, relative, b"must-remain-bound")
        inputs = capture_inputs(self.folder)
        self.assertNotIn(ANCHOR, inputs)
        for relative in neighbors:
            self.assertEqual(inputs[relative], self._reference(b"must-remain-bound"))

    def test_v2_readers_allow_new_anchor_without_rewriting_authority(self):
        directory, _ = self._fixture(POLICY_V2)
        authority = self._authority(directory)
        self._write(self.folder, ANCHOR, b"new-administrative")
        self._assert_valid()
        self.assertEqual(self._authority(directory), authority)

    def test_v2_readers_allow_changed_unbound_anchor_bytes(self):
        self._write(self.folder, ANCHOR, b"before")
        directory, _ = self._fixture(POLICY_V2)
        authority = self._authority(directory)
        self._write(self.folder, ANCHOR, b"different-length-administrative-content")
        self._assert_valid()
        self.assertEqual(self._authority(directory), authority)

    def test_v2_neighbor_digest_remains_bound(self):
        relative = "takes/.acceptance-lease/other.lock"
        self._write(self.folder, relative, b"before")
        self._fixture(POLICY_V2)
        self._write(self.folder, relative, b"after")
        self._assert_rejected("report inputs no longer match")

    def test_v2_pending_journal_digest_remains_bound(self):
        relative = "takes/accept.lock"
        self._write(self.folder, relative, b"generated-pending-marker")
        self._fixture(POLICY_V2)
        self._write(self.folder, relative, b"changed-pending-marker")
        self._assert_rejected("report inputs no longer match")

    def test_legacy_missing_policy_with_unchanged_inputs_remains_valid(self):
        directory, document = self._fixture()
        self.assertNotIn("input_policy", document)
        authority = self._authority(directory)
        self._assert_valid()
        self.assertEqual(self._authority(directory), authority)

    def test_legacy_added_anchor_surfaces_specific_compatibility_limitation(self):
        directory, _ = self._fixture()
        authority = self._authority(directory)
        self._write(self.folder, ANCHOR, b"new-first-backup-anchor")
        self._assert_rejected("REPORT_INPUT_POLICY_COMPATIBILITY_REQUIRED")
        self.assertEqual(self._authority(directory), authority)

    def test_legacy_added_anchor_does_not_hide_another_source_change(self):
        self._fixture()
        self._write(self.folder, ANCHOR, b"new-first-backup-anchor")
        self._write(self.folder, "Config.toml", b"# changed actual source")
        self._assert_rejected("report inputs no longer match")

    def test_legacy_recorded_anchor_keeps_original_digest_and_size(self):
        content = b"legacy-recorded-anchor-content"
        self._write(self.folder, ANCHOR, content)
        directory, document = self._fixture()
        self.assertEqual(document["inputs"][ANCHOR], self._reference(content))
        authority = self._authority(directory)
        self._assert_valid()
        self.assertEqual(self._authority(directory), authority)

    def test_legacy_recorded_anchor_change_fails_without_rebinding(self):
        self._write(self.folder, ANCHOR, b"recorded")
        directory, _ = self._fixture()
        authority = self._authority(directory)
        self._write(self.folder, ANCHOR, b"modified-longer")
        self._assert_rejected("report inputs no longer match")
        self.assertEqual(self._authority(directory), authority)

    def test_legacy_recorded_anchor_removal_fails_without_rebinding(self):
        anchor = self._write(self.folder, ANCHOR, b"recorded")
        directory, _ = self._fixture()
        authority = self._authority(directory)
        anchor.unlink()
        self._assert_rejected("report inputs no longer match")
        self.assertEqual(self._authority(directory), authority)

    def test_present_unknown_or_malformed_policy_is_rejected_by_both_readers(self):
        policies = [None, False, 1, [], {}, "", "kinelab.report-inputs.v1", "kinelab.report-inputs.v3"]
        for policy in policies:
            with self.subTest(policy=policy):
                folder = self._new_session()
                self._fixture(policy, folder=folder)
                self._assert_rejected("REPORT_INVALID", folder)

    def test_invalid_policy_is_rejected_even_without_source_comparison(self):
        self._fixture({"unsupported": "policy"})
        with self.assertRaisesRegex(ValueError, "REPORT_INVALID"):
            committed_reports(self.index, self.folder.name, check_inputs=False)

    def test_v2_cannot_silently_discard_a_recorded_anchor_binding(self):
        self._write(self.folder, ANCHOR, b"must-never-be-waived")
        directory, document = self._fixture(POLICY_V2, record_anchor=True)
        self.assertIn(ANCHOR, document["inputs"])
        authority = self._authority(directory)
        self._assert_rejected("REPORT_INVALID")
        self.assertEqual(self._authority(directory), authority)

    def test_anchor_directory_is_not_treated_as_excluded_regular_file(self):
        self._write(self.folder, ANCHOR + "/nested.txt", b"not-an-administrative-file")
        with self.assertRaisesRegex(ValueError, "REPORT_INVALID"):
            capture_inputs(self.folder)

    def test_linked_exact_anchor_is_rejected_before_any_exclusion(self):
        outside = self._write(self.root, "owned-outside.txt", b"owned-generated-content")
        anchor = self.folder / ANCHOR
        anchor.parent.mkdir(parents=True)
        try:
            anchor.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"host cannot create generated symlink: {exc}")
        with self.assertRaisesRegex(ValueError, "REPORT_INVALID"):
            capture_inputs(self.folder)

    def test_linked_anchor_parent_is_rejected_before_any_exclusion(self):
        outside = self.root / "owned-outside-directory"
        outside.mkdir()
        (outside / "t6-startup.lock").write_bytes(b"owned-generated-content")
        parent = self.folder / "takes/.acceptance-lease"
        parent.parent.mkdir(parents=True, exist_ok=True)
        try:
            parent.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"host cannot create generated directory symlink: {exc}")
        with self.assertRaisesRegex(ValueError, "REPORT_INVALID"):
            capture_inputs(self.folder)
