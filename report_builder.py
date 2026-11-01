"""Truthful offline research report generator for KineLab PT.

Generates multi-page vector PDF, machine-readable JSON, and tabular CSV summaries.
Zero fabricated clinical diagnoses, zero interpolated angles for missing frames.
Prominently watermarks test-only or synthetic fixtures.
"""
from __future__ import annotations

import csv
import json
import math
import tempfile
import textwrap
import unicodedata
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages, RendererPdf
from matplotlib.font_manager import FontProperties

from gait_events import EVIDENCE_CLASSIFICATION, GAIT_ALGORITHM_VERSION, SOURCE_SCHEMA
from manual_assessment import validate_manual_assessment
from report_generation import OMITTED
from session_contract import sha256_file, strict_json_loads
from session_index import SessionIndex
from squat_events import SQUAT_ALGORITHM_VERSION
from take_acceptance import checked_path


def _csv_row(writer, values):
    def literal(value):
        if isinstance(value, str):
            normalized = unicodedata.normalize('NFKC', value).lstrip('\ufeff \t\r\n\v\f')
            if normalized.startswith(('=', '+', '-', '@')) or any(ord(c) < 32 for c in value):
                return 'Text: ' + value
        return value
    writer.writerow([literal(value) for value in values])


EVENT_ANALYSIS_UNAVAILABLE = "UNAVAILABLE"


def _or_unavailable(value):
    return value if value is not None else EVENT_ANALYSIS_UNAVAILABLE


def _event_count(value, field, maximum=None):
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"{field}: expected a bounded nonnegative integer")
    return value


def _event_score(value, field, minimum=0.0, maximum=1.0):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not minimum <= value <= maximum):
        raise ValueError(f"{field}: expected a finite raw score in [{minimum}, {maximum}]")


def _event_exclusions(value, field, frames):
    if not isinstance(value, dict):
        raise TypeError(f"{field}: expected an exclusion-count object")
    for key, count in value.items():
        if key == "policy" and isinstance(count, str):
            continue
        if isinstance(count, dict):
            _event_exclusions(count, f"{field}.{key}", frames)
        else:
            _event_count(count, f"{field}.{key}", frames)


def _validated_event_candidate(doc, passport, kind):
    """Validate the fields we expose; source matching does not prove derivation."""
    if doc.get("test_only") is not True:
        raise ValueError("test_only must be true for the current candidate producers")
    if doc.get("evidence_classification") != EVIDENCE_CLASSIFICATION:
        raise ValueError("evidence_classification contradicts the test-only producer")
    expected = (GAIT_ALGORITHM_VERSION, "UNVALIDATED_EVENT_CANDIDATES") if kind == "gait" else (
        SQUAT_ALGORITHM_VERSION, "UNVALIDATED_2D_SQUAT_CANDIDATES")
    if doc.get("algorithm_version") != expected[0]:
        raise ValueError("algorithm_version is incompatible with the current producer")
    if doc.get("classification") != expected[1]:
        raise ValueError("classification is incompatible with unvalidated candidates")
    if kind == "gait" and doc.get("source_schema") != SOURCE_SCHEMA:
        raise ValueError("source_schema is incompatible with the current gait producer")
    role = doc.get("role")
    source = passport.get("sources", {}).get(role) if isinstance(role, str) else None
    digest = doc.get("source_sha256")
    if (role not in ("cam01_trial", "cam02_trial") or not isinstance(source, dict)
            or not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or digest != source.get("sha256") or digest != source.get("observed_sha256")
            or source.get("integrity_state") != "unchanged"):
        raise ValueError("source binding unavailable or inconsistent with the indexed session source")
    frames = _event_count(doc.get("observed_frames"), "observed_frames")
    if frames == 0:
        raise ValueError("observed_frames must be positive")
    key = "candidates" if kind == "gait" else "repetitions"
    items = doc.get(key)
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError(f"{key}: expected an explicit list of objects")
    count_key = "candidate_count" if kind == "gait" else "candidate_repetition_count"
    if _event_count(doc.get(count_key), count_key) != len(items):
        raise ValueError(f"{count_key} does not match {key}")
    metrics = doc.get("unsupported_metrics")
    if not isinstance(metrics, list) or any(
        not isinstance(metric, dict) or metric.get("status") != "UNSUPPORTED"
        or metric.get("value") is not None or not isinstance(metric.get("metric"), str)
        or not isinstance(metric.get("reason"), str) for metric in metrics
    ):
        raise ValueError("unsupported_metrics must preserve explicit unsupported/null values")
    result: dict = {"role": role, "source_sha256": digest, "algorithm_version": expected[0],
              "test_only": True, "evidence_classification": EVIDENCE_CLASSIFICATION,
              "classification": expected[1], "unsupported_metrics": metrics}
    for item in items:
        if item.get("model_score_is_probability") is not False:
            raise ValueError(f"{key}.model_score_is_probability must be false")
        if kind == "gait":
            _event_count(item.get("frame_index"), "candidates.frame_index", frames - 1)
            _event_count(item.get("window_observed_frames"), "candidates.window_observed_frames", frames)
            if item["window_observed_frames"] == 0:
                raise ValueError("candidates.window_observed_frames must be positive")
            _event_score(item.get("window_min_raw_landmark_score"), "candidates.window_min_raw_landmark_score", .43, math.inf)
            _event_score(item.get("window_min_score_margin_over_threshold"),
                         "candidates.window_min_score_margin_over_threshold", 0, math.inf)
            if not math.isclose(item["window_min_score_margin_over_threshold"],
                                item["window_min_raw_landmark_score"] - .43, rel_tol=0.0, abs_tol=1e-6):
                raise ValueError("candidates raw-score threshold margin is contradictory")
            if item.get("side") not in ("left", "right") or item.get("event_type") not in (
                    "unassigned_extremum", "candidate_initial_contact", "candidate_toe_off"):
                raise ValueError("candidates side/event_type is incompatible with the producer")
        else:
            for field in ("start_frame", "bottom_frame", "end_frame"):
                _event_count(item.get(field), f"repetitions.{field}", frames - 1)
            if not item["start_frame"] <= item["bottom_frame"] <= item["end_frame"]:
                raise ValueError("repetitions phase boundaries are out of order")
            _event_score(item.get("min_required_landmark_raw_score"),
                         "repetitions.min_required_landmark_raw_score", .43, math.inf)
            _event_count(item.get("unmeasured_frames_within_rep"),
                         "repetitions.unmeasured_frames_within_rep", item["end_frame"] - item["start_frame"] + 1)
    if kind == "gait":
        _event_exclusions(doc.get("sample_exclusions"), "sample_exclusions", frames)
        result.update(candidate_count=len(items), sample_exclusions=doc["sample_exclusions"],
                      candidates=[{field: item[field] for field in (
                          "frame_index", "side", "event_type", "window_min_raw_landmark_score",
                          "window_min_score_margin_over_threshold", "window_observed_frames",
                          "model_score_is_probability")} for item in items])
    else:
        quality = doc.get("quality")
        if not isinstance(quality, dict):
            raise ValueError("quality: expected an exclusion-count object")
        _event_exclusions(quality.get("exclusion_reasons"), "quality.exclusion_reasons", frames)
        incomplete = _event_count(doc.get("incomplete_attempts"), "incomplete_attempts", frames)
        result.update(candidate_repetition_count=len(items), incomplete_attempts=incomplete,
                      quality_exclusion_reasons=quality["exclusion_reasons"],
                      repetitions=[{field: item[field] for field in (
                          "start_frame", "bottom_frame", "end_frame", "min_required_landmark_raw_score",
                          "unmeasured_frames_within_rep", "model_score_is_probability")} for item in items])
    return result


