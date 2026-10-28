"""T6 Python orchestration: one narrowly scoped local API, existing quality guards.

Operator actions only. The existing SessionLibrary, CaptureStation,
WorkflowController and SyncReviewWindow remain the authoritative sources.
No clinical accuracy or 3D reconstruction is inferred from test footage.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import os
import subprocess
import sys
import threading
from uuid import uuid4

from capture_station import (
    RAW_ROLES, ROLE_GUIDE, RECOMMENDED_SECONDS, WEBCAM_ROLES,
    prepare_recording, ffmpeg_command, finalize_recording,
    import_phone_mp4, save_board_measurement
)
from session_library import SessionLibrary, SessionError
from workflow_controller import WorkflowController, WorkflowBlocked
from workflow_recovery import inspect_recovery
from session_index import SessionIndex
from report_builder import ReportBuilder
from backup_manager import BackupManager

ROOT = Path(__file__).resolve().parent
DEFAULT_PROJECT = ROOT / "projects" / "capture-20261026-trial01"
CALISCOPE = "caliscope-walking-test-20261027"
ALLOWED_REPORTS = {
    "session.json", "normalization.json", "preflight.json", "sync-observations.json",
    "sync.json", "run.json", "board-measurement.json", "Config.toml",
}


class IntegrationBlocked(ValueError):
    """An explicit action was not authorized or its native quality gate failed."""


class IntegratedService:
    def __init__(self, projects_root: Path | None = None):
        self.projects_root = (Path(projects_root) if projects_root is not None
                              else ROOT / "projects").resolve()
        self.library = SessionLibrary(self.projects_root)
        self.mutex = threading.RLock()
        self.jobs: dict[str, WorkflowController] = {}
        self.webcam: dict | None = None
        self.webcam_latest: dict[str, dict] = {}
        db_path = self.projects_root / ".kinelab_index.db"
        self.index = SessionIndex(db_path, self.projects_root)
        self.report_builder = ReportBuilder(self.projects_root, self.index)
        self.backup_mgr = BackupManager(self.projects_root, self.index)

    def close(self):
        if hasattr(self, "index") and self.index:
            self.index.close()

    def __del__(self):
        self.close()

    def sessions(self) -> list[dict]:
        with self.mutex:
            return [{key: value for key, value in item.items() if key != "path"}
                    for item in self.library.list_sessions()]

    def create_session(self, session_id: str, *, kind: str = "real") -> dict:
        if kind != "real":
            # Demo folders may be created via original setup tooling; the
            # consumer integrated shell only creates real unregistered sessions.
            raise IntegrationBlocked("This app creates only REAL unregistered sessions")
        with self.mutex:
            folder = self.library.create_session(session_id, kind=kind)
            return {key: value for key, value in self.library.describe_session(folder.name).items()
                    if key != "path"}

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
            roles = [{
                "role": role, "instruction": ROLE_GUIDE[role],
                "camera": "phone" if role.startswith("cam01") else "webcam",
                "file_present": (path / "raw" / (role + ".mp4")).is_file(),
                "record_seconds": RECOMMENDED_SECONDS.get(role),
            } for role in RAW_ROLES]
            if info["can_register"]:
                readiness = self.library.registration_readiness(session_id)
            else:
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
            return {
                **{key: value for key, value in info.items() if key != "path"}, "roles": roles,
                "missing": readiness.get("missing", []),
                "issues": readiness.get("issues", []),
                "ready_to_register": bool(readiness.get("ready_to_register")),
                "sources": sources,
                "measurement_status": "physical_camera_and_clinical_validation_unverified",
                "test_only": info["kind"] == "test-only",
            }

    def register(self, session_id: str, *, confirm: bool):
        if confirm is not True:
            raise IntegrationBlocked("Explicit operator confirm required before registration")
        with self.mutex:
            self._editable(session_id)
            return self.library.register_session(session_id)

    def measure_board(self, session_id: str, mm: float, operator: str, *, confirm: bool):
        if confirm is not True:
            raise IntegrationBlocked("Explicit measured checkerboard confirmation required")
        with self.mutex:
            return save_board_measurement(self._editable(session_id), mm, operator)

    def import_phone(self, session_id: str, role: str, temp_file: Path, *, confirm: bool):
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
        except (OSError, ValueError) as error:
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
        with self.mutex:
            self._poll_webcam()
            if self.webcam is not None:
                raise IntegrationBlocked("Webcam busy; stop or finish the current recording")
            project = self._editable(session_id)
            _output, partial = prepare_recording(project, role, seconds)
            log = (project / "capture-station-t6.log").open("ab")
            try:
                process = subprocess.Popen(
                    ffmpeg_command(partial, seconds),
                    cwd=str(ROOT), stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            finally:
                log.close()
            self.webcam = {
                "process": process, "session": session_id, "role": role, "seconds": seconds,
            }
            return self._poll_webcam()

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

    def processing_status(self, session_id: str) -> dict:
        with self.mutex:
            self._project(session_id)
            job = self.jobs.get(session_id)
            if job is None:
                return {"state": "idle", "action": None, "passed": False, "message": "No job active"}
            status = job.poll()
            return {
                "state": status.state, "action": status.action,
                "passed": status.passed, "message": status.message,
                "log_file": status.log_path.name if status.log_path else None,
            }

    def start_processing(self, session_id: str, action: str, *, confirm: bool) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Explicit operator confirm required before native processing")
        with self.mutex:
            self._project(session_id)
            if self.webcam is not None and self._poll_webcam().get("state") == "recording":
                raise IntegrationBlocked("Cannot start native processing while the webcam is recording")
            old = self.jobs.get(session_id)
            if old is not None and old.poll().state == "running":
                raise IntegrationBlocked("Native processing busy for this session")
            job = WorkflowController(self._project(session_id))
            job.plan(action)  # fail closed before any subprocess is created
            status = job.start(action)
            self.jobs[session_id] = job
            return {"state": status.state, "action": status.action, "passed": False,
                    "message": status.message}

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
                            and (file.name.endswith(".motion.json") or file.name.endswith(".pdf")
                                 or file.name.endswith(".csv") or file.name.endswith("-research-summary.json"))
                            and file.parent.resolve() == exports.resolve()):
                        ftype = "research_report" if file.suffix in (".pdf", ".csv", ".json") else "motion_export"
                        files.append({
                            "filename": file.name, "key": "exports/" + file.name,
                            "type": ftype, "bytes": file.stat().st_size,
                        })
            return files

    def passport(self, session_id: str) -> dict:
        with self.mutex:
            self.index.reindex()
            return self.index.get_passport(session_id)

    def compare(self, s1: str, s2: str) -> dict:
        with self.mutex:
            self.index.reindex()
            return self.index.compare_sessions(s1, s2)

    def generate_reports(self, session_id: str, *, confirm: bool) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Explicit confirmation required to generate research reports")
        with self.mutex:
            result = self.report_builder.generate_reports(session_id)
            self.index.reindex()
            return {
                "ok": True, "session_id": session_id,
                "generated": [p.name for p in result.values()],
                "message": f"Generated truthful PDF, CSV and JSON research reports for {session_id}"
            }

    def backups(self) -> list[dict]:
        with self.mutex:
            backup_dir = self.projects_root / "backups"
            if not backup_dir.is_dir():
                return []
            res = []
            for f in sorted(backup_dir.glob("*.zip"), reverse=True):
                if f.is_file():
                    try:
                        res.append({**self.backup_mgr.inspect_backup(f), "filename": f.name})
                    except Exception:
                        pass
            return res

    def create_backup(self, *, confirm: bool, session_ids: list[str] | None = None) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Explicit confirmation required to create backup")
        with self.mutex:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            backup_dir = self.projects_root / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            dest = backup_dir / f"kinelab-backup-{now}.zip"
            manifest = self.backup_mgr.create_backup(dest, session_ids=session_ids)
            return {"ok": True, "backup_file": dest.name, "manifest": manifest,
                    "message": f"Created hash-verified backup {dest.name}"}

    def restore_backup(self, backup_name: str, *, confirm: bool, overwrite: bool = False) -> dict:
        if confirm is not True:
            raise IntegrationBlocked("Explicit confirmation required to restore backup")
        with self.mutex:
            backup_file = self.projects_root / "backups" / backup_name
            result = self.backup_mgr.restore_backup(backup_file, overwrite=overwrite)
            return result

    def artifact(self, session_id: str, key: str) -> Path:
        files = {entry["key"] for entry in self.reports(session_id)}
        if key not in files:
            raise IntegrationBlocked("Unknown, unavailable or unapproved report artifact")
        project = self._project(session_id).resolve()
        candidate = (project / key).resolve()
        if not candidate.is_relative_to(project) or not candidate.is_file() or candidate.is_symlink():
            raise IntegrationBlocked("Report cannot escape the selected session")
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
        with self.mutex:
            project = self._project(session_id)
            pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
            if target == "capture":
                if not pythonw.is_file():
                    raise IntegrationBlocked("Local Python GUI environment missing")
                process = subprocess.Popen(
                    [str(pythonw), str(ROOT / "capture_station_gui.py"), "--session-id", session_id],
                    cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
                return {"opened": True, "target": "capture", "message": "Original Capture Station window opened for this session"}
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
                if not pythonw.is_file():
                    raise IntegrationBlocked("Local Python GUI environment missing")
                # Validate observations can be made before any GUI launches.
                from sync_evidence import normalized_videos
                normalized_videos(project)
                subprocess.Popen(
                    [str(pythonw), str(ROOT / "launch_sync_review.py"), "--session-id", session_id],
                    cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
                return {"opened": True, "target": "sync", "message": "Frame-review window opened"}
            raise IntegrationBlocked("Unknown native tool action")
