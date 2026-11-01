# Current candidate package notice

Current candidate acceptance: NOT_GRANTED. Clean-machine validation: NOT_RUN. Physical validation: BLOCKED_ON_PHYSICAL_EVIDENCE. Clinical validation: UNVERIFIED.

The report below is retained historical evidence from an earlier workstation package. Its archive hash, file counts, dependencies and PASS/status claims do not describe or verify this candidate. Its original shortcut instructions are superseded: preserve the existing installation and original shortcut; use only the isolated KineLab PT Candidate entry point and fresh TEST_ONLY data for current candidate verification.

Follow the generated README-OFFLINE-INSTALL.md and app/RUNBOOK.md in this package. Verify this package against its own DISTRIBUTION-MANIFEST.json. Package integrity proves file hashes only; it does not grant runtime, clean-machine or release acceptance.

<!-- CURRENT-CANDIDATE-NOTICE:END -->
# KineLab PT — Clean-Machine Installation & Verification Report

## 1. Package Specifications
- **Package Name**: `KineLabPT-v1.0.0-windows-x64`
- **Archive Path**: `dist/KineLabPT-v1.0.0-windows-x64.zip`
- **Archive Size**: 710,453 bytes
- **SHA-256 Digest**: `ee627f33a07977b8972c7a0c8ddc0edc2d2b406c253c5f4be4dc96163ff538e5`
- **Total Packaged Files**: 45 files (verified 100% against manifest)
- **Target Platform**: Windows 10 / 11 64-bit (x86_64)

## 2. Clean-Machine Prerequisites
To deploy this distribution on a fresh, air-gapped clinical workstation without developer tooling:
1. **Operating System**: Windows 10 (version 19041+) or Windows 11.
2. **Visual C++ Redistributable**: Microsoft Visual C++ 2015–2022 Redistributable (x64) installed (required by OpenSim and ONNX Runtime native DLLs).
3. **Python Runtime**: Python 3.10–3.13 64-bit installed with standard libraries.
4. **Offline Dependencies**:
   - Pose2Sim 0.10.49, OpenSim 4.6, ONNX Runtime 1.31.0, Matplotlib, PySide6 installed via offline wheel cache or bundled `.venv`.
   - FFmpeg executable on system PATH or placed in `tools/`.
5. **Model Weights**:
   - The 4 required ONNX models (`rtmpose-m...`, `yolox_m...`, `LSTM/v0.3_lower`, `LSTM/v0.3_upper`) pre-populated in `%USERPROFILE%\.cache\rtmlib\hub\checkpoints\` and Pose2Sim package directories per `model-cache.json`.

## 3. Installation & Verification Protocol
1. **Extraction**: Unpack `KineLabPT-v1.0.0-windows-x64.zip` to target application directory.
2. **Integrity Check**:
   Run `python -c "import json, hashlib, pathlib; ..."` or `tools/build_offline_distribution.py` verification pass to confirm all 37 file hashes match `DISTRIBUTION-MANIFEST.json`.
3. **Shortcut Creation**:
   Execute `powershell -ExecutionPolicy Bypass -File .\Install-DesktopShortcut.ps1`.
   Verify that exactly one shortcut named `KineLab PT.lnk` is created on the Desktop pointing to `t6_launcher.py` with `assets/kinelab-pt.ico`.
4. **Offline Startup**:
   Disconnect network interfaces (air-gap verification).
   Launch `Start-KineLabPT.bat` or double-click `KineLab PT.lnk`.
   Confirm the application binds to `127.0.0.1:4184+`, opens the browser with token fragment `#access=<token>`, and renders the unified dashboard without console errors or outbound network attempts.

## 4. Current Workstation Verification Status
- **Software Build Status**: `SOFTWARE_BUILD_VERIFIED`
- **Offline Package Status**: `PACKAGE_INTEGRITY_VERIFIED`
- **Air-Gapped Clean Machine Hardware Proof**: `PENDING_INDEPENDENT_HARDWARE_PROVISIONING`
  - Automated tests pass on development workstation `AGENTZERO` (Windows 11).
  - Clean-machine test on separate unconfigured hardware requires physical workstation access.
