"""T6 loopback-only, authenticated static UI + constrained KineLab workflow API.

No cloud, generic file server, arbitrary shell execution, CORS permissions
or user-supplied filesystem paths. Browser fetches use an ephemeral bearer token.
All writes delegate to the existing tested session/capture/workflow guards.
"""
from __future__ import annotations

import argparse
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
from threading import Lock
import traceback
from urllib.parse import unquote, urlsplit, parse_qs
from uuid import uuid4

from t6_service import IntegratedService, IntegrationBlocked, CALISCOPE, ROOT

DIST = ROOT / "viewer" / "dist"
SAMPLES = ROOT / "projects" / CALISCOPE / "external-source"
MAX_JSON = 64 * 1024
MAX_UPLOAD = 1024 * 1024 * 1024  # Maximum 1 GiB; no implicit data redirection.
AUTH_PREFIX = "Bearer "
ALLOWED_SAMPLE_ROOTS = {"gait-t5", "pose2d-fullseq"}
ALLOWED_SAMPLE_TYPES = {".html", ".json", ".csv", ".mp4", ".png", ".jpg", ".jpeg"}


def make_server(service: IntegratedService, *, token: str, dist: Path = DIST,
                samples: Path = SAMPLES, port: int = 0) -> ThreadingHTTPServer:
    if not isinstance(token, str) or len(token) < 40:
        raise ValueError("Strong local session access token required")
    dist = Path(dist).resolve()
    samples = Path(samples).resolve()
    if not (dist / "index.html").is_file():
        raise FileNotFoundError("Built React UI unavailable; run npm build first")
    class Handler(BaseHTTPRequestHandler):
        server_version = "KineLabT6/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, _format, *args):
            # Never log bearer tokens or user-provided filenames.
            return

        def _header(self, code: int, mime: str, length: int, extra: dict | None = None):
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
            self.wfile.write(data)

        def _error(self, code: int, message: str):
            self._json(code, {"error": message, "ok": False})

        def _check_host(self) -> bool:
            target = f"127.0.0.1:{self.server.server_port}"
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
            if origin and origin != f"http://127.0.0.1:{self.server.server_port}":
                self._error(403, "Cross-origin actions are not permitted")
                return False
            if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
                self._error(403, "Cross-site requests are not accepted")
                return False
            return True

        def _body(self) -> dict:
            if self.headers.get("Transfer-Encoding"):
                raise IntegrationBlocked("Chunked request bodies not accepted")
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError as error:
                raise IntegrationBlocked("Invalid Content-Length") from error
            if length < 0:
                raise IntegrationBlocked("Content-Length required")
            if length > MAX_JSON:
                try:
                    self.rfile.read(min(length, 256 * 1024))
                except Exception:
                    pass
                raise OverflowError("JSON body too large")
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise TypeError("JSON request required")
            try:
                obj = json.loads(self.rfile.read(length))
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
                       request_path == "/favicon.ico")
            if not allowed:
                raise FileNotFoundError("Unknown app asset")
            candidate = (dist / unquote(request_path.lstrip("/"))).resolve()
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
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_OPTIONS(self):
            if not self._check_host():
                return
            self._error(405, "Cross-origin preflights not supported")

        def do_GET(self):
            if not self._check_host():
                return
            url = urlsplit(self.path)
            path = url.path
            if not path.startswith("/api/v1/"):
                try:
                    static, sample = self._safe_static(path)
                    self._file(static, sample=sample)
                except (OSError, ValueError, FileNotFoundError):
                    self._error(404, "Static file not available")
                return
            if not self._authorized():
                return
            parts = [unquote(v) for v in path.strip("/").split("/")]
            try:
                if path == "/api/v1/health":
                    self._json(200, {"name": "KineLab PT", "app": "unified_t6",
                                     "version": "t6", "local_only": True,
                                     "clinical_accuracy_verified": False})
                elif path == "/api/v1/sessions":
                    self._json(200, {"sessions": service.sessions()})
                elif path == "/api/v1/analysis":
                    self._json(200, service.analysis())
                elif path == "/api/v1/backups":
                    self._json(200, {"backups": service.backups()})
                elif parts == ["api", "v1", "compare"]:
                    params = parse_qs(url.query)
                    s1 = params.get("s1", [None])[0]
                    s2 = params.get("s2", [None])[0]
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
                    elif action == "recovery":
                        self._json(200, service.recovery(ident))
                    else:
                        self._error(404, "Unknown session API")
                elif len(parts) >= 6 and parts[:3] == ["api", "v1", "sessions"] and parts[4] == "artifact":
                    file_key = "/".join(parts[5:])
                    self._file(service.artifact(parts[3], file_key), download=True)
                else:
                    self._error(404, "Unknown API endpoint")
            except (ValueError, FileNotFoundError, OSError) as err:
                self._error(409, str(err))

        def _upload(self, session: str, role: str):
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
            if parts[:3] != ["api", "v1", "sessions"] and parts[:3] != ["api", "v1", "backup"] and parts[:3] != ["api", "v1", "system"]:
                self._error(404, "Unknown API route")
                return
            try:
                if len(parts) == 6 and parts[4] == "import":
                    self._json(201, self._upload(parts[3], parts[5]))
                    return
                data = self._body()
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
                if parts == ["api", "v1", "backup", "create"]:
                    self._json(201, service.create_backup(confirm=confirmed, session_ids=data.get("session_ids")))
                    return
                if parts == ["api", "v1", "backup", "restore"]:
                    self._json(200, service.restore_backup(data.get("backup_name"), confirm=confirmed, overwrite=data.get("overwrite", False)))
                    return
                if len(parts) == 3 and parts[:3] == ["api", "v1", "sessions"]:
                    self._json(201, service.create_session(data.get("id"), kind=data.get("kind", "real")))
                    return
                if len(parts) == 6 and parts[4] == "reports" and parts[5] == "generate":
                    self._json(201, service.generate_reports(parts[3], confirm=confirmed))
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
            except OverflowError as err:
                self._error(413, str(err))
            except TypeError as err:
                self._error(415, str(err))
            except (FileExistsError, IntegrationBlocked, ValueError, OSError) as err:
                self._error(409, str(err))
            except Exception as exc:
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                sys.stderr.write(f"[{now}] ERROR in {self.command} {self.path}: {exc}\n")
                traceback.print_exc(file=sys.stderr)
                sys.stderr.flush()
                # Do not expose filesystem data or tracebacks over HTTP.
                self._error(500, "Unexpected local API error; inspect the local application log")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="KineLab PT unified local-only server")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()

    local_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "KineLabPT"
    local_dir.mkdir(parents=True, exist_ok=True)
    log_file = (local_dir / "t6-server.log").open("a", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file

    doc = json.loads(args.state.read_text(encoding="utf-8-sig"))
    if (not isinstance(doc, dict) or doc.get("port") != args.port or
            not isinstance(doc.get("token"), str) or len(doc["token"]) < 40):
        raise ValueError("Unified local server state mismatch")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    log_file.write(f"\n[{now}] KineLab PT server starting on 127.0.0.1:{args.port}\n")
    log_file.flush()

    server = make_server(IntegratedService(), token=doc["token"], port=args.port)
    try:
        server.serve_forever(poll_interval=0.5)
    except Exception as exc:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        log_file.write(f"[{now}] Server fatal exception: {exc}\n")
        traceback.print_exc(file=log_file)
        log_file.flush()
    finally:
        server.server_close()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        log_file.write(f"[{now}] KineLab PT server stopped cleanly.\n")
        log_file.flush()


if __name__ == "__main__":
    main()
