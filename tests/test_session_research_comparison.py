"""Generated complete native contract files, not physical or clinical evidence."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from export_motion import motion
from native_evidence_fixture import complete_native_fixture
from session_contract import ROLES, sha256_file
from session_index import SessionIndex
from setup_project import register_captures
from test_export_motion import trc_text
from test_session_metadata import confirmed_metadata


class ResearchComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"; self.projects.mkdir()
        self.index = SessionIndex(self.root / "index.db", self.projects)
        self.addCleanup(self.index.close)
        probe = patch("session_index.probe_clip", return_value={"width": 640, "height": 480, "fps": 30, "duration": 1})
        probe.start(); self.addCleanup(probe.stop)

    def make_session(self, name, *, metadata=True, degrees="yes", through="kinematics", angles=(0.2, 0.8, 0.5)):
        root = self.projects / name; (root / "raw").mkdir(parents=True)
        (root / "Config.toml").write_text("[project]\n", encoding="utf-8")
        for role in ROLES:
            (root / "raw" / (role + ".mp4")).write_bytes(("generated " + role).encode())
        # Before implementation the legacy producer remains usable, so RED exercises real comparison.
        session = register_captures(root, name)
        if metadata:
            session["metadata"] = confirmed_metadata() if metadata is True else copy.deepcopy(metadata)
            (root / "session.json").write_text(json.dumps(session), encoding="utf-8")
        mot = (f"generated\nnRows=3\nnColumns=3\ninDegrees={degrees}\nendheader\n"
               "time knee_angle_r pelvis_tx\n" +
               "".join(f"{t} {angle} {translation}\n" for t, angle, translation in
                       zip((2, 2.1, 2.4), angles, (0.1, 0.2, 0.3))))
        manifest, trc, mot_path = complete_native_fixture(root, trc_text(), mot, through=through)
        if through == "kinematics":
            # The general fixture repeats TRC bytes for filtering and augmentation.
            # Give the native loader an unambiguous, genuinely bound source revision.
            augmented = root / "pose-3d/fixture_filt_LSTM.trc"
            augmented.write_text(trc_text().replace("factory_trial", "generated_augmented"), encoding="utf-8")
            run = json.loads(manifest.read_text())
            run["stages"][6]["artifacts"][0]["sha256"] = sha256_file(augmented)
            run["stages"][7]["quality"]["consumed_trc"] = copy.deepcopy(run["stages"][6]["artifacts"][0])
            manifest.write_text(json.dumps(run), encoding="utf-8")
            trc = augmented
        exported = motion(trc, mot_path if through == "kinematics" else None, run_manifest=manifest)
        (root / "exports").mkdir()
        (root / "exports" / "generated.motion.json").write_text(json.dumps(exported), encoding="utf-8")
        return root

    def compare(self):
        self.index.reindex()
        return self.index.compare_sessions("a", "b")

    def test_matching_verified_angular_sources_have_descriptive_endpoints(self):
        a = self.make_session("a"); self.make_session("b")
        result = self.compare()
        self.assertTrue(result["compatible"], result["reason"])
        research = result["research_measurements"]
        self.assertEqual(research["status"], "AVAILABLE")
        self.assertEqual(research["uncertainty"]["status"], "UNAVAILABLE")
        self.assertFalse(result["clinical_accuracy_verified"])
        self.assertEqual(len(research["coordinates"]), 1)
        coordinate = research["coordinates"][0]
        self.assertEqual((coordinate["name"], coordinate["unit"]), ("knee_angle_r", "deg"))
        self.assertEqual(coordinate["session_1"]["min"], 0.2)
        self.assertEqual(coordinate["session_1"]["max"], 0.8)
        self.assertAlmostEqual(coordinate["session_1"]["excursion"], 0.6)
        self.assertIn("model_sha256", research["sessions"][0]["source_revision"])
        # Existing immutable source artifacts remain unchanged when comparison is repeated.
        before = {p: p.read_bytes() for p in a.rglob("*") if p.is_file()}
        self.index.compare_sessions("a", "b")
        self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))

    def test_legacy_metadata_absence_never_manufactures_identity_or_zero(self):
        self.make_session("a", metadata=False); self.make_session("b")
        result = self.compare()
        self.assertFalse(result["compatible"])
        self.assertEqual(result["research_measurements"]["status"], "UNAVAILABLE")
        self.assertEqual(result["research_measurements"]["coordinates"], [])

    def test_task_and_native_units_mismatches_are_rejected(self):
        metadata = confirmed_metadata(); metadata["task_id"] = "different-task"
        self.make_session("a"); self.make_session("b", metadata=metadata, degrees="no")
        result = self.compare()
        self.assertFalse(result["compatible"])
        self.assertIn("task_id", result["reason"])
        self.assertIn("units", result["reason"])
        self.assertEqual(result["research_measurements"]["coordinates"], [])

    def test_changed_model_bytes_cannot_reuse_matching_claimed_digest(self):
        self.make_session("a"); b = self.make_session("b")
        self.index.reindex()
        (b / "kinematics/fixture.osim").write_text("changed", encoding="utf-8")
        result = self.index.compare_sessions("a", "b")
        self.assertFalse(result["compatible"])
        self.assertEqual(result["research_measurements"]["status"], "UNAVAILABLE")

    def test_marker_only_source_has_no_invented_angular_measurement(self):
        self.make_session("a", through="filtering"); self.make_session("b", through="filtering")
        result = self.compare()
        self.assertFalse(result["compatible"])
        self.assertEqual(result["research_measurements"]["coordinates"], [])

    def test_test_only_marker_cannot_enter_real_comparison(self):
        self.make_session("a"); b = self.make_session("b")
        (b / "TEST-ONLY-NOT-CALIBRATED.txt").write_text("generated test fixture", encoding="utf-8")
        result = self.compare()
        self.assertFalse(result["compatible"])
        self.assertEqual(result["research_measurements"]["coordinates"], [])

    def test_finite_source_values_cannot_emit_infinite_excursion(self):
        self.make_session("a", angles=(-1e308, 1e308, 0))
        self.make_session("b", angles=(-1e308, 1e308, 0))
        result = self.compare()
        self.assertFalse(result["compatible"])
        self.assertEqual(result["research_measurements"]["status"], "UNAVAILABLE")
        self.assertEqual(result["research_measurements"]["coordinates"], [])

