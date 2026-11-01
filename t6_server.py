"""T6 loopback-only, authenticated static UI + constrained KineLab workflow API.

No cloud, generic file server, arbitrary shell execution, CORS permissions
or user-supplied filesystem paths. Browser fetches use an ephemeral bearer token.
All writes delegate to the existing tested session/capture/workflow guards.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer as _ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from backup_manager import BackupConflictError
from capture_station import PARTICIPANT_RECORDING_BLOCKED
from local_diagnostics import log_local_failure
from runtime_config import ensure_data_root, ensure_directory, is_reparse, runtime_identity
from session_contract import strict_json_loads
from t6_service import CALISCOPE, ROOT, IntegratedService, IntegrationBlocked

DIST = ROOT / "viewer" / "dist"
SAMPLES = ROOT / "projects" / CALISCOPE / "external-source"
MAX_JSON = 64 * 1024
logger = logging.getLogger(__name__)
MAX_UPLOAD = 1024 * 1024 * 1024  # Maximum 1 GiB; no implicit data redirection.
AUTH_PREFIX = "Bearer "
ALLOWED_SAMPLE_ROOTS = {"gait-t5", "pose2d-fullseq"}
ALLOWED_SAMPLE_TYPES = {".html", ".json", ".csv", ".mp4", ".png", ".jpg", ".jpeg"}
_PEER_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


class _ResponseDisconnected(Exception):
    """The response socket closed; do not attempt another HTTP response."""


class ThreadingHTTPServer(_ThreadingHTTPServer):
    """Keep stdlib request failures inside the fixed-label diagnostics boundary."""

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if error is not None:
            log_local_failure(logger, logging.ERROR, "local_request_handler_failed", error)


class _OwnedServiceHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    owned_service: IntegratedService | None = None

    def server_close(self):
        try:
            super().server_close()
        finally:
            service = self.owned_service
            if service is not None:
                self.owned_service = None
                service.close()


def make_server(service: IntegratedService, *, token: str, dist: Path = DIST,
                samples: Path = SAMPLES, port: int = 0, owns_service: bool = False) -> ThreadingHTTPServer:
    if not isinstance(token, str) or len(token) < 40:
        raise ValueError("Strong local session access token required")
    dist = Path(dist).resolve()
    samples = Path(samples).resolve()
    if not (dist / "index.html").is_file():
        raise FileNotFoundError("Built React UI unavailable; run npm build first")
    class Handler(BaseHTTPRequestHandler):
        server_version = "KineLabT6/1"
        protocol_version = "HTTP/1.1"

        def handle_one_request(self):
            try:
                super().handle_one_request()
            except _ResponseDisconnected:
                self.close_connection = True

        def flush_headers(self):
            try:
                super().flush_headers()
            except _PEER_DISCONNECT_ERRORS as error:
                raise _ResponseDisconnected from error

        def _write_response(self, data):
            try:
                self.wfile.write(data)
            except _PEER_DISCONNECT_ERRORS as error:
                raise _ResponseDisconnected from error

        def log_message(self, _format, *args):
            # Never log bearer tokens or user-provided filenames.
            return

        def _header(self, code: int, mime: str, length: int, extra: dict | None = None):
            self._response_started = True
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.close_connection = True
            if extra:
                for k, v in extra.items():
                    self.send_header(k, v)
            self.end_headers()

        def _json(self, code: int, item):
            data = json.dumps(item, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
            self._header(code, "application/json; charset=utf-8", len(data))
            self._write_response(data)

        def _error(self, code: int, message: str):
            self._json(code, {"error": message, "ok": False})

        def _port(self) -> int:
            return cast(ThreadingHTTPServer, self.server).server_port

        def _check_host(self) -> bool:
            target = f"127.0.0.1:{self._port()}"
            if self.headers.get("Host", "") != target:
                self._error(400, "Only this application's loopback address is allowed")
                return False
            return True

        def _authorized(self) -> bool:
            sent = self.headers.get("Authorization", "")
            if not secrets.compare_digest(sent, AUTH_PREFIX + token):
                self._error(401, "Local app authorization token missing or invalid")
                return False
            origin = self.headers.get("Origin")
            if origin and origin != f"http://127.0.0.1:{self._port()}":
                self._error(403, "Cross-origin actions are not permitted")
                return False
            if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
                self._error(403, "Cross-site requests are not accepted")
                return False
            return True

        def _body(self, *, drain_oversize: bool = True) -> dict:
            if self.headers.get("Transfer-Encoding"):
                raise IntegrationBlocked("Chunked request bodies not accepted")
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError as error:
                raise IntegrationBlocked("Invalid Content-Length") from error
            if length < 0:
                raise IntegrationBlocked("Content-Length required")
            if length > MAX_JSON:
                if drain_oversize:
                    try:
                        self.rfile.read(min(length, 256 * 1024))
                    except OSError as error:
                        log_local_failure(logger, logging.WARNING, "oversize_body_drain_failed", error)
                raise OverflowError("JSON body too large")
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise TypeError("JSON request required")
            try:
                obj = strict_json_loads(self.rfile.read(length))
            except (ValueError, UnicodeError) as error:
                raise IntegrationBlocked("Invalid JSON document") from error
            if not isinstance(obj, dict):
                raise IntegrationBlocked("JSON payload must be an object")
            return obj

        def _safe_static(self, request_path: str) -> tuple[Path, bool]:
            if request_path == "/":
                return dist / "index.html", False
            if request_path.startswith("/samples/"):
                if not (samples.parent / "TEST-ONLY-NOT-CALIBRATED.txt").is_file():
                    raise FileNotFoundError("External research sample must be TEST ONLY")
                relative = Path(unquote(request_path[len("/samples/"):]))
                if not relative.parts or relative.parts[0] not in ALLOWED_SAMPLE_ROOTS:
                    raise FileNotFoundError("Unknown public test file")
                source = (samples / relative).resolve()
                if not source.is_relative_to(samples) or source.is_symlink() or source.suffix.lower() not in ALLOWED_SAMPLE_TYPES:
                    raise FileNotFoundError("Test file access refused")
                return source, True
            allowed = (request_path.startswith("/assets/") or
                       request_path == "/motion/demo.motion.json" or
                       request_path in ("/favicon.ico", "/favicon.svg"))
            if not allowed:
                raise FileNotFoundError("Unknown app asset")
            relative = Path(unquote(request_path.lstrip("/")))
            if ".." in relative.parts:
                raise FileNotFoundError("Asset path traversal refused")
            candidate = (dist / relative).resolve()
            if not candidate.is_relative_to(dist) or candidate.is_symlink():
                raise FileNotFoundError("Asset cannot escape app bundle")
            return candidate, False

        def _file(self, file: Path, *, sample: bool = False, download: bool = False):
            if not file.is_file():
                raise FileNotFoundError("Local asset not found")
            size = file.stat().st_size
            mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if file.suffix.lower() == ".js":
                mime = "text/javascript"
            elif file.suffix.lower() == ".mp4":
                mime = "video/mp4"
            elif file.suffix.lower() == ".json":
                mime = "application/json"
            elif file.suffix.lower() == ".pdf":
                mime = "application/pdf"
            elif file.suffix.lower() == ".csv":
                mime = "text/csv; charset=utf-8"
            mime += "; charset=utf-8" if mime.startswith(("text/", "application/json")) else ""
            extras = {"Accept-Ranges": "bytes"}
            if download:
                extras["Content-Disposition"] = f'attachment; filename="{file.name}"'
            if mime.startswith("text/html"):
                extras["Content-Security-Policy"] = (
                    "default-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'; "
                    "connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
                    "frame-src 'self'; script-src 'self'" + (" 'unsafe-inline'" if sample else "") +
                    "; style-src 'self' 'unsafe-inline'"
                )
            range_header = self.headers.get("Range")
            first, last = 0, size - 1
            status = 200
            if range_header:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header.strip())
                if match is None:
                    self._header(416, mime, 0, {"Content-Range": f"bytes */{size}"})
                    return
                first = int(match.group(1))
                last = int(match.group(2)) if match.group(2) else size - 1
                if first >= size or last < first:
                    self._header(416, mime, 0, {"Content-Range": f"bytes */{size}"})
                    return
                last = min(last, size - 1)
                status = 206
                extras["Content-Range"] = f"bytes {first}-{last}/{size}"
            length = max(0, last - first + 1)
            self._header(status, mime, length, extras)
            with file.open("rb") as stream:
                stream.seek(first)
                remaining = length
                while remaining:
                    chunk = stream.read(min(128 * 1024, remaining))
                    if not chunk:
                        break
                    self._write_response(chunk)
                    remaining -= len(chunk)

        def do_OPTIONS(self):
            if not self._check_host():
                return
            self._error(405, "Cross-origin preflights not supported")

        def do_GET(self):
            self._response_started = False
            if not self._check_host():
                return
            url = urlsplit(self.path)
            path = url.path
            if not path.startswith("/api/v1/"):
                try:
                    static, sample = self._safe_static(path)
                    self._file(static, sample=sample)
                except (OSError, ValueError, FileNotFoundError) as error:
                    if self._response_started:
                        self.close_connection = True
                        log_local_failure(logger, logging.ERROR, "unexpected_local_get_error", error)
                    else:
                        self._error(404, "Static file not available")
                except _ResponseDisconnected:
                    self.close_connection = True
                    return
                except Exception as error:  # noqa: BLE001 - Keep private failures inside the static boundary.
                    log_local_failure(logger, logging.ERROR, "unexpected_local_get_error", error)
                    self.close_connection = True
                    if not self._response_started:
                        self._error(500, "Unexpected local request error; inspect the local application log")
                return
            if not self._authorized():
                return
            parts = [unquote(v) for v in path.strip("/").split("/")]
            try:
                if path == "/api/v1/health":
                    self._json(200, {"name": "KineLab PT", "app": "unified_t6",
                                     "version": "t6", "local_only": True, "runtime_id": getattr(service, "runtime_id", None),
                                     "clinical_accuracy_verified": False})
                elif path == "/api/v1/sessions":
                    self._json(200, {"sessions": service.sessions()})
                elif parts == ["api", "v1", "recordings"]:
                    self._json(200, {"recordings": service.recordings.list_recordings()})
                elif len(parts) == 4 and parts[:3] == ["api", "v1", "recordings"]:
                    self._json(200, service.recordings.verify(parts[3]))
                elif path == "/api/v1/analysis":
                    self._json(200, service.analysis())
                elif path == "/api/v1/backup/schedule":
                    self._json(200, service.backup_schedule_status())
                elif path == "/api/v1/backups":
                    self._json(200, {"backups": service.backups()})
                elif parts == ["api", "v1", "exercises", "presets"] or path == "/api/v1/exercises/presets":
                    self._json(200, service.get_exercise_presets())
                elif parts == ["api", "v1", "compare"]:
                    params = parse_qs(url.query, keep_blank_values=True)
                    s1 = params.get("s1", [None])[0]
                    s2 = params.get("s2", [None])[0]
                    names = ("expected_metadata_context_s1", "expected_metadata_context_s2")
                    if any(name in params for name in names):
                        if any(name not in params or len(params[name]) != 1
                               or re.fullmatch(r"[0-9a-f]{64}", params[name][0]) is None
                               for name in names):
                            raise IntegrationBlocked("METADATA_CONTEXT_INVALID: paired SHA256 contexts required")
                        self._json(200, service.compare(
                            s1, s2, expected_metadata_context_s1=params[names[0]][0],
                            expected_metadata_context_s2=params[names[1]][0]))
                    else:
                        self._json(200, service.compare(s1, s2))
                elif len(parts) == 4 and parts[:3] == ["api", "v1", "sessions"]:
                    self._json(200, service.session_detail(parts[3]))
                elif len(parts) == 5 and parts[:3] == ["api", "v1", "sessions"]:
                    ident, action = parts[3], parts[4]
                    if action == "processing":
                        self._json(200, service.processing_status(ident))
                    elif action == "capture":
                        self._json(200, service.camera_status(ident))
                    elif action == "passport":
                        self._json(200, service.passport(ident))
                    elif action == "motion":
                        self._json(200, service.motion_data(ident))
                    elif action == "reports":
                        self._json(200, {"reports": service.reports(ident)})
                    elif action == "report-context":
                        self._json(200, service.report_context(ident))
                    elif action == "recovery":
                        self._json(200, service.recovery(ident))
                    elif action in ("manual-assessment-context", "manual-assessments"):
                        self._json(200, service.manual_assessment_context(ident))
                    else:
                        self._error(404, "Unknown session API")
                elif (len(parts) in (6, 7) and parts[:3] == ["api", "v1", "sessions"]
                      and parts[4] == "evidence-exports"):
                    if len(parts) == 6:
                        self._json(200, service.evidence_export_receipt(parts[3], parts[5]))
                    elif parts[6] == "artifact":
                        payload = service.evidence_export_artifact(parts[3], parts[5])
                        self._header(200, "application/zip", len(payload),
                                     {"Content-Disposition": 'attachment; filename="evidence.zip"'})
                        self._write_response(payload)
                    else:
                        self._error(404, "Unknown evidence export API")
                elif len(parts) >= 6 and parts[:3] == ["api", "v1", "sessions"] and parts[4] == "artifact":
                    file_key = "/".join(parts[5:])
                    self._file(service.artifact(parts[3], file_key), download=True)
                else:
                    self._error(404, "Unknown API endpoint")
            except sqlite3.Error:
                self._error(503, "STORAGE_UNAVAILABLE: no saved acknowledgment; retain the draft and retry")
            except _ResponseDisconnected:
                raise
            except OSError as error:
                log_local_failure(logger, logging.WARNING, "local_get_storage_error", error)
                self._error(409, "LOCAL_STORAGE_ERROR: local file operation failed; inspect the local application log")
            except ValueError as err:
                self._error(409, str(err))
            except Exception as error:  # noqa: BLE001 - Keep private failures inside the API boundary.
                log_local_failure(logger, logging.ERROR, "unexpected_local_get_error", error)
                self._error(500, "Unexpected local API error; inspect the local application log")

        def _upload(self, session: str, role: str):
            # Refuse before the session lookup and before import-staging/ is created.
            if role == "cam01_trial":
                raise IntegrationBlocked(PARTICIPANT_RECORDING_BLOCKED)
            if self.headers.get("X-KineLab-Consent", "") != "yes":
                raise IntegrationBlocked("Explicit phone import consent header required")
            if self.headers.get("Content-Type", "").split(";")[0] != "video/mp4":
                raise TypeError("Only original MP4 upload accepted")
            if self.headers.get("Transfer-Encoding"):
                raise IntegrationBlocked("Chunked upload bodies not accepted")
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError as error:
                raise IntegrationBlocked("Invalid MP4 body length") from error
            if length < 1:
                raise IntegrationBlocked("No file uploaded")
            if length > MAX_UPLOAD:
                raise OverflowError("Local phone MP4 exceeds 1 GiB limit")
            project = service._editable(session)
            if role not in ("cam01_intrinsics", "cam01_board", "cam01_trial"):
                raise IntegrationBlocked("Only cam01 phone-role MP4s may be imported")
            target = project / "raw" / (role + ".mp4")
            if target.exists():
                raise FileExistsError("Existing phone source is immutable; start a new session or stage a retake")
            tmp_root = project / "import-staging"
            tmp_root.mkdir(exist_ok=True)
            if tmp_root.is_symlink() or not tmp_root.resolve().is_relative_to(project):
                raise IntegrationBlocked("Import staging must remain in this session")
            tmp = tmp_root / ("phone-" + uuid4().hex + ".mp4")
            try:
                with tmp.open("xb") as stream:
                    remaining = length
                    while remaining > 0:
                        data = self.rfile.read(min(1024 * 1024, remaining))
                        if not data:
                            raise IntegrationBlocked("Incomplete phone file; source is not published")
                        stream.write(data)
                        remaining -= len(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                imported = service.import_phone(session, role, tmp, confirm=True)
                return {"filename": imported.name, "role": role,
                        "state": "imported", "original_preserved": True,
                        "clinical_accuracy_verified": False}
            finally:
                tmp.unlink(missing_ok=True)

        def do_POST(self):
            if not self._check_host() or not self._authorized():
                return
            parts = [unquote(v) for v in urlsplit(self.path).path.strip("/").split("/")]
            if parts[:3] not in (["api", "v1", "sessions"], ["api", "v1", "backup"], ["api", "v1", "system"], ["api", "v1", "recordings"], ["api", "v1", "inference"]):
                self._error(404, "Unknown API route")
                return
            try:
                if len(parts) == 6 and parts[4] == "import":
                    self._json(201, self._upload(parts[3], parts[5]))
                    return
                if (len(parts) == 5 and parts[:3] == ["api", "v1", "sessions"]
                        and parts[4] == "manual-assessments"):
                    data = self._body(drain_oversize=False)
                    self._json(200, service.publish_manual_assessment_entry(parts[3], data))
                    return
                if (len(parts) == 5 and parts[:3] == ["api", "v1", "sessions"]
                        and parts[4] == "metadata-revisions"):
                    data = self._body(drain_oversize=False)
                    self._json(200, service.publish_metadata_revision(parts[3], data))
                    return
                data = self._body()
                if parts[:3] == ["api", "v1", "inference"]:
                    if parts == ["api", "v1", "inference", "frame"]:
                        self._json(200, service.pose_inference.infer(data))
                    else:
                        self._error(404, "Unknown inference API")
                    return
                if parts[:3] == ["api", "v1", "recordings"]:
                    if len(parts) == 3:
                        self._json(201, service.recordings.create(data))
                    elif len(parts) == 5 and parts[4] == "chunks":
                        self._json(200, service.recordings.append(parts[3], data))
                    elif len(parts) == 5 and parts[4] == "finalize":
                        if set(data) not in ({"operation_id", "last_sequence"}, {"operation_id", "last_sequence", "end_reason"}):
                            raise ValueError("MEASUREMENT_INVALID: finalization envelope")
                        self._json(200, service.recordings.finalize(parts[3], data["operation_id"], data["last_sequence"],
                            end_reason=data.get("end_reason", "operator_finished")))
                    else:
                        self._error(404, "Unknown recording API")
                    return
                confirmed = data.get("confirm") is True
                if parts == ["api", "v1", "system", "shutdown"]:
                    if not confirmed:
                        self._error(400, "Confirmation required for system shutdown")
                        return
                    self._json(200, {"status": "shutting_down", "message": "KineLab local server is shutting down."})
                    server_ref = self.server
                    def _delayed_shutdown():
                        import time
                        time.sleep(0.3)
                        server_ref.shutdown()
                    threading.Thread(target=_delayed_shutdown, daemon=True).start()
                    return
                if parts == ["api", "v1", "backup", "schedule"]:
                    from backup_schedule import BackupScheduleError
                    try:
                        self._json(200, service.configure_backup_schedule(data))
                    except BackupScheduleError as error:
                        self._error(409 if "POLICY_REQUIRED" in str(error) else 400, str(error))
                    return
                if parts == ["api", "v1", "backup", "prune"]:
                    from backup_schedule import BackupScheduleError
                    if set(data) != {"confirm"} or type(data["confirm"]) is not bool:
                        self._error(400, "BACKUP_PRUNING_REQUEST_INVALID")
                        return
                    try:
                        service.prune_backups()
                    except BackupScheduleError as error:
                        self._error(409, str(error))
                    return
                if parts == ["api", "v1", "backup", "create"]:
                    self._json(201, service.create_backup(confirm=confirmed, session_ids=data.get("session_ids")))
                    return
                if parts == ["api", "v1", "backup", "restore"]:
                    self._json(200, service.restore_backup(data.get("backup_name"), confirm=confirmed, overwrite=data.get("overwrite", False)))
                    return
                if len(parts) == 3 and parts[:3] == ["api", "v1", "sessions"]:
                    self._json(201, service.create_session(data.get("id"), kind=data.get("kind", "real"), metadata=data.get("metadata")))
                    return
                if parts == ["api", "v1", "sessions", "live-set"]:
                    self._json(201, service.save_live_session(data))
                    return
                if len(parts) == 5 and parts[:3] == ["api", "v1", "sessions"] and parts[4] == "evidence-exports":
                    from evidence_export import ExportRequestError, validate_request
                    try:
                        validated = validate_request(data)
                    except ExportRequestError as error:
                        self._error(400, str(error))
                        return
                    self._json(201, service.create_evidence_export(parts[3], validated))
                    return
                if len(parts) == 6 and parts[4] == "reports" and parts[5] == "generate":
                    cas_fields = {"expected_report_head", "expected_report_context_sha256"}
                    if set(data) not in ({"confirm"}, {"confirm"} | cas_fields) or not confirmed:
                        self._error(400, "REPORT_REQUEST_INVALID: exact confirmed report envelope required")
                        return
                    cas = {}
                    if cas_fields <= set(data):
                        head = data["expected_report_head"]
                        context = data["expected_report_context_sha256"]
                        valid_head = head is None or (
                            isinstance(head, dict) and set(head) == {"generation", "manifest_sha256"}
                            and isinstance(head["generation"], str)
                            and re.fullmatch(r"report-[0-9a-f]{32}", head["generation"]) is not None
                            and isinstance(head["manifest_sha256"], str)
                            and re.fullmatch(r"[0-9a-f]{64}", head["manifest_sha256"]) is not None)
                        if (not valid_head or not isinstance(context, str)
                                or re.fullmatch(r"[0-9a-f]{64}", context) is None):
                            self._error(400, "REPORT_REQUEST_INVALID: exact head and SHA256 context required")
                            return
                        cas = {name: data[name] for name in cas_fields}
                    self._json(201, service.generate_reports(parts[3], confirm=confirmed, **cas))
                    return
                if len(parts) != 5 and not (len(parts) == 6 and parts[5] in ("stop", "cancel")):
                    self._error(404, "Unknown action")
                    return
                sid, action = parts[3], parts[4]
                if len(parts) == 6 and action == "capture" and parts[5] == "stop":
                    result = service.stop_webcam(sid, confirm=confirmed)
                elif len(parts) == 6 and action == "processing" and parts[5] == "cancel":
                    result = service.cancel_processing(sid, confirm=confirmed)
                elif len(parts) != 5:
                    self._error(404, "Unknown action")
                    return
                elif action == "register":
                    result = service.register(sid, confirm=confirmed)
                elif action == "board":
                    result = service.measure_board(sid, data.get("mm"), data.get("operator"),
                                                   confirm=confirmed)
                elif action == "capture":
                    result = service.record_webcam(sid, data.get("role"),
                                                   seconds=data.get("seconds"), confirm=confirmed)
                elif action == "processing":
                    result = service.start_processing(sid, data.get("action"), confirm=confirmed)
                elif action == "open":
                    result = service.open_native(sid, data.get("target"), confirm=confirmed)
                else:
                    self._error(404, "Unknown session action")
                    return
                self._json(200, result)
            except _ResponseDisconnected:
                raise
            except OverflowError as err:
                self._error(413, str(err))
            except TypeError as err:
                self._error(415, str(err))
            except sqlite3.Error:
                self._error(503, "STORAGE_UNAVAILABLE: no saved acknowledgment; retain the draft and retry")
            except OSError as error:
                log_local_failure(logger, logging.WARNING, "local_post_storage_error", error)
                message = "LOCAL_STORAGE_ERROR: local file operation failed; inspect the local application log"
                if type(error) is BackupConflictError and error.args == (
                    "RESTORE_OVERWRITE_UNAVAILABLE: existing sessions cannot be replaced",
                ):
                    message = "RESTORE_OVERWRITE_UNAVAILABLE: existing sessions cannot be replaced"
                self._error(409, message)
            except (IntegrationBlocked, ValueError) as err:
                self._error(409, str(err))
            except Exception as error:  # noqa: BLE001 - Preserve the API boundary with bounded privacy-safe diagnostics.
                log_local_failure(logger, logging.ERROR, "unexpected_local_api_error", error)
                # Do not expose filesystem data or tracebacks over HTTP.
                self._error(500, "Unexpected local API error; inspect the local application log")

    if owns_service:
        owned = _OwnedServiceHTTPServer(("127.0.0.1", port), Handler)
        owned.owned_service = service
        return owned
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    from t6_launcher import STATE, _remove_owned_state

    parser = argparse.ArgumentParser(description="KineLab PT unified local-only server")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()

    data_root = ensure_data_root(args.data_root)
    local_dir = ensure_directory(args.state.parent)
    if is_reparse(args.state):
        raise ValueError("Unified local server state must not be linked")
    log_file = (local_dir / "t6-server.log").open("a", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file

    doc = json.loads(args.state.read_text(encoding="utf-8-sig"))
    if (not isinstance(doc, dict) or doc.get("port") != args.port or
            not isinstance(doc.get("token"), str) or len(doc["token"]) < 40 or
            doc.get("runtime_id") != runtime_identity(data_root)):
        raise ValueError("Unified local server state mismatch")

    now = datetime.datetime.now(datetime.UTC).isoformat()
    log_file.write(f"\n[{now}] KineLab PT server starting on 127.0.0.1:{args.port}\n")
    log_file.flush()

    service = IntegratedService(projects_root=data_root)
    try:
        server = make_server(service, token=doc["token"], port=args.port, owns_service=True)
    except BaseException:
        service.close()
        raise
    try:
        server.serve_forever(poll_interval=0.5)
    except Exception as error:  # noqa: BLE001 - Preserve cleanup with bounded privacy-safe diagnostics.
        log_local_failure(logger, logging.ERROR, "local_server_failed", error)
    finally:
        server.server_close()
        try:
            if args.state == STATE:
                _remove_owned_state(doc)
        except (OSError, ValueError, TimeoutError) as error:
            log_local_failure(logger, logging.ERROR, "local_server_failed", error)
        now = datetime.datetime.now(datetime.UTC).isoformat()
        log_file.write(f"[{now}] KineLab PT server stopped.\n")
        log_file.flush()


if __name__ == "__main__":
    main()
