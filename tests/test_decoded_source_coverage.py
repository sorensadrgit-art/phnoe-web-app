"""DXA acceptance on disposable generated TEST_ONLY clips; no physical claim.

The provenance verifier and decoder are real on every positive path. Mocks below
inject decoder failure or a concurrent rewrite only; they never provide a
passing production decoder result. Fixture expectations are built independently.
"""
import copy
import hashlib
import importlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import native_evidence_fixture as fixtures
from normalize_capture import ROLES


class DecodedSourceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("source_coverage"),
                             "DXA MISSING: decoded source verifier")
        self.gate = importlib.import_module("source_coverage")
        self.assertTrue(callable(getattr(fixtures, "native_chain_fixture", None)),
                        "DXA MISSING: generated-media fixture")
        owned = tempfile.TemporaryDirectory(prefix="TEST_ONLY-DXA-")
        self.addCleanup(owned.cleanup)
        self.project = Path(owned.name).resolve()
        (self.project / "Config.toml").write_text("# TEST_ONLY generated\n", encoding="utf-8")
        self.identity = {"session_id": "TEST_ONLY-DXA",
                         "config_sha256": self.digest(self.project / "Config.toml"),
                         "inputs": {role: hashlib.sha256(("TEST_ONLY original " + role).encode()).hexdigest()
                                    for role in ROLES}}

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def chain(self, **kwargs):
        return fixtures.native_chain_fixture(self.project, self.identity,
                                             counts=kwargs.pop("counts", {"cam01": 7, "cam02": 7}),
                                             **kwargs)

    def verify(self, record, through="personAssociation", **kwargs):
        return self.gate.verify_source_coverage(self.project, self.identity, record,
                                                through=through, **kwargs)

    def inventory(self, record, stage):
        item = next(item for item in record["stages"] if item["name"] == stage)
        folder = {"poseEstimation": "pose", "synchronization": "pose-sync",
                  "personAssociation": "pose-associated"}[stage]
        item["artifacts"] = [{"path": path.relative_to(self.project).as_posix(),
                              "sha256": self.digest(path)}
                             for path in sorted((self.project / folder).rglob("*.json"))]
        return item

    def pose_path(self, folder, frame, camera="cam01"):
        return self.project / folder / (camera + "_json") / f"{camera}_{frame:06d}.json"

    def snapshot(self):
        return {p.relative_to(self.project).as_posix(): self.digest(p)
                for p in self.project.rglob("*") if p.is_file()}

    def test_DXA01_real_decoded_media_matches_independent_expected_summary(self):
        record = self.chain()
        before = self.snapshot()
        self.assertEqual(self.verify(record), record["stages"][3]["quality"]["source_coverage"])
        self.assertEqual(self.verify(record)["common_range"], [1, 7])
        self.assertEqual(self.verify(record)["physical_source_frame_equality"], "UNVERIFIED")
        self.assertEqual(self.snapshot(), before)

    def test_DXA02_rehashed_normalization_count_lie_is_refused_by_real_decode(self):
        record = self.chain()
        path = self.project / "normalization.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["outputs"]["cam01_trial"]["frame_count"] += 1
        value["outputs"]["cam01_trial"]["timestamps"].append(7 / 30)
        path.write_text(json.dumps(value), encoding="utf-8")
        record["normalization"]["sha256"] = self.digest(path)
        for item in record["stages"][1:4]:
            item["quality"]["source_coverage"]["normalization"] = copy.deepcopy(record["normalization"])
        with self.assertRaises(ValueError):
            self.verify(record)

    def test_DXA03_coherently_rehashed_noncodec_media_is_refused(self):
        record = self.chain()
        path = self.project / "normalization.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        media = self.project / value["outputs"]["cam01_trial"]["path"]
        media.write_bytes(b"TEST_ONLY not codec media\n")
        value["outputs"]["cam01_trial"]["sha256"] = self.digest(media)
        path.write_text(json.dumps(value), encoding="utf-8")
        record["normalization"]["sha256"] = self.digest(path)
        with self.assertRaises((ValueError, OSError)):
            self.verify(record)

    def test_DXA04_current_hashed_raw_membership_missing_or_extra_is_refused(self):
        for mode in ("missing-first", "extra-tail"):
            with self.subTest(mode=mode):
                record = self.chain()
                first = self.pose_path("pose", 0)
                if mode == "missing-first":
                    first.unlink()
                else:
                    self.pose_path("pose", 7).write_bytes(first.read_bytes())
                self.inventory(record, "poseEstimation")
                with self.assertRaises(ValueError):
                    self.verify(record, through="poseEstimation")
                if mode == "extra-tail":
                    self.pose_path("pose", 7).unlink()

    def test_DXA05_sync_same_count_wrong_source_bytes_is_refused(self):
        record = self.chain()
        self.pose_path("pose-sync", 2).write_bytes(self.pose_path("pose-sync", 3).read_bytes())
        self.inventory(record, "synchronization")
        with self.assertRaises(ValueError):
            self.verify(record, through="synchronization")

    def test_DXA06_negative_offset_retains_nonzero_start_without_reindexing(self):
        record = self.chain(counts={"cam01": 9, "cam02": 7},
                            offsets={"cam01": 0, "cam02": -2})
        summary = self.verify(record)
        self.assertEqual(summary["common_range"], [2, 9])
        self.assertEqual(summary["cameras"]["cam02"]["synchronized_range"], [2, 9])
        self.assertTrue(self.pose_path("pose-associated", 2, "cam02").is_file())
        self.assertFalse(self.pose_path("pose-associated", 0, "cam02").exists())

    def test_DXA07_positive_offset_native_zero_drop_is_preserved(self):
        record = self.chain(counts={"cam01": 9, "cam02": 9},
                            offsets={"cam01": 0, "cam02": 2})
        summary = self.verify(record)
        self.assertEqual(summary["common_range"], [1, 7])
        self.assertEqual(summary["cameras"]["cam02"]["synchronized_range"], [1, 7])

    def test_DXA08_association_selected_person_must_be_unchanged_source_member(self):
        record = self.chain()
        path = self.pose_path("pose-associated", 2)
        value = json.loads(path.read_text(encoding="utf-8"))
        value["people"][0]["pose_keypoints_2d"][0] += 1
        path.write_text(json.dumps(value), encoding="utf-8")
        self.inventory(record, "personAssociation")
        with self.assertRaises(ValueError):
            self.verify(record)

    def test_DXA09_association_envelope_must_match_synchronized_frame(self):
        record = self.chain()
        path = self.pose_path("pose-associated", 2)
        value = json.loads(path.read_text(encoding="utf-8"))
        value["TEST_ONLY_source_index"] = 3
        path.write_text(json.dumps(value), encoding="utf-8")
        self.inventory(record, "personAssociation")
        with self.assertRaises(ValueError):
            self.verify(record)

    def test_DXA10_interior_absence_is_explicit_missing_but_endpoints_required(self):
        record = self.chain()
        self.pose_path("pose-associated", 3).unlink()
        item = self.inventory(record, "personAssociation")
        item["quality"]["source_coverage"]["associated_missing_frames"]["cam01"] = [3]
        self.assertEqual(self.verify(record)["associated_missing_frames"]["cam01"], [3])
        self.pose_path("pose-associated", 1).unlink()
        self.inventory(record, "personAssociation")
        with self.assertRaises(ValueError):
            self.verify(record)

    def test_DXA11_exact_native_missing_person_sentinel_is_not_measured_selection(self):
        record = self.chain()
        path = self.pose_path("pose-associated", 3)
        value = json.loads(path.read_text(encoding="utf-8"))
        value["people"] = [{}]
        path.write_text(json.dumps(value), encoding="utf-8")
        self.inventory(record, "personAssociation")
        self.assertEqual(self.verify(record)["common_range"], [1, 7])
        value["people"] = [{"unrecognized": "TEST_ONLY malformed"}]
        path.write_text(json.dumps(value), encoding="utf-8")
        self.inventory(record, "personAssociation")
        with self.assertRaises(ValueError):
            self.verify(record)

    def test_DXA12_cache_reuse_redecodes_and_missing_decoder_fails_closed(self):
        record = self.chain()
        import normalize_capture
        with mock.patch.object(normalize_capture, "inspect_video",
                               wraps=normalize_capture.inspect_video) as decoder:
            self.verify(record)
            first = decoder.call_count
            self.verify(record)
            self.assertGreaterEqual(first, 2)
            self.assertGreaterEqual(decoder.call_count - first, 2)
        # Negative fault injection only: never supply fabricated passing metadata.
        with (
            mock.patch.object(normalize_capture, "inspect_video",
                              side_effect=FileNotFoundError("TEST_ONLY missing decoder")),
            self.assertRaises((ValueError, OSError)),
        ):
            self.verify(record)

    def test_DXA13_all_nondefault_explicit_frame_ranges_are_refused(self):
        record = self.chain()
        for crop in ("[1, 7]", "[2, 6]"):
            with self.subTest(crop=crop):
                (self.project / "Config.toml").write_text(
                    "[project]\nframe_range = " + crop + "\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.verify(record)

    def test_DXA14_legacy_v2_v3_and_tampered_cached_coverage_cannot_promote(self):
        record = self.chain()
        for policy in ("kinelab.pipeline-quality.v2", "kinelab.pipeline-quality.v3"):
            candidate = copy.deepcopy(record)
            candidate["quality_policy"] = policy
            with self.assertRaises(ValueError):
                self.verify(candidate)
        record["stages"][3]["quality"]["source_coverage"]["common_range"] = [0, 7]
        with self.assertRaises(ValueError):
            self.verify(record)

    def test_DXA15_normalization_mutation_during_real_decode_is_refused(self):
        record = self.chain()
        import normalize_capture
        original = normalize_capture.inspect_video
        mutated = False
        def decode_then_mutate(path):
            nonlocal mutated
            result = original(path)
            if not mutated:
                normalization = self.project / "normalization.json"
                normalization.write_bytes(normalization.read_bytes() + b" ")
                mutated = True
            return result
        with (
            mock.patch.object(normalize_capture, "inspect_video", side_effect=decode_then_mutate),
            self.assertRaises(ValueError),
        ):
            self.verify(record)
        self.assertTrue(mutated, "the real decoder ran before the concurrent mutation")

    def test_DXA16_both_associated_views_truncated_together_still_refused(self):
        record = self.chain()
        for camera in ("cam01", "cam02"):
            self.pose_path("pose-associated", 6, camera).unlink()
        self.inventory(record, "personAssociation")
        # Even a coherently rewritten stored common range cannot redefine
        # the independently decoded raw/synchronized source interval.
        record["stages"][3]["quality"]["source_coverage"]["common_range"] = [1, 6]
        with self.assertRaises(ValueError):
            self.verify(record)

    def test_DXA17_malformed_nonfinite_and_duplicate_decoder_json_is_refused(self):
        record = self.chain()
        import normalize_capture
        original = normalize_capture._probe_output
        for mode in ("malformed", "nonfinite", "duplicate"):
            with self.subTest(mode=mode):
                def corrupt_probe(command, mode=mode):
                    raw = original(command)
                    if mode == "malformed":
                        return "{TEST_ONLY invalid JSON"
                    if mode == "duplicate":
                        # A permissive last-key-wins parser would accept this.
                        return '{"streams":[],' + raw.lstrip()[1:]
                    value = json.loads(raw)
                    value["frames"][0]["best_effort_timestamp_time"] = "NaN"
                    return json.dumps(value)
                with (
                    mock.patch.object(normalize_capture, "_probe_output", side_effect=corrupt_probe),
                    self.assertRaises(ValueError),
                ):
                    self.verify(record)

    def test_DXA18_decoder_timeout_is_refused_without_promoting_cached_evidence(self):
        record = self.chain()
        before = self.snapshot()
        import subprocess

        import normalize_capture
        with (
            mock.patch.object(normalize_capture, "_probe_output",
                              side_effect=subprocess.TimeoutExpired(["ffprobe", "TEST_ONLY"], 120)),
            self.assertRaises(ValueError),
        ):
            self.verify(record)
        self.assertEqual(self.snapshot(), before)

    def project_alias(self):
        owned = tempfile.TemporaryDirectory(prefix="TEST_ONLY-DXA-alias-")
        self.addCleanup(owned.cleanup)
        alias = Path(owned.name).resolve() / "linked-project"
        try:
            alias.symlink_to(self.project, target_is_directory=True)
        except (NotImplementedError, OSError) as error:
            self.skipTest("directory symlink creation unavailable on this host: " + str(error))
        self.addCleanup(alias.unlink, missing_ok=True)
        self.assertFalse(self.project.is_symlink(), "the control project must be ordinary")
        self.assertTrue(alias.is_symlink(), "the negative path must be an actual directory link")
        self.assertEqual(alias.resolve(), self.project)
        return alias

    def project_bytes(self):
        return {path.relative_to(self.project).as_posix(): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file()}

    def test_DXA19_config_crop_check_refuses_linked_project_root(self):
        alias = self.project_alias()
        before = self.project_bytes()
        self.assertIsNone(self.gate.reject_configured_crop(self.project))
        try:
            with self.assertRaisesRegex(ValueError, "QUALITY_UNVERIFIED: decoded source coverage:"):
                self.gate.reject_configured_crop(alias)
        finally:
            self.assertEqual(self.project_bytes(), before)
            self.assertTrue(alias.is_symlink(), "admission must preserve the refused alias")

    def test_DXA20_normalization_capture_refuses_linked_project_root(self):
        alias = self.project_alias()
        record = self.chain(through="poseEstimation")
        before = self.project_bytes()
        observed = self.gate.capture_normalization(
            self.project, self.identity, record["normalization"], decode=True)
        self.assertEqual(observed["binding"], record["normalization"])
        self.assertEqual(observed["counts"], {"cam01": 7, "cam02": 7})
        try:
            with self.assertRaisesRegex(ValueError, "QUALITY_UNVERIFIED: decoded source coverage:"):
                self.gate.capture_normalization(
                    alias, self.identity, record["normalization"], decode=True)
        finally:
            self.assertEqual(self.project_bytes(), before)
            self.assertTrue(alias.is_symlink(), "admission must preserve the refused alias")

    def test_DXA21_source_coverage_refuses_linked_project_root(self):
        alias = self.project_alias()
        record = self.chain()
        before = self.project_bytes()
        self.assertEqual(self.verify(record), record["stages"][3]["quality"]["source_coverage"])
        try:
            with self.assertRaisesRegex(ValueError, "QUALITY_UNVERIFIED: decoded source coverage:"):
                self.gate.verify_source_coverage(
                    alias, self.identity, record, through="personAssociation")
        finally:
            self.assertEqual(self.project_bytes(), before)
            self.assertTrue(alias.is_symlink(), "admission must preserve the refused alias")

if __name__ == "__main__":
    unittest.main()
