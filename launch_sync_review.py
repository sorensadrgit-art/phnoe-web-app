"""Open the preexisting KineLab exact-frame sync reviewer for the selected session."""
from __future__ import annotations

import argparse
import sys
import tkinter as tk
from tkinter import messagebox

from session_library import SessionLibrary
from sync_evidence import normalized_videos
from sync_review_gui import SyncReviewWindow

ROOT = __import__("pathlib").Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="KineLab PT native manual sync review")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--check", action="store_true", help="Check evidence gate without opening UI")
    args = parser.parse_args()
    project = SessionLibrary(ROOT / "projects").open_session(args.session_id)
    try:
        normalized_videos(project)
    except (ValueError, OSError) as error:
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
