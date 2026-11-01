"""N01 rejected triangulation review: generated TEST_ONLY regressions.

Every fixture value is generated in a fresh owned temporary root. None is a
participant recording, measured value, physical accuracy or clinical claim.
RED expectation before the slice: assertion failures prefixed "N01-RR MISSING",
never ImportError or SyntaxError. Tests named *_compat pass before and after.
Prepared against run_pipeline.py adab083b...; pipeline_quality.py is in flight under root
(ed2664bd... at preparation, 59002ac4... at refinement). Content-bound at publication:
quality.json, the sidecar, source TRC, calibration, preflight.json and normalization.json
(normalized outputs through its stored hashes); Config.toml through run config_sha256.
run.json is structurally revalidated only: it cannot carry its own digest.
"""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pipeline_quality as quality
import run_pipeline
from native_evidence_fixture import native_chain_fixture
from normalize_capture import ROLES

SESSION = "TEST_ONLY-rr-generated"
OTHER = "TEST_ONLY-rr-other"
CAMERAS = ["cam01", "cam02"]
TRC_PATH = "pose-3d/TEST_ONLY.trc"
CAL_PATH = "calibration/TEST_ONLY.toml"
TRC_BYTES = ("PathFileType\t4\t(X/Y/Z)\tTEST_ONLY.trc\n"
             "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames\n"
             "30\t30\t6\t7\tmm\t30\t1\t6\n"
             "Frame#\tTime\t" + "\t\t\t".join(quality.FRAME_MARKERS) +
             "\t\t\n\t\t" + "\t".join(f"{axis}{index}" for index in range(1, 8) for axis in ("X", "Y", "Z")) + "\n" +
             "\n".join(f"{index}\t{index / 30:.12f}\t" + "\t".join(["0", "0", "1000"] * 7) for index in range(1, 7)) + "\n").encode("utf-8")
CAL_BYTES = b"# TEST_ONLY generated calibration\n"
REASON = "RECONSTRUCTION_REJECTED: TEST_ONLY generated coverage below criteria"
LABEL = "REJECTED / NOT USABLE FOR MEASUREMENT"
REJECTED_SCHEMA = "kinelab.rejected-triangulation.v1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def cell(status, likelihood=None, residual=None, depth=None):
    return {"status": status, "likelihood": likelihood, "reprojection_px": residual, "camera_depth": depth}


def observations():
    rows = []
    for frame in range(1, 7):
        for marker in quality.FRAME_MARKERS:
            cameras = {"cam01": cell("supported", .9, 2.0, 2.1), "cam02": cell("supported", .8, 3.5, 2.4)}
            if marker == "RKnee" and frame in (2, 3):
                cameras["cam02"] = cell("no_pose_file")
            rows.append({"frame": frame, "marker": marker, "cameras": cameras})
    return rows


def validator():
    api = getattr(run_pipeline, "validate_rejected_triangulation", None)
    unittest.TestCase().assertTrue(
        callable(api), "N01-RR MISSING: run_pipeline.validate_rejected_triangulation is not implemented")
    return api