def _collect_event_analysis(folder: Path, passport: dict, manual_context=None) -> dict:
    """Expose validated test-only candidates; never infer absent or unbound scores."""
    groups: dict[str, list[dict]] = {"gait": [], "squat": [], "scoring": []}
    issues = []
    schemas = {"kinelab.2d-gait-candidates.v1": "gait", "kinelab.2d-squat-candidates.v1": "squat"}

    def add_manual(path):
        relative = path.relative_to(folder).as_posix()
        if manual_context is not None and relative not in {
                receipt['descriptor']['path'] for receipt in manual_context['assessments']}:
            entry = {field: EVENT_ANALYSIS_UNAVAILABLE for field in (
                'missed_reference_count', 'unscorable_reference_count', 'false_candidate_count',
                'by_event_type', 'phase_boundary_disagreement_count', 'incomplete_attempts')}
            entry.update(status='BLOCKED_STALE_OR_UNAUDITED_MANUAL_ASSESSMENT', artifact=relative)
            groups['scoring'].append(entry)
            return
        try:
            groups["scoring"].append(validate_manual_assessment(folder, path, passport))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            entry = {field: EVENT_ANALYSIS_UNAVAILABLE for field in (
                "missed_reference_count", "unscorable_reference_count", "false_candidate_count",
                "by_event_type", "phase_boundary_disagreement_count", "incomplete_attempts")}
            entry.update(status="BLOCKED_INVALID_MANUAL_ASSESSMENT", reason=str(exc), artifact=relative,
                         artifact_sha256=EVENT_ANALYSIS_UNAVAILABLE)
            groups["scoring"].append(entry)
            issues.append({"artifact": relative, "status": "INVALID", "reason": str(exc)})

    for directory in (folder, folder / "exports"):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            relative = path.relative_to(folder).as_posix()
            if path.name.endswith(".manual-assessment.json"):
                add_manual(path)
                continue
            try:
                data = strict_json_loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                issues.append({"artifact": relative, "status": "INVALID", "reason": str(exc)})
                continue
            if not isinstance(data, dict):
                if any(word in path.stem for word in ("gait", "squat", "scoring")):
                    issues.append({"artifact": relative, "status": "INVALID", "reason": "event artifact must be an object"})
                continue
            schema = data.get("schema")
            kind = schemas.get(schema) if isinstance(schema, str) else None
            if kind:
                try:
                    result = _validated_event_candidate(data, passport, kind)
                    result["artifact"] = relative
                    result["artifact_sha256"] = sha256_file(path)
                    groups[kind].append(result)
                except (TypeError, ValueError) as exc:
                    issues.append({"artifact": relative, "status": "INVALID", "reason": str(exc)})
            elif (isinstance(schema, str) and schema.startswith(("kinelab.2d-gait-candidates", "kinelab.2d-squat-candidates"))):
                issues.append({"artifact": relative, "status": "INCOMPATIBLE", "reason": f"unsupported event schema: {schema}"})
            elif isinstance(schema, str) and schema.startswith("kinelab.manual-assessment"):
                add_manual(path)
            elif (any(key in data for key in ("missed_reference_count", "reference_outcomes", "matched_pairs"))
                  or "scoring" in path.stem):
                reason = "Current scoring producers omit source/reference binding; stored counts cannot be verified for this session."
                invalid = None
                try:
                    if data.get("test_only") is not True or data.get("evidence_classification") != EVIDENCE_CLASSIFICATION:
                        raise ValueError("scoring test_only/evidence_classification contradicts the current producers")
                    for field in ("missed_reference_count", "unscorable_reference_count", "false_candidate_count",
                                  "reference_count", "candidate_count", "matched_count",
                                  "phase_boundary_disagreement_count", "incomplete_attempts"):
                        if data.get(field) is not None:
                            _event_count(data[field], f"scoring.{field}")
                    for field in ("precision", "recall"):
                        if data.get(field) is not None:
                            _event_score(data[field], f"scoring.{field}")
                    if "by_event_type" in data:
                        _event_exclusions(data["by_event_type"], "scoring.by_event_type", None)
                except (TypeError, ValueError) as exc:
                    invalid = str(exc)
                    reason = invalid + "; " + reason
                entry: dict = {field: EVENT_ANALYSIS_UNAVAILABLE for field in (
                    "missed_reference_count", "unscorable_reference_count", "false_candidate_count",
                    "by_event_type", "phase_boundary_disagreement_count", "incomplete_attempts")}
                entry.update(status="BLOCKED_INVALID_SCORING" if invalid else "BLOCKED_UNBOUND_SCORING", reason=reason, artifact=relative,
                             artifact_sha256=sha256_file(path))
                groups["scoring"].append(entry)
                issues.append({"artifact": relative, "status": "INVALID" if invalid else "UNVERIFIED", "reason": reason})
            elif any(word in path.stem for word in ("gait-candidates", "squat-candidates")):
                issues.append({"artifact": relative, "status": "INCOMPATIBLE", "reason": "missing or unsupported event schema"})
    present = any(groups.values())
    status = ("BLOCKED_INVALID_OR_UNBOUND_EVENT_EVIDENCE" if issues else
              "TEST_ONLY_CANDIDATE_EVIDENCE_NOT_PHYSICAL_VALIDATION" if present else EVENT_ANALYSIS_UNAVAILABLE)
    return {"status": status,
            "gait_candidates": groups["gait"] or EVENT_ANALYSIS_UNAVAILABLE,
            "squat_candidates": groups["squat"] or EVENT_ANALYSIS_UNAVAILABLE,
            "manual_scoring": groups["scoring"] or EVENT_ANALYSIS_UNAVAILABLE,
            "artifact_issues": issues,
            "note": ("Stored candidates are generated/test-only, unvalidated evidence. Source matching checks source bytes, "
                     "not algorithm derivation or physical/clinical validity. Blocked or absent fields remain UNAVAILABLE."
                     if present or issues else "No stored event-analysis artifacts found; event confidence is unavailable.")}


_GAIT_EVENT_FIELDS = ("frame_index", "side", "event_type",
                      "window_min_raw_landmark_score",
                      "window_min_score_margin_over_threshold",
                      "window_observed_frames", "model_score_is_probability")
_SQUAT_REP_FIELDS = ("start_frame", "bottom_frame", "end_frame",
                     "min_required_landmark_raw_score",
                     "unmeasured_frames_within_rep", "model_score_is_probability")
_EVENT_CSV_LAYOUT = {"gait_candidates": ("candidates", _GAIT_EVENT_FIELDS),
                     "squat_candidates": ("repetitions", _SQUAT_REP_FIELDS)}


