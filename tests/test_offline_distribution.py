"""Packaging tests use temporary fixtures, never existing release artifacts."""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import build_offline_distribution as package


class TestOfflineDistribution(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kinelab-package-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for source in package.ROOT.glob("*.py"):
            shutil.copy2(source, self.source / source.name)
        for relative, content in {
            "viewer/dist/index.html": "<title>SYNTHETIC PACKAGE FIXTURE</title>",
            "assets/kinelab-pt.ico": "synthetic icon",
            "RUNBOOK.md": "# SYNTHETIC RUNBOOK FIXTURE\n",
            "requirements.lock.txt": "# synthetic inventory\n",
            "environment.json": '{"scope":"synthetic fixture"}',
            "model-cache.json": json.dumps({"files": [{"path": "C:\\Users\\fixture-user\\.cache\\synthetic.onnx",
                                                       "size_bytes": 3, "sha256": "c" * 64}]}),
            "viewer/package.json": '{"name":"synthetic-fixture"}',
            "viewer/src/main.jsx": "// SYNTHETIC FRONTEND SOURCE FIXTURE\n",
        }.items():
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        (self.source / "models").mkdir()
        shutil.copy2(package.ROOT / "models/pose-models.json", self.source / "models/pose-models.json")
        (self.source / "tools").mkdir()
        shutil.copy2(Path(package.__file__), self.source / "tools/build_offline_distribution.py")
        self.target = self.source / "dist/package"
        self.archive = self.source / "dist/package.zip"
        patches = patch.multiple(package, ROOT=self.source, TARGET_DIR=self.target, ZIP_PATH=self.archive,
                                 FRONTEND_DIST=None, FRONTEND_INPUTS=None)
        patches.start()
        self.addCleanup(patches.stop)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def stage(self):
        package.copy_application_files()
        package.write_launcher_scripts()

    def test_shortcut_installer_never_overwrites_existing_shortcuts(self):
        self.stage()
        script = (self.target / "Install-DesktopShortcut.ps1").read_text(encoding="utf-8")
        self.assertIn("KineLab PT Candidate.lnk", script)
        self.assertIn("Refusing to overwrite", script)
        self.assertNotIn("$Force", script)
        self.assertNotIn('"KineLab PT.lnk"', script[script.index("CreateShortcut"):])
        readme = (self.target / "README-OFFLINE-INSTALL.md").read_text(encoding="utf-8")
        self.assertIn("KineLab PT Candidate", readme)

    def test_generated_launchers_disable_bytecode_writes_and_bind_shortcut_arguments(self):
        self.stage()
        batch = (self.target / "Start-KineLabPT.bat").read_text(encoding="utf-8")
        invocations = [line.strip() for line in batch.splitlines() if "t6_launcher.py" in line]
        self.assertEqual(invocations, ["%PYTHON_EXE% -B t6_launcher.py %*"])
        script = (self.target / "Install-DesktopShortcut.ps1").read_text(encoding="utf-8")
        self.assertNotRegex(script, r"\$args\b")
        self.assertIn('$target = Join-Path $ScriptDir "Start-KineLabPT.bat"\n    $launcherArguments = ""', script)
        self.assertIn('$target = $pythonw\n    $launcherArguments = "-B `"$LauncherPy`""', script)
        self.assertEqual(script.count("$Shortcut.Arguments"), 1)
        self.assertIn("if ($launcherArguments) { $Shortcut.Arguments = $launcherArguments }", script)

    def test_docs_with_private_user_paths_are_excluded_and_reported(self):
        docs = self.source / "docs"
        docs.mkdir()
        (docs / "clean.md").write_text("# Clean synthetic guide\n", encoding="utf-8")
        (docs / "private.md").write_text("See C:\\Users\\fixture-user\\secret for details\n",
                                         encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            package.check_prerequisites()
        self.assertIn("private.md", output.getvalue())
        self.stage()
        self.assertTrue((self.target / "docs/clean.md").is_file())
        self.assertFalse((self.target / "docs/private.md").exists())

    def test_stale_public_copy_is_accepted_but_stale_generated_file_is_refused(self):
        record = "dist/frontend-stale-inputs.json"
        (self.source / "viewer/public").mkdir(parents=True, exist_ok=True)
        (self.source / "viewer/public/favicon.svg").write_text("<svg>SYNTHETIC</svg>", encoding="utf-8")
        self.assertEqual(package.main(["--capture-frontend-inputs", record]), 0)
        captured = (self.source / record).stat().st_mtime
        build = self.source / "dist/frontend-stale"
        build.mkdir()
        index = build / "index.html"
        index.write_text("<title>SYNTHETIC STAND-IN</title>", encoding="utf-8")
        copied = build / "favicon.svg"
        shutil.copy2(self.source / "viewer/public/favicon.svg", copied)
        stale = captured - 100
        os.utime(copied, (stale, stale))
        with patch.object(package, "FRONTEND_DIST", build), patch.object(
                package, "FRONTEND_INPUTS", self.source / record):
            package.check_prerequisites()
            os.utime(index, (stale, stale))
            with self.assertRaisesRegex(ValueError, "predates"):
                package.check_prerequisites()

    def test_sha256_file(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"Hello KineLab Distribution")
            temp_path = Path(f.name)
        try:
            digest = package.sha256_file(temp_path)
            self.assertEqual(len(digest), 64)
            # Known sha256 for "Hello KineLab Distribution"
            import hashlib
            expected = hashlib.sha256(b"Hello KineLab Distribution").hexdigest()
            self.assertEqual(digest, expected)
        finally:
            temp_path.unlink(missing_ok=True)

    def test_existing_target_is_preserved(self):
        self.target.mkdir(parents=True)
        sentinel = self.target / "keep.txt"
        sentinel.write_bytes(b"existing artifact")
        with self.assertRaises(FileExistsError):
            package.copy_application_files()
        self.assertEqual(sentinel.read_bytes(), b"existing artifact")

    def test_existing_archive_blocks_staging_and_archive_overwrite(self):
        self.archive.parent.mkdir(parents=True)
        self.archive.write_bytes(b"existing archive")
        with self.assertRaises(FileExistsError):
            package.copy_application_files()
        self.assertFalse(self.target.exists())
        with self.assertRaises(FileExistsError):
            package.create_zip_archive()
        self.assertEqual(self.archive.read_bytes(), b"existing archive")

    def test_destination_outside_workspace_dist_is_rejected(self):
        for target in (self.root / "outside", self.source / "dist", self.source / "dist/../../escape"):
            with self.subTest(target=target), patch.object(package, "TARGET_DIR", target):
                with self.assertRaisesRegex(ValueError, "destination|dist"):
                    package.copy_application_files()
                self.assertFalse((target / "app").exists())

    def directory_link(self, link, destination):
        link.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(destination)],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            link.symlink_to(destination, target_is_directory=True)
        self.addCleanup(lambda: os.rmdir(link) if link.exists() else None)

    def test_junction_source_and_destination_are_rejected_without_copy(self):
        outside = self.root / "benign-outside"
        outside.mkdir()
        (outside / "sentinel.txt").write_bytes(b"must not copy")
        link = self.source / "assets/external"
        self.directory_link(link, outside)
        with self.assertRaisesRegex(ValueError, "link|reparse|junction"):
            package.copy_application_files()
        self.assertFalse(self.target.exists())
        os.rmdir(link)
        link = self.source / "dist/redirect"
        self.directory_link(link, outside)
        with patch.object(package, "TARGET_DIR", link / "package"), self.assertRaisesRegex(ValueError, "link|reparse|junction"):
            package.copy_application_files()
        self.assertEqual((outside / "sentinel.txt").read_bytes(), b"must not copy")
        self.assertFalse((outside / "package").exists())

    def test_manifest_binds_source_build_and_observed_git_state(self):
        self.stage()
        package.generate_manifest()
        data = json.loads((self.target / "DISTRIBUTION-MANIFEST.json").read_text())
        provenance = data["provenance"]
        self.assertEqual(len(provenance["source_sha256"]), 64)
        self.assertEqual(len(provenance["frontend_build_sha256"]), 64)
        self.assertEqual(provenance["frontend_source_build_match"], "UNVERIFIED")
        self.assertEqual(provenance["git"]["status"], "UNAVAILABLE")
        self.assertIsNone(provenance["git"]["dirty"])
        with (self.source / "t6_service.py").open("a", encoding="utf-8") as stream:
            stream.write("\n# changed after staging\n")
        with self.assertRaisesRegex(ValueError, "source|Source"):
            package.generate_manifest()

    def test_staged_junction_is_rejected_before_archive_creation(self):
        self.stage()
        outside = self.root / "benign-payload"
        outside.mkdir()
        (outside / "sentinel.txt").write_bytes(b"must not archive")
        self.directory_link(self.target / "app/assets/external", outside)
        with self.assertRaisesRegex(ValueError, "link|reparse|junction"):
            package.create_zip_archive()
        self.assertFalse(self.archive.exists())

    def fresh_frontend(self, name="frontend-build-1"):
        """Synthetic stand-in for a separately built frontend; never a release build."""
        record = f"dist/{name}-inputs.json"
        self.assertEqual(package.main(["--capture-frontend-inputs", record]), 0)
        build = self.source / "dist" / name
        build.mkdir(parents=True)
        (build / "index.html").write_text("<title>SYNTHETIC STAND-IN FRONTEND BUILD</title>", encoding="utf-8")
        return ["--frontend-dist", f"dist/{name}", "--frontend-inputs", record]

    def test_explicit_cli_build_preserves_output_and_records_git_observation(self):
        observation = {"status": "OBSERVED", "head": "a" * 40, "dirty": True,
                       "status_sha256": "b" * 64}
        frontend = self.fresh_frontend()
        with patch.object(package, "git_identity", return_value=observation):
            self.assertEqual(package.main(["--out", "dist/unique-fixture", *frontend]), 0)
            archive = self.source / "dist/unique-fixture.zip"
            before = archive.read_bytes()
            manifest = json.loads((self.source / "dist/unique-fixture/DISTRIBUTION-MANIFEST.json").read_text())
            self.assertEqual(manifest["provenance"]["git"], observation)
            self.assertEqual(manifest["provenance"]["frontend_source_build_match"],
                             "INPUTS_MATCH_RECORDED_BUILD_UNREPRODUCED")
            self.assertEqual(manifest["runtime_validation_status"], "NOT_RUN")
            staged = self.source / "dist/unique-fixture/app/viewer/dist/index.html"
            self.assertIn("SYNTHETIC STAND-IN", staged.read_text(encoding="utf-8"))
            self.assertEqual(package.main(["--out", "dist/unique-fixture", *frontend]), 1)
            self.assertEqual(archive.read_bytes(), before)

    def test_cli_requires_explicit_fresh_frontend_bound_to_captured_sources(self):
        observation = {"status": "OBSERVED", "head": "a" * 40, "dirty": False, "status_sha256": "b" * 64}
        frontend = self.fresh_frontend()
        with patch.object(package, "git_identity", return_value=observation):
            self.assertEqual(package.main(["--out", "dist/no-frontend"]), 1)
            self.assertEqual(package.main(["--out", "dist/no-inputs", *frontend[:2]]), 1)
            self.assertEqual(package.main(["--out", "dist/frontend-build-1/inside", *frontend]), 1)
            (self.source / "viewer/src/main.jsx").write_text("// changed after capture\n", encoding="utf-8")
            self.assertEqual(package.main(["--out", "dist/changed-source", *frontend]), 1)
            self.assertEqual(package.main(["--capture-frontend-inputs", frontend[3]]), 1)
        for name in ("no-frontend", "no-inputs", "changed-source", "frontend-build-1/inside"):
            self.assertFalse((self.source / "dist" / name).exists(), name)
            self.assertFalse((self.source / "dist" / (name + ".zip")).exists(), name)

    def test_cli_refuses_missing_git_provenance_before_staging(self):
        self.assertEqual(package.main(["--out", "dist/no-git-fixture", *self.fresh_frontend()]), 1)
        self.assertFalse((self.source / "dist/no-git-fixture").exists())

    def test_runtime_closure_includes_transitive_imports_and_prior_payload(self):
        closure = set(package.runtime_modules(self.source))
        for required in ("kinematics_quality.py", "runtime_config.py", "unified_service.py",
                         "t6_launcher.py", "t6_server.py", "t6_service.py", "capture_station_gui.py"):
            self.assertIn(required, closure)
        self.assertNotIn("launch_kinelab_unified.py", closure)
        self.stage()
        for name in closure:
            self.assertEqual(package.sha256_file(self.target / "app" / name),
                             package.sha256_file(self.source / name))

    def test_runtime_list_covers_local_imports_and_script_entry_points(self):
        shipped, missing = set(package.runtime_modules(self.source)), set()
        for name in shipped:
            tree = ast.parse((self.source / name).read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                dependencies = []
                if isinstance(node, ast.Import):
                    dependencies = [alias.name.split(".")[0] + ".py" for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    dependencies = [node.module.split(".")[0] + ".py"]
                elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                      and node.value.endswith(".py") and Path(node.value).name == node.value):
                    dependencies = [node.value]
                missing.update((name, dep) for dep in dependencies
                               if (self.source / dep).is_file() and dep not in shipped)
        self.assertEqual(sorted(missing), [])

    def test_prerequisites_reject_missing_model_manifest(self):
        (self.source / "models/pose-models.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "pose-models.json"):
            package.check_prerequisites()

    def test_new_local_import_is_staged_through_derived_closure(self):
        with (self.source / "t6_service.py").open("a", encoding="utf-8") as stream:
            stream.write("\nimport added_package_dependency\n")
        (self.source / "added_package_dependency.py").write_text("VALUE = 1\n", encoding="utf-8")
        package.check_prerequisites()
        self.stage()
        self.assertTrue((self.target / "app/added_package_dependency.py").is_file())

    def test_prerequisites_reject_unstaged_package_import_and_report_all_missing(self):
        with (self.source / "t6_service.py").open("a", encoding="utf-8") as stream:
            stream.write("\nimport omitted_package_dependency\n")
        (self.source / "omitted_package_dependency").mkdir()
        (self.source / "omitted_package_dependency/__init__.py").write_text("", encoding="utf-8")
        (self.source / "capture_station_gui.py").unlink()
        (self.source / "models/pose-models.json").unlink()
        with self.assertRaises(RuntimeError) as raised:
            package.check_prerequisites()
        for expected in ("omitted_package_dependency/", "capture_station_gui.py", "pose-models.json"):
            self.assertIn(expected, str(raised.exception))
        self.assertFalse(self.target.exists())

    def test_provisioning_record_is_sanitized_and_reports_unprovisioned_state(self):
        self.stage()
        package.generate_manifest()
        self.assertFalse((self.target / "app/model-cache.json").exists())
        self.assertFalse((self.target / "app/environment.json").exists())
        record = json.loads((self.target / "RUNTIME-PROVISIONING.json").read_text(encoding="utf-8"))
        manifest = json.loads((self.source / "models/pose-models.json").read_text(encoding="utf-8"))
        self.assertEqual([item["expected_sha256"] for item in record["model_set"]["weights"]],
                         [item["sha256"] for item in manifest["models"]])
        self.assertTrue(all(item["provisioning"] == "NOT_PROVISIONED" for item in record["model_set"]["weights"]))
        self.assertEqual(record["observed_workstation_model_cache"], [])
        self.assertEqual(record["workstation_model_cache_status"], "NOT_INSPECTED_PRIVATE_INPUT")
        self.assertNotIn("synthetic.onnx", json.dumps(record))
        self.assertEqual(set(record["native"].values()), {"NOT_PROVISIONED"})
        self.assertEqual(record["clinical_validation_status"], "UNVERIFIED")
        for name in ("RUNTIME-PROVISIONING.json", "SOURCE-PROVENANCE.json", "DISTRIBUTION-MANIFEST.json"):
            content = (self.target / name).read_text(encoding="utf-8")
            self.assertNotRegex(content, r"(?<![A-Za-z])[A-Za-z]:(\\\\|/)|fixture-user", name)
            self.assertNotIn(self.root.name, content, name)

    def test_private_model_inventory_is_never_opened_or_reported(self):
        # Invented TEST_ONLY inventory. Refuse Path.open reads.
        original_open = Path.open
        forbidden = {self.source / name for name in package.WORKSTATION_INVENTORIES}
        def guarded_open(path, *args, **kwargs):
            if path in forbidden:
                raise AssertionError("TEST_ONLY_PRIVATE_INPUT_READ")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", guarded_open):
            self.stage()
            package.generate_manifest()
        record = json.loads((self.target / "RUNTIME-PROVISIONING.json").read_text(encoding="utf-8"))
        self.assertEqual(record["observed_workstation_model_cache"], [])
        self.assertEqual(record["workstation_model_cache_status"], "NOT_INSPECTED_PRIVATE_INPUT")
        self.assertNotIn("synthetic.onnx", json.dumps(record))
        self.assertNotIn("fixture-user", json.dumps(record))

    def test_unapproved_public_model_fields_fail_before_any_staging(self):
        path = self.source / "models/pose-models.json"
        approved = path.read_bytes()
        original = json.loads(approved)
        mutations = (
            lambda doc: doc.update(TEST_ONLY_UNKNOWN="TEST_ONLY_PRIVATE_MARKER"),
            lambda doc: doc.update(id="TEST_ONLY_PRIVATE_MARKER"),
            lambda doc: doc.update(source_license="TEST_ONLY_PRIVATE_MARKER"),
            lambda doc: doc["runtime"].update(TEST_ONLY_UNKNOWN="TEST_ONLY_PRIVATE_MARKER"),
            lambda doc: doc["models"][0].update(filename="../TEST_ONLY_PRIVATE_MARKER"),
            lambda doc: doc["models"][0].update(path="TEST_ONLY_PRIVATE_MARKER"),
            lambda doc: doc["models"][0].update(url="file:///TEST_ONLY_PRIVATE_MARKER"),
            lambda doc: doc["models"][0].update(sha256="TEST_ONLY_PRIVATE_MARKER"),
            lambda doc: doc["models"][0].update(bytes=True),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate.__code__.co_firstlineno):
                document = json.loads(approved)
                mutate(document)
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "^PUBLIC_MODEL_METADATA_NOT_APPROVED$"):
                    package.copy_application_files()
                self.assertFalse(self.target.exists())
                self.assertFalse(self.archive.exists())
        path.write_bytes(approved)
        self.assertEqual(json.loads(path.read_bytes()), original)

    def test_same_size_and_duplicate_key_model_metadata_are_not_approved(self):
        path = self.source / "models/pose-models.json"
        approved = path.read_bytes()
        attacks = (
            approved.replace(b"detector.onnx", b"TEST_ONLY.onx", 1),
            b'{"TEST_ONLY_UNKNOWN":"TEST_ONLY_PRIVATE_MARKER",'
            b'"id":"TEST_ONLY_PRIVATE_MARKER",' + approved.lstrip()[1:],
        )
        self.assertEqual(len(attacks[0]), len(approved))
        for raw in attacks:
            with self.subTest(size=len(raw)):
                path.write_bytes(raw)
                with self.assertRaisesRegex(ValueError, "^PUBLIC_MODEL_METADATA_NOT_APPROVED$"):
                    package.runtime_provisioning()
                self.assertFalse(self.target.exists())
        path.write_bytes(approved)

    def test_copy_and_report_read_public_model_spec_once(self):
        model_path = self.source / "models/pose-models.json"
        approved = model_path.read_bytes()
        original_open, original_hash = Path.open, package.sha256_file
        specification_reads, hash_depth = [], 0

        def observed_open(path, *args, **kwargs):
            if path == model_path and hash_depth == 0:
                specification_reads.append(path)
            return original_open(path, *args, **kwargs)

        def observed_hash(path):
            nonlocal hash_depth
            hash_depth += 1
            try:
                return original_hash(path)
            finally:
                hash_depth -= 1

        # Hash-only provenance checks still run fully; count actual content captures.
        with patch.object(package, "sha256_file", side_effect=observed_hash), \
                patch.object(Path, "open", observed_open):
            package.copy_application_files()

        self.assertEqual(specification_reads, [model_path])
        staged = (self.target / "app/models/pose-models.json").read_bytes()
        self.assertEqual(staged, approved)
        manifest = json.loads(staged)
        record = json.loads((self.target / "RUNTIME-PROVISIONING.json").read_text(encoding="utf-8"))
        self.assertEqual(record["model_set"]["id"], manifest["id"])
        self.assertEqual(record["model_set"]["license"], manifest["source_license"])
        self.assertEqual(record["model_set"]["runtime"], manifest["runtime"])
        self.assertEqual(record["model_set"]["weights"], [
            {"filename": item["filename"], "expected_sha256": item["sha256"],
             "expected_bytes": item["bytes"], "archive_sha256": item.get("archive_sha256"),
             "source_url": item["url"], "provisioning": "NOT_PROVISIONED"}
            for item in manifest["models"]
        ])
        self.assertEqual(record, package.runtime_provisioning())

    def test_stages_model_manifest_without_weights(self):
        self.stage()
        self.assertEqual((self.target / "app/models/pose-models.json").read_bytes(),
                         (self.source / "models/pose-models.json").read_bytes())
        self.assertFalse((self.target / "app/models/pose-v1").exists())

    def test_verified_manifest_and_zip_never_claim_software_or_runtime_validation(self):
        self.stage()
        package.generate_manifest()
        manifest = self.target / "DISTRIBUTION-MANIFEST.json"
        self.assertEqual(json.loads(manifest.read_text())["verification_status"], "PACKAGE_INTEGRITY_NOT_CHECKED")
        package.verify_distribution_integrity()
        data = json.loads(manifest.read_text())
        self.assertEqual(data["verification_status"], "PACKAGE_INTEGRITY_VERIFIED")
        self.assertEqual(data["software_build_status"], "NOT_RUN")
        self.assertEqual(data["runtime_validation_status"], "NOT_RUN")
        self.assertEqual(data["physical_validation_status"], "BLOCKED_ON_PHYSICAL_EVIDENCE")
        self.assertEqual(data["clinical_validation_status"], "UNVERIFIED")
        package.create_zip_archive()
        with zipfile.ZipFile(self.archive) as archive:
            saved = json.loads(archive.read(package.PACKAGE_NAME + "/DISTRIBUTION-MANIFEST.json"))
            self.assertEqual(saved, data)

    def test_integrity_rejects_tampered_or_unlisted_files(self):
        self.stage()
        package.generate_manifest()
        path = self.target / "app/t6_service.py"
        original = path.read_bytes()
        path.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            package.verify_distribution_integrity()
        path.write_bytes(original)
        (self.target / "unlisted.txt").write_text("extra", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest|unlisted"):
            package.verify_distribution_integrity()

    def test_guidance_matches_unprovisioned_runtime_and_storage(self):
        self.stage()
        text = (self.target / "README-OFFLINE-INSTALL.md").read_text(encoding="utf-8")
        for required in ("KineLabPT-Candidate-M1", "--data-root", "never discovered or migrated", "ffmpeg", "ffprobe", "Blender", "OpenSim", "Pose2Sim",
                         "UNVERIFIED", "not provisioned", "LOCALAPPDATA"):
            self.assertIn(required, text)
        self.assertNotIn("Program Files", text)
        self.assertNotIn("stored strictly", text)
        self.assertNotIn("uses `app/projects`", text)

    def test_packaged_candidate_notices_supersede_historical_install_and_acceptance_claims(self):
        repository_docs = Path(__file__).resolve().parents[1] / "docs"
        docs = self.source / "docs"
        docs.mkdir()
        names = ("CLEAN_INSTALL_REPORT.md", "RELEASE_ACCEPTANCE_MATRIX.md", "VERCEL_WEB_DEMO.md")
        for name in names:
            shutil.copy2(repository_docs / name, docs / name)

        self.stage()
        for name in names:
            with self.subTest(document=name):
                staged = self.target / "docs" / name
                self.assertTrue(staged.is_file(), "Reviewed public guidance must ship with the package")
                self.assertEqual(staged.read_bytes(), (repository_docs / name).read_bytes())
                text = staged.read_text(encoding="utf-8")
                marker = "<!-- CURRENT-CANDIDATE-NOTICE:END -->"
                self.assertIn(marker, text, "Historical instructions require a leading candidate notice")
                notice, history = text.split(marker, 1)
                self.assertTrue(notice.startswith("# Current candidate package notice\n"))
                for required in ("Current candidate acceptance: NOT_GRANTED",
                                 "Clean-machine validation: NOT_RUN",
                                 "Physical validation: BLOCKED_ON_PHYSICAL_EVIDENCE",
                                 "Clinical validation: UNVERIFIED", "KineLab PT Candidate",
                                 "TEST_ONLY", "README-OFFLINE-INSTALL.md", "app/RUNBOOK.md"):
                    self.assertIn(required, notice)
                self.assertIn("original shortcut", notice)
                self.assertIn("\n# KineLab PT", history, "Retain the historical source document")

    def test_isolated_staged_service_constructs_with_unprovisioned_models(self):
        self.stage()
        scratch = self.root / "empty-runtime"
        scratch.mkdir()
        env = os.environ.copy()
        env.update(LOCALAPPDATA=str(scratch / "local"), MPLCONFIGDIR=str(scratch / "matplotlib"),
                   TEMP=str(scratch), TMP=str(scratch), PYTHONUTF8="1",
                   KINELAB_CANDIDATE_DATA_ROOT=str(scratch / "generated-data-root"))
        env.pop("PYTHONPATH", None)
        script = '''
import pathlib, sys
app, scratch = map(pathlib.Path, sys.argv[1:])
def forbid_external(event, args):
    if event in {"socket.connect", "socket.bind", "subprocess.Popen"}:
        raise AssertionError("External operation forbidden: " + event)
sys.addaudithook(forbid_external)
sys.path.insert(0, str(app))
import t6_launcher, t6_server, t6_service
import runtime_config
data_root = runtime_config.ensure_data_root()
assert data_root == (scratch / "generated-data-root").resolve(), data_root
service = t6_service.IntegratedService(projects_root=data_root, pose_models=scratch / "absent-models")
try:
    assert service.sessions() == []
    assert service.pose_inference._pipeline is None
    try:
        service.pose_inference._load()
    except FileNotFoundError as error:
        assert str(error) == "MODELS_UNAVAILABLE"
    else:
        raise AssertionError("Missing weights must remain unavailable")
    for module in (t6_launcher, t6_server, t6_service, runtime_config):
        assert pathlib.Path(module.__file__).resolve().parent == app.resolve()
    assert not (app / "projects").exists()
    assert not (scratch / "absent-models").exists()
    print("ISOLATED_PACKAGE_CONSTRUCTION_OK; MODELS_UNAVAILABLE; NO_NATIVE_STAGE")
finally:
    service.close()
'''
        result = subprocess.run([sys.executable, "-I", "-B", "-c", script,
                                 str(self.target / "app"), str(scratch)], cwd=scratch, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ISOLATED_PACKAGE_CONSTRUCTION_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