class RejectedReviewBase(unittest.TestCase):
    def setUp(self):
        self.build()

    def build(self):
        owned = tempfile.TemporaryDirectory(prefix="kinelab-rr-TEST_ONLY-")
        self.addCleanup(owned.cleanup)
        self.project = Path(owned.name).resolve()
        self.write("Config.toml", b"# TEST_ONLY generated configuration\n")
        self.write(CAL_PATH, CAL_BYTES)
        self.session = {"session_id": SESSION, "captures": {
            role: {"sha256": sha(("TEST_ONLY original " + role).encode())} for role in ROLES},
            "camera_ids": list(CAMERAS)}
        self.identity = {"session_id": SESSION, "config_sha256": sha((self.project / "Config.toml").read_bytes()), "inputs": {role: entry["sha256"] for role, entry in self.session["captures"].items()}}
        # Real generated TEST_ONLY media and both-camera native memberships;
        # the native algorithm delegate remains a unit seam in triangulate().
        self.native_record = native_chain_fixture(
            self.project, self.identity, counts={"cam01": 7, "cam02": 7})
        # run.json is a mutable publication output, not a source input.
        # Keep the generated record in memory until triangulate publishes it.
        (self.project / "run.json").unlink()
        log = self.project / "logs.txt"
        start = log.stat().st_size
        unit_log = b"TEST_ONLY mocked calibration delegate; no native inference or physical proof\n"
        with log.open("ab") as stream:
            stream.write(unit_log)
        self.calibration_log = {
            "path": "logs.txt", "start": start, "end": start + len(unit_log),
            "sha256": sha(unit_log),
        }

    def write(self, relative, data):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def write_json(self, relative, value):
        return self.write(relative, json.dumps(value, indent=2).encode("utf-8"))

    def sidecar(self, session=SESSION, trc_sha=None):
        document = quality.build_frame_diagnostics(observations(), list(quality.FRAME_MARKERS), {
            "session_id": session, "camera_ids": list(CAMERAS),
            "source_trc": {"path": TRC_PATH, "sha256": trc_sha or sha(TRC_BYTES)},
            "calibration": {"path": CAL_PATH, "sha256": sha(CAL_BYTES)}})
        return quality.write_frame_diagnostics(self.project, document)

    def report(self, ok=False, session=SESSION, diagnostics=True, trc_sha=None, binding=None):
        value = {"schema": "kinelab.quality.v1", "policy": quality.QUALITY_POLICY, "session_id": SESSION, "ok": ok,
                 "errors": [] if ok is True else [REASON],
                 "source_coverage": copy.deepcopy(self.native_record["stages"][3]["quality"]["source_coverage"])}
        if diagnostics:
            value["frame_diagnostics"] = binding if binding is not None else self.sidecar(session=session, trc_sha=trc_sha)
        return quality._save(self.project, "quality.json", value)

    def prior_record(self):
        record = copy.deepcopy(self.native_record)
        record["coordinateSystem"] = "opensim_y_up"
        record["native_triangulation_policy"] = {"interpolation": "none", "fill_large_gaps_with": "nan"}
        record["stages"][0] = {
            "name": "calibration", "status": "passed",
            "artifacts": [{"path": CAL_PATH, "sha256": sha(CAL_BYTES)}],
            "quality": {"ok": True, "fixture_only": True, "policy": quality.QUALITY_POLICY,
                        "log": copy.deepcopy(self.calibration_log)}}
        return record

    def triangulate(self, produce, expect_error=True):
        """Run the real run_stages triangulation branch with the native call and session loader replaced."""
        prior = self.prior_record()
        self.write_json("run.json", prior)

        def native(stage, project):
            self.write(TRC_PATH, TRC_BYTES)
        with mock.patch.object(run_pipeline, "load_session", return_value=self.session), \
                mock.patch.object(run_pipeline, "validate_run_evidence", return_value={"run": prior}), \
                mock.patch.object(run_pipeline, "_invoke_stage", side_effect=native), \
                mock.patch.object(run_pipeline, "_validate_artifacts"), \
                mock.patch.object(run_pipeline, "_validate_stage_quality", side_effect=produce):
            if expect_error:
                with self.assertRaises(ValueError):
                    run_pipeline.run_stages(self.project, "triangulation", "triangulation")
            else:
                run_pipeline.run_stages(self.project, "triangulation", "triangulation")
        return json.loads((self.project / "run.json").read_text(encoding="utf-8"))

    def rejected_run(self):
        self.published = self.report(ok=False)
        return self.triangulate(lambda *args, **kwargs: self.published)


