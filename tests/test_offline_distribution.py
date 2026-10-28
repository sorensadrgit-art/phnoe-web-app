"""Unit tests for offline distribution packaging and manifest verification."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.build_offline_distribution import (
    DIST_DIR,
    PACKAGE_NAME,
    TARGET_DIR,
    ZIP_PATH,
    sha256_file,
    verify_distribution_integrity,
)


class TestOfflineDistribution(unittest.TestCase):

    def test_sha256_file(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"Hello KineLab Distribution")
            temp_path = Path(f.name)
        try:
            digest = sha256_file(temp_path)
            self.assertEqual(len(digest), 64)
            # Known sha256 for "Hello KineLab Distribution"
            import hashlib
            expected = hashlib.sha256(b"Hello KineLab Distribution").hexdigest()
            self.assertEqual(digest, expected)
        finally:
            temp_path.unlink(missing_ok=True)

    def test_package_directory_and_manifest_exist(self):
        self.assertTrue(TARGET_DIR.is_dir(), "Distribution directory must exist")
        manifest_file = TARGET_DIR / "DISTRIBUTION-MANIFEST.json"
        self.assertTrue(manifest_file.is_file(), "DISTRIBUTION-MANIFEST.json must exist")

        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(data.get("schema"), "kinelab.distribution.manifest.v1")
        self.assertEqual(data.get("package_name"), PACKAGE_NAME)
        self.assertEqual(data.get("verification_status"), "SOFTWARE_BUILD_VERIFIED")
        self.assertEqual(data.get("physical_validation_status"), "BLOCKED_ON_PHYSICAL_EVIDENCE")
        self.assertEqual(data.get("clinical_validation_status"), "UNVERIFIED")
        self.assertGreater(data.get("total_files", 0), 20)
        self.assertGreater(data.get("total_bytes", 0), 100000)

    def test_zip_archive_validity(self):
        self.assertTrue(ZIP_PATH.is_file(), "Distribution ZIP archive must exist")
        with zipfile.ZipFile(ZIP_PATH, "r") as zf:
            names = zf.namelist()
            self.assertTrue(any("Start-KineLabPT.bat" in n for n in names))
            self.assertTrue(any("Install-DesktopShortcut.ps1" in n for n in names))
            self.assertTrue(any("t6_launcher.py" in n for n in names))
            self.assertTrue(any("index.html" in n for n in names))

    def test_distribution_integrity_check(self):
        # Must not raise
        verify_distribution_integrity()


if __name__ == "__main__":
    unittest.main()
