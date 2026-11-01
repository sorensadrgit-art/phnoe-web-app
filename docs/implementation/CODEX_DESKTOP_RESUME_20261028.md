# Codex Desktop — Resume KineLab PT M1 (2026-10-28)

## Immediate action

Resume the **approved M1 containment Tasks 1–3** in this *existing isolated worktree*. Do **not** start a new clone, overwrite/revert the current dirty worktree, or assume the edited tests are sufficient proof. Continue Task 3 verification and correct any issues within approved scope only.

**Workspace:** `C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace`

**Branch:** `feat/kinelab-m1-containment-20261028` (local only).

**Current HEAD:** `7efd108caf4244d10672014a9cb0f7afceb253ff`. The M1 edits are **uncommitted and unpushed**. Never reset, stash, discard, checkout another branch over the edits, commit, push, merge or deploy without explicit owner acceptance.

**Primary authorization:** `docs/implementation/M1_SCOPED_PLAN_20261028.md` (owner approved only Tasks 1–3). Also read `AGENTS.md`, `docs/audits/KineLab_PT_Production_Readiness_Report.md`, `docs/implementation/M0_BASELINE_20261028.md`, `docs/implementation/TASK_CATALOG.md`, and `docs/implementation/VERIFICATION_LOG.md`.

## What is already changed but NOT accepted

Task 1 containment: `t6_service.py` refuses all unverified live-session saves with `LIVE_ACQUISITION_UNVERIFIED` before any session folder is created. Existing `kind=live` inventory/passports are marked unverified; legacy live report/motion/artifact endpoints are blocked. Frontend no longer runs synthetic pose inference behind the camera-preview label, exposes unavailable camera metrics, and disables unverified persistence. Synthetic-only demo remains separate. Changes include `session_index.py`, `session_library.py`, `report_builder.py`, `LiveTrackerStudio.jsx`, `LiveSetSummaryModal.jsx`, and `ReportStudio.jsx`.

Task 2 containment: `backup_manager.py` performs strict ZIP/manifest inventory preflight, rejects unsafe member paths, aliases, symlinks, suspicious compression, large archives, missing files, and destructive overwrite. It validates source digests in staging, publishes only nonconflicting new sessions, and rolls back its newly published names on failure. `t6_service.py` validates restore filenames; `UnifiedApp.jsx` sends `overwrite:false`. A coherent full database/audit restore and destructive overwrite remain unsupported.

The new `tests/test_m1_containment.py` (19 tests) passed after the fixes. Original `tests/test_backup_manager.py` (3 tests) also passed. `git diff --check` passed. Earlier in this task, `tests/test_live_session_api.py` (4) and `tests/test_report_builder.py` (3) passed after Task 1. **This does not mean Task 3/full regression/browser/packaging are complete.** Before changing app code, the new tests first failed with multiple original containment defects; logs under ignored `dist/m1-containment-RED*.log`. Current green test log: `dist/m1-containment-GREEN-first.log`.

**Review risk:** Earlier happy-path tests were rewritten to expect safe refusal; review the diffs critically and add independent regression coverage instead of silently reducing coverage. Recheck legacy read-only inventory, server error responses, compatibility, Windows path/reparse handling, cleanup and concurrency/fault injection. No real patient data was used.

## Continue now — exact Task 3 checklist

1. Start with `git status --short --branch` and `git diff --check`. Preserve all modified/untracked files. Inspect the whole diff before making further edits. Keep work within this repo.
2. Run focused tests using the existing verified venv, Windows PowerShell, and disposable synthetic fixtures:
   - `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_m1_containment.py -v`
   - `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_backup_manager.py -v`
   - relevant live-session, service, index, server and report-builder unit tests.
3. Complete approved Task 3: `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v`, `npm --prefix viewer test`, `node --test viewer/src/gaitReviewLogic.test.cjs`, `npm --prefix viewer run build`, `npm --prefix viewer run build:cloud`. Record exact counts, skips, failures and the build chunk-size warnings.
4. Exercise authenticated localhost HTTP/API, camera-preview vs synthetic-only UI, archived legacy live evidence refusal, non-destructive restore results, broken ZIPs, keyboard flow, and console/network using **only synthetic and isolated runtime data**. Check the path exclusion guard below before launching tools.
5. Rebuild the portable package (isolated checkout only), independently verify ZIP file hashes, and explicitly report missing runtime/model/clean-install gates. Review new/old test assertions and audit six M0 counterexamples; do not treat the intentionally failing baseline probe as a product green test.
6. Update `docs/implementation/VERIFICATION_LOG.md`, `TASK_BOARD.md`, the owner-approval plan and create `M1_RESULT_REVIEW_20261028.md` with exact evidence, remaining gaps, rollback and acceptance request. All clinical, privacy, and real camera validations remain UNVERIFIED.
7. Do NOT commit, push, merge, deploy, modify `main`, or make changes outside M1 Tasks 1–3. Stop at review and request result acceptance; do not mark the project production or clinically ready.

## Hard safety boundary

**NEVER access** `C:\Users\soren\Documents\Projects\KineLab-PT-DualCam`, the actual `KineLab PT.lnk`, existing patient/session data, user credentials, hosted production, or other repositories. Use disposable temp roots and this isolated worktree. Do not run a second agent in the same worktree. No real participant capture.

**Known remaining blockers:** durable recorder/idempotency, immutable expected digest baselines, camera frame-to-pose inference, validated geometry/calibration/IK, reference error benchmarks, EMG hardware for measured muscle activity, privacy/security decisions D01–D08, release packaging/clean Windows install, full coherent backup/recovery. Passing tests only validates those software cases.
