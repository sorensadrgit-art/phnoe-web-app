# KineLab PT — Complete Acceptance Catalog

All **44 additions** are quoted from section 4 of the uploaded audit. Treat this as a requirement inventory, **not** evidence that a feature has been implemented. Verify all findings against the current Git revision.

**Source:** [Full production-readiness audit](../audits/KineLab_PT_Production_Readiness_Report.md). See [Task Board](TASK_BOARD.md) for ownership and milestone, [Verification Log](VERIFICATION_LOG.md) for evidence, [Decision Register](DECISION_REGISTER.md) for scope decisions.

### B01

**Addition:** Real acquisition and permanent source provenance

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Live and backend paths fabricate motion. A camera preview must not imply measurement. **Files:** `LiveTrackerStudio.jsx`, `liveKinematics.js`, `t6_service.py`, report/export consumers; **new:** versioned pose/sensor adapter. [S04, S09; P01, P09]

**Exact testable acceptance criterion:**
A known prerecorded moving-body sequence produces time-aligned landmarks from the selected pinned model; covering/removing the subject changes validity and never falls back to animation. Source kind `camera/EMG/import/synthetic` is immutable and visible in every downstream output. Missing measured frames reject or produce an explicitly incomplete record. Synthetic data cannot enter a real-session namespace. Referenced TRC/model assets must exist and match hashes.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B02

**Addition:** One strict runtime measurement contract

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Live API accepts unsupported exercises, malformed vectors, NaN, negative timing and truthy string booleans. **Files:** `t6_server.py`, `t6_service.py`, `session_contract.py`, frontend serializers, all report/export readers; **new:** shared versioned schemas. [S08–S09; P11]

**Exact testable acceptance criterion:**
Reject duplicate JSON keys, nonfinite numbers, wrong types/dimensions, unsupported IDs/versions, invalid units, negative/nonmonotonic timestamps, duplicate sequence numbers and inconsistent summaries **before publication**. Error identifies field/reason and preserves recoverable draft. Native producer/consumer and live code round-trip identical typed fixtures. Standard JSON serialization forbids NaN. Unknown future schemas fail clearly.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B03

**Addition:** Incremental durable session recording

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Current data lives in a component ref until a bulk save that soon exceeds API size limits. **Files:** `LiveTrackerStudio.jsx`, `t6_server.py`, `t6_service.py`, `session_index.py`; **new:** recorder journal/chunk API. [S04, S08–S10; P13]

**Exact testable acceptance criterion:**
Persist bounded chunks continuously with stable session/set/chunk IDs and sequence ranges. UI receives a durable acknowledgement only after commit; a saved-through indicator covers only a contiguous prefix. Deliver chunks 1, 3, then 2: the prefix stays at 1 until 2 commits. At agreed maximum duration/rate, memory and queue sizes remain bounded and data exceeds 64 KiB without failure. Kill renderer/service at every tested boundary: all acknowledged chunks recover exactly; unacknowledged tails and sequence gaps are explicit. A larger bulk-request limit alone does not satisfy this.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B04

**Addition:** Atomic finalization and multi-file publication

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Session is labelled completed before telemetry/exports; native normalization publishes several files separately. **Files:** `t6_service.py`, `normalize_capture.py`, `capture_station.py`, `setup_project.py`, export/report writers. [S09, S17–S18; P12]

**Exact testable acceptance criterion:**
Use a durable transaction/generation journal and commit manifest. At every write/flush/rename/index boundary, exception, process-kill, disk-full and supported power-loss tests recover either the previous committed generation or the complete new one. Mixed/incomplete generations never show completed. Preserve originals and quarantine partial artifacts. Readers use committed generations only.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B05

**Addition:** Idempotency, concurrency and one authoritative writer

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Retries fail ambiguously; second-resolution IDs can collide; locks are process-local and launcher startup has a source-level race. **Files:** `t6_service.py`, `t6_launcher.py`, `session_index.py`, live client. [S09, S24; P10]

**Exact testable acceptance criterion:**
Client generates stable IDs before capture. Repeating an identical request after lost response returns the same receipt; same idempotency request/chunk key with different payload rejects as conflict. Concurrent chunk/session submissions produce exactly one committed result. Simultaneous launches yield one writer or explicit refusal. Mutations use transactions and revision checks; tests cover overlapping finalize/retry/backup/reindex.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B06