class ReportBuilder:
    def __init__(self, projects_root: Path | str, index: SessionIndex | None = None):
        self.projects_root = checked_path(Path(projects_root)).resolve()
        self.index = index or SessionIndex(self.projects_root / ".kinelab_index.db", self.projects_root)

    def generate_reports(self, session_id: str, output_dir: Path | str | None = None, *,
                         expected_report_head=OMITTED,
                         expected_report_context_sha256=OMITTED) -> dict[str, Path]:
        from report_generation import capture_inputs, publication_context, publish_reports
        from take_acceptance import acceptance_lease, require_no_pending
        folder = self.index.library.open_session(session_id)
        passport = self.index.get_passport(session_id)
        if passport.get("kind") == "live" or passport.get("state") == "EVIDENCE_UNVERIFIED":
            raise ValueError("EVIDENCE_UNVERIFIED: legacy live motion cannot be used to generate research reports")
        exports = folder / 'exports'
        if output_dir is not None and Path(output_dir).resolve() != exports.resolve():
            raise ValueError('REPORT_OUTPUT_INVALID: report generations belong to the selected session exports')
        if any((exports / f'{session_id}-{suffix}').exists()
                for suffix in ('research-report.pdf', 'research-summary.json', 'metrics.csv')):
            raise ValueError('OUTPUT_EXISTS: existing report revision is immutable')
        # Refuse stale/invalid requests before creating even the administrative anchor.
        publication_context(self.index, session_id, expected_report_head, expected_report_context_sha256)
        require_no_pending(folder)
        # The OS lease is fail-fast; no index lock is held while acquiring it.
        with acceptance_lease(folder):
            require_no_pending(folder)
            context, head = publication_context(self.index, session_id, expected_report_head,
                                                expected_report_context_sha256)
            inputs = capture_inputs(folder)
            exports.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.report-staging-', dir=exports) as temporary:
                staging = Path(temporary)
                outputs = self._generate_report_files(session_id, staging, report_context=context)
                return publish_reports(self.index, session_id, staging, outputs, inputs,
                                       context=context, supersedes=head)

    def _generate_report_files(self, session_id: str, output_dir: Path, *, report_context=None) -> dict[str, Path]:
        folder = self.index.library.open_session(session_id)
        passport = self.index.get_passport(session_id)
        if passport.get("kind") == "live" or passport.get("state") == "EVIDENCE_UNVERIFIED":
            raise ValueError("EVIDENCE_UNVERIFIED: legacy live motion cannot be used to generate research reports")
        self.index.reindex()
        passport = self.index.get_passport(session_id)
        if passport.get("state") == "EVIDENCE_INVALID":
            raise ValueError("EVIDENCE_INVALID: changed or missing upstream evidence")
        from export_motion import load_verified_motion
        motion_files = sorted((folder / "exports").glob("*.motion.json"))
        if len(motion_files) > 1:
            raise ValueError("EVIDENCE_INVALID: select one immutable motion revision before reporting")
        measured = load_verified_motion(folder, motion_files[0]) if motion_files else None
        measurement_count = sum(any(point is not None for point in frame["xyz"])
                                for frame in measured["frames"]) if measured else 0
        is_test_only = passport.get("is_test_only", False)
        watermark = passport.get("watermark")
        now_utc = datetime.now(UTC).isoformat()

        out_dir = Path(output_dir) if output_dir else (folder / "exports")
        out_dir.mkdir(parents=True, exist_ok=True)

        session_json_path = folder / "session.json"
        sess_meta = {}
        if session_json_path.is_file():
            try:
                sess_meta = strict_json_loads(session_json_path.read_text(encoding="utf-8-sig"))
                if not isinstance(sess_meta, dict):
                    raise TypeError("session metadata must be an object")
            except (OSError, ValueError, TypeError) as error:
                raise ValueError("EVIDENCE_INVALID: unreadable session metadata") from error

        if "live" in (sess_meta.get("kind"), passport.get("kind")):
            raise ValueError("EVIDENCE_UNVERIFIED: legacy live motion cannot be used to generate research reports")
        effective_metadata = None
        if report_context is not None:
            from session_metadata_revision import read_metadata_state
            state = read_metadata_state(self.index, session_id)
            if state['status'] != 'AVAILABLE' or state['context_sha256'] != report_context['metadata_context_sha256']:
                raise ValueError('REPORT_CONTEXT_CHANGED: verified metadata changed before rendering')
            effective_metadata = state['metadata']

        pdf_path = out_dir / f"{session_id}-research-report.pdf"
        json_path = out_dir / f"{session_id}-research-summary.json"
        csv_path = out_dir / f"{session_id}-metrics.csv"
        if any(path.exists() for path in (pdf_path, json_path, csv_path)):
            raise ValueError("OUTPUT_EXISTS: existing report revision is immutable")
        def installed(package):
            try:
                return version(package)
            except PackageNotFoundError:
                return "unavailable"

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
            "measurement_count": measurement_count,
            "event_analysis": _collect_event_analysis(folder, passport,
                None if report_context is None else report_context['manual_assessment_context']),
            "csv_text_policy": "Formula-shaped or control-containing strings are prefixed with Text: in CSV; JSON preserves the original value.",
            "measurement_status": "No valid measurements" if not measurement_count else
                ("Synthetic test samples only" if is_test_only else "Research samples — physical accuracy unverified"),
            "motion_sha256": sha256_file(motion_files[0]) if measured else None,
            "provenance": {
                "software": "KineLab PT local software candidate",
                "pose2sim_version": installed("pose2sim"),
                "opensim_version": installed("opensim"),
                "onnxruntime_version": installed("onnxruntime")
            },
            "passport": passport,
            "sources": passport.get("sources", {}),
            "board_measurement": passport.get("board_measurement"),
            "runs": passport.get("runs", {}),
            "limitations": "Internal research software only. Physical camera geometry and clinical accuracy unverified without physical measurement evidence and independent reference validation."
        }
        if report_context is not None:
            json_doc.update(effective_metadata=effective_metadata,
                            metadata_context_sha256=report_context['metadata_context_sha256'],
                            manual_assessment_context=report_context['manual_assessment_context'],
                            report_context_sha256=report_context['report_context_sha256'])
        json_path.write_text(json.dumps(json_doc, indent=2, allow_nan=False), encoding="utf-8")

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
            _csv_row(writer, [
                "session_id", "kind", "state", "captured_count", "board_measured_mm",
                "operator", "calibration_passed", "sync_passed", "reconstruction_passed",
                "clinical_accuracy_verified", "is_test_only", "generated_at_utc"
            ])
            _csv_row(writer, [
                session_id, passport.get("kind"), passport.get("state"),
                passport.get("captured_count"), board_mm, operator,
                cal_passed, sync_passed, recon_passed,
                False, is_test_only, now_utc
            ])
            # Additional detail rows for captured sources
            _csv_row(writer, [])
            _csv_row(writer, ["role", "filename", "bytes", "sha256", "duration_s", "width", "height", "fps"])
            for role, s in passport.get("sources", {}).items():
                _csv_row(writer, [
                    role, s.get("filename", ""), s.get("bytes", ""), s.get("sha256", ""),
                    s.get("duration", ""), s.get("width", ""), s.get("height", ""), s.get("fps", "")
                ])
            event_analysis = json_doc["event_analysis"]
            if effective_metadata is not None:
                _csv_row(writer, [])
                _csv_row(writer, ['effective_metadata', 'value'])
                for key, value in sorted(effective_metadata.items()):
                    _csv_row(writer, [key, value])
                _csv_row(writer, ['metadata_context_sha256', report_context['metadata_context_sha256']])
            _csv_row(writer, [])
            _csv_row(writer, ["event_analysis", "value"])
            _csv_row(writer, ["status", event_analysis["status"]])
            for group in ("gait_candidates", "squat_candidates"):
                section = event_analysis[group]
                _csv_row(writer, [group, section if isinstance(section, str)
                                  else f"{len(section)} artifact(s); per-event fields in JSON report"])
            scoring = event_analysis["manual_scoring"]
            if isinstance(scoring, str):
                _csv_row(writer, ["manual_scoring", scoring])
            else:
                for position, entry in enumerate(scoring):
                    for key in ("missed_reference_count", "unscorable_reference_count",
                                "false_candidate_count", "phase_boundary_disagreement_count",
                                "incomplete_attempts", "status", "reason", "evidence_classification"):
                        _csv_row(writer, [f"manual_scoring[{position}].{key}",
                                          entry.get(key, "UNAVAILABLE")])

            # B16: full per-row event detail so the CSV reconciles 1:1 with the
            # JSON event_analysis counts and the paginated PDF tables. Every value
            # comes from the already-validated json_doc (no new raw-file reads)
            # and passes through the _csv_row escaping policy.
            _csv_row(writer, [])
            _csv_row(writer, ["event_row", "field", "value"])
            for group in ("gait_candidates", "squat_candidates"):
                section = event_analysis[group]
                if isinstance(section, str):
                    _csv_row(writer, [group, "rows", section])
                    continue
                row_key, fields = _EVENT_CSV_LAYOUT[group]
                for artifact_position, artifact_entry in enumerate(section):
                    base = f"{group}[{artifact_position}]"
                    for meta_key in ("artifact", "artifact_sha256", "role",
                                     "algorithm_version", "classification",
                                     "evidence_classification", "candidate_count",
                                     "candidate_repetition_count", "incomplete_attempts"):
                        if meta_key in artifact_entry:
                            _csv_row(writer, [base, meta_key, artifact_entry[meta_key]])
                    for row_position, event_row in enumerate(artifact_entry[row_key]):
                        for field in fields:
                            _csv_row(writer, [f"{base}.{row_key}[{row_position}]", field,
                                              event_row[field]])
            issue_list = event_analysis["artifact_issues"]
            _csv_row(writer, ["artifact_issues", "count", len(issue_list)])
            for issue_position, issue in enumerate(issue_list):
                for issue_key in ("artifact", "status", "reason"):
                    _csv_row(writer, [f"artifact_issues[{issue_position}]", issue_key,
                                      issue.get(issue_key, EVENT_ANALYSIS_UNAVAILABLE)])

        # 3. PDF Report (Vector Matplotlib PdfPages)
        self._build_pdf(pdf_path, json_doc)

        return {"pdf": pdf_path, "json": json_path, "csv": csv_path}

    def _build_pdf(self, pdf_path: Path, doc: dict):
        """Replay the pure render plan produced by build_pdf_pages 1:1.

        B16: pagination, repeated per-page table headers, computed 'Page X of Y'
        footers, full validated event/repetition tables, blocked-artifact and
        no-data statements, and passport-derived provenance are all decided in
        build_pdf_pages (plain data). Plan checks cover draw operations and row
        reconciliation; PDF rendering, glyphs and readability need separate checks.
        """
        pages = build_pdf_pages(doc)
        with PdfPages(pdf_path) as pdf:
            for page in pages:
                fig = plt.figure(figsize=(8.5, 11), dpi=150)
                fig.patch.set_facecolor("#f8faf9")
                ax = fig.add_axes((0, 0, 1, 1))
                # Render-plan coordinates are fractions of the fixed page.
                ax.set_xlim(0.0, 1.0)
                ax.set_ylim(0.0, 1.0)
                ax.set_autoscale_on(False)
                ax.axis("off")
                for op in page:
                    kind = op["kind"]
                    if kind == "text":
                        ax.text(op["x"], op["y"], op["s"], color=op["color"],
                                fontsize=op["fontsize"], weight=op["weight"],
                                ha=op["ha"], fontfamily="sans-serif", parse_math=False, usetex=False)
                    elif kind == "rect":
                        ax.add_patch(plt.Rectangle((op["x"], op["y"]), op["w"], op["h"],
                                                   facecolor=op["facecolor"],
                                                   edgecolor=op["edgecolor"],
                                                   linewidth=op["linewidth"]))
                    elif kind == "hline":
                        ax.plot([op["x0"], op["x1"]], [op["y"], op["y"]],
                                color=op["color"], linewidth=0.8)
                    else:
                        raise ValueError(f"REPORT_RENDER_FAILED: unknown plan op {kind!r}")
                pdf.savefig(fig)
                plt.close(fig)
        return pdf_path


