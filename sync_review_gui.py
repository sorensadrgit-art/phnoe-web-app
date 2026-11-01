"""Manual frame-accurate sync cue review for the two normalized camera files.

Opens only after the operator requests review; no device capture or network I/O.
This screen does not certify calibration. Only Pose2Sim's native stage can do
the subsequent comparison, and clinical accuracy is independently unverified.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import cv2
from PIL import Image, ImageTk

from sync_evidence import (
    CAMERAS,
    SyncEvidenceError,
    normalized_videos,
    prepare_sync,
    save_sync,
    suggested_reference,
)

BG = "#0B1722"
PANEL = "#142737"
TEXT = "#EDF6FA"
MUTED = "#A7BAC6"
ACCENT = "#64E9DF"
ERROR = "#FFAF8B"


class FrameReviewError(ValueError):
    pass


def release_widget_references(owner: tk.Misc) -> None:
    """Drop an already-destroyed window's references to its child widgets and Tk images.

    Child widgets (via `master`) and Tk variables (via `_root`) can point back to the window, so
    attributes holding them form reference cycles. Left to the cyclic collector, the final Tcl
    reference may be dropped on a non-Tk thread, which leaks the Tcl interpreter.
    """
    for name, value in list(vars(owner).items()):
        if name == "master":
            continue
        if isinstance(value, (tk.Misc, tk.Variable)):
            delattr(owner, name)
        elif isinstance(value, dict) and any(
                isinstance(item, (tk.Misc, ImageTk.PhotoImage)) for item in value.values()):
            value.clear()


def read_exact_frame(capture, requested: int):
    """Seek then verify the decoded frame index; never show a different cue frame."""
    if type(requested) is not int or requested < 0:
        raise FrameReviewError("Invalid frame index")
    if not capture.set(cv2.CAP_PROP_POS_FRAMES, requested):
        raise FrameReviewError("Cannot seek to selected video frame")
    ok, frame = capture.read()
    if not ok or frame is None:
        raise FrameReviewError(f"Cannot decode video frame {requested}")
    actual = round(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
    if actual != requested:
        raise FrameReviewError(f"Requested frame {requested}, but decoded frame {actual}; do not mark this cue")
    return frame


class SyncReviewWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, project: Path):
        self.session, self.videos = normalized_videos(project)
        self.project = Path(project).resolve()
        if (self.project / "sync-observations.json").exists():
            raise SyncEvidenceError("Existing sync-observations.json is immutable; use a clean session to remark cues")
        super().__init__(parent)
        self.title(f"KineLab PT | Inspect synchronization cues | {self.project.name}")
        self.geometry("1130x790")
        self.minsize(960, 640)
        self.configure(bg=BG)
        self.readers: dict[str, cv2.VideoCapture] = {}
        self.marks: dict[str, dict[str, int]] = {camera: {} for camera in CAMERAS}
        self.frame_verified: dict[str, int | None] = {camera: None for camera in CAMERAS}
        self.preview_widgets: dict[str, tk.Label] = {}
        self.frame_widgets: dict[str, tk.Label] = {}
        self.message_widgets: dict[str, tk.Label] = {}
        self.scales: dict[str, tk.Scale] = {}
        self.photo_refs: dict[str, ImageTk.PhotoImage] = {}
        self.reference = tk.StringVar(value=suggested_reference(self.project))
        try:
            for camera in CAMERAS:
                path = self.videos[camera]["path"]
                cap = cv2.VideoCapture(str(path))
                if not cap.isOpened():
                    cap.release()
                    raise FrameReviewError("Cannot open normalized footage for " + camera)
                self.readers[camera] = cap
            self._build()
            for camera in CAMERAS:
                self._show(camera, 0)
            self.protocol("WM_DELETE_WINDOW", self.close)
        except Exception:
            for cap in self.readers.values():
                cap.release()
            self.destroy()
            raise

    def _label(self, parent, value, *, size=10, color=TEXT, bold=False):
        return tk.Label(parent, text=value, bg=parent.cget("bg"), fg=color,
                        anchor="w", justify="left",
                        font=("Segoe UI", size, "bold" if bold else "normal"))

    def _button(self, parent, value, action, *, strong=False):
        return tk.Button(parent, text=value, command=action, relief="flat",
                         cursor="hand2", padx=10, pady=6,
                         bg=ACCENT if strong else "#1C4051",
                         fg="#05242E" if strong else TEXT,
                         activebackground="#9AFFEB",
                         font=("Segoe UI", 10, "bold"))

    def _build(self):
        header = tk.Frame(self, bg=BG, padx=24, pady=19)
        header.pack(fill="x")
        self._label(header, "03  /  INDEPENDENT TWO-CAMERA CUE REVIEW",
                    size=10, bold=True, color=ACCENT).pack(anchor="w")
        self._label(header, f"Session: {self.project.name}", size=18, bold=True).pack(anchor="w", pady=5)
        self._label(header,
                    "Mark the same visible START and END event separately in both normalized 30 FPS videos. "
                    "This generates independent operator observations; native Pose2Sim verification must still pass.",
                    color=MUTED, size=10).pack(anchor="w")

        panes = tk.Frame(self, bg=BG, padx=15, pady=5)
        panes.pack(fill="both", expand=True)
        for camera in CAMERAS:
            p = tk.Frame(panes, bg=PANEL, padx=12, pady=10)
            p.pack(side="left", fill="both", expand=True, padx=7)
            self._label(p, f"{camera.upper()}  /  {self.videos[camera]['frames']} normalized frames",
                        bold=True, size=12, color=ACCENT).pack(anchor="w")
            preview = tk.Label(p, bg="#08121B")
            preview.pack(fill="x", pady=(9, 9))
            self.preview_widgets[camera] = preview
            frame_label = self._label(p, "Frame 0 / timestamp 0.000 s",
                                      size=10, color=TEXT, bold=True)
            frame_label.pack(anchor="w")
            self.frame_widgets[camera] = frame_label
            slider = tk.Scale(
                p, from_=0, to=self.videos[camera]["frames"] - 1,
                orient="horizontal", showvalue=False, resolution=1,
                length=450, bg=PANEL, fg=TEXT, troughcolor="#305467",
                highlightthickness=0, activebackground=ACCENT,
                command=lambda v, cam=camera: self._show(cam, int(float(v))),
            )
            slider.pack(fill="x")
            self.scales[camera] = slider
            move = tk.Frame(p, bg=PANEL)
            move.pack(anchor="w", pady=(3, 8))
            self._button(move, "◀ Previous frame",
                         lambda cam=camera: self._step(cam, -1)).pack(side="left", padx=(0, 7))
            self._button(move, "Next frame ▶",
                         lambda cam=camera: self._step(cam, 1)).pack(side="left")
            mark = tk.Frame(p, bg=PANEL)
            mark.pack(anchor="w", pady=(3, 7))
            self._button(mark, "Mark START", lambda cam=camera: self._mark(cam, "start"),
                         strong=True).pack(side="left", padx=(0, 7))
            self._button(mark, "Mark END", lambda cam=camera: self._mark(cam, "end"),
                         strong=True).pack(side="left")
            marked = self._label(p, "START: —  /  END: —", color=MUTED, size=10)
            marked.pack(anchor="w")
            self.message_widgets[camera] = marked

        bottom = tk.Frame(self, bg=BG, padx=24, pady=17)
        bottom.pack(fill="x")
        row = tk.Frame(bottom, bg=BG)
        row.pack(fill="x")
        self._label(row, "Reference camera (native Pose2Sim must agree):",
                    color=MUTED).pack(side="left", padx=(0, 10))
        chooser = ttk.Combobox(row, textvariable=self.reference,
                               values=list(CAMERAS), state="readonly", width=10)
        chooser.pack(side="left")
        self._label(row, "Shorter video suggested; operator selection is NOT native confirmation.",
                    size=9, color=MUTED).pack(side="left", padx=14)
        self._button(bottom, "Save four observed cue frames",
                     self._save, strong=True).pack(anchor="w", pady=(15, 8))
        self.status = self._label(
            bottom, "Nothing measured yet. Choose each video frame and explicitly mark both cues.",
            color=MUTED, size=9,
        )
        self.status.pack(anchor="w")
        self._label(bottom,
                    "Warning: creating observations does not establish calibration, reconstruction quality, "
                    "physical accuracy, or clinical validity.",
                    size=9, color=ERROR).pack(anchor="w", pady=3)

    def _show(self, camera: str, index: int):
        cap = self.readers[camera]
        try:
            frame = read_exact_frame(cap, index)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            thumbnail = Image.fromarray(rgb)
            thumbnail.thumbnail((480, 265), Image.Resampling.LANCZOS)
            self.photo_refs[camera] = ImageTk.PhotoImage(thumbnail)
            self.preview_widgets[camera].configure(image=self.photo_refs[camera], text="")
            self.frame_verified[camera] = index
            self.frame_widgets[camera].configure(
                text=f"Decoded frame {index} of {self.videos[camera]['frames'] - 1} | {index / 30:.3f} s",
                fg=TEXT,
            )
        except (FrameReviewError, OSError, ValueError) as error:
            self.frame_verified[camera] = None
            self.frame_widgets[camera].configure(text=str(error), fg=ERROR)

    def _step(self, camera: str, amount: int):
        slider = self.scales[camera]
        target = max(0, min(self.videos[camera]["frames"] - 1, int(slider.get()) + amount))
        slider.set(target)

    def _mark(self, camera: str, cue: str):
        current = self.frame_verified[camera]
        if current is None:
            messagebox.showerror("Invalid frame", "The exact selected video frame was not decoded.", parent=self)
            return
        self.marks[camera][cue] = current
        state = self.marks[camera]
        self.message_widgets[camera].configure(
            text=f"START: {state.get('start', '—')}  /  END: {state.get('end', '—')}",
            fg=ACCENT,
        )
        self.status.configure(text=f"Marked {camera} {cue.upper()} at normalized video frame {current}.",
                              fg=TEXT)

    def _save(self):
        try:
            record = prepare_sync(self.project, self.marks, reference=self.reference.get(),
                                  operator_confirmed=True)
            offsets = ", ".join(f"{k}={v['offset_frames']:+d} frames"
                                for k, v in record["cameras"].items())
            if not messagebox.askyesno(
                "Confirm independent observed cues",
                "Did you personally inspect and mark the SAME start and end events in both "
                "normalized camera videos?\n\n"
                f"Reference selected: {record['reference']}\nObserved offsets: {offsets}\n\n"
                "These cues are NOT YET VERIFIED against the native Pose2Sim results. "
                "Saving does not certify physical accuracy.\n\nSave the immutable observation record?",
                parent=self,
            ):
                return
            path = save_sync(self.project, self.marks, reference=self.reference.get(),
                             operator_confirmed=True)
            self.status.configure(text=f"Saved operator observations: {path.name} — NATIVE SYNC PENDING",
                                  fg=ACCENT)
            messagebox.showinfo(
                "Observations saved",
                f"{path}\n\nThe next native synchronization run must independently confirm "
                "the reference, signed offset, and start/end residuals.",
                parent=self,
            )
        except (SyncEvidenceError, FileExistsError, OSError, ValueError) as error:
            self.status.configure(text="SYNC EVIDENCE BLOCKED: " + str(error), fg=ERROR)
            messagebox.showerror("Cannot save observations", str(error), parent=self)

    def close(self):
        for cap in self.readers.values():
            cap.release()
        self.destroy()

    def destroy(self):
        super().destroy()
        release_widget_references(self)
