# KineLab PT — Shared 44-Task Board

**State:** planning only; every addition is NOT STARTED. See [Full audit](../audits/KineLab_PT_Production_Readiness_Report.md), [Acceptance catalog](TASK_CATALOG.md) and [Master plan](MASTER_PLAN.md).

| ID | Task | Priority | Milestone | Lead lane | Status |
|---|---|---|---|---|---|
| [B01](TASK_CATALOG.md#b01) | Real acquisition and permanent source provenance | BLOCKER | M1 | Shared | NOT STARTED |
| [B02](TASK_CATALOG.md#b02) | One strict runtime measurement contract | BLOCKER | M1 | Codex | NOT STARTED |
| [B03](TASK_CATALOG.md#b03) | Incremental durable session recording | BLOCKER | M2 | Codex | NOT STARTED |
| [B04](TASK_CATALOG.md#b04) | Atomic finalization and multi-file publication | BLOCKER | M2 | Codex | NOT STARTED |
| [B05](TASK_CATALOG.md#b05) | Idempotency, concurrency and one authoritative writer | BLOCKER | M2 | Codex | NOT STARTED |
| [B06](TASK_CATALOG.md#b06) | Immutable evidence and fail-closed prerequisite gates | BLOCKER | M1 | Codex | NOT STARTED |
| [B07](TASK_CATALOG.md#b07) | Correct index, schema migrations and durable audit history | BLOCKER | M1 | Codex | NOT STARTED |
| [B08](TASK_CATALOG.md#b08) | Safe restore validation and containment | BLOCKER | M1 | Codex | NOT STARTED |
| [B09](TASK_CATALOG.md#b09) | Coherent backup and rollback-capable recovery | BLOCKER | M2 | Codex | NOT STARTED |
| [B10](TASK_CATALOG.md#b10) | Subject/operator identity and asynchronous UI isolation | BLOCKER | M1 | Antigravity | NOT STARTED |
| [B11](TASK_CATALOG.md#b11) | Valid geometry, confidence and occlusion rejection | BLOCKER | M3 | Antigravity | NOT STARTED |
| [B12](TASK_CATALOG.md#b12) | Correct exercise semantics and immutable set lifecycle | BLOCKER | M3 | Antigravity | NOT STARTED |
| [B13](TASK_CATALOG.md#b13) | Run-bound calibration and synchronization | BLOCKER | M3 | Research/clinical | NOT STARTED |
| [B14](TASK_CATALOG.md#b14) | Complete timelines and physically possible 3D | BLOCKER | M3 | Research/clinical | NOT STARTED |
| [B15](TASK_CATALOG.md#b15) | Model fitting, filtering and IK validity | BLOCKER | M3 | Research/clinical | NOT STARTED |
| [B16](TASK_CATALOG.md#b16) | Truthful, reproducible reports and exports | BLOCKER | M1 | Codex | NOT STARTED |
| [B17](TASK_CATALOG.md#b17) | Reference validation for every clinical measurement claim | BLOCKER | M3 | Research/clinical | NOT STARTED |
| [B18](TASK_CATALOG.md#b18) | Live freshness, bounded performance and safe interruption | BLOCKER | M3 | Antigravity | NOT STARTED |
| [B19](TASK_CATALOG.md#b19) | Data protection before human recording | BLOCKER | M4 | Codex | NOT STARTED |
| [B20](TASK_CATALOG.md#b20) | Reproducible supported release and failure gates | BLOCKER | M4 | Codex | NOT STARTED |
| [B21](TASK_CATALOG.md#b21) | Measured muscle acquisition and synchronization | BLOCKER | M3 | Research/clinical | NOT STARTED |
| [R01](TASK_CATALOG.md#r01) | Protected persistent data root and upgrade preservation | REQUIRED | M2 | Codex | NOT STARTED |
| [R02](TASK_CATALOG.md#r02) | Recoverable jobs and safe shutdown | REQUIRED | M2 | Codex | NOT STARTED |
| [R03](TASK_CATALOG.md#r03) | Guided subject, protocol and calibration setup | REQUIRED | M3 | Antigravity | NOT STARTED |
| [R04](TASK_CATALOG.md#r04) | Complete session review, history and compatible comparisons | REQUIRED | M5 | Antigravity | NOT STARTED |
| [R05](TASK_CATALOG.md#r05) | Reliable offline operation and explicit sync policy | REQUIRED | M4 | Codex | NOT STARTED |
| [R06](TASK_CATALOG.md#r06) | Honest research gait/squat analysis | REQUIRED | M5 | Research/clinical | NOT STARTED |
| [R07](TASK_CATALOG.md#r07) | Model-specific confidence and coordinate adapters | REQUIRED | M3 | Research/clinical | NOT STARTED |
| [R08](TASK_CATALOG.md#r08) | Complete interoperable evidence export | REQUIRED | M4 | Shared | NOT STARTED |
| [R09](TASK_CATALOG.md#r09) | Accessible clinical workflows | REQUIRED | M5 | Antigravity | NOT STARTED |
| [R10](TASK_CATALOG.md#r10) | Responsive layout and readable hierarchy | REQUIRED | M5 | Antigravity | NOT STARTED |
| [R11](TASK_CATALOG.md#r11) | Complete error, loading and empty states | REQUIRED | M5 | Antigravity | NOT STARTED |
| [R12](TASK_CATALOG.md#r12) | Performance and operational diagnostics | REQUIRED | M4 | Codex | NOT STARTED |
| [R13](TASK_CATALOG.md#r13) | Dependency, model and release provenance | REQUIRED | M4 | Codex | NOT STARTED |
| [R14](TASK_CATALOG.md#r14) | One supported API/launcher contract | REQUIRED | M4 | Codex | NOT STARTED |
| [R15](TASK_CATALOG.md#r15) | Evidence-derived documentation and status badges | REQUIRED | M4 | Codex | NOT STARTED |
| [R16](TASK_CATALOG.md#r16) | Model/protocol change control and regression corpus | REQUIRED | M3 | Research/clinical | NOT STARTED |
| [R17](TASK_CATALOG.md#r17) | Pilot usability and operating procedures | REQUIRED | M5 | Antigravity | NOT STARTED |
| [R18](TASK_CATALOG.md#r18) | Backup scheduling, retention and recovery monitoring | REQUIRED | M2 | Codex | NOT STARTED |
| [N01](TASK_CATALOG.md#n01) | Frame-level diagnostic review | RECOMMENDED | M5 | Antigravity | NOT STARTED |
| [N02](TASK_CATALOG.md#n02) | Simplify shared frontend contracts | RECOMMENDED | M5 | Antigravity | NOT STARTED |
| [N03](TASK_CATALOG.md#n03) | Optional avatar and adaptive rendering | RECOMMENDED | M5 | Antigravity | NOT STARTED |
| [N04](TASK_CATALOG.md#n04) | Longitudinal review with uncertainty | RECOMMENDED | M5 | Antigravity | NOT STARTED |
| [N05](TASK_CATALOG.md#n05) | Portable offline evidence verifier | RECOMMENDED | M5 | Research/clinical | NOT STARTED |

## Shared workflow

- Milestone M0 first: rebaseline against current HEAD and get implementation plan approved.
- Each agent uses a distinct branch/worktree. Do not edit the same working tree concurrently.
- Change a status only with actual code/test evidence; use `VERIFICATION_LOG.md`.
- Conditional native/EMG blockers stay unresolved until release scope is approved and applicable checks are satisfied, or unsupported claims are removed.
- Never commit patient recordings or secrets. Never merge to main or deploy without explicit acceptance.