**Addition:** Immutable evidence and fail-closed prerequisite gates

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Reindex blesses changed bytes; file existence and incomplete manifests can imply passed outputs. **Files:** `session_index.py`, `run_pipeline.py`, `workflow_controller.py`, `export_motion.py`, `t6_service.motion_data`, passport/reports. [S10, S18, S21–S22; P14–P16, P24]

**Exact testable acceptance criterion:**
Preserve committed expected hashes and protect audit history against unauthorized modification; authorized changes create new revisions. Changed/missing upstream bytes invalidate dependent results and raise visible audit events; reindex cannot replace the baseline. API, CLI, GUI, resume and export share the same ordered prerequisite validator. Omitted/failed/reordered stages, arbitrary output files and stale quality evidence cannot yield passed/reportable. Explicit exploratory exports remain unverified and segregated.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B07

**Addition:** Correct index, schema migrations and durable audit history

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Run schema mismatch, stale rows, disabled FK enforcement and audit loss undermine provenance. **Files:** `session_index.py`, `backup_manager.py`, all mutating service actions; **new:** migration fixtures/audit schema. [S10, S12; P15–P16, P21]

**Exact testable acceptance criterion:**
Native stage lists index correctly. Reconciliation identifies absent/corrupt records rather than retaining valid state. Enforce relied-on foreign keys; transactional migrations have interruption/rollback and future-version rejection tests. Record actor, action, revision, inputs, outcome and timestamp for capture, edits, export, reports, deletion, restore, recovery and access-policy changes. Rebuild/restore preserves audit event identities; an index rebuild cannot substitute for lost audit evidence.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B08

**Addition:** Safe restore validation and containment

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Demonstrated unchecked content, outside-root replacement and destructive overwrite failure. **Files:** `backup_manager.py`, backup API/tests, restore UI. [S12; P17–P20]

**Exact testable acceptance criterion:**
Before touching live data, validate schema, session IDs, exact archive inventory, normalized contained paths, uniqueness, sizes and hashes; reject traversal/absolute paths, symlinks and resource-limit violations. Missing/unlisted/duplicate entries fail. Extract only to bounded staging. All demonstrated malicious/incomplete fixtures reject with **zero changes** to destination or sibling directories.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B09

**Addition:** Coherent backup and rollback-capable recovery

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Backup includes its own directory; DB snapshot/audit is not restored. In-process API writes are serialized, but asynchronous native workers/other writers are not bound to one snapshot generation. **Files:** `backup_manager.py`, `session_index.py`, service, `ReportStudio.jsx`, runbook. [S12; P20–P21]

**Exact testable acceptance criterion:**
Exclude backup/staging trees. Snapshot one committed generation including audit history and verify after creation. Preview conflicts and chosen resolution; create a safety recovery point before cutover. Inject failure at every cutover: originals remain or roll back. A clean-machine restore reproduces identities, counts, source digests, revisions and audit events. Demonstrate an independent-copy recovery drill against approved RPO/RTO.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B10

**Addition:** Subject/operator identity and asynchronous UI isolation

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Generic patient default and late responses can misattribute or display another session's evidence. **Files:** `LiveSetSummaryModal.jsx`, `LiveTrackerStudio.jsx`, `UnifiedApp.jsx`, `ReportStudio.jsx`, schemas/reports/audit. [S07, S09, S13–S14]

**Exact testable acceptance criterion:**
Human capture requires explicit pseudonymous subject/operator and laterality/protocol confirmation, locked to the set. No silent default patient. Corrections create audited revisions. Delayed A responses after selecting B cannot change B's detail, passport, report or export target. Abort/version requests and check returned identity; automated mounted-UI tests prove rapid-switch/poll/reconnect safety.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B11

**Addition:** Valid geometry, confidence and occlusion rejection

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Aspect ratio, zero-length limbs, missing visibility and image-to-metre conversion are invalid. **Files:** `liveKinematics.js`, pose adapter, `LiveTrackerStudio.jsx`, HUD/export. [S04–S05; P02–P04]

**Exact testable acceptance criterion:**
Define image/pixel/metric coordinate spaces, camera crop, mirror and left/right conventions. Correct aspect handling; reject degenerate/nonfinite/out-of-plane/ambiguous-person/occluded/stale observations. Image-normalized coordinates cannot be labelled measured metres. Nondegenerate pixel-coordinate fixture angles match analytical references within 0.1° and retain the same result across equivalent aspect/crop/mirror representations with correct anatomical side; all known invalid fixtures produce invalidity, not zero/180°/100% defaults. Calibrate thresholds against reference error and preserve per-joint reasons/uncertainty.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B12

