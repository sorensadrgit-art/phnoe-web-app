"""Drawn-geometry regression; decoded PDF and raster acceptance remain separate."""
from __future__ import annotations

import csv
import io
import json
import math
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from matplotlib.backends.backend_pdf import PdfPages

from report_builder import ReportBuilder
from session_contract import sha256_file
from session_index import SessionIndex
from session_library import SessionLibrary
from test_report_b16_pdf import _gait_doc_with, _squat_doc_with


class B16DrawnGeometryTests(unittest.TestCase):
    def test_public_report_drawn_extents_rows_and_long_scalar_stay_on_page(self):
        """Inspect actual Agg-drawn transforms, never planned input coordinates."""
        pages = []
        original_savefig = PdfPages.savefig

        def inspect_and_save(pdf, figure, *args, **kwargs):
            figure.canvas.draw()
            renderer = figure.canvas.get_renderer()
            inverse = figure.transFigure.inverted()
            artists = []
            for axis in figure.axes:
                for artist in axis.texts:
                    bounds = inverse.transform_bbox(artist.get_window_extent(renderer))
                    origin = inverse.transform(
                        artist.get_transform().transform(artist.get_position()))
                    artists.append({
                        "kind": "text", "text": artist.get_text(),
                        "bounds": tuple(float(v) for v in bounds.extents),
                        "origin": tuple(float(v) for v in origin),
                    })
                for artist in [*axis.lines, *axis.patches]:
                    bounds = inverse.transform_bbox(artist.get_window_extent(renderer))
                    artists.append({
                        "kind": "geometry", "text": "",
                        "bounds": tuple(float(v) for v in bounds.extents),
                    })
            pages.append(artists)
            return original_savefig(pdf, figure, *args, **kwargs)

        with tempfile.TemporaryDirectory(prefix="kinelab-b16-drawn-") as temporary:
            root = Path(temporary)
            projects = root / "projects"
            projects.mkdir()
            index = SessionIndex(root / "index.db", projects)
            try:
                library = SessionLibrary(projects)
                folder = library.create_session("b16-drawn", kind="demo")
                source = folder / "raw" / "cam01_trial.mp4"
                source.parent.mkdir(exist_ok=True)
                source.write_bytes(b"generated identity fixture; not camera video")
                for name, payload in (
                    ("gait-candidates.json", _gait_doc_with(40)),
                    ("squat-candidates.json", _squat_doc_with(4)),
                ):
                    payload["source_sha256"] = sha256_file(source)
                    (folder / name).write_text(json.dumps(payload), encoding="utf-8")
                operator = "Z" * 6000
                board = {
                    "expected_square_mm": 25.4, "measured_square_mm": 25.3,
                    "measured_by": operator, "recorded_at_utc": "2026-10-28T00:00:00Z",
                    "source": "TEST_ONLY generated layout fixture; not physical evidence",
                }
                (folder / "board-measurement.json").write_text(
                    json.dumps(board), encoding="utf-8")
                index.reindex()
                self.assertEqual(
                    index.get_passport("b16-drawn")["board_measurement"]["measured_by"], operator)
                with mock.patch.object(PdfPages, "savefig", new=inspect_and_save):
                    artifacts = ReportBuilder(projects, index).generate_reports("b16-drawn")
                document = json.loads(artifacts["json"].read_text(encoding="utf-8"))
                self.assertIs(document["is_test_only"], True)
                self.assertEqual(document["passport"]["board_measurement"]["measured_by"],
                                 operator)
                self.assertEqual(
                    document["event_analysis"]["gait_candidates"][0]["candidate_count"], 40)
                self.assertEqual(
                    document["event_analysis"]["squat_candidates"][0][
                        "candidate_repetition_count"], 4)
                csv_text = artifacts["csv"].read_text(encoding="utf-8")
                self.assertIn(operator, csv_text)
                rows = list(csv.reader(io.StringIO(csv_text)))
                self.assertEqual(
                    [row for row in rows if len(row) == 3 and row[1] == "frame_index"
                     and row[0].startswith("gait_candidates[0].candidates[")],
                    [[f"gait_candidates[0].candidates[{i}]", "frame_index", str(i)]
                     for i in range(40)])
                for i in range(4):
                    self.assertIn([f"squat_candidates[0].repetitions[{i}]",
                                   "end_frame", str(17 + i * 20)], rows)
                pdf_bytes = artifacts["pdf"].read_bytes()
                self.assertTrue(pdf_bytes.startswith(b"%PDF"))
                self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", pdf_bytes)), len(pages))
            finally:
                index.close()

        self.assertGreater(len(pages), 2)
        gait_frames = []
        squat_frames = []
        drawn_operator = []
        for page_number, artists in enumerate(pages, start=1):
            texts = [item for item in artists if item["kind"] == "text"]
            with self.subTest(page=page_number, check="actual_drawn_bounds"):
                violations = [
                    (item["kind"], item["text"][:60], item["bounds"])
                    for item in artists
                    if not (all(math.isfinite(v) for v in item["bounds"])
                            and 0 <= item["bounds"][0] <= item["bounds"][2] <= 1
                            and 0 <= item["bounds"][1] <= item["bounds"][3] <= 1)
                ]
                self.assertFalse(
                    violations, f"{len(violations)} off-page drawn artists: {violations[:5]}")
            with self.subTest(page=page_number, check="drawn_footer"):
                footer = [item for item in texts
                          if item["text"] == f"Page {page_number} of {len(pages)}"]
                self.assertEqual(len(footer), 1)
                self.assertTrue(all(0 <= item["bounds"][1] <= item["bounds"][3] < 0.105
                                    for item in footer))
                warning = [item for item in texts if item["text"] ==
                           "KineLab PT - Confidential Research Output - Not for Diagnostic Use"]
                self.assertEqual(len(warning), 1)
                self.assertTrue(all(0 <= item["bounds"][1] <= item["bounds"][3] < 0.105
                                    for item in warning))
            baselines = {}
            for item in texts:
                x, y = item["origin"]
                baselines.setdefault(round(y, 6), {})[round(x, 6)] = item["text"]
                if item["text"] and set(item["text"]) == {"Z"}:
                    drawn_operator.append(item["text"])
            for cells in baselines.values():
                if cells.get(0.06, "").isdigit() and cells.get(0.13) in {"left", "right"}:
                    gait_frames.append(int(cells[0.06]))
                if all(cells.get(x, "").isdigit() for x in (0.06, 0.15, 0.25)):
                    squat_frames.append(tuple(int(cells[x]) for x in (0.06, 0.15, 0.25)))
        self.assertEqual(gait_frames, list(range(40)))
        self.assertEqual(squat_frames, [(5 + i * 20, 11 + i * 20, 17 + i * 20)
                                       for i in range(4)])
        self.assertEqual("".join(drawn_operator), "Z" * 6000)
