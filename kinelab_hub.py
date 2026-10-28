"""One KineLab desktop launcher for seven safely archived, original shortcuts.

No webcam recording, pose inference, exports or network operations occur on
startup. User must choose which original shortcut to launch.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "launchers" / "desktop-archive-20261027"

HUB_ENTRIES = (
    {"key": "capture", "category": "core", "title": "Capture Station",
     "subtitle": "Phone + webcam recording, sessions, and quality gates",
     "filename": "KineLab PT - Capture Station.lnk"},
    {"key": "motion", "category": "core", "title": "Motion Lab",
     "subtitle": "3D skeleton, playback, ROM graphs, and video review",
     "filename": "KineLab PT - Motion Lab.lnk"},
    {"key": "gait", "category": "test", "title": "Gait Event Review",
     "subtitle": "2D walking-event hypotheses and manual reference review",
     "filename": "KineLab PT - Gait Event Review.lnk"},
    {"key": "tracking", "category": "test", "title": "Full Walking Tracking",
     "subtitle": "Annotated 720-frame walking analysis and confidence plots",
     "filename": "KineLab PT - Full Walking Tracking.lnk"},
    {"key": "caliscope", "category": "test", "title": "Caliscope Sample Videos",
     "subtitle": "Two-angle walking and calibration source videos",
     "filename": "KineLab PT - Caliscope Sample Videos.lnk"},
    {"key": "pose", "category": "test", "title": "2D Pose Test",
     "subtitle": "Two-camera annotated skeleton comparison image",
     "filename": "KineLab PT - 2D Pose Test.lnk"},
    {"key": "mixed", "category": "test", "title": "Original Test Videos",
     "subtitle": "Legacy unrelated test clips; not synchronized or calibrated",
     "filename": "KineLab PT - TEST VIDEOS.lnk"},
)

BG = "#09151F"
PANEL = "#162936"
BORDER = "#2F4D5B"
FG = "#ECFAF8"
MUTED = "#A7C0C9"
ACCENT = "#65E6D4"
WARNING = "#EFC19D"


def _find_entry(entry_key: str) -> dict:
    if not isinstance(entry_key, str):
        raise ValueError("Only an existing KineLab launcher action may be selected")
    for item in HUB_ENTRIES:
        if item["key"] == entry_key:
            return item
    raise ValueError("Unknown KineLab launcher action")


def resolve_shortcut(entry_key: str, archive: Path = ARCHIVE) -> Path:
    entry = _find_entry(entry_key)
    archive = Path(archive)
    if archive.is_symlink():
        raise ValueError("Shortcut archive symlinks are not permitted")
    path = archive / entry["filename"]
    if path.is_symlink() or path.resolve().parent != archive.resolve():
        raise ValueError("The shortcut must remain in its designated local archive")
    if not path.is_file():
        raise FileNotFoundError("Original shortcut is missing: " + str(path))
    return path


def launch_shortcut(entry_key: str, archive: Path = ARCHIVE) -> Path:
    path = resolve_shortcut(entry_key, archive=archive)
    os.startfile(str(path))   # Windows ShellExecute retains original shortcut args.
    return path


def label(parent, content, size=10, color=FG, strong=False, wrap=0):
    return tk.Label(parent, text=content, bg=parent.cget("bg"), fg=color,
                    font=("Segoe UI", size, "bold" if strong else "normal"),
                    anchor="w", justify="left", wraplength=wrap)


class KineLabHub(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("KineLab PT - Application Hub")
        self.geometry("890x755")
        self.minsize(750, 590)
        self.configure(bg=BG)
        icon=ROOT / "assets" / "kinelab-pt.ico"
        if icon.is_file():
            self.iconbitmap(str(icon))
        self._draw()

    def _draw(self):
        head=tk.Frame(self,bg=BG,padx=26,pady=17)
        head.pack(fill="x")
        label(head,"KINELAB PT  /  SINGLE LAUNCHER",10,ACCENT,True).pack(anchor="w")
        label(head,"Your motion lab, in one place.",24,strong=True).pack(anchor="w",pady=(6,3))
        label(head,"Choose a tool to open. No camera turns on until you explicitly record.",
              10,MUTED).pack(anchor="w")
        body=tk.Frame(self,bg=BG,padx=24)
        body.pack(fill="both",expand=True)
        label(body,"MAIN APPLICATION",10,ACCENT,True).pack(anchor="w",pady=(5,10))
        core=tk.Frame(body,bg=BG)
        core.pack(fill="x")
        for item in (entry for entry in HUB_ENTRIES if entry["category"]=="core"):
            self._card(core,item,True).pack(side="left",fill="both",expand=True,padx=(0,10),pady=(0,12))
        label(body,"RESEARCH / TEST VIEWERS",10,ACCENT,True).pack(anchor="w",pady=(5,6))
        label(body,"These are demonstration datasets, not calibrated clinical results.",
              9,MUTED).pack(anchor="w",pady=(0,9))
        grid=tk.Frame(body,bg=BG)
        grid.pack(fill="both",expand=True)
        for col in (0,1):
            grid.grid_columnconfigure(col,weight=1,uniform="tools")
        tests=[x for x in HUB_ENTRIES if x["category"]=="test"]
        for n,item in enumerate(tests):
            self._card(grid,item,False).grid(row=n//2,column=n%2,sticky="nsew",
                                            padx=(0,10),pady=(0,8))
        footer=tk.Frame(self,bg=BG,padx=26,pady=12)
        footer.pack(fill="x")
        label(footer,"7 original launchers safely preserved  |  unrelated desktop icons unchanged",
              9,MUTED).pack(side="left")
        tk.Button(footer,text="Open saved shortcuts",command=self._open_archive,
                  bg=PANEL,fg=FG,borderwidth=0,relief="flat",cursor="hand2",
                  font=("Segoe UI",9),padx=12,pady=7).pack(side="right")

    def _card(self,parent,item,core):
        panel=tk.Frame(parent,bg=PANEL,highlightbackground=BORDER,
                       highlightthickness=1,padx=13,pady=10)
        label(panel,item["title"],13 if core else 10,strong=True).pack(anchor="w",pady=(0,4))
        label(panel,item["subtitle"],9,MUTED,wrap=335).pack(anchor="w")
        row=tk.Frame(panel,bg=PANEL)
        row.pack(fill="x",pady=(8 if core else 4,0))
        if not core:
            label(row,"TEST ONLY",8,WARNING,True).pack(side="left")
        tk.Button(row,text="Open app" if core else "Open viewer",
                  command=lambda key=item["key"]: self._launch(key),
                  bg=ACCENT if core else "#254855",
                  fg="#06252A" if core else FG,activebackground="#8CF2E6",
                  cursor="hand2",borderwidth=0,relief="flat",
                  font=("Segoe UI",9,"bold"),padx=12,pady=7).pack(side="right")
        return panel

    def _launch(self,key):
        try:
            launch_shortcut(key)
        except (FileNotFoundError,ValueError,OSError) as err:
            messagebox.showerror("KineLab launcher unavailable",str(err),parent=self)

    def _open_archive(self):
        try:
            if not ARCHIVE.is_dir():
                raise FileNotFoundError("Shortcuts archive is missing: "+str(ARCHIVE))
            os.startfile(str(ARCHIVE))
        except (FileNotFoundError,OSError) as err:
            messagebox.showerror("Cannot open saved shortcuts",str(err),parent=self)


def main():
    app=KineLabHub()
    if "--smoke" in sys.argv:
        try:
            app.update_idletasks()
            assert len(HUB_ENTRIES)==7
            assert app.title()=="KineLab PT - Application Hub"
        finally:
            app.destroy()
        print("KINELAB_ONE_ICON_HUB_GUI_SMOKE_OK")
        return 0
    app.mainloop()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
