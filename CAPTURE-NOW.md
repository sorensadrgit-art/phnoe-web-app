# KineLab PT — first real two-camera recording

**Current stage:** capture preparation. This is not clinical measurement or validation.

## Start (Windows desktop)

Double-click **KineLab PT - Capture Station**. The original **KineLab PT - Motion Lab** shortcut remains unchanged.

**Session library (v1 T1):** Use the **ACTIVE SESSION** selector at the top to reopen existing sessions or choose **New session** to create a unique real recording session. Creating a session never opens the camera or registers video. Each session has its own six source roles and physical board measurement. Existing mixed online test data is labeled **TEST-ONLY** and cannot be registered as real footage from this interface. Once six actual clips and a measured board entry pass file readiness, **Register six clips** binds the source hashes; this does not constitute measured camera calibration or synchronized reconstruction.

For a non-destructive retake, use **Stage alternate MP4** next to the relevant role, then explicitly **Accept staged take**. Any previously selected clip is archived under that session's `takes/archive/` before the newly selected clip is published to the active `raw/` filename. Registered sessions cannot be changed this way; start a new session for a different physical trial.

**Processing controls (v1 T2):** After explicitly registering one REAL session, use the capture window's **05 GUARDED LOCAL PROCESSING** controls in order: **Normalize six files**, **Calibrate + 2D pose**, **Reconstruct 3D**, then **Export marker-only**. Each is a separate, explicit local action; progress is the actual native stage state, never an invented percentage. Reconstruct 3D will refuse to start without independently observed synchronization cues in that session's `sync-observations.json`. The registered videos cannot be overwritten through this interface. Only previously passed and hashed stage outputs can be exported as motion JSON.

**Manually verify synchronization cues (v1 T3):** After normalized footage exists, click **Review start/end cues**. Inspect the two local normalized videos, scrub one frame at a time, mark the SAME visible start and end event independently for each camera, and select the reference camera (shorter video suggested). The app requires all four observed indices; rejects nonexistent frames, too-close cues or drift greater than one frame; and saves a no-overwrite `sync-observations.json`. The file is explicitly pending native Pose2Sim offset/reference/correlation verification and cannot establish clinical accuracy by itself. If the native reference or offset disagrees, the processing quality gate rejects the session—do not change observations merely to force a pass.

**Interrupted actions (v1 T3):** Use **Inspect / recover interrupted action**. The report is read-only until the user explicitly confirms archival of a proven orphaned `workflow.lock` or native `run.lock`. All failed/incomplete native artifacts remain unverified, and conflicting output inventories still require a clean session. This is not an automatic replay/resume feature.

**Cancel active processing:** This explicitly terminates the verified local subprocess tree, not the camera or unrelated programs. Incomplete native artifacts remain **UNVERIFIED**, and a native `run.lock` may require operator-assisted recovery. The UI never removes stale native locks automatically. Read RUNBOOK.md before retrying a cancelled calibration or Pose2Sim action.

The capture station only uses the local disk and the built-in **Integrated Webcam**. It **does not** turn on the webcam when launched. Recording begins only after you click **Record webcam** and confirm. Each recording ends automatically, or press **Stop camera recording**. No clips are sent to a VPS or cloud service.

## Equipment

- Your smartphone and your Alienware laptop's Integrated Webcam; no paid camera equipment.
- Printed calibration board from **Open printable checkerboard**; white paper is fine if kept flat and rigid.
- Ruler (measure **actual square side**), even lighting, a clear exercise area, and stable camera supports.
- Board: **8 columns × 10 rows of squares**, **7 × 9 inner corners**, specified square side **20 mm**. Print with **Actual Size / 100%**, not Fit or Scale to Page.
- Measure a real square side with the ruler. Enter the measured millimeters in the capture station; do not assume it is exactly 20 mm. If the physical measurement is outside 19.6–20.4 mm, reprint with corrected scale and remeasure.

## Camera layout

Place your phone at a front/diagonal view (Camera 1 / cam01). The webcam is Camera 2 / cam02, about 45–70 degrees from the phone's viewpoint. Ensure **both** cameras show the full person and feet throughout squatting, and both can see the calibration board. Use landscape phone video (prefer 1920 × 1080 at 30 FPS; 1280 × 720 at 30 FPS is also fine). Do not switch lenses, zoom, stabilization setting or orientation within a camera's six-file session. Different phone and webcam input resolutions are allowed; KineLab normalizes each.

