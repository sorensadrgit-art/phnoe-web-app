"""TEST_ONLY lock-inventory packaging regressions; no native activation."""
from __future__ import annotations

import unittest

import test_offline_distribution as fixtures
from tools import build_offline_distribution as package


class TestOfflineDistributionLockInventory(unittest.TestCase):
    def setUp(self):
        # Reuse only the existing generated temporary-source setup, not its tests.
        self.fixture = fixtures.TestOfflineDistribution(methodName="test_sha256_file")
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.lock = self.fixture.source / "requirements.lock.txt"

    def test_intact_lock_inventory_is_copied_byte_exact(self):
        expected = self.lock.read_bytes()
        package.check_prerequisites()
        package.copy_application_files()
        self.assertEqual(
            (self.fixture.target / "app/requirements.lock.txt").read_bytes(), expected
        )

    def test_missing_lock_inventory_refused_before_staging(self):
        package.check_prerequisites()  # Establish the intact fixture is accepted first.
        self.lock.unlink()
        with self.assertRaisesRegex(RuntimeError, "requirements[.]lock[.]txt"):
            package.check_prerequisites()
        self.assertFalse(self.fixture.target.exists())
        self.assertFalse(self.fixture.archive.exists())

    def test_direct_staging_cannot_bypass_missing_lock_inventory(self):
        package.check_prerequisites()  # All other generated prerequisites are intact.
        self.lock.unlink()
        with self.assertRaises(FileNotFoundError):
            package.copy_application_files()
        self.assertFalse(self.fixture.target.exists())
        self.assertFalse(self.fixture.archive.exists())


if __name__ == "__main__":
    unittest.main()