# ---------------------------------------------------------------------------
# B16 PDF render plan.
#
# build_pdf_pages(doc) returns a list of pages; each page is a list of plain
# draw-op dicts consumed by _build_pdf. The plan checks content, coordinates and
# row reconciliation; actual PDF rendering and readability remain separate gates.
# The plan preserves (or refuses rather than silently truncates):
#   - every validated gait/squat/manual event and repetition row in the plan
#     and carries a counting tag used for JSON/PDF reconciliation;
#   - table column headers repeat on every page a table continues onto;
#   - each table page-chunk carries a 'rows X-Y of N' range label;
#   - footers carry computed 'Page X of Y' numbering (no hardcoded totals);
#   - all provenance statements derive only from the already-verified doc /
#     passport data (recorded expected_square_mm, probed source metadata,
#     run records bound to this revision); anything not verifiable from those
#     inputs renders UNAVAILABLE plus an evidence-limitation note;
#   - blocked-artifact reasons and explicit no-data statements are included.
# No unbound raw-file reads are performed anywhere in this module.
# ---------------------------------------------------------------------------

_PDF_TOP = 0.895
_PDF_BOTTOM = 0.135
_PDF_LINE = 0.021
_PDF_LIMIT_NOTE = ("UNAVAILABLE - not recorded in the verified inputs bound to this "
                   "report revision; nothing is inferred (evidence limitation).")
_PDF_COLORS = {"primary": "#0f4c47", "dark": "#1c2b29", "warn": "#b45309",
               "gray": "#4b5563", "light": "#9ca3af", "red": "#dc2626",
               "mint": "#99f6e4", "head": "#374151"}

_GAIT_TABLE = {"headers": ("Frame", "Side", "Event type", "Min score", "Margin",
                            "Win frames", "Prob?"),
                   "col_x": (0.06, 0.13, 0.21, 0.42, 0.53, 0.66, 0.79),
                   "col_chars": (7, 7, 22, 10, 8, 10, 6)}
_SQUAT_TABLE = {"headers": ("Start", "Bottom", "End", "Min req. score", "Unmeasured",
                             "Prob?"),
                    "col_x": (0.06, 0.15, 0.25, 0.34, 0.52, 0.70),
                    "col_chars": (8, 8, 8, 18, 17, 12)}
_SOURCE_TABLE = {"headers": ("Role", "Filename", "Status", "Resolution", "FPS",
                              "Duration"),
                     "col_x": (0.06, 0.20, 0.50, 0.62, 0.76, 0.86),
                     "col_chars": (14, 30, 9, 13, 7, 8)}
_CHAIN_TABLE = {"headers": ("Pipeline Gate",
                             "Acceptance Evidence (derived from bound records)",
                             "Gate Verdict"),
                    "col_x": (0.06, 0.30, 0.80),
                    "col_chars": (24, 52, 12)}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _wrap(value, max_chars, *, width=None, fontsize=9.0, weight="normal"):
    """Preserve normalized text; additionally fit literal PDF text to its column."""
    text = " ".join(str(value).split())
    if not text:
        return [""]
    lines = textwrap.wrap(text, width=max(8, int(max_chars)),
                          break_long_words=True, break_on_hyphens=False) or [""]
    if width is None:
        return lines
    # RendererPdf uses the same unhinted font metrics as the saved vector PDF.
    # Reserve one em inside the column for glyph overhang and backend rounding.
    available = width * 8.5 * 72 - fontsize
    if not math.isfinite(available) or available <= 0:
        raise ValueError("REPORT_RENDER_FAILED: invalid text column width")
    renderer = RendererPdf(None, 72, 11, 8.5)
    font = FontProperties(family="sans-serif", size=fontsize, weight=weight)

    def fits(line):
        measured, _, _ = renderer.get_text_width_height_descent(line, font, False)
        return math.isfinite(measured) and measured <= available

    result = []
    for line in lines:
        while line:
            if fits(line):
                result.append(line)
                break
            low, high = 0, len(line)
            while low < high:
                middle = (low + high + 1) // 2
                if fits(line[:middle]):
                    low = middle
                else:
                    high = middle - 1
            if low == 0:
                raise ValueError("REPORT_RENDER_FAILED: glyph does not fit text column")
            boundary = line.rfind(" ", 0, low + 1)
            count = boundary if boundary > 0 else low
            result.append(line[:count].rstrip())
            line = line[count:].lstrip()
    return result