class RejectedEvidencePublicationTests(RejectedReviewBase):
    def test_policy_and_schema_binding_compat(self):
        self.assertEqual(quality.QUALITY_POLICY, "kinelab.pipeline-quality.v4")
        self.assertEqual(run_pipeline.QUALITY_POLICY, quality.QUALITY_POLICY)
        self.assertEqual(quality.FRAME_DIAGNOSTICS_SCHEMA, "kinelab.reconstruction-frames.v1")

    def test_returned_rejected_quality_is_published_as_separate_failed_stage_evidence(self):
        run = self.rejected_run()
        item = run["stages"][run_pipeline.STAGES.index("triangulation")]
        self.assertEqual(item["status"], "failed")
        self.assertTrue(item["error"].startswith("ValueError: QUALITY_REJECTED"))
        self.assertIn("rejected_evidence", item, "N01-RR MISSING: failed triangulation did not publish rejected_evidence")
        evidence = item["rejected_evidence"]
        self.assertEqual(evidence["schema"], REJECTED_SCHEMA)
        self.assertEqual(evidence["session_id"], SESSION)
        self.assertEqual(evidence["quality"], {"path": "quality.json", "sha256": sha((self.project / "quality.json").read_bytes())})
        self.assertEqual(evidence["frame_diagnostics"], self.published["frame_diagnostics"])
        self.assertEqual(evidence["source_trc"], {"path": TRC_PATH, "sha256": sha(TRC_BYTES)})
        self.assertEqual(evidence["calibration"], {"path": CAL_PATH, "sha256": sha(CAL_BYTES)})
        self.assertEqual(evidence["bound_inputs"], {
            "preflight": {"path": "preflight.json", "sha256": sha((self.project / "preflight.json").read_bytes())},
            "normalization": {"path": "normalization.json", "sha256": sha((self.project / "normalization.json").read_bytes())}},
            "publication must bind the exact preflight and normalization bytes it observed")
        self.assertEqual(evidence["reasons"], [REASON])
        self.assertIs(evidence["usable_for_measurement"], False)

    def test_rejected_evidence_never_promotes_the_stage(self):
        item = self.rejected_run()["stages"][run_pipeline.STAGES.index("triangulation")]
        self.assertEqual(item["artifacts"], [], "a rejected TRC must never become a passed-stage artifact")
        self.assertNotIn("quality", item, "a rejected quality report must never occupy the passed-stage quality key")
        self.assertNotEqual(item["status"], "passed")

    def test_unavailable_outcomes_publish_nothing_compat(self):
        def raise_before(*args, **kwargs):
            raise ValueError("RECONSTRUCTION_REJECTED: TEST_ONLY error before diagnostics")
        cases = {
            "error before diagnostics": raise_before,
            "rejected without diagnostics": lambda *a, **k: self.report(ok=False, diagnostics=False),
            "ok None": lambda *a, **k: self.report(ok=None),
            "ok zero": lambda *a, **k: self.report(ok=0),
            "ok string": lambda *a, **k: self.report(ok="false"),
            "non-dict": lambda *a, **k: [],
            "cross-session sidecar": lambda *a, **k: self.report(ok=False, session=OTHER),
            "source-swapped sidecar": lambda *a, **k: self.report(ok=False, trc_sha="0" * 64),
            "malformed binding": lambda *a, **k: self.report(ok=False, binding={"path": "diagnostics/x.json"}),
        }
        for name, produce in cases.items():
            with self.subTest(name):
                self.build()
                item = self.triangulate(produce)["stages"][run_pipeline.STAGES.index("triangulation")]
                self.assertEqual(item["status"], "failed")
                self.assertNotIn("rejected_evidence", item)

    def test_validator_refuses_unpublished_outcomes(self):
        api = validator()
        for name, produce in {"rejected without diagnostics": lambda *a, **k: self.report(ok=False, diagnostics=False),
                              "cross-session sidecar": lambda *a, **k: self.report(ok=False, session=OTHER)}.items():
            with self.subTest(name):
                self.build()
                self.triangulate(produce)
                with self.assertRaises(ValueError):
                    api(self.project, session=self.session)

    def test_ordinary_passed_triangulation_is_unchanged_compat(self):
        published = {}

        def passed(*args, **kwargs):
            published.update(self.report(ok=True))
            return published
        run = self.triangulate(passed, expect_error=False)
        item = run["stages"][run_pipeline.STAGES.index("triangulation")]
        self.assertEqual(item["status"], "passed")
        self.assertEqual(item["artifacts"], [{"path": TRC_PATH, "sha256": sha(TRC_BYTES)}])
        self.assertEqual(item["quality"], published)
        self.assertEqual(set(item), {"name", "status", "artifacts", "quality", "started_at", "completed_at"})

    def test_measurement_validator_still_refuses_rejected_run_compat(self):
        self.rejected_run()
        with self.assertRaises(ValueError):
            run_pipeline.validate_run_evidence(self.project, "triangulation", session=self.session)


    def test_run_manifest_is_structurally_read_not_self_hashed(self):
        api = validator()
        self.rejected_run()
        path = self.project / "run.json"
        path.write_text(json.dumps(json.loads(path.read_text(encoding="utf-8"))), encoding="utf-8")
        result = api(self.project, session=self.session)
        self.assertEqual(result["status"], "REJECTED", "run.json is structurally revalidated; it cannot carry its own digest")


