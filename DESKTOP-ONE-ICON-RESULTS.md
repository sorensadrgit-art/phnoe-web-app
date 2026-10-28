# KineLab PT — One-icon Windows desktop cleanup

**Completed:** October 27, 2026, AgentZero Windows.

## Desktop result

The seven original KineLab shortcut files were moved byte-for-byte to:

C:\Users\soren\Documents\Projects\KineLab-PT-DualCam\launchers\desktop-archive-20261027

Exactly one desktop shortcut remains:

C:\Users\soren\OneDrive\Desktop\KineLab PT.lnk

This new icon opens kinelab_hub.py using the project's existing isolated Python environment, with the existing KineLab PT .ico. The hub presents Capture Station and Motion Lab as primary actions, and five research/test viewer shortcuts in a separate section. All launches are initiated by explicit user button press; the hub does not start recording, processing or uploading anything automatically.

## Preserved originals

- KineLab PT - Capture Station.lnk
- KineLab PT - Motion Lab.lnk
- KineLab PT - Gait Event Review.lnk
- KineLab PT - Full Walking Tracking.lnk
- KineLab PT - Caliscope Sample Videos.lnk
- KineLab PT - 2D Pose Test.lnk
- KineLab PT - TEST VIDEOS.lnk

All seven original shortcut hashes were verified after moving. The exact original targets and command-line arguments are recorded in SHORTCUT-MANIFEST.json inside the archive. The 14 other desktop shortcuts remained unchanged, including their SHA-256 hashes.

A previous interrupted move was rolled back successfully; its manifest is preserved separately as ROLLED-BACK-ATTEMPT-MANIFEST.json. The second attempt was syntax-checked and completed successfully.

## Verification

- Six new Python unit tests for the hub passed, including exact seven-link menu, launch dispatch, missing links, unknown keys, symlink/path escapes and test media separation.
- Tkinter GUI startup smoke passed.
- Opening the new desktop .lnk started the hub Python process. The two linked pythonw.exe process records are the virtual-environment launcher and its child Python process, not two different hub functions.
- No FFmpeg capture process appeared as a result.
- At final full regression: **146 Python tests passed; 23 JavaScript tests passed**; Vite build and both GUI startup smokes passed.
- Existing production viewer bundle size advisory remains; it is not a test failure.

## Reversal instructions (optional)

The original seven shortcuts can be copied back to the desktop without altering the archived copies using the restore script:

C:\Users\soren\Documents\Projects\KineLab-PT-DualCam\launchers\desktop-archive-20261027\RESTORE-ORIGINAL-DESKTOP-SHORTCUTS.ps1

Run the script with the explicit PowerShell switch -ConfirmRestore. It validates all original link hashes and refuses to overwrite existing desktop files. Restoring would add the seven original icons again; it does not remove the one-icon hub automatically.

## Scope

No original videos, real captures, test-session reports, Pose2Sim outputs, project environment, installed models, VPS files, or unrelated desktop items were changed by the shortcut cleanup. 
