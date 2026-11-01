# Task D — Synthetic Summary: Independent Review Corrections (Factory Opus 5.5)

Date: 2026-10-29. Branch: feat/kinelab-m1-containment-20261028 (pre-existing; no commit, no push).
Scope: corrected the four findings reproduced by the independent Codex review in
`dist/fullproject-20261028/D-summary-codex-review-1793247341993.log`.
Authoritative plan: `docs/implementation/autonomous-20261028/implementation-plan.md` (unchanged).
Note: `task-D-summary-brief.md` / `task-D-summary-report.md` were not present in this workspace
root; this round worked from the current task statement, the Codex review log, and source.

## Affected files (exclusive edit scope respected)

- `viewer/src/LiveSetSummaryModal.jsx` (presentation fix)
- `viewer/src/liveSource.test.js` (regressions + assertion correction)
- New logs: `dist/fullproject-20261028/D-factory-summary-review-red.log`,
  `dist/fullproject-20261028/D-factory-summary-review-green.log`

No other application files touched. The dirty working tree listed by `git status` is pre-existing
work owned by other agents and was not modified.

## Finding-by-finding

### 1. validReps:null + finite symmetry rendered "(Balanced)" alongside "repetitions were not assessed"
- Source evidence: `exerciseStateMachine.js` sets `validReps: null` exactly when
  `config.projectionOnly` (form not assessed); only the `squats` preset feeds `kneeSymmetry`
  against `minSymmetry`. A qualitative rating on unassessed reps is contradictory evidence.
- Fix: `symmetryRated` now also requires `cleanCount !== null && faults !== null`. The finite raw
  value still renders (`100%`), but the label becomes `(rating UNAVAILABLE: repetitions not fully
  assessed)`; valid zero and finite values stay distinguishable from missing (existing zero test
  still passes). Balance exercises keep `(not assessed for this exercise)`.

### 2. faultsLog:[null] silently filtered into a no-fault claim
- Fix: fault history is accepted only when every entry is well-formed (non-empty string `fault`,
  integer `count >= 0`, `count <= totalReps` when the total is known, `percentage` finite in
  0-100 when present). Any malformed entry makes the whole history UNAVAILABLE:
  heading `Form Fault Diagnostics (UNAVAILABLE)` and message
  `Form assessment UNAVAILABLE: fault history missing or malformed.` No silent filtering.

### 3. Out-of-range metrics rendered as valid (999 deg, 500%, 20 faulted reps on 1 rep)
- Tracker contract evidence (from `exerciseStateMachine.js`, not invented thresholds):
  - Knee flexion outside 0-180 deg is rejected in `update()`, so depth metrics are bounded to
    0-180 deg (image-plane geometry, not clinical).
  - Balance `peakDepth` is hold duration in seconds (`duration/1000`), and elapsed time
    accumulates the same gaps, so a hold cannot exceed elapsed test time. `durationSeconds` is
    `Math.round(elapsed/1000)`, so the bound allows 0.5 s rounding slack.
  - Fault counts are per-rep tallies, so one fault type cannot exceed `totalReps`; `percentage`
    is `round(count/totalReps*100)`, bounded 0-100.
- Fix: `depthInRange()` gates average/best depth (per-exercise units); out-of-range values render
  UNAVAILABLE. Fault entries failing count/percentage consistency invalidate the whole log.

### 4. Over-broad empty-summary assertion /100%/ and modal sizing change
- `git log -p` showed the committed card used `width: '100%'`; the working tree had
  `flex: '0 1 620px'`, changed solely so `width:100%` would not trip /100%/. Restored
  `width: '100%', maxWidth: 620` (no UI redesign).
- The test now inspects the semantic symmetry cell:
  `Bilateral Movement Symmetry</span><span ...>UNAVAILABLE</span>` must match, and no rendered
  `N% (` value/label may appear. The missing-evidence regression is preserved.
- Same class of mistake fixed in the two new range regressions: `999`/`9999` matched the
  backdrop's `z-index:9999`; assertions now target rendered values (`>999`, `>9999`, `500%`,
  `20 rep`).

## Commands and exit codes (this machine, this order)

1. Red (regressions added, component unfixed):
   `cd viewer; node --test src/liveSource.test.js` -> exit=1, 12 pass / 4 fail
   (the four new regressions failed exactly on the reviewed defects).
   Log: `D-factory-summary-review-red.log`.
2. Intermediate (component fixed, assertions still broad): exit=1, 14 pass / 2 fail, both
   failures self-inflicted by the broad `999`/`9999` regexes matching `z-index:9999` (that log
   was overwritten by step 3).
3. Green (assertions scoped to rendered values):
   `cd viewer; node --test src/liveSource.test.js` -> exit=0, 16 pass / 0 fail.
   Log: `D-factory-summary-review-green.log`.

Focused Node SSR test only, per constraints. No build, no dev server, no full suite, no browser,
no camera, no commits.

## Evidence vs assumptions

- Source/spec evidence: bounds above are read directly from `exerciseStateMachine.js`
  (0-180 deg input rejection, balance hold = seconds vs elapsed, fault percentage formula,
  `validReps: null` under projectionOnly). Labels, callbacks, demo/closed-measured saving
  branches, and the SYNTHETIC TEST SUMMARY banner are unchanged.
- Assumptions: the 0.5 s slack on the balance hold bound compensates only for the tracker's own
  `Math.round` of elapsed time. The `(rating UNAVAILABLE: ...)` wording is a presentation choice
  consistent with existing UNAVAILABLE labeling, not a tracker contract requirement.

## Limitations

- SSR/markup-level verification only. Parent must run the final browser, build, and full-suite
  checks; no browser or build was run this round.
- The modal validates display ranges only; it cannot detect semantically wrong-but-in-range
  synthetic inputs.
- No owner, clinical, or physical-validation acceptance is claimed or implied. Labels
  SOFTWARE_BUILD_VERIFIED (focused test scope only) / BLOCKED_ON_PHYSICAL_EVIDENCE /
  CLINICAL_VALIDATION: UNVERIFIED remain in force.
