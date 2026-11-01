"""Generated TEST_ONLY research comparison fixture bound to the backend producer.

Not physical or clinical evidence. Regenerate the viewer fixture from the actual
authenticated loopback comparison/list producers with::

    python -X utf8 -B tests/test_research_comparison_fixture.py --write
"""
import argparse
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT, ROOT / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

# A module import keeps unittest discovery from collecting ResearchComparisonTests twice.
import test_reconstruction_timing as timing_sessions
import test_session_metadata_context_api as context_api

FIXTURE = ROOT / "viewer" / "src" / "fixtures" / "researchComparison.generated.json"
WRAPPER = {
    "evidence_kind": "GENERATED_CONTRACT_FIXTURE_ONLY",
    "test_only": True,
    "research_only": True,
    "physical_accuracy_verified": False,
    "clinical_validation": "UNVERIFIED",
    "camera_probe": "MOCKED; all six MP4 names contain generated text bytes, never recordings",
    "producer": "authenticated GET /api/v1/compare and GET /api/v1/sessions",
    "session_rows_projection": "id,kind,evidence_status,metadata_context_sha256,research_source_revision",
    "generator": "tests/test_research_comparison_fixture.py",
}
PROBE_ANGLES = (0.35, 1.45, 0.9)
HASH = re.compile(r"[0-9a-f]{64}")
FRAME_PATH = re.compile(r"diagnostics/reconstruction-frames\.([0-9a-f]{64})\.json")


def produce(angles_b=None, *, with_rows=False):
    """Obtain comparison and selected session-row fields through the authenticated API."""
    case = timing_sessions.ReconstructionTimingApiTests(
        "test_10_api_mixed_grid_uses_bound_unfiltered_trc_not_native_filtered_grid")

    def native_contract(root, **kwargs):
        angles = angles_b if root.name == "b" and angles_b is not None else (0.2, 0.8, 0.5)
        context_api.SessionMetadataContextApiTests.native_contract(root, angles=angles, **kwargs)

    try:
        case.setUp()
        with patch.object(case, "native_contract", side_effect=native_contract):
            case.fixture("a", [0, 1, 2, 4, 5], rejected=(2,))
            case.fixture("b", [0, 1, 2, 4, 5], rejected=(2,))
        comparison = case.comparison()
        case.assertTrue(comparison["compatible"], comparison["reason"])
        case.assertEqual(comparison["research_measurements"]["status"], "AVAILABLE", comparison)
        status, listed = case.request("GET", "/api/v1/sessions")
        case.assertEqual(status, 200, listed)
        keys = ("id", "kind", "evidence_status", "metadata_context_sha256", "research_source_revision")
        rows = [{key: row[key] for key in keys} for row in listed["sessions"]]
        case.assertEqual([row["id"] for row in rows], ["a", "b"])
        for source in comparison["research_measurements"]["sessions"]:
            case.assertIn("timing", source, "R04 MISSING: genuine fixture timing projection")
            case.assertEqual(source["timing"]["status"], "AVAILABLE", source["timing"])
        return (comparison, rows) if with_rows else comparison
    finally:
        case.doCleanups()


