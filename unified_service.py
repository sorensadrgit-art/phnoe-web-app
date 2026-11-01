"""Offline KineLab PT T6 local service. No original recordings served as web assets.

Strict loopback Host, Origin, per-launch session key, endpoint allowlists.
Reuses existing capture/session/processing quality gates; not a clinical tool.
A localhost access key does not protect against other local same-user software.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import subprocess
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from capture_station import (
    PARTICIPANT_RECORDING_BLOCKED,
    RAW_ROLES,
    finalize_recording,
    import_phone_mp4,
    save_board_measurement,
)
from kinelab_hub import launch_shortcut
from session_library import SessionError, SessionLibrary
from squat_events import SquatEvidenceError, analyze_squats
from sync_evidence import SyncEvidenceError, save_sync
from workflow_controller import ACTIONS, WorkflowBlocked, WorkflowController
from workflow_recovery import inspect_recovery

ROOT=Path(__file__).resolve().parent
DIST=ROOT/"viewer"/"dist"
PROJECTS=ROOT/"projects"
SAMPLES=PROJECTS/"caliscope-walking-test-20261027"/"external-source"
JSON_LIMIT=25*1024*1024
UPLOAD_LIMIT=220*1024*1024
REPORT_FILES={"session.json","session-template.json","preflight.json","normalization.json",
              "run.json","sync.json","sync-observations.json","board-measurement.json"}
GUIDES={"runbook":"RUNBOOK.md","capture":"CAPTURE-NOW.md",
        "t1":"V1-T1-RESULTS.md","t2":"V1-T2-RESULTS.md","t3":"V1-T3-RESULTS.md",
        "t4":"V1-T4-RESULTS.md","t5":"V1-T5-RESULTS.md",
        "squat":"V1-T5-SQUAT-ADDENDUM.md","desktop":"DESKTOP-ONE-ICON-RESULTS.md"}
RESEARCH={
 "gait-t5":{"index.html","gait-t5-summary.json","cam01_trial_gait_candidates.json",
            "cam02_trial_gait_candidates.json"},
 "pose2d-fullseq":{"index.html","cam01_trial_tracked.mp4","cam02_trial_tracked.mp4",
                   "cam01_trial_frame_metrics.csv","cam02_trial_frame_metrics.csv",
                   "cam01_trial_keypoints_2d.json","cam02_trial_keypoints_2d.json",
                   "full-sequence-report.json","two-camera-tracking-contact-sheet.jpg"},
}
MIME={".js":"text/javascript",".css":"text/css",".html":"text/html; charset=utf-8",
      ".json":"application/json; charset=utf-8",".mp4":"video/mp4",".png":"image/png",
      ".jpg":"image/jpeg",".svg":"image/svg+xml"}


class AppError(ValueError):
    def __init__(self,message,status=400):
        super().__init__(message)
        self.status=status


class WorkflowJobJournal:
    """Append-only observations, never authority to adopt or replay a process.

    Each exclusive numbered event is flushed before acknowledgement. A partial
    event is retained and blocks further starts; no in-place repair is attempted.
    Callers serialize their own requests; exclusive generation creation also
    rejects competing service instances. This is not a native process supervisor.
    """
    ACTIVE: ClassVar[set[str]] = {"starting", "running", "interrupted"}
    TERMINAL: ClassVar[set[str]] = {"passed", "failed", "cancelled", "cancelled-after-action"}

    def __init__(self, project, owner_id):
        self.project = Path(project)
        self.owner_id = owner_id
        self.directory = self.project / "workflow-journal"
        self.operation_id = None

    @staticmethod
    def _safe(path):
        for item in (path, *path.parents):
            try:
                info = item.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise AppError("Job recovery required: linked journal or source", 409)

    @staticmethod
    def _digest(value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _identity(self):
        identity = {}
        for name in ("Config.toml", "session.json"):
            path = self.project / name
            self._safe(path)
            if path.is_file():
                if path.stat().st_size > JSON_LIMIT:
                    raise AppError("Job recovery required: source identity exceeds limit", 409)
                identity[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return identity

    def _read(self):
        self._safe(self.directory)
        if not self.directory.exists():
            return []
        files = sorted(self.directory.iterdir())
        if len(files) > 10000 or not files:
            raise AppError("Job recovery required: incomplete journal", 409)
        events = []
        previous = None
        for generation, path in enumerate(files, 1):
            self._safe(path)
            if path.name != f"{generation:08d}.json" or not path.is_file() or path.stat().st_size > 16384:
                raise AppError("Job recovery required: journal generation gap or invalid entry", 409)
            raw = path.read_bytes()
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise AppError("Job recovery required: invalid journal entry", 409)
            digest = event.get("sha256")
            payload = {key: value for key, value in event.items() if key != "sha256"}
            canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
            if (raw != canonical or digest != self._digest(payload)
                    or event.get("schema") != "kinelab.workflow-job.v1"
                    or event.get("session_id") != self.project.name
                    or event.get("generation") != generation
                    or event.get("previous_sha256") != previous
                    or event.get("action") not in ACTIONS
                    or event.get("state") not in self.ACTIVE | self.TERMINAL
                    or not isinstance(event.get("owner_id"), str)
                    or not isinstance(event.get("operation_id"), str)
                    or len(event["operation_id"]) != 32):
                raise AppError("Job recovery required: corrupt journal identity or hash", 409)
            if events:
                prior = events[-1]
                same = event["operation_id"] == prior["operation_id"]
                if (same and (event["owner_id"] != prior["owner_id"]
                              or event["action"] != prior["action"]
                              or event["source_identity"] != prior["source_identity"]
                              or prior["state"] in self.TERMINAL)
                        or not same and (prior["state"] not in self.TERMINAL or event["state"] != "starting")):
                    raise AppError("Job recovery required: invalid operation transition", 409)
            elif event["state"] != "starting":
                raise AppError("Job recovery required: missing initial operation", 409)
            events.append(event)
            previous = digest
        if events[-1].get("source_identity") != self._identity():
            raise AppError("Job recovery required: source identity changed", 409)
        return events

    def _blocked(self, message, event=None):
        event = event or {}
        return {"state": "recovery-required", "action": event.get("action"), "passed": False,
                "message": message, "recovery_required": True, "session_id": self.project.name,
                "operation_id": event.get("operation_id"), "generation": event.get("generation"),
                "log_available": bool(event.get("log_file"))}

    def status(self):
        try:
            events = self._read()
            event = events[-1] if events else None
            locks = any((self.project / name).exists() or (self.project / name).is_symlink()
                        for name in ("workflow.lock", "run.lock"))
            if event and event["state"] in self.ACTIVE:
                return self._blocked("Job recovery required: previous work may still be running; inspect its evidence and ownership before any retry", event)
            if locks or not event and (any((self.project / name).exists() for name in
                    ("run.json", "normalization.json", "preflight.json"))
                    or any(self.project.glob("workflow-*.log"))):
                return self._blocked("Job recovery required: native evidence has no safely owned active worker", event)
            if event:
                state = "completed-unverified" if event["state"] == "passed" else event["state"]
                return {"state": state, "action": event["action"], "passed": False,
                        "message": "Recorded prior outcome; artifacts have not been revalidated in this instance",
                        "recovery_required": False, "operation_id": event["operation_id"],
                        "session_id": self.project.name, "generation": event["generation"],
                        "log_available": bool(event.get("log_file"))}
            return {"state": "idle", "action": None, "passed": False,
                    "message": "No recorded operation or native evidence", "recovery_required": False,
                    "operation_id": None, "session_id": self.project.name, "generation": 0}
        except (OSError, ValueError, KeyError, TypeError) as error:
            # Do not expose exception paths or silently repair malformed history.
            message = str(error) if isinstance(error, AppError) else "Job recovery required: unreadable or corrupt journal"
            return self._blocked(message)

    def _append(self, action, state, operation_id, *, log_file=None):
        events = self._read()
        prior = events[-1] if events else None
        if state == "starting" and prior and prior["state"] not in self.TERMINAL:
            raise AppError("Job recovery required: another operation already owns this generation", 409)
        if state != "starting" and (not prior or prior["operation_id"] != operation_id
                or prior["owner_id"] != self.owner_id or prior["state"] in self.TERMINAL):
            raise AppError("Job recovery required: operation ownership changed", 409)
        event = {"schema": "kinelab.workflow-job.v1", "generation": len(events) + 1,
                 "previous_sha256": prior["sha256"] if prior else None,
                 "session_id": self.project.name, "operation_id": operation_id,
                 "owner_id": self.owner_id, "action": action, "state": state,
                 "source_identity": self._identity(), "log_file": log_file,
                 "recorded_at": datetime.now(UTC).isoformat()}
        event["sha256"] = self._digest(event)
        self._safe(self.directory)
        self.directory.mkdir(exist_ok=True)
        path = self.directory / f"{event['generation']:08d}.json"
        with path.open("xb") as stream:
            stream.write(json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        return event

    def begin(self, action):
        state = self.status()
        if state["recovery_required"]:
            raise AppError(state["message"], 409)
        if action not in ACTIONS:
            raise AppError("Unknown workflow action", 400)
        operation_id = uuid4().hex
        event = self._append(action, "starting", operation_id)
        self.operation_id = operation_id
        return event

    def observe(self, status):
        events = self._read()
        event = events[-1] if events else None
        if (not event or event["operation_id"] != self.operation_id
                or event["owner_id"] != self.owner_id or status.action != event["action"]
                or status.state not in self.ACTIVE | self.TERMINAL):
            raise AppError("Job recovery required: observation does not own this operation", 409)
        if event["state"] == "interrupted":
            return self._blocked("Job recovery required: owner declared interruption", event)
        if event["state"] != status.state:
            event = self._append(status.action, status.state, self.operation_id,
                                 log_file=status.log_path.name if status.log_path else None)
        return {"state": status.state, "action": status.action, "passed": status.passed,
                "message": status.message, "log_available": bool(status.log_path),
                "operation_id": event["operation_id"], "session_id": self.project.name,
                "generation": event["generation"], "recovery_required": False}

    def interrupt(self):
        events = self._read()
        event = events[-1] if events else None
        if (event and event["operation_id"] == self.operation_id
                and event["owner_id"] == self.owner_id and event["state"] in {"starting", "running"}):
            self._append(event["action"], "interrupted", self.operation_id, log_file=event.get("log_file"))
        return self.status()


def _safe_session(item):
    return {k:item[k] for k in
            ("id","kind","status","captured_roles","total_roles","can_register","has_board_measurement")
            if k in item}


def _contained(root,path):
    if path.is_symlink():
        raise AppError("Symlinked resources are not exposed",403)
    result=path.resolve()
    if not result.is_relative_to(root.resolve()):
        raise AppError("Resource outside the approved local folder",403)
    return result


class AppCore:
    def __init__(self,projects_root=PROJECTS,dist=DIST,samples=SAMPLES,*,token=None):
        self.library=SessionLibrary(Path(projects_root))
        self.dist=Path(dist).resolve()
        self.samples=Path(samples).resolve()
        self.token=token or secrets.token_urlsafe(32)
        self.mutex=threading.RLock()
        self.jobs={}
        self.job_journals={}
        self.instance_id=uuid4().hex
        self.recording=None

    def session(self,id):
        return self.library.open_session(id)

    def editable(self,id):
        return self.library._require_editable(id)

    def sessions(self):
        with self.mutex:
            return {"sessions":[_safe_session(s) for s in self.library.list_sessions()]}

    def detail(self,id):
        with self.mutex:
            path=self.session(id)
            record=_safe_session(self.library.describe_session(id))
            record["roles"]={role:{"present":(path/"raw"/(role+".mp4")).is_file()}
                             for role in RAW_ROLES}
            record["artifacts"]={
                key:(path/name).is_file() for key,name in (
                 ("registration","session.json"),("preflight","preflight.json"),
                 ("normalization","normalization.json"),("observed_cues","sync-observations.json"),
                 ("native_sync","sync.json"),("native_run","run.json"))
            }
            record["warning"]="Source file presence is not physical calibration or clinical accuracy."
            return {"detail":record}

    def readiness(self,id):
        with self.mutex:
            data=self.library.registration_readiness(id)
            data.pop("session",None)
            return {"readiness":data}

    def create(self,id):
        with self.mutex:
            created=self.library.create_session(id,kind="real")
            return {"session":_safe_session(self.library.describe_session(created.name))}

    def register(self,id,confirmed):
        if confirmed is not True:raise AppError("Explicit registration approval required",409)
        with self.mutex:
            self.library.register_session(id)
            return {"session":_safe_session(self.library.describe_session(id)),
                    "message":"Input identity registered. No 3D or clinical accuracy verification."}

    def board(self,id,mm,operator,confirmed):
        if confirmed is not True:raise AppError("Confirm physically measuring the board with a ruler",409)
        with self.mutex:
            record=save_board_measurement(self.editable(id),mm,operator)
            return {"board":{"measured_square_mm":record["measured_square_mm"],
                             "source":record["source"]}}

    def reports(self,id):
        with self.mutex:
            path=self.session(id)
            files=sorted(n for n in REPORT_FILES if
                         (path/n).is_file() and not (path/n).is_symlink())
            exports=path/"exports"
            if exports.is_dir() and not exports.is_symlink():
                files.extend("exports/"+f.name for f in exports.glob("*.motion.json")
                             if f.is_file() and not f.is_symlink())
            return {"files":files,"pdf_report_ready":False,
                    "notice":"A clinical-style PDF report has not been built; T7 remains pending."}

    def report(self,id,name):
        with self.mutex:
            path=self.session(id)
            if name not in REPORT_FILES and not(name.startswith("exports/") and name.endswith(".motion.json")
                    and name.count("/")==1 and
                    name.split("/")[-1].replace(".","").replace("_","").replace("-","").isalnum()):
                raise AppError("Only approved session JSON reports may be opened",400)
            target=_contained(path,path/name)
            if not target.is_file():raise AppError("Approved report is absent",404)
            if target.stat().st_size>JSON_LIMIT:raise AppError("Report exceeds bounded size limit",409)
            return target

    def guides(self):
        return {"guides":[{"id":k,"name":v} for k,v in GUIDES.items()
                          if (ROOT/v).is_file()]}

    def guide(self,name):
        if name not in GUIDES:raise AppError("Unknown guide",400)
        target=_contained(ROOT,ROOT/GUIDES[name])
        if not target.is_file():raise AppError("Guide not found",404)
        return target

    def job(self,id):
        with self.mutex:
            journal=self._job_journal(id)
            worker=self.jobs.get(id)
            if worker is None:
                return {"job":journal.status()}
            state=worker.poll()
            return {"job":journal.observe(state)}

    def _job_journal(self,id):
        project=self.session(id)
        if id not in self.job_journals:
            self.job_journals[id]=WorkflowJobJournal(project,self.instance_id)
        return self.job_journals[id]

    def interrupt_jobs(self):
        """Persist uncertainty only; native processes are not stopped or adopted."""
        with self.mutex:
            return [journal.interrupt() for journal in self.job_journals.values()]

    def job_start(self,id,action,confirmed):
        if confirmed is not True:raise AppError("Operator must confirm native processing",409)
        with self.mutex:
            if self._record_status()["state"]=="running":
                raise AppError("Finish webcam recording before native processing",409)
            prev=self.jobs.get(id)
            journal=self._job_journal(id)
            if prev:
                previous=prev.poll()
                journal.observe(previous)
                if previous.state=="running":
                    raise AppError("Native processing already active",409)
            if journal.status()["recovery_required"]:
                raise AppError("Job recovery required before native processing",409)
            worker=WorkflowController(self.session(id))
            plan=worker.plan(action)
            journal.begin(action)
            self.jobs[id]=worker
            try:
                status=worker.start(action)
            except BaseException:
                journal.interrupt()
                self.jobs.pop(id,None)
                raise
            result=journal.observe(status)
            result["message"]=plan.description
            return {"job":result}

    def job_cancel(self,id,confirmed):
        if confirmed is not True:raise AppError("Explicit process stop confirmation required",409)
        with self.mutex:
            worker=self.jobs.get(id)
            if worker is None:raise AppError("No active native action from this app",409)
            return {"message":worker.cancel_now(),
                    "warning":"Interrupted outputs remain unverified; inspect recovery status."}

    def recovery(self,id):
        with self.mutex:
            data=inspect_recovery(self.session(id))
            data.pop("session",None)
            return {"recovery":data}

    def sync(self,id,cues,reference,confirmed):
        if confirmed is not True:raise AppError("All four visual sync cues require operator confirmation",409)
        with self.mutex:
            if self.library.describe_session(id)["kind"]!="real":
                raise AppError("Test-only footage cannot be registered as real sync evidence",409)
            output=save_sync(self.session(id),cues,reference=reference,operator_confirmed=True)
            return {"file":output.name,"message":"Operator cues recorded; native Pose2Sim synchronization still pending."}

    def _record_status(self):
        active=self.recording
        if not active:return {"state":"idle","role":None}
        code=active["process"].poll()
        if code is None:return {"state":"running","role":active["role"],"session":active["id"]}
        self.recording=None
        if code!=0:return {"state":"failed","role":active["role"],
                           "message":"FFmpeg exited unsuccessfully; partial file retained."}
        try:
            out=finalize_recording(active["project"],active["role"])
            return {"state":"saved","role":active["role"],"filename":out.name,"session":active["id"]}
        except (OSError,ValueError) as exc:
            return {"state":"failed","role":active["role"],"message":str(exc)}

    def record_status(self):
        with self.mutex:return {"recording":self._record_status()}

    def record_start(self,id,role,seconds,confirmed):
        if confirmed is not True:raise AppError("Explicit webcam consent required",409)
        raise AppError(PARTICIPANT_RECORDING_BLOCKED,409)

    def record_stop(self,confirmed):
        if confirmed is not True:raise AppError("Explicit camera stop confirmation required",409)
        with self.mutex:
            if not self.recording or self.recording["process"].poll() is not None:
                raise AppError("No camera recording is running",409)
            try:
                self.recording["process"].stdin.write(b"q\n")
                self.recording["process"].stdin.flush()
            except (OSError,ValueError) as err:
                raise AppError("Unable to stop camera safely; wait for its timer",409) from err
            return {"message":"Stop sent; completed MP4 will publish only after FFprobe verification."}

    def upload(self,id,role,stream,length,confirmed):
        if role=="cam01_trial":raise AppError(PARTICIPANT_RECORDING_BLOCKED,409)
        if confirmed is not True:raise AppError("Confirm importing local phone MP4",409)
        if role not in ("cam01_intrinsics","cam01_board","cam01_trial"):
            raise AppError("Only three phone MP4 roles can be imported",400)
        if type(length) is not int or length<1 or length>UPLOAD_LIMIT:
            raise AppError("MP4 input must be between 1 byte and 220MB",400)
        with self.mutex:
            project=self.editable(id)
            if self._record_status()["state"]=="running":
                raise AppError("Finish recording before phone import",409)
            pending=project/"raw"/(role+"."+uuid4().hex+".incoming.mp4")
            try:
                with pending.open("xb") as dst:
                    remaining=length
                    while remaining:
                        block=stream.read(min(1024*1024,remaining))
                        if not block:raise AppError("Incomplete MP4 transfer",400)
                        dst.write(block);remaining-=len(block)
                    dst.flush();os.fsync(dst.fileno())
                original=import_phone_mp4(project,role,pending)
                return {"role":role,"filename":original.name,"bytes":original.stat().st_size,
                        "message":"Local MP4 verified; capture remains uncalibrated and unregistered."}
            finally:
                pending.unlink(missing_ok=True)

    def research(self):
        available=(self.samples.parent/"TEST-ONLY-NOT-CALIBRATED.txt").is_file()
        return {"available":available and (self.samples/"gait-t5"/"index.html").is_file(),
                "status":"EXTERNAL SAMPLE — TEST ONLY",
                "gait_review_url":"/research/gait-t5/index.html" if available else None,
                "tracking_url":"/research/pose2d-fullseq/index.html" if available else None,
                "squat_status":"Only synthetic test repetitions verified; no real squat test."}

    def research_file(self,folder,name):
        if folder not in RESEARCH or name not in RESEARCH[folder]:
            raise AppError("Research resource not approved",404)
        if not (self.samples.parent/"TEST-ONLY-NOT-CALIBRATED.txt").is_file():
            raise AppError("Missing sample-only provenance guard",404)
        target=_contained(self.samples/folder,self.samples/folder/name)
        if not target.is_file():raise AppError("Research asset missing",404)
        return target

    def squat(self,payload):
        if payload.get("activity_confirmed") is not True or payload.get("camera_view")!="side":
            raise AppError("Confirmed side-view squat source required",409)
        data=payload.get("evidence")
        if not isinstance(data,dict) or data.get("test_only") is not True:
            raise AppError("Only explicitly test-only HALPE26 source observations accepted",409)
        if data.get("source_sha256")!=payload.get("source_sha256"):
            raise AppError("Input 2D hash mismatch",409)
        result=analyze_squats(data,payload.get("role"),payload.get("source_sha256"),
                              camera_view="side",activity_confirmed=True,
                              image_width=payload.get("image_width",1024),
                              image_height=payload.get("image_height",576))
        return {"analysis":{"status":result["status"],
            "candidate_repetition_count":result["candidate_repetition_count"],
            "repetitions":result["repetitions"],"incomplete_attempts":result["incomplete_attempts"],
            "quality":result["quality"],"count_is_clinically_validated":False,
            "input_identity":"user-supplied-test-json-not-independently-verified-against-mp4"}}


def make_handler(core):
    class Handler(BaseHTTPRequestHandler):
        server_version="KineLabUnified/0.6"
        def log_message(self,fmt,*args):
            return  # do not record raw query strings, subject paths or tokens
        def headers_for(self,status,mime,size,extra=None,inline=False):
            self.send_response(status)
            for name,value in {
                "Content-Type":mime,"Content-Length":str(size),
                "X-Content-Type-Options":"nosniff","Cache-Control":"no-store",
                "Referrer-Policy":"no-referrer","X-Frame-Options":"SAMEORIGIN",
                "Cross-Origin-Resource-Policy":"same-origin",
                "Content-Security-Policy":(
                    "default-src 'self'; connect-src 'self'; img-src 'self' blob: data:; "
                    "media-src 'self' blob:; font-src 'self'; frame-src 'self'; "
                    "worker-src 'self' blob:; script-src 'self'"+
                    (" 'unsafe-inline'" if inline else "")+
                    "; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'"),
            }.items():self.send_header(name,str(value))
            for name,value in (extra or {}).items():self.send_header(name,str(value))
            self.end_headers()
        def json_out(self,data,status=200):
            raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode("utf-8")
            self.headers_for(status,"application/json; charset=utf-8",len(raw))
            self.wfile.write(raw)
        def error_out(self,error,status=None):
            if status is None:status=error.status if isinstance(error,AppError) else 409
            raw=str(error).replace(str(ROOT),"[project]").replace(
                str(core.library.projects_root),"[sessions]")
            self.json_out({"error":raw[:340]},status)
        def permitted(self,public=False):
            if self.headers.get("Host")!=f"127.0.0.1:{self.server.server_port}":
                self.error_out(AppError("Host refused",403));return False
            origin=self.headers.get("Origin")
            if origin and origin!=f"http://127.0.0.1:{self.server.server_port}":
                self.error_out(AppError("Cross-origin request refused",403));return False
            if public:return True
            if not secrets.compare_digest(self.headers.get("X-KineLab-Key",""),core.token):
                self.error_out(AppError("Local session key required",403));return False
            return True
        def file_out(self,file,*,mime=None,media=False,inline=False):
            length=file.stat().st_size;start,end=0,length-1;status=200;extra={}
            if media:
                extra["Accept-Ranges"]="bytes"
                request=self.headers.get("Range")
                if request:
                    if not request.startswith("bytes=") or "," in request:
                        raise AppError("Invalid media range",416)
                    parts=request[6:].split("-")
                    if len(parts)!=2 or not parts[0].isdigit() or (parts[1] and not parts[1].isdigit()):
                        raise AppError("Invalid media range",416)
                    start=int(parts[0])
                    end=min(int(parts[1]),length-1) if parts[1] else length-1
                    if start>=length or start>end:raise AppError("Media range outside video",416)
                    status=206;extra["Content-Range"]=f"bytes {start}-{end}/{length}"
            size=max(0,end-start+1)
            self.headers_for(status,mime or MIME.get(file.suffix) or
                             guess_type(file.name)[0] or "application/octet-stream",
                             size,extra,inline=inline)
            with file.open("rb") as stream:
                stream.seek(start)
                remaining=size
                while remaining:
                    chunk=stream.read(min(1024*1024,remaining))
                    if not chunk:break
                    self.wfile.write(chunk);remaining-=len(chunk)
        def read_json(self):
            if "application/json" not in self.headers.get("Content-Type",""):
                raise AppError("JSON body required",400)
            try:
                n=int(self.headers.get("Content-Length","0"))
                if n<1 or n>JSON_LIMIT:raise ValueError
                data=json.loads(self.rfile.read(n))
                if not isinstance(data,dict):raise TypeError
                return data
            except (ValueError,UnicodeError,TypeError):
                raise AppError("Malformed or oversized JSON body",400)
        def do_GET(self):
            try:
                route=urlsplit(self.path)
                params={k:v[0] for k,v in parse_qs(route.query).items()}
                if route.path=="/api/health":
                    if self.permitted(public=True):
                        self.json_out({"app":"KineLab PT","service":"unified",
                                       "mode":"offline-local","status":"ready"})
                    return
                if route.path.startswith("/api/"):
                    if not self.permitted():return
                    id=params.get("id","")
                    actions={
                        "/api/sessions":lambda:core.sessions(),
                        "/api/session":lambda:core.detail(id),
                        "/api/readiness":lambda:core.readiness(id),
                        "/api/reports":lambda:core.reports(id),
                        "/api/job":lambda:core.job(id),
                        "/api/record":lambda:core.record_status(),
                        "/api/recovery":lambda:core.recovery(id),
                        "/api/research":lambda:core.research(),
                        "/api/guides":lambda:core.guides(),
                    }
                    if route.path in actions:return self.json_out(actions[route.path]())
                    if route.path=="/api/report":
                        return self.file_out(core.report(id,params.get("file","")))
                    if route.path=="/api/guide":
                        return self.file_out(core.guide(params.get("name","")),
                                             mime="text/markdown; charset=utf-8")
                    raise AppError("Unknown API route",404)
                if not self.permitted(public=True):return
                if route.path.startswith("/research/"):
                    bits=route.path.strip("/").split("/")
                    if len(bits)!=3:raise AppError("Research route refused",404)
                    path=core.research_file(bits[1],bits[2])
                    return self.file_out(path,media=path.suffix==".mp4",
                                         inline=path.suffix==".html")
                relative=unquote(route.path)
                if relative=="/":relative="/index.html"
                if relative=="/index.html" or relative=="/motion/demo.motion.json" or (
                    relative.startswith("/assets/") and relative.count("/")<=2 and
                    relative.endswith((".js",".css",".png",".jpg",".svg",".woff2"))):
                    target=_contained(core.dist,core.dist/relative.lstrip("/"))
                    if target.is_file():return self.file_out(target)
                raise AppError("Static file unavailable",404)
            except AppError as err:self.error_out(err)
            except (OSError,ValueError,SessionError,WorkflowBlocked,
                    SyncEvidenceError,SquatEvidenceError) as err:self.error_out(err)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_OPTIONS(self):
            self.error_out(AppError("Cross-origin preflight disabled",403))
        def do_POST(self):
            if not self.permitted():return
            try:
                route=urlsplit(self.path)
                if route.path=="/api/upload":
                    params=parse_qs(route.query)
                    if self.headers.get("Content-Type")!="video/mp4":
                        raise AppError("Only video/mp4 imports accepted",400)
                    try:n=int(self.headers.get("Content-Length","0"))
                    except (ValueError,TypeError):raise AppError("Invalid MP4 byte count",400)
                    response=core.upload(params.get("id",[""])[0],
                        params.get("role",[""])[0],self.rfile,n,
                        self.headers.get("X-KineLab-Confirm")=="yes")
                    return self.json_out(response,201)
                data=self.read_json()
                id=data.get("id","")
                confirm=data.get("confirmed")
                operations={
                    "/api/session/create":lambda:core.create(data.get("id","")),
                    "/api/session/register":lambda:core.register(id,confirm),
                    "/api/board":lambda:core.board(id,data.get("measured_square_mm"),
                                                  data.get("operator"),confirm),
                    "/api/job/start":lambda:core.job_start(id,data.get("action"),confirm),
                    "/api/job/cancel":lambda:core.job_cancel(id,confirm),
                    "/api/record/start":lambda:core.record_start(id,data.get("role"),
                                                                 data.get("seconds"),confirm),
                    "/api/record/stop":lambda:core.record_stop(confirm),
                    "/api/sync/save":lambda:core.sync(id,data.get("cues"),
                                                     data.get("reference"),confirm),
                    "/api/squat/analyze":lambda:core.squat(data),
                    "/api/legacy/open":lambda:self.open_legacy(data),
                }
                if route.path not in operations:raise AppError("Unknown mutation route",404)
                return self.json_out(operations[route.path](),
                                     201 if route.path=="/api/session/create" else 200)
            except AppError as err:self.error_out(err)
            except (OSError,ValueError,TypeError,SessionError,WorkflowBlocked,
                    SyncEvidenceError,SquatEvidenceError,subprocess.SubprocessError) as err:
                self.error_out(err,409)
        def open_legacy(self,data):
            if data.get("confirmed") is not True:
                raise AppError("Explicit legacy-tool launch confirmation required",409)
            key=data.get("key")
            if key == "capture":
                raise AppError(PARTICIPANT_RECORDING_BLOCKED,409)
            if key not in ("capture","motion","gait","tracking","caliscope","pose","mixed"):
                raise AppError("Invalid legacy launcher",400)
            launch_shortcut(key)
            return {"message":"Original tool opened through its preserved KineLab shortcut"}
    return Handler


def make_server(core,host="127.0.0.1",port=0):
    if host!="127.0.0.1":raise AppError("Loopback bind only",400)
    class LocalServer(ThreadingHTTPServer):
        daemon_threads=True
        allow_reuse_address=False
    return LocalServer((host,port),make_handler(core))


def main():
    from runtime_config import retired_entrypoint
    return retired_entrypoint("unified_service.py",
        "Its standalone server exposes the obsolete /api routes with X-KineLab-Key over the "
        "in-installation projects directory; t6_service.py imports it only as a library.")


def legacy_main():
    parser=argparse.ArgumentParser(description="KineLab PT offline unified local service")
    parser.add_argument("--port",type=int,required=True)
    parser.add_argument("--key",type=str,required=True)
    args=parser.parse_args()
    if not 1<=args.port<=65535 or len(args.key)<24:
        raise ValueError("Invalid port/key")
    if not (DIST/"index.html").is_file():raise FileNotFoundError("Viewer needs npm build first")
    app=AppCore(token=args.key)
    server=make_server(app,port=args.port)
    try:server.serve_forever(poll_interval=.25)
    finally:server.server_close()


if __name__=="__main__":
    raise SystemExit(main())
