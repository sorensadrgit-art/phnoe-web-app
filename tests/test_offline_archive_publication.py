"""Generated archive publication tests; no installed runtime or release artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import test_offline_distribution as fixture_module
from tools import build_offline_distribution as package


class OfflineArchivePublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.TestOfflineDistribution(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.stage()
        package.generate_manifest()
        package.verify_distribution_integrity()
        self.target, self.archive = self.fixture.target, self.fixture.archive
        self.manifest = self.target / "DISTRIBUTION-MANIFEST.json"
        self.manifest_bytes = self.manifest.read_bytes()
        self.source_bytes = (self.fixture.source / "t6_service.py").read_bytes()

    def assert_originals_preserved(self):
        self.assertEqual(self.manifest.read_bytes(), self.manifest_bytes)
        self.assertEqual((self.fixture.source / "t6_service.py").read_bytes(), self.source_bytes)

    def test_00_mutated_verified_payload_refused_before_archive_publication(self):
        victim = self.target / "app/t6_service.py"
        changed = victim.read_bytes() + b"\n# TEST_ONLY changed after manifest verification\n"
        victim.write_bytes(changed)
        with self.assertRaises(ValueError):
            package.create_zip_archive()
        self.assertFalse(self.archive.exists())
        self.assertEqual(victim.read_bytes(), changed)
        self.assert_originals_preserved()

    def test_01_positive_archive_exact_members_and_bytes_remain_compatible(self):
        digest, size = package.create_zip_archive()
        self.assertEqual(size, self.archive.stat().st_size)
        self.assertEqual(digest, hashlib.sha256(self.archive.read_bytes()).hexdigest())
        entries = json.loads(self.manifest_bytes)["files"]
        with zipfile.ZipFile(self.archive) as archive:
            names = {f"{package.PACKAGE_NAME}/{entry['path']}" for entry in entries}
            manifest_name = f"{package.PACKAGE_NAME}/DISTRIBUTION-MANIFEST.json"
            self.assertEqual(set(archive.namelist()), names | {manifest_name})
            self.assertEqual(len(archive.namelist()), len(names) + 1)
            self.assertEqual(archive.read(manifest_name), self.manifest_bytes)
            for entry in entries:
                raw = archive.read(f"{package.PACKAGE_NAME}/{entry['path']}")
                self.assertEqual(len(raw), entry["size_bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])
        before = self.archive.read_bytes()
        with self.assertRaises(FileExistsError):
            package.create_zip_archive()
        self.assertEqual(self.archive.read_bytes(), before)
        self.assert_originals_preserved()

    def test_02_unlisted_file_refused_before_archive_publication(self):
        extra = self.target / "TEST_ONLY-unlisted.txt"
        extra.write_bytes(b"TEST_ONLY not manifest-bound")
        with self.assertRaises(ValueError):
            package.create_zip_archive()
        self.assertFalse(self.archive.exists())
        self.assertEqual(extra.read_bytes(), b"TEST_ONLY not manifest-bound")
        self.assert_originals_preserved()

    def test_03_deleted_file_refused_before_archive_publication(self):
        victim = self.target / "app/t6_service.py"
        victim.unlink()
        with self.assertRaises(ValueError):
            package.create_zip_archive()
        self.assertFalse(self.archive.exists())
        self.assertFalse(victim.exists())
        self.assert_originals_preserved()

    def test_04_missing_manifest_refused_before_archive_publication(self):
        self.manifest.unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            package.create_zip_archive()
        self.assertFalse(self.archive.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual((self.fixture.source / "t6_service.py").read_bytes(), self.source_bytes)

    def test_05_changed_during_copy_refuses_and_retains_partial_evidence(self):
        victim = self.target / "app/t6_service.py"
        changed = victim.read_bytes() + b"\n# TEST_ONLY changed during ZIP copy\n"
        original_open = zipfile.ZipFile.open
        fired = []

        class MutatingWriter:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def write(self, block):
                count = self.stream.write(block)
                if not fired:
                    fired.append(True)
                    victim.write_bytes(changed)
                return count

        def open_member(archive, name, mode="r", pwd=None, *, force_zip64=False):
            stream = original_open(archive, name, mode, pwd, force_zip64=force_zip64)
            member_name = name.filename if isinstance(name, zipfile.ZipInfo) else name
            if mode == "w" and member_name == f"{package.PACKAGE_NAME}/app/t6_service.py":
                return MutatingWriter(stream)
            return stream

        with patch.object(zipfile.ZipFile, "open", new=open_member), self.assertRaises(ValueError):
            package.create_zip_archive()
        self.assertEqual(fired, [True], "Fault must occur inside real member copying")
        self.assertFalse(self.archive.exists())
        partial = Path(str(self.archive) + ".partial")
        self.assertTrue(partial.is_file())
        partial_bytes = partial.read_bytes()
        self.assertGreater(len(partial_bytes), 0)
        self.assertEqual(victim.read_bytes(), changed)
        victim.write_bytes(self.source_bytes)
        with self.assertRaises(FileExistsError):
            package.create_zip_archive()
        self.assertEqual(partial.read_bytes(), partial_bytes)
        self.assertFalse(self.archive.exists())
        self.assert_originals_preserved()

    def test_06_staged_junction_remains_refused(self):
        outside = self.fixture.root / "TEST_ONLY-outside"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_bytes(b"TEST_ONLY outside")
        self.fixture.directory_link(self.target / "app/assets/external", outside)
        with self.assertRaisesRegex(ValueError, "link|reparse|junction"):
            package.create_zip_archive()
        self.assertFalse(self.archive.exists())
        self.assertEqual(sentinel.read_bytes(), b"TEST_ONLY outside")
        self.assert_originals_preserved()

    def test_07_hardlinked_member_refused_without_source_changes(self):
        victim = self.target / "app/t6_service.py"
        original = victim.read_bytes()
        sibling = self.fixture.root / "TEST_ONLY-hardlink-source.py"
        sibling.write_bytes(original)
        victim.unlink()
        try:
            os.link(sibling, victim)
        except OSError as error:
            self.skipTest(f"Owned fixture hard links unavailable: {error}")
        with self.assertRaises(ValueError):
            package.create_zip_archive()
        self.assertFalse(self.archive.exists())
        self.assertEqual(sibling.read_bytes(), original)
        self.assertEqual(victim.read_bytes(), original)
        self.assert_originals_preserved()

    def test_08_partial_tamper_during_final_staging_recheck_refused(self):
        original_check = package._distribution_manifest
        calls, tampered = [], []
        partial = Path(str(self.archive) + ".partial")

        def final_check_window():
            result = original_check()
            calls.append(True)
            if len(calls) == 2:
                verified = partial.read_bytes()
                self.assertTrue(verified.startswith(b"PK"), "Actual ZIP must already exist")
                # Same inode and size; change the already-decoded ZIP during final staging validation.
                changed = b"Q" + verified[1:]
                partial.write_bytes(changed)
                tampered.append(changed)
            return result

        with patch.object(package, "_distribution_manifest", side_effect=final_check_window), self.assertRaises(ValueError):
            package.create_zip_archive()
        self.assertEqual(calls, [True, True], "Fault must reach the final staging check")
        self.assertEqual(len(tampered), 1)
        self.assertEqual(partial.read_bytes(), tampered[0], "Retain exact tampered partial evidence")
        self.assertFalse(self.archive.exists())
        self.assert_originals_preserved()
