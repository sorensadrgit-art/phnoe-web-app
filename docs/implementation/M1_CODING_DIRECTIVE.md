# M1 approved execution — safety constraints for local coding agent

Owner approved exactly **Tasks 1–3** of `docs/implementation/M1_SCOPED_PLAN_20261028.md` on **2026-10-28**. Start with Task 1 only; return precise results and do not do Task 2 unless separately directed by this supervising assistant. All app edits are authorized only inside this isolated repository on local branch `feat/kinelab-m1-containment-20261028`.

## Non-negotiable
- NEVER read, write, enumerate private recordings in, test against, or launch `C:\Users\soren\Documents\Projects\KineLab-PT-DualCam`, its `projects` folder, or other patient-data locations. It is the separate live installation and is out of scope. Do NOT copy or migrate patient data.
- NEVER modify `main`, create deployment changes, publish, commit, push, install external packages, run destructive filesystem commands or change security policy.
- Use only disposable `tempfile.TemporaryDirectory` roots / explicitly generated synthetic fixtures. Preserve original records and unknown provenance.
- Follow `AGENTS.md`, the full M1 plan and the original audit. Follow red-green-refactor TDD: tests must FAIL against unchanged code before introducing the fix, with observed failures logged. Add tests without removing existing assertions.
- Keep scientific validity UNVERIFIED. No real pose estimation, no reopening real acquisition, no claims that physical capture works.

## Task 1 — approved, execute now
1. Confirm HEAD + clean **application code**. Read relevant existing tests and service/index/report/frontend call sites.
2. Add focused failing Python tests for `LIVE_ACQUISITION_UNVERIFIED` before any file creation, forged source fields, synthetic/empty/malformed frame attempts, and unverified legacy record promotion and report generation. Add relevant Node/React presentation tests when practical. Record exact failing commands/results.
3. Implement smallest robust service-side HTTP 409 rejection for the /api/v1/sessions/live-set endpoint, early before directory creation, backed by reusable service exception. No caller input can bypass. Ensure all direct service callers fail closed. Existing records remain readable as UNVERIFIED and not RESEARCH_REPORTABLE solely due to exports; any report from unverified evidence refused, unchanged old stored bytes. Native validated acquisition must remain separate.
4. Change only the necessary frontend/UI to clearly show that persistence/clinical measurements are unavailable. Make camera preview not display simulated motion as real measured tracking. An explicitly labeled synthetic demonstration may remain. Any displayed metrics must accurately show source state. Do NOT break the independently synthetic cloud demo.
5. Run targeted Python and JS tests, both builds. Record exact outcomes and unresolved gaps in `docs/implementation/VERIFICATION_LOG.md` (or a new dedicated M1 log) and maintain `TASK_BOARD.md` as IN PROGRESS/PARTIAL, NOT ACCEPTED unless the actual acceptance criteria are met.
6. End response with changed files, RED failure evidence and GREEN results, tests still failing, remaining risks, and explicitly state readiness for supervising assistant to proceed to Task 2.

Do not alter the M0 historic audit or approval wording. Do not treat tests as clinical proof.