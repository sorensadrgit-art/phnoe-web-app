"""Generated actual service/list observations; no camera or clinical evidence."""
import copy
import importlib
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import test_session_research_comparison as comparison_fixture
from session_library import SessionLibrary
from t6_service import IntegratedService

FIELD = "research_source_revision"
SCHEMA = "kinelab.comparison-source-observation.v1"


def refresh_generated_native(project, *, update_artifacts=True):
    manifest = project / "run.json"
    if update_artifacts:
        run = json.loads(manifest.read_text(encoding="utf-8"))
        for stage in run["stages"]:
            for artifact in stage["artifacts"]:
                artifact["sha256"] = comparison_fixture.sha256_file(project / artifact["path"])
        for index in (5, 6, 7):
            field = "consumed_trc" if index == 7 else "source"
            run["stages"][index]["quality"][field] = copy.deepcopy(run["stages"][index - 1]["artifacts"][0])
        manifest.write_text(json.dumps(run), encoding="utf-8")
    native = comparison_fixture.motion(project / "pose-3d/fixture_filt_LSTM.trc",
                                       project / "kinematics/fixture.mot", run_manifest=manifest)
    (project / "exports/generated.motion.json").write_text(json.dumps(native), encoding="utf-8")


class ComparisonSourceRevisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = comparison_fixture.ResearchComparisonTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.a = self.fixture.make_session("a")
        self.b = self.fixture.make_session("b")
        # Exercise the actual API producer without starting its DB/startup/device lifecycle.
        self.service = object.__new__(IntegratedService)
        self.service._closed = True
        self.service.mutex = threading.RLock()
        self.service.library = SessionLibrary(self.fixture.projects)
        self.service.index = self.fixture.index

    def rows(self):
        return self.service.sessions()

    def observation(self, session_id="b"):
        row = next(item for item in self.rows() if item["id"] == session_id)
        value = row.get(FIELD)
        self.assertIsInstance(value, dict, "Actual session API must expose a source observation")
        self.assertEqual(value.get("schema"), SCHEMA)
        self.assertIs(value.get("evidence_verified"), False)
        return value

    def assert_available(self, value):
        self.assertEqual(value["status"], "AVAILABLE", value.get("reason"))
        self.assertRegex(value["token"], r"^[a-f0-9]{64}$")
        self.assertIsNone(value["reason"])

    def assert_unavailable(self, value, reason):
        self.assertEqual(value["status"], "UNAVAILABLE")
        self.assertIsNone(value["token"])
        self.assertIn(reason, value["reason"])

    def test_identical_actual_api_observation_is_deterministic(self):
        first = self.observation()
        self.assert_available(first)
        self.assertEqual(first, self.observation())

    def test_valid_same_id_protocol_change_updates_actual_api(self):
        first = self.observation()
        manifest = self.b / "session.json"
        session = json.loads(manifest.read_text(encoding="utf-8"))
        session["metadata"]["protocol_version"] = "revision-2"
        manifest.write_text(json.dumps(session), encoding="utf-8")
        second = self.observation()
        self.assert_available(second)
        self.assertNotEqual(first["token"], second["token"])

    def test_same_size_preserved_mtime_native_bytes_never_retain_token(self):
        self.assert_available(self.observation())
        for relative in ("pose-3d/fixture_filt_LSTM.trc", "kinematics/fixture.mot", "kinematics/fixture.osim"):
            with self.subTest(source=relative):
                source = self.b / relative
                before = self.observation()
                stat = source.stat()
                original = source.read_bytes()
                replacement = bytes([original[0] ^ 1]) + original[1:]
                source.write_bytes(replacement)
                os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                after = self.observation()
                self.assertNotEqual(before, after)
                self.assert_unavailable(after, "SOURCE_INVALID")
                source.write_bytes(original)
                os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                self.assertEqual(before, self.observation())

    def test_run_and_motion_source_bytes_are_observed_even_when_shape_unchanged(self):
        first = self.observation()
        for relative in ("run.json", "exports/generated.motion.json", "Config.toml",
                         "preflight.json", "normalization.json", "logs.txt"):
            with self.subTest(source=relative):
                source = self.b / relative
                original = source.read_bytes()
                source.write_bytes(original + b"\n")
                self.assertNotEqual(first, self.observation())
                source.write_bytes(original)
                self.assertEqual(first, self.observation())

    def test_candidate_inventory_ambiguity_is_unavailable(self):
        self.assert_available(self.observation())
        source = self.b / "exports/generated.motion.json"
        duplicate = self.b / "exports/second.motion.json"
        duplicate.write_bytes(source.read_bytes())
        self.assert_unavailable(self.observation(), "AMBIGUOUS")
        duplicate.unlink()
        added = self.b / "kinematics/second.osim"
        added.write_bytes((self.b / "kinematics/fixture.osim").read_bytes())
        self.assert_unavailable(self.observation(), "SOURCE_INVALID")

    def test_missing_corrupt_and_duplicate_key_sources_have_no_token(self):
        self.assert_available(self.observation())
        source = self.b / "run.json"
        original = source.read_bytes()
        for replacement in (b"{", b'{"schema":"kinelab.run.v1","schema":"other"}'):
            source.write_bytes(replacement)
            self.assert_unavailable(self.observation(), "SOURCE_INVALID")
        source.unlink()
        self.assert_unavailable(self.observation(), "SOURCE_UNAVAILABLE")
        source.write_bytes(original)

    def test_observation_adds_no_video_reads_to_existing_listing_validation(self):
        self.assert_available(self.observation())
        original = Path.open
        videos = []

        def guarded(path, *args, **kwargs):
            if path.suffix.casefold() in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
                videos.append(path)
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", guarded):
            self.assert_available(self.observation())
        # Existing _describe/load_session still hashes six originals per session.
        expected = [root / "raw" / (role + ".mp4") for root in (self.a, self.b)
                    for role in comparison_fixture.ROLES]
        self.assertCountEqual(videos, expected)

    def test_caps_fail_closed_without_truncated_proof(self):
        self.assert_available(self.observation())
        module = importlib.import_module("comparison_revision")
        for name, value in (("MAX_FILE_BYTES", 64), ("MAX_TOTAL_BYTES", 128),
                            ("MAX_ARTIFACTS", 1), ("MAX_DIRECTORY_ENTRIES", 1)):
            with self.subTest(cap=name), patch.object(module, name, value):
                self.assert_unavailable(self.observation(), "LIMIT")

    def test_reparse_source_is_refused_by_existing_path_guard(self):
        self.assert_available(self.observation())
        from take_acceptance import is_reparse
        selected = self.b / "kinematics/fixture.osim"
        with patch("take_acceptance.is_reparse", side_effect=lambda path: path == selected or is_reparse(path)):
            self.assert_unavailable(self.observation(), "SOURCE_INVALID")

    def test_optional_frame_diagnostics_binding_is_observed_and_validated(self):
        import pipeline_quality as quality

        self.assert_available(self.observation())  # Legacy absence is supported.
        manifest = self.b / "run.json"
        run = json.loads(manifest.read_text(encoding="utf-8"))
        identity = {"session_id": self.b.name, "camera_ids": list(quality.FRAME_CAMERAS),
                    "source_trc": copy.deepcopy(run["stages"][4]["artifacts"][0]),
                    "calibration": copy.deepcopy(run["stages"][0]["artifacts"][0])}
        rows = [{"frame": 0, "marker": marker, "cameras": {
            camera: {"status": "supported", "likelihood": .9,
                     "reprojection_px": 2.0, "camera_depth": 2.0}
            for camera in quality.FRAME_CAMERAS}} for marker in quality.FRAME_MARKERS]
        document = quality.build_frame_diagnostics(rows, quality.FRAME_MARKERS, identity)
        binding = quality.write_frame_diagnostics(self.b, document)
        run["stages"][4]["quality"]["frame_diagnostics"] = binding
        manifest.write_text(json.dumps(run), encoding="utf-8")
        refresh_generated_native(self.b, update_artifacts=False)
        before = self.observation()
        self.assert_available(before)
        sidecar = self.b / binding["path"]
        original, proof = sidecar.read_bytes(), sidecar.stat()
        sidecar.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        os.utime(sidecar, ns=(proof.st_atime_ns, proof.st_mtime_ns))
        self.assert_unavailable(self.observation(), "SOURCE_INVALID")
        sidecar.write_bytes(original)
        os.utime(sidecar, ns=(proof.st_atime_ns, proof.st_mtime_ns))
        self.assertEqual(before, self.observation())
        for malformed in ({**binding, "sha256": "["}, {**binding, "frames": True}):
            with self.subTest(binding=malformed):
                run["stages"][4]["quality"]["frame_diagnostics"] = malformed
                manifest.write_text(json.dumps(run), encoding="utf-8")
                # Deliberately corrupt input: the real exporter refuses these bindings.
                native_path = self.b / "exports/generated.motion.json"
                native = json.loads(native_path.read_text(encoding="utf-8"))
                native["provenance"]["runManifestSha256"] = comparison_fixture.sha256_file(manifest)
                native_path.write_text(json.dumps(native), encoding="utf-8")
                self.assert_unavailable(self.observation(), "SOURCE_INVALID")

    def test_source_changed_during_observation_has_no_token(self):
        self.assert_available(self.observation())
        module = importlib.import_module("comparison_revision")
        original = module._read_source
        changed = False

        def racing(*args, **kwargs):
            nonlocal changed
            result = original(*args, **kwargs)
            if not changed and args[0] == self.b:
                changed = True
                with (self.b / "session.json").open("ab") as stream:
                    stream.write(b" ")
            return result

        with patch.object(module, "_read_source", racing):
            self.assert_unavailable(self.observation(), "CHANGED")


