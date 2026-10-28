# KineLab PT Capture Station — local implementation result

Date: 2026-10-26. Target device: AgentZero (Alienware Windows PC).
Target root: `C:\Users\soren\Documents\Projects\KineLab-PT-DualCam`.

## Created, without replacing the original Pose2Sim pipeline
- `capture_station.py`: six-role file preflight, FFprobe geometry and duration metadata, explicitly-confirmed local FFmpeg webcam recording command, publish-only-valid webcam MP4, no-overwrite phone MP4 import with byte-level source matching, physical board measurement recording. No camera is opened on import.
- `capture_station_gui.py`: dark Tkinter capture station with webcam Record/Stop buttons, phone MP4 import controls, printable board button, measurement form, step instructions, read-only readiness status, and scrolling.
- `tests/test_capture_station.py`: 13 new tests including real FFmpeg synthetic MP4 finalization and actual demo-MP4 import bytes.
- `assets/checkerboard_20mm.svg`: printable 8 × 10 checkerboard at 20 mm square side, actual-size printing required.
- `CAPTURE-NOW.md`: physical capture operator instructions and exact PowerShell continuation commands.
- Desktop shortcut: `C:\Users\soren\OneDrive\Desktop\KineLab PT - Capture Station.lnk`. Original motion viewer shortcut unchanged.

## Checks executed
- Windows PnP: Integrated Webcam present. FFmpeg DirectShow lists 1280×720 at 30fps with YUYV422. Enumeration only; no live webcam recording was initiated.
- New test suite initially red on missing module; after implementation, 13 capture-station tests pass.
- Full local suite: 66 Python tests passed; 10 JavaScript tests passed; Vite built; GUI startup smoke succeeded; local viewer returned HTTP 200.
- Real existing demo MP4 copied to an isolated test session with SHA256 preservation. Synthetic FFmpeg-generated 1280×720 MP4 finalized via capture station's public validation path.
- Desktop shortcut exists and resolves to isolated `pythonw.exe` + `capture_station_gui.py`. Windows process verified. No webcam recording process detected.
- Real trial: zero of six raw MP4 inputs. No `session.json` was created. No fake measured board, synchronization observations, or claim of 3D accuracy.

## Operator requirements before first real acceptance
Print the board at Actual Size, physically measure the printed 20 mm squares and enter measured value; keep camera geometry/lens/settings fixed; acquire all six actual files. Start and end visible sync cues in the overlapping trial are mandatory. Inspect capture readiness, register six sources, normalize and run existing Pose2Sim stages. Require native RMS and independent sync evidence, observed two-view reconstruction, then marker-only export; only consider OpenSim angles after confirming subject/model assumptions. Finally repeat from clean project folder without reliance on network before claiming offline replay.

The capture assistant does not silently adjust the existing Pose2Sim/normalization rules, delete VPS resources or upload private footage.
