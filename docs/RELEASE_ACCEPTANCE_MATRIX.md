# KineLab PT — Release Acceptance Matrix

## Milestone Verification Summary

| Gate | Description | Status | Verification Evidence |
|---|---|---|---|
| **G0** | Preflight, Audit & Rollback Snapshot | **PASS** | Rollback snapshot in `KineLab-G0-Snapshots\g0-20261027-215915`. 5,593 files hashed, 0 mismatches. Baseline 189 Python & 33 JS tests passed. |
| **G1** | T6 Architecture & Security Stabilization | **PASS** | Localhost-only (127.0.0.1), token authentication in URL fragment, DNS rebinding rejection, path traversal rejection, concurrent upload lock, oversized payload TCP drain. 31/31 server & service tests pass. |
| **G2** | Guided Capture Wizard & Evidence Passport | **PASS** | 10-stage passport state machine (`EMPTY` → `RESEARCH_REPORTABLE`), 6-role camera registration, checkerboard calibration check, visual sync cue protocol. Verified in `EvidencePassport.jsx` & `GuidedCaptureWizard.jsx`. |
| **G3** | Native Processing Pipeline & 3D Correctness | **PASS** | Multi-camera triangulation, OpenSim IK processing, marker augmentation LSTM validation, unit mappings (degrees/radians), non-uniform timestamp lookup. 10/10 motion data tests pass. |
| **G4** | Motion Lab, Gait & Squat Analysis Integration | **PASS** | Gait event detection (initial contact, toe-off, cadence, step length), squat depth & symmetry metrics, Three.js 3D skeleton review, dual synchronized camera playback. |
| **G5** | T7 SQLite History, Reports & Staged Backup/Restore | **PASS** | SQLite `.kinelab_index.db` metadata indexing, multi-page vector PDF reports (`report_builder.py`), machine-readable JSON & CSV exports, atomic backup & restore with 100% SHA-256 verification (`backup_manager.py`). |
| **G6** | T8 Windows Offline Distribution Package | **PASS** | Standalone portable bundle `dist/KineLabPT-v1.0.0-windows-x64.zip` (SHA-256: `ee627f33a07977b8972c7a0c8ddc0edc2d2b406c253c5f4be4dc96163ff538e5`). Single desktop shortcut script `Install-DesktopShortcut.ps1`. Offline documentation and manifests. |
| **G7** | Accessibility, UX & Performance Hardening | **PASS** | WCAG 2.1 AA focus-visible outlines, contrast compliance, `@media (prefers-reduced-motion: reduce)`, Vite production bundle under 1.2 MB gzipped to 335 KB, instant localhost reuse. |
| **G8** | Private Feature Branch Staging & PR | **PASS** | Vetted source code staged to private repository `phnoe-web-app` on feature branch `feature/kinelab-v1-finalization`. Zero PHI, zero video binaries, zero tokens in Git. |
| **G9** | Source Media Verification & Truthful Status | **PASS** | Source media hashes verified unchanged (`cam02_board.mp4`, `cam02_trial.mp4`). Truthful status declaration: `SOFTWARE_BUILD_VERIFIED`, `BLOCKED_ON_PHYSICAL_EVIDENCE`, `CLINICAL_VALIDATION: UNVERIFIED`. |

---

## Detailed Acceptance Gates

### Gate 1: Security & Session Isolation
- [x] Server listens exclusively on `127.0.0.1`.
- [x] Host header validation rejects DNS rebinding (`evil.com`, `attacker.local`).
- [x] Session tokens passed only via HTTP `Authorization: Bearer <token>` or browser URL fragment `#access=<token>`, never logged or transmitted in query strings.
- [x] URL-encoded traversal (`..%2f`, `%00`) rejected with 404/403.
- [x] Concurrent uploads to the same camera role reject collisions with HTTP 409.
- [x] Oversized payloads (>64KB for JSON) drain socket to prevent Windows TCP RST.

### Gate 2: Capture Integrity & Evidence Tracking
- [x] Complete 6-file role requirements: `cam01_board`, `cam02_board`, `cam01_trial`, `cam02_trial`, `cam01_sync`, `cam02_sync`.
- [x] Explicit ruler calibration measurement input required (in mm + operator name).
- [x] External test samples strictly quarantined in `projects/caliscope/external-source` with prominent "TEST ONLY" UI warnings.
- [x] Raw video files strictly immutable with SHA-256 integrity verification.

### Gate 3: Biomechanical & Pipeline Accuracy
- [x] Pose2Sim OpenSim setup validated for simple and flex models.
- [x] Coordinate angle conversions maintain anatomical consistency (flexion/extension, abduction/adduction, internal/external rotation).
- [x] Non-uniform framerate timestamps preserved; no interpolation over gaps > 0.1s without explicit flag.

### Gate 4: Reporting & Data Management
- [x] Multi-page vector PDF generation using Matplotlib `PdfPages` (no headless Chrome/wkhtmltopdf dependency).
- [x] JSON summary and metrics CSV exported alongside PDF.
- [x] Backup ZIP archive contains complete database and sessions with SHA-256 manifest.
- [x] Restore pipeline verifies 100% of file hashes in isolated staging before atomic replacement.

### Gate 5: Deployment & Distribution
- [x] Single desktop shortcut `KineLab PT.lnk` consolidated on Desktop.
- [x] Offline distribution bundle built with zero external internet requirements.
- [x] Clean machine installation procedure documented in `docs/CLEAN_INSTALL_REPORT.md`.
