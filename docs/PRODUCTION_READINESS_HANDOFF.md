# KineLab PT — Production Readiness / Multi-Agent Handoff
Prepared: 2026-10-28 (America/New_York)
GitHub: https://github.com/sorensadrgit-art/phnoe-web-app (private)
Baseline source: ffde4be70d0a501980d1d22aac3dea1c91006ff9
Working branch: feat/kinelab-production-readiness-20261028 (local, not pushed)
Public web demo: https://kinelab-pt.vercel.app (synthetic demonstration; not a clinical service)

## User's intended outcome
Develop KineLab PT into a reliable, secure, visually refined research/physical-therapy motion-analysis platform, with a reproducible Windows installation and a deliberately separate production-ready web offering. Preserve all working software and its data, and allow Codex/Antigravity/Agent Zero to collaborate via this source tree and verifiable evidence.

## Baseline architecture
- Desktop localhost-only Python service: `t6_launcher.py`, `t6_server.py`, `t6_service.py`, `session_index.py`, `report_builder.py`, `backup_manager.py`.
- Research pipeline: dual cameras, calibration + sync, Pose2Sim triangulation, OpenSim IK, gait and squat analysis, evidence passports; raw inputs immutable.
- Frontend: React 19, Vite 7, R3F/Three.js. Browser components include `viewer/src/UnifiedApp.jsx`, `LiveTrackerStudio.jsx`, `LiveDigitalTwin.jsx`, `LiveHUDOverlay.jsx`.
- Web demo: `viewer/src/CloudDemoApp.jsx` under `npm run build:cloud` (synthetic landmarks only; no backend, camera or patient data). Production on Vercel is a **hosting status**, not clinical validation.
- Offline Windows bundle is created by `tools/build_offline_distribution.py`; manifest hashes need verification. The distribution ZIP includes source/modules/compiled UI but does NOT include the whole Python environment, model weights or FFmpeg; clean machine must verify prerequisites.

## Non-negotiable release constraints
1. Patient privacy, source-media immutability, consent and provenance. Do not place PHI or research recordings in Git, archives, telemetry, Vercel, or third-party LLM prompts.
2. Calibrations, measured angles and clinical outcomes must be based on actual validated data; synthetic results labeled. Physical accuracy and clinical validation currently UNVERIFIED.
3. Existing desktop launcher and data must remain operational, offline, and localhost-only. No direct public exposure of loopback server.
4. Branch-isolated reversible changes, baseline snapshot and automated regression gates. No push to main or deployment to a clinical endpoint without explicit approval.
5. Test Windows 10/11, browser rendering, camera permissions, safety guards and artifacts independently before release.

## SOREN execution contract (repeat per milestone)
Understand → Investigate → Rederive → Plan Forge → Plan Acceptance → Execute → Result Acceptance.
For every proposed change: state need, current evidence, risk, files, plan, rollback, test expected to fail before fix, implementation diff, test pass evidence, browser/device validation, accepted or blocked result.

## Priority milestones and objective acceptance
### P0 — Proven baseline, packaging and recovery
- Inventory dependencies, OS/GPU/CPU constraints, repository state, clean working tree and app versions.
- Validate `npm --prefix viewer test`, `npm --prefix viewer run build`, `npm --prefix viewer run build:cloud`, Python tests.
- Verify package SHA-256 manifest and archive integrity; test extracted viewer and launcher without modifying existing runtime.
- Produce reproducible install/bootstrap scripts and tested clean-machine or VM evidence.
- **Accept:** repeatable install/test/launch with no secret or PHI exposure, rollback and documented failure states.

### P1 — Actual camera-to-landmark inference
- Currently the HUD/3D avatar exercise metrics derive from a generated simulated pose in `LiveTrackerStudio.jsx`, even when camera is visible.
- Add a real pose estimator with explicit source mode selection (REAL CAMERA / SYNTHETIC TEST), MediaPipe or equivalent local inference, landmark visibility, FPS/confidence and failure gating.
- Ensure browser camera frames stay local unless specific user consent and an approved secure architecture permit otherwise.
- **Accept:** real camera joint landmark movements drive on-screen skeleton, confidence/latency telemetry, permission denial test, correct fallback labeled 'simulation', independent reference-motion accuracy benchmark plan.