class RejectedEvidenceReviewTests(RejectedReviewBase):
    def directory_alias(self, root):
        owned = tempfile.TemporaryDirectory(prefix="TEST_ONLY-linked-root-")
        self.addCleanup(owned.cleanup)
        alias = Path(owned.name) / "project-alias"
        self.addCleanup(alias.unlink, missing_ok=True)
        try:
            alias.symlink_to(root, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest("directory symlink unavailable: " + type(error).__name__)
        self.assertTrue(alias.is_symlink())
        self.assertEqual(alias.resolve(), root.resolve())
        return alias

    def test_review_refuses_linked_project_root_with_intact_rejected_evidence(self):
        # Assemble the existing generated rejected contract without triangulate()'s
        # unit seams: both admission APIs and all read/decode checks remain real.
        record = self.prior_record()
        self.write(TRC_PATH, TRC_BYTES)
        report = self.report(ok=False)
        evidence = run_pipeline._rejected_evidence(
            self.project, self.session, record, report,
            {TRC_PATH: (sha(TRC_BYTES), (self.project / TRC_PATH).stat().st_mtime_ns)})
        self.assertIsInstance(evidence, dict)
        record["stages"][run_pipeline.STAGES.index("triangulation")] = {
            "name": "triangulation", "status": "failed", "artifacts": [],
            "rejected_evidence": evidence}
        self.write_json("run.json", record)
        api = validator()
        self.assertEqual(api(self.project, session=self.session)["status"], "REJECTED")
        alias = self.directory_alias(self.project)
        before = {path.relative_to(self.project).as_posix(): path.read_bytes()
                  for path in self.project.rglob("*") if path.is_file()}
        try:
            with self.assertRaisesRegex(ValueError, "^REJECTED_EVIDENCE_UNVERIFIED:"):
                api(alias, session=self.session)
        finally:
            self.assertEqual({path.relative_to(self.project).as_posix(): path.read_bytes()
                              for path in self.project.rglob("*") if path.is_file()}, before)
            self.assertTrue(alias.is_symlink())

    def test_exact_rejected_evidence_reviews_read_only(self):
        api = validator()
        self.rejected_run()
        before = {path: sha(path.read_bytes()) for path in self.project.rglob("*") if path.is_file()}
        result = api(self.project, session=self.session)
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["label"], LABEL)
        self.assertIs(result["usable_for_measurement"], False)
        self.assertEqual(result["reasons"], [REASON])
        self.assertEqual(result["frame_diagnostics"]["session_id"], SESSION)
        self.assertEqual(len(result["frame_diagnostics"]["frames"]), 6)
        rknee = result["frame_diagnostics"]["frames"][2]["markers"]["RKnee"]["cameras"]["cam02"]
        self.assertIsNone(rknee["likelihood"], "unavailable camera values must stay unavailable, not fabricated")
        self.assertEqual({path: sha(path.read_bytes()) for path in self.project.rglob("*") if path.is_file()}, before,
                         "review must not write, repair or promote any file")

    def test_changed_bound_bytes_or_identity_invalidate_review(self):
        api = validator()
        triangulation = run_pipeline.STAGES.index("triangulation")

        def edit_run(change):
            def apply():
                path = self.project / "run.json"
                record = json.loads(path.read_text(encoding="utf-8"))
                change(record, record["stages"][triangulation])
                path.write_text(json.dumps(record), encoding="utf-8")
            return apply

        def append(relative):
            return lambda: (self.project / relative).write_bytes((self.project / relative).read_bytes() + b"\n")
        mutations = {
            "sidecar bytes": lambda: append(self.published["frame_diagnostics"]["path"])(),
            "quality bytes": append("quality.json"),
            "source TRC bytes": append(TRC_PATH),
            "calibration bytes": append(CAL_PATH),
            "configuration": append("Config.toml"),
            "preflight": append("preflight.json"),
            "normalization record": append("normalization.json"),
            "normalized output": lambda: append(next(iter(ROLES.values())))(),
            "stage promoted": edit_run(lambda record, item: item.update(status="passed")),
            "quality hash rebound": edit_run(lambda record, item: item["rejected_evidence"]["quality"].update(sha256="0" * 64)),
            "protocol changed": edit_run(lambda record, item: record.update(quality_policy="kinelab.pipeline-quality.v1")),
            "evidence removed": edit_run(lambda record, item: item.pop("rejected_evidence", None)),
        }
        for name, mutate in mutations.items():
            with self.subTest(name):
                self.build()
                self.rejected_run()
                mutate()
                with self.assertRaises(ValueError):
                    api(self.project, session=self.session)

    def test_other_session_invalidates_review(self):
        api = validator()
        self.rejected_run()
        with self.assertRaises(ValueError):
            api(self.project, session={**self.session, "session_id": OTHER})

    def test_linked_bound_file_is_refused(self):
        api = validator()
        self.rejected_run()
        target = self.project / "quality.json"
        moved = self.project / "TEST_ONLY-quality-target.json"
        target.replace(moved)
        try:
            os.symlink(moved, target)
        except (OSError, NotImplementedError) as error:
            self.skipTest("symlink creation unavailable on this host: " + type(error).__name__)
        with self.assertRaises(ValueError):
            api(self.project, session=self.session)


