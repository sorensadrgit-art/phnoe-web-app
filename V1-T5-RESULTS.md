# KineLab PT v1.0 — T5 exploratory gait-analysis checkpoint

**Date:** October 27, 2026  
**Execution:** AgentZero (Windows, fully local)  
**Status:** Software subset implemented and tested. The broader T5 milestone is **PARTIAL**, awaiting manual reference review, squat-analysis work and real calibrated camera acceptance.

## What was implemented

1. **Pure gait signal processor:** `gait_events.py` validates hash-bound, ordered 30 FPS HALPE26 **2D** trajectories and proposes conservative left/right heel and big-toe horizontal image-motion extrema relative to the detected pelvis. It uses a seven-frame smoothing window only where all source samples are observed, excludes low model-score landmarks without interpolation, requires prominence/spacing, and never estimates physical meters, stride length, or gait cadence.
2. **Orientation requirement:** Extrema have no contact/toe-off interpretation until the operator explicitly identifies the camera's **screen-forward direction**. Even then, event labels remain unvalidated hypotheses.
3. **Human-reference contract:** Explicitly named and confirmed video observations (frame, body side, event kind), one-to-one matching within a configurable ±frame tolerance, score and source-hash binding, rejection of duplicate/foreign/malformed or machine-created reference records. `None` reference produces unavailable precision/recall, not a false 100% score.
4. **Offline review application:** The standalone local `external-source/gait-t5/index.html` offers both 12-second annotated videos, separate camera selection/frame stepping, manual event recording/export/import, optional direction selection, 2D heel/toe signal plots, raw extrema overlays and exploratory one-to-one agreement. Automated suggestions are initially hidden by the UI; once revealed, that camera's reference labels are frozen.
5. **Windows desktop shortcut:** `C:\Users\soren\OneDrive\Desktop\KineLab PT - Gait Event Review.lnk` opens the review HTML. `projects/caliscope-walking-test-20261027/GAIT-REVIEW-QUICKSTART.md` contains operator instructions.
6. **Traceable evidence:** `gait-t5-summary.json`, two camera-specific immutable candidate reports, `ui-provenance.json` with content SHA-256, independent browser screenshot, and original source file checksums.

## Actual isolated Caliscope test fixture

| Measure | Camera 1 | Camera 2 |
|---|---:|---:|
| Real source video | Caliscope cam_1 | Caliscope cam_3 |
| Original trial frames | 360 | 360 |
| Existing 2D detected-person frames | 360 | 360 |
| Usable heel + big-toe 2D signal coverage | 100% | 100% |
| **Unassigned 2D extrema** | **55** | **66** |
| Actual manually observed initial contacts / toe-offs | **0** | **0** |
| Clinical gait event accuracy | Unverified | Unverified |

The 55/66 counts combine heels, toes, extrema and both sides. They are **not** counted walking steps, treadmill contacts, gait cadence, ground-truth events or a substitute for human annotations.

## Verified execution

- **Test-first Python:** 11 new `tests/test_gait_events.py` tests passed (after red import test and a red human-reference safety test). Full suite: **125 Python tests passed**.
- **Test-first JavaScript:** 8 new `viewer/src/gaitReviewLogic.test.cjs` tests passed. Full viewer test set: **23 JavaScript tests passed**.
- **Vite production build:** passed. Existing large-chunk advisory is not a test failure. KineLab Capture Station GUI smoke passed.
- **Chrome browser interaction:** both source MP4 files loaded with 12-second duration; candidate proposals initially hidden; no-consent mark refused; camera switch displayed the selected Cam 2 source; +1 frame updated the readonly time. Final browser interaction result: `T5_UI_BROWSER_INTERACTION_SMOKE_PASS`.
- **UI defect repaired:** An actual failing browser test revealed `selected-record` readonly INPUT displayed the previous camera because script assigned `textContent`. The UI now assigns INPUT `value` and retest passed; generated HTML and original template hashes were revalidated.
- **Source integrity:** Previous 720-frame 2D report and both tracked videos re-audited; all frame data re-derived and hashes matched. Real webcam originals `cam02_board.mp4` and `cam02_trial.mp4` remained unchanged. The test-only folder contains no `session.json`, `run.json`, `sync.json`, `sync-observations.json` or `preflight.json`.
- **Manual labels:** No automated or invented review annotations were persisted. `gait_event_ground_truth_provided=false`, `manual_reference_count=0`.

## Engineering files

Application:
- `gait_events.py`
- `tests/test_gait_events.py`
- `viewer/src/gaitReviewLogic.cjs`
- `viewer/src/gaitReviewLogic.test.cjs`

Isolated example workspace:
- `projects/caliscope-walking-test-20261027/external-source/generate_gait_t5.py`
- `.../gait-t5/{cam01_trial_gait_candidates.json,cam02_trial_gait_candidates.json,gait-t5-summary.json,index.html,ui-provenance.json}`
- `.../gait-review-template.html`, `.../make_gait_review.py`, `.../verify_gait_ui.py`, `.../finalize_gait_ui.py`
- `.../test_gait_browser.cjs`, `.../gait-t5/gait-browser-qa.png`
- `C:\Users\soren\Projects\kinelab-team\evidence\v1-execution\t5-full-python.log`, `t5-js.log`, `t5-vite.log`, `t5-video-integrity.log`.

The earlier project rollback snapshot remains at `C:\Users\soren\Projects\kinelab-team\snapshots\pre-v1-execution-20261026` (captures excluded; source snapshot only).

## Explicit limitations and next acceptance

1. **Human review is still needed.** The user must inspect real video frames, label visible side-specific events, export/import separate source-bound manual-reference files and compare only after selecting the visible screen-forward direction. The UI hides proposals until annotation but their JSON exists locally, so this is not a rigorous blinded clinical protocol.
2. **Gait event ground truth unavailable.** No independently instrumented contact measurements or checked full-reference labels exist. High 2D model scores and smooth image trajectories do not establish heel strike timing, toe-off accuracy, gait speed, 3D kinematics or clinical validity.
3. **T5 not fully complete.** A synthetic-fixture-only 2D squat phase/repetition detector was implemented after this initial report; see `V1-T5-SQUAT-ADDENDUM.md`. Real squat footage and manual validation, clinical/model output acceptance, gait-event threshold generalization, and main-viewer workflow integration remain outstanding.
4. **Full v1.0 incomplete.** T6 integrated desktop user experience, T7 local reports/history, T8 offline Windows installer, T9 real phone + webcam physically measured calibration and T10 release sign-off still require work. Caliscope footage cannot be used to bypass the real-capture gate.
5. **Offline file scope.** The review page and metrics work entirely on localhost or file-based data; it does not upload videos or create clinical records.

**Next user action:** Open the single desktop icon `KineLab PT`, select **Gait Event Review** under Research / Test Viewers, and follow `GAIT-REVIEW-QUICKSTART.md`. Mark visually observed events personally for each camera, then export manual-reference JSON files. Candidate-vs-annotation agreement can only be assessed after review and remains provisional.