### P2 — Scientific and clinical correctness
- Version and validate angle definitions, mirroring, frame timing, 2D/3D coordinate frames, limb symmetry, rep FSM, tracker drift.
- Make missing/unreliable inference yield 'unavailable' rather than clinically suggestive metrics; protect calibration/sync gates.
- **Accept:** reference test fixtures, labeled measured vs simulated datasets, numerical tolerances, error budgets, independent physical validation evidence or explicit BLOCKED status.

### P3 — Windows runtime and release engineering
- Provide self-contained installer or precise offline dependency prereq checks, model-weight licensing/hash pinning, signature strategy, rollback and uninstall.
- Add Windows startup/stop monitoring and guaranteed local-only port handling, manifest integrity verification, crash diagnostics and recovery testing.
- **Accept:** clean Windows VM install, start/stop/reopen, no duplicate daemon, no unexpected outbound network, readable reports, reproducible offline package.

### P4 — Real cloud architecture (separate from existing demo)
- Design a new authenticated API boundary with RBAC, consent, audit logs, secure sessions, encryption in transit/at rest, retention/deletion, abuse protection, and regulated-data suitability review.
- Use persistent database/object storage and asynchronous compute workers for OpenSim/Pose2Sim. Vercel static UI/serverless functions cannot replace a sustained local native pipeline or SQLite file state.
- Never repurpose the current loopback server as a public API. No real data uploads prior to threat model, authorization tests and written deployment acceptance.
- **Accept:** architecture decision record, privacy model, disaster recovery, infrastructure diagram, isolated preview, security test evidence and cloud cost model.

### P5 — Premium motion UI, accessibility and performance
- Preserve dashboard UX while improving visual hierarchy, fast 3D interactions, responsive layouts, reduced motion and keyboard navigation.
- Tune render budgets, split Three.js heavy modules, manage camera/RAF/WebGL cleanup; monitor INP/LCP/CLS and mobile GPU load.
- **Accept:** cross-browser screenshots, keyboard/screen reader tests, core interaction automation, LCP/INP/CLS budgets, no WebGL memory leaks.

### P6 — CI/CD and release acceptance
- CI: exact dependencies/lockfiles, Python+JS tests, type/lint/security checks, secret/PHI scan, build both targets, artifact hash/signature and SBOM.
- Preview + staged release approval; protect GitHub `main`, record source SHA and acceptance owner, preserve immutable source recordings.
- **Accept:** automated checks and deploy logs, rollback rehearsed, approved deployment and clinical-validation disclaimer.

## Initial work order for first agent
1. Run `git status --short --branch` and identify baseline commit, then read this doc and `AGENTS.md`.
2. Run frontend tests and cloud + desktop build; run backend tests using known available Python environment.
3. Inspect the LiveTrackerStudio synthetic-pose loop for a measured camera input path and write a test-first P1 plan (not a misleading UI-only fix).
4. Validate the offline distribution from this exact working source commit, identify missing dependency bundles and model/FFmpeg prerequisites.
5. Submit a bounded P0/P1 plan with file-level change list, tests, rollback, risk and evidence; implement only the approved scope and checkpoint result.
6. Report STATUS, BLOCKERS, SOURCE COMMIT, TEST LOGS, CHANGED FILES, PREVIEW URL (if any), and NEXT ACCEPTANCE GATE.

## Local commands
```powershell
Set-Location 'C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace'
git status --short --branch
npm --prefix viewer ci
npm --prefix viewer test
npm --prefix viewer run build
npm --prefix viewer run build:cloud
# Use the isolated, preinstalled scientific environment in this workspace:
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests
# From an ordinary desktop production build only:
python tools\build_offline_distribution.py
```
The local checkout has its own isolated Python environment and synthetic/test-only fixtures (not copied patient datasets). Read `docs/BASELINE_QA_20261028.md` for the passing test recheck, prior intermittent Windows socket failure, and remaining release blockers. Never copy this developer environment blindly into a clean-machine release. Record blockers without modifying patient recordings.

## Agent collaboration
Codex: test-first engineering and code review.
Antigravity/Claude Code: React/Three.js UI architecture, interaction and browser QA.
Agent Zero: Windows installation, Python process lifecycle, local scientific integrations and reproducible evidence.
Use this shared Git workspace and written evidence files; avoid simultaneous edits of the same file or conflicting pushes.
