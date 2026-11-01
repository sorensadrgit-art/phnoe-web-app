"""Generated-only checks for historical integrity and exact report input deltas."""
import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import report_generation
import test_report_current_context as fixtures


class ReportCurrentContextBoundaryTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        case = fixtures.ReportCurrentContextTests(
            "test_00_R1_registered_initial_publication_is_v2_with_exact_receipt_and_three_files")
        try:
            case.setUp()
            yield case
        finally:
            case.doCleanups()

    def assert_current_refuses_without_healing(self, case):
        before, audit = case.tree(case.folder), case.index.verify_audit()
        with self.assertRaises(ValueError):
            report_generation.current_report_context(case.index, fixtures.SID)
        self.assertEqual(case.tree(case.folder), before)
        self.assertEqual(case.index.verify_audit(), audit)

    def test_R6_unaudited_new_input_cannot_become_a_current_report_context(self):
        with self.fixture() as case:
            first, _ = case.generate_v2()
            old = case.tree(first["json"].parent)
            (case.folder / "exports" / "TEST_ONLY-unaudited-input.txt").write_bytes(
                b"TEST_ONLY unrelated new input")
            self.assert_current_refuses_without_healing(case)
            self.assertEqual(case.tree(first["json"].parent), old)
            # Historical integrity is independent of whether those inputs are current.
            self.assertEqual(len(report_generation.committed_reports(
                case.index, fixtures.SID, check_inputs=False)), 3)

    def test_R6_valid_metadata_delta_does_not_authorize_an_unrelated_export(self):
        with self.fixture() as case:
            first, _ = case.generate_v2()
            case.correct_metadata()
            current = case.context()
            (case.folder / "exports" / "TEST_ONLY-not-audited.json").write_text(
                '{"test_only":true}', encoding="utf-8")
            before, audit = case.tree(case.folder), case.index.verify_audit()
            self.assert_current_refuses_without_healing(case)
            with self.assertRaises(ValueError):
                case.builder.generate_reports(fixtures.SID,
                    expected_report_head=case.head(first),
                    expected_report_context_sha256=current["report_context_sha256"])
            self.assertEqual(case.tree(case.folder), before)
            self.assertEqual(case.index.verify_audit(), audit)

    def test_R5_each_older_manifest_json_and_csv_remains_binding(self):
        for kind in ("manifest", "json", "csv"):
            with self.subTest(kind=kind), self.fixture() as case:
                first, _ = case.generate_v2()
                case.correct_metadata()
                current = case.context()
                case.generate_v2(expected_report_head=case.head(first),
                    expected_report_context_sha256=current["report_context_sha256"])
                target = first["json"].parent / "manifest.json" if kind == "manifest" else first[kind]
                if kind == "manifest":
                    document = json.loads(target.read_bytes())
                    document["session_id"] = "TEST_ONLY-another-session"
                    target.write_bytes(fixtures.canonical(document))
                else:
                    target.write_bytes(target.read_bytes() + b"\nTEST_ONLY deliberate corruption")
                before, audit = case.tree(case.folder), case.index.verify_audit()
                with self.assertRaises(ValueError):
                    report_generation.committed_reports(case.index, fixtures.SID, check_inputs=False)
                self.assert_current_refuses_without_healing(case)
                self.assertEqual(case.tree(case.folder), before)
                self.assertEqual(case.index.verify_audit(), audit)

    def test_R4_source_mutation_during_superseding_render_has_no_new_authority(self):
        with self.fixture() as case:
            first, _ = case.generate_v2()
            old = case.tree(first["json"].parent)
            case.correct_metadata()
            current = case.context()
            publications = case.index.conn.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type='REPORT_PUBLISHED'").fetchone()[0]

            def change_during_render(path, _document):
                path.write_bytes(b"%PDF-TEST_ONLY injected render boundary")
                (case.folder / "Config.toml").write_text(
                    "# TEST_ONLY deliberately changed during rendering\n", encoding="utf-8")

            with (patch.object(case.builder, "_build_pdf", side_effect=change_during_render),
                  self.assertRaises(ValueError)):
                case.builder.generate_reports(fixtures.SID,
                    expected_report_head=case.head(first),
                    expected_report_context_sha256=current["report_context_sha256"])
            self.assertEqual(case.index.conn.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type='REPORT_PUBLISHED'"
            ).fetchone()[0], publications)
            self.assertEqual(case.tree(first["json"].parent), old)
            self.assertEqual(len(list(first["json"].parent.parent.glob("*/manifest.json"))), 1)


if __name__ == "__main__":
    unittest.main()