# Appended 2026-10-29 (independent review finding N01-IR-04). The original 12 methods
# above are unchanged. The browser validator requires quality schema exactly
# "kinelab.quality.v1"; publication and the read-only Python review must agree.
QUALITY_SCHEMA = "kinelab.quality.v1"
ABSENT = object()
BAD_SCHEMAS = {"schema missing": ABSENT, "schema null": None, "schema wrong version": "kinelab.quality.v0",
               "schema of another report": "kinelab.calibration-quality.v1"}


class RejectedQualitySchemaRegressionTests(RejectedReviewBase):
    def files(self):
        return {path.relative_to(self.project).as_posix(): sha(path.read_bytes())
                for path in self.project.rglob("*") if path.is_file()}

    def schema_report(self, schema):
        value = {"policy": quality.QUALITY_POLICY, "session_id": SESSION, "ok": False, "errors": [REASON],
                 "frame_diagnostics": self.sidecar(),
                 "source_coverage": copy.deepcopy(self.native_record["stages"][3]["quality"]["source_coverage"])}
        if schema is not ABSENT:
            value = {"schema": schema, **value}
        self.returned = quality._save(self.project, "quality.json", value)
        self.stored_quality = sha((self.project / "quality.json").read_bytes())
        return self.returned

    def test_rejected_quality_without_exact_schema_publishes_nothing(self):
        triangulation = run_pipeline.STAGES.index("triangulation")
        for name, schema in {"control exact schema": QUALITY_SCHEMA, **BAD_SCHEMAS}.items():
            with self.subTest(name):
                self.build()
                inputs = self.files()
                item = self.triangulate(lambda *a, s=schema, **k: self.schema_report(s))["stages"][triangulation]
                stored = json.loads((self.project / "quality.json").read_text(encoding="utf-8"))
                # Fixture invariants: the returned report is the persisted report and differs from a
                # publishable one only in its schema; the generated inputs were not touched.
                self.assertEqual(stored, self.returned)
                self.assertEqual(sha((self.project / "quality.json").read_bytes()), self.stored_quality)
                self.assertEqual(stored.get("schema", ABSENT), schema)
                self.assertEqual({key: value for key, value in self.files().items() if key in inputs}, inputs)
                self.assertEqual(set(self.files()) - set(inputs),
                                 {"run.json", TRC_PATH, "quality.json", self.returned["frame_diagnostics"]["path"]})
                self.assertEqual(item["status"], "failed")
                self.assertTrue(item["error"].startswith("ValueError: QUALITY_REJECTED"))
                self.assertEqual(item["artifacts"], [])
                self.assertNotIn("quality", item)
                if schema == QUALITY_SCHEMA:
                    self.assertIn("rejected_evidence", item, "control: the exact-schema report must publish")
                else:
                    self.assertNotIn("rejected_evidence", item,
                                     "N01-RR SCHEMA: a rejected quality report without schema " + QUALITY_SCHEMA
                                     + " must publish no rejected_evidence")

    def test_rebound_quality_without_exact_schema_is_refused_without_rewrite(self):
        api = validator()
        triangulation = run_pipeline.STAGES.index("triangulation")
        for name, schema in {"control rebound exact schema": QUALITY_SCHEMA, **BAD_SCHEMAS}.items():
            with self.subTest(name):
                self.build()
                self.rejected_run()
                self.assertEqual(api(self.project, session=self.session)["status"], "REJECTED")
                run_path, quality_path = self.project / "run.json", self.project / "quality.json"
                record = json.loads(run_path.read_text(encoding="utf-8"))
                report = json.loads(quality_path.read_text(encoding="utf-8"))
                self.assertEqual(report["schema"], QUALITY_SCHEMA)
                report.pop("schema")
                if schema is not ABSENT:
                    report = {"schema": schema, **report}
                data = json.dumps(report, indent=2).encode("utf-8")
                quality_path.write_bytes(data)
                record["stages"][triangulation]["rejected_evidence"]["quality"]["sha256"] = sha(data)
                run_path.write_text(json.dumps(record), encoding="utf-8")
                # Fixture invariants: the rebound digest matches the tampered bytes and only the schema differs.
                self.assertEqual(json.loads(run_path.read_text(encoding="utf-8"))["stages"][triangulation]
                                 ["rejected_evidence"]["quality"], {"path": "quality.json", "sha256": sha(quality_path.read_bytes())})
                stored = json.loads(quality_path.read_text(encoding="utf-8"))
                self.assertEqual({k: v for k, v in stored.items() if k != "schema"},
                                 {k: v for k, v in self.published.items() if k != "schema"})
                self.assertEqual(stored.get("schema", ABSENT), schema)
                before = self.files()
                if schema == QUALITY_SCHEMA:
                    self.assertEqual(api(self.project, session=self.session)["status"], "REJECTED",
                                     "control: rebinding exact-schema bytes must still review")
                else:
                    with self.assertRaises(ValueError, msg="N01-RR SCHEMA: review must refuse quality schema " + repr(schema)):
                        api(self.project, session=self.session)
                self.assertEqual(self.files(), before, "review must not heal, rewrite or promote any file")


if __name__ == "__main__":
    unittest.main()