class _PlanBuilder:
    """Accumulates draw ops into pages; starts a new page when out of room."""

    def __init__(self):
        self.pages: list = [[]]
        self.y = _PDF_TOP

    def new_page(self):
        self.pages.append([])
        self.y = _PDF_TOP

    def ensure(self, height):
        if self.y - height < _PDF_BOTTOM:
            self.new_page()

    def op(self, **operation):
        self.pages[-1].append(operation)

    def rect(self, x, y, w, h, facecolor, edgecolor="none", linewidth=0.0):
        self.op(kind="rect", x=x, y=y, w=w, h=h, facecolor=facecolor,
                edgecolor=edgecolor, linewidth=linewidth)

    def hline(self, y=None, color="#d1d5db"):
        self.op(kind="hline", x0=0.06, x1=0.94,
                y=self.y if y is None else y, color=color)

    def text(self, x, value, max_chars=95, tag=None, color=None, fontsize=9.0,
             weight="normal", ha="left"):
        first = True
        if ha == "left":
            width = 0.94 - x
        elif ha == "right":
            width = x - 0.06
        else:
            width = 2 * min(x - 0.06, 0.94 - x)
        for line in _wrap(value, max_chars, width=width, fontsize=fontsize, weight=weight):
            self.ensure(_PDF_LINE)
            self.op(kind="text", x=x, y=self.y, s=line, tag=tag if first else None,
                    color=color or _PDF_COLORS["dark"], fontsize=fontsize,
                    weight=weight, ha=ha)
            self.y -= _PDF_LINE
            first = False

    def gap(self, height=0.012):
        self.ensure(height)
        self.y -= height


def _banner(pb, title, subtitle=None):
    if pb.y != _PDF_TOP or pb.pages[-1]:
        pb.new_page()
    pb.rect(0.0, 0.925, 1.0, 0.075, _PDF_COLORS["primary"])
    pb.op(kind="text", x=0.06, y=0.962, s=title, tag=None, color="white",
          fontsize=13.0, weight="bold", ha="left")
    if subtitle:
        pb.op(kind="text", x=0.06, y=0.936, s=subtitle, tag=None,
              color=_PDF_COLORS["mint"], fontsize=8.5, weight="normal", ha="left")
    pb.y = _PDF_TOP


def _pairs(pb, pairs, label_chars=26, value_chars=66, fontsize=9.0,
           x_label=0.08, x_value=0.34):
    """Two-column label/value block, continued line by line across pages."""
    for label, value in pairs:
        text_value = value if isinstance(value, str) else str(value)
        label_lines = _wrap(label, label_chars, width=x_value - x_label - 0.02, fontsize=fontsize, weight="bold")
        value_lines = _wrap(text_value, value_chars, width=0.94 - x_value, fontsize=fontsize)
        value_color = _PDF_COLORS["red"] if "ABSENT" in text_value else _PDF_COLORS["dark"]
        for offset in range(max(len(label_lines), len(value_lines))):
            pb.ensure(_PDF_LINE)
            if offset < len(label_lines):
                pb.op(kind="text", x=x_label, y=pb.y, s=label_lines[offset],
                      tag=None, color=_PDF_COLORS["gray"], fontsize=fontsize,
                      weight="bold", ha="left")
            if offset < len(value_lines):
                pb.op(kind="text", x=x_value, y=pb.y, s=value_lines[offset],
                      tag=None, color=value_color, fontsize=fontsize, weight="normal",
                      ha="left")
            pb.y -= _PDF_LINE


def _table(pb, title, headers, col_x, col_chars, rows, tag_prefix, count_label):
    """Paginated table: headers repeat per page, 'rows X-Y of N' chunk labels,
    wrapped multi-line cells, fail-closed on rows that cannot fit (never
    silently truncated or skipped). Returns the number of data rows rendered."""
    pb.text(0.06, title, max_chars=85, color=_PDF_COLORS["primary"],
            fontsize=10.0, weight="bold")
    total = len(rows)
    pb.text(0.06, f"{count_label}: {total}", max_chars=105,
            color=_PDF_COLORS["gray"], fontsize=8.5)
    if total == 0:
        pb.text(0.06, "NO VALIDATED ROWS - zero data rows exist in the verified "
                      "JSON for this section; absence is reported explicitly and "
                      "never rendered as measured zeros.",
                max_chars=112, color=_PDF_COLORS["warn"], fontsize=8.5)
        pb.gap()
        return 0

    def row_lines(cells, fontsize=8.0, weight="normal"):
        return [
            _wrap(cell, col_chars[index],
                  width=(col_x[index + 1] if index + 1 < len(col_x) else 0.94)
                  - col_x[index], fontsize=fontsize, weight=weight)
            for index, cell in enumerate(cells)
        ]

    def draw_row(cells, tag=None, color=None, fontsize=8.0, weight="normal"):
        wrapped = row_lines(cells, fontsize, weight)
        height = max(len(cell_lines) for cell_lines in wrapped) * _PDF_LINE
        if pb.y - height < _PDF_BOTTOM:
            return False
        baseline = pb.y
        for index, cell_lines in enumerate(wrapped):
            for offset, line in enumerate(cell_lines):
                pb.op(kind="text", x=col_x[index], y=baseline - offset * _PDF_LINE,
                      s=line, tag=tag if (index == 0 and offset == 0) else None,
                      color=color or _PDF_COLORS["dark"], fontsize=fontsize,
                      weight=weight, ha="left")
        pb.y = baseline - height
        return True

    rendered = 0
    position = 0
    while position < total:
        first_height = max(len(cell_lines)
                           for cell_lines in row_lines(rows[position])) * _PDF_LINE
        if pb.y - (_PDF_LINE * 2 + first_height + 0.01) < _PDF_BOTTOM:
            pb.new_page()
        label_op = {"kind": "text", "x": 0.06, "y": pb.y, "s": "", "tag": None,
                    "color": _PDF_COLORS["gray"], "fontsize": 7.5,
                    "weight": "normal", "ha": "left"}
        pb.pages[-1].append(label_op)
        pb.y -= _PDF_LINE
        draw_row(list(headers), color=_PDF_COLORS["head"], fontsize=8.0,
                 weight="bold")
        pb.hline(y=pb.y + _PDF_LINE / 2)
        pb.y -= 0.005
        chunk_first = position
        while position < total:
            if not draw_row(list(rows[position]), tag=tag_prefix + (position,)):
                break
            position += 1
            rendered += 1
        if position == chunk_first:
            raise ValueError("REPORT_RENDER_FAILED: table row does not fit on an "
                             "empty page; refusing to truncate or skip rows")
        label_op["s"] = f"rows {chunk_first + 1}-{position} of {total}"
        pb.gap(0.016)
    return rendered


def _gate_evidence(run):
    if not isinstance(run, dict):
        return "UNAVAILABLE - no run record bound to this report revision"
    config = str(run.get("config_sha256") or EVENT_ANALYSIS_UNAVAILABLE)
    return (f"run record: state={run.get('state', EVENT_ANALYSIS_UNAVAILABLE)}; "
            f"passed={run.get('passed', False)}; config_sha256={config[:16]}; "
            f"updated_utc={run.get('updated_at_utc') or EVENT_ANALYSIS_UNAVAILABLE}")


def _expected_event_totals(event_analysis):
    def row_total(section, key):
        if not isinstance(section, list):
            return 0
        return sum(len(artifact[key]) for artifact in section
                   if isinstance(artifact, dict) and isinstance(artifact.get(key), list))
    scoring = event_analysis.get("manual_scoring")
    return {"gait_event_rows": row_total(event_analysis.get("gait_candidates"),
                                         "candidates"),
            "squat_repetition_rows": row_total(event_analysis.get("squat_candidates"),
                                               "repetitions"),
            "manual_scoring_entries": len(scoring) if isinstance(scoring, list) else 0}


