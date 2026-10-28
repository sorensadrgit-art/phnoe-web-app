"""Desktop Capture Station. Local-only; camera starts solely on explicit Record click."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from capture_station import (
    DEFAULT_PROJECT, RAW_ROLES, WEBCAM_ROLES, RECOMMENDED_SECONDS,
    ROLE_GUIDE, check_readiness, clip_path, ffmpeg_command, finalize_recording,
    import_phone_mp4, prepare_recording, save_board_measurement
)
from session_library import SessionLibrary, SessionError
from workflow_controller import WorkflowController, WorkflowBlocked

ROOT = Path(__file__).resolve().parent
BG = "#09131D"
PANEL = "#111F2D"
ACCENT = "#62E4DD"
FG = "#EDF7FA"
MUTED = "#9CB0BD"
BORDER = "#29414F"


def label(parent, value, *, size=10, color=FG, bold=False, **kwargs):
    return tk.Label(parent, text=value, bg=parent.cget("bg"), fg=color,
                    font=("Segoe UI", size, "bold" if bold else "normal"),
                    anchor="w", justify="left", **kwargs)


def button(parent, title, handler, *, prominent=False, width=None):
    item = tk.Button(parent, text=title, command=handler, cursor="hand2",
                     font=("Segoe UI", 10, "bold"), relief="flat", bd=0,
                     bg=ACCENT if prominent else "#1C3442",
                     fg="#06252E" if prominent else FG, activebackground="#8DFFF5",
                     activeforeground="#06252E", padx=14, pady=9)
    if width:
        item.config(width=width)
    return item


class CaptureApp(tk.Tk):
    def __init__(self, initial_session_id: str | None = None):
        super().__init__()
        self.title("KineLab PT | Capture Station")
        self.geometry("1020x800")
        self.minsize(800, 690)
        self.configure(bg=BG)
        ico = ROOT / "assets" / "kinelab-pt.ico"
        if ico.exists():
            self.iconbitmap(str(ico))
        self.process = None
        self.current_role = None
        self.started_at = 0
        self.capture_duration = 0
        self.stop_requested = False
        self.status_nodes = {}
        self.workflow = None
        self.library = SessionLibrary(ROOT / "projects")
        self.project = self.library.open_session(initial_session_id or DEFAULT_PROJECT.name)
        self._build()
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self.close_safe)

    def _build(self):
        header = tk.Frame(self, bg=BG, padx=30, pady=22)
        header.pack(fill="x")
        label(header, "KINELAB  /  LOCAL MOTION CAPTURE", size=10, bold=True, color=ACCENT).pack(anchor="w")
        label(header, "Phone + Webcam Capture Station", size=22, bold=True).pack(anchor="w", pady=(5, 2))
        label(header, "Six real recordings. Measured calibration. Explicit consent. No uploads.",
              size=10, color=MUTED).pack(anchor="w")
        sessionbar = tk.Frame(self, bg=BG, padx=30, pady=6)
        sessionbar.pack(fill="x")
        label(sessionbar, "ACTIVE SESSION", bold=True, size=9, color=ACCENT).pack(side="left", padx=(0, 8))
        self.session_choice = tk.StringVar(value=self.project.name)
        self.session_picker = ttk.Combobox(sessionbar, textvariable=self.session_choice,
                                           state="readonly", width=29, font=("Segoe UI", 10))
        self.session_picker.pack(side="left", padx=(0, 9))
        self.session_picker.bind("<<ComboboxSelected>>", self._choose_session)
        button(sessionbar, "New session", self.create_session).pack(side="left", padx=(0, 7))
        button(sessionbar, "Register six clips", self.register_active_session, prominent=True).pack(side="left")
        self.session_badge = label(self, "UNREGISTERED", size=9, color=MUTED)
        self.session_badge.pack(fill="x", padx=30, pady=(0, 5))
        viewport = tk.Frame(self, bg=BG)
        viewport.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(viewport, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        canvas = tk.Canvas(viewport, bg=BG, borderwidth=0, highlightthickness=0,
                           yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=canvas.yview)
        body = tk.Frame(canvas, bg=BG, padx=24)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(body_id, width=e.width))
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>",
                    lambda wheel: canvas.yview_scroll(-int(wheel.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        left = tk.Frame(body, bg=PANEL, padx=20, pady=17, width=365, height=860)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)
        right = tk.Frame(body, bg=PANEL, padx=19, pady=17)
        right.pack(side="left", fill="both", expand=True)

        label(left, "01   PRINT + MEASURE BOARD", size=11, bold=True, color=ACCENT).pack(anchor="w")
        label(left, "8 × 10 squares · 7 × 9 inner corners\n20 mm nominal square size",
              size=10, color=FG).pack(anchor="w", pady=(9, 9))
        button(left, "Open printable checkerboard", self.open_board, prominent=True).pack(fill="x")
        label(left, "Print at 100% / Actual Size, never Fit to Page.\nUse a physical ruler to measure one full square.\nDo not type 20 mm unless you measured it.",
              size=9, color=MUTED).pack(anchor="w", pady=(9, 11))
        label(left, "Measured square (millimeters)", size=10, bold=True).pack(anchor="w")
        self.mm = tk.Entry(left, bg="#07131D", fg=FG, insertbackground=FG, relief="flat",
                           highlightbackground=BORDER, highlightthickness=1, font=("Segoe UI", 12))
        self.mm.pack(fill="x", ipady=6, pady=(5, 8))
        label(left, "Measured by (initials)", size=10, bold=True).pack(anchor="w")
        self.operator = tk.Entry(left, bg="#07131D", fg=FG, insertbackground=FG, relief="flat",
                                 highlightbackground=BORDER, highlightthickness=1, font=("Segoe UI", 12))
        self.operator.pack(fill="x", ipady=6, pady=(5, 8))
        button(left, "Save measured board size", self.store_measurement).pack(fill="x")

        tk.Frame(left, bg=BORDER, height=1).pack(fill="x", pady=17)
        label(left, "02   POSITION BOTH CAMERAS", size=11, bold=True, color=ACCENT).pack(anchor="w")
        label(left, "Phone (cam01): front / diagonal view.\nWebcam (cam02): roughly 45–70° apart.\nBoth show full body, feet and floor.\nKeep lens, focus, zoom and camera placement fixed\nbetween board and movement recordings.",
              size=9, color=FG).pack(anchor="w", pady=(9, 5))
        tk.Frame(left, bg=BORDER, height=1).pack(fill="x", pady=13)
        label(left, "03   SHARED START + END CUES", size=11, bold=True, color=ACCENT).pack(anchor="w")
        label(left, "During the overlapping trial recordings:\n1. Make a visible sharp hand movement.\n2. Perform 3 slow squats.\n3. Repeat a visible sharp movement near end.\n\nNative Pose2Sim sync plus independent cue\nmeasurements are required to accept the data.",
              size=9, color=FG).pack(anchor="w", pady=(9, 5))
        button(left, "Open session footage folder", self.open_raw).pack(fill="x", pady=(13, 4))
        button(left, "Open capture quickstart", lambda: os.startfile(str(ROOT / "CAPTURE-NOW.md"))).pack(fill="x", pady=(2, 4))
        button(left, "Read processing runbook", lambda: os.startfile(str(ROOT / "RUNBOOK.md"))).pack(fill="x")

        label(right, "04   CAPTURE THE SIX ORIGINAL CLIPS", size=11, bold=True, color=ACCENT).pack(anchor="w")
        label(right, "Phone: import MP4. Webcam: press Record only when ready.", color=MUTED, size=9).pack(anchor="w", pady=(5, 12))
        for role in RAW_ROLES:
            row = tk.Frame(right, bg="#152A38", padx=10, pady=7)
            row.pack(fill="x", pady=4)
            upper = tk.Frame(row, bg=row.cget("bg"))
            upper.pack(fill="x")
            label(upper, role + ".mp4", bold=True, size=10).pack(side="left")
            indicator = label(upper, "NOT RECORDED", size=9, color="#F8BB91")
            indicator.pack(side="right")
            self.status_nodes[role] = indicator
            label(row, ROLE_GUIDE[role], size=8, color=MUTED).pack(anchor="w", pady=(3, 5))
            if role.startswith("cam01"):
                button(row, "Import phone MP4", lambda role=role: self.import_phone(role)).pack(anchor="w")
            else:
                button(row, f"Record webcam · {RECOMMENDED_SECONDS[role]} s",
                       lambda role=role: self.record_webcam(role)).pack(anchor="w")
            alternatives = tk.Frame(row, bg=row.cget("bg"))
            alternatives.pack(fill="x", pady=(6, 0))
            button(alternatives, "Stage alternate MP4",
                   lambda role=role: self.stage_alternate(role)).pack(side="left", padx=(0, 7))
            button(alternatives, "Accept staged take",
                   lambda role=role: self.accept_alternate(role)).pack(side="left")

        workflow_panel = tk.Frame(right, bg="#152A38", padx=12, pady=12)
        workflow_panel.pack(fill="x", pady=(14, 5))
        label(workflow_panel, "05   GUARDED LOCAL PROCESSING", size=11,
              bold=True, color=ACCENT).pack(anchor="w")
        label(workflow_panel, "Run a single requested action. Missing physical evidence blocks the next stage.",
              size=8, color=MUTED).pack(anchor="w", pady=(4, 8))
        first = tk.Frame(workflow_panel, bg=workflow_panel.cget("bg"))
        first.pack(fill="x")
        button(first, "Normalize six files",
               lambda: self.start_workflow("normalize")).pack(side="left", padx=(0, 6))
        button(first, "Calibrate + 2D pose",
               lambda: self.start_workflow("calibrate_pose")).pack(side="left")
        second = tk.Frame(workflow_panel, bg=workflow_panel.cget("bg"))
        second.pack(fill="x", pady=(7, 4))
        button(second, "Review start/end cues",
               self.review_sync_cues).pack(side="left", padx=(0, 6))
        button(second, "Reconstruct 3D",
               lambda: self.start_workflow("reconstruct")).pack(side="left", padx=(0, 6))
        button(workflow_panel, "Export marker-only",
               lambda: self.start_workflow("export_markers")).pack(anchor="w", pady=(6, 3))
        button(workflow_panel, "Cancel active processing",
               self.request_stop_workflow).pack(anchor="w", pady=(5, 5))
        button(workflow_panel, "Inspect / recover interrupted action",
               self.inspect_recovery_ui).pack(anchor="w", pady=(0, 5))
        self.workflow_label = label(workflow_panel, "NO ACTIVE PROCESSING",
                                    size=9, color=MUTED, wraplength=440)
        self.workflow_label.pack(anchor="w")

        footer = tk.Frame(self, bg=BG, padx=30, pady=13)
        footer.pack(fill="x")
        self.current = label(footer, "CAMERA IDLE", size=10, bold=True, color=ACCENT)
        self.current.pack(side="left")
        self.stop_btn = button(footer, "Stop camera recording", self.stop_webcam)
        self.stop_btn.pack(side="right", padx=(10, 0))
        self.stop_btn.configure(state="disabled")
        button(footer, "Refresh + check all six", self.refresh, prominent=True).pack(side="right")
        self.summary = label(self, "", size=10, color=MUTED)
        self.summary.pack(fill="x", padx=30, pady=(0, 12))

    def inspect_recovery_ui(self):
        from workflow_recovery import RecoveryBlocked, inspect_recovery, archive_orphaned_lock
        try:
            info = inspect_recovery(self.project)
            lines = [
                f"Session: {self.project.name}",
                f"Native stage state: {info['native_run']}",
                "Failed/running stages: " + (
                    ", ".join(info["incomplete_stages"]) if info["incomplete_stages"] else "none recorded"
                ),
                f"Related native workers detected: {info['related_worker_count']}",
            ]
            for name, lock in info["locks"].items():
                lines.append(f"{name}: {lock['state']}")
            lines.append("")
            lines.append(info["next_step"])
            messagebox.showinfo("KineLab recovery diagnostics", "\n".join(lines), parent=self)
            if self._workflow_running() or (self.process is not None and self.process.poll() is None):
                return
            for name, state in info["locks"].items():
                if state["state"] != "orphaned":
                    continue
                if not messagebox.askyesno(
                    "Archive verified orphaned lock?",
                    f"{name} belongs to a PID that is no longer running. "
                    "No related native workers were detected.\n\n"
                    "Archive this lock (retain its original contents) rather than deleting it?\n"
                    "Unfinished run artifacts remain UNVERIFIED and may require a new session.\n\n"
                    "This will NOT mark any stage passed.",
                    parent=self,
                ):
                    continue
                archived = archive_orphaned_lock(self.project, name, confirmed=True)
                messagebox.showinfo(
                    "Lock archived; native results remain unverified",
                    f"Original lock retained at:\n{archived}\n\n"
                    "Inspect run.json and the recorded artifact inventory before starting again.",
                    parent=self,
                )
        except (OSError, ValueError, RecoveryBlocked) as error:
            messagebox.showerror("Recovery refused", str(error), parent=self)

    def review_sync_cues(self):
        if self._workflow_running() or (self.process is not None and self.process.poll() is None):
            messagebox.showwarning(
                "Active camera / processing",
                "Finish the active operation before reviewing normalized video cues.",
                parent=self,
            )
            return
        try:
            from sync_review_gui import SyncReviewWindow
            SyncReviewWindow(self, self.project)
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror(
                "Sync review unavailable",
                str(error) + "\n\nRegister and normalize six real videos first.",
                parent=self,
            )

    def _workflow_running(self) -> bool:
        return (self.workflow is not None and self.workflow.process is not None
                and self.workflow.process.poll() is None)

    def start_workflow(self, action: str):
        if self.process is not None and self.process.poll() is None:
            messagebox.showwarning("Camera busy", "Finish the webcam recording before processing.", parent=self)
            return
        if self._workflow_running():
            messagebox.showwarning("Processing busy", "An existing local action is running.", parent=self)
            return
        try:
            candidate = WorkflowController(self.project)
            plan = candidate.plan(action)
            if not messagebox.askyesno(
                "Run guarded local processing?",
                f"{plan.description}\n\n"
                "Uses only this registered session. Real physical calibration and independent sync "
                "measurements are required for later stages. No online test fixture can pass "
                "the real capture gates.\n\nStart this action?",
                parent=self,
            ):
                return
            candidate.start(action)
            self.workflow = candidate
            self.workflow_label.configure(
                text=f"RUNNING: {plan.description} — native stage progress, no invented %",
                fg=ACCENT,
            )
            self.after(750, self._poll_workflow)
        except (OSError, ValueError, WorkflowBlocked) as error:
            self.workflow_label.configure(text="BLOCKED: " + str(error), fg="#F8BB91")
            messagebox.showerror("Processing blocked", str(error), parent=self)

    def _poll_workflow(self):
        if self.workflow is None:
            return
        try:
            status = self.workflow.poll()
        except (OSError, ValueError) as error:
            self.workflow_label.configure(text="PROCESSING ERROR: " + str(error), fg="#F8BB91")
            messagebox.showerror("Processing error", str(error), parent=self)
            return
        self.workflow_label.configure(
            text=f"{status.state.upper()}: {status.message}",
            fg=ACCENT if status.passed or status.state == "running" else "#F8BB91",
        )
        if status.state == "running":
            self.after(850, self._poll_workflow)
            return
        if status.passed:
            messagebox.showinfo(
                "Verified action completed",
                f"{status.message}\n\nNext processing action still requires your explicit request.",
                parent=self,
            )
        elif status.state == "cancelled":
            messagebox.showwarning(
                "Processing cancelled",
                f"{status.message}\n\nInspect the recorded stage outputs and native run.lock before retry.\n{status.log_path}",
                parent=self,
            )
        elif status.state == "failed":
            messagebox.showerror(
                "Processing rejected",
                f"{status.message}\n\nLocal diagnostic log:\n{status.log_path}",
                parent=self,
            )
        self.refresh()

    def request_stop_workflow(self):
        if not self._workflow_running():
            messagebox.showinfo("No active processing", "No current action is running.", parent=self)
            return
        if not messagebox.askyesno(
            "Cancel active native action?",
            "Stop the current local subprocess and its children now?\n\n"
            "Original camera files remain unchanged. Partial processed outputs are UNVERIFIED "
            "and might require manual clean-session recovery.\n\nCancel now?",
            parent=self,
        ):
            return
        try:
            note = self.workflow.cancel_now()
            self.workflow_label.configure(text=note, fg="#F8BB91")
        except (WorkflowBlocked, OSError, ValueError) as error:
            messagebox.showerror("Cannot cancel process safely", str(error), parent=self)

    def _ensure_editable(self) -> bool:
        state = self.library.describe_session(self.project.name)
        if not state["can_register"]:
            messagebox.showwarning(
                "Read-only session",
                "This is a registered, legacy, or test-only session. "
                "Create a new real session before adding or replacing recordings.",
                parent=self,
            )
            return False
        return True

    def _choose_session(self, _event=None):
        if (self.process is not None and self.process.poll() is None) or self._workflow_running():
            self.session_choice.set(self.project.name)
            messagebox.showwarning(
                "Capture/processing in progress", "Finish the active action before switching sessions.",
                parent=self,
            )
            return
        try:
            self.project = self.library.open_session(self.session_choice.get())
            self.mm.delete(0, tk.END)
            self.operator.delete(0, tk.END)
        except (OSError, SessionError) as error:
            self.session_choice.set(self.project.name)
            messagebox.showerror("Cannot open session", str(error), parent=self)
        self.refresh()

    def create_session(self):
        if (self.process is not None and self.process.poll() is None) or self._workflow_running():
            messagebox.showwarning("Action in progress", "Finish the active action first.", parent=self)
            return
        name = simpledialog.askstring(
            "New recording session", "Enter a unique session ID (letters, numbers, _ or -).",
            parent=self,
        )
        if name is None:
            return
        try:
            created = self.library.create_session(name)
            self.project = created
            self.session_choice.set(created.name)
            self.mm.delete(0, tk.END)
            self.operator.delete(0, tk.END)
            self.refresh()
            messagebox.showinfo(
                "Session created",
                f"{created.name}\n\nNo camera started. Import or record the six files when ready.",
                parent=self,
            )
        except (OSError, SessionError, ValueError) as error:
            messagebox.showerror("Session not created", str(error), parent=self)

    def register_active_session(self):
        if (self.process is not None and self.process.poll() is None) or self._workflow_running():
            messagebox.showwarning("Action in progress", "Finish the active action first.", parent=self)
            return
        try:
            report = self.library.registration_readiness(self.project.name)
            if not report["ready_to_register"]:
                missing = ", ".join(report.get("missing", []))
                issues = "; ".join(report.get("issues", []))
                raise SessionError("Registration refused. Missing: " + (missing or "none")
                                   + ". " + issues)
            if not messagebox.askyesno(
                "Register six real clips",
                "Bind the six accepted ORIGINAL clips to this session using SHA-256?\n"
                "Registration freezes the selected footage and does NOT establish "
                "synchronization, valid 3D reconstruction, or clinical accuracy.\n\nProceed?",
                parent=self,
            ):
                return
            result = self.library.register_session(self.project.name)
            messagebox.showinfo(
                "Capture identity registered",
                f"{result['session_id']}\n\nRun the normalization and measured "
                "calibration/synchronization gates next.",
                parent=self,
            )
        except (SessionError, ValueError, OSError) as error:
            messagebox.showerror("Registration refused", str(error), parent=self)
        self.refresh()

    def stage_alternate(self, role: str):
        if not self._ensure_editable():
            return
        source = filedialog.askopenfilename(
            parent=self, title=f"Select an alternate MP4 take for {role}",
            filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")],
        )
        if not source:
            return
        try:
            saved = self.library.stage_take(self.project.name, role, Path(source))
            messagebox.showinfo(
                "Alternate preserved",
                f"Staged independently at:\n{saved}\n\n"
                "The selected original is unchanged. Press Accept staged take to select it.",
                parent=self,
            )
        except (OSError, ValueError, SessionError) as error:
            messagebox.showerror("Cannot stage take", str(error), parent=self)
        self.refresh()

    def accept_alternate(self, role: str):
        if not self._ensure_editable():
            return
        folder = self.project / "takes" / role
        if not folder.is_dir():
            messagebox.showinfo("No staged takes", "Stage an alternate MP4 first.", parent=self)
            return
        selection = filedialog.askopenfilename(
            parent=self, title=f"Select a staged take for {role}",
            initialdir=str(folder), filetypes=[("MP4 video", "*.mp4")],
        )
        if not selection:
            return
        if not messagebox.askyesno(
            "Accept take?",
            f"Select {Path(selection).name} as {role}.mp4?\n"
            "If the old clip exists, its bytes will be independently archived. "
            "Registered sessions cannot change recordings.",
            parent=self,
        ):
            return
        try:
            chosen = self.library.accept_take(self.project.name, role, Path(selection))
            messagebox.showinfo(
                "Take selected", f"Active role:\n{chosen}\nPrior footage preserved in takes/archive.",
                parent=self,
            )
        except (OSError, ValueError, SessionError) as error:
            messagebox.showerror("Take selection refused", str(error), parent=self)
        self.refresh()

    def open_board(self):
        board = ROOT / "assets" / "checkerboard_20mm.svg"
        try:
            if not board.exists():
                subprocess.run([sys.executable, str(ROOT / "make_board.py"), str(board)], check=True)
            os.startfile(str(board))
        except Exception as exc:
            messagebox.showerror("Printable board", str(exc), parent=self)

    def open_raw(self):
        os.startfile(str(self.project / "raw"))

    def store_measurement(self):
        if not self._ensure_editable():
            return
        try:
            value = float(self.mm.get().strip())
            result = save_board_measurement(self.project, value, self.operator.get())
            messagebox.showinfo("Recorded", f"Operator-measured square: {result['measured_square_mm']} mm.\nNo clinical accuracy claim is implied.", parent=self)
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Board measurement", str(exc), parent=self)

    def import_phone(self, role: str):
        if not self._ensure_editable():
            return
        file = filedialog.askopenfilename(
            parent=self, title=f"Select original phone MP4 for {role}",
            filetypes=[("MP4 videos", "*.mp4"), ("All files", "*.*")])
        if not file:
            return
        if not messagebox.askyesno("Import phone footage",
                                   f"Copy {Path(file).name} into {role}.mp4?\nOriginal remains unchanged. Existing clips never overwrite.",
                                   parent=self):
            return
        try:
            self.current.configure(text=f"COPYING {role}", fg=ACCENT)
            self.update_idletasks()
            imported = import_phone_mp4(self.project, role, Path(file))
            self.current.configure(text="CAMERA IDLE")
            messagebox.showinfo("Import complete", f"Copied and validated:\n{imported}", parent=self)
        except Exception as exc:
            self.current.configure(text="IMPORT FAILED", fg="#F8BB91")
            messagebox.showerror("Phone import failed", str(exc), parent=self)
        self.refresh()

    def record_webcam(self, role: str):
        if self.process is not None:
            messagebox.showwarning("Already recording", "Finish the current webcam recording first.", parent=self)
            return
        if self._workflow_running():
            messagebox.showwarning("Processing active", "Finish the local processing action first.", parent=self)
            return
        if not self._ensure_editable():
            return
        seconds = RECOMMENDED_SECONDS[role]
        try:
            _dest, partial = prepare_recording(self.project, role, seconds)
            if not messagebox.askyesno("Start live webcam recording?",
                 f"The Integrated Webcam will turn ON now.\n\nClip: {role}.mp4\nDuration: up to {seconds} seconds\nLocal only; no uploading.\n\nFor the trial, start your PHONE recording immediately afterward, then perform visible START and END cues.",
                 parent=self):
                return
            log = (self.project / "capture-station.log").open("ab")
            try:
                self.process = subprocess.Popen(
                    ffmpeg_command(partial, seconds), cwd=str(ROOT),
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            finally:
                log.close()
            self.current_role = role
            self.started_at = time.monotonic()
            self.capture_duration = seconds
            self.stop_requested = False
            self.stop_btn.configure(state="normal")
            self._poll()
        except Exception as exc:
            self.process = None
            self.stop_btn.configure(state="disabled")
            messagebox.showerror("Recording could not start", str(exc), parent=self)

    def _poll(self):
        if self.process is None:
            return
        code = self.process.poll()
        if code is None:
            elapsed = int(time.monotonic() - self.started_at)
            self.current.config(text=f"● RECORDING {self.current_role}    {elapsed} / {self.capture_duration} s", fg="#FF9C75")
            self.after(500, self._poll)
            return
        role = self.current_role
        self.process = None
        self.current_role = None
        self.stop_btn.configure(state="disabled")
        try:
            if code != 0:
                raise RuntimeError(f"FFmpeg exited {code}. Check capture-station.log and the .part.mp4 file; existing footage was not overwritten.")
            result = finalize_recording(self.project, role)
            self.current.config(text="CAPTURE SAVED", fg=ACCENT)
            messagebox.showinfo("Webcam clip saved", f"{result.name}\nLocal original has been preserved.", parent=self)
        except Exception as exc:
            self.current.config(text="CAPTURE NEEDS ATTENTION", fg="#F8BB91")
            messagebox.showerror("Capture not finalized", str(exc), parent=self)
        self.refresh()

    def stop_webcam(self):
        if not self.process or self.process.poll() is not None or self.stop_requested:
            return
        self.stop_requested = True
        try:
            self.process.stdin.write(b"q\n")
            self.process.stdin.flush()
            self.current.config(text="STOPPING CAMERA, FINALIZING MP4…", fg="#FF9C75")
        except Exception as exc:
            messagebox.showwarning("Stop failed", f"{exc}\nCapture will end automatically by its timer.", parent=self)

    def refresh(self):
        """Rebuild session choices from disk; never infer an actual 3D-quality pass."""
        try:
            sessions = self.library.list_sessions()
            self.session_picker["values"] = [entry["id"] for entry in sessions]
            self.session_choice.set(self.project.name)
            info = self.library.describe_session(self.project.name)
            self.session_badge.configure(
                text=(f"{info['kind'].upper()}  /  {info['status'].upper()}  /  "
                      f"{info['captured_roles']} OF 6 FILES  /  "
                      "RECONSTRUCTION NOT CLINICALLY VALIDATED"),
                fg=ACCENT if info["can_register"] else "#F8BB91",
            )
            report = self.library.registration_readiness(self.project.name)
            for role in RAW_ROLES:
                exists = (self.project / "raw" / (role + ".mp4")).is_file()
                self.status_nodes[role].configure(
                    text="FILE PRESENT" if exists else "NEEDED",
                    fg=ACCENT if exists else "#F8BB91",
                )
            count = info["captured_roles"]
            if report.get("ready_to_register"):
                line = ("Six source files and board-entry preflight passed. Click Register six clips. "
                        "Actual synchronized/calibrated motion remains unverified.")
            elif info["status"] == "registered":
                line = ("SOURCE FILES REGISTERED. Recordings are frozen. Continue with real calibration, "
                        "synchronization and reconstruction quality gates in RUNBOOK.md.")
            elif not info["can_register"]:
                line = (f"{info['status'].upper()} / {info['kind'].upper()}: "
                        "inspection only; create a new REAL session to record or register footage.")
            else:
                problems = report.get("issues", [])
                missing = report.get("missing", [])
                line = f"{count}/6 captured. " + (
                    "Needs attention: " + " | ".join(problems[:2]) if problems
                    else "Missing: " + ", ".join(missing[:3])
                )
            self.summary.configure(text=line)
        except (OSError, ValueError, SessionError) as error:
            self.summary.configure(text="SESSION ERROR: " + str(error))

    def close_safe(self):
        if self.process is not None and self.process.poll() is None:
            messagebox.showwarning("Recording active", "Stop the webcam recording or allow its timer to finish before closing.", parent=self)
            return
        if self._workflow_running():
            messagebox.showwarning("Processing active", "The current guarded action must finish before closing.", parent=self)
            return
        self.destroy()


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="KineLab PT native Capture Station")
    parser.add_argument("--session-id", help="Start with a validated local session ID")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.smoke:
        app = CaptureApp(initial_session_id=args.session_id)
        try:
            app.update_idletasks()
            assert app.project.name in app.session_picker["values"]
            assert len(app.status_nodes) == len(RAW_ROLES)
            existing = app.project.name
            for entry in app.library.list_sessions():
                if entry["kind"] == "test-only":
                    app.session_choice.set(entry["id"])
                    app._choose_session()
                    assert app.project.name == entry["id"]
                    assert app.library.describe_session(entry["id"])["can_register"] is False
                    app.session_choice.set(existing)
                    app._choose_session()
                    break
            assert app.project.name == existing
            assert app.workflow is None
            # An incomplete session must show a blocked state, not start inference.
            from unittest.mock import patch
            with patch.object(messagebox, "showerror") as error_dialog:
                app.start_workflow("normalize")
                assert error_dialog.called
            assert not app._workflow_running()
            assert "BLOCKED" in app.workflow_label.cget("text")
            with patch.object(messagebox, "showerror") as sync_dialog:
                app.review_sync_cues()
                assert sync_dialog.called  # No registered & normalized video to inspect.
            with patch.object(messagebox, "showinfo") as recovery_dialog:
                app.inspect_recovery_ui()
                assert recovery_dialog.called
        finally:
            app.destroy()
        print("CAPTURE_GUI_SESSION_WORKFLOW_SYNC_RECOVERY_SMOKE_OK")
        return 0
    CaptureApp(initial_session_id=args.session_id).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
