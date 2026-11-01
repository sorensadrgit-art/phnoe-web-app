"""TEST_ONLY generated source archives; the extracted integrity gate runs unmocked."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path

import test_offline_distribution as fixtures
from tools import build_offline_distribution as package
from tools.package_agent_handoff import verify_and_extract


class TestStandalonePackageVerifier(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TestOfflineDistribution()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fixture.stage()
        package.generate_manifest()
        package.verify_distribution_integrity()
        package.create_zip_archive()
        self.extraction = self.fixture.root / "TEST_ONLY-extraction"
        self.extraction.mkdir()
        verify_and_extract(self.fixture.archive, self.extraction)
        self.package_root = self.extraction / package.PACKAGE_NAME
        self.script = self.package_root / "tools/build_offline_distribution.py"
        self.manifest = self.package_root / "DISTRIBUTION-MANIFEST.json"
        self.expected = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.foreign = self.fixture.root / "TEST_ONLY-foreign-cwd"
        self.foreign.mkdir()
        self.env = dict(os.environ)
        for key in ("TEMP", "TMP", "APPDATA", "LOCALAPPDATA"):
            directory = self.fixture.root / ("TEST_ONLY-" + key)
            directory.mkdir()
            self.env[key] = str(directory)
        self.env.pop("PYTHONHOME", None)
        self.env.pop("PYTHONPATH", None)

    def snapshot(self):
        result = {}
        for path in self.package_root.rglob("*"):
            info = path.lstat()
            name = path.relative_to(self.package_root).as_posix()
            if stat.S_ISLNK(info.st_mode):
                result[name] = ("link", os.readlink(path))
            elif stat.S_ISREG(info.st_mode):
                result[name] = ("file", path.read_bytes(), info.st_nlink)
        return result

    def run_verifier(self, *, expected=None, success=True, extra=()):
        self.assertTrue(self.script.is_file(), "Standalone verifier missing from genuine extracted package")
        before = self.snapshot()
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", "-I", "-B", str(self.script),
             "--verify-package", str(self.package_root.resolve()),
             "--expected-manifest-sha256", self.expected if expected is None else expected, *extra],
            cwd=self.foreign, env=self.env, capture_output=True, text=True,
            encoding="utf-8", timeout=20, check=False)
        self.assertEqual(self.snapshot(), before, "Read-only verifier changed package bytes or membership")
        self.assertEqual(list(self.foreign.iterdir()), [])
        self.assertEqual(completed.returncode, 0 if success else 1, completed.stderr)
        self.assertIn("PACKAGE_INTEGRITY_VERIFIED_READ_ONLY=" if success else "[VERIFY ERROR]",
                      completed.stdout if success else completed.stderr)

    def test_shipped_verifier_is_byte_exact_and_foreign_cwd_accepts(self):
        self.assertTrue(self.script.is_file(), "Standalone verifier missing from genuine extracted package")
        self.assertEqual(self.script.read_bytes(), Path(package.__file__).read_bytes())
        self.run_verifier()

    def test_tampered_member_refused_without_rewriting(self):
        self.run_verifier()
        (self.package_root / "app/requirements.lock.txt").write_bytes(b"TEST_ONLY changed lock")
        self.run_verifier(success=False)

    def test_missing_member_refused_without_rewriting(self):
        self.run_verifier()
        (self.package_root / "app/requirements.lock.txt").unlink()
        self.run_verifier(success=False)

    def test_unlisted_member_refused_without_rewriting(self):
        self.run_verifier()
        (self.package_root / "TEST_ONLY-unlisted.txt").write_bytes(b"TEST_ONLY")
        self.run_verifier(success=False)

    def test_wrong_manifest_digest_refused_without_rewriting(self):
        self.run_verifier()
        self.run_verifier(expected="0" * 64, success=False)

    def test_coherently_hashed_traversal_manifest_refused(self):
        self.run_verifier()
        document = json.loads(self.manifest.read_bytes())
        document["files"][0]["path"] = "../TEST_ONLY-escape.txt"
        self.manifest.write_text(json.dumps(document), encoding="utf-8")
        self.expected = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.run_verifier(success=False)
        self.assertFalse((self.extraction / "TEST_ONLY-escape.txt").exists())

    def test_hardlinked_member_refused_with_matching_content(self):
        self.run_verifier()
        member = self.package_root / "app/requirements.lock.txt"
        twin = self.fixture.root / "TEST_ONLY-hardlink-twin.txt"
        twin.write_bytes(member.read_bytes())
        member.unlink()
        os.link(twin, member)
        self.assertEqual(member.stat().st_nlink, 2)
        self.run_verifier(success=False)
        self.assertEqual(twin.read_bytes(), member.read_bytes())

    def test_verification_rejects_build_options_without_writes(self):
        self.run_verifier()
        build_target = self.fixture.root / "TEST_ONLY-must-remain-absent"
        self.run_verifier(success=False, extra=("--out", str(build_target)))
        self.assertFalse(build_target.exists())

    def test_unlisted_shadow_module_never_executes_before_refusal(self):
        self.run_verifier()
        marker = self.foreign / "TEST_ONLY-foreign-marker.txt"
        shadow = self.package_root / "tools/argparse.py"
        shadow.write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('TEST_ONLY shadow import', encoding='utf-8')\n"
            "raise RuntimeError('TEST_ONLY unchecked shadow module executed')\n",
            encoding="utf-8",
        )
        self.assertFalse(marker.exists())
        self.run_verifier(success=False)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
