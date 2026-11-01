"""SOURCE CANDIDATE ONLY. Generated observations; no runtime claims."""
import copy
import json
import unittest
from unittest.mock import patch

import comparison_revision
import pipeline_quality as quality
import test_session_metadata_context_api as context_api
from export_motion import motion
from session_contract import sha256_file
from session_metadata_revision import read_metadata_state
from test_frame_diagnostics_n01 import CALIBRATION, SESSION, TRC, generated_observations, identity


def _timing_trc(grid):
    names = quality.FRAME_MARKERS
    header = ["PathFileType\t4\t(X/Y/Z)\tTEST_ONLY-timing.trc",
              "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames",
              f"30\t30\t{len(grid)}\t{len(names)}\tm\t30\t0\t{len(grid)}",
              "Frame#\tTime\t" + "\t".join(name + "\t\t" for name in names),
              "\t\t" + "\t".join(f"{axis}{index}" for index in range(1, len(names) + 1) for axis in "XYZ")]
    body = [f"{index}\t{index / 30:.9f}\t" + "\t".join(["1", "2", "3"] * len(names)) for index in grid]
    return "\n".join([*header, *body]) + "\n"


class ReconstructionTimingTests(unittest.TestCase):
    def document(self, grid, rejected=()):
        source = generated_observations()
        rows = []
        for index in grid:
            template = 1 if index in rejected else 0
            selected = copy.deepcopy([row for row in source if row["frame"] == template])
            for row in selected:
                row["frame"] = index
            rows.extend(selected)
        return quality.build_frame_diagnostics(rows, quality.FRAME_MARKERS, identity())

    def project(self, grid, rejected=(), **overrides):
        arguments = {"session_id": SESSION, "source_trc": TRC, "calibration": CALIBRATION}
        arguments.update(overrides)
        fn = getattr(quality, "project_reconstruction_timing", None)
        self.assertTrue(callable(fn), "R04 MISSING: bound reconstruction timing projection")
        return fn(self.document(grid, rejected), [index / 30 for index in grid], **arguments)

    def test_00_mixed_valid_rejected_missing_exhaustive_intervals(self):
        result = self.project([0, 1, 2, 4, 5], rejected=(2,))
        self.assertEqual(result["sample_counts"], {"observed": 5, "valid": 4, "rejected": 1, "missing_interior": 1})
        self.assertEqual([item["category"] for item in result["intervals"]],
                         ["valid_adjacent", "rejected_or_transition_adjacent", "unknown_gap", "valid_adjacent"])
        self.assertEqual(result["gaps"], [{"first_missing_frame": 3, "last_missing_frame": 3,
                                           "missing_samples": 1, "left_time_s": 2 / 30, "right_time_s": 4 / 30}])
        self.assertEqual([(s["classification"], s["first_frame"], s["last_frame"]) for s in result["segments"]],
                         [("valid", 0, 1), ("rejected", 2, 2), ("valid", 4, 5)])
        self.assertAlmostEqual(result["duration_s"]["valid_adjacent"], 2 / 30)
        self.assertAlmostEqual(result["duration_s"]["rejected_or_transition_adjacent"], 1 / 30)
        self.assertAlmostEqual(result["duration_s"]["unknown_gap"], 2 / 30)
        self.assertAlmostEqual(sum(v for k, v in result["duration_s"].items() if k != "observed_span"), 5 / 30)
        self.assertFalse(result["physical_accuracy_verified"])
        self.assertFalse(result["clinical_accuracy_verified"])

    def test_01_source_session_and_calibration_mismatch_refuse(self):
        for overrides in ({"session_id": "TEST_ONLY-wrong"},
                          {"source_trc": {**TRC, "sha256": "8" * 64}},
                          {"calibration": {**CALIBRATION, "sha256": "9" * 64}}):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, "TIMING_SOURCE_MISMATCH"):
                self.project([0, 1], **overrides)

    def test_02_singleton_has_no_extrapolated_interval_or_duration(self):
        for rejected in ((), (70,)):
            with self.subTest(rejected=rejected):
                result = self.project([70], rejected)
                self.assertEqual(result["intervals"], [])
                self.assertEqual(result["gaps"], [])
                self.assertEqual(result["sample_counts"]["missing_interior"], 0)
                self.assertTrue(all(value == 0 for value in result["duration_s"].values()))

    def test_03_rejected_first_and_last_classify_transition_intervals(self):
        result = self.project([10, 11, 12], rejected=(10, 12))
        self.assertEqual([i["category"] for i in result["intervals"]],
                         ["rejected_or_transition_adjacent", "rejected_or_transition_adjacent"])
        self.assertEqual(result["duration_s"]["valid_adjacent"], 0)
        self.assertAlmostEqual(result["duration_s"]["observed_span"], 2 / 30)

    def test_04_sparse_huge_span_uses_two_rows_not_full_session_array(self):
        result = self.project([0, 10**9])
        self.assertEqual(result["sample_counts"]["missing_interior"], 10**9 - 1)
        self.assertEqual(len(result["intervals"]), 1)
        self.assertEqual(len(result["gaps"]), 1)
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["duration_s"]["valid_adjacent"], 0)

    def test_05_time_grid_duplicate_nonfinite_bool_and_row_mismatch_refuse(self):
        fn = getattr(quality, "project_reconstruction_timing", None)
        self.assertTrue(callable(fn), "R04 MISSING: bound reconstruction timing projection")
        for times in ([0, 0], [0, float("nan")], [0, float("inf")], [False, 1 / 30],
                      [0, .04], [], [0], [0, 1 / 30, 2 / 30], [0, 10 ** 1000]):
            with self.subTest(times=times), self.assertRaisesRegex(ValueError, "TIMING_GRID_MISMATCH"):
                fn(self.document([0, 1]), times, session_id=SESSION, source_trc=TRC, calibration=CALIBRATION)

        empty = self.document([0])
        empty["frames"] = []
        with self.subTest(case="empty document"), self.assertRaisesRegex(ValueError, "FRAME_DIAGNOSTICS_INVALID"):
            fn(empty, [], session_id=SESSION, source_trc=TRC, calibration=CALIBRATION)
        huge = self.document([0, 1])
        huge["frames"][1]["synchronized_frame_index"] = 10 ** 1000
        with self.subTest(case="index overflow"), self.assertRaisesRegex(ValueError, "TIMING_GRID_MISMATCH"):
            fn(huge, [0, 1 / 30], session_id=SESSION, source_trc=TRC, calibration=CALIBRATION)
        capped = self.document([0])
        first = capped["frames"][0]
        capped["frames"] = [{**first, "synchronized_frame_index": index} for index in range(4097)]
        with self.subTest(case="bounded cap plus one"), self.assertRaisesRegex(ValueError, "TIMING_LIMIT_EXCEEDED"):
            fn(capped, [], session_id=SESSION, source_trc=TRC, calibration=CALIBRATION)

    def test_06_contiguous_positive_nonzero_start_does_not_invent_leading_missing(self):
        result = self.project([60, 61, 62])
        self.assertEqual(result["sample_counts"]["missing_interior"], 0)
        self.assertEqual(len(result["segments"]), 1)
        self.assertAlmostEqual(result["duration_s"]["valid_adjacent"], 2 / 30)
        self.assertIn("UNVERIFIED", result["source_extent"])

