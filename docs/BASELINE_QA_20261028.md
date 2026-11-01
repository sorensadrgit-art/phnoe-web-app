# KineLab PT — Baseline QA / Reproduction Evidence
Date: 2026-10-28; host: AGENTZERO (Windows, OneDrive-backed Desktop)
Private repo main baseline: `ffde4be70d0a501980d1d22aac3dea1c91006ff9`
Local feature branch: `feat/kinelab-production-readiness-20261028`
Engineering readiness: **HANDOFF PREPARED; not a clinical production release**

## Verified on this machine
- A separate Git clone and local agent branch were made; original `KineLab-PT-DualCam` and original desktop shortcut are unchanged.
- Node v24.19.0; `npm --prefix viewer ci` completed from a pinned `package-lock.json`.
- Frontend unit tests: **45/45 passed** (`npm --prefix viewer test`).
- Vite desktop build: **PASS**, and Vite cloud demo build: **PASS**. See script names `build` and `build:cloud`.
- An isolated Python 3.13.16 `.venv` installed the pinned scientific stack via `uv pip install -r requirements.lock.txt`; import of OpenSim, Pose2Sim and ONNX Runtime passed.
- Portable Windows distribution generated from the latest project source. Manifest integrity **53 files verified** in the initial rebuild; repeat the builder after this document is committed to obtain the final manifest and ZIP checksum.
- The test environment contains an explicitly DEMO-only session scaffold and one `demo-local` 97-frame TRC example from the original local demo path. No actual patient footage, camera recordings, user databases or real-session folders were copied into the agent checkout.

## Python test baseline
First test run on the fresh unprepared Git clone: 223 tests, 5 failures / 11 errors / 1 skip. These were predominantly missing isolated Python `.venv`, expected generated distribution, and local test-only fixture directories.

After provisioning those dependencies and synthetic/test fixtures:
- Full run #1: **223 run; 1 error, 1 skipped**. The error was an intermittent Windows `ConnectionAbortedError [WinError 10053]` during `test_t6_server.LocalServerTests.test_foreign_origin_and_wrong_host_cannot_write` (HTTP reject-path test).
- Focused server suite rerun: **18 tests passed**.
- Full suite rerun: **223 tests run, OK (skipped=1)**; therefore 222 passed, 1 skipped on the final run. Log: `dist/python-baseline-retest.log` (local, ignored by Git).
- Python 3.13/Tkinter produced destructor-thread warnings even on the passing run. These are not counted as test failures, but need release investigation.

**Do not erase the intermittent socket failure.** Add a deterministic regression test for Windows early HTTP rejection and document whether the server should drain or close the request to avoid connection aborts. Investigate Tkinter shutdown/thread warnings before a desktop release.

## Production blockers remaining
1. Camera output currently uses synthetic landmarks for the motion HUD/3D tracking loop, even when a real camera view is shown. True camera inference and evidence validation are not complete.
2. Python/model runtime, FFmpeg, scientific dependencies, and clean-machine install are NOT bundled in the portable ZIP. The separate agent checkout *does* have the installed Python environment and node_modules; release packaging must address redistributable runtime licensing and offline installation.
3. No clean Windows 10/11 VM acceptance has been performed for this new handoff.
4. No clinical physical measurement validation or gold-standard motion capture benchmark. Clinical validation remains **UNVERIFIED**.
5. The public Vercel deployment is **synthetic demonstration only**. No approved authenticated backend, PHI controls, audit/persistence, native processing workers or security review for live patient uploads.
6. Vite produces an approximately 943 kB minified 3D/live module; optimize code splitting and mobile GPU performance with measured budgets.
7. Source includes tracked example portfolio assets (design reference material). Use only authorized, non-PHI fixtures. OneDrive sync may back up the Desktop handoff depending on user settings.

## Test and packaging commands (superseded 2026-10-29)
The results above are historical baseline evidence. Current packaging requires a frontend-input capture before a new build and explicit unused package destinations. Do not rerun the former no-argument builder or Desktop handoff command against the preserved M1 archive. See `PRODUCTION_READINESS_HANDOFF.md` for the current contract; final candidate and clean-machine acceptance remain pending.
```powershell
Set-Location 'C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace'
$env:PYTHONUTF8='1'
npm --prefix viewer test
& '.\.venv\Scripts\python.exe' -X utf8 -B -m unittest discover -s tests
# Replace review-01 with a fresh run name; keep frontend sources stable between steps:
& '.\.venv\Scripts\python.exe' -X utf8 -B tools\build_offline_distribution.py --capture-frontend-inputs dist\candidate-inputs-review-01.json
npm --prefix viewer run build -- --outDir ../dist/candidate-ui-review-01
& '.\.venv\Scripts\python.exe' -X utf8 -B tools\build_offline_distribution.py --out dist\KineLabPT-candidate-review-01 --frontend-dist dist\candidate-ui-review-01 --frontend-inputs dist\candidate-inputs-review-01.json
npm --prefix viewer run build:cloud -- --outDir ../dist/candidate-cloud-review-01
```

This document is reproducibility evidence from one Windows workstation, not a clean-room clinical safety certification.
