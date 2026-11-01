# KineLab M1 Containment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` after explicit plan approval. Execute natively in this isolated checkout or a child feature branch; do not start parallel agents merely from this document.

**Status:** APPROVED BY PROJECT OWNER, 2026-10-28 (America/New_York) — Tasks 1–3 only, including disabling unsafe live save/reporting and destructive restore overwrite. No other milestones, clinical recording, deployment, main-branch changes, live-app edits, or patient-data access are authorized.

**Goal:** Stop the demonstrated false-measurement and destructive-restore paths while preserving all existing source records.

**Architecture:** Retain the local bearer-gated service, React viewer and existing module boundaries. First contain unsafe operations with explicit refusal and accurate status. Reopen persisted acquisition and destructive restore only in separately accepted increments that provide strict contracts, immutable evidence and durable transactions.

**Tech Stack:** Existing Python standard library/SQLite, React 19, Vite 7, current Node test runner and Python unittest. No new runtime dependency is needed for this first slice.

**Spec:** `AGENTS.md`, `MASTER_PLAN.md`, audit sections 3–4, `TASK_CATALOG.md` B01/B02/B06/B08/B09/B16, and `M0_BASELINE_20261028.md`.

## Global constraints

- Work on `feat/kinelab-production-readiness-20261028` or a child branch, based on reviewed HEAD `7efd108caf4244d10672014a9cb0f7afceb253ff`.
- No changes to the original Windows app, shortcut, patient data, main branch or hosted demo. No deployment, production migration or new inference dependency.
- Preserve `127.0.0.1`, bearer/Host/origin checks, immutable raw media and the separate synthetic cloud build.
- Retain `SOFTWARE_BUILD_VERIFIED` only for its proved scope, `BLOCKED_ON_PHYSICAL_EVIDENCE`, and `CLINICAL_VALIDATION: UNVERIFIED`.
- Existing records remain on disk without relabeling their original provenance. Unknown source remains unknown; do not retroactively claim measured or synthetic provenance without evidence.
- Use failing regression tests on disposable fixtures before each application change. Do not weaken tests to retain a misleading successful status.
- Owner: Codex lead engineer for implementation, cross-file integration and evidence. Acceptance owner: project owner. Clinical/research decisions remain with the project owner and validation lead; no role assignment implies their sign-off.

## Review focus

- A stale client bypasses a disabled button: the server must refuse the same unsafe operation (Task 1/2 HTTP tests).
- Synthetic motion is relabelled by a missing or forged source field: the currently unverified acquisition path remains unable to persist measured sessions (Task 1).
- A session with old/corrupt metadata appears in history: show unverified evidence without rewriting originals or producing reassuring reports (Task 1).
- A ZIP uses Windows drive/UNC/case aliases or reparse points: reject before publication; preserve all pre-existing bytes (Task 2).
- A failure occurs after one restored session is published: roll back only newly created destinations and retain all original sessions (Task 2 fault injection).

## First approval scope

Approve **Tasks 1–3 only**, with their tests and evidence updates. This is a deliberately bounded safety increment. It does not complete all acceptance criteria for B01, B02, B06, B08, B09 or B16; acquisition, durable recording, immutable generations and full validated restore remain subsequent work. It makes the unsafe paths unavailable rather than silently trustworthy.

### Task 1 — Stop false measured persistence and report promotion

**Owner / dependencies:** Codex, after plan approval. No unresolved clinical endpoint decision is needed to refuse fabricated evidence.

**Files:** `t6_service.py`, `session_library.py`, `session_index.py`, `report_builder.py`; `viewer/src/LiveTrackerStudio.jsx`, `LiveSetSummaryModal.jsx`, `UnifiedApp.jsx`, `unifiedModel.js`, `ReportStudio.jsx` only where these consumers need the new unavailable/unverified states. Tests: `tests/test_live_session_api.py`, `test_t6_service.py`, `test_session_index.py`, `test_report_builder.py`, `viewer/src/unifiedModel.test.js`, and one focused live-source test included in `viewer/package.json`.

