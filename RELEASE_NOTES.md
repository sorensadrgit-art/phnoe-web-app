# KineLab PT v1.0.0-rc1 — Release Notes

**Build Date**: October 27, 2026  
**Status**: Research Release Candidate 1 (`SOFTWARE_BUILD_VERIFIED`)  
**Target Platform**: Windows 10 / 11 64-bit  

---

### Highlights & Key Capabilities

1. **Unified Research Workspace**:
   - Single desktop entry point (`KineLab PT.lnk`) replacing disparate scripts and multi-window launchers.
   - Clean, accessible web interface running locally on `127.0.0.1` with ephemeral cryptographic token security.

2. **10-Stage Evidence Passport**:
   - Explicit gating from raw capture registration (`EMPTY`) to research reporting (`RESEARCH_REPORTABLE`).
   - Cryptographic SHA-256 integrity inspection for every raw capture and processed artifact.
   - Strict segregation and prominent UI labeling of external test datasets.

3. **Guided Capture Wizard**:
   - Protocol-driven 6-role camera registration (Phone Cam 1 vs Webcam Cam 2).
   - In-app physical calibration input (ruler measurement in mm + operator signature).
   - Pre-flight checklist for lighting, focus lock, checkerboard flatness, and sync cues.

4. **T7 SQLite History & Vector PDF Reporting**:
   - Automatic background indexing into local `.kinelab_index.db`.
   - Side-by-side session comparison with parameter difference highlighting.
   - Multi-page vector PDF reports generated via Matplotlib (no external renderer dependencies).
   - Machine-readable JSON summary and CSV export.

5. **Staged Atomic Backup & Restore**:
   - Full session and database backup into verified `.zip` archives.
   - Staged restore in isolated scratch folders with 100% hash verification before commit.

6. **T8 Offline Distribution Packaging**:
   - Portable Windows bundle with batch launcher (`Start-KineLabPT.bat`) and desktop shortcut installer.
   - Zero cloud or internet dependencies.

---

### Verification & Testing
- 214 Python unit tests passing.
- 27 JavaScript unit tests passing.
- 100% raw video integrity preserved.

### Physical & Clinical Notice
KineLab PT is experimental research software. See `docs/PHYSICAL_VALIDATION_PENDING.md` for current validation status and physical laboratory requirements.
