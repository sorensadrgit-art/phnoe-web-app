"""Open the preexisting KineLab exact-frame sync reviewer for the selected session."""
from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from runtime_config import is_reparse, resolve_data_root
from session_library import SessionError, SessionLibrary
from sync_evidence import normalized_videos
from sync_review_gui import SyncReviewWindow

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="KineLab PT native manual sync review")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--data-root", type=Path, required=True,
                        help="Candidate data root that owns the session (the launcher passes its own)")
    parser.add_argument("--check", action="store_true", help="Check evidence gate without opening UI")
    args = parser.parse_args()
    try:
        data_root = resolve_data_root(args.data_root)
        for part in (data_root, *data_root.parents):
            if is_reparse(part):
                raise ValueError("DATA_ROOT_UNSAFE: linked or reparse directories are refused")
        if not data_root.is_dir():
            raise ValueError("DATA_ROOT_MISSING: start KineLab PT with t6_launcher.py --data-root first")
        project = SessionLibrary(data_root).open_session(args.session_id)
        normalized_videos(project)
    except (ValueError, OSError, SessionError) as error:
        if args.check:
            print("SYNC_NOT_READY=" + str(error), file=sys.stderr)
            return 2
        root = tk.Tk()
        root.withdraw()
        try:
            messagebox.showerror("Sync review blocked", str(error), parent=root)
        finally:
            root.destroy()
        return 2
    if args.check:
        print("SYNC_EVIDENCE_PREREQUISITES_PRESENT")
        return 0
    root = tk.Tk()
    root.withdraw()
    try:
        SyncReviewWindow(root, project)
        root.mainloop()
    finally:
        root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
