"""Generated TEST_ONLY byte-admission fixtures; never launch an admitted executable."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import build_offline_distribution as package


class PreparedRuntimeAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kinelab-runtime-TEST_ONLY-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for path in package.ROOT.glob("*.py"):
            shutil.copy2(path, self.source / path.name)
        for relative, raw in {
            "viewer/dist/index.html": b"<title>TEST_ONLY</title>",
            "viewer/package.json": b'{"name":"TEST_ONLY"}',
            "viewer/src/main.jsx": b"// TEST_ONLY\n",
            "assets/kinelab-pt.ico": b"TEST_ONLY NOT AN ICON",
            "RUNBOOK.md": b"# TEST_ONLY",
            "requirements.lock.txt": b"TEST_ONLY_fixture==0.0.0\n",
        }.items():
            destination = self.source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
        self.input = self.root / "prepared-TEST_ONLY"
        self.input.mkdir()
        self.target = self.source / "dist/package"
        self.archive = self.source / "dist/package.zip"
        self.manifest = self.input / "prepared-runtime.json"
        self.files = {
            "runtime/python/python.exe": b"TEST_ONLY NOT EXECUTABLE python",
            "runtime/python/pythonw.exe": b"TEST_ONLY NOT EXECUTABLE pythonw",
            "runtime/bin/ffmpeg.exe": b"TEST_ONLY NOT EXECUTABLE ffmpeg",
            "runtime/bin/ffprobe.exe": b"TEST_ONLY NOT EXECUTABLE ffprobe",
            "runtime/licenses/TEST_ONLY.txt": b"TEST_ONLY NOT LICENSE CLEARANCE",
            "runtime/policy/dependencies.json": b'{"TEST_ONLY":"UNRESOLVED"}',
            "runtime/policy/cv2-provider.json": b'{"TEST_ONLY":"UNRESOLVED"}',
            "app/models/pose-v1/detector.onnx": b"TEST_ONLY NOT MODEL detector",
            "app/models/pose-v1/pose.onnx": b"TEST_ONLY NOT MODEL pose",
        }
        for relative, raw in self.files.items():
            path = self.input / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        model = {"id": "rtmlib-coco17-cpu-v1", "runtime": {}, "source_license": "TEST_ONLY",
                 "models": [{"filename": Path(path).name, "bytes": len(raw),
                             "sha256": hashlib.sha256(raw).hexdigest()}
                            for path, raw in self.files.items() if path.endswith(".onnx")]}
        model_path = self.source / "models/pose-models.json"
        model_path.parent.mkdir()
        model_path.write_text(json.dumps(model), encoding="utf-8")
        self.document = {
            "schema": "kinelab.prepared-runtime-input.v1",
            "profile": {"platform": "windows-amd64", "python_abi": "cp313",
                        "dependency_resolution_sha256":
                        hashlib.sha256(self.files["runtime/policy/dependencies.json"]).hexdigest(),
                        "cv2_provider_policy_sha256":
                        hashlib.sha256(self.files["runtime/policy/cv2-provider.json"]).hexdigest()},
            "source_artifact": {"kind": "PREPARED_TREE", "sha256": None,
                                "size_bytes": None, "source_reference": "TEST_ONLY"},
            "dependencies": ["TEST_ONLY_fixture==0.0.0"],
            "licenses": [{"id": "TEST_ONLY", "path": "runtime/licenses/TEST_ONLY.txt",
                          "source_reference": "TEST_ONLY",
                          "redistribution_evidence_reference": "TEST_ONLY"}],
            "entrypoints": {"python": "runtime/python/python.exe",
                            "pythonw": "runtime/python/pythonw.exe",
                            "ffmpeg": "runtime/bin/ffmpeg.exe", "ffprobe": "runtime/bin/ffprobe.exe"},
            "models": {"model_set_id": model["id"],
                       "model_manifest_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
                       "files": sorted(path for path in self.files if path.endswith(".onnx"))},
            "files": [{"path": path, "size_bytes": len(raw),
                       "sha256": hashlib.sha256(raw).hexdigest(), "license_id": "TEST_ONLY"}
                      for path, raw in self.files.items()],
        }
        self.save_manifest()
        patches = patch.multiple(package, ROOT=self.source, TARGET_DIR=self.target,
                                 ZIP_PATH=self.archive, FRONTEND_DIST=None, FRONTEND_INPUTS=None,
                                 # TEST_ONLY approval pins isolate invented non-executable fixtures.
                                 PUBLIC_MODEL_MANIFEST_SHA256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
                                 PUBLIC_MODEL_MANIFEST_BYTES=model_path.stat().st_size)
        patches.start()
        self.addCleanup(patches.stop)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def save_manifest(self):
        self.manifest.write_text(json.dumps(self.document), encoding="utf-8")

    def selected(self):
        # Existing public staging boundary remains callable before the new optional seam exists.
        return patch.object(package, "PREPARED_RUNTIME_MANIFEST", self.manifest, create=True)

    def refused_before_staging(self, code):
        before = {path.relative_to(self.input).as_posix(): path.read_bytes()
                  for path in self.input.rglob("*") if path.is_file()}
        with self.selected(), self.assertRaisesRegex(ValueError, "PREPARED_RUNTIME_" + code):
            package.copy_application_files()
        self.assertFalse(self.target.exists())
        self.assertFalse(self.archive.exists())
        self.assertEqual(before, {path.relative_to(self.input).as_posix(): path.read_bytes()
                                  for path in self.input.rglob("*") if path.is_file()})

    def test_00_explicit_missing_member_refuses_existing_public_stager_before_output(self):
        (self.input / "runtime/python/python.exe").unlink()
        self.refused_before_staging("INCOMPLETE")

    def test_01_unknown_schema_refuses_before_output(self):
        self.document["schema"] = "TEST_ONLY-unknown"
        self.save_manifest()
        self.refused_before_staging("SCHEMA")

    def test_02_declared_traversal_refuses_before_output(self):
        self.document["files"][0]["path"] = "runtime/../outside.exe"
        self.save_manifest()
        self.refused_before_staging("PATH")

    def test_03_case_duplicate_refuses_before_output(self):
        duplicate = dict(self.document["files"][0])
        duplicate["path"] = "runtime/python/PYTHON.EXE"
        self.document["files"].append(duplicate)
        self.save_manifest()
        self.refused_before_staging("DUPLICATE")

    def test_04_hash_mismatch_refuses_before_output(self):
        (self.input / "runtime/python/python.exe").write_bytes(b"TEST_ONLY MODIFIED")
        self.refused_before_staging("SIZE|HASH")

    def test_05_extra_secret_file_refuses_before_output(self):
        (self.input / "runtime/python/.env").write_bytes(b"TEST_ONLY SENTINEL")
        self.refused_before_staging("PATH")

    def test_06_missing_policy_binding_refuses_before_output(self):
        self.document["profile"]["cv2_provider_policy_sha256"] = "0" * 64
        self.save_manifest()
        self.refused_before_staging("POLICY_BINDING")

    def test_07_wrong_abi_refuses_before_output(self):
        self.document["profile"]["python_abi"] = "cp314"
        self.save_manifest()
        self.refused_before_staging("PROFILE")

    def test_08_unknown_model_identity_refuses_before_output(self):
        self.document["models"]["model_manifest_sha256"] = "0" * 64
        self.save_manifest()
        self.refused_before_staging("MODEL_ID")

    def test_09_model_digest_mismatch_refuses_before_output(self):
        item = next(value for value in self.document["files"]
                    if value["path"].endswith("detector.onnx"))
        item["sha256"] = "0" * 64
        self.save_manifest()
        self.refused_before_staging("MODEL_ID")

    def test_10_generated_admission_stages_exact_bytes_without_native_claim(self):
        before = {path: (self.input / path).read_bytes() for path in self.files}
        with self.selected():
            package.copy_application_files()
        for path, raw in before.items():
            self.assertEqual((self.target / path).read_bytes(), raw)
            self.assertEqual((self.input / path).read_bytes(), raw)
        saved = json.loads((self.target / "RUNTIME-PROVISIONING.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["prepared_input"]["state"],
                         "FILES_VERIFIED_PROFILE_UNRESOLVED_NATIVE_NOT_RUN")
        self.assertEqual(saved["prepared_input"]["native_activation"], "NOT_RUN")
        self.assertEqual((self.target / "PREPARED-RUNTIME-INPUT.json").read_bytes(),
                         self.manifest.read_bytes())
        self.assertFalse(self.archive.exists())

    def test_11_unresolved_profile_cannot_emit_fallback_launcher_or_archive(self):
        with self.selected():
            package.copy_application_files()
            with self.assertRaisesRegex(RuntimeError, "PREPARED_RUNTIME_PROFILE_NOT_ESTABLISHED"):
                package.write_launcher_scripts()
            with self.assertRaisesRegex(RuntimeError, "PREPARED_RUNTIME_PROFILE_NOT_ESTABLISHED"):
                package.create_zip_archive()
        self.assertFalse((self.target / "Start-KineLabPT.bat").exists())
        self.assertFalse((self.target / "Install-DesktopShortcut.ps1").exists())
        self.assertFalse(self.archive.exists())

    def test_12_default_remains_not_provisioned_without_prepared_tree_copy(self):
        with patch.object(package, "PREPARED_RUNTIME_MANIFEST", None, create=True):
            package.copy_application_files()
        self.assertFalse((self.target / "runtime").exists())
        self.assertFalse((self.target / "PREPARED-RUNTIME-INPUT.json").exists())
        saved = json.loads((self.target / "RUNTIME-PROVISIONING.json").read_text(encoding="utf-8"))
        self.assertNotIn("prepared_input", saved)
        self.assertEqual(set(saved["native"].values()), {"NOT_PROVISIONED"})

    def test_13_existing_output_is_preserved_and_never_overwritten(self):
        self.target.mkdir(parents=True)
        sentinel = self.target / "TEST_ONLY.txt"
        sentinel.write_bytes(b"TEST_ONLY PRIOR OUTPUT")
        with self.selected(), self.assertRaises(FileExistsError):
            package.copy_application_files()
        self.assertEqual(sentinel.read_bytes(), b"TEST_ONLY PRIOR OUTPUT")
        self.assertFalse(self.archive.exists())

    def test_14_hardlinked_input_is_refused_without_output(self):
        source = self.input / "runtime/python/python.exe"
        os.link(source, self.root / "TEST_ONLY-owned-hardlink.bin")
        self.refused_before_staging("FILE_BOUND")

    def test_15_input_change_after_admission_preserves_partial_and_refuses_ack(self):
        original_snapshot = package.source_snapshot
        changed = self.input / "runtime/python/python.exe"
        calls = 0

        def snapshot_then_change():
            nonlocal calls
            result = original_snapshot()
            if calls == 0:
                changed.write_bytes(b"TEST_ONLY changed after selection")
            calls += 1
            return result

        with self.selected(), patch.object(package, "source_snapshot", snapshot_then_change), self.assertRaisesRegex(ValueError, "PREPARED_RUNTIME_SIZE|PREPARED_RUNTIME_HASH"):
            package.copy_application_files()
        self.assertTrue((self.target / "app/t6_launcher.py").is_file())
        self.assertEqual(changed.read_bytes(), b"TEST_ONLY changed after selection")
        self.assertFalse((self.target / "PREPARED-RUNTIME-INPUT.json").exists())
        self.assertFalse((self.target / "RUNTIME-PROVISIONING.json").exists())
        self.assertFalse(self.archive.exists())

    def test_16_duplicate_json_key_is_refused_before_output(self):
        raw = self.manifest.read_text(encoding="utf-8")
        self.manifest.write_text(raw.replace('{"schema":', '{"schema":"TEST_ONLY-duplicate","schema":', 1),
                                 encoding="utf-8")
        self.refused_before_staging("DUPLICATE")

    def test_17_boolean_size_is_not_an_integer_inventory_size(self):
        self.document["files"][0]["size_bytes"] = True
        self.save_manifest()
        self.refused_before_staging("INVENTORY")

    def test_18_partial_prepared_copy_blocks_public_writers_after_selection_is_cleared(self):
        original_stream = package._prepared_stream
        first_relative = self.document["files"][0]["path"]
        first_target = self.target / first_relative
        copied = []
        input_before = {path.relative_to(self.input).as_posix(): path.read_bytes()
                        for path in self.input.rglob("*") if path.is_file()}

        def copy_first_then_interrupt(*args, **kwargs):
            result = original_stream(*args, **kwargs)
            if len(args) >= 4 and args[3] == first_target:
                copied.append(first_target)
                raise OSError("TEST_ONLY interrupted after first prepared member copy")
            return result

        with self.selected(), patch.object(package, "_prepared_stream", copy_first_then_interrupt), self.assertRaisesRegex(ValueError, "^PREPARED_RUNTIME_STAGING_UNAVAILABLE_PARTIAL_RETAINED$"):
            package.copy_application_files()
        self.assertEqual(copied, [first_target])
        self.assertEqual(first_target.read_bytes(), self.files[first_relative])
        for relative in self.files:
            if relative != first_relative:
                self.assertFalse((self.target / relative).exists())
        self.assertFalse((self.target / "PREPARED-RUNTIME-INPUT.json").exists())
        self.assertFalse((self.target / "RUNTIME-PROVISIONING.json").exists())

        def staged_bytes():
            return {path.relative_to(self.target).as_posix(): path.read_bytes()
                    for path in self.target.rglob("*") if path.is_file()}

        retained = staged_bytes()
        with patch.object(package, "PREPARED_RUNTIME_MANIFEST", None):
            self.assertIsNone(package.PREPARED_RUNTIME_MANIFEST)
            for name in ("write_launcher_scripts", "create_zip_archive"):
                with self.subTest(writer=name):
                    with self.assertRaisesRegex(
                            RuntimeError, "^PREPARED_RUNTIME_PROFILE_NOT_ESTABLISHED$"):
                        getattr(package, name)()
                    self.assertEqual(retained, staged_bytes())
                    self.assertFalse(self.archive.exists())
        self.assertEqual(retained, staged_bytes())
        self.assertEqual(input_before, {path.relative_to(self.input).as_posix(): path.read_bytes()
                                      for path in self.input.rglob("*") if path.is_file()})
        self.assertFalse((self.target / "Start-KineLabPT.bat").exists())
        self.assertFalse((self.target / "Install-DesktopShortcut.ps1").exists())
        self.assertFalse(self.archive.exists())
        intent_path = self.target / "PREPARED-RUNTIME-STAGING.json"
        self.assertTrue(intent_path.is_file())
        self.assertEqual(json.loads(intent_path.read_text(encoding="utf-8")), {
            "schema": "kinelab.prepared-runtime-staging-intent.v1",
            "state": "PENDING", "input_manifest_sha256":
            hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
        })


if __name__ == "__main__":
    unittest.main()
