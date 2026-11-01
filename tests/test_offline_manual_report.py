"""Generated manual v2 fixtures; isolated stdlib verifier is the independent oracle.

Labels below are analytic TEST_ONLY inputs, never observations by a human.
Positive controls currently require RED at REPORT_MANUAL_UNSUPPORTED. Every
attack first requires its valid archive to pass, so attacks are NOT_REACHED
while independent manual semantics remain unsupported. No TestCase aliases.
"""
import copy
import hashlib
import json
import unittest
from contextlib import contextmanager

import test_offline_report_v2 as portable
import test_report_current_context as reports
from gait_events import orient_event_candidates, propose_extrema
from manual_assessment_entry import manual_assessment_context, publish_manual_assessment_entry
from squat_events import analyze_squats
from test_manual_assessment_provenance import generated_trajectory
from test_squat_events import fixture_reps


class OfflineManualReportTests(unittest.TestCase):
    def setUp(self):
        self.portable = portable.OfflineReportV2Tests(
            "test_00_initial_actual_v2_passes_isolated_verifier")

    @contextmanager
    def fixture(self, kind="gait", *, entries=1, stale=False, revise_between=False):
        with self.portable.fixture() as case:
            source = case.session["captures"]["cam01_trial"]["sha256"]
            trajectory = generated_trajectory(source) if kind == "gait" else fixture_reps(1)
            trajectory["source_sha256"] = source
            if kind == "gait":
                candidates = orient_event_candidates(propose_extrema(
                    trajectory, "cam01_trial", source, image_width=1024, image_height=576),
                    screen_forward="right")
                labels = [{"frame_index": 50, "side": "left", "event_type": "initial_contact"}]
            else:
                candidates = analyze_squats(trajectory, "cam01_trial", source,
                    camera_view="side", activity_confirmed=True, image_width=1024, image_height=576)
                labels = [{"start_frame": 50, "bottom_frame": 73, "end_frame": 97}]
            folder = case.folder / "assessment-inputs" / ("TEST_ONLY-" + kind)
            folder.mkdir(parents=True)
            case.write(folder / "trajectory.json", trajectory)
            case.write(folder / "candidates.json", candidates)
            receipts = []
            for digit in "56"[:entries]:
                if digit == "6" and revise_between:
                    case.correct_metadata()
                context = manual_assessment_context(case.index, reports.SID)
                item = next(item for item in context["input_sets"] if item["kind"] == kind)
                receipts.append(publish_manual_assessment_entry(case.index, reports.SID, {
                    "operation_id": digit * 32,
                    "context_sha256": context["context_sha256"],
                    "metadata_context_sha256": context["metadata_context_sha256"],
                    "input_id": item["input_id"], "source_sha256": item["source_sha256"],
                    "reviewer": "TEST_ONLY analytic labels; no human reviewer",
                    "annotation_origin": "human_observed_video_frames",
                    "labels": copy.deepcopy(labels), "tolerance_frames": 3, "confirm": True,
                }))
            if stale:
                case.correct_metadata()
            archive, files = self.portable.archive(case)
            try:
                yield case, archive, files, receipts
            finally:
                case.assert_originals()

    @staticmethod
    def reseal_context(document):
        manual = document["manual_assessment_context"]
        manual.pop("sha256", None)
        manual["sha256"] = reports.digest(manual)
        document["report_context_sha256"] = reports.digest({
            key: document[key] for key in ("schema", "session_id", "input_policy", "inputs",
                "origin_sha256", "run_sha256", "metadata_context_sha256", "manual_assessment_context")
        } | {"schema": "kinelab.report-context.v1"})

    def forge_report(self, payload, connection, generation, change):
        def alter(document):
            change(document)
            self.reseal_context(document)
        self.portable.forge_manifest(payload, connection, generation, alter)

    @staticmethod
    def replace_binding(value, relative, raw):
        """Update exact path bindings; semantic mutations must defeat hash-only checks."""
        checksum = hashlib.sha256(raw).hexdigest()
        if isinstance(value, dict):
            if value.get("path") == relative and "sha256" in value:
                value["sha256"] = checksum
                if "bytes" in value:
                    value["bytes"] = len(raw)
            if relative in value:
                if isinstance(value[relative], str):
                    value[relative] = checksum
                elif isinstance(value[relative], dict) and "sha256" in value[relative]:
                    value[relative]["sha256"] = checksum
                    if "bytes" in value[relative]:
                        value[relative]["bytes"] = len(raw)
            for child in value.values():
                OfflineManualReportTests.replace_binding(child, relative, raw)
        elif isinstance(value, list):
            for child in value:
                OfflineManualReportTests.replace_binding(child, relative, raw)

    def forge_entry(self, payload, connection, generation, operation, attack):
        prefix = f"sessions/{reports.SID}/"
        relative = f"exports/manual-entry-{operation}.manual-assessment.json"
        descriptor = json.loads(payload[prefix + relative])
        row = connection.execute("SELECT id,details_json FROM audit_events WHERE "
            "event_type='MANUAL_ASSESSMENT_ENTRY_PUBLISHED' AND session_id=? ORDER BY id",
            (reports.SID,)).fetchall()
        event = next(item for item in row
            if json.loads(item["details_json"])["request"]["operation_id"] == operation)
        details = json.loads(event["details_json"])
        if attack == "score":
            descriptor["score"]["matched_count"] += 1
        elif attack == "source":
            descriptor["source"]["sha256"] = "f" * 64
        elif attack == "clinical":
            descriptor["clinical_accuracy_validated"] = True
        elif attack == "test_only":
            descriptor["test_only"] = False
        elif attack == "request":
            details["request"]["tolerance_frames"] = True
        else:
            name = {"reference": "reference", "candidate": "candidates", "snapshot": "session"}[attack]
            binding = descriptor["inputs"][name]
            document = json.loads(payload[prefix + binding["snapshot"]["path"]])
            if attack == "reference":
                document["labels"][0]["frame_index"] += 7
                document["labels"][0]["time_seconds"] = round(document["labels"][0]["frame_index"] / 30, 6)
            elif attack == "candidate":
                document["candidates"][0]["frame_index"] += 1
                document["candidates"][0]["time_seconds"] = round(document["candidates"][0]["frame_index"] / 30, 6)
            else:
                document["session_id"] = "TEST_ONLY-forged-origin"
            raw = reports.canonical(document)
            for path in (binding["path"], binding["snapshot"]["path"]):
                payload[prefix + path] = raw
                self.replace_binding(descriptor, path, raw)
        raw = reports.canonical(descriptor)
        copied = f"exports/manual-entry-{operation}.manual-assessment-inputs/descriptor.json"
        payload[prefix + relative] = raw
        payload[prefix + copied] = raw
        details["receipt"]["descriptor"]["sha256"] = hashlib.sha256(raw).hexdigest()
        connection.execute("UPDATE audit_events SET details_json=? WHERE id=?",
            (reports.canonical(details).decode(), event["id"]))
        for member, body in payload.items():
            if not member.startswith(prefix):
                continue
            path = member[len(prefix):]
            connection.execute("UPDATE artifacts SET sha256=?,bytes=? WHERE session_id=? AND artifact_key=?",
                (hashlib.sha256(body).hexdigest(), len(body), reports.SID, path))
        def rebind(document):
            for member, body in payload.items():
                if member.startswith(prefix):
                    self.replace_binding(document["inputs"], member[len(prefix):], body)
            for receipt in document["manual_assessment_context"]["assessments"]:
                if receipt["operation_id"] == operation:
                    receipt["descriptor"]["sha256"] = details["receipt"]["descriptor"]["sha256"]
        self.forge_report(payload, connection, generation, rebind)

    def test_00_actual_gait_manual_v2_requires_semantic_acceptance(self):
        with self.fixture() as (_, archive, _, __):
            self.portable.verify(archive, valid=True)

    def test_01_actual_squat_manual_v2_requires_semantic_acceptance(self):
        with self.fixture("squat") as (_, archive, _, __):
            self.portable.verify(archive, valid=True)

    def test_02_metadata_correction_partitions_prior_manual_as_unavailable(self):
        with self.fixture(stale=True) as (case, archive, files, receipts):
            document = case.head(files)
            manifest = json.loads((files["json"].parent / "manifest.json").read_bytes())
            self.assertEqual(manifest["manual_assessment_context"]["assessments"], [])
            self.assertEqual(manifest["manual_assessment_context"]["unavailable_assessments"], [
                {"operation_id": receipts[0]["operation_id"], "reason": "METADATA_CONTEXT_CHANGED"}])
            self.assertIsNotNone(document)
            self.portable.verify(archive, valid=True)

    def test_03_manual_historical_generation_survives_metadata_supersession(self):
        with self.fixture() as (case, _, files, __):
            case.correct_metadata()
            context = case.context()
            case.generate_v2(expected_report_head=case.head(files),
                expected_report_context_sha256=context["report_context_sha256"])
            from backup_manager import BackupManager
            archive = case.base / "TEST_ONLY-manual-superseded.zip"
            BackupManager(case.projects, case.index).create_backup(archive)
            self.portable.verify(archive, valid=True)

    def test_04_omitted_or_reordered_manual_receipts_refuse(self):
        for attack in ("omitted", "reordered"):
            with self.subTest(attack=attack), self.fixture(entries=2) as (case, archive, files, _):
                self.portable.verify(archive, valid=True)
                def mutate(payload, connection, attack=attack):
                    def change(document):
                        items = document["manual_assessment_context"]["assessments"]
                        items.pop() if attack == "omitted" else items.reverse()
                    self.forge_report(payload, connection, files["json"].parent.name, change)
                self.portable.verify(self.portable.rewrite(case, archive, mutate), valid=False)

    def test_08_entry_metadata_must_be_latest_before_its_own_audit_id(self):
        for attack in ("past_context", "future_context"):
            with self.subTest(attack=attack), self.fixture(entries=2, revise_between=True) as (case, archive, files, receipts):
                self.portable.verify(archive, valid=True)
                def mutate(payload, connection, attack=attack):
                    chosen, other = (1, 0) if attack == "past_context" else (0, 1)
                    operation = receipts[chosen]["operation_id"]
                    context = receipts[other]["metadata_context_sha256"]
                    for row in connection.execute("SELECT id,details_json FROM audit_events WHERE "
                            "event_type='MANUAL_ASSESSMENT_ENTRY_PUBLISHED' ORDER BY id").fetchall():
                        details = json.loads(row["details_json"])
                        if details["request"]["operation_id"] == operation:
                            details["request"]["metadata_context_sha256"] = context
                            details["receipt"]["metadata_context_sha256"] = context
                            connection.execute("UPDATE audit_events SET details_json=? WHERE id=?",
                                (reports.canonical(details).decode(), row["id"]))
                    changed = copy.deepcopy(receipts)
                    changed[chosen]["metadata_context_sha256"] = context
                    def partition(document):
                        active = document["metadata_context_sha256"]
                        manual = document["manual_assessment_context"]
                        manual["assessments"] = sorted((item for item in changed
                            if item["metadata_context_sha256"] == active), key=lambda item: item["operation_id"])
                        manual["unavailable_assessments"] = sorted(({
                            "operation_id": item["operation_id"], "reason": "METADATA_CONTEXT_CHANGED"}
                            for item in changed if item["metadata_context_sha256"] != active),
                            key=lambda item: item["operation_id"])
                    self.forge_report(payload, connection, files["json"].parent.name, partition)
                self.portable.verify(self.portable.rewrite(case, archive, mutate), valid=False)

    def test_05_stale_manual_cannot_be_promoted_to_current(self):
        with self.fixture(stale=True) as (case, archive, files, receipts):
            self.portable.verify(archive, valid=True)
            def mutate(payload, connection):
                def change(document):
                    document["manual_assessment_context"]["assessments"] = receipts
                    document["manual_assessment_context"]["unavailable_assessments"] = []
                self.forge_report(payload, connection, files["json"].parent.name, change)
            self.portable.verify(self.portable.rewrite(case, archive, mutate), valid=False)

    def test_06_unaudited_manual_authority_sibling_refuses(self):
        with self.fixture() as (case, archive, _, __):
            self.portable.verify(archive, valid=True)
            def mutate(payload, connection):
                payload[f"sessions/{reports.SID}/assessment-entries/entry-{'7' * 32}/reference.json"] = b"{}"
            self.portable.verify(self.portable.rewrite(case, archive, mutate), valid=False)

    def test_07_rehashed_manual_semantic_and_provenance_forgeries_refuse(self):
        for attack in ("score", "reference", "candidate", "source", "snapshot", "request", "clinical", "test_only"):
            with self.subTest(attack=attack), self.fixture() as (case, archive, files, receipts):
                self.portable.verify(archive, valid=True)
                def mutate(payload, connection, attack=attack):
                    self.forge_entry(payload, connection, files["json"].parent.name,
                        receipts[0]["operation_id"], attack)
                self.portable.verify(self.portable.rewrite(case, archive, mutate), valid=False)
