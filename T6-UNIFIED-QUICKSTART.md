# KineLab PT — Unified Desktop Quickstart (T6)

## Open the application
On AgentZero, double-click **KineLab PT** on your Windows desktop. It now opens the single integrated local React workspace in your browser. The application starts or reuses its local-only service and does not automatically turn on a camera, process files, or upload footage.

If the page says you are unauthorized or shows only legacy Motion Lab, reopen it from the **KineLab PT desktop icon** rather than manually typing the localhost port. The application uses an ephemeral local authorization token passed by the launcher.

## Sections
- **Overview:** See your active session, count of captured source files, and live stage status.
- **Sessions:** Choose an existing session or explicitly create a new REAL draft session. Use TEST ONLY folders solely for software demos.
- **Capture:** Import each phone MP4 into its corresponding cam01 role. Use explicit consent to record webcam cam02 roles. Print and physically measure the board. Register six source files only when all file gates actually pass. The button **Open original camera station** opens the native Tkinter tools with your selected session.
- **Process:** Choose one guarded native action at a time (normalize, calibrate/pose, reconstruct, export). Missing recorded sync cues or failing stage quality will still block subsequent steps. For exact-frame human start/end review, choose **Open native frame review**.
- **3D Motion:** View the existing skeleton and descriptive joint-angle graphs. Demo movement does not establish real clinical measurement.
- **Analysis:** Open the Caliscope gait experiment; manual reference annotations remain separate from automatic event candidates. Squat analysis currently uses synthetic-test verification only.
- **Reports:** Download existing local session evidence. T7 professional PDF reports and historical comparisons are not implemented yet.
- **Diagnostics:** Inspect local API and stage status, review recovery locks and open the runbook.

## Data and safety
- Source footage and run manifests are stored locally in `projects/<session>/`.
- The existing import, file/hash registration, physical measurement entry, normalization and Pose2Sim reconstruction gates are retained.
- Do not present sample Caliscope footage as true calibrated patient or phone/webcam motion.
- Closing the browser does not change or delete original footage or an active native job. Use processing controls to cancel native work with explicit confirmation.
- The localhost access token is private app state; do not share your browser URL or the local instance state file.

## Technical and recovery
- Unified service: loopback 127.0.0.1; the selected port can change if occupied.
- Current code: `t6_service.py`, `t6_server.py`, `t6_launcher.py`; integrated UI: `viewer/src/UnifiedApp.jsx`.
- Original single-icon link and before-T6 sources are backed up at `launchers/t6-pre-integration-backup-20261027/`. The seven old individual shortcuts are archived under `launchers/desktop-archive-20261027/`.
- Acceptance record: `V1-T6-RESULTS.md`. Detailed pipeline instructions: `RUNBOOK.md`.
- T7–T10 and real calibrated capture acceptance are still future work; KineLab PT v1.0 is not certified or released as a clinical measurement system.
