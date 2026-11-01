"""Generated TEST_ONLY clips exercise the real fixture/export gates; no browser or inference."""
import json
import tempfile
import unittest
from pathlib import Path

from export_motion import load_verified_motion
from native_evidence_fixture import complete_native_fixture
from run_pipeline import validate_run_evidence
from t6_service import IntegratedService
from test_export_motion import trc_text
from tools.verify_browser_isolation import _prepare_default_comparison_fixture


class BrowserComparisonNativeFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="KineLab-PT-TEST-ONLY-browser-native-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = IntegratedService(self.root / "projects")
        self.addCleanup(self.service.close)

    def test_bound_native_motion_but_demo_comparison_refused(self):
        receipt = _prepare_default_comparison_fixture(self.service)
        self.assertTrue(receipt["test_only"])
        self.assertFalse(receipt["source_video_decoded"])
        self.assertTrue(receipt["normalized_test_only_video_decoded"])
        self.assertEqual(receipt["native_compute"], "NOT_PERFORMED")
        self.assertFalse(receipt["physical_accuracy_verified"])
        self.assertEqual(receipt["clinical_validation"], "UNVERIFIED")
        self.assertEqual(set(receipt["sessions"]), {"synthetic-race-d", "synthetic-race-e"})
        session_sources = {}
        for sid in receipt["sessions"]:
            folder = self.service.index.projects_root / sid
            before = {p.relative_to(folder).as_posix(): p.read_bytes()
                      for p in folder.rglob("*") if p.is_file()}
            session_sources[sid] = before
            verified = validate_run_evidence(folder, "kinematics")
            coverage = verified["run"]["stages"][4]["quality"]["source_coverage"]
            self.assertEqual(coverage["common_range"], [1, 4])
            exported = load_verified_motion(folder, folder / "exports/generated.motion.json")
            self.assertEqual(exported["schema"], "kinelab.motion.v2")
            self.assertEqual(exported["fps"], 30)
            self.assertEqual(len(exported["frames"]), 3)
            for index, frame in enumerate(exported["frames"], 1):
                self.assertAlmostEqual(frame["t"], index / 30)
            self.assertEqual([row[1] for row in exported["kinematics"]["rows"]], [0.2, 0.8, 0.5])
            self.assertEqual([row[0] for row in exported["kinematics"]["rows"]],
                             [frame["t"] for frame in exported["frames"]])
            self.assertEqual({p.relative_to(folder).as_posix(): p.read_bytes()
                              for p in folder.rglob("*") if p.is_file()}, before)
        comparison = self.service.index.compare_sessions("synthetic-race-d", "synthetic-race-e")
        self.assertFalse(comparison["compatible"], comparison)
        self.assertEqual(comparison["reason"],
                         "Incompatible: test-only sessions cannot be compared against real recordings")
        self.assertEqual(comparison["research_measurements"]["status"], "UNAVAILABLE")
        self.assertEqual(comparison["research_measurements"]["sessions"], [])
        self.assertEqual(comparison["research_measurements"]["coordinates"], [])
        self.assertFalse(comparison["clinical_accuracy_verified"])
        for sid, source in session_sources.items():
            folder = self.service.index.projects_root / sid
            self.assertEqual({p.relative_to(folder).as_posix(): p.read_bytes()
                              for p in folder.rglob("*") if p.is_file()}, source)

    def test_zero_origin_remains_rejected_without_changing_bound_fixture(self):
        _prepare_default_comparison_fixture(self.service)
        folder = self.service.index.projects_root / "synthetic-race-d"
        before = {p.relative_to(folder).as_posix(): p.read_bytes()
                  for p in folder.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(ValueError, "TEST_ONLY bound TRC fixture requires a positive, nonempty native interval"):
            complete_native_fixture(folder, trc_text(times=(0, 0.1, 0.2)), through="kinematics")
        self.assertEqual({p.relative_to(folder).as_posix(): p.read_bytes()
                          for p in folder.rglob("*") if p.is_file()}, before)
        self.assertEqual(json.loads((folder / "run.json").read_text(encoding="utf-8"))["quality_policy"],
                         validate_run_evidence(folder, "kinematics")["run"]["quality_policy"])


if __name__ == "__main__":
    unittest.main()