def stable(value):
    """Keep every key and value except per-run digests and producer timestamps."""
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"} and isinstance(value["path"], str):
            match = FRAME_PATH.fullmatch(value["path"])
            if match:
                if match.group(1) != value["sha256"]:
                    raise AssertionError("frame diagnostics path/digest binding mismatch")
                return {"path": "diagnostics/reconstruction-frames.<sha256>.json",
                        "sha256": "<sha256>"}
        return {key: "<utc>" if key == "updated_at_utc" else stable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [stable(item) for item in value]
    if isinstance(value, str) and HASH.fullmatch(value):
        return "<sha256>"
    return value


def committed():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class StableComparisonBindingTests(unittest.TestCase):
    def test_bound_content_address_is_stable_without_mutating_input(self):
        first = {"path": "diagnostics/reconstruction-frames." + "a" * 64 + ".json",
                 "sha256": "a" * 64}
        second = {"path": "diagnostics/reconstruction-frames." + "b" * 64 + ".json",
                  "sha256": "b" * 64}
        self.assertEqual(stable(first), stable(second))
        self.assertEqual(first["sha256"], "a" * 64)
        self.assertIn("a" * 64, first["path"])

    def test_mismatched_embedded_digest_is_rejected_before_normalization(self):
        for digest in ("b" * 64, "not-a-digest", None):
            with self.subTest(digest=digest), self.assertRaisesRegex(AssertionError, "binding mismatch"):
                stable({"path": "diagnostics/reconstruction-frames." + "a" * 64 + ".json",
                        "sha256": digest})

    def test_unknown_paths_structure_and_semantic_changes_remain_visible(self):
        digest = "a" * 64
        bound = {"path": "diagnostics/reconstruction-frames." + digest + ".json", "sha256": digest}
        for path in ("other/reconstruction-frames." + digest + ".json",
                     "../diagnostics/reconstruction-frames." + digest + ".json",
                     "diagnostics/reconstruction-frames." + digest + ".json.extra"):
            with self.subTest(path=path):
                self.assertNotEqual(stable(bound), stable({**bound, "path": path}))
        self.assertNotEqual(stable(bound), stable({**bound, "unexpected": True}))
        self.assertNotEqual(stable({"binding": bound, "observed": 5}),
                            stable({"binding": bound, "observed": 4}))

class ResearchComparisonFixtureBindingTests(unittest.TestCase):
    def test_committed_fixture_matches_producer_contract(self):
        document = committed()
        wrapper = {key: value for key, value in document.items()
                   if key not in ("comparison", "session_rows", "asymmetric_endpoint_probe")}
        self.assertEqual(wrapper, WRAPPER)
        comparison, rows = produce(with_rows=True)
        self.assertEqual(stable(document["comparison"]), stable(comparison))
        self.assertEqual(stable(document["session_rows"]), stable(rows))

    def test_asymmetric_probe_matches_producer_endpoint_order(self):
        document = committed()
        probe = document["asymmetric_endpoint_probe"]
        self.assertEqual(tuple(probe["session_2_angles_deg"]), PROBE_ANGLES)
        result = produce(PROBE_ANGLES)
        self.assertTrue(result["compatible"], result["reason"])
        coordinate = result["research_measurements"]["coordinates"][0]
        expected_1 = document["comparison"]["research_measurements"]["coordinates"][0]["session_1"]
        self.assertEqual(coordinate["session_1"], expected_1)
        self.assertEqual(coordinate["session_2"], probe["expected_session_2"])
        self.assertNotEqual(coordinate["session_1"], coordinate["session_2"])


    def test_real_api_mixed_timing_and_current_session_rows_are_bound(self):
        document = committed()
        rows = {row["id"]: row for row in document["session_rows"]}
        for source in document["comparison"]["research_measurements"]["sessions"]:
            timing = source["timing"]
            self.assertEqual(timing["status"], "AVAILABLE", timing)
            self.assertEqual(timing["sample_counts"],
                             {"observed": 5, "valid": 4, "rejected": 1, "missing_interior": 1})
            self.assertEqual(timing["bindings"]["run_sha256"], source["source_revision"]["run_sha256"])
            self.assertNotEqual(timing["bindings"]["source_trc"]["sha256"],
                                source["source_revision"]["trc_sha256"])
            row = rows[source["session_id"]]
            self.assertEqual(timing["bindings"]["metadata_context_sha256"], row["metadata_context_sha256"])
            self.assertEqual(timing["bindings"]["comparison_source_observation"]["token"],
                             row["research_source_revision"]["token"])
            self.assertFalse(timing["physical_accuracy_verified"])


def write():
    probe = produce(PROBE_ANGLES)["research_measurements"]["coordinates"][0]["session_2"]
    comparison, rows = produce(with_rows=True)
    document = {**WRAPPER,
                "session_rows": rows,
                "asymmetric_endpoint_probe": {"session_2_angles_deg": list(PROBE_ANGLES),
                                              "expected_session_2": probe},
                "comparison": comparison}
    FIXTURE.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate the viewer fixture")
    if parser.parse_args().write:
        write()
    else:
        unittest.main(argv=[sys.argv[0]])

