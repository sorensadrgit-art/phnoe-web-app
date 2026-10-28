# KineLab functional implementation — October 26, 2026

The original plan's software path is implemented and tested. Real capture acceptance remains pending: there are no six operator recordings, measured board dimensions or independent start/end cue observations in the prepared session. Synthetic fixtures do not establish physical or clinical accuracy.

## Delivered behavior

- Capture registration validates six original hashes, session identity and safe paths. Empty templates cannot enter processing.
- Normalization validates all sources before conversion, stages the six outputs transactionally, and records exact timestamp ticks, transforms and source-frame mappings. Real FFmpeg tests cover 25-to-30 fps conversion and nonzero input PTS. Originals are preserved.
- Calibration uses measured native RMS, not the placeholder zero. Sync retains the actual native reference camera and checks drift using independent ordered endpoint pairs.
- The runner rejects missing, malformed, stale, mixed or changed artifacts and requires the exact recorded inventory on resume. Acceptance triangulation disables interpolation and gap filling. Reconstruction quality counts observed two-view support before filtering/augmentation.
- TRC/MOT export preserves units and actual timestamps, binds v2 output to session/run/calibration hashes, and atomically publishes complete output without overwriting files. Legacy demo input remains supported.
- The existing viewer adds local-file selection, visible failure/recovery, timestamp playback, keyboard scrubbing, reduced-motion defaults and demo/real/marker-only labels. Blender independently reads the same contract and preserves timing/basis in GLB.
- `RUNBOOK.md` contains local commands. `requirements.lock.txt`, `environment.json` and `model-cache.json` inventory the current environment; they are not a tested clean-machine installer or proof of offline capture replay.

## Verification

The full suite passed **53 Python tests** and **10 JavaScript tests**, with no skips. Python tests ran real FFmpeg encoding/decoding and the installed Blender, including v2 validation, rational/irregular timestamps, missing markers, axes and output protection. Vite built using the existing dependency installation.

Browser checks exercised the built viewer: demo rendering, play/pause, keyboard start/end scrub, malformed local-file rejection with stale data cleared, valid local-file recovery, reduced-motion initial pause, a 390 px viewport without horizontal overflow and no captured warning/error console entries. No real exported capture was available.

Independent code review found four issues: mixed stale outputs, cam02 reference handling, concealed drift and non-atomic export. Each was reproduced in a failing regression and corrected. Further verified adapter corrections cover zero-based native TRC indices, FFmpeg rounding, floating-point projections, multiple detections before association and filtered/augmented artifact ownership.

Evidence: `C:\Users\soren\Projects\kinelab-team\evidence`, particularly `python-validation-final.txt`, `js-validation-final.txt`, `source-snapshot.json`, `integration-manifest.json`, RED/GREEN regression logs and `viewer-functional-proof.png`.

## Scope and recovery

Application: `C:\Users\soren\Documents\Projects\KineLab-PT-DualCam`. Verified backup: `C:\Users\soren\Projects\kinelab-team\snapshots\before-implementation-20261026`, including a scratch restoration check. Work was isolated in `C:\Users\soren\Projects\kinelab-team\project`. Integration verifies each overwritten original against its snapshot and records before/after hashes. Existing recordings, demo assets, environment and bundled tools are preserved. No Git history was invented.

Codex leads the work. Factory's verified native connection supplied exporter/viewer/Blender implementation. Antigravity's native handshake and supplied-code review succeeded; its implementation attempt was blocked by native command permission, which was not expanded. The owner then directed Codex to execute the original plan. Desktop UI agent handshakes are not claimed.

Rulings: use the verified snapshot instead of a Git worktree; retain the actual Pose2Sim reference timeline; disable inferred gap filling for measured acceptance; retain marker-only output until optional subject/model assumptions are confirmed. No production deployment, VPS change, marketing work or paid service was added.

## Remaining acceptance work

Task 7 is incomplete. Record the six clips, physically measure the board, supply independent start/end events, pass real calibration/sync/reconstruction gates, export the session, then replay in a new folder and offline after caches are prepared. OpenSim angles also require confirmed subject/model inputs. `projects/capture-20261026-trial01` contains configuration/templates only, with no valid `session.json` or fabricated measurements.