**Addition:** Correct exercise semantics and immutable set lifecycle

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Missing data counts as a rep; extension/balance/zero values/finish/configuration have reproducible defects. **Files:** `exerciseStateMachine.js`, `LiveTrackerStudio.jsx`, `LiveSetSummaryModal.jsx`. [S04, S06, S14; P04–P08]

**Exact testable acceptance criterion:**
Each exercise has validated active side, units, phase/direction and timing rules. Seated extension fixture counts correctly; missing data cannot complete reps; gaps/pause add no valid hold time; zero remains zero. Finish stops acquisition and is idempotent. Target/exercise changes create a new versioned set or are locked during capture. Displayed/effective targets match, balance uses seconds, and reset cannot erase unacknowledged recoverable work silently.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B13

**Addition:** Run-bound calibration and synchronization

**Priority:** BLOCKER

**Status:** NOT STARTED
**Scope condition:** **if native research is supported**
**Finding, motivation and affected implementation:**
Shared logs can supply stale residuals; board dimensions/lens conventions are inconsistent. **Files:** `pipeline_quality.py`, `sync_evidence.py`, `setup_project.py`, normalization/capture adapters. [S17–S20]

**Exact testable acceptance criterion:**
Structured measurements bind run/config/model/calibration/raw/normalized/mapping hashes, camera order, units and actual board dimensions/uncertainty. Old log entries cannot pass a new run. Calibration invalidates after incompatible geometry changes. Nonzero-distortion fixtures and held-out physical checks validate scale/reprojection. Known positive/negative offsets and interval boundaries match actual synchronized content; drift beyond approved budget rejects or invokes a validated recorded correction.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B14

**Addition:** Complete timelines and physically possible 3D

**Priority:** BLOCKER

**Status:** NOT STARTED
**Scope condition:** **if native research is supported**
**Finding, motivation and affected implementation:**
Sparse frames and behind-camera coincident skeleton pass. **Files:** `pipeline_quality.py`, `export_motion.py`, stage manifests, normalization maps. [S19, S21; P22–P23]

**Exact testable acceptance criterion:**
Use expected source interval/grid, including missing and duplicate frames. Account separately for observed/rejected/dropped/trimmed/interpolated samples. Frames 0 and 1000 cannot mean uninterrupted coverage. Reject negative camera depth, collapsed limbs and inadequately conditioned triangulation; enforce documented anatomical/temporal checks. Preserve source frame IDs and gap masks through filtering/export. Reprojection alone never establishes clinical accuracy.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B15

**Addition:** Model fitting, filtering and IK validity

**Priority:** BLOCKER

**Status:** NOT STARTED
**Scope condition:** **if claimed**
**Finding, motivation and affected implementation:**
Several native stages receive unconditional quality success; inherited body defaults are not measured patient inputs. **Files:** `run_pipeline.py`, `setup_project.py`, `export_motion.py`, processing UI. [S18, S21–S22]

**Exact testable acceptance criterion:**
Select/record approved subject parameters, model hash, scaling setup and constraints. Missing inputs or fallback height/mass remain explicit and block unsupported clinical claims. Preserve observed versus inferred markers. Validate filter peak/timing distortion and IK/scaling residuals against approved thresholds. Retain exact setup/output evidence. Either complete the guided IK flow and physical tests or ship clearly labelled marker-only output.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B16

**Addition:** Truthful, reproducible reports and exports

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Corrupt/no evidence becomes clinical-looking success; invented identity/model/rep values and mismatched totals exist. **Files:** `report_builder.py`, `export_motion.py`, `ReportStudio.jsx`, motion/report API. [S13, S21, S25; P21, P25]

**Exact testable acceptance criterion:**
Malformed evidence blocks a valid report with an actionable integrity error. No-data output says “No valid measurements”; no clean-form, fake rep, default symmetry or unsupported model claim. Tables/charts/totals reconcile to the same immutable generation and include all reps or explicit pagination. Each revision records actual source/model/calibration/units/gaps/software; reruns create a new linked revision, not silent overwrite.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B17

