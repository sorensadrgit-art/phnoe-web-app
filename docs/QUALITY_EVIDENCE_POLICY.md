# Quality evidence policy

This policy governs what the software is allowed to call "measured". It is the
contract behind the Evidence Passport.

---

## 1. Evidence state machine (append-only)

```
EMPTY -> DRAFT -> SIX_FILES_PROBED -> REGISTERED_ORIGINALS -> NORMALIZATION_PASSED
      -> CALIBRATION_PASSED -> SYNC_PASSED -> 3D_PASSED -> KINEMATICS_PASSED
      -> RESEARCH_REPORTABLE
```

Every transition requires an artifact, not a filename:

| Transition | Required evidence |
|---|---|
| `DRAFT -> SIX_FILES_PROBED` | 6 role slots, each FFprobe-verified: codec, resolution, fps, frames, duration, SHA-256 |
| `-> REGISTERED_ORIGINALS` | Immutable originals stored; per-file SHA-256; refusal to overwrite an existing registration |
| `-> NORMALIZATION_PASSED` | Normalizer log, output hash, and equality of intended frame count |
| `-> CALIBRATION_PASSED` | Physical board square size with units + who measured it; intrinsics/extrinsics artifacts; native reprojection error reported |
| `-> SYNC_PASSED` | Two cue events with exact decoded frame index per camera; residual offset and end-of-trial drift |
| `-> 3D_PASSED` | Native triangulation/manifest output; missing-frame statistics; person-association result; filter parameters |
| `-> KINEMATICS_PASSED` | OpenSim IK `.mot` with model name + version + hash, coordinate list, units, and the native marker-error report |
| `-> RESEARCH_REPORTABLE` | Report generated *from* the above, with every unavailable field explicitly marked |

## 2. Invalidation

- Changing any registered original, calibration input, sync cue, configuration,
  model, or software version **invalidates every downstream state**.
- Invalidation is recorded, never erased: the session keeps its history and the
  new state begins at the first affected transition.
- A partially written run leaves artifacts marked `FAILED`/`UNVERIFIED`. Partial
  output is never promoted to `PASSED` by retry.

## 3. TEST_ONLY is a separate branch

- Demo/Caliscope/synthetic material enters at `TEST_ONLY` and **cannot** reach
  `REAL_VALIDATED` by renaming, copying, or toggling a UI control.
- Test-only artifacts are watermarked in the UI and in every export.
- Reports generated from them carry **TEST ONLY — NOT PHYSICAL VALIDATION**
  prominently, on the cover page.

## 4. Claim labels

| Label | Meaning | Precondition |
|---|---|---|
| `SOFTWARE_BUILD_VERIFIED` | Code, UI, tests, packaging pass in the stated environment | All software gates green |
| `RESEARCH_WORKFLOW_VERIFIED` | A real session completed native calibration → sync → 3D | Genuine six-role capture; **no accuracy claim** |
| `CLINICAL_VALIDATION_COMPLETE` | Agreement with an independent reference at predeclared thresholds | Reference protocol + results + intended-use review |

`KINEMATICS_PASSED` is **not** clinical accuracy. `RESEARCH_WORKFLOW_VERIFIED` is
**not** validity. Rotation of a markerless pipeline through a published study's
pooled error is not a result for this device, protocol, or population.

## 5. Prohibited shortcuts

1. Zero exit code treated as success → forbidden; native quality metrics decide.
2. File presence treated as a gate pass → forbidden.
3. Silent interpolation to fill missing 3D frames → forbidden; gaps stay gaps.
4. 2D joint angles substituted for OpenSim model angles → forbidden.
5. Missing toe markers counted as measured foot contacts → forbidden.
6. Synthetic calibration metrics or fabricated reprojection error → forbidden.
7. Auto-generated gait-event or repetition labels presented as human reference → forbidden.
8. Published thresholds adopted as this system's acceptance without device-specific measurement → forbidden.
9. Post-hoc threshold choice after seeing results → forbidden; preregister.
10. Demo footage registered as a real session → forbidden.

## 6. Reporting duties

Every report must state: session identity and type; camera/media configuration;
measured board value and native calibration/sync evidence; 2D detection and
missingness; accepted 3D/IK outputs **or** explicit unavailability; gait/squat
labels with human-review status; model/software versions and hashes; limitations;
full artifact inventory including failed quality checks.

A report must never contain a diagnosis, a treatment recommendation, a normative
range presented as measured, or a number whose source artifact does not exist.
