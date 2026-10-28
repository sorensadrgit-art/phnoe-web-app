# KineLab PT — Agent Implementation Master Plan

> SETUP ONLY. No application defects have been fixed by adding this plan. Current clinical measurement release: NO-GO.

## Authority and baseline

- Primary evidence: [Full production-readiness audit](../audits/KineLab_PT_Production_Readiness_Report.md), audited commit `ffde4be70d0a501980d1d22aac3dea1c91006ff9`.
- Existing complementary project handoff: [PRODUCTION_READINESS_HANDOFF](../PRODUCTION_READINESS_HANDOFF.md); follow its safety and release controls.
- Isolated Git branch at setup: `feat/kinelab-production-readiness-20261028`, initial HEAD `6fadc1970fbdfaeaefdad17aa42287b4e475a2de`. Diff that HEAD from the audited revision before using an old line number.
- Live application directory `C:\Users\soren\Documents\Projects\KineLab-PT-DualCam` is NOT the engineering worktree. Leave it and the existing KineLab PT shortcut intact.
- Existing public Vercel app is a synthetic demo, not the validated clinical measurement application.

## Release definition

Trustworthy clinical measurement is not equivalent to mathematically zero sensor error. Release requires zero silent acceptance of invalid/synthetic data, complete and verified acknowledged records under tested failures, and independent per-measurement reference validation. A video skeleton is not a muscle activity sensor; EMG or approved alternative hardware/protocol is required to claim measured muscle activity.

## Execution sequence

| Milestone | Required output | Representative report IDs | Exit gate |
|---|---|---|---|
| M0 — Rebaseline and plan acceptance | Reproduce builds/tests; diff HEAD vs audit; risks, owners, dependencies and rollback written | B20, R13, R15 | Report factual baseline, test failures, safe implementation order; no code modifications yet |
| M1 — Evidence truth and corruption containment | Eliminate falsely measured/synthetic status; strict measurement contract; fix unsafe restore and integrity reindex | B01, B02, B06, B07, B08, B10, B16 | Synthetic/invalid/altered sources fail closed, restore never deletes originals on error |
| M2 — Recorder and recoverability | Incremental durable append, exact ACKs, atomic finish, safe retry, protected storage, coherent backup | B03, B04, B05, B09, R01, R02, R18 | Crash, duplicate, disk-full, restart and restore injection tests preserve acknowledged records |
| M3 — Valid measurement | Real camera pose inference; aspect-correct geometry; uncertainty and exercise logic; native checks where enabled | B01, B11, B12, B13, B14, B15, B18, R03, R07, R16 | Measured/demo cannot mix; missing/stale frames reject; native quality fails impossible reconstruction |
| M4 — Security, reports and supported release | Privacy threat model, truthful exports, offline packaging, CI, measured performance | B17, B19, B20, B21 (conditional), R05, R08, R12, R13, R14 | Documented supported platform; full tests/restore drill; human trials still blocked until approved validation |
| M5 — Accessible clinical UX and pilot | Device/calibration, live validity + save state, history/review/export, adaptive UI | R04, R06, R09, R10, R11, R17, N01–N05 | Keyboard, screen reader, desktop/mobile reflow and guided clinical pilot evidence |

**Note:** M1 and M2 are safety prerequisites before real participant capture. Native-only B13–B15 and muscle-only B21 must be either completed and independently validated or explicitly excluded/disabled with corrected release claims. Do not declare them passed by exclusion alone.

## Agent lanes and merge protocol

**Codex / backend & integrity:** own the persistent recorder, service contracts, index, backup/restore, immutable provenance, recoverable jobs, tests and CI. Use a child branch/worktree; record failing regression tests before the fix.

**Antigravity / frontend & tracking:** own the camera adapter, source-mode controls, geometric validity, exercise FSM/UI, accessibility and rendered UX. Use a separate child branch/worktree. Integrate against versioned API contracts; do not assume measured camera data exists.

**AgentZero / coordinator & QA:** maintain the shared task board and verification evidence, run independent smoke tests, reconcile contracts, and help create reviewable integration changes. Do not allow two agents to modify the same worktree concurrently.

Agents must first read `AGENTS.md`, this plan, the full audit and the existing handoff. Deliver a scoped plan for user acceptance before application-code edits. Cross-lane changes require identified ownership, a reversible branch, tests and integration review. No auto-merge to main, production deployment, real data copy or credential upload.

## Per-task evidence contract

1. Confirm current code still reproduces audit finding; label changed, resolved, unverified or reproducible.
2. Write affected files, risk, integration dependency, user impact and expected failure case.
3. Add failing automated tests on synthetic/disposable fixtures. Never use private patient data in Git/test outputs.
4. Implement the smallest reversible change and re-run affected tests.
5. Record exact commands, environment, outputs, timestamps and artifact hashes in `VERIFICATION_LOG.md`.
6. Verify cross-feature behavior, interruption/failure handling, data integrity and rollback.
7. Mark accepted only with evidence and reviewer sign-off, not based on green UI or passing unrelated tests.

## First change to approve

Begin with a bounded M0 plan and B01/B02/B08 integrity triage. Make tests demonstrate existing false-camera provenance, malformed data acceptance, and restore containment on disposable fixtures. Present implementation slices for review. Do not start clinical capture or mark muscle tracking supported.