class ReconstructionTimingApiTests(unittest.TestCase):
    """Real generated public API; codec probing only is isolated by the existing helper."""
    def setUp(self):
        context_api.SessionMetadataContextApiTests.setUp(self)

    def stop_server(self):
        context_api.SessionMetadataContextApiTests.stop_server(self)

    def request(self, *args, **kwargs):
        return context_api.SessionMetadataContextApiTests.request(self, *args, **kwargs)

    def registered(self, *args, **kwargs):
        return context_api.SessionMetadataContextApiTests.registered(self, *args, **kwargs)

    def native_contract(self, root, **kwargs):
        context_api.SessionMetadataContextApiTests.native_contract(root, **kwargs)

    def fixture(self, sid, grid, rejected=(), *, diagnostics=True, diagnostic_grid=None):
        # Native synchronization retains positive indexes; keep relative gap/rejection geometry.
        shift = 1 if min(grid) == 0 else 0
        grid = [index + shift for index in grid]
        rejected = tuple(index + shift for index in rejected)
        if diagnostic_grid is not None:
            diagnostic_grid = [index + shift for index in diagnostic_grid]
        existing_native_contract = self.native_contract
        produced = {}

        def completed_native_contract(root):
            source_trc = _timing_trc(grid)
            existing_native_contract(root, source_trc=source_trc, downstream_trc=_timing_trc(grid[:3]))
            names = quality.FRAME_MARKERS
            trc_path = root / "pose-3d/fixture.trc"
            manifest = root / "run.json"
            run = json.loads(manifest.read_text(encoding="utf-8"))
            source = {"path": "pose-3d/fixture.trc", "sha256": sha256_file(trc_path)}
            run["stages"][4]["artifacts"] = [source]
            run["stages"][5]["quality"]["source"] = copy.deepcopy(source)
            if diagnostics:
                observations = []
                for index in grid if diagnostic_grid is None else diagnostic_grid:
                    template = 1 if index in rejected else 0
                    selected = copy.deepcopy([row for row in generated_observations() if row["frame"] == template])
                    for row in selected:
                        row["frame"] = index
                    observations.extend(selected)
                calibration = run["stages"][0]["artifacts"][0]
                document = quality.build_frame_diagnostics(observations, names,
                    {"session_id": sid, "camera_ids": list(quality.FRAME_CAMERAS),
                     "source_trc": source, "calibration": calibration})
                run["stages"][4]["quality"]["frame_diagnostics"] = quality.write_frame_diagnostics(root, document)
            manifest.write_text(json.dumps(run), encoding="utf-8")
            augmented = root / "pose-3d/fixture_filt_LSTM.trc"
            exported = motion(augmented, root / "kinematics/fixture.mot", run_manifest=manifest)
            (root / "exports/generated.motion.json").write_text(json.dumps(exported), encoding="utf-8")
            tracked = [root / name for name in ("session.json", "run.json",
                       "exports/generated.motion.json", "pose-3d/fixture.trc",
                       "pose-3d/fixture_filt_LSTM.trc", "kinematics/fixture.mot")]
            if diagnostics:
                tracked.append(root / run["stages"][4]["quality"]["frame_diagnostics"]["path"])
            produced.update({path.relative_to(root).as_posix(): path.read_bytes() for path in tracked})

        with patch.object(self, "native_contract", side_effect=completed_native_contract):
            root = self.registered(sid, native=True)
        self.assertTrue(produced, "completed source bytes must precede the first index baseline")
        self.assertEqual({name: (root / name).read_bytes() for name in produced}, produced,
                         "registration/indexing must preserve the completed source bytes")
        status, passport = self.request("GET", f"/api/v1/sessions/{sid}/passport")
        self.assertEqual(status, 200, passport)
        self.assertEqual(passport["state"], "KINEMATICS_PASSED", passport)
        self.assertEqual(passport.get("integrity_errors", []), [], passport)
        metadata = read_metadata_state(self.service.index, sid)
        self.assertEqual(metadata["status"], "AVAILABLE", metadata)
        self.assertEqual({name: (root / name).read_bytes() for name in produced}, produced,
                         "passport read must preserve the completed source bytes")
        return root

    def comparison(self):
        status, payload = self.request("GET", "/api/v1/compare?s1=a&s2=b")
        self.assertEqual(status, 200, payload)
        return payload

    def test_10_api_mixed_grid_uses_bound_unfiltered_trc_not_native_filtered_grid(self):
        root = self.fixture("a", [0, 1, 2, 4, 5], rejected=(2,))
        self.fixture("b", [0, 1, 2, 4, 5], rejected=(2,))
        original = (root / "session.json").read_bytes()
        result = self.comparison()
        self.assertTrue(result["compatible"], result["reason"])
        sources = result["research_measurements"]["sessions"]
        self.assertEqual([item["session_id"] for item in sources], ["a", "b"])
        for source in sources:
            self.assertIn("timing", source, "R04 MISSING: comparison source timing projection")
            timing = source["timing"]
            self.assertEqual(timing["status"], "AVAILABLE", timing)
            self.assertEqual(timing["sample_counts"], {"observed": 5, "valid": 4, "rejected": 1, "missing_interior": 1})
            self.assertNotEqual(timing["bindings"]["source_trc"]["sha256"], source["source_revision"]["trc_sha256"])
            self.assertEqual(timing["bindings"]["run_sha256"], source["source_revision"]["run_sha256"])
            self.assertEqual(timing["bindings"]["metadata_context_sha256"], source["metadata_context_sha256"])
            self.assertFalse(timing["bindings"]["comparison_source_observation"]["evidence_verified"])
            self.assertAlmostEqual(timing["duration_s"]["valid_adjacent"], 2 / 30)
        self.assertEqual((root / "session.json").read_bytes(), original)

    def test_11_api_grid_disagreement_is_precise_unavailable_not_valid_range(self):
        self.fixture("a", [0, 1, 2], diagnostic_grid=[0, 1, 3])
        self.fixture("b", [0, 1, 2])
        result = self.comparison()
        self.assertTrue(result["compatible"], result["reason"])
        source = result["research_measurements"]["sessions"][0]
        self.assertIn("timing", source, "R04 MISSING: grid mismatch timing projection")
        timing = source["timing"]
        self.assertEqual(timing["status"], "UNAVAILABLE")
        self.assertEqual(timing["code"], "TIMING_GRID_MISMATCH")
        self.assertIsNone(timing["duration_s"])
        self.assertEqual(timing["segments"], [])

    def test_12_api_singleton_and_rejected_endpoints_do_not_extrapolate(self):
        self.fixture("a", [70], rejected=(70,))
        self.fixture("b", [10, 11, 12], rejected=(10, 12))
        result = self.comparison()
        self.assertTrue(result["compatible"], result["reason"])
        for source in result["research_measurements"]["sessions"]:
            self.assertIn("timing", source, "R04 MISSING: singleton and endpoint timing projection")
        first, second = [source["timing"] for source in result["research_measurements"]["sessions"]]
        self.assertEqual(first["status"], "AVAILABLE", first)
        self.assertEqual(first["intervals"], [])
        self.assertTrue(all(value == 0 for value in first["duration_s"].values()))
        self.assertEqual(second["duration_s"]["valid_adjacent"], 0)
        self.assertEqual(len(second["intervals"]), 2)

    def test_13_api_mutation_during_same_byte_read_refuses_entire_stale_comparison(self):
        root = self.fixture("a", [0, 1, 2])
        self.fixture("b", [0, 1, 2])
        actual = comparison_revision._read_source
        changed = []
        def mutate(project, relative, budget):
            raw = actual(project, relative, budget)
            if project == root and relative == "pose-3d/fixture.trc" and not changed:
                with (root / relative).open("ab") as stream:
                    stream.write(b"\n")
                changed.append(True)
            return raw
        with patch("comparison_revision._read_source", side_effect=mutate):
            result = self.comparison()
        self.assertTrue(changed, "actual bound TRC read seam was not exercised")
        self.assertFalse(result["compatible"])
        self.assertEqual(result["research_measurements"]["coordinates"], [])
        self.assertIn("TIMING_SOURCE_CHANGED", result["reason"])
        self.assertTrue((root / "pose-3d/fixture.trc").read_bytes().endswith(b"\n\n"), "comparison must not repair attack bytes")

    def test_14_api_legacy_absence_preserves_angular_and_explicit_timing_unavailable(self):
        self.fixture("a", [0, 1, 2], diagnostics=False)
        self.fixture("b", [0, 1, 2], diagnostics=False)
        result = self.comparison()
        self.assertTrue(result["compatible"], result["reason"])
        self.assertTrue(result["research_measurements"]["coordinates"])
        for source in result["research_measurements"]["sessions"]:
            self.assertIn("timing", source, "R04 MISSING: explicit legacy timing projection")
            self.assertEqual(source["timing"]["code"], "TIMING_DIAGNOSTICS_ABSENT")
            self.assertEqual(source["timing"]["status"], "UNAVAILABLE")

    def test_15_api_changed_bound_source_bytes_refuse_without_heal(self):
        root = self.fixture("a", [0, 1, 2])
        self.fixture("b", [0, 1, 2])
        path = root / "pose-3d/fixture.trc"
        changed = path.read_bytes() + b"\n"
        path.write_bytes(changed)
        result = self.comparison()
        self.assertFalse(result["compatible"])
        self.assertEqual(result["research_measurements"]["coordinates"], [])
        self.assertEqual(path.read_bytes(), changed)

    def test_16_api_stale_metadata_context_refuses_no_favorable_timing_reuse(self):
        self.fixture("a", [0, 1, 2])
        self.fixture("b", [0, 1, 2])
        contexts = [read_metadata_state(self.service.index, sid)["context_sha256"] for sid in ("a", "b")]
        context_api.SessionMetadataContextApiTests.publish(self, "b", metadata=self.initial)
        path = ("/api/v1/compare?s1=a&s2=b&expected_metadata_context_s1=" + contexts[0]
                + "&expected_metadata_context_s2=" + contexts[1])
        status, result = self.request("GET", path)
        self.assertEqual(status, 200, result)
        self.assertFalse(result["compatible"])
        self.assertEqual(result["research_measurements"]["status"], "UNAVAILABLE")
        self.assertEqual(result["research_measurements"]["coordinates"], [])
        self.assertIn("METADATA_CONTEXT_CHANGED", result["reason"])
    def test_17_authenticated_passport_projects_bound_mixed_timing(self):
        root = self.fixture("a", [0, 1, 2, 4], rejected=(2,))
        original = (root / "session.json").read_bytes()
        status, passport = self.request("GET", "/api/v1/sessions/a/passport")
        self.assertEqual(status, 200, passport)
        self.assertIn("timing", passport, "R04 MISSING: authenticated passport timing projection")
        timing = passport["timing"]
        self.assertEqual(timing["status"], "AVAILABLE", timing)
        self.assertEqual(timing["sample_counts"], {"observed": 4, "valid": 3, "rejected": 1, "missing_interior": 1})
        self.assertEqual(timing["bindings"]["source_trc"]["path"], "pose-3d/fixture.trc")
        self.assertFalse(timing["physical_accuracy_verified"])
        self.assertEqual((root / "session.json").read_bytes(), original)

    def test_18_authenticated_passport_legacy_absence_is_explicit_unavailable(self):
        self.fixture("a", [0, 1], diagnostics=False)
        status, passport = self.request("GET", "/api/v1/sessions/a/passport")
        self.assertEqual(status, 200, passport)
        self.assertIn("timing", passport, "R04 MISSING: explicit unavailable passport timing")
        self.assertEqual(passport["timing"]["code"], "TIMING_DIAGNOSTICS_ABSENT")
        self.assertIsNone(passport["timing"]["duration_s"])
        self.assertEqual(passport["timing"]["segments"], [])

    def test_19_authenticated_passport_read_mutation_refuses_without_heal(self):
        root = self.fixture("a", [0, 1, 2, 4], rejected=(2,))
        actual = comparison_revision._read_source
        changed = []
        def mutate(project, relative, budget):
            raw = actual(project, relative, budget)
            if project == root and relative == "pose-3d/fixture.trc" and not changed:
                with (root / relative).open("ab") as stream:
                    stream.write(b"\n")
                changed.append(True)
            return raw
        with patch("comparison_revision._read_source", side_effect=mutate):
            status, passport = self.request("GET", "/api/v1/sessions/a/passport")
        self.assertEqual(status, 200, passport)
        self.assertIn("timing", passport, "R04 MISSING: guarded passport timing projection")
        self.assertEqual(passport["timing"]["status"], "UNAVAILABLE")
        self.assertEqual(passport["timing"]["code"], "TIMING_SOURCE_CHANGED")
        self.assertIsNone(passport["timing"]["duration_s"])
        self.assertTrue(changed, "actual source reader must be exercised")
        self.assertTrue((root / "pose-3d/fixture.trc").read_bytes().endswith(b"\n\n"))
