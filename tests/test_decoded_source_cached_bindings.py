"""TEST_ONLY cache binding regressions; actual normalized clips/decoder and geometry.

No successful decoder, source-coverage gate, or reconstruction gate is mocked.
Only the previously unrestricted associated read_text boundary is substituted in
one negative control. The physical/clinical status remains UNVERIFIED.
"""
import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

import pipeline_quality
import source_coverage
import test_reconstruction_frame_grid as geometry_fixtures
from native_evidence_fixture import native_chain_fixture
from session_contract import ROLES


class DecodedSourceCachedBindingsTests(unittest.TestCase):
    def fixture(self):
        geometry = geometry_fixtures.ReconstructionFrameGridTests(
            "test_contiguous_zero_based_observations_keep_existing_quality")
        geometry.setUp()
        self.addCleanup(geometry.doCleanups)
        root, session, required = geometry.native_fixture(range(1, 9))
        people = {camera: json.loads(next((root / "pose-associated" / (camera + "_json")).glob("*.json")).read_bytes())["people"]
                  for camera in session["camera_ids"]}
        inputs = {role: hashlib.sha256(("TEST_ONLY generated source identity " + role).encode()).hexdigest()
                  for role in ROLES}
        session["captures"] = {role: {"sha256": checksum} for role, checksum in inputs.items()}
        identity = {"session_id": session["session_id"],
                    "config_sha256": hashlib.sha256((root / "Config.toml").read_bytes()).hexdigest(),
                    "inputs": inputs}
        # Generates and independently probes real normalized clips. Raw/sync/assoc
        # are native-shaped both-camera evidence containing the calibrated points.
        record = native_chain_fixture(root, identity, counts={"cam01": 9, "cam02": 9},
                                      offsets={"cam01": 0, "cam02": 0}, people=people)
        record["native_triangulation_policy"] = {"interpolation": "none", "fill_large_gaps_with": "nan"}
        (root / "run.json").write_text(json.dumps(record), encoding="utf-8")
        intact = pipeline_quality.validate_reconstruction(root, session)
        self.assertTrue(intact["ok"], intact)
        self.assertEqual(intact["source_coverage"]["common_range"], [1, 9])
        self.assertEqual(intact["source_coverage"]["physical_source_frame_equality"], "UNVERIFIED")
        self.assertEqual(set(intact["markers"]), set(required))
        return root, session, identity, record, intact

    def test_cached_sync_residuals_must_equal_independently_observed_endpoint_pairs(self):
        root, _, identity, record, _ = self.fixture()
        intact = source_coverage.verify_source_coverage(root, identity, record, through="personAssociation")
        self.assertEqual(intact["common_range"], [1, 9])
        original = copy.deepcopy(record)
        synchronization = next(stage for stage in record["stages"] if stage["name"] == "synchronization")
        # Both values remain finite, within one frame, with zero declared drift.
        # Observed pinned source pairs still prove residual zero at both ends.
        synchronization["quality"]["cameras"]["cam02"].update(
            start_residual_frames=1, end_residual_frames=1)
        self.assertEqual(synchronization["quality"]["source_frame_pairs"],
                         original["stages"][2]["quality"]["source_frame_pairs"])
        self.assertEqual(synchronization["quality"]["log"], original["stages"][2]["quality"]["log"])
        (root / "run.json").write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "(?i)(residual.*disagree|declared.*residual)"):
            source_coverage.verify_source_coverage(root, identity, record, through="personAssociation")

    def test_associated_diagnostics_parse_only_digest_verified_captured_bytes(self):
        root, session, _, _, intact = self.fixture()
        associated = root / "pose-associated"
        original_files = {path: path.read_bytes() for path in associated.rglob("*.json")}
        original_read_text = Path.read_text
        unadmitted_reads = []

        def substitute_unadmitted_read(path, *args, **kwargs):
            if path.is_relative_to(associated) and path.suffix == ".json":
                unadmitted_reads.append(path)
                # A read/swap/restore adversary supplies a syntactically valid,
                # unmeasured no-person document to the old second read only.
                # Actual hash-bound buffers, decoder and all source gates remain real.
                return '{"people": []}'
            return original_read_text(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", substitute_unadmitted_read):
            observed = pipeline_quality.validate_reconstruction(root, session)
        # Captured-byte parsing must ignore the unadmitted mutable-path reader.
        self.assertTrue(observed["ok"], observed)
        self.assertEqual(unadmitted_reads, [])
        self.assertEqual(observed["markers"], intact["markers"])
        self.assertEqual(observed["frame_diagnostics"], intact["frame_diagnostics"])
        self.assertEqual({path: path.read_bytes() for path in original_files}, original_files)


if __name__ == "__main__":
    unittest.main()
