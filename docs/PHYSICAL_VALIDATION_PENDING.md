# Physical validation — pending

**Status: `BLOCKED_ON_PHYSICAL_EVIDENCE`.**

The software side is not yet complete either, but this document exists because no
amount of software work can substitute for the items below. Nothing in this file
may be filled in from test fixtures.

---

## 1. What is missing

No confirmed session contains six authentic, simultaneously captured role files
with a physically measured calibration target and two independently marked sync
cues. Prior real capture had two webcam clips only. Caliscope/online clips are
`TEST_ONLY` and can never be registered as real.

## 2. Six required roles

| Role | Source | Required properties |
|---|---|---|
| `cam01_intrinsics` | Phone | Board fully in frame, no motion blur, ≥ 20 s, static |
| `cam02_intrinsics` | Webcam | Same discipline; autofocus/exposure locked |
| `cam01_board` | Phone | Board visible from both cameras simultaneously, ≥ 10 s, static |
| `cam02_board` | Webcam | Same take, same board position |
| `cam01_trial` | Phone | Movement trial, both cameras rolling |
| `cam02_trial` | Webcam | Same trial, overlapping time window |

Record per file: device model, lens, resolution, fps, mounting height, distance to
subject, lighting. Lock white balance, focus, exposure, and stabilisation before
the board take and leave them locked through the trial.

## 3. Board measurement protocol

1. Checkerboard with 7 × 9 **inner** corners.
2. Measure square edge with a rigid ruler or caliper, **three times**, at three
   different squares; record all three.
3. Record units (mm preferred) and who measured, with a timestamp.
4. Preregister the acceptable spread between the three measurements **before**
   the capture session. Do not choose it afterwards.
5. Photograph the measurement (ruler in frame) and store it beside the session.

## 4. Synchronisation protocol

1. Two unambiguous visual events: one at the start, one at the end of the trial
   (e.g. a hand clap or a light flash visible to both cameras).
2. Mark the exact decoded frame index of each event in **each** camera.
3. Preregister the maximum acceptable residual offset and the maximum acceptable
   end-of-trial drift.
4. Record both numbers in the session manifest. A cue that cannot be marked in
   both cameras is a `SYNC_PASSED` blocker, not an approximation.

## 5. Preregistration sheet (fill before capturing)

| Parameter | Value |
|---|---|
| Board square size + units | |
| Allowed spread across 3 measurements | |
| Max residual sync offset (frames / ms) | |
| Max end-of-trial drift (frames / ms) | |
| Max acceptable native reprojection error | |
| Max acceptable missing-frame fraction | |
| Max acceptable OpenSim marker RMS | |
| Reference measurement method (if any) | |

Values must be justified by device/protocol evidence, not copied from another
laboratory's published error margins.

## 6. Capture runbook

1. Freeze device settings; verify Focus/Exposure lock on both cameras.
2. Record the three role pairs in the order intrinsics → board → trial.
3. Perform the two sync cues around the trial.
4. Stop recording; copy files off both devices **without re-encoding**.
5. Compute SHA-256 for all six files; register into a new session as real capture.
6. Enter the board measurement; run native calibration and record its reported error.
7. Mark the two sync events; confirm residual and drift against §5.
8. Run the pipeline; review native quality output before accepting any 3D result.
9. Generate the research report; verify it says what actually happened.

## 7. Acceptance criteria for `RESEARCH_WORKFLOW_VERIFIED`

- six authentic role files registered with stable hashes
- measured board value within the preregistered spread
- native calibration completed with reported error inside the preregistered bound
- sync residual and drift inside the preregistered bounds
- 3D result produced with missing-frame fraction inside the bound
- report generated from those artifacts and containing no fabricated field

## 8. Acceptance criteria for `CLINICAL_VALIDATION_COMPLETE`

Requires, additionally: a written intended use and target population; an
independent reference measurement (instrumented or criterion standard);
predeclared error thresholds per joint/outcome; a results analysis with the
achieved agreement; and intended-use/regulatory review. Until all of that exists,
the only permissible label is `UNVERIFIED`.

---

## 9. Sign-off

| Field | Value |
|---|---|
| Session folder | *(to be recorded on the workstation)* |
| Roles complete | 0 of 6 |
| Board measurement recorded | No |
| Sync events marked | No |
| Native calibration error | Not run |
| Reference measurement | None |
| Result | `BLOCKED_ON_PHYSICAL_EVIDENCE` |
