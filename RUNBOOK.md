# KineLab local capture runbook

This is the functional local workflow. The existing demo is usable now. A real phone/webcam run still needs six original recordings and independent synchronization observations. No real capture accuracy has been established.

The application remains at `C:\Users\soren\Documents\Projects\KineLab-PT-DualCam`. The verified source backup and implementation evidence are under `C:\Users\soren\Projects\kinelab-team`. There is no Git repository or invented commit history. `requirements.lock.txt` inventories the existing Windows environment; clean-machine installation from that file has not been tested.

## Open the viewer

Use the existing desktop launcher, or run:

```powershell
$kinelabRoot = 'C:\Users\soren\Documents\Projects\KineLab-PT-DualCam'
$kinelabPython = Join-Path $kinelabRoot '.venv\Scripts\python.exe'
& $kinelabPython -B (Join-Path $kinelabRoot 'launch_motion_lab.py')
```

The launcher serves only `127.0.0.1`. The initial motion is explicitly a demo, with no joint-angle data. **Load local motion JSON** selects a file on this machine without uploading it. Invalid files show an error and clear stale data. Valid v1 files are labeled unbound legacy data; v2 files include session identity. Play/pause and keyboard scrubbing use actual source times. Reduced-motion mode starts paused.

**T4 review:** The viewer now includes left/right estimated joint-angle plots (with ROM over actual available samples) and a separate synchronized video panel. For **genuine real v2 motion only**, select all five local evidence files using the independent file controls: the exact `run.json`, `normalization.json`, `sync.json`, and normalized `videos/cam01.mp4` and `videos/cam02.mp4` from the SAME session. The application verifies the exact run-manifest SHA-256 against the motion export, matching session/configuration/input identities, passed native sync stages, observed source-frame pairs and drift, and the byte-for-byte SHA-256 of each MP4 before showing paired video previews. No local file is uploaded.

The common skeleton timeline drives browser seek targets using recorded signed camera offsets and normalized frame timestamps. **Browser-decoded video seek accuracy is not certified**, especially during active playback; pause and inspect a frame manually. Missing coverage remains visibly unavailable. The chart does not invent joint angles for marker-only sessions. No clinical validity or physical accuracy is implied by the software evidence check.

## 1. Prepare one recording session

An empty `projects/capture-20261026-trial01` was prepared during software checks. To create another session, choose a new directory:

```powershell
Set-Location -LiteralPath $kinelabRoot
& $kinelabPython -B setup_project.py --project projects\capture-new-trial --session-id capture-new-trial
```

Existing destinations are refused. `session-template.json` is an incomplete template, not a valid session. Use one smartphone and one webcam. Keep placement and lens/zoom settings fixed between calibration and the trial; use consistent orientation/resolution for each camera. Measure the printed board: 8×10 squares with 7×9 inner corners and 20 mm square sides. Do not assume printer scaling is correct.

Record these six clips and copy originals into the chosen session's `raw` folder using exactly these names:

- `cam01_intrinsics.mp4`: phone views of the board at multiple useful image positions.
- `cam02_intrinsics.mp4`: webcam intrinsic views.
- `cam01_board.mp4`, `cam02_board.mp4`: both cameras see the same stationary board, visible in the first frame.
- `cam01_trial.mp4`, `cam02_trial.mp4`: overlapping recordings of one subject, with a shared visible event near both the start and end.

The current native calibration path uses the first extrinsic frame. Do not pass a board clip that starts before the board becomes visible. Checkerboard detection checks visibility, not diverse views or physical scale. Calibration residuals and actual trial quality are separate gates.

## 2. Register and normalize

For the prepared session:

```powershell
$kinelabTrial = Join-Path $kinelabRoot 'projects\capture-20261026-trial01'
& $kinelabPython -B setup_project.py --project $kinelabTrial --register-captures
& $kinelabPython -B normalize_capture.py --project $kinelabTrial
```

Registration records SHA-256 hashes and refuses an existing `session.json`. All six originals must exist before any conversion starts. Normalization stages all outputs before replacing destinations, preserves original bytes/PTS, applies a consistent camera-specific image transform, and writes 1280×720 CFR 30 fps H.264 without audio. Audio, if present, remains in the originals. `normalization.json` records exact timestamp ticks, transforms, output hashes and source-frame mappings. Separate source durations are allowed; matching nominal frame rates do not prove synchronization.

To verify existing normalized outputs without re-encoding:

```powershell
& $kinelabPython -B normalize_capture.py --project $kinelabTrial --check-only
```

This writes only the new preflight report after successful checks. Original/config/output hash changes invalidate the previous report. `--overwrite` explicitly permits replacing normalized outputs after all conversions succeed; it never permits overwriting originals.

## 3. Calibrate, estimate pose and inspect synchronization

```powershell
& $kinelabPython -B run_pipeline.py --project $kinelabTrial --start calibration --stop poseEstimation
```

The calibration gate reads both camera matrices and the measured RMS residuals in the native log. Pose2Sim's `metadata.error=0.0` placeholder is ignored. Initial fitted RMS target: ≤2 px per camera; this is not a physical 3D error bound. Physically measured board scale remains a separate requirement.

Synchronization needs independent cue observations. Once the six originals are registered and normalization/preflight has passed, click **Review start/end cues** in the local Capture Station. Its two independent video viewers allow frame-by-frame inspection of the actual normalized clips: explicitly mark the same **start** and **end** event in **both** cameras. It suggests the shorter trial as reference; choose the reference, inspect the four frame indices, then explicitly confirm. The resulting `sync-observations.json` is immutable and labeled **pending_native_pose2sim_validation**; it is *not* a synchronization pass until Pose2Sim's independent native offset, correlation, reference camera and start/end residual checks agree. If events are unclear or drift exceeds one frame, obtain a new properly synchronized trial instead of entering guesses.

