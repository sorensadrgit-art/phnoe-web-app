"""T6 Python orchestration: one narrowly scoped local API, existing quality guards.

Operator actions only. The existing SessionLibrary, CaptureStation,
WorkflowController and SyncReviewWindow remain the authoritative sources.
No clinical accuracy or 3D reconstruction is inferred from test footage.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import UTC
from pathlib import Path
from uuid import uuid4

import manual_assessment_entry
from backup_manager import BackupCorruptError, BackupManager
from backup_schedule import BackupSchedule, BackupScheduleError
from capture_station import (
    PARTICIPANT_RECORDING_BLOCKED,
    RAW_ROLES,
    RECOMMENDED_SECONDS,
    ROLE_GUIDE,
    WEBCAM_ROLES,
    finalize_recording,
    import_phone_mp4,
    save_board_measurement,
)
from local_diagnostics import log_local_failure
from pose_inference import PoseInference
from recording_store import RecordingStore
from report_builder import ReportBuilder
from report_generation import OMITTED, current_report_generation_context
from runtime_config import ensure_data_root, runtime_identity
from session_index import SessionIndex
from session_library import SessionLibrary
from session_metadata_revision import publish_metadata_revision, read_metadata_state
from unified_service import WorkflowJobJournal
from workflow_controller import WorkflowController
from workflow_recovery import inspect_recovery

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)
DEFAULT_PROJECT = ROOT / "projects" / "capture-20261026-trial01"
CALISCOPE = "caliscope-walking-test-20261027"
ALLOWED_REPORTS = {
    "session.json", "normalization.json", "preflight.json", "sync-observations.json",
    "sync.json", "run.json", "board-measurement.json", "Config.toml",
}


class IntegrationBlocked(ValueError):
    """An explicit action was not authorized or its native quality gate failed."""


class IntegratedService:
    def __init__(self, projects_root: Path | None = None, *, pose_models: Path | None = None):
        self.projects_root = ensure_data_root(projects_root)
        self.runtime_id = runtime_identity(self.projects_root)
        self.mutex = threading.RLock()
        self.jobs: dict[str, WorkflowController] = {}
        self.job_journals: dict[str, WorkflowJobJournal] = {}
        self.instance_id = uuid4().hex
        self._closed = False
        self.webcam: dict | None = None
        self.webcam_latest: dict[str, dict] = {}
        self.backup_mgr = BackupManager(self.projects_root)
        self.backup_schedule = BackupSchedule(self.backup_mgr)
        self.backup_schedule.recover(now=int(time.time()), strict=False)
        self.backup_pump = None  # D05/D08 OPEN: no production worker may start.
        with self.backup_mgr.startup_recovery():
            self.library = SessionLibrary(self.projects_root)
            db_path = self.projects_root / ".kinelab_index.db"
            self.index = SessionIndex(db_path, self.projects_root)
            self.backup_mgr.index = self.index
        self.recordings = RecordingStore(self.index)
        self.report_builder = ReportBuilder(self.projects_root, self.index)
        self.pose_inference = PoseInference(pose_models if pose_models is not None else ROOT / 'models' / 'pose-v1')

    def close(self):
        mutex = getattr(self, "mutex", None)
        if mutex is None:
            return
        # Join outside service.mutex: a worker may be waiting for that mutex.
        pump_failure = None
        pump = getattr(self, "backup_pump", None)
        if pump is not None:
            try:
                pump.close()
            except BackupScheduleError as error:
                if pump.thread.is_alive():
                    raise  # Preserve its index until the owned worker actually exits.
                pump_failure = error
        with mutex:
            if getattr(self, "_closed", False):
                return
            failure = pump_failure
            try:
                for journal in getattr(self, "job_journals", {}).values():
                    if journal.operation_id is not None:
                        try:
                            journal.interrupt()
                        except (OSError, ValueError) as error:
                            failure = failure or error
            finally:
                if hasattr(self, "index") and self.index:
                    self.index.close()
            if failure is not None:
                raise failure
            self._closed = True

    def __del__(self):
        try:
            self.close()
        except Exception as error:  # noqa: BLE001 - Best-effort cleanup uses bounded privacy-safe diagnostics.
            log_local_failure(logger, logging.ERROR, "local_service_cleanup_failed", error)

    def sessions(self) -> list[dict]:
        with self.mutex:
            sessions = []
            for item in self.library.list_sessions():
                metadata_state = read_metadata_state(self.index, item["id"])
                sessions.append({
                    **{key: value for key, value in item.items() if key != "path"},
                    "metadata_state": metadata_state,
                    "effective_metadata": metadata_state["metadata"] if metadata_state["status"] == "AVAILABLE" else None,
                    "metadata_context_sha256": metadata_state["context_sha256"] if metadata_state["status"] == "AVAILABLE" else None,
                })
            return sessions

    def create_session(self, session_id: str, *, kind: str = "real", metadata: dict | None = None) -> dict:
        if kind != "real":
            # Demo folders may be created via original setup tooling; the
            # consumer integrated shell only creates real unregistered sessions.
            raise IntegrationBlocked("This app creates only REAL unregistered sessions")
        with self.mutex:
            if self.index.conn.execute("SELECT 1 FROM recordings WHERE session_id=?", (session_id,)).fetchone():
                raise IntegrationBlocked("RECORDING_CONFLICT: synthetic recording identity cannot become a native session")
            folder = self.library.create_session(session_id, kind=kind, metadata=metadata)
            return {**{key: value for key, value in self.library.describe_session(folder.name).items()
                       if key != "path"},
                    "metadata_confirmation": self.library.metadata_confirmation(folder.name)}

    def _project(self, session_id: str) -> Path:
        return self.library.open_session(session_id)

    def _editable(self, session_id: str) -> Path:
        folder = self._project(session_id)
        state = self.library.describe_session(session_id)
        if state["kind"] != "real" or state["status"] != "draft":
            raise IntegrationBlocked("Only a REAL unregistered session can accept footage or board measurements")
        return folder

    def session_detail(self, session_id: str) -> dict:
        with self.mutex:
            path = self._project(session_id)
            info = self.library.describe_session(session_id)
            if info["kind"] == "live":
                roles = []
                readiness = {
                    "ready_to_register": False,
                    "missing": [],
                    "issues": [],
                }
            elif info["can_register"]:
                roles = [{
                    "role": role, "instruction": ROLE_GUIDE[role],
                    "camera": "phone" if role.startswith("cam01") else "webcam",
                    "file_present": (path / "raw" / (role + ".mp4")).is_file(),
                    "record_seconds": RECOMMENDED_SECONDS.get(role),
                } for role in RAW_ROLES]
                readiness = self.library.registration_readiness(session_id)
            else:
                roles = [{
                    "role": role, "instruction": ROLE_GUIDE[role],
                    "camera": "phone" if role.startswith("cam01") else "webcam",
                    "file_present": (path / "raw" / (role + ".mp4")).is_file(),
                    "record_seconds": RECOMMENDED_SECONDS.get(role),
                } for role in RAW_ROLES]
                readiness = {
                    "ready_to_register": False,
                    "missing": [role for role in RAW_ROLES if not (path / "raw" / (role + ".mp4")).is_file()],
                    "issues": ["Only a complete, unregistered REAL capture can be registered here"],
                }
            sources = {
                name: (path / name).is_file()
                for name in ("session.json", "board-measurement.json", "normalization.json",
                             "preflight.json", "sync-observations.json", "sync.json", "run.json")
            }
            metadata_state = read_metadata_state(self.index, session_id)
            return {
                **{key: value for key, value in info.items() if key != "path"}, "roles": roles,
                "missing": readiness.get("missing", []),
                "issues": readiness.get("issues", []),
                "ready_to_register": bool(readiness.get("ready_to_register")),
                "sources": sources,
                "metadata_confirmation": self.library.metadata_confirmation(session_id),
                "metadata_state": metadata_state,
                "effective_metadata": metadata_state["metadata"] if metadata_state["status"] == "AVAILABLE" else None,
                "metadata_context_sha256": metadata_state["context_sha256"] if metadata_state["status"] == "AVAILABLE" else None,
                "measurement_status": "EVIDENCE_UNVERIFIED" if info["evidence_status"] == "unverified" else "physical_camera_and_clinical_validation_unverified",
                "test_only": info["kind"] == "test-only",
            }

    def register(self, session_id: str, *, confirm: bool):
        if confirm is not True:
            raise IntegrationBlocked("Explicit operator confirm required before registration")
        with self.mutex:
            self._editable(session_id)
            result = self.library.register_session(session_id)
            self.index.reindex()
            return result

    def measure_board(self, session_id: str, mm: float, operator: str, *, confirm: bool):
        if confirm is not True:
            raise IntegrationBlocked("Explicit measured checkerboard confirmation required")
        with self.mutex:
            return save_board_measurement(self._editable(session_id), mm, operator)

    def import_phone(self, session_id: str, role: str, temp_file: Path, *, confirm: bool):
        if role == "cam01_trial":
            raise IntegrationBlocked(PARTICIPANT_RECORDING_BLOCKED)
        if confirm is not True:
            raise IntegrationBlocked("Explicit phone-file import confirmation required")
        if role not in ("cam01_intrinsics", "cam01_board", "cam01_trial"):
            raise IntegrationBlocked("Only the three cam01 phone roles may be imported as MP4")
        with self.mutex:
            folder = self._editable(session_id)
            return import_phone_mp4(folder, role, Path(temp_file))

    def _poll_webcam(self):
        info = self.webcam
        if info is None:
            return None
        process = info["process"]
        code = process.poll()
        if code is None:
            return {"state": "recording", "session_id": info["session"], "role": info["role"],
                    "seconds": info["seconds"], "message": "Webcam recording in progress; no percentages inferred"}
        try:
            if code != 0:
                raise IntegrationBlocked(f"FFmpeg exited {code}. The .part.mp4 remains unverified; inspect local capture log")
            saved = finalize_recording(self._project(info["session"]), info["role"])
            result = {"state": "saved", "session_id": info["session"], "role": info["role"],
                      "message": "Verified MP4 published; original not overwritten", "filename": saved.name}
        except OSError as error:
            log_local_failure(logger, logging.WARNING, "capture_status_storage_error", error)
            result = {"state": "failed", "session_id": info["session"], "role": info["role"],
                      "message": "CAPTURE_FINALIZE_FAILED: local storage error; unverified recording preserved"}
        except ValueError as error:
            result = {"state": "failed", "session_id": info["session"], "role": info["role"],
                      "message": str(error)}
        finally:
            try:
                process.stdin.close()
            except (OSError, AttributeError):
                pass
            self.webcam = None
        self.webcam_latest[info["session"]] = result
        return result

    def camera_status(self, session_id: str) -> dict:
        with self.mutex:
            self._project(session_id)
            current = self._poll_webcam()
            if current and current["session_id"] == session_id:
                return current
            if self.webcam is not None:
                return {"state": "busy_elsewhere", "message": "Another local session is recording"}
            return self.webcam_latest.get(session_id, {"state": "idle", "message": "Webcam idle"})

    def record_webcam(self, session_id: str, role: str, *, seconds: int, confirm: bool) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Explicit webcam recording consent required")
        if role not in WEBCAM_ROLES:
            raise IntegrationBlocked("Only cam02 webcam roles can use local webcam recording")
        raise IntegrationBlocked(PARTICIPANT_RECORDING_BLOCKED)

    def stop_webcam(self, session_id: str, *, confirm: bool) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Stopping an active camera requires explicit consent")
        with self.mutex:
            if self.webcam is None or self.webcam["session"] != session_id:
                raise IntegrationBlocked("No active webcam recording in this session")
            status = self._poll_webcam()
            if status["state"] != "recording":
                return status
            process = self.webcam["process"]
            try:
                process.stdin.write(b"q\n")
                process.stdin.flush()
            except OSError as error:
                raise IntegrationBlocked("Could not stop FFmpeg gracefully; wait for its timer") from error
            return {"state": "stopping", "session_id": session_id,
                    "message": "Graceful stop requested. MP4 is not saved until verified."}

    def _job_journal(self, session_id: str) -> WorkflowJobJournal:
        project = self._project(session_id)
        if session_id not in self.job_journals:
            self.job_journals[session_id] = WorkflowJobJournal(project, self.instance_id)
        return self.job_journals[session_id]

    def processing_status(self, session_id: str) -> dict:
        with self.mutex:
            journal = self._job_journal(session_id)
            job = self.jobs.get(session_id)
            if job is None:
                return journal.status()
            status = job.poll()
            result = journal.observe(status)
            result["log_file"] = status.log_path.name if status.log_path else None
            return result

    def start_processing(self, session_id: str, action: str, *, confirm: bool) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Explicit operator confirm required before native processing")
        with self.mutex:
            self._project(session_id)
            if self.webcam is not None and self._poll_webcam().get("state") == "recording":
                raise IntegrationBlocked("Cannot start native processing while the webcam is recording")
            old = self.jobs.get(session_id)
            journal = self._job_journal(session_id)
            if old is not None:
                previous = old.poll()
                if previous.state == "running":
                    raise IntegrationBlocked("Native processing busy for this session")
                journal.observe(previous)
            if journal.status()["recovery_required"]:
                raise IntegrationBlocked("Job recovery required before native processing")
            job = WorkflowController(self._project(session_id))
            job.plan(action)  # fail closed before any subprocess is created
            journal.begin(action)
            self.jobs[session_id] = job
            try:
                status = job.start(action)
            except BaseException:
                try:
                    journal.interrupt()
                finally:
                    self.jobs.pop(session_id, None)
                raise
            return journal.observe(status)

    def cancel_processing(self, session_id: str, *, confirm: bool) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Explicit operator confirmation required before cancelling native work")
        with self.mutex:
            job = self.jobs.get(session_id)
            if job is None:
                raise IntegrationBlocked("No known native action to cancel")
            return {"state": "cancelling", "passed": False, "message": job.cancel_now()}

    def reports(self, session_id: str) -> list[dict]:
        with self.mutex:
            project = self._project(session_id)
            files = []
            for name in sorted(ALLOWED_REPORTS):
                candidate = project / name
                if candidate.is_file() and not candidate.is_symlink():
                    files.append({
                        "filename": name, "key": name, "type": "session_evidence",
                        "bytes": candidate.stat().st_size,
                    })
            exports = project / "exports"
            if exports.is_dir() and not exports.is_symlink():
                for file in sorted(exports.iterdir()):
                    if (file.is_file() and not file.is_symlink()
                            and file.name.endswith(".motion.json")
                            and file.parent.resolve() == exports.resolve()):
                        files.append({
                            "filename": file.name, "key": "exports/" + file.name,
                            "type": "motion_export", "bytes": file.stat().st_size,
                        })
            from report_generation import committed_reports
            files.extend(committed_reports(self.index, session_id))
            return files

    def passport(self, session_id: str) -> dict:
        with self.mutex:
            changed_timing_sources = self.index.reindex() or set()
            passport = self.index.get_passport(session_id)
            try:
                source = self.index._research_source(session_id)
                if session_id in changed_timing_sources:
                    raise ValueError("TIMING_SOURCE_CHANGED")
                passport["timing"] = source["timing"]
            except (OSError, ValueError, KeyError, TypeError) as error:
                code = ("TIMING_SOURCE_CHANGED" if session_id in changed_timing_sources
                        else str(error).split(":", 1)[0])
                if code not in {"TIMING_SOURCE_CHANGED", "TIMING_METADATA_CHANGED"}:
                    code = "TIMING_SOURCE_UNAVAILABLE"
                passport["timing"] = {
                    "schema": "kinelab.reconstruction-timing.v1",
                    "status": "UNAVAILABLE", "code": code, "reason": code,
                    "duration_s": None, "segments": [], "gaps": [], "intervals": [],
                    "physical_accuracy_verified": False,
                    "clinical_accuracy_verified": False,
                    "clinical_validation": "UNVERIFIED",
                }
            return passport

    def motion_data(self, session_id: str) -> dict:
        with self.mutex:
            if self.library.describe_session(session_id)["evidence_status"] == "unverified":
                raise IntegrationBlocked("EVIDENCE_UNVERIFIED: legacy live motion cannot be served as verified tracking")
            project = self._project(session_id)
            self.index.reindex()
            if self.index.get_passport(session_id)["state"] == "EVIDENCE_INVALID":
                raise IntegrationBlocked("EVIDENCE_INVALID: changed or missing source evidence")
            exports = project / "exports"
            if exports.is_dir() and not exports.is_symlink():
                files = sorted(exports.glob("*.motion.json"))
                if len(files) > 1:
                    raise IntegrationBlocked("EVIDENCE_INVALID: multiple motion revisions require explicit selection")
                if files:
                    from export_motion import load_verified_motion
                    data = load_verified_motion(project, files[0])
                    if data["schema"] == "kinelab.motion.v1":
                        return {**data, "sessionId": session_id, "kind": "synthetic", "sourceKind": "synthetic",
                                "physical_accuracy_verified": False, "clinical_accuracy_verified": False}
                    return data
            raise FileNotFoundError(f"No motion JSON found for session {session_id}")

    def compare(self, s1: str, s2: str, *, expected_metadata_context_s1: str | None = None,
                expected_metadata_context_s2: str | None = None) -> dict:
        with self.mutex:
            changed_timing_sources = self.index.reindex() or set()
            result = self.index.compare_sessions(
                s1, s2, expected_metadata_context_s1=expected_metadata_context_s1,
                expected_metadata_context_s2=expected_metadata_context_s2)
            if changed_timing_sources.intersection((s1, s2)):
                result["compatible"] = False
                result["reason"] = ((result["reason"] + "; ") if result["reason"] else "") + "TIMING_SOURCE_CHANGED"
                result["research_measurements"]["status"] = "UNAVAILABLE"
                result["research_measurements"]["coordinates"] = []
                result["research_measurements"]["sessions"] = []
            return result

    def publish_metadata_revision(self, session_id: str, request: dict) -> dict:
        fields = {"metadata", "expected_origin_sha256", "expected_head_sha256",
                  "operation_id", "reason_code", "confirm"}
        if not isinstance(request, dict) or set(request) != fields:
            raise IntegrationBlocked("METADATA_INVALID: exact revision request fields required")
        with self.mutex:
            if self._closed:
                raise IntegrationBlocked("METADATA_UNAVAILABLE: service closed")
            if self.webcam is not None:
                raise IntegrationBlocked("METADATA_BUSY: capture active")
            try:
                running = any(job.poll().state == "running" for job in self.jobs.values())
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise IntegrationBlocked("METADATA_UNAVAILABLE: processing state unavailable") from error
            if running:
                raise IntegrationBlocked("METADATA_BUSY: processing active")
            # The publisher owns the single session OS lease and immutable audit commit.
            return publish_metadata_revision(self.index, session_id, **request)

    def _manual_assessment_idle(self) -> None:
        if self._closed:
            raise IntegrationBlocked("MANUAL_ASSESSMENT_UNAVAILABLE")
        if self.webcam is not None:
            raise IntegrationBlocked("MANUAL_ASSESSMENT_BUSY")
        try:
            running = any(job.poll().state == "running" for job in self.jobs.values())
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise IntegrationBlocked("MANUAL_ASSESSMENT_UNAVAILABLE") from error
        if running:
            raise IntegrationBlocked("MANUAL_ASSESSMENT_BUSY")

    def manual_assessment_context(self, session_id: str) -> dict:
        with self.mutex:
            self._manual_assessment_idle()
            return manual_assessment_entry.manual_assessment_context(self.index, session_id)

    def publish_manual_assessment_entry(self, session_id: str, request: dict) -> dict:
        with self.mutex:
            self._manual_assessment_idle()
            return manual_assessment_entry.publish_manual_assessment_entry(self.index, session_id, request)

    def report_context(self, session_id: str) -> dict:
        with self.mutex:
            try:
                return current_report_generation_context(self.index, session_id)
            except ValueError as error:
                code = str(error).partition(":")[0]
                if code in {"REPORT_CONTEXT_UNAVAILABLE", "REPORT_INVALID", "REPORT_SOURCE_CHANGED",
                            "REPORT_INPUT_POLICY_COMPATIBILITY_REQUIRED"}:
                    reason = code
                elif code in {"AUDIT_INVALID", "ARTIFACT_MISMATCH", "QUALITY_POLICY", "QUALITY_REJECTED",
                              "QUALITY_SCHEMA", "QUALITY_UNAVAILABLE", "QUALITY_UNVERIFIED",
                              "METADATA_UNAVAILABLE", "METADATA_INVALID", "METADATA_SOURCE_CHANGED",
                              "METADATA_SOURCE_INVALID", "METADATA_SOURCE_TOO_LARGE",
                              "METADATA_REGISTERED_SESSION_REQUIRED"}:
                    reason = "REPORT_CONTEXT_UNAVAILABLE"
                else:
                    raise
                return {"schema": "kinelab.report-generation-context.v1", "session_id": session_id,
                        "status": "UNAVAILABLE", "report_context_sha256": None,
                        "head": None, "reason": reason}

    def generate_reports(self, session_id: str, *, confirm: bool,
                         expected_report_head=OMITTED,
                         expected_report_context_sha256=OMITTED) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Explicit confirmation required to generate research reports")
        with self.mutex:
            result = self.report_builder.generate_reports(
                session_id, expected_report_head=expected_report_head,
                expected_report_context_sha256=expected_report_context_sha256)
            self.index.reindex()
            return {
                "ok": True, "session_id": session_id,
                "generated": [p.name for p in result.values()],
                "message": f"Generated truthful PDF, CSV and JSON research reports for {session_id}"
            }

    def create_evidence_export(self, session_id: str, body: dict) -> dict:
        """One shared audited publisher; no reindex or arbitrary output path."""
        from evidence_export import publish
        with self.mutex:
            return publish(self.index, session_id, body)

    def evidence_export_receipt(self, session_id: str, operation_id: str) -> dict:
        from evidence_export import read_receipt
        with self.mutex:
            return read_receipt(self.index, session_id, operation_id)

    def evidence_export_artifact(self, session_id: str, operation_id: str) -> bytes:
        from evidence_export import read_receipt
        with self.mutex:
            # Return exact verified bytes; HTTP never reopens a checked path.
            return read_receipt(self.index, session_id, operation_id, artifact=True)

    def _backup_directory(self) -> Path:
        directory = self.projects_root / "backups"
        if (directory.is_symlink()
                or getattr(os.path, "isjunction", lambda _: False)(str(directory))
                or directory.resolve().parent != self.projects_root):
            raise IntegrationBlocked("BACKUP_NAME_INVALID: backup directory must not be a link")
        return directory

    def _backup_schedule_status_locked(self) -> dict:
        status = self.backup_schedule.status()
        pump = self.backup_pump
        # Fixed labels only; no arbitrary exception text, paths, causes or notes.
        if pump is None:
            status["pump_status"] = "NOT_ATTACHED"
        elif pump.health_failure is not None:
            status["pump_status"] = "HEALTH_UNRECORDED"
            status["engine_health"] = "REVIEW_REQUIRED"
        elif pump.failure is not None:
            status["pump_status"] = "TICK_FAILED"
            status["engine_health"] = "REVIEW_REQUIRED"
        else:
            status["pump_status"] = "ATTACHED"
        return status

    def backup_schedule_status(self) -> dict:
        with self.mutex:
            return self._backup_schedule_status_locked()

    def configure_backup_schedule(self, request: object) -> dict:
        with self.mutex:
            self.backup_schedule.configure(request)
            return self._backup_schedule_status_locked()

    def prune_backups(self) -> None:
        self.backup_schedule.prune()

    def backup_schedule_tick(self) -> dict:
        # Pump lock order: service mutex -> scheduler OS lease -> session leases -> index.
        with self.mutex:
            if self._closed:
                raise IntegrationBlocked("BACKUP_SCHEDULE_CLOSED")
            busy = self.webcam is not None or any(job.poll().state == "running" for job in self.jobs.values())
            return self.backup_schedule.tick(now=int(time.time()), busy=busy)

    def backups(self) -> list[dict]:
        with self.mutex:
            backup_dir = self._backup_directory()
            if not backup_dir.is_dir():
                return []
            res = []
            for f in sorted(backup_dir.glob("*.zip"), reverse=True):
                if f.is_file():
                    try:
                        res.append({**self.backup_mgr.inspect_backup(f), "filename": f.name})
                    except (BackupCorruptError, OSError) as error:
                        log_local_failure(logger, logging.WARNING, "local_backup_inspection_failed", error)
            return res

    def create_backup(self, *, confirm: bool, session_ids: list[str] | None = None) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Explicit confirmation required to create backup")
        with self.mutex:
            if self.webcam is not None or any(job.poll().state == "running" for job in self.jobs.values()):
                raise IntegrationBlocked("BACKUP_BUSY: finish native capture and processing before backup")
            from datetime import datetime
            now = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            backup_dir = self._backup_directory()
            backup_dir.mkdir(parents=True, exist_ok=True)
            dest = backup_dir / f"kinelab-backup-{now}-{uuid4().hex}.zip"
            manifest = self.backup_mgr.create_backup(dest, session_ids=session_ids)
            return {"ok": True, "backup_file": dest.name, "manifest": manifest,
                    "message": f"Created hash-verified backup {dest.name}"}

    def restore_backup(self, backup_name: str, *, confirm: bool, overwrite: bool = False) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Explicit confirmation required to restore backup")
        if (not isinstance(backup_name, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.zip", backup_name, flags=re.IGNORECASE) is None
                or backup_name.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL"}):
            raise IntegrationBlocked("BACKUP_NAME_INVALID: select a listed ZIP file name only")
        if overwrite is not False:
            from backup_manager import BackupConflictError
            raise BackupConflictError("RESTORE_OVERWRITE_UNAVAILABLE: existing sessions cannot be replaced")
        with self.mutex:
            directory = self._backup_directory()
            backup_file = directory / backup_name
            if backup_file.is_symlink() or backup_file.resolve().parent != directory.resolve():
                raise IntegrationBlocked("BACKUP_NAME_INVALID: backup must stay inside approved directory")
            if self.backup_mgr.inspect_backup(backup_file)["schema"] == "kinelab.backup.v2":
                recoveries = self.projects_root / "recovery-generations"
                if (recoveries.is_symlink()
                        or getattr(os.path, "isjunction", lambda _: False)(str(recoveries))
                        or recoveries.resolve().parent != self.projects_root):
                    raise IntegrationBlocked("RESTORE_PATH_INVALID: recovery directory must not be a link")
                recoveries.mkdir(exist_ok=True)
                destination = recoveries / f"recovered-{uuid4().hex}"
                result = self.backup_mgr.restore_generation(backup_file, destination)
                relative = destination.relative_to(self.projects_root).as_posix()
                return {**result, "recovery_directory": relative,
                        "message": f"Verified complete recovery in {relative}. Active workspace unchanged."}
            return self.backup_mgr.restore_backup(backup_file, overwrite=False)

    def artifact(self, session_id: str, key: str) -> Path:
        if self.library.describe_session(session_id)["evidence_status"] == "unverified":
            raise IntegrationBlocked("EVIDENCE_UNVERIFIED: archived live reports are not approved evidence downloads")
        self.index.reindex()
        if self.index.get_passport(session_id)["state"] == "EVIDENCE_INVALID":
            raise IntegrationBlocked("EVIDENCE_INVALID: changed or missing source evidence")
        files = {entry["key"] for entry in self.reports(session_id)}
        if key not in files:
            raise IntegrationBlocked("Unknown, unavailable or unapproved report artifact")
        project = self._project(session_id).resolve()
        candidate = (project / key).resolve()
        if not candidate.is_relative_to(project) or not candidate.is_file() or candidate.is_symlink():
            raise IntegrationBlocked("Report cannot escape the selected session")
        if key.endswith(".motion.json"):
            from export_motion import load_verified_motion
            load_verified_motion(project, candidate)
        return candidate

    def analysis(self) -> dict:
        result = {
            "gait": {
                "status": "unavailable", "test_only": True,
                "manual_reference": "not supplied",
                "clinical_accuracy_verified": False,
            },
            "squat": {
                "status": "synthetic_tests_only", "test_only": True,
                "algorithm": "kinelab-t5-squat-2d-phase-v1",
                "clinical_accuracy_verified": False,
                "message": "Squat phase/repetition detector passed synthetic tests. No real side-view squat sequence has been independently validated.",
            },
        }
        sample = self.projects_root / CALISCOPE
        candidate = sample / "external-source" / "gait-t5" / "gait-t5-summary.json"
        if (sample / "TEST-ONLY-NOT-CALIBRATED.txt").is_file() and candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8-sig"))
                if data.get("status") == "UNVALIDATED_CANDIDATES_AWAITING_MANUAL_REVIEW":
                    result["gait"] = {
                        "status": "unvalidated_candidates", "test_only": True,
                        "manual_reference": "not supplied",
                        "clinical_accuracy_verified": False,
                        "view_count": len(data["source_camera_views"]),
                        "candidates": [
                            {"role": e["role"], "count": e["candidate_count"]}
                            for e in data["source_camera_views"]
                        ],
                        "review_path": "/samples/gait-t5/index.html",
                    }
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return result

    def recovery(self, session_id: str) -> dict:
        state = inspect_recovery(self._project(session_id))
        return {key: value for key, value in state.items() if key != "session"}

    def open_native(self, session_id: str, target: str, *, confirm: bool) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Explicit operator request required to open a native tool")
        if target == "capture":
            raise IntegrationBlocked(PARTICIPANT_RECORDING_BLOCKED)
        with self.mutex:
            project = self._project(session_id)
            if target == "folder":
                os.startfile(str(project))
                return {"opened": True, "target": "folder", "message": "Session folder opened"}
            if target == "runbook":
                os.startfile(str(ROOT / "RUNBOOK.md"))
                return {"opened": True, "target": "runbook", "message": "Runbook opened"}
            if target == "board":
                os.startfile(str(ROOT / "assets" / "checkerboard_20mm.svg"))
                return {"opened": True, "target": "board", "message": "Printable checkerboard opened"}
            if target == "sync":
                interpreter = Path(sys.executable)
                if not interpreter.is_file():
                    raise IntegrationBlocked("Local Python GUI environment missing")
                # Validate observations can be made before any GUI launches.
                from sync_evidence import normalized_videos
                normalized_videos(project)
                subprocess.Popen(
                    [str(interpreter), str(ROOT / "launch_sync_review.py"), "--session-id", session_id,
                     "--data-root", str(self.projects_root)],
                    cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
                return {"opened": True, "target": "sync", "message": "Frame-review window opened"}
            raise IntegrationBlocked("Unknown native tool action")

    def get_exercise_presets(self) -> dict:
        return {
            "ok": True,
            "presets": {
                "squats": {
                    "id": "squats",
                    "name": "Squat",
                    "target_rom_deg": 80,
                    "target_options": [60, 75, 90],
                    "fault_tolerances": {
                        "max_trunk_lean": 35,
                        "max_valgus": 8,
                        "min_symmetry": 75,
                    },
                    "instructions": "Stand with feet shoulder-width apart. Descend by bending knees and hips while keeping chest upright.",
                    "clinical_notes": "Monitors bilateral knee flexion depth, trunk tilt, and knee valgus collapse.",
                },
                "lunges": {
                    "id": "lunges",
                    "name": "Lunge",
                    "target_rom_deg": 80,
                    "target_options": [60, 75, 90],
                    "fault_tolerances": {
                        "max_trunk_lean": 25,
                        "max_valgus": 10,
                        "min_symmetry": 60,
                    },
                    "instructions": "Step forward with one leg, lowering hips until both knees are bent at approximately 90°.",
                    "clinical_notes": "Assesses unilateral eccentric quadriceps control, lead knee stability, and vertical trunk posture.",
                },
                "knee-extension": {
                    "id": "knee-extension",
                    "name": "Knee Extension",
                    "target_rom_deg": 75,
                    "target_options": [45, 60, 75],
                    "fault_tolerances": {
                        "max_trunk_lean": 30,
                        "max_valgus": 12,
                        "min_symmetry": 70,
                    },
                    "instructions": "Extend the knee against gravity to full terminal extension.",
                    "clinical_notes": "Focuses on terminal extension lag, quad activation, and range-of-motion restoration post-op.",
                },
                "balance": {
                    "id": "balance",
                    "name": "Single-Leg Balance",
                    "target_rom_deg": 30,
                    "target_options": [15, 30, 45],
                    "fault_tolerances": {
                        "max_trunk_lean": 20,
                        "max_sway": 15,
                    },
                    "instructions": "Lift one foot off the ground and hold steady single-leg stance with arms across chest.",
                    "clinical_notes": "Measures postural sway velocity, lateral trunk compensation, and proprioceptive stability.",
                },
            }
        }

    def save_live_session(self, payload: dict) -> dict:
        """Fail closed until measured acquisition, strict contracts and durable ACKs exist.

        No client-provided source, validity flag, landmarks or summary can override
        this containment gate. Previous implementation silently synthesized frames.
        """
        raise IntegrationBlocked(
            "LIVE_ACQUISITION_UNVERIFIED: saving live measurements is disabled "
            "until camera inference and durable source provenance are independently verified"
        )
