"""Truthful offline research report generator for KineLab PT.

Generates multi-page vector PDF, machine-readable JSON, and tabular CSV summaries.
Zero fabricated clinical diagnoses, zero interpolated angles for missing frames.
Prominently watermarks test-only or synthetic fixtures.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

from session_contract import sha256_file
from session_index import SessionIndex


class ReportBuilder:
    def __init__(self, projects_root: Path | str, index: SessionIndex | None = None):
        self.projects_root = Path(projects_root).resolve()
        self.index = index or SessionIndex(self.projects_root / ".kinelab_index.db", self.projects_root)

    def generate_reports(self, session_id: str, output_dir: Path | str | None = None) -> dict[str, Path]:
        folder = self.projects_root / session_id
        if not folder.is_dir():
            raise FileNotFoundError(f"Session {session_id} not found in {self.projects_root}")

        passport = self.index.get_passport(session_id)
        is_test_only = passport.get("is_test_only", False)
        watermark = passport.get("watermark")
        now_utc = datetime.now(timezone.utc).isoformat()

        out_dir = Path(output_dir) if output_dir else (folder / "exports")
        out_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = out_dir / f"{session_id}-research-report.pdf"
        json_path = out_dir / f"{session_id}-research-summary.json"
        csv_path = out_dir / f"{session_id}-metrics.csv"

        # 1. JSON Report
        json_doc = {
            "schema": "kinelab.research-report.v1",
            "session_id": session_id,
            "generated_at_utc": now_utc,
            "is_test_only": is_test_only,
            "watermark": watermark,
            "state": passport.get("state"),
            "clinical_accuracy_verified": False,
            "physical_accuracy_verified": False,
            "provenance": {
                "software": "KineLab PT v1.0",
                "pose2sim_version": "0.10.49",
                "opensim_version": "4.6",
                "onnxruntime_version": "1.31.0",
                "host": os.environ.get("COMPUTERNAME", "AgentZero")
            },
            "passport": passport,
            "sources": passport.get("sources", {}),
            "board_measurement": passport.get("board_measurement"),
            "runs": passport.get("runs", {}),
            "limitations": "Internal research software only. Physical camera geometry and clinical accuracy unverified without physical measurement evidence and independent reference validation."
        }
        json_path.write_text(json.dumps(json_doc, indent=2), encoding="utf-8")

        # 2. CSV Report
        board_mm = ""
        operator = ""
        if passport.get("board_measurement"):
            board_mm = str(passport["board_measurement"].get("measured_square_mm", ""))
            operator = str(passport["board_measurement"].get("measured_by", ""))

        runs = passport.get("runs", {})
        cal_passed = bool(runs.get("calibration", {}).get("passed", False))
        sync_passed = bool(runs.get("synchronization", {}).get("passed", False))
        recon_passed = bool(runs.get("triangulation", {}).get("passed", False))

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "session_id", "kind", "state", "captured_count", "board_measured_mm",
                "operator", "calibration_passed", "sync_passed", "reconstruction_passed",
                "clinical_accuracy_verified", "is_test_only", "generated_at_utc"
            ])
            writer.writerow([
                session_id, passport.get("kind"), passport.get("state"),
                passport.get("captured_count"), board_mm, operator,
                cal_passed, sync_passed, recon_passed,
                False, is_test_only, now_utc
            ])
            # Additional detail rows for captured sources
            writer.writerow([])
            writer.writerow(["role", "filename", "bytes", "sha256", "duration_s", "width", "height", "fps"])
            for role, s in passport.get("sources", {}).items():
                writer.writerow([
                    role, s.get("filename", ""), s.get("bytes", ""), s.get("sha256", ""),
                    s.get("duration", ""), s.get("width", ""), s.get("height", ""), s.get("fps", "")
                ])

        # 3. PDF Report (Vector Matplotlib PdfPages)
        self._build_pdf(pdf_path, json_doc)

        return {"pdf": pdf_path, "json": json_path, "csv": csv_path}

    def _build_pdf(self, pdf_path: Path, doc: dict):
        session_id = doc["session_id"]
        is_test_only = doc["is_test_only"]
        passport = doc["passport"]
        runs = passport.get("runs", {})
        cal_passed = bool(runs.get("calibration", {}).get("passed", False))
        sync_passed = bool(runs.get("synchronization", {}).get("passed", False))
        recon_passed = bool(runs.get("triangulation", {}).get("passed", False))

        primary_teal = "#0f4c47"
        bg_dark = "#092320"
        text_dark = "#1c2b29"
        accent_warn = "#b45309"
        font_family = "sans-serif"

        with PdfPages(pdf_path) as pdf:
            # ---------------- PAGE 1: Cover & Provenance ----------------
            fig = plt.figure(figsize=(8.5, 11), dpi=150)
            fig.patch.set_facecolor("#f8faf9")
            ax = fig.add_axes([0, 0, 1, 1])
            ax.axis("off")

            # Header Banner
            rect = plt.Rectangle((0, 0.88), 1, 0.12, facecolor=primary_teal, edgecolor="none")
            ax.add_patch(rect)
            ax.text(0.06, 0.94, "KINELAB PT — BIOMECHANICS RESEARCH REPORT", color="white",
                    fontsize=16, weight="bold", fontfamily=font_family)
            ax.text(0.06, 0.90, "Local-First Desktop Movement Analysis · Research Software Prototype", color="#99f6e4",
                    fontsize=10, fontfamily=font_family)

            if is_test_only:
                warn_rect = plt.Rectangle((0.06, 0.82), 0.88, 0.045, facecolor="#fef3c7", edgecolor=accent_warn, linewidth=1.5)
                ax.add_patch(warn_rect)
                ax.text(0.5, 0.838, "TEST ONLY — NOT PHYSICAL DUAL-CAMERA VALIDATION",
                        color=accent_warn, fontsize=11, weight="bold", ha="center", fontfamily=font_family)
            else:
                info_rect = plt.Rectangle((0.06, 0.82), 0.88, 0.045, facecolor="#e6fffa", edgecolor=primary_teal, linewidth=1)
                ax.add_patch(info_rect)
                ax.text(0.5, 0.838, f"SESSION PASSPORT STATE: {passport.get('state', 'UNKNOWN')}",
                        color=primary_teal, fontsize=11, weight="bold", ha="center", fontfamily=font_family)

            # Metadata Block
            ax.text(0.06, 0.77, "SESSION PROVENANCE & IDENTIFICATION", color=primary_teal, fontsize=11, weight="bold")
            meta_lines = [
                ("Session Identifier:", session_id),
                ("Capture Type / Kind:", passport.get("kind", "unknown")),
                ("Report Generation UTC:", doc["generated_at_utc"]),
                ("Host Workstation:", doc["provenance"]["host"]),
                ("Pipeline Versions:", f"KineLab PT v1.0 | Pose2Sim {doc['provenance']['pose2sim_version']} | OpenSim {doc['provenance']['opensim_version']}"),
                ("Evidence State:", passport.get("state", "UNKNOWN")),
                ("Clinical Accuracy:", "UNVERIFIED (Research Software Only)")
            ]
            y = 0.73
            for label, val in meta_lines:
                ax.text(0.08, y, label, color="#4b5563", fontsize=9.5, weight="bold")
                ax.text(0.35, y, val, color=text_dark, fontsize=9.5)
                y -= 0.026

            # Source Files Table
            ax.text(0.06, y - 0.02, "CAPTURED CAMERA SOURCES (6-ROLE PROTOCOL)", color=primary_teal, fontsize=11, weight="bold")
            y -= 0.05
            headers = ["Role", "Filename", "Status", "Resolution", "FPS", "Duration"]
            col_x = [0.06, 0.28, 0.52, 0.65, 0.77, 0.86]
            for i, h in enumerate(headers):
                ax.text(col_x[i], y, h, color="#374151", fontsize=9, weight="bold")
            y -= 0.008
            ax.plot([0.06, 0.94], [y, y], color="#d1d5db", linewidth=0.8)
            y -= 0.022

            sources = passport.get("sources", {})
            for role in ("cam01_intrinsics", "cam02_intrinsics", "cam01_board", "cam02_board", "cam01_trial", "cam02_trial"):
                s = sources.get(role)
                if s:
                    fn = s.get("filename", "")
                    st = "Present"
                    res = f"{s.get('width', '-')}x{s.get('height', '-')}"
                    fps = f"{s.get('fps', '-'):.1f}" if isinstance(s.get('fps'), (int, float)) else "-"
                    dur = f"{s.get('duration', '-'):.1f}s" if isinstance(s.get('duration'), (int, float)) else "-"
                else:
                    fn = f"{role}.mp4"
                    st = "MISSING"
                    res, fps, dur = "-", "-", "-"
                
                ax.text(col_x[0], y, role, color=text_dark, fontsize=8.5)
                ax.text(col_x[1], y, fn, color=text_dark, fontsize=8.5)
                ax.text(col_x[2], y, st, color=primary_teal if st == "Present" else "#dc2626", fontsize=8.5, weight="bold")
                ax.text(col_x[3], y, res, color=text_dark, fontsize=8.5)
                ax.text(col_x[4], y, fps, color=text_dark, fontsize=8.5)
                ax.text(col_x[5], y, dur, color=text_dark, fontsize=8.5)
                y -= 0.022

            # Footer notice
            ax.plot([0.06, 0.94], [0.10, 0.10], color="#d1d5db", linewidth=0.8)
            ax.text(0.5, 0.065, "KineLab PT — Confidential Research Output · Not for Diagnostic Use",
                    color="#6b7280", fontsize=8, ha="center")
            ax.text(0.5, 0.045, doc["limitations"],
                    color="#9ca3af", fontsize=7.5, ha="center")

            pdf.savefig(fig)
            plt.close(fig)

            # ---------------- PAGE 2: Calibration, Synchronization & Quality ----------------
            fig2 = plt.figure(figsize=(8.5, 11), dpi=150)
            fig2.patch.set_facecolor("#f8faf9")
            ax2 = fig2.add_axes([0, 0, 1, 1])
            ax2.axis("off")

            # Header
            rect2 = plt.Rectangle((0, 0.92), 1, 0.08, facecolor=primary_teal, edgecolor="none")
            ax2.add_patch(rect2)
            ax2.text(0.06, 0.95, "PHYSICAL CALIBRATION & SYNCHRONIZATION EVIDENCE", color="white",
                     fontsize=14, weight="bold", fontfamily=font_family)

            # Board Measurement section
            ax2.text(0.06, 0.87, "1. OPERATOR PHYSICAL BOARD MEASUREMENT", color=primary_teal, fontsize=11, weight="bold")
            bm = passport.get("board_measurement")
            if bm:
                b_lines = [
                    ("Board Configuration:", "7x9 inner corners (8x10 squares), 20.0 mm expected"),
                    ("Operator Measured Value:", f"{bm.get('measured_square_mm')} mm"),
                    ("Measurement Performed By:", str(bm.get("measured_by", "unspecified"))),
                    ("Recorded Timestamp:", str(bm.get("recorded_at_utc", "-"))),
                    ("Measurement Verification:", "Operator-reported physical ruler entry (not auto-inferred)")
                ]
            else:
                b_lines = [
                    ("Physical Board Measurement:", "ABSENT / PENDING OPERATOR ENTRY"),
                    ("Protocol Requirement:", "Must print checkerboard at 100%, measure square with ruler, record mm"),
                    ("Quality Gate Status:", "BLOCKED — Registration and Calibration require measured mm")
                ]
            y2 = 0.835
            for l, v in b_lines:
                ax2.text(0.08, y2, l, color="#4b5563", fontsize=9, weight="bold")
                ax2.text(0.38, y2, v, color=text_dark if "ABSENT" not in v else "#dc2626", fontsize=9)
                y2 -= 0.024

            # Camera Synchronization section
            y2 -= 0.02
            ax2.text(0.06, y2, "2. CAMERA GEOMETRY & SYNCHRONIZATION", color=primary_teal, fontsize=11, weight="bold")
            y2 -= 0.035
            sync_lines = [
                ("Camera 1 (cam01):", "Phone, primary perspective view"),
                ("Camera 2 (cam02):", "Integrated Webcam, secondary synchronized view"),
                ("Synchronization Method:", "Dual visual cues (clap / heel strike) with exact decoded frame times"),
                ("Pose2Sim Triangulation:", "Direct linear transform with cross-camera reprojection thresholding")
            ]
            for l, v in sync_lines:
                ax2.text(0.08, y2, l, color="#4b5563", fontsize=9, weight="bold")
                ax2.text(0.38, y2, v, color=text_dark, fontsize=9)
                y2 -= 0.024

            # Quality Checkpoints Table
            y2 -= 0.02
            ax2.text(0.06, y2, "3. STAGE ACCEPTANCE EVIDENCE CHAIN", color=primary_teal, fontsize=11, weight="bold")
            y2 -= 0.04
            ax2.plot([0.06, 0.94], [y2 + 0.015, y2 + 0.015], color="#d1d5db", linewidth=0.8)
            ax2.text(0.06, y2, "Pipeline Gate", color="#374151", fontsize=9, weight="bold")
            ax2.text(0.36, y2, "Acceptance Evidence", color="#374151", fontsize=9, weight="bold")
            ax2.text(0.78, y2, "Gate Verdict", color="#374151", fontsize=9, weight="bold")
            y2 -= 0.008
            ax2.plot([0.06, 0.94], [y2, y2], color="#d1d5db", linewidth=0.8)
            y2 -= 0.024

            chain = [
                ("Six Source Videos", "6 MP4s probed, matching geometry", "PASS" if passport.get("captured_count") == 6 else "PENDING"),
                ("Physical Measurement", "Ruler measurement recorded", "PASS" if bm else "PENDING"),
                ("Original Hash Registration", "session.json immutable registration", "PASS" if passport.get("badge") in ("REGISTERED", "TEST ONLY") else "PENDING"),
                ("Video Normalization", "preflight.json verified 30fps CFR", "PASS" if "NORMALIZATION_PASSED" in str(passport.get("history", [])) else "PENDING"),
                ("Camera Calibration", "Intrinsics/extrinsics reprojection OK", "PASS" if cal_passed else "PENDING"),
                ("DualCam Synchronization", "Sync cues verified in sync.json", "PASS" if sync_passed else "PENDING"),
                ("3D Triangulation & Filter", "Passed TRC 3D marker coordinates", "PASS" if recon_passed else "PENDING"),
                ("OpenSim Kinematics", "Inverse kinematics .mot angles", "PASS" if "KINEMATICS_PASSED" in str(passport.get("history", [])) else "UNVERIFIED")
            ]
            for g, ev, verd in chain:
                c = primary_teal if verd == "PASS" else ("#b45309" if verd == "PENDING" else "#6b7280")
                ax2.text(0.06, y2, g, color=text_dark, fontsize=8.5)
                ax2.text(0.36, y2, ev, color=text_dark, fontsize=8.5)
                ax2.text(0.78, y2, verd, color=c, fontsize=8.5, weight="bold")
                y2 -= 0.022

            # Page 2 Footer
            ax2.plot([0.06, 0.94], [0.10, 0.10], color="#d1d5db", linewidth=0.8)
            ax2.text(0.5, 0.065, "KineLab PT — Page 2 of 2 · Evidence Chain", color="#6b7280", fontsize=8, ha="center")

            pdf.savefig(fig2)
            plt.close(fig2)

        return pdf_path