The observation file contains:

- `session_id`: the exact registered session ID; `fps`: 30.
- `reference`: the native synchronization reference camera.
- `inputs`: the six source hashes copied from `session.json`.
- `cameras`: each camera's integer `offset_frames`, independently measured `start_residual_frames`, and `end_residual_frames`.
- `source_frame_pairs`: start and end observations for each camera, each with `camera`, `synchronized_frame_index`, and `source_frame_index`.

The sign convention is `source_frame_index = synchronized_frame_index + offset_frames`. Frame numbers refer to normalized video frames/native pose indices, not an unrelated phone clock. An independent cue pair residual is `source_frame_index - synchronized_frame_index - offset_frames`. Start/end residuals must agree with those pairs, each be within one frame, and change by at most one frame. Do not fill observations with zero unless actually measured.

```powershell
& $kinelabPython -B run_pipeline.py --project $kinelabTrial --start synchronization --stop filtering
```

The native synchronization stage writes offsets/correlations in `logs.txt`; if independent observations are missing or disagree, the stage is recorded as failed even though its intermediate files may exist. Inspect that evidence, supply measured observations, and rerun from synchronization. Do not manually mark stages passed.

Pose2Sim selects the shorter recording as its reference, so either camera may be the reference; its offset must be zero. Retain that timeline and use distinct start/end pairs from each camera. Resume requires exactly the recorded artifact inventory. Mixed old/new outputs cause rejection; preserve old results and use a clean session when a rerun leaves extra files.

The first pilot requires the configured `Body_with_feet` model and two cameras. Acceptance triangulation explicitly disables interpolation and last-value gap filling; this effective policy is recorded in `run.json`. Quality reprojects the unfiltered native TRC into actual associated 2D poses and requires ≥95% two-view support for required lower-limb points, ≤15 px residual support, and no required-marker gap longer than three frames. These are initial engineering targets, not clinical validation. Quality reports record the accepted time interval.

`run.json` records stage states and actual output hashes. Missing/stale/malformed output, changed input/configuration, unavailable measurements, or native errors stop subsequent stages. A `run.lock` prevents concurrent processing. Use **Inspect / recover interrupted action** in Capture Station to examine `run.lock`, `workflow.lock`, and the native `run.json` states. The app shows which stages were interrupted, and only offers optional lock archival after it establishes the original PID is no longer running and finds no related native workers. Archival requires explicit confirmation and keeps lock contents for diagnosis. It NEVER treats the remaining artifacts as valid; if old or mixed outputs conflict, preserve them and create a clean session. Do not manually remove a lock while its process may still be active.

## 4. Export marker-only motion first

Use the explicit filtered TRC named in `run.json`; do not guess the newest file:

```powershell
& $kinelabPython -B export_motion.py --project $kinelabTrial --run-manifest (Join-Path $kinelabTrial 'run.json') --trc '<exact-filtered-TRC-path>' --no-mot --out (Join-Path $kinelabTrial 'exports\capture.motion.json')
```

Existing export destinations are refused. The exporter validates units/counts/times and verifies session/config/input/calibration/TRC bindings. Load the resulting JSON using the viewer's local-file control. Marker-only output never claims joint-angle availability.

## 5. Optional OpenSim and Blender

Only after the marker run passes, confirm subject/model assumptions before marker augmentation and kinematics. The template's 70 kg mass, automatic height and fallback 1.7 m are not measured subject facts.

```powershell
& $kinelabPython -B run_pipeline.py --project $kinelabTrial --start markerAugmentation --stop kinematics
& $kinelabPython -B export_motion.py --project $kinelabTrial --run-manifest (Join-Path $kinelabTrial 'run.json') --trc '<exact-augmented-TRC-path>' --mot '<exact-MOT-path>' --out (Join-Path $kinelabTrial 'exports\capture-angles.motion.json')
```

TRC/MOT must belong to the same run with matching temporal coverage. Angular and translational coordinates keep distinct units; only angular values convert to degrees for display. Unsupported coordinate names require an explicit verified unit mapping rather than guessing.

Blender and Three.js independently consume the motion JSON. Blender uses actual timestamps and rational FPS/FPS-base; GLB is Y-up. It refuses existing output files:

```powershell
$kinelabBlender = Join-Path $kinelabRoot 'tools\blender-4.5.15-windows-x64\blender.exe'
& $kinelabBlender -b --python-exit-code 1 --python (Join-Path $kinelabRoot 'blender_import.py') -- (Join-Path $kinelabTrial 'exports\capture.motion.json') (Join-Path $kinelabTrial 'exports\capture.blend') (Join-Path $kinelabTrial 'exports\capture.glb')
```

## Verification and limits

```powershell
& $kinelabPython -B -m unittest discover -s tests -v
node --test viewer\src\motionData.test.js
```

The tests use synthetic inputs, existing demo data, real FFmpeg encoding/decoding, and the installed Blender executable. Those establish software behavior, not physical measurement accuracy. A real end-to-end acceptance run and offline repeat remain pending the actual six recordings, measured board and independent cues. Model-cache/network availability for a fresh full Pose2Sim run is not yet verified. No VPS operation, paid integration, market/release work or clinical validation is part of this implementation.
