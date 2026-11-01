# Current candidate package notice

Current candidate acceptance: NOT_GRANTED. Clean-machine validation: NOT_RUN. Physical validation: BLOCKED_ON_PHYSICAL_EVIDENCE. Clinical validation: UNVERIFIED.

The web-demo description below is separate from candidate installation and runtime acceptance. Its original shortcut reference and existing localhost checks describe the preserved installation; they are not candidate verification steps. Preserve the original shortcut and installation. Use only the isolated KineLab PT Candidate entry point and fresh TEST_ONLY data for current candidate verification.

Follow the generated README-OFFLINE-INSTALL.md and app/RUNBOOK.md in this package. A running original installation, hosted synthetic demonstration or package integrity check does not verify this candidate's native runtime, clean-machine operation or physical measurement.

<!-- CURRENT-CANDIDATE-NOTICE:END -->
# KineLab PT — Vercel web demonstration

## Deployment contract

- Git repository: `sorensadrgit-art/phnoe-web-app` (private).
- Vercel project root directory: `viewer`.
- Vercel framework: Vite; build: `npm run build:cloud`; output: `dist`. The dedicated cloud mode excludes the local UnifiedApp and backend UI source from public JavaScript bundles. The desktop/offline distribution continues to use `npm run build`.
- The browser entrypoint selects the **full desktop application** exclusively on the Windows launcher's loopback host (`127.0.0.1` / `localhost`).
- On all other hosts, the app renders a deliberately limited **synthetic demonstration**.

## What the web demonstration does

- Runs client-side simulation of exercise motions, joint metrics, HUD, and a Three.js skeleton visualizer.
- Allows downloading **synthetic** JSON results to the visitor's device.
- Does not enumerate or request camera devices, ingest patient identifiers, upload video, call the Python API, or persist session data remotely.
- Clearly labels simulated metrics as not derived from actual camera footage and not clinically validated.
- Vercel response policy denies camera, microphone, and geolocation permission.

## What remains desktop-only

The existing `t6_launcher.py` / `t6_server.py` local loopback architecture (including native capture, SQLite, Pose2Sim/OpenSim, evidence passports, report generation and backup) is not hosted on Vercel. It continues to run offline from the original Windows shortcut.

**This is not a clinical cloud service or an end-to-end migration.** A future full cloud product would require separate design for identity/authentication, encryption, consent, regulatory controls, persistent storage, job queues, native processing workers, signed results, and security testing. Never deploy the current localhost server as an unrestricted public API.

## Verification

1. `npm --prefix viewer test`
2. `npm --prefix viewer run build:cloud` for Vercel; `npm --prefix viewer run build` for offline Windows packaging.
3. Inspect the hosted site: simulation mode, no camera permission, all exercise controls, 3D rendering, synthetic JSON export.
4. Check that the local launcher at `http://127.0.0.1:4184` continues to render `UnifiedApp` with existing functionality.