**Addition:** Reference validation for every clinical measurement claim

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
No measured accuracy result exists; software tests do not establish physical validity. **Affected:** complete measurement path; **new:** consented reference dataset, protocol, analysis harness, validation dossier. [S01; section 1.3; X01–X03]

**Exact testable acceptance criterion:**
Before clinical reliance, freeze pipeline and meet approved per-endpoint targets on held-out participants and supported hardware/conditions. Use standardized blinded repeat goniometry for defined static ROM; a suitable synchronized dynamic reference for dynamic/3D claims. Quantify reference uncertainty, bias, MAE, tails, limits of agreement, coverage, repeatability and subgroup failures. Independent participants/trials, not correlated frames alone, determine study power. Failed endpoints are restricted or redesigned.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B18

**Addition:** Live freshness, bounded performance and safe interruption

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Stale/missing data advances state; no end-to-end latency proof; launcher busy-spins. **Files:** live loop/worker/media lifecycle, `t6_launcher.py`, service polling/indexing, recorder. [S04, S07, S24; P07, V14]

**Exact testable acceptance criterion:**
Measure section 1.3 targets on supported devices for ≥30 minutes and declared maximum session length. Bound capture queues and storage acknowledgement time; prioritize measurement/persistence over avatar rendering. Device loss, backgrounding, sleep, worker failure or thermal slowdown yields explicit invalid/interrupted state. No silent frame loss. Fix idle loop and verify proposed idle CPU <2% of one core; benchmark passport indexing during recording.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B19

**Addition:** Data protection before human recording

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Local bearer is useful but not a complete clinical privacy/accountability policy; raw video, exports and ZIPs are sensitive. **Files:** service/launcher/storage/backup/logging, setup/export UI; **new:** deployment-specific access/consent/retention policy. [S07–S09, S12, S24; X07–X08]

**Exact testable acceptance criterion:**
Approve single-operator versus multi-user threat model. Verify OS file ACLs, workstation access/inactivity behavior, secret handling, export access and encryption/recovery-key policy appropriate to deployment. An unauthorized non-admin OS identity must not read recordings, backups or instance tokens; unauthorized application actors must not view/export outside their permitted scope. Persist study/clinical authorization references; implement retention/deletion with audit and backup policy. Inject sentinel identifiers/secrets into failure scenarios and verify they are absent from exported logs/diagnostics. Multi-user scope additionally requires authenticated actors and patient-level authorization tests. Do not infer legal compliance from localhost or disclaimers.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B20

**Addition:** Reproducible supported release and failure gates

**Priority:** BLOCKER

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Build/package passes coexist with missing scripts/modules/assets, hardcoded paths and failed full tests. **Files:** `tools/build_offline_distribution.py`, model/environment manifests, launcher, package scripts, tests; **new:** CI/release workflow. [S02–S03, S24, S27, S30; V08–V15]

**Exact testable acceptance criterion:**
On a clean supported Windows machine with networking disabled, provision all runtimes/models/FFmpeg and run setup→capture→commit→review→export→restore. Package required modules including runner/sync launcher, bootstrap data directory safely, and remove workstation-specific paths. Required unit/integration/fault/UI tests, lint and type checks pass with no safety-path skips. Protect release branch/checks; bind package/status to exact tested commit and hashes.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### B21

**Addition:** Measured muscle acquisition and synchronization

**Priority:** BLOCKER

**Status:** NOT STARTED
**Scope condition:** **if muscle tracking is in first release**
**Finding, motivation and affected implementation:**
Current application has no muscle measurement. **Affected:** **new** sensor adapters, channels, clock/quality schemas, setup/live/review UI, validation and privacy workflows; existing recorder/report contracts. [section 6.2; X04]

**Exact testable acceptance criterion:**
Choose muscles, hardware, sampling and normalization protocol. Record channel→muscle/side mapping, electrode setup, raw signal, filters, timestamps, clock drift, quality and disconnects. Validate synchronized acquisition and timing against reference; channel loss/saturation/artifact cannot become valid activation. Claims distinguish electrical activity, inferred activation and force. If deferred, remove muscle-measurement claims and label any anatomical visualization educational.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R01

**Addition:** Protected persistent data root and upgrade preservation

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Sessions/index currently use installation-relative `ROOT/projects`; generated instructions claim a different location. **Files:** `t6_service.py`, launcher/configuration, installer. [S09, S24, S27]

