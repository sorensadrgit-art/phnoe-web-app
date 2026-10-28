# KineLab PT v1.0 — T3 synchronization and recovery implementation

Local execution host: AgentZero, October 27, 2026. This checkpoint reports implemented software and synthetic test coverage, not physical measurement validation.

## Delivered

- sync_evidence.py: creates an immutable, source-hash-bound sync-observations.json only from four explicitly marked, visible start/end events in the two normalized videos. Computes the signed other-camera offset using independently observed start frames, checks end drift within one frame, and preserves native reference/correlation as a separate, later acceptance gate.
- sync_review_gui.py: operator-requested offline side-by-side frame inspector, actual decoded frame index checks, per-camera frame scrubbing, manual Start/End marks, explicit confirmation, and no-overwrite evidence publication. It never starts webcams or fabricates cue frames.
- workflow_recovery.py: read-only worker/native lock and run-manifest diagnostics. Explicit archiving only of locks whose owner PID is no longer running and no related worker was detected; archives rather than deleting the lock. Partial run artifacts remain unverified and are never automatically marked passed.
- capture_station_gui.py: Review start/end cues and Inspect / recover interrupted action controls. Camera recording and background processing remain operator-triggered. Existing capture and export behavior preserved.
- RUNBOOK.md and CAPTURE-NOW.md updated with native sync quality requirements, measured cue protocol, and recovery cautions.
- tests/test_sync_evidence.py, tests/test_sync_review_gui.py, tests/test_workflow_recovery.py: coverage for four observed cues, offsets and drift, immutable outputs, mismatched source hashes, test-only refusal, native quality contract with synthetic logs, actual FFmpeg MP4 frame decoding, GUI cue marking, and safe/orphan/active lock states.

## Fresh verification

- **114 Python tests passed.**
- **10 JavaScript tests passed.**
- Vite build passed; existing code-size advisory remains.
- Capture Station GUI session/workflow/sync/recovery startup smoke passed.
- Real source webcam captures cam02_board.mp4 and cam02_trial.mp4 retain SHA-256 parity with existing copies; no camera was automatically recording.
- Prepared real trial remains **unregistered**, with only two real webcam MP4s and no sync-observations.json — correct fail-closed state.
- Artifacts: C:\Users\soren\Projects\kinelab-team\evidence\v1-execution\t3-full-python.log, t3-js.log, t3-vite.log.
- Rollback baseline: C:\Users\soren\Projects\kinelab-team\snapshots\pre-v1-execution-20261026.

## Important limits

- Manual start/end cue evidence has been tested with synthetic normalized timing/video fixtures; it has NOT passed a genuine two-camera Pose2Sim synchronization and reconstruction session.
- Real native reference/correlation and independent physical accuracy remain unmeasured. No online test video can stand in for synchronized real footage.
- Interrupted/native stage output recovery remains conservative; archiving a truly abandoned lock is not a guarantee that the previous stage inventory is reusable. A clean session may still be required.
- T4–T10 remain pending: synchronized consumer review/graphs, full analysis, unified React shell, local reports, clean-machine offline installer, real physical workflow pilot and release sign-off.