**Interfaces / decisions:** Preserve `/api/v1/sessions/live-set` and `IntegratedService.save_live_session(payload: dict) -> dict` as the compatibility boundary, but make the unverified live-write path reject with HTTP 409 and a stable `LIVE_ACQUISITION_UNVERIFIED` reason. This gate must run before directory creation. Current generated motion remains available in explicitly synthetic presentation/download flows, without persistence into the session library. No `source` request field may override the gate. Existing legacy live records remain readable as unverified inventory; they cannot receive `RESEARCH_REPORTABLE`, verified motion responses or valid clinical-looking reports solely because export files exist.

- [x] Add regression cases `test_live_write_unverified_rejects_before_files`, `test_forged_source_cannot_enable_live_write`, and `test_legacy_live_evidence_never_promotes_or_generates_valid_report`. Assert HTTP 409/reason, unchanged destination inventory, unchanged original hashes, and no fabricated frame/TRC/report creation. Include M0's empty-frame and malformed/NaN/string-boolean payloads.
- [x] Run the affected tests against the baseline; retain failures showing the previous acceptance/promotion behavior.
- [x] Implement refusal in the shared service and update its UI callers. Camera preview must display unavailable measurement values; it must not display generated motion as camera-derived. Synthetic mode must remain explicitly labelled. Remove automatic/default patient persistence through this path.
- [x] Keep old live records explicitly unverified across list/detail/passport/report consumers. Do not migrate or delete them. Refuse unverifiable motion/report export with `EVIDENCE_UNVERIFIED`; preserve any existing output files. Existing native validation remains a separate gate.
- [x] Re-run targeted Python/Node tests, then verify the mounted desktop camera-preview/synthetic states without recording a person. Direct POST must fail even from a stale client. Build cloud and desktop; confirm the cloud synthetic demonstration remains usable and never gains a backend dependency.

**User impact:** Existing live Save/report behavior becomes deliberately unavailable until the acquisition/recorder contract is accepted. This is a visible compatibility change; the approval includes that change. Existing files and the original live installation are untouched.

**Rollback:** A single reviewable change can be reverted on the isolated branch. Do not roll back by deleting session folders. Reverting restores the known unsafe behavior, so that version must remain excluded from participant use.

### Task 2 — Validate restore inventory and contain publication

**Owner / dependencies:** Codex, after plan approval; independent of Task 1. Destructive overwrite remains disabled until B09's coherent recovery design and D05/D08 are accepted.

**Files:** `backup_manager.py`, `t6_service.py`, `t6_server.py` only for error mapping if needed, and **`viewer/src/UnifiedApp.jsx`** (the actual unconditional `overwrite:true` caller at baseline line 293). Tests: `tests/test_backup_manager.py`, `test_t6_service.py`, `test_t6_server.py`.

**Interfaces / decisions:** Retain `BackupManager.restore_backup(zip_path, overwrite=False) -> dict`. Reject `overwrite=True` with `BackupConflictError`/HTTP 409 and stable `RESTORE_OVERWRITE_UNAVAILABLE`, before destination mutation. Preserve the existing service confirmation requirement. The initial supported operation is a verified non-conflicting restore only. Resolve `backup_name` strictly within the service backup directory; reject paths instead of joining arbitrary request text.