**Exact testable acceptance criterion:**
Choose a configurable protected data root separate from replaceable program files; check free space/permissions before capture. Upgrade, reinstall and rollback fixtures preserve every committed session/audit hash. Relocation is explicit, verified and recoverable. Storage warning thresholds account for maximum supported recording and backup size.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R02

**Addition:** Recoverable jobs and safe shutdown

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Jobs/camera state is in memory; HTTP shutdown does not itself establish finalized capture. **Files:** service `close`/webcam polling, `t6_server.py`, workflow/recovery, recorder. [S08–S09, S22]

**Exact testable acceptance criterion:**
Shutdown quiesces or marks jobs interrupted, durably commits pending records before acknowledging them, preserves prior acknowledged records and marks any remaining tail uncommitted. Persist job identity and verify owned camera/process resources stop or enter the declared recoverable state. Restart reconciles committed sequences, partial media and owned subprocesses. Resume never trusts unverified artifacts. Test close, OS sleep, crash, cancel and reconnect during each stage without manual manifest deletion.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R03

**Addition:** Guided subject, protocol and calibration setup

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Live defaults start without explicit clinical context; checkbox acknowledgement is not calibration evidence. **Files:** `LiveTrackerStudio.jsx`, `GuidedCaptureWizard.jsx`, session schemas. [S04, S25]

**Exact testable acceptance criterion:**
Start is disabled until selected protocol's identity, side, device/model, framing and calibration requirements pass. Operator-reported checks are distinguished from measured checks and persisted with identity/time. Camera movement/settings invalidate incompatible calibration. Retake/reconnect instructions identify the exact unmet condition.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R04

**Addition:** Complete session review, history and compatible comparisons

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Filters are ineffective; comparison compatibility is weak; analysis can display stale selection. **Files:** `ReportStudio.jsx`, `UnifiedApp.jsx`, `MotionApp.jsx`, `session_index.py`. [S07, S10, S23, S25]

**Exact testable acceptance criterion:**
Search/filter changes the visible set. Every review binds visible subject/session/revision and shows valid/rejected durations, gap timeline, source and review state. Comparison checks subject, task, side, units, model/calibration and protocol; incompatible pairs reject or show an explicitly approved research comparison. Missing values are never zero or improvement.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R05

**Addition:** Reliable offline operation and explicit sync policy

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Local service exists, but offline model availability/reconnect recovery is not proven; no remote-sync engine exists. **Files:** model cache, deployment modes, recorder/service; **new** outbox/sync only if selected. [S03, S29]

**Exact testable acceptance criterion:**
With egress blocked, all promised local features load and complete. Service disconnect queues only within declared recoverable limits and displays unsaved status. If cloud/multi-device sync is selected, test encrypted authenticated transfer, idempotent sequence reconciliation, conflicts and merge revisions; no last-write-wins overwrite of clinical measurements. If local-only, remove sync implications and document verified transfer/backup instead.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R06

**Addition:** Honest research gait/squat analysis

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Candidate events and reference comparison do not establish all claimed gait/phase measures. **Files:** `gait_events.py`, `squat_events.py`, research UI/docs. [S28]

**Exact testable acceptance criterion:**
Reject ambiguous-person/low-confidence/occluded samples consistently. Validate each claimed event and phase boundary against source-bound independent labels; report false/missed/incomplete events separately. Unsupported cadence/metric stride length remains absent. Test-only samples retain that classification in every report/export.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R07

**Addition:** Model-specific confidence and coordinate adapters

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Current native score bounds differ from research adapters; different model coordinates can silently change meaning. **Files:** native pose validator, event adapters, geometry schemas. [S05, S18, S28; V18]

**Exact testable acceptance criterion:**
Freeze raw score range/meaning and coordinate conventions per model/version; retain raw and transformed confidence separately. Same sample receives the same validity decision across live/native/events/export. Fixtures cover >1 scores, nonfinite values, occlusion, person switches and coordinate transforms. Model changes require explicit migration/revalidation, not silent clamping.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R08

**Addition:** Complete interoperable evidence export

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Live v1 and native v2 provenance differ; output existence does not guarantee usable clinical transfer. **Files:** `export_motion.py`, `report_builder.py`, motion readers; **new** evidence-bundle manifest. [S09, S13, S21, S23]

