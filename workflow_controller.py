"""Guarded local KineLab processing steps, retaining all Pose2Sim quality gates.

Each action is explicitly requested by the operator; the controller never
generates calibration/sync measurements, runs an unknown project, overwrites
existing results or treats a zero process exit alone as a quality pass.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import psutil

from session_contract import load_session, sha256_file
from session_library import SessionLibrary

ROOT = Path(__file__).resolve().parent
ACTIONS = ("normalize", "calibrate_pose", "reconstruct", "export_markers")


class WorkflowBlocked(ValueError):
    """A stage must not run or be shown as passed without the required evidence."""


@dataclass(frozen=True)
class WorkflowPlan:
    action: str
    command: tuple[str, ...]
    description: str
    expected_output: Path | None = None


@dataclass(frozen=True)
class WorkflowStatus:
    action: str
    state: str
    message: str
    passed: bool
    log_path: Path | None = None


class WorkflowController:
    def __init__(self, project: Path):
        supplied = Path(project)
        if supplied.is_symlink():
            raise WorkflowBlocked("Invalid session: symbolic links are not accepted")
        self.project = supplied.resolve()
        self.library = SessionLibrary(self.project.parent)
        self.library.open_session(self.project.name)
        self.process = None
        self.plan_active: WorkflowPlan | None = None
        self.log_path: Path | None = None
        self.cancel_requested = False
        self._lock_owner: str | None = None
        self.status = WorkflowStatus("", "idle", "No operation active", False)

    def _ensure_registered(self):
        description = self.library.describe_session(self.project.name)
        if description["kind"] == "test-only":
            raise WorkflowBlocked("test-only mixed videos cannot be processed as a real capture")
        if description["status"] != "registered" or description["kind"] != "real":
            raise WorkflowBlocked("A valid registered REAL six-clip session is required first")
        try:
            return load_session(self.project)
        except (ValueError, OSError) as error:
            raise WorkflowBlocked("Registered source identity is missing or changed: " + str(error)) from error

    def _verify_preflight(self):
        session = self._ensure_registered()
        preflight = self.project / "preflight.json"
        if not preflight.is_file():
            raise WorkflowBlocked("Verified preflight is missing; normalize all registered originals first")
        try:
            data = json.loads(preflight.read_text(encoding="utf-8-sig"))
            identity = {"session_id": session["session_id"],
                        "config_sha256": sha256_file(self.project / "Config.toml"),
                        "inputs": {role: entry["sha256"] for role, entry in session["captures"].items()}}
            if (data.get("schema") != "kinelab.preflight.v1"
                    or data.get("ok") is not True or data.get("errors")
                    or any(data.get(key) != value for key, value in identity.items())):
                raise WorkflowBlocked("Preflight does not match the current session/configuration")
            from run_pipeline import _verify_normalized
            _verify_normalized(self.project, identity)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise WorkflowBlocked("Verified preflight is invalid: " + str(error)) from error

    def _stage_status(self, stage_names: tuple[str, ...]):
        record_path = self.project / "run.json"
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise WorkflowBlocked("Passed native run.json is missing") from error
        session = self._ensure_registered()
        if (record.get("schema") != "kinelab.run.v1" or record.get("session_id") != session["session_id"]
                or record.get("config_sha256") != sha256_file(self.project / "Config.toml")
                or record.get("inputs") != {role: entry["sha256"] for role, entry in session["captures"].items()}):
            raise WorkflowBlocked("Native run manifest belongs to changed or different recordings")
        stages = record.get("stages", [])
        if not isinstance(stages, list):
            raise WorkflowBlocked("Invalid run manifest stages")
        accepted = {}
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            name = stage.get("name")
            if name not in stage_names:
                continue
            if stage.get("status") != "passed" or not stage.get("artifacts"):
                raise WorkflowBlocked("Required stage not passed: " + str(name))
            if not isinstance(stage.get("quality"), dict) or stage["quality"].get("ok") is not True:
                raise WorkflowBlocked("Required native stage quality is missing or rejected: " + str(name))
            for item in stage["artifacts"]:
                relative = Path(item.get("path", ""))
                artifact = (self.project / relative).resolve()
                if relative.is_absolute() or not artifact.is_relative_to(self.project) or not artifact.is_file():
                    raise WorkflowBlocked("Stage artifact missing or escaped session")
                if sha256_file(artifact) != item.get("sha256"):
                    raise WorkflowBlocked("Stage output no longer matches recorded hash")
            accepted[name] = stage
        if set(accepted) != set(stage_names):
            raise WorkflowBlocked("Required passed stages missing: " + ", ".join(set(stage_names) - set(accepted)))
        return accepted

    def plan(self, action: str) -> WorkflowPlan:
        if action not in ACTIONS:
            raise WorkflowBlocked("Unknown workflow action: " + str(action))
        session = self._ensure_registered()
        python = str(ROOT / ".venv" / "Scripts" / "python.exe")
        if not Path(python).is_file():
            raise WorkflowBlocked("Missing project Python environment")
        project = str(self.project)
        if action == "normalize":
            if (self.project / "normalization.json").exists():
                raise WorkflowBlocked("Normalized output already exists; use the verified preflight and resume")
            return WorkflowPlan(action, (python, "-B", str(ROOT / "normalize_capture.py"),
                                         "--project", project), "Normalize and validate six originals")
        self._verify_preflight()
        if action == "calibrate_pose":
            if (self.project / "run.json").exists():
                raise WorkflowBlocked("An existing run.json exists; inspect stage inventory before a rerun")
            return WorkflowPlan(action, (python, "-B", str(ROOT / "run_pipeline.py"),
                                         "--project", project, "--start", "calibration",
                                         "--stop", "poseEstimation"), "Calibrate cameras and estimate 2D poses")
        if action == "reconstruct":
            observations = self.project / "sync-observations.json"
            if not observations.is_file():
                raise WorkflowBlocked("Independently observed sync-observations.json is required")
            try:
                data = json.loads(observations.read_text(encoding="utf-8"))
                if (data.get("session_id") != session["session_id"]
                        or not data.get("source_frame_pairs")
                        or not data.get("cameras")):
                    raise WorkflowBlocked("sync-observations.json lacks recorded independent cue pairs")
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                raise WorkflowBlocked("sync-observations.json is malformed: " + str(error)) from error
            self._stage_status(("calibration", "poseEstimation"))
            return WorkflowPlan(action, (python, "-B", str(ROOT / "run_pipeline.py"),
                                         "--project", project, "--start", "synchronization",
                                         "--stop", "filtering"), "Synchronize, associate and reconstruct 3D")
        self._stage_status(("calibration", "poseEstimation", "synchronization",
                            "personAssociation", "triangulation", "filtering"))
        record = json.loads((self.project / "run.json").read_text(encoding="utf-8"))
        filtered = next(stage for stage in record["stages"] if stage.get("name") == "filtering")
        candidates = [self.project / item["path"] for item in filtered["artifacts"]
                      if item["path"].lower().endswith(".trc")]
        if len(candidates) != 1:
            raise WorkflowBlocked("Expected one exact run-bound filtered TRC for marker-only export")
        export = self.project / "exports" / (session["session_id"] + ".motion.json")
        if export.exists():
            raise WorkflowBlocked("Export destination already exists; refusing overwrite")
        return WorkflowPlan(action, (
            python, "-B", str(ROOT / "export_motion.py"), "--project", project,
            "--run-manifest", str(self.project / "run.json"),
            "--trc", str(candidates[0]), "--no-mot", "--out", str(export)
        ), "Export validated marker-only 3D motion", export)

    def _cleanup_lock(self):
        lock = self.project / "workflow.lock"
        if self._lock_owner is not None and lock.is_file():
            try:
                if lock.read_text(encoding="utf-8") == self._lock_owner:
                    lock.unlink()
            finally:
                self._lock_owner = None

    def start(self, action: str) -> WorkflowStatus:
        if self.process is not None and self.process.poll() is None:
            raise WorkflowBlocked("Workflow busy; one local action at a time")
        if (self.project / "workflow.lock").exists():
            raise WorkflowBlocked("Workflow busy; inspect workflow.lock and old process before retry")
        plan = self.plan(action)
        lock = self.project / "workflow.lock"
        owner = f"{os.getpid()}:{uuid4().hex}"
        try:
            with lock.open("x", encoding="utf-8") as stream:
                stream.write(owner)
        except FileExistsError as error:
            raise WorkflowBlocked("Workflow busy; another operation holds workflow.lock") from error
        self._lock_owner = owner
        self.log_path = self.project / f"workflow-{action}-{uuid4().hex}.log"
        self.cancel_requested = False
        self.plan_active = plan
        try:
            with self.log_path.open("xb") as stream:
                self.process = subprocess.Popen(
                    list(plan.command), stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, cwd=str(ROOT),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
            self.status = WorkflowStatus(action, "running", plan.description + " (running; no estimated %)", False, self.log_path)
            return self.status
        except BaseException:
            self._cleanup_lock()
            self.process = None
            self.plan_active = None
            raise

    def _verify_completed(self, plan: WorkflowPlan):
        if plan.action == "normalize":
            self._verify_preflight()
        elif plan.action == "calibrate_pose":
            self._stage_status(("calibration", "poseEstimation"))
        elif plan.action == "reconstruct":
            self._stage_status(("calibration", "poseEstimation", "synchronization",
                                "personAssociation", "triangulation", "filtering"))
        elif plan.action == "export_markers":
            output = plan.expected_output
            if output is None or not output.is_file():
                raise WorkflowBlocked("Expected marker-only motion JSON was not produced")
            data = json.loads(output.read_text(encoding="utf-8"))
            session = self._ensure_registered()
            if (data.get("schema") != "kinelab.motion.v2" or data.get("sessionId") != session["session_id"]
                    or data.get("kinematics") is not None
                    or data.get("quality", {}).get("status") != "passed"
                    or data.get("quality", {}).get("mode") != "marker-only"):
                raise WorkflowBlocked("Export is not a session-bound passed marker-only result")

    def poll(self) -> WorkflowStatus:
        if self.plan_active is None or self.process is None:
            return self.status
        code = self.process.poll()
        plan = self.plan_active
        if code is None:
            message = plan.description + " (running; native stages determine progress)"
            try:
                if self.log_path and self.log_path.is_file():
                    tail = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-35:]
                    stages = [line for line in tail if line.startswith(("STAGE_START=", "STAGE_OK="))]
                    if stages:
                        message = stages[-1]
            except OSError:
                pass
            self.status = WorkflowStatus(plan.action, "running", message, False, self.log_path)
            return self.status
        try:
            if self.cancel_requested and code != 0:
                self.status = WorkflowStatus(
                    plan.action, "cancelled",
                    "Native child process stopped; partial artifacts are unverified. "
                    "Inspect run.json, native run.lock and the action log before retry.",
                    False, self.log_path,
                )
                return self.status
            if code != 0:
                raise WorkflowBlocked(f"Native action exited {code}; inspect the local action log and rerun only after recovery")
            self._verify_completed(plan)
            if self.cancel_requested:
                self.status = WorkflowStatus(plan.action, "cancelled-after-action",
                                             "Current native action completed; no next action will start", False, self.log_path)
            else:
                self.status = WorkflowStatus(plan.action, "passed",
                                             "Native action completed and recorded evidence verified", True, self.log_path)
        except (OSError, ValueError, TypeError) as error:
            self.status = WorkflowStatus(plan.action, "failed", str(error), False, self.log_path)
        finally:
            self._cleanup_lock()
            self.process = None
            self.plan_active = None
        return self.status

    def cancel_now(self) -> str:
        """Explicitly stop only the verified native subprocess tree.

        Partial outputs remain untrusted. Never delete run.lock or create a passed
        manifest to recover from an interrupted native stage.
        """
        if self.process is None or self.process.poll() is not None or self.plan_active is None:
            raise WorkflowBlocked("No active native action to cancel")
        try:
            parent = psutil.Process(self.process.pid)
            actual = [str(arg).casefold() for arg in parent.cmdline()]
            expected_script = str(Path(self.plan_active.command[2]).resolve()).casefold()
            expected_project = str(self.project).casefold()
            if expected_script not in actual or expected_project not in actual:
                raise WorkflowBlocked("Native process identity mismatch; refusing to terminate a different process")
            children = parent.children(recursive=True)
            targets = [*children, parent]
            self.cancel_requested = True
            for child in targets:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            _gone, alive = psutil.wait_procs(targets, timeout=3)
            for child in alive:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            return "Native action cancellation requested; unverified partial outputs require review"
        except (psutil.AccessDenied, psutil.ZombieProcess) as error:
            raise WorkflowBlocked("Cannot safely cancel the verified native process: " + str(error)) from error
        except psutil.NoSuchProcess as error:
            raise WorkflowBlocked("Native process exited before cancellation; inspect its result") from error

    def request_cancel(self) -> str:
        if self.process is None or self.process.poll() is not None:
            raise WorkflowBlocked("No running local action to stop")
        self.cancel_requested = True
        return "Stop requested after current action"