def _render_cover(pb, doc):
    passport = doc.get("passport") or {}
    _banner(pb, "KINELAB PT - BIOMECHANICS RESEARCH REPORT",
            "Local-First Desktop Movement Analysis - Research Software Prototype")
    if doc.get("is_test_only"):
        pb.rect(0.06, pb.y - 0.032, 0.88, 0.045, "#fef3c7", _PDF_COLORS["warn"], 1.5)
        pb.op(kind="text", x=0.5, y=pb.y - 0.016, tag=None, ha="center",
              s="TEST ONLY - NOT PHYSICAL DUAL-CAMERA VALIDATION",
              color=_PDF_COLORS["warn"], fontsize=10.5, weight="bold")
        pb.y -= 0.055
    else:
        pb.rect(0.06, pb.y - 0.032, 0.88, 0.045, "#e6fffa", _PDF_COLORS["primary"], 1.0)
        pb.op(kind="text", x=0.5, y=pb.y - 0.016, tag=None, ha="center",
              s=f"SESSION PASSPORT STATE: {passport.get('state', 'UNKNOWN')}",
              color=_PDF_COLORS["primary"], fontsize=10.5, weight="bold")
        pb.y -= 0.055
    pb.text(0.06, "SESSION PROVENANCE & IDENTIFICATION", max_chars=85,
            color=_PDF_COLORS["primary"], fontsize=10.5, weight="bold")
    provenance = doc.get("provenance") or {}
    event_analysis = doc.get("event_analysis") or {}
    meta_lines = [
        ("Session Identifier:", doc.get("session_id", EVENT_ANALYSIS_UNAVAILABLE)),
        ("Capture Type / Kind:", passport.get("kind", "unknown")),
        ("Report Generation UTC:", doc.get("generated_at_utc",
                                           EVENT_ANALYSIS_UNAVAILABLE)),
        ("Measurements:", doc.get("measurement_status", EVENT_ANALYSIS_UNAVAILABLE)),
        ("Pipeline Versions:",
         (f"Pose2Sim {provenance.get('pose2sim_version', EVENT_ANALYSIS_UNAVAILABLE)} | "
         f"OpenSim {provenance.get('opensim_version', EVENT_ANALYSIS_UNAVAILABLE)}")),
        ("Evidence State:", passport.get("state", "UNKNOWN")),
        ("Clinical Accuracy:", "UNVERIFIED (Research Software Only)"),
        ("Event Analysis:", event_analysis.get("status", EVENT_ANALYSIS_UNAVAILABLE)),
    ]
    if doc.get("effective_metadata") is not None:
        effective = doc["effective_metadata"]
        meta_lines.extend([
            ("Effective Subject:", str(effective["subject_id"])),
            ("Effective Operator:", str(effective["operator_id"])),
            ("Effective Protocol:", str(effective["protocol_id"]))])
    _pairs(pb, meta_lines)
    pb.gap()
    sources = passport.get("sources") or {}
    rows = []
    for role in ("cam01_intrinsics", "cam02_intrinsics", "cam01_board",
                 "cam02_board", "cam01_trial", "cam02_trial"):
        source = sources.get(role)
        if isinstance(source, dict):
            fps = source.get("fps")
            duration = source.get("duration")
            rows.append([role,
                         str(source.get("filename") or EVENT_ANALYSIS_UNAVAILABLE),
                         "Present",
                         (f"{source['width']}x{source['height']}"
                          if all(_is_number(source.get(key))
                                 and math.isfinite(source[key]) and source[key] > 0
                                 for key in ("width", "height")) else "UNAVAIL."),
                         f"{fps:.1f}" if _is_number(fps) else "UNAVAIL.",
                         f"{duration:.1f}s" if _is_number(duration) else "UNAVAIL."])
        else:
            rows.append([role, f"{role}.mp4 (expected path)", "MISSING",
                         "UNAVAIL.", "UNAVAIL.", "UNAVAIL."])
    layout = _SOURCE_TABLE
    _table(pb, "CAPTURED CAMERA SOURCES (6-ROLE PROTOCOL, PASSPORT-PROBED METADATA)",
           layout["headers"], layout["col_x"], layout["col_chars"], rows,
           ("sources",), "Source rows")


def _render_evidence(pb, doc):
    passport = doc.get("passport") or {}
    runs = passport.get("runs") or {}
    bm = passport.get("board_measurement")
    _banner(pb, "PHYSICAL CALIBRATION & SYNCHRONIZATION EVIDENCE",
            "Every statement below derives from the verified passport bound to this revision.")
    pb.text(0.06, "1. OPERATOR PHYSICAL BOARD MEASUREMENT", max_chars=85,
            color=_PDF_COLORS["primary"], fontsize=10.5, weight="bold")
    if isinstance(bm, dict):
        expected = bm.get("expected_square_mm")
        measured = bm.get("measured_square_mm")
        board_lines = [
            ("Recorded Expected Square:",
             f"{expected} mm (expected_square_mm recorded in board-measurement.json, "
             "index-verified)" if _is_number(expected) else _PDF_LIMIT_NOTE),
            ("Operator Measured Value:",
             f"{measured} mm" if _is_number(measured) else _PDF_LIMIT_NOTE),
            ("Measurement Performed By:", str(bm.get("measured_by") or _PDF_LIMIT_NOTE)),
            ("Recorded Timestamp:", str(bm.get("recorded_at_utc") or _PDF_LIMIT_NOTE)),
            ("Recorded Source Field:", str(bm.get("source") or _PDF_LIMIT_NOTE)),
            ("Board Geometry Note:",
             ("Corner/square counts and print scaling are not recorded in the verified "
             "inputs; no board geometry beyond the recorded square sizes is claimed "
             "(evidence limitation).")),
            ("Measurement Verification:",
             "Operator-reported physical ruler entry (not auto-inferred)"),
        ]
    else:
        board_lines = [
            ("Physical Board Measurement:", "ABSENT / PENDING OPERATOR ENTRY"),
            ("Recorded Expected Square:", _PDF_LIMIT_NOTE),
            ("Protocol Requirement:",
             "Must print checkerboard at 100%, measure square with ruler, record mm"),
            ("Quality Gate Status:",
             "BLOCKED - Registration and Calibration require measured mm"),
        ]
    _pairs(pb, board_lines, fontsize=8.5, value_chars=70)
    pb.gap()
    pb.text(0.06, "2. CAMERA GEOMETRY & SYNCHRONIZATION (PASSPORT-DERIVED ONLY)",
            max_chars=85, color=_PDF_COLORS["primary"], fontsize=10.5, weight="bold")
    sources = passport.get("sources") or {}
    sync_lines = []
    for role in ("cam01_trial", "cam02_trial"):
        source = sources.get(role)
        if isinstance(source, dict):
            geometry = ", ".join(f"{key}={source[key]}"
                                 for key in ("width", "height", "fps", "duration")
                                 if _is_number(source.get(key)))
            sync_lines.append((f"Camera stream {role}:", geometry or _PDF_LIMIT_NOTE))
        else:
            sync_lines.append((f"Camera stream {role}:",
                               ("UNAVAILABLE - role absent from the verified passport "
                               "sources.")))
    sync_lines.append(("Camera Device Labels:",
                       ("UNAVAILABLE - device model/name (phone, webcam, ...) is not "
                       "recorded in any verified input bound to this revision; no "
                       "device claim is rendered (evidence limitation).")))
    sync_run = runs.get("synchronization")
    sync_lines.append(("Synchronization Gate:",
                       _gate_evidence(sync_run) if isinstance(sync_run, dict) else
                       "UNAVAILABLE - no synchronization run record is bound to this "
                       "report revision."))
    sync_lines.append(("Synchronization Method Detail:",
                       ("UNAVAILABLE - per-camera cue offsets/residuals computed by "
                       "sync_evidence.prepare_sync are not part of the passport "
                       "inputs bound to this revision; no exact-decoded-frame-time "
                       "claim is rendered (evidence limitation).")))
    tri_run = runs.get("triangulation")
    sync_lines.append(("Triangulation Gate:",
                       _gate_evidence(tri_run) if isinstance(tri_run, dict) else
                       "UNAVAILABLE - no triangulation run record is bound to this "
                       "report revision."))
    sync_lines.append(("Reconstruction Method Detail:",
                       ("UNAVAILABLE - algorithm internals (DLT variant, reprojection "
                       "thresholds) are not recorded in the verified inputs; only the "
                       "bound gate verdict above is stated (evidence limitation).")))
    _pairs(pb, sync_lines, fontsize=8.5, value_chars=70)
    pb.gap()
    pb.text(0.06, "3. STAGE ACCEPTANCE EVIDENCE CHAIN", max_chars=85,
            color=_PDF_COLORS["primary"], fontsize=10.5, weight="bold")
    cal_passed = bool(runs.get("calibration", {}).get("passed", False))
    sync_passed = bool(runs.get("synchronization", {}).get("passed", False))
    recon_passed = bool(runs.get("triangulation", {}).get("passed", False))
    history = str(passport.get("history", []))
    captured = passport.get("captured_count")
    probed = sum(1 for source in sources.values() if isinstance(source, dict))
    chain = [
        ("Six Source Videos",
         (f"passport captured_count={captured if _is_number(captured) else 'UNAVAILABLE'}; "
         f"probed passport source rows={probed}"),
         "PASS" if captured == 6 else "PENDING"),
        ("Physical Measurement",
         "board-measurement.json recorded and index-verified" if isinstance(bm, dict)
         else "UNAVAILABLE - no recorded board measurement",
         "PASS" if isinstance(bm, dict) else "PENDING"),
        ("Original Hash Registration", "session.json immutable registration",
         "PASS" if passport.get("badge") in ("REGISTERED", "TEST ONLY") else "PENDING"),
        ("Video Normalization",
         "NORMALIZATION_PASSED recorded in passport history"
         if "NORMALIZATION_PASSED" in history else
         "UNAVAILABLE - no normalization record in the bound passport history",
         "PASS" if "NORMALIZATION_PASSED" in history else "PENDING"),
        ("Camera Calibration", _gate_evidence(runs.get("calibration")),
         "PASS" if cal_passed else "PENDING"),
        ("DualCam Synchronization", _gate_evidence(runs.get("synchronization")),
         "PASS" if sync_passed else "PENDING"),
        ("3D Triangulation & Filter", _gate_evidence(runs.get("triangulation")),
         "PASS" if recon_passed else "PENDING"),
        ("OpenSim Kinematics",
         "KINEMATICS_PASSED recorded in passport history"
         if "KINEMATICS_PASSED" in history else
         "UNAVAILABLE - no kinematics record in the bound passport history",
         "PASS" if "KINEMATICS_PASSED" in history else "UNVERIFIED"),
    ]
    layout = _CHAIN_TABLE
    _table(pb, "Acceptance chain (verdicts from bound passport/run records only)",
           layout["headers"], layout["col_x"], layout["col_chars"],
           [[gate, evidence, verdict] for gate, evidence, verdict in chain],
           ("chain",), "Gate rows")