**Do not move either camera between board calibration and the movement trial.** This is critical to multiview reconstruction. Keep the horizontal board flat on the ground when recording each extrinsics clip; board corners must appear in the **first frame**. Avoid mirrors, heavy occlusion and low light. If you need a new camera position, begin a new capture session and recalibrate.

## Required six videos

The prepared session folder is:

`C:\Users\soren\Documents\Projects\KineLab-PT-DualCam\projects\capture-20261026-trial01\raw`

| Clip | Camera | What to record |
|---|---|---|
| `cam01_intrinsics.mp4` | Phone | 25–40 s: move and tilt checkerboard across different image locations |
| `cam02_intrinsics.mp4` | Webcam | Use the station's **Record webcam · 35 s**, vary board position and tilt |
| `cam01_board.mp4` | Phone | Stationary horizontal board visible in **first frame** |
| `cam02_board.mp4` | Webcam | **Record webcam · 12 s**, same board stationary in first frame |
| `cam01_trial.mp4` | Phone | One person; visibly shared start and end cues; 3 controlled squats |
| `cam02_trial.mp4` | Webcam | **Record webcam · 60 s**, overlapping **same** phone trial with same cues |

The two intrinsic calibration videos are captured with each camera held in its final location and *the checkerboard moved through space*. Board clips may be recorded sequentially so long as the board remains fixed and visible; the trial clips must overlap in real time.

For the trial, start webcam first and phone immediately afterward. Once both recorders are running, make a **sharp, visible hand movement** (start cue), perform 3 slow squats, then repeat a sharp visible hand movement (end cue), all before either camera stops. Ensure cues are visible from both angles. This facilitates measuring synchronization and drift independently. No automatic synchronization claim can be made from nominal 30 FPS alone.

Use the phone's camera app. Transfer the three **MP4 files** to Windows by USB, then use each **Import phone MP4** button. The importer makes a byte-for-byte checked copy and preserves the selected source. **Do not merely rename a .MOV file to .mp4**; that changes the extension but not the video container. If your phone produces MOV, retain it safely and obtain a proper MP4 copy before using this v1 station.

The station records webcam MP4 clips directly with FFmpeg at 1280 × 720 / 30 FPS. Each button refuses to overwrite an existing clip or unfinished `.part.mp4`. If a take fails, preserve it, open the raw folder, and manually relocate it before trying a new take; do not delete data needed for troubleshooting.

## After all six exist

Click **Refresh + check all six**. The station verifies file readability and cross-recording resolution/orientation consistency and records the physical board measurement separately. This **does not** establish checkerboard view diversity, calibration residuals, synchronized events, or physical accuracy.

Then use PowerShell in the KineLab project root to perform the gated processing:

```powershell
$kinelabRoot = 'C:\Users\soren\Documents\Projects\KineLab-PT-DualCam'
$kinelabTrial = Join-Path $kinelabRoot 'projects\capture-20261026-trial01'
$kinelabPython = Join-Path $kinelabRoot '.venv\Scripts\python.exe'
& $kinelabPython -B (Join-Path $kinelabRoot 'capture_station.py') --project $kinelabTrial check
& $kinelabPython -B (Join-Path $kinelabRoot 'setup_project.py') --project $kinelabTrial --register-captures
& $kinelabPython -B (Join-Path $kinelabRoot 'normalize_capture.py') --project $kinelabTrial
```

Only proceed when the preceding gate passes. Continue **RUNBOOK.md** sections 3–5 for Pose2Sim calibration, 2D detection, independent start/end synchronization measurement, two-view quality, marker-only export, optional OpenSim, and Blender/Three.js. A metadata checker is not proof of clinical-grade accuracy.

## Software validation vs. real-person validation

The built-in software demos/tests prove program behavior. They do not validate measurement quality for your home camera setup. Your first real capture must pass *measured* reprojection and independent synchronization checks (including start-to-end drift), followed by 3D reconstruction quality and offline replay. OpenSim joint angles additionally require subject/model values that are actually measured.
