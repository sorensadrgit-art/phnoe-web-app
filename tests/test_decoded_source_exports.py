"""TEST_ONLY public-caller decoded-extent regressions using real normalized clips.

The fixture selects the installed production quality policy. No successful decoder
is mocked. Resume injects only a native-delegate tripwire after real validation;
decoder-unavailable cases inject negative I/O failure after a real positive.
"""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import export_motion
import normalize_capture
import run_pipeline
from native_evidence_fixture import complete_native_fixture
from session_contract import ROLES
from tools import verify_evidence


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def trc(first=1, stop=9):
    rows = ["PathFileType\t4\t(X/Y/Z)\tTEST_ONLY.trc",
            "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames",
            f"30\t30\t{stop-first}\t2\tm\t30\t{first}\t{stop-first}",
            "Frame#\tTime\tHip\t\t\tRHip\t\t", "\t\tX1\tY1\tZ1\tX2\tY2\tZ2"]
    rows.extend(f"{index}\t{index / 30:.9f}\t0\t1\t0\t.1\t1\t0" for index in range(first, stop))
    return "\n".join(rows) + "\n"


class DelegateReached(RuntimeError):
    """Negative tripwire: a caller reached native work before refusing bad evidence."""


class DecodedSourceExportsTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix="TEST_ONLY-decoded-exports-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "Config.toml").write_text("# TEST_ONLY generated fixture\n[project]\n", encoding="utf-8")
        captures = {}
        for role in ROLES:
            path = root / ("TEST_ONLY-" + role + ".mp4")
            path.write_bytes(("TEST_ONLY original role, no physical claim: " + role).encode())
            captures[role] = {"path": path.name, "sha256": digest(path.read_bytes())}
        session = {"schema": "kinelab.session.v1", "session_id": "TEST_ONLY-decoded-exports",
                   "kind": "real", "subject_count": 1, "camera_ids": ["cam01", "cam02"],
                   "created_at": "2026-10-31T00:00:00+00:00", "captures": captures}
        (root / "session.json").write_bytes(canonical(session))
        manifest, filtered, _ = complete_native_fixture(root, trc())
        # This is actual installed public validation, before any negative injection.
        self.assertEqual(run_pipeline.validate_run_evidence(root, "filtering")["run"]["session_id"],
                         session["session_id"])
        return root, manifest, filtered

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

    def test_validate_refuses_linked_project_root_with_intact_evidence(self):
        root, _, _ = self.fixture()
        alias = self.directory_alias(root)
        ordinary = run_pipeline.validate_run_evidence(root, "filtering")
        self.assertEqual(ordinary["run"]["session_id"], "TEST_ONLY-decoded-exports")
        before = {path.relative_to(root).as_posix(): path.read_bytes()
                  for path in root.rglob("*") if path.is_file()}
        try:
            with self.assertRaisesRegex(ValueError, "^ARTIFACT_MISMATCH:"):
                run_pipeline.validate_run_evidence(alias, "filtering")
        finally:
            self.assertEqual({path.relative_to(root).as_posix(): path.read_bytes()
                              for path in root.rglob("*") if path.is_file()}, before)
            self.assertTrue(alias.is_symlink())

    def test_resume_refuses_linked_project_root_before_native_delegate(self):
        root, manifest, _ = self.fixture()
        alias = self.directory_alias(root)
        original = manifest.read_bytes()
        # Only the native delegate is replaced; all admission and decoder gates run.
        with mock.patch.object(run_pipeline, "_invoke_stage", side_effect=DelegateReached("TEST_ONLY")) as delegate:
            with self.assertRaises(DelegateReached):
                run_pipeline.run_stages(root, "filtering", "filtering")
            self.assertEqual(delegate.call_count, 1)
        manifest.write_bytes(original)
        before = {path.relative_to(root).as_posix(): path.read_bytes()
                  for path in root.rglob("*") if path.is_file()}
        try:
            with mock.patch.object(run_pipeline, "_invoke_stage", side_effect=DelegateReached("TEST_ONLY")) as delegate:
                with self.assertRaisesRegex(ValueError, "^QUALITY_UNVERIFIED:"):
                    run_pipeline.run_stages(alias, "filtering", "filtering")
                self.assertEqual(delegate.call_count, 0)
        finally:
            self.assertEqual({path.relative_to(root).as_posix(): path.read_bytes()
                              for path in root.rglob("*") if path.is_file()}, before)
            self.assertTrue(alias.is_symlink())

    def assert_declared_hashes(self, root, record):
        for stage in record["stages"]:
            for artifact in stage["artifacts"]:
                self.assertEqual(artifact["sha256"], digest((root / artifact["path"]).read_bytes()))
        normalization = (root / "normalization.json").read_bytes()
        self.assertEqual(record["normalization"]["sha256"], digest(normalization))
        for item in json.loads(normalization)["outputs"].values():
            self.assertEqual(item["sha256"], digest((root / item["path"]).read_bytes()))

    def shorten_association_and_trc(self, root, manifest):
        record = json.loads(manifest.read_bytes())
        old = copy.deepcopy(record)
        for camera in ("cam01", "cam02"):
            folder = root / "pose-associated" / (camera + "_json")
            for index in (1, 8):
                (folder / f"{camera}_{index:06d}.json").unlink()
        for stage in record["stages"]:
            if stage["name"] == "personAssociation":
                stage["artifacts"] = [item for item in stage["artifacts"] if (root / item["path"]).is_file()]
            if stage["name"] in ("triangulation", "filtering"):
                for item in stage["artifacts"]:
                    path = root / item["path"]
                    path.write_text(trc(2, 8), encoding="utf-8")
                    item["sha256"] = digest(path.read_bytes())
            if stage["name"] in ("personAssociation", "triangulation"):
                # An attacker can relabel an unsigned summary as well as every file hash.
                stage["quality"]["source_coverage"]["common_range"] = [2, 8]
        # Filtering binds the actual newly shortened upstream TRC, not its old hash.
        upstream = next(item for item in record["stages"] if item["name"] == "triangulation")["artifacts"][0]
        next(item for item in record["stages"] if item["name"] == "filtering")["quality"]["source"] = copy.deepcopy(upstream)
        manifest.write_bytes(canonical(record))
        self.assert_declared_hashes(root, record)
        # Raw pose, synchronization, normalization and the source log are all intact.
        for index in (0, 1, 2):
            self.assertEqual(record["stages"][index], old["stages"][index])
        self.assertEqual(record["normalization"], old["normalization"])
        return record

    def test_validate_refuses_coherent_associated_and_trc_endpoint_crop(self):
        root, manifest, _ = self.fixture()
        self.shorten_association_and_trc(root, manifest)
        with self.assertRaisesRegex(ValueError, "(?i)(decoded|coverage|endpoint|extent|common|membership)"):
            run_pipeline.validate_run_evidence(root, "filtering")

    def test_resume_refuses_crop_before_native_delegate(self):
        root, manifest, _ = self.fixture()
        original = manifest.read_bytes()
        # Positive boundary control: intact evidence reaches the delegate. It does
        # not fake a successful native stage or decoder invocation.
        with mock.patch.object(run_pipeline, "_invoke_stage", side_effect=DelegateReached("TEST_ONLY")) as delegate:
            with self.assertRaises(DelegateReached):
                run_pipeline.run_stages(root, "filtering", "filtering")
            self.assertEqual(delegate.call_count, 1)
        manifest.write_bytes(original)
        self.shorten_association_and_trc(root, manifest)
        with mock.patch.object(run_pipeline, "_invoke_stage", side_effect=DelegateReached("TEST_ONLY")) as delegate:
            with self.assertRaisesRegex(ValueError, "(?i)(decoded|coverage|endpoint|extent|common|membership)"):
                run_pipeline.run_stages(root, "filtering", "filtering")
            self.assertEqual(delegate.call_count, 0)

    def test_motion_export_refuses_coherent_associated_and_trc_endpoint_crop(self):
        root, manifest, filtered = self.fixture()
        intact = export_motion.motion(filtered, run_manifest=manifest)
        self.assertEqual(len(intact["frames"]), 8)
        self.shorten_association_and_trc(root, manifest)
        with self.assertRaisesRegex(ValueError, "(?i)(decoded|coverage|endpoint|extent|common|membership)"):
            export_motion.motion(filtered, run_manifest=manifest)

    def test_cache_redecodes_rehashed_normalized_media_instead_of_trusting_old_count(self):
        root, manifest, _ = self.fixture()
        record = json.loads(manifest.read_bytes())
        normalized = json.loads((root / "normalization.json").read_bytes())
        # Replace a trial with another REAL, valid generated clip (two frames),
        # preserving the false old nine-frame declaration. Every digest is rebound.
        replacement = root / normalized["outputs"]["cam01_intrinsics"]["path"]
        target = root / normalized["outputs"]["cam01_trial"]["path"]
        self.assertNotEqual(target.read_bytes(), replacement.read_bytes())
        target.write_bytes(replacement.read_bytes())
        normalized["outputs"]["cam01_trial"]["sha256"] = digest(target.read_bytes())
        (root / "normalization.json").write_bytes(canonical(normalized))
        record["normalization"]["sha256"] = digest(canonical(normalized))
        for stage in record["stages"]:
            summary = stage.get("quality", {}).get("source_coverage")
            if summary:
                summary["normalization"] = copy.deepcopy(record["normalization"])
                summary["cameras"]["cam01"]["sha256"] = digest(target.read_bytes())
        manifest.write_bytes(canonical(record))
        self.assert_declared_hashes(root, record)
        with self.assertRaisesRegex(ValueError, "(?i)(decoded|normaliz|count|timestamp|coverage)"):
            run_pipeline.validate_run_evidence(root, "filtering")

    def test_cached_validation_refuses_unavailable_decoder_after_real_positive(self):
        root, _, _ = self.fixture()
        # Negative I/O injection only; the intact control above used the real decoder.
        before = {path.relative_to(root).as_posix(): digest(path.read_bytes())
                  for path in root.rglob("*") if path.is_file()}
        missing = FileNotFoundError("TEST_ONLY decoder absent")
        # Inject at spawn, below the real inspect_video error adapter.
        with (mock.patch.object(normalize_capture.subprocess, "Popen", side_effect=missing) as probe,
              self.assertRaisesRegex(ValueError, r"^INPUT_MISSING: FFprobe is required on PATH$") as caught):
            run_pipeline.validate_run_evidence(root, "filtering")
        attempts = list(probe.call_args_list)
        self.assertIn(len(attempts), (1, 2))
        names = [Path(call.args[0][-1]).name for call in attempts]
        self.assertCountEqual(names, ["cam01.mp4"] if len(attempts) == 1 else ["cam01.mp4", "cam02.mp4"])
        for call in attempts:
            self.assertEqual(call.args[0][0], "ffprobe")
        self.assertIs(caught.exception.__cause__, missing)
        self.assertEqual({path.relative_to(root).as_posix(): digest(path.read_bytes())
                          for path in root.rglob("*") if path.is_file()}, before)

    @staticmethod
    def portable_fixture():
        # Reuse the real report, audit, backup and manual-assessment producer. Its
        # original-source metadata seam is not a normalized-media decoder mock.
        from test_offline_manual_report import OfflineManualReportTests
        helper = OfflineManualReportTests("test_00_actual_gait_manual_v2_requires_semantic_acceptance")
        helper.setUp()
        return helper

    def verify_archive(self, archive, expected):
        before = digest(archive.read_bytes())
        result = verify_evidence.verify_archive(archive)
        self.assertEqual(digest(archive.read_bytes()), before)
        self.assertIs(result["ok"], expected, json.dumps(result, sort_keys=True))
        self.assertFalse(result["scope"]["physical_accuracy_verified"])
        self.assertEqual(result["scope"]["clinical_validation"], "UNVERIFIED")
        return result

    def test_portable_refuses_coherent_raw_crop_and_rehashed_normalization_declaration(self):
        helper = self.portable_fixture()
        with helper.fixture() as (case, archive, files, _):
            self.verify_archive(archive, True)
            generation = files["json"].parent.name

            def mutate(payload, connection):
                import test_report_current_context as reports
                prefix = f"sessions/{reports.SID}/"
                original_payload = dict(payload)
                published_outputs = {name: raw for name, raw in payload.items()
                                     if name.startswith(prefix + f"exports/{generation}/")
                                     and not name.endswith("/manifest.json")}
                self.assertEqual(set(published_outputs), {
                    prefix + f"exports/{generation}/{reports.SID}-{suffix}"
                    for suffix in ("research-report.pdf", "research-summary.json", "metrics.csv")})
                normal = json.loads(payload[prefix + "normalization.json"])
                run = json.loads(payload[prefix + "run.json"])
                pose = next(item for item in run["stages"] if item["name"] == "poseEstimation")
                old_media = {camera: payload[prefix + normal["outputs"][camera + "_trial"]["path"]]
                             for camera in ("cam01", "cam02")}
                for camera in ("cam01", "cam02"):
                    item = normal["outputs"][camera + "_trial"]
                    last = item["frame_count"] - 1
                    item["frame_count"] = last
                    item["timestamps"] = item["timestamps"][:-1]
                    relative = f"pose/{camera}_json/{camera}_{last:06d}.json"
                    self.assertIn(prefix + relative, payload)
                    payload.pop(prefix + relative)
                    pose["artifacts"] = [entry for entry in pose["artifacts"] if entry["path"] != relative]
                    summary = pose["quality"]["source_coverage"]["cameras"][camera]
                    summary["decoded_frame_count"] = last
                    summary["source_range"] = [0, last]
                payload[prefix + "normalization.json"] = canonical(normal)
                run["normalization"]["sha256"] = digest(payload[prefix + "normalization.json"])
                pose["quality"]["source_coverage"]["normalization"] = copy.deepcopy(run["normalization"])
                payload[prefix + "run.json"] = canonical(run)
                forged_run_sha = digest(payload[prefix + "run.json"])
                # Entry-time run snapshots must remain byte-identical to their
                # rehashed current input. We do not merely break a copied hash.
                for member in list(payload):
                    if member.startswith(prefix) and member.endswith("/run.json"):
                        payload[member] = payload[prefix + "run.json"]
                normalization_snapshots = [member for member in payload
                    if member.startswith(prefix + "exports/manual-entry-")
                    and member.endswith(".manual-assessment-inputs/normalization.json")]
                self.assertTrue(normalization_snapshots)
                for member in normalization_snapshots:
                    payload[member] = payload[prefix + "normalization.json"]
                # Dependencies are exact inventories; remove both deleted pose
                # members wherever the existing descriptor recorded them.
                def rebind(value):
                    if isinstance(value, dict):
                        for key in list(value):
                            if key.startswith("pose/") and prefix + key not in payload:
                                del value[key]
                        for member, raw in payload.items():
                            if member.startswith(prefix) and raw != original_payload.get(member):
                                helper.replace_binding(value, member[len(prefix):], raw)
                        if isinstance(value.get("run"), dict) and value["run"].get("through") == "poseEstimation":
                            value["run"]["sha256"] = forged_run_sha
                        for child in value.values():
                            rebind(child)
                    elif isinstance(value, list):
                        for child in value:
                            rebind(child)
                # Acyclic current->snapshot->descriptor bindings settle before
                # report/audit receipts are resealed by their existing helpers.
                for _round in range(8):
                    forged_run_sha = digest(payload[prefix + "run.json"])
                    changed = False
                    for member in list(payload):
                        if not member.startswith(prefix) or not member.endswith(".json") or member.startswith(prefix + f"exports/{generation}/"):
                            continue
                        try:
                            document = json.loads(payload[member])
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            continue
                        original_document = copy.deepcopy(document)
                        rebind(document)
                        if document == original_document:
                            continue
                        raw = canonical(document)
                        if raw != payload[member]:
                            payload[member] = raw
                            changed = True
                    if not changed:
                        break
                else:
                    self.fail("TEST_ONLY adversarial bindings did not converge")
                forged_run_sha = digest(payload[prefix + "run.json"])
                for member in payload:
                    if member.startswith(prefix) and member.endswith("/run.json"):
                        self.assertEqual(payload[member], payload[prefix + "run.json"])
                for member in normalization_snapshots:
                    self.assertEqual(payload[member], payload[prefix + "normalization.json"])
                for row in connection.execute("SELECT id,details_json FROM audit_events WHERE event_type='MANUAL_ASSESSMENT_ENTRY_PUBLISHED'").fetchall():
                    details = json.loads(row["details_json"])
                    relative = details["receipt"]["descriptor"]["path"]
                    details["receipt"]["descriptor"]["sha256"] = digest(payload[prefix + relative])
                    connection.execute("UPDATE audit_events SET details_json=? WHERE id=?", (canonical(details).decode(), row["id"]))
                def update_report(document):
                    rebind(document)
                    for relative in ("run.json", "normalization.json"):
                        raw = payload[prefix + relative]
                        binding = document["inputs"][relative]
                        self.assertEqual(set(binding), {"sha256", "bytes"})
                        binding.update(sha256=digest(raw), bytes=len(raw))
                        self.assertEqual(binding, {"sha256": digest(raw), "bytes": len(raw)})
                    document["run_sha256"] = forged_run_sha
                    self.assertEqual(document["inputs"]["run.json"]["sha256"], forged_run_sha)
                    for receipt in document["manual_assessment_context"]["assessments"]:
                        receipt["descriptor"]["sha256"] = digest(payload[prefix + receipt["descriptor"]["path"]])
                helper.forge_report(payload, connection, generation, update_report)
                for name, raw in published_outputs.items():
                    self.assertEqual(payload[name], raw)
                for camera, raw in old_media.items():
                    self.assertEqual(payload[prefix + normal["outputs"][camera + "_trial"]["path"]], raw)
            forged = helper.portable.rewrite(case, archive, mutate)
            result = self.verify_archive(forged, False)
            lineage = [item for item in result["failures"] if item["check"] == "report.lineage"]
            self.assertTrue(lineage, result)
            self.assertTrue(any("manual independent normalized decode unavailable or invalid" in item["message"].lower()
                                for item in lineage), lineage)

    def test_portable_refuses_unavailable_decoder_after_real_positive(self):
        helper = self.portable_fixture()
        with helper.fixture() as (_, archive, _, __):
            self.verify_archive(archive, True)
            # Explicit bounded negative injection at the portable decoder I/O.
            # create=True keeps this a BUSINESS RED on v3: old code ignores it.
            with mock.patch.object(verify_evidence, "_offline_probe_output", create=True,
                                   side_effect=FileNotFoundError("TEST_ONLY decoder absent")):
                result = self.verify_archive(archive, False)
            lineage = [item for item in result["failures"] if item["check"] == "report.lineage"]
            self.assertTrue(lineage, result)
            self.assertTrue(any("manual independent normalized decode unavailable or invalid" in item["message"].lower()
                                for item in lineage), lineage)


if __name__ == "__main__":
    unittest.main()