def generated_api_cases():
    """Export actual API rows and comparison for the companion component regression."""
    case = ComparisonSourceRevisionTests("runTest")
    case.setUp()
    try:
        first = case.rows()
        comparison = {"comparison": case.fixture.compare()}
        equal = case.rows()
        changes = {}
        bound = [case.b / relative for relative in ("run.json", "exports/generated.motion.json")]
        for name, relative, transform in (
            ("protocol", "session.json", lambda data: json.dumps({**json.loads(data), "metadata": {
                **json.loads(data)["metadata"], "protocol_version": "revision-2"}}).encode()),
            ("motion", "exports/generated.motion.json", lambda data: data + b"\n"),
            ("run", "run.json", lambda data: data + b"\n"),
            ("trc", "pose-3d/fixture_filt_LSTM.trc", lambda data: data + b"\n"),
            ("mot", "kinematics/fixture.mot", lambda data: data + b"\n"),
            ("model", "kinematics/fixture.osim", lambda data: data + b"\n"),
        ):
            source = case.b / relative
            originals = {path: path.read_bytes() for path in {source, *bound}}
            original = originals[source]
            source.write_bytes(transform(original))
            if name in ("trc", "mot", "model", "run"):
                refresh_generated_native(case.b, update_artifacts=name != "run")
            changes[name] = case.rows()
            for path, content in originals.items():
                path.write_bytes(content)
        return {"evidence_kind": "generated_api_revision_regression", "test_only": True,
                "physical_accuracy_verified": False, "before_rows": first, "equal_rows": equal,
                "changes": changes, "comparison": comparison}
    finally:
        case.fixture.doCleanups()


if __name__ == "__main__":
    if sys.argv[1:] == ["--emit-api-cases"]:
        print(json.dumps(generated_api_cases(), sort_keys=True))
    else:
        unittest.main()