**Exact testable acceptance criterion:**
Export a selected immutable revision with schema/version, units, coordinate definitions, quality/gaps, model/calibration references, audit lineage and de-identification options. Independent validator detects altered/missing files. Round-trip JSON/CSV/TRC/MOT only for actually supported schemas; reject incompatible import with precise reason. Never invent unavailable source formats.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R09

**Addition:** Accessible clinical workflows

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Canvas information, modal focus and state semantics are incomplete. **Files:** HUD, summary, charts, all primary controls/CSS. [S14, S23, S26; X09]

**Exact testable acceptance criterion:**
Complete setup→record→pause→finish→review→save/export using keyboard and tested screen reader. Dialog name/role/focus trap/Escape/return focus work; toggles expose state; canvas/chart values have DOM/table equivalents; live announcements are meaningful and rate-limited. Audit supported surfaces against WCAG 2.2 AA, including contrast, focus, errors, status and reflow.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R10

**Addition:** Responsive layout and readable hierarchy

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Fixed avatar inset, tiny labels and inline summary grid risk obstructing clinical controls. **Files:** live/HUD/modal/`unified.css`. [S14, S26]

**Exact testable acceptance criterion:**
At 320/390/768/1024/1440 CSS-pixel widths, portrait/landscape and 200% zoom, identity/validity/save state and critical controls remain usable without clipping. Meet applicable 400%-zoom/reflow criterion too. Overlay transforms stay aligned for every supported aspect/crop/mirror mode. Use specification in section 5, verified by rendered tests.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R11

**Addition:** Complete error, loading and empty states

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Suppressed errors/fixed ONLINE labels and reassuring empties conceal failures. **Files:** boot, `UnifiedApp.jsx`, live/model/camera flow, report/comparison/backup screens. [S07, S14, S25]

**Exact testable acceptance criterion:**
Inject permission denial, occupied/disconnected camera, model failure, API timeout, disk-full, corrupt session, missing asset, empty result and failed export. Each gives accurate reason, retry/recovery action and retained draft where possible. Failed polls show data age/offline status. No failed state displays Saved, Verified, clean form or fabricated values.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R12

**Addition:** Performance and operational diagnostics

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Repeated passport calls rehash/reprobe all sessions under a shared lock; long native inputs can be costly. **Files:** service/index polling, normalization metadata reads, worker/renderer. [S07, S10, S18]

**Exact testable acceptance criterion:**
Approve numeric recorder-memory, queue-length, disk-reserve and p95/p99 durable-acknowledgement budgets before testing. Benchmark declared maximum session duration/library size on minimum supported hardware; capture+index+backup must remain within every approved budget. Do not block durable writes behind full reindex. Diagnostics expose capture/inference/render/persist rates, drops, queue depth, storage capacity, model version and useful redacted errors.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R13

**Addition:** Dependency, model and release provenance

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Pinned inventory does not prove reproducible or secure distribution; weights/licenses can differ from packages. **Files:** requirements/npm lockfiles, model manifest, builder; **new** SBOM/license/security evidence. [S02–S03, S27]

**Exact testable acceptance criterion:**
Ship exact runtime/model hashes and licenses; verify weight availability offline, scan dependencies/models with a documented remediation process, and record results against commit. Replace workstation paths. No unresolved release-blocking vulnerability under the approved threat model; updates trigger required regression and measurement checks. Do not infer network transmission from a dependency name alone.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R14

**Addition:** One supported API/launcher contract

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Retained legacy launcher uses `/api`, `#key` and custom header; current UI uses `/api/v1`, `#access` and Bearer. **Files:** old/current launchers/services and docs. [S07–S08, S24]

**Exact testable acceptance criterion:**
Every advertised launcher starts the matching frontend/API and selected session. Retire, redirect or clearly version legacy paths. Smoke tests authenticate, select session and exercise advertised operations through every supported entry point. Missing prerequisites produce repair guidance rather than silent native failure.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R15

**Addition:** Evidence-derived documentation and status badges

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
README/runbook/UI claims exceed current implementation; “15 focused checks passed” is static copy. **Files:** README, release/build/security/backup docs, passport/footer/build metadata. [S01, S07, S11–S12, S27, S30]

**Exact testable acceptance criterion:**
Generate build/test status from exact release evidence. Correct six-role names, marker-only guided export, visual synchronization, actual data path and restore behavior. Run every documented command on a clean supported installation. Display operator observations, software verification, physical accuracy and clinical approval as distinct statuses.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R16

