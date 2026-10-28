# KineLab PT — Physical & Clinical Validation Status

## Status Declaration
- **Software Build Status**: `SOFTWARE_BUILD_VERIFIED`
- **Physical Research Validation**: `BLOCKED_ON_PHYSICAL_EVIDENCE`
- **Clinical Validation**: `UNVERIFIED`

---

## 1. Regulatory & Research Disclaimer
**KineLab PT is experimental research software, NOT a cleared medical device.**
It has not been reviewed, cleared, or approved by the United States Food and Drug Administration (FDA), European Medicines Agency (EMA), or any other regulatory authority.
It is intended solely for biomechanics research, physical therapy movement science experimentation, and laboratory algorithm evaluation.
It MUST NOT be used for primary medical diagnosis, patient surgical planning, or direct therapeutic intervention without independent clinical validation.

---

## 2. Inventory of Missing Physical Evidence (Blockers)

While all software modules, test suites, algorithms, and packaging are verified and passing, end-to-end scientific validation is pending the collection of physical laboratory evidence:

### Blocker 1: Missing Camera 1 (Phone) Physical Video
- **Current State**:
  The development repository contains physical recordings exclusively for Camera 2 (Webcam):
  - `projects/capture-20261026-trial01/raw/cam02_board.mp4` (SHA-256: `5EBEFC8748E5D93FADFE07497C8F27913F8A9FD3E42F17FBCFF8E850008B45F7`)
  - `projects/capture-20261026-trial01/raw/cam02_trial.mp4` (SHA-256: `BE641DAE4C5CA92FA67B1619048800AF7D62EBB06C1184109D6E55CE09027C13`)
- **Blocker Detail**:
  Camera 1 (Phone) recordings (`cam01_board.mp4`, `cam01_trial.mp4`) were not physically collected during the 2026-10-26 trial.
- **Resolution Path**:
  A new dual-camera trial must be physically conducted using the Guided Capture Wizard protocol, recording simultaneous footage from both Phone (Cam 1) and Webcam (Cam 2).

### Blocker 2: Physical Calibration Board Ground-Truth Measurement
- **Current State**:
  A standard 20.0 mm checkerboard pattern was generated (`make_board.py`).
- **Blocker Detail**:
  The physical printout of the board must be measured with calibrated digital vernier calipers by the operator, and the exact dimension entered into the registration wizard to prevent spatial scale error in 3D triangulation.

### Blocker 3: Hardware Camera Synchronization Cue
- **Current State**:
  Audio-visual sync algorithm is implemented and verified on synthetic / sample pairs.
- **Blocker Detail**:
  Physical trial recordings require a clear visual flash or sharp acoustic/visual contact event (e.g. clapboard or foot-strike stomp visible to both cameras) to compute cross-camera frame alignment.

### Blocker 4: Optical Motion Capture Ground-Truth Comparison
- **Current State**:
  Pose2Sim and OpenSim inverse kinematics pipelines operate deterministically and pass all numerical unit tests.
- **Blocker Detail**:
  Markerless 3D joint centers have not yet been validated against a gold-standard optical marker system (e.g., Vicon, Qualisys, or OptiTrack) with synchronized force plates to quantify kinematic accuracy (mean absolute error in degrees across sagittal, frontal, and transverse planes).

### Blocker 5: Clinical Protocol & Inter-Rater Reliability
- **Current State**:
  Automated gait event detection and squat depth metrics are implemented.
- **Blocker Detail**:
  Formal clinical protocol review, test-retest reliability studies, and inter-rater agreement across multiple physical therapy practitioners are pending future clinical trials.