def _render_unsupported(pb, artifact):
    for metric in artifact.get("unsupported_metrics") or []:
        pb.text(0.12,
                f"unsupported metric: {metric.get('metric', EVENT_ANALYSIS_UNAVAILABLE)}"
                f" - status={metric.get('status', EVENT_ANALYSIS_UNAVAILABLE)}, "
                f"value={metric.get('value')}, "
                f"reason={metric.get('reason', EVENT_ANALYSIS_UNAVAILABLE)}",
                max_chars=105, fontsize=7.5, color=_PDF_COLORS["gray"])


def _render_events(pb, doc):
    ea = doc.get("event_analysis") or {}
    _banner(pb, "EVENT & REPETITION EVIDENCE - TEST-ONLY CANDIDATES",
            "All rows rendered from the validated JSON report data; PDF totals equal JSON counts.")
    pb.text(0.06, f"Event analysis status: {ea.get('status', EVENT_ANALYSIS_UNAVAILABLE)}",
            max_chars=98, fontsize=9.0, weight="bold")
    pb.text(0.06, f"Note: {ea.get('note', EVENT_ANALYSIS_UNAVAILABLE)}",
            max_chars=112, fontsize=8.0, color=_PDF_COLORS["gray"])
    pb.text(0.06, "Stored candidates are generated/test-only evidence: NOT physical "
                  "or clinical validation.",
            max_chars=98, fontsize=8.5, color=_PDF_COLORS["warn"], weight="bold")
    totals = {"gait_event_rows": 0, "squat_repetition_rows": 0,
              "manual_scoring_entries": 0}

    pb.gap()
    pb.text(0.06, "A. GAIT EVENT CANDIDATES", max_chars=85,
            color=_PDF_COLORS["primary"], fontsize=10.5, weight="bold")
    gait = ea.get("gait_candidates", EVENT_ANALYSIS_UNAVAILABLE)
    if isinstance(gait, str):
        pb.text(0.06, f"NO DATA - {gait}: no validated gait event rows exist for "
                      "this session; zero rows are rendered and absence is never "
                      "reported as measured zeros.",
                max_chars=112, fontsize=8.5, color=_PDF_COLORS["warn"])
    else:
        pb.text(0.06, f"Gait candidate artifacts: {len(gait)}", max_chars=105,
                fontsize=8.5, color=_PDF_COLORS["gray"])
        for index, artifact in enumerate(gait):
            pb.text(0.06,
                    f"Gait artifact [{index}]: {artifact.get('artifact')} "
                    f"(role={artifact.get('role')}, "
                    f"algorithm={artifact.get('algorithm_version')}, "
                    f"source_sha256={str(artifact.get('source_sha256'))[:16]}..., "
                    f"artifact_sha256={str(artifact.get('artifact_sha256'))[:16]}...)",
                    max_chars=105, fontsize=8.5, weight="bold")
            rows = [[str(item[field]) for field in _GAIT_EVENT_FIELDS]
                    for item in artifact.get("candidates", [])]
            layout = _GAIT_TABLE
            rendered = _table(pb, f"Gait candidate events - artifact [{index}]",
                              layout["headers"], layout["col_x"], layout["col_chars"],
                              rows, ("gait", index), "Validated candidate event rows")
            if rendered != artifact.get("candidate_count"):
                raise ValueError("REPORT_RECONCILIATION_FAILED: gait artifact "
                                 f"[{index}] rendered {rendered} of "
                                 f"{artifact.get('candidate_count')} rows")
            totals["gait_event_rows"] += rendered
            pb.text(0.10, "sample_exclusions: "
                          f"{json.dumps(artifact.get('sample_exclusions'), sort_keys=True)}",
                    max_chars=110, fontsize=7.5, color=_PDF_COLORS["gray"])
            _render_unsupported(pb, artifact)
            pb.gap()

    pb.gap()
    pb.text(0.06, "B. SQUAT REPETITION CANDIDATES", max_chars=85,
            color=_PDF_COLORS["primary"], fontsize=10.5, weight="bold")
    squat = ea.get("squat_candidates", EVENT_ANALYSIS_UNAVAILABLE)
    if isinstance(squat, str):
        pb.text(0.06, f"NO DATA - {squat}: no validated squat repetition rows exist "
                      "for this session; zero rows are rendered and absence is never "
                      "reported as measured zeros.",
                max_chars=112, fontsize=8.5, color=_PDF_COLORS["warn"])
    else:
        pb.text(0.06, f"Squat candidate artifacts: {len(squat)}", max_chars=105,
                fontsize=8.5, color=_PDF_COLORS["gray"])
        for index, artifact in enumerate(squat):
            pb.text(0.06,
                    f"Squat artifact [{index}]: {artifact.get('artifact')} "
                    f"(role={artifact.get('role')}, "
                    f"algorithm={artifact.get('algorithm_version')}, "
                    f"source_sha256={str(artifact.get('source_sha256'))[:16]}..., "
                    f"artifact_sha256={str(artifact.get('artifact_sha256'))[:16]}...)",
                    max_chars=105, fontsize=8.5, weight="bold")
            rows = [[str(item[field]) for field in _SQUAT_REP_FIELDS]
                    for item in artifact.get("repetitions", [])]
            layout = _SQUAT_TABLE
            rendered = _table(pb, f"Squat repetitions - artifact [{index}]",
                              layout["headers"], layout["col_x"], layout["col_chars"],
                              rows, ("squat", index), "Validated repetition rows")
            if rendered != artifact.get("candidate_repetition_count"):
                raise ValueError("REPORT_RECONCILIATION_FAILED: squat artifact "
                                 f"[{index}] rendered {rendered} of "
                                 f"{artifact.get('candidate_repetition_count')} rows")
            totals["squat_repetition_rows"] += rendered
            pb.text(0.10,
                    "quality_exclusion_reasons: "
                    f"{json.dumps(artifact.get('quality_exclusion_reasons'), sort_keys=True)}"
                    f"; incomplete_attempts={artifact.get('incomplete_attempts')}",
                    max_chars=110, fontsize=7.5, color=_PDF_COLORS["gray"])
            _render_unsupported(pb, artifact)
            pb.gap()

    pb.gap()
    pb.text(0.06, "C. MANUAL SCORING ENTRIES", max_chars=85,
            color=_PDF_COLORS["primary"], fontsize=10.5, weight="bold")
    scoring = ea.get("manual_scoring", EVENT_ANALYSIS_UNAVAILABLE)
    if isinstance(scoring, str):
        pb.text(0.06, f"NO DATA - {scoring}: no validated manual scoring entries "
                      "exist for this session; nothing is rendered and absence is "
                      "never reported as measured zeros.",
                max_chars=112, fontsize=8.5, color=_PDF_COLORS["warn"])
    else:
        pb.text(0.06, f"Manual scoring entries: {len(scoring)}", max_chars=105,
                fontsize=8.5, color=_PDF_COLORS["gray"])
        for index, entry in enumerate(scoring):
            pb.text(0.06,
                    f"Manual scoring entry [{index}]: "
                    f"{entry.get('artifact', EVENT_ANALYSIS_UNAVAILABLE)}",
                    max_chars=105, fontsize=9.0, weight="bold", tag=("manual", index))
            entry_pairs = [(key, entry.get(key, EVENT_ANALYSIS_UNAVAILABLE))
                           for key in ("status", "reason", "missed_reference_count",
                                       "unscorable_reference_count",
                                       "false_candidate_count",
                                       "phase_boundary_disagreement_count",
                                       "incomplete_attempts", "by_event_type",
                                       "evidence_classification", "artifact_sha256")]
            _pairs(pb, entry_pairs, label_chars=32, value_chars=78, fontsize=8.0,
                   x_value=0.36)
            totals["manual_scoring_entries"] += 1
            pb.gap()

    pb.gap()
    pb.text(0.06, "D. BLOCKED / INVALID ARTIFACT STATEMENTS", max_chars=85,
            color=_PDF_COLORS["primary"], fontsize=10.5, weight="bold")
    issues = ea.get("artifact_issues") or []
    if not issues:
        pb.text(0.06, "None recorded - no blocked, invalid, incompatible or unbound "
                      "event artifacts were found for this session.",
                max_chars=112, fontsize=8.5)
    else:
        pb.text(0.06, f"Blocked/invalid artifacts: {len(issues)}", max_chars=105,
                fontsize=8.5, color=_PDF_COLORS["gray"])
        for index, issue in enumerate(issues):
            pb.text(0.06,
                    f"Blocked artifact [{index}]: "
                    f"{issue.get('artifact', EVENT_ANALYSIS_UNAVAILABLE)} - status "
                    f"{issue.get('status', EVENT_ANALYSIS_UNAVAILABLE)}",
                    max_chars=105, fontsize=8.5, weight="bold",
                    color=_PDF_COLORS["warn"])
            pb.text(0.10, f"Reason: {issue.get('reason', EVENT_ANALYSIS_UNAVAILABLE)}",
                    max_chars=110, fontsize=8.0, color=_PDF_COLORS["gray"])

    expected = _expected_event_totals(ea)
    if totals != expected:
        raise ValueError(f"REPORT_RECONCILIATION_FAILED: rendered {totals} != "
                         f"JSON counts {expected}")
    pb.gap()
    pb.text(0.06, "E. PDF/JSON/CSV RECONCILIATION", max_chars=85,
            color=_PDF_COLORS["primary"], fontsize=10.5, weight="bold")
    pb.text(0.06,
            f"Rendered data rows - gait_event_rows={totals['gait_event_rows']}, "
            f"squat_repetition_rows={totals['squat_repetition_rows']}, "
            f"manual_scoring_entries={totals['manual_scoring_entries']}. These "
            "totals equal the JSON report event_analysis counts and the per-row "
            "CSV keys. A count mismatch prevents report publication.",
            max_chars=112, fontsize=8.0)