**Addition:** Model/protocol change control and regression corpus

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Clinical error bounds depend on camera/model/configuration and patient scope. **Affected:** validation harness, protocol catalog, package update flow. [B11–B17]

**Exact testable acceptance criterion:**
Version approved protocols and reference fixtures. Changes to geometry/model/filter/camera/scaling thresholds automatically trigger relevant accuracy/coverage/latency tests. Include sparse time, wrong side, nonzero distortion, camera movement, low light, occlusion, multiple people, rapid motion and device disconnect. Keep appropriately consented private data outside public source control.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R17

**Addition:** Pilot usability and operating procedures

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Current flow requires expert file selection/recovery and contains misleading reassurance. **Affected:** setup/live/review/recovery UX, training and support documentation. [S14, S23, S25]

**Exact testable acceptance criterion:**
Representative operators complete prespecified setup, invalid-tracking response, identity check, save/recovery and export tasks on supported devices. Record critical task errors and remediation. No participant must infer record durability or tracking validity from color/animation alone. Define stop/pain, incident and support procedures for the chosen pilot setting.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### R18

**Addition:** Backup scheduling, retention and recovery monitoring

**Priority:** REQUIRED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Manual ZIP creation provides no scheduling/monitoring evidence against future approved recovery objectives. **Files:** backup service/UI/configuration, protected storage. [S12]

**Exact testable acceptance criterion:**
Implement approved frequency/destination/retention; show last verified recovery point and failed/missed jobs. Periodic restore drills prove agreed RPO/RTO and key recovery. Pruning cannot remove the last required verified recovery point, and backups never recursively include backups. Data deletion/retention policy explicitly covers independent copies.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### N01

**Addition:** Frame-level diagnostic review

**Priority:** RECOMMENDED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Helps explain native rejection without editing JSON. **Files:** 3D/synchronized review, quality display.

**Exact testable acceptance criterion:**
Selecting a rejected frame shows source video frames, camera support, residuals, depth/geometry, missingness and observed/inferred legend, all matching stored evidence. No diagnostic graphic is labelled a validated clinical measurement without validation.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### N02

**Addition:** Simplify shared frontend contracts

**Priority:** RECOMMENDED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Repeated navigation/state/style code increases divergence. **Files:** `unifiedLogic.js`, `unifiedModel.js`, inline modal/live styles.

**Exact testable acceptance criterion:**
After usage review, use one protocol/units/navigation contract and shared status components; remove only demonstrably unused paths. Tests and visual comparisons prove intended behavior unchanged. Add strict TypeScript incrementally where useful; runtime schemas remain mandatory.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### N03

**Addition:** Optional avatar and adaptive rendering

**Priority:** RECOMMENDED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
3D should not consume resources needed for measurement or obscure limbs. **Files:** `LiveDigitalTwin.jsx`, live layouts, bundle splitting.

**Exact testable acceptance criterion:**
Avatar is optional/collapsible, stops rendering when hidden, and degrades before capture/recording. Document measured CPU/GPU/memory and latency improvement on target hardware; all source/quality labels remain visible.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### N04

**Addition:** Longitudinal review with uncertainty

**Priority:** RECOMMENDED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Useful after validated repeatability and compatibility exist. **Files:** session history/comparison, reports.

**Exact testable acceptance criterion:**
Trend displays only compatible endpoints or clearly disclosed differences; shows uncertainty and measurement availability. A missing or protocol-changed measurement cannot appear as recovery/improvement. Claims of meaningful change require approved repeatability thresholds.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.

### N05

**Addition:** Portable offline evidence verifier

**Priority:** RECOMMENDED

**Status:** NOT STARTED

**Finding, motivation and affected implementation:**
Independent review improves confidence in exported/restored records. **New component:** read-only verifier and schema documentation.

**Exact testable acceptance criterion:**
On a separate machine, verify manifest completeness, schema, digests, sequence accounting and lineage without opening the main application. Altered, omitted and reordered evidence fails with clear reasons. Physical correctness remains a separate validation question.

**Implementation / affected files to verify:** derive from finding and current code; plan with failing tests and a reversible patch before executing.
**Acceptance evidence:** PENDING; record actual commands, fixture outcomes, durability tests and reviewer sign-off in `VERIFICATION_LOG.md`.
**Rollback:** Preserve source, release and saved session compatibility; write specific rollback before modifying code.
