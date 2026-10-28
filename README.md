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

## SOREN résumé example

The latest independent portfolio copy is [Motion Exhibits v7](examples/soren-motion-v7/README.md). It includes a self-contained browser demo and editable Remotion/HyperFrames sources. Its rendered art and attributed study asset are scoped to that example; the earlier v4 copy is preserved.

Private repository. Do not publish or redistribute sample research footage without confirming its rights.