- [x] Add failing cases for M0's unlisted file, `../m0-sibling`, and absent staged session source. Assert exact file/directory snapshots and original hashes are unchanged after rejection, including siblings and the index.
- [x] Add cases for absolute/drive/UNC paths, backslashes, duplicate members and duplicate/case-equivalent normalized paths, duplicate JSON keys, symlink/reparse entries/destinations, declared-size mismatch, missing/extra inventory, invalid session IDs and truncated/corrupt archives. Declare conservative restore limits in this change: at most 10,000 members, 10 GiB total expanded bytes, 1 GiB per member and 100:1 expansion ratio; reject before extraction when metadata exceeds a limit and enforce actual byte counts while extracting. These are containment limits, not approved recording-size promises.
- [x] Add valid single/multiple-session non-conflicting cases and inject failures at each publication boundary. Invalid/preflight-failed archives must change zero destination bytes. Publication failures must remove only directories created by that operation; prior destinations must never be deleted or replaced. Reject existing-session conflicts even when a client submits overwrite.
- [x] Preflight the complete schema, inventory, path set, file types, limits, sizes and hashes in bounded staging before publishing anything. Reuse `_check_id` and existing digest helpers where they fit; use one shared validation path for inspect/restore. Preserve the SQLite online-backup API. Do not claim audit restoration or a coherent snapshot until B09 passes.
- [x] Update the actual UI restore caller to submit non-destructive restore and display exact validation/conflict outcomes. Do not promise a conflict-resolution preview that is not implemented.
- [x] Run the complete backup/service/server tests and the six M0 counterexample fixtures with secure expected assertions. Review cleanup, Windows junctions and failure injection before acceptance.

**User impact:** Overwrite becomes unavailable. Oversized or older incomplete archives receive actionable refusal; originals remain intact. Full destructive recovery, backup scheduling and RPO/RTO compliance are outside this slice.

**Rollback:** Revert code only in the isolated branch. Keep the input archive immutable. Test all changes on disposable destinations; no real restore or data migration is authorized.

### Task 3 — Integrate, verify and request result acceptance

**Owner / dependencies:** Codex after Tasks 1 and 2; project owner accepts the result. No second agent or remote publication is assumed.

**Files:** affected tests/scripts plus `VERIFICATION_LOG.md`, `TASK_BOARD.md` and this proposal. Do not change the historical audit.

- [x] Run the declared frontend suite including its new relevant cases, the omitted gait-review suite, both builds, and the complete Python suite in the verified interpreter. Record skips and Tkinter/socket failures separately; do not omit them from counts.
- [x] Run mounted desktop/API checks for synthetic-vs-camera labels, stale-client refusal, unverified legacy history, restore errors and keyboard access to the changed controls. Use only synthetic fixtures and isolated runtime state. Verify console/network results and cleanup.
- [x] Rebuild and hash-check the package after source changes. Leave its missing-runtime/clean-install gates unresolved unless separately authorized work satisfies them. Do not present a manifest assertion as a passed release gate.
- [x] Review the whole scoped diff, source preservation, dependency lockfiles, private-data exclusions and rollback. Present exact regression outcomes and remaining acceptance gaps for owner review. Commit/publish only if requested; never merge or deploy automatically.

## Subsequent proposals — not covered by first approval

| Order | Outcome and acceptance | Files / lead | Dependencies and rollback |
|---|---|---|---|
| M1 integrity and strict contracts | One versioned source/schema contract shared by live/native/readers; reject duplicate/nonfinite/wrong-type/sequence/summary data. Preserve committed expected digests and audit identities; quarantine changes; no arbitrary-file or incomplete-stage promotion. | `session_contract.py`, service/server, `session_index.py`, pipeline/export/report consumers, shared JSON fixtures; Codex with frontend contract review | Design against all producer/consumer callers before changing formats. Disposable migration fixtures first; real schema/data migration needs its own backup and change approval. |
| M2 durable recorder | Transactional chunk+receipt+audit commit, stable IDs, contiguous saved-through sequence, idempotent retry and atomic finalized generation. Test chunks 1/3/2, lost ACK, conflicting retry, crash/disk-full and restart. UI never equates buffered with saved. | service/server/index, new recorder only if no existing component fits, `LiveTrackerStudio.jsx`; Codex | Depends on strict contracts and immutable identity. Approve fault model, maximum session/queue/buffer budgets, protected data root and D05/D08. No reopening measured capture before applicable M1/M2 gates pass. |
| M2 coherent recovery | Snapshot one committed generation with audit history; exclude backup/staging trees; reviewed conflicts, safety copy, rollback at every cutover and independent recovery drill. | `backup_manager.py`, index/service/UI/runbook; Codex | Depends on committed generations and approved RPO/RTO/key/retention policy. No overwrite until original-preservation fault tests pass. |
| Release evidence slice | Include all required modules; bootstrap safely; remove hardcoded scientific/Blender paths; include omitted tests; provide lint/type gates, exact artifact provenance and CI. Reproduce startup/idle/shutdown/Tk failures before fixing. | builder, launchers, environment/model manifests, tests, `viewer/package.json`, CI; Codex | Package/OS/model-license review; no bulk upgrades. Verify fresh supported Windows offline installation. Revert code/package together; preserve external data root. |
| M3 measured acquisition and later UX | Pinned local inference, calibrated coordinate/validity contract, exercise lifecycle and independent endpoint validation; later complete accessibility/history/report workflows. | pose adapter, geometry/FSM, native quality, UI; engineering with clinical validation lead | D01/D02/D03/D06/D07; separate accepted plans. Hardware/EMG, physical benchmarks and clinical claims cannot be chosen or passed by software-only work. |

