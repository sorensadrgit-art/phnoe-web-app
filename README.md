# phnoe-web-app — KineLab PT DualCam

Private development repository for **KineLab PT**, a local-first phone + webcam motion-capture and movement-analysis research application.

> **Source import status:** The repository has been created, but the complete verified AgentZero source tree has **not yet been uploaded**. AgentZero became unavailable during the requested GitHub sync. This README and the safety configuration are preparatory only, not a claim that the project has been mirrored.

## Project components being prepared for version control

- Windows Capture Station and phone/webcam recording roles.
- Local session library, registration integrity, and operator-controlled processing.
- Pose2Sim/OpenSim calibration, pose estimation, 3D processing, and marker-only export.
- React + Three.js Motion Lab and synchronized review.
- Experimental gait and squat 2D analysis, explicitly separate from clinical measurements.
- Unified localhost application UI, token-gated API, Python/JavaScript tests, and deployment/operation documentation.

The latest verified **local** T6 checkpoint had **189 Python tests**, **33 JavaScript tests**, a successful Vite build, and a Chromium navigation smoke test. Those tests were run on AgentZero, **not in GitHub CI**.

## Important data exclusions

This repository is intended for **source code and vetted documentation only**. Do not commit videos, photographs of participants, patient records, hardware-specific camera recordings, calibration runs, cache/model downloads, credentials, localhost bearer tokens, local environment folders, Blender binaries, or build outputs.

When AgentZero is available, review a staged file manifest and scan for secrets before the first source commit. The included `.gitignore` is a safeguard, not a substitute for manual inspection. Preserve all original recordings locally.

## Current limits

KineLab PT is **a research and software-development prototype**. Online Caliscope examples are test-only. Real phone/webcam calibration, physical 3D accuracy, clinical outcome accuracy, clean-machine offline installation, and final v1.0 release acceptance are not established.

## Intended local project path

Source of truth on AgentZero: `C:\Users\soren\Documents\Projects\KineLab-PT-DualCam`.

Repository: `https://github.com/sorensadrgit-art/phnoe-web-app`

## SOREN résumé example

The latest editable portfolio is [Section Explorers v8](examples/soren-motion-v8/README.md): six distinct interactive sections, opt-in anatomy and movement viewers, and the retained v7 ribbon and films. Build it into a portable static site using its own package scripts.

[Motion Exhibits v7](examples/soren-motion-v7/README.md) remains available as the self-contained browser demo and editable Remotion/HyperFrames film source. Its rendered art and attributed study asset are scoped to the portfolio examples; the earlier v4 copy is also preserved.

Private repository. Do not publish or redistribute sample research footage without confirming its rights.
