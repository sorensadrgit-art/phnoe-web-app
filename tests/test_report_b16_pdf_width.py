"""Actual PDF glyph-box regression; requires the already-installed decoder runtime."""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from matplotlib.backends.backend_pdf import PdfPages

import test_report_b16_drawn_geometry as drawn


class B16PdfWidthTests(unittest.TestCase):
    def test_public_pdf_all_glyphs_rows_long_scalar_and_missing_dimensions(self):
        decoder = Path(os.environ["KINELAB_PDF_DECODER_PYTHON"])
        self.assertTrue(decoder.is_absolute() and decoder.is_file())
        original_close = PdfPages.close
        observations = []
        seen = set()
        code = r"""
import json, sys
import pdfplumber
pages = []
with pdfplumber.open(sys.argv[1]) as pdf:
    for number, page in enumerate(pdf.pages, 1):
        failures = []
        for char in page.chars:
            if not (0 <= char["x0"] <= char["x1"] <= page.width
                    and 0 <= char["top"] <= char["bottom"] <= page.height):
                failures.append({key: char[key] for key in
                                 ("text", "x0", "x1", "top", "bottom")})
        horizontal_lines = []
        stroke_glyph_intersections = []
        for line in page.lines:
            if line["top"] != line["bottom"]:
                continue
            horizontal_lines.append(line)
            half_width = line["linewidth"] / 2
            stroke_top = line["top"] - half_width
            stroke_bottom = line["bottom"] + half_width
            for char in page.chars:
                if not char["text"].strip():
                    continue
                if (max(line["x0"], char["x0"]) < min(line["x1"], char["x1"])
                        and max(stroke_top, char["top"])
                        < min(stroke_bottom, char["bottom"])):
                    stroke_glyph_intersections.append({
                        "line": {key: line[key] for key in
                                 ("x0", "x1", "top", "bottom", "linewidth")},
                        "glyph": {key: char[key] for key in
                                  ("text", "x0", "x1", "top", "bottom")},
                    })
        text = page.extract_text() or ""
        words = page.extract_words()
        baselines = {}
        for word in words:
            baseline = baselines.setdefault(round(word["top"], 2), {})
            for anchor in (0.06, 0.13, 0.15, 0.25):
                if abs(word["x0"] - anchor * page.width) < 0.5:
                    baseline[anchor] = word["text"]
        gait = [int(cells[0.06]) for cells in baselines.values()
                if cells.get(0.06, "").isdigit()
                and cells.get(0.13) in {"left", "right"}]
        squat = [[int(cells[x]) for x in (0.06, 0.15, 0.25)]
                 for cells in baselines.values()
                 if all(cells.get(x, "").isdigit() for x in (0.06, 0.15, 0.25))]
        pages.append({"page": number, "failures": failures, "text": text,
                      "horizontal_lines": len(horizontal_lines),
                      "stroke_glyph_intersections": stroke_glyph_intersections,
                      "gait_frames": gait, "squat_frames": squat,
                      "operator_z": sum(len(word["text"]) for word in page.extract_words()
                                        if word["text"] and set(word["text"]) == {"Z"})})
print(json.dumps(pages, allow_nan=False))
"""

        def decode_after_close(pdf):
            filename = Path(pdf._filename)
            original_close(pdf)
            if filename in seen or not filename.is_file():
                return
            seen.add(filename)
            run = subprocess.run(
                [str(decoder), "-I", "-X", "utf8", "-c", code, str(filename)],
                capture_output=True, encoding="utf-8", timeout=60, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            observations.extend(json.loads(run.stdout))

        with mock.patch.object(PdfPages, "close", new=decode_after_close):
            # Executes the existing real public publisher fixture and its unchanged
            # complete 40 gait / 4 squat / 6000-Z / JSON / CSV / drawn assertions.
            case = drawn.B16DrawnGeometryTests(
                "test_public_report_drawn_extents_rows_and_long_scalar_stay_on_page")
            case.debug()
        self.assertTrue(observations, "No actual published PDF was decoded")
        text = "\n".join(page["text"] for page in observations)
        self.assertEqual(sum(page["operator_z"] for page in observations), 6000)
        self.assertEqual([frame for page in observations for frame in page["gait_frames"]],
                         list(range(40)))
        self.assertEqual([frames for page in observations for frames in page["squat_frames"]],
                         [[5 + i * 20, 11 + i * 20, 17 + i * 20] for i in range(4)])
        self.assertNotIn("NonexNone", text)
        self.assertIn("UNAVAIL.", text)
        for page in observations:
            with self.subTest(page=page["page"]):
                self.assertEqual(page["failures"], [])
                self.assertIn(f"Page {page['page']} of {len(observations)}", page["text"])
                self.assertIn("KineLab PT - Confidential Research Output - Not for Diagnostic Use",
                              page["text"])
        self.assertEqual(
            [(page["page"], page["stroke_glyph_intersections"])
             for page in observations
             if not page["horizontal_lines"] or page["stroke_glyph_intersections"]],
            [],
            "Actual PDF horizontal strokes must exist and avoid decoded glyph boxes",
        )
