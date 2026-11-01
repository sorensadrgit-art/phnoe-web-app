"""Generated fixtures with actual KineLab backend calls; no native stages."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli_anything.kinelab.core.operator import inspect_package, quality, verify_evidence
from cli_anything.kinelab.utils.kinelab_backend import refuse_live_path, source_identity, workspace_root

WORKSPACE = Path(__file__).resolve().parents[4]


class TestCore(unittest.TestCase):
    def test_quality_plan_is_not_execution(self):
        result = quality(WORKSPACE, ["python-syntax"], execute=False)
        self.assertEqual(result["status"], "NOT_RUN")
        self.assertEqual(result["schema"], "kinelab.quality-checks.v2")
        self.assertTrue(all(c["status"] == "NOT_RUN" for c in result["checks"]))

    def test_broad_or_mutating_checks_are_rejected(self):
        for check in ("python-tests", "desktop-build", "cloud-build", "security-advisories"):
            with self.subTest(check=check), self.assertRaisesRegex(ValueError, "bounded"):
                quality(WORKSPACE, [check], execute=True)

    def test_missing_backend_is_an_error(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError, "workspace"):
            quality(Path(folder), ["python-runtime"], execute=False)

    def test_package_inspection_preserves_manifest_and_does_not_claim_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "DISTRIBUTION-MANIFEST.json"
            path.write_text(json.dumps({"verification_status": "SOFTWARE_BUILD_VERIFIED", "files": []}), encoding="utf-8")
            before = path.read_bytes()
            result = inspect_package(WORKSPACE, path)
            self.assertEqual(result["stored_claims"]["verification_status"], "SOFTWARE_BUILD_VERIFIED")
            self.assertEqual(result["payload_verification"], "NOT_RUN")
            self.assertEqual(result["sha256"], hashlib.sha256(before).hexdigest())
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_package_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "DISTRIBUTION-MANIFEST.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                inspect_package(WORKSPACE, path)

    def test_real_evidence_backend_rejects_generated_bad_archive_without_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "generated-invalid.zip"
            path.write_bytes(b"synthetic invalid archive")
            before = path.read_bytes()
            result, code = verify_evidence(WORKSPACE, path)
            self.assertEqual(code, 1)
            self.assertFalse(result["ok"])
            self.assertEqual(result["failures"][0]["code"], "EVIDENCE_CORRUPT")
            self.assertEqual(path.read_bytes(), before)

    def test_real_quality_runtime_probe_has_explicit_scope(self):
        result = quality(WORKSPACE, ["python-runtime"], execute=True)
        self.assertEqual(result["status"], "PASS")
        selected = [c for c in result["checks"] if c["selected"]]
        self.assertEqual([c["id"] for c in selected], ["python-runtime"])
        self.assertTrue(result["limitations"])

class TestBoundaryAndIdentity(unittest.TestCase):
    def test_live_legacy_checkout_is_refused_before_filesystem_access(self):
        for path in (Path(r"C:\Users\soren\Documents\Projects\KineLab-PT-DualCam"),
                     Path(r"C:\Users\soren\Documents\Projects\kinelab-pt-dualcam\viewer")):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "LIVE_PATH_REFUSED"):
                workspace_root(path)

    def test_data_roots_databases_and_secrets_are_refused_as_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            candidates = [Path(folder) / "KineLab-PT-DualCam" / "DISTRIBUTION-MANIFEST.json",
                          Path(folder) / "KineLabPT-Candidate-M1" / "data" / "DISTRIBUTION-MANIFEST.json",
                          Path(folder) / "sessions.sqlite", Path(folder) / "kinelab.db", Path(folder) / ".env"]
            for path in candidates:
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "LIVE_PATH_REFUSED"):
                    refuse_live_path(path)

    def test_configured_candidate_data_root_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            data_root = Path(folder) / "generated-data-root"
            with mock.patch.dict(os.environ, {"KINELAB_CANDIDATE_DATA_ROOT": str(data_root)}), \
                    self.assertRaisesRegex(ValueError, "LIVE_PATH_REFUSED"):
                refuse_live_path(data_root / "DISTRIBUTION-MANIFEST.json")

    def test_identity_names_workspace_head_and_current_source_hashes(self):
        identity = source_identity(WORKSPACE)
        self.assertEqual(identity["workspace"], str(WORKSPACE))
        self.assertRegex(identity["git_head"], r"^[0-9a-f]{40}$")
        backend = WORKSPACE / "tools" / "check_quality.py"
        self.assertEqual(identity["source_sha256"]["tools/check_quality.py"],
                         hashlib.sha256(backend.read_bytes()).hexdigest())
        self.assertIn("cli_anything/kinelab/kinelab_cli.py", identity["harness_sha256"])
        self.assertEqual(identity["clinical_validation"], "UNVERIFIED")

    def test_quality_uses_explicit_scientific_runtime_not_harness_interpreter(self):
        result = quality(WORKSPACE, ["python-runtime"], execute=False)
        self.assertEqual(result["interpreters"]["scientific_python"],
                         str(WORKSPACE / ".venv" / "Scripts" / "python.exe"))
        self.assertEqual(result["harness_identity"]["git_head"], source_identity(WORKSPACE)["git_head"])

class TestResolvedLivePathRefusal(unittest.TestCase):
    def test_alternate_data_stream_suffix_is_refused(self):
        for path in (r"C:\Users\soren\Documents\Projects\KineLab-PT-DualCam::$INDEX_ALLOCATION",
                     r"C:\generated\folder:stream"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "LIVE_PATH_REFUSED"):
                refuse_live_path(Path(path))

    def test_short_name_component_is_refused(self):
        for path in (r"C:\Users\soren\Documents\Projects\KINELA~1", r"C:\generated\PROGRA~2\x.json"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "LIVE_PATH_REFUSED"):
                refuse_live_path(Path(path))

    def _link(self, target: Path, link: Path) -> None:
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        except (ImportError, OSError):
            os.symlink(target, link, target_is_directory=True)

    def test_junction_to_refused_location_is_refused_after_resolution(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("KineLab-PT-DualCam", "KineLabPT-Candidate-M1"):
                target = Path(folder) / name
                target.mkdir()
                link = Path(folder) / ("innocent-" + name[-4:])
                self._link(target, link)
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "LIVE_PATH_REFUSED"):
                    refuse_live_path(link / "DISTRIBUTION-MANIFEST.json")
                with self.subTest(workspace=name), self.assertRaisesRegex(ValueError, "LIVE_PATH_REFUSED"):
                    workspace_root(link)

    def test_ordinary_temporary_path_is_not_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "DISTRIBUTION-MANIFEST.json"
            self.assertEqual(refuse_live_path(path), Path(os.path.abspath(path)))


if __name__ == "__main__":
    unittest.main()
