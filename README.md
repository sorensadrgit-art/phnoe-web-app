# KineLab PT — Motion Analysis Research Platform & Live Tracker Studio

[![Software Status](https://img.shields.io/badge/software--build-verified-brightgreen.svg)]()
[![Test Suite](https://img.shields.io/badge/tests-266%20passed%20(223%20Python%20%2B%2043%20JS)-success.svg)]()
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-blue.svg)]()
[![Architecture](https://img.shields.io/badge/network-localhost%20only%20(127.0.0.1)-orange.svg)]()
[![Clinical Status](https://img.shields.io/badge/clinical--validation-unverified%20(research%20prototype)-yellow.svg)]()

**KineLab PT** is a local-first, privacy-preserving physical therapy motion analysis and biofeedback platform for Windows. It operates entirely offline without cloud dependencies, external telemetry, or data transmission.

The platform provides two complementary operating modes:
1. **Live Tracker Studio**: A camera-first, zero-latency biofeedback studio with an interactive heads-up display (HUD), real-time joint angle trigonometry, exercise rep counting, form coaching alerts, a live Three.js 3D digital twin avatar, and instant clinical report generation.
2. **Research Lab**: A multi-camera guided capture and batch processing pipeline for synchronized phone and webcam recordings, checkerboard/Caliscope extrinsics calibration, Pose2Sim 3D triangulation, OpenSim inverse kinematics (IK), and cryptographic evidence passports.

---

## Architecture Overview

```
KineLab PT Unified Platform
│
├── Live Tracker Studio (Real-Time Interactive Mode)
│   ├── Camera Input: Local webcam, external USB wide-angle camera, or phone stream
│   ├── Kinematics Engine (liveKinematics.js): Knee flexion, hip angle, 3D trunk lean, valgus, symmetry
│   ├── Exercise State Machine (exerciseStateMachine.js): Squat, Lunge, Knee Extension, Balance reps & faults
│   ├── Biofeedback HUD (LiveHUDOverlay.jsx): High-contrast skeleton lines, angle badges, dynamic depth gauge
│   ├── 3D Digital Twin (LiveDigitalTwin.jsx): Three.js real-time 3D skeleton avatar with 360° orbit controls
│   └── Instant Reporting: Vector PDF Biofeedback & Form Coaching Report with Matplotlib trajectory curves
│
├── Research Lab (Multi-Camera Batch Pipeline)
│   ├── Guided Capture Wizard: 6-role camera registration (Phone Cam 1 & Webcam Cam 2)
│   ├── Evidence Passport: 10-stage state machine (EMPTY → RESEARCH_REPORTABLE) with SHA-256 checks
│   ├── Processing Pipeline: 01 Normalize → 02 2D Pose → 03 Reconstruct 3D → 04 Export OpenSim IK
│   ├── 3D Motion Lab: Synchronized dual-camera video playback with 3D skeleton review
│   └── Analysis & Reports: Gait events, squat symmetry, and multi-page vector clinical PDF reports
│
└── Core System & Security
    ├── Loopback Server (t6_server.py): Bound strictly to 127.0.0.1 with bearer token authentication
    ├── Supervised Launcher (t6_launcher.py): In-process server lifecycle, instant localhost reuse
    ├── SQLite Storage (session_index.py): Local metadata indexing and search (.kinelab_index.db)
    └── Backup Manager (backup_manager.py): Atomic staged backup and restore with 100% SHA-256 verification
```

---

## Quick Start

### Prerequisites
- **Operating System**: Windows 10 (version 19041+) or Windows 11 64-bit.
- **Python**: Python 3.10–3.13 64-bit.
- **Visual C++ Redistributable**: Microsoft Visual C++ 2015–2022 Redistributable (x64) installed.

### Launching the Application
Double-click the desktop shortcut **`KineLab PT.lnk`**, or run from PowerShell:
```powershell
python t6_launcher.py
```

To start without automatically opening the default browser:
```powershell
python t6_launcher.py --no-browser
```

The launcher starts the server on `127.0.0.1:4184`, writes diagnostic logs to `%LOCALAPPDATA%\KineLabPT\t6-server.log`, and opens the authenticated application in your browser:
```
http://127.0.0.1:4184/#access=<64-character-token>
```

> **Fast Reuse**: If KineLab PT is already running, launching it again detects the active instance in under 0.2s, opens a browser tab, and exits cleanly without spawning duplicate processes.

---

## Feature Details

### 1. Live Tracker Studio
- **Camera-First Viewport**: Real-time video preview with device selection and horizontal mirror toggle.
- **Biomechanical Angles**:
  - **Knee Flexion**: Clinical convention ($0^\circ$ = straight standing, $90^\circ$ = right angle, $120^\circ+$ = deep squat).
  - **Hip Angle**: Trunk-to-thigh flexion angle.
  - **3D Trunk Lean**: True sagittal spinal tilt calculated via 3D depth vectors ($\sqrt{dx^2 + dz^2}$).
  - **Knee Valgus / Varus**: Medial deviation relative to the pelvic midline to prevent false-positives on mirrored feeds.
  - **Bilateral Symmetry**: Left vs. right loading balance percentage.
- **Exercise Presets**:
  - **Squat**: Deep ($90^\circ+$), Functional ($75^\circ$), and Gentle ($60^\circ$) target depths.
  - **Lunge**: Unilateral lead-leg tracking with trail-leg clearance checks.
  - **Knee Extension**: Seated or standing terminal extension monitoring.
  - **Single-Leg Balance**: Dynamic wall-clock hold duration timer and center-of-mass sway detection.
- **Real-Time Coaching HUD**:
  - Large readable rep counter visible from 6–10 feet away.
  - Dynamic depth arc gauge that fills and turns green upon reaching target ROM.
  - Form coaching callout banner (*"Push knees outward"*, *"Excessive trunk lean"*, *"Great depth"*).
- **Interactive 3D Digital Twin**: Split-screen or picture-in-picture view with a Three.js 3D skeleton avatar that mirrors movements in real time with 360° orbit controls.
- **One-Click Session Ingestion**: Clicking **"Finish Set"** allows saving the set directly into KineLab's local SQLite database and generating an instant Clinical Summary PDF.

### 2. Research Lab Pipeline
- **6-Role Video Matrix**:
  - `cam01_intrinsics`, `cam02_intrinsics`: Checkerboard intrinsic camera calibration.
  - `cam01_board`, `cam02_board`: Extrinsic board calibration for spatial alignment.
  - `cam01_trial`, `cam02_trial`: Synchronized movement trial recordings.
- **Evidence Passport**: Enforces strict scientific integrity gates (`EMPTY` $\rightarrow$ `DRAFT` $\rightarrow$ `SIX_FILES_PROBED` $\rightarrow$ `CHECKERBOARD_CALIBRATED` $\rightarrow$ `POSE2D_ESTIMATED` $\rightarrow$ `RECONSTRUCTED_3D` $\rightarrow$ `MARKERS_EXPORTED` $\rightarrow$ `REPORT_COMPILED` $\rightarrow$ `RESEARCH_REPORTABLE`).
- **Processing Stage-Gates**: Operator-controlled processing via Pose2Sim triangulation, Butterworth filtering, and OpenSim inverse kinematics.

---

## Verification & Testing

The platform includes full automated test suites across both Python and JavaScript:

### Running JavaScript Unit Tests
```powershell
npm --prefix viewer test
```
*43 tests pass across 6 suites in ~110ms (`liveKinematics.test.js`, `exerciseStateMachine.test.js`, `motionData.test.js`, `syncPlayback.test.js`, `unifiedLogic.test.js`, `unifiedModel.test.js`).*

### Building Frontend Production Bundle
```powershell
npm --prefix viewer run build
```
*Vite compiles the production bundle in ~11s without warnings or syntax errors.*

### Running Python Unit & Regression Tests
```powershell
python -m unittest discover -s tests
```
*223 tests pass across 23 test modules in ~55s (covering security, API endpoints, launcher lifecycle, report generation, live session ingestion, and backup/restore).*

---

## Standalone Offline Distribution Package

To build the standalone portable distribution package for deployment on air-gapped clinical workstations:
```powershell
python tools/build_offline_distribution.py
```
This produces `dist/KineLabPT-v1.0.0-windows-x64.zip` containing all core modules, compiled UI, desktop shortcuts, model configurations, and documentation, verified 100% against `DISTRIBUTION-MANIFEST.json`.

---

## Security, Privacy & Integrity Guarantees

1. **Loopback Only**: Server binds exclusively to `127.0.0.1`. Remote network interfaces cannot access the API.
2. **DNS Rebinding Defense**: Host header validation rejects non-loopback hosts.
3. **Token Authorization**: Ephemeral 64-character bearer tokens are passed via the URL fragment (`#access=<token>`) and stored in local browser storage, never transmitted in query strings or server access logs.
4. **Zero Cloud / Zero Telemetry**: No analytical trackers, third-party CDNs, external font requests, or cloud APIs.
5. **Immutable Source Footage**: Original camera recordings are immutable; cryptographic SHA-256 digests are verified before and after all processing operations.

---

## Clinical Status Disclaimer

> **Research & Development Prototype Notice**:  
> KineLab PT is an investigative software research platform. Measurements, kinematic curves, and exercise form feedback are provided for research, motion coaching, and experimental validation only. They are **not** certified diagnostic medical devices and should not be used as the sole basis for clinical diagnosis or surgical planning without independent physical calibration against optical motion-capture gold standards.
