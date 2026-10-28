# KineLab PT — Quality & Evidence Policy

## 1. Purpose & Scope
This policy governs data integrity, scientific reproducibility, and evidence management across the KineLab PT motion analysis platform. It establishes immutable rules for data collection, quality gating, reporting, and archival.

## 2. Hard Invariants (Zero-Tolerance Rules)
1. **Never Overwrite Raw Capture Footage**:
   All original video recordings (e.g., `cam01_board.mp4`, `cam02_trial.mp4`) are strictly read-only. Ingestion pipelines and normalization tools MUST create distinct derived files with provenance links and never modify or replace the raw capture inputs.
2. **Never Fabricate Calibration or Synchronization Data**:
   If calibration fails (e.g., reprojection error > 1.5 pixels, board undetected), the system MUST halt and transition to `CALIBRATION_FAILED`. Fabricating synthetic camera matrices or substituting default values is prohibited.
3. **Never Fabricate Joint Kinematics or Clinical Metrics**:
   If marker reconstruction or inverse kinematics produces missing data or poor tracking confidence, the system MUST report missing frames/coordinates explicitly. Interpolating across distant intervals without explicit operator confirmation is prohibited.
4. **Never Confuse Test Samples with Physical Captures**:
   External sample datasets (such as Caliscope public tests) MUST remain segregated in `projects/caliscope/external-source/` and carry explicit `TEST_ONLY` flags across all UI screens, logs, and exported reports.

## 3. The 10-Stage Evidence Passport
Every session in KineLab PT tracks its progression through an explicit 10-stage state machine:

| Stage | Level | Acceptance Criteria |
|---|---|---|
| `EMPTY` | 0 | Session directory created; no files registered. |
| `DRAFT` | 1 | Metadata initialized; partial files detected. |
| `SIX_FILES_PROBED` | 2 | Exactly 6 required video roles identified and probed via FFprobe. |
| `REGISTERED_ORIGINALS` | 3 | Physical measurement recorded (checkerboard square size in mm + operator), raw hashes computed, originals locked read-only. |
| `NORMALIZATION_PASSED` | 4 | Videos normalized to fixed framerate/codec; source timestamp mappings verified. |
| `CALIBRATION_PASSED` | 5 | Multi-camera intrinsic and extrinsic calibration calculated; mean reprojection error <= 1.5 px. |
| `SYNC_PASSED` | 6 | Temporal offset calculated between cameras; sync cue verified with cross-correlation score >= 0.85. |
| `3D_PASSED` | 7 | 3D marker triangulation complete; mean residual error <= 15 mm. |
| `KINEMATICS_PASSED` | 8 | OpenSim inverse kinematics solved; marker errors <= 20 mm; coordinate ranges physically plausible. |
| `RESEARCH_REPORTABLE` | 9 | Quality gates verified; multi-page PDF, JSON, and CSV research reports generated with complete audit trail. |

## 4. Hash Verification & Provenance Manifests
- Every processed artifact (TRC, MOT, normalized MP4, report PDF) MUST link to the SHA-256 digests of its input files.
- In-memory and on-disk verification ensures that any file tampering or silent corruption is immediately flagged as a quality violation.

## 5. Audit Logging & Session History
- All state transitions, calibration runs, and export actions are logged to the local SQLite database (`.kinelab_index.db`).
- Audit records include: timestamp (UTC), operator name, session ID, action type, parameters, input hashes, and outcome.
- Logs are append-only.