def _render_limitations(pb, doc):
    _banner(pb, "REPORT EVIDENCE LIMITATIONS")
    pb.text(0.06, doc.get("limitations") or
            "UNAVAILABLE - no report limitations were recorded.",
            max_chars=112, fontsize=8.0, color=_PDF_COLORS["gray"])


def _render_footers(pages, doc):
    total_pages = len(pages)
    limitation_note = ("Full evidence limitations are listed in the report body."
                       if doc.get("limitations") else
                       "Limitations unavailable; see the report body.")
    for index, page in enumerate(pages):
        page.append({"kind": "hline", "x0": 0.06, "x1": 0.94, "y": 0.105,
                     "color": "#d1d5db"})
        page.append({"kind": "text", "x": 0.5, "y": 0.078, "tag": None, "ha": "center",
                     "s": "KineLab PT - Confidential Research Output - Not for "
                          "Diagnostic Use",
                     "color": "#6b7280", "fontsize": 8.0, "weight": "normal"})
        page.append({"kind": "text", "x": 0.5, "y": 0.056, "tag": None, "ha": "center",
                     "s": f"Page {index + 1} of {total_pages}",
                     "color": "#6b7280", "fontsize": 8.5, "weight": "bold"})
        page.append({"kind": "text", "x": 0.5, "y": 0.038, "tag": None,
                     "ha": "center", "s": limitation_note,
                     "color": "#9ca3af", "fontsize": 6.5, "weight": "normal"})


def _assert_plan_reconciliation(pages, doc):
    expected = _expected_event_totals(doc.get("event_analysis") or {})
    counted = {"gait_event_rows": 0, "squat_repetition_rows": 0,
               "manual_scoring_entries": 0}
    kinds = {"gait": "gait_event_rows", "squat": "squat_repetition_rows",
             "manual": "manual_scoring_entries"}
    for page in pages:
        for op in page:
            tag = op.get("tag")
            if isinstance(tag, tuple) and tag and tag[0] in kinds:
                counted[kinds[tag[0]]] += 1
    if counted != expected:
        raise ValueError(f"REPORT_RECONCILIATION_FAILED: PDF plan tags {counted} "
                         f"!= JSON counts {expected}")


def build_pdf_pages(doc):
    """Pure B16 render plan: list of pages of plain draw-op dicts.

    Checks on this plan cover intended content, coordinates and row counts.
    Actual PDF rendering, glyphs and readability require separate verification.
    Fails closed (ValueError) when planned rows diverge from JSON report counts.
    """
    pb = _PlanBuilder()
    _render_cover(pb, doc)
    _render_evidence(pb, doc)
    _render_events(pb, doc)
    _render_limitations(pb, doc)
    _render_footers(pb.pages, doc)
    _assert_plan_reconciliation(pb.pages, doc)
    return pb.pages