## Self-review and approval record

All six fresh M0 failures map to this containment scope or the explicitly deferred immutable-integrity increment. Task 1 prevents new false live evidence and refuses old unverified promotion; it does not repair native integrity or implement camera inference. Task 2 directly closes the demonstrated unsafe restore publication routes while deferring destructive recovery. Task 3 proves integration without declaring the full catalog complete. Durability, identity, native scientific validity, privacy policy and physical validation remain blocking work.

**Owner result decision, 2026-10-28:** ACCEPTED WITH LIMITATIONS for Tasks 1–3 as bounded safety-containment only, as recorded in [owner acceptance](M1_OWNER_ACCEPTANCE_20261028.md) and [result review](M1_RESULT_REVIEW_20261028.md). Canceled browser downloads and all clinical, data integrity, security, packaging, physical-validation and recovery blockers remain unresolved. D01–D08 remain OPEN; full M1 and release acceptance are NOT GRANTED.

**Approval:** APPROVED on 2026-10-28 by project owner in ChatGPT: "I explicitly approve KineLab PT M1 scoped plan Tasks 1–3 only, including temporary disabling of unsafe live saving/reporting and destructive restore overwrite. Record my approval in the plan and proceed with implementation using tests and disposable fixtures on the isolated AgentZero feature branch. Do not modify the existing desktop app, patient data, main branch, or production deployment. Verify the results and report remaining blockers."

**Approved engineering branch:** `feat/kinelab-m1-containment-20261028` (local child branch of reviewed `7efd108c`). **Implementation:** Tasks 1–3 carried out and their bounded result ACCEPTED WITH LIMITATIONS on 2026-10-28. **Result acceptance:** LIMITED TO SAFETY CONTAINMENT ONLY; browser downloads and all wider blockers remain open. D01–D08 remain OPEN. No commit, push, merge, deployment, patient-data access, participant recording or next milestone is authorized.

## Verification record, 2026-10-28

The checked steps above mean the specified work/check was performed, not that every release criterion passed or the owner accepted the result. Full evidence: [result review](M1_RESULT_REVIEW_20261028.md) and [durable receipt](M1_EVIDENCE_20261028.json). Final Python: 258 run, 256 passed, two absent-Blender skips; Node: 50 declared plus eight separate gait cases passed; both builds passed with large-chunk warnings. Isolated packaged-service/browser checks passed the containment assertions; browser file downloads were canceled and remain unresolved. Package hashes match, but missing modules/runtime/clean-install gates remain. Tkinter/Tcl warnings persist. No actual camera, participant, live installation, commit, push or deployment was used. Broader B01/B02/B06/B08/B09/B16 criteria remain open.

**Task 3 evidence delivery: COMPLETE WITH DOCUMENTED LIMITATIONS. Result acceptance: ACCEPTED WITH LIMITATIONS by project owner on 2026-10-28 (Tasks 1–3 only). Full M1/release/clinical acceptance: NOT GRANTED.**
