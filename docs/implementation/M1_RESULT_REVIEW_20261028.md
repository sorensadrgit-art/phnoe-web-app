# M1 containment Tasks 1–3 — result review

**2026-10-28, America/New_York. Status: verification performed; owner result ACCEPTED WITH LIMITATIONS as a bounded M1 Tasks 1–3 safety-containment result only.**

The approved containment remains in place: live measurement persistence is refused, legacy live evidence cannot become a valid report or motion response, and restore overwrite is unavailable. Task 3 added independent regression coverage, corrected gaps found by that coverage, ran the complete suites, exercised an extracted package on isolated localhost fixtures, and verified the rebuilt archive. Browser download delivery remains unresolved. This is not completion of the full M1 milestone or permission to use the application with participants.

- `SOFTWARE_BUILD_VERIFIED`: the two builds and the software cases specified below only.
- `BLOCKED_ON_PHYSICAL_EVIDENCE`.
- `CLINICAL_VALIDATION: UNVERIFIED`.
- Branch: `feat/kinelab-m1-containment-20261028`; HEAD remains `7efd108caf4244d10672014a9cb0f7afceb253ff`. All changes remain uncommitted and unpushed.

## Scope and preservation

This continued the owner's approved [Tasks 1–3](M1_SCOPED_PLAN_20261028.md) and [desktop resume](CODEX_DESKTOP_RESUME_20261028.md). No reset, stash, commit, push, merge, deployment, live-app access, patient-data access, or second agent was used. The original shortcut and original Windows application were not accessed.

All 23 files that were dirty or untracked at resume were copied byte-for-byte to `dist/m1-task3-20261028/before/`, with `before-hashes.json` and `before.patch`. The preceding distribution was retained in `before-distribution/` and `before-distribution.zip`. Existing changes were inspected and continued in place; these copies are local rollback evidence, not a publication artifact. The historical audit is unchanged.

No runtime dependencies or lockfiles changed. `viewer/package.json` only adds the focused React presentation test to the declared test command and a terminal newline. Test fixtures that previously referenced the forbidden original installation or existing project recordings now use this checkout's scientific environment and generated synthetic inputs. No scientific model or Blender binary was installed.

## Changes confirmed by independent regression cases

1. Corrupt, incomplete or relabelled legacy metadata, a legacy live schema, and retained live telemetry all remain unverified. The original provenance fields and files are retained. List, detail, passport, comparison, motion, report generation, archived downloads and UI badges honor that state. A test-only marker cannot erase it. This is containment; native immutable expected digests are still absent.
2. Restore preflight rejects Windows component case aliases, file/directory collisions, forbidden Windows characters, and ZIP reparse attributes as well as the original unsafe-path/inventory cases. The service rejects actual backup-directory junctions, including junctions to a sibling under the same parent.
3. Publication rollback checks the identity of a directory it created before removing it. Injected competing writers and replaced destinations retain their own files. This does not implement a cross-process transaction or crash-recovery protocol.
4. Tests that expected successful unsafe overwrite or fabricated live output now assert the explicitly approved refusal. Positive nonconflicting single/multiple-session restore, existing audit preservation and native/synthetic workflows remain tested. The suite was not made green by deleting all successful restore coverage.
5. Final screenshot review found an old restore-help promise of a conflict preview. That copy was corrected to state nonconflicting restore and no database/audit-history restoration. No backend behavior changed in this final copy correction. Frontend tests, both builds, package verification and a fresh mounted-package browser/API check were repeated afterward; the Python suite already covers the unchanged Python source.

## Reproducible verification

Commands were run from this isolated checkout. Evidence files below are under `dist/m1-task3-20261028/` unless noted; that directory is ignored. [M1_EVIDENCE_20261028.json](M1_EVIDENCE_20261028.json) records hashes, source state and results so ignored logs cannot silently be substituted.

| Check | Result | Evidence / limit |
|---|---|---|
| `.venv/Scripts/python.exe -X utf8 -B -m unittest discover -s tests -v` | **258 run; 256 passed; 2 skipped; 0 failures; 0 errors** | `python-verified-full.log`; 60.938 s; Python 3.13.16, OpenSim 4.6-2026-06-22-85aaf64, Pose2Sim 0.10.49 imported |
| Original M1 containment and backup suites | **19 + 3 passed** | `initial-containment.log`, `initial-backup.log`; also included in final full run |
| Independent acceptance suite | **16 passed** | `acceptance-races-GREEN.log`; includes actual Windows junctions, faults, competing destinations and authenticated HTTP |
| `npm --prefix viewer test` | **50 passed; 0 failed/skipped** | `frontend-FINAL.log`; includes four actual React SSR presentation cases |
| `node --test viewer/src/gaitReviewLogic.test.cjs` | **8 passed** | `gait-review.log`; still a separate command, not added silently to the declared suite |
| `npm --prefix viewer run build:cloud` | **PASS**, 609 modules, 3.54 s | `build-cloud-FINAL.log`; CloudDemoApp 943.15 kB / gzip 257.99 kB; retained separately before desktop build |
| `npm --prefix viewer run build` | **PASS**, 609 modules, 3.45 s | `build-desktop-FINAL.log`; LiveTrackerStudio 938.72 kB / gzip 256.69 kB |
| `python tools/build_offline_distribution.py` using the verified venv | **Archive generated and independently checked** | `package-build-FINAL.log`, `package-check.json`; not a clean-install pass |
| Extracted-package authenticated API | **12 checks passed**, repeated on final package | `packaged-api-final-check.json`; 401 without bearer, 400 invalid Host, 403 invalid Origin, nine expected 409 refusals; 10 original fixture files unchanged |
| Diff, source preservation, package/private-file inventory and cleanup | **PASS for enumerated checks** | `final-checks.json` and durable receipt; no assurance of a completed security audit |

Both builds retain Vite's greater-than-500-kB chunk warning. No performance threshold is inferred from a successful build.

**Skips and warnings:** the two real-Blender subprocess tests skipped because the executable is absent in this isolated checkout: `test_real_blender_accepts_v2_and_rejects_bad_json_before_writing` and `test_real_blender_exports_timestamps_and_refuses_existing_destinations`. No fallback into the original installation was allowed. The final Python run still emitted two ignored Tkinter `Variable.__del__` errors (`main thread is not in main loop`) and a Tcl interpreter deallocation warning. The earlier socket failure did not recur; it is not declared fixed.

**RED → GREEN accounting:** after correcting two new test-harness mistakes, the independent 14-test run had 11 failing assertions (`acceptance-RED-corrected.log`). Fixes brought it to 14 passing. Two additional race/junction tests then failed in a 16-test run and passed after the identity/junction fixes. The corrected focused frontend run had 13 tests, 10 passing and 3 failing; the final declared suite has 50 passing. Earlier full runs exposed obsolete overwrite assertions and one incorrect exception expectation in the revised test; those were corrected while retaining positive restore checks. `python-verified-full.log` is the final result, not an earlier failed run. The pre-resume `dist/m1-containment-RED*.log` files are retained as historical evidence, not represented as fresh baseline executions.

One repeat invocation of the task-local package extraction verifier stopped at its deliberate existing-output assertion. It overwrote nothing. The original successful verification and the subsequent non-extracting final integrity check establish the archive result; the rejected repeat is not counted as a product test failure or a second successful extraction.

## Six M0 counterexamples

The original M0 demonstration harness was not relabelled as a green product test. The following secure expectations were exercised in the final suite:

| Counterexample | Secure regression and result | Remaining boundary |
|---|---|---|
| P09: empty live frames produce invented motion | `test_live_write_unverified_rejects_before_files`: refusal before session creation | No measured acquisition implementation |
| P11: malformed/NaN/string-validity data accepted | `test_forged_source_cannot_enable_live_write`, HTTP and independent index-preservation cases: refusal | A strict shared native/live contract is still required |
| P14: altered motion becomes trusted after reindex | `test_modified_legacy_motion_remains_unavailable_after_reindex`: legacy evidence stays blocked | **Native expected-digest immutability remains unresolved**; this does not repair the general reindex defect |
| P17: unlisted archive member published | `test_unlisted_member_rejected_with_no_destination_change`: rejection with unchanged destination snapshot | Full backup-generation coherence deferred |
| P18: manifest `../m0-sibling` escapes root | `test_traversal_session_rejected_without_touching_sibling`: rejection; sibling retained | Not a hostile local-process security proof |
| P19: missing staged source destroys overwrite target | `test_absent_required_file_rejected_without_deleting_existing` plus overwrite refusal: originals preserved | Destructive restore remains disabled |

## Isolated browser and packaged-service evidence

The browser used dedicated `agent-browser` sessions, headless Chrome and a 127.0.0.1 domain allowlist. The desktop server imported the **extracted package**, with generated projects, an empty sample root and a separate local state directory. The cloud page served the retained cloud build. Owned ports were 53544/53545 for the full interaction pass and 61255/61256 for the final copy/build/package recheck. Browser media APIs were replaced before app execution with a synthetic permission-denial fixture; no camera device or person was accessed. This validates refusal/presentation, not a real camera preview.

| Flow | Observation |
|---|---|
| Camera preview and denial | Explicit unavailable joint/rep/muscle values, zero measurement canvases, Finish disabled. Denial did not switch into synthetic mode. Switching back from synthetic again removed both canvases and disabled Finish. |
| Synthetic selection | Feed toggle worked with focus + Enter; two canvases rendered, synthetic warning stayed visible, and Finish became available. No live-save POST was issued. |
| Synthetic summary | Finish and Close worked with keyboard activation. Summary says synthetic/not measured; no patient input or Save button. Generated JSON has `source_type=SYNTHETIC_TEST_ONLY` and `clinical_accuracy_verified=false`. |
| Legacy/corrupt inventory | Both synthetic legacy fixtures remained listed with UNVERIFIED status. Generate and all archived download buttons were disabled. Direct stale-client requests also received 409. |
| Restore | Keyboard submission: broken ZIP → 409 `BACKUP_CORRUPT`; valid nonconflicting archive → 200 and visible restored session; repeat → 409 `RESTORE_CONFLICT`. Every observed UI POST sent `overwrite:false`. Confirmation text was recorded; only this fixture's confirmations were auto-accepted. |
| Cloud demonstration | Explicit synthetic demo, two canvases, Finish/summary usable, zero camera calls, zero API requests, all observed resources from its own local origin. No cloud backend or deployment was used. |
| Console/network | No uncaught page errors. Only two expected camera-denial warnings persisted in the browser console across navigation. Desktop POST failures were the intentional restore refusals. |
| Cleanup | Dedicated browser closed; both owned servers stopped; ephemeral token/init files removed; owned ports checked closed. Synthetic evidence remains only in the ignored task directory. |

Receipts: `desktop-browser-receipt.json`, `cloud-browser-receipt.json`, `packaged-api-check.json`. Screenshots: `desktop-camera-preview.png`, `desktop-synthetic.png`, `desktop-restore-invalid.png`, `desktop-legacy-report-refusal.png`, `cloud-synthetic.png`, `cloud-synthetic-summary.png`. Rendered screenshots were inspected. The fixture scripts are retained locally for reproduction.

Final-package receipts: `desktop-final-browser-receipt.json`, `cloud-final-browser-receipt.json`, `packaged-api-final-check.json`, plus `desktop-final-restore.png`. The corrected restore copy is mounted, the invalid preview promise is absent, unverified report actions remain disabled, keyboard nonconflicting restore succeeds, and the final cloud build remains local-only with no camera/API calls. All four owned ports and both browser sessions were closed.

**Unresolved browser finding:** desktop and cloud `agent-browser download` attempts reported **“Download was canceled”**, with relative and absolute destinations. A temporary browser-only delayed-revocation experiment also canceled and was reverted. Capturing the generated Blob proved the synthetic JSON labels, not delivery of a downloaded file. No application change was made on an unproven diagnosis. Browser download delivery needs a separate focused reproduction/fix or an explicit accepted limitation before claiming the complete export flow works.

**Accessibility boundary:** changed controls received direct focus and Enter activation. This was not a complete Tab-order, screen-reader, focus-trap, contrast, reflow or reduced-motion assessment. The summary has no semantic dialog role. A camera-denial notice also remains visible after selecting synthetic mode. These observations and broader status/copy issues remain open under R09–R11/R15; they were not expanded into a UI redesign.

## Package and release boundary

Archive: `dist/KineLabPT-v1.0.0-windows-x64.zip`.

SHA-256: `86d4914604011b357f356c3ae5cb41db887a286e69991a4b6fe31858cf50a182`.

The 751,419-byte ZIP has exactly 55 members: 54 manifest-listed files plus the manifest. All listed sizes, SHA-256 digests, CRCs, total 1,994,539 uncompressed file bytes and current `app/` source bytes matched. The inventory contains no projects/session data, databases, recordings, `.env`, private keys, virtual environment or dependency cache. The preceding tested package is retained locally as `pre-copy-review-package.zip` with its original receipt.

**Release remains blocked:** `app/run_pipeline.py` and `app/launch_sync_review.py` are absent; Python/scientific runtime provisioning, model weights/licences and FFmpeg provisioning are not a verified offline bundle. A clean supported Windows installation and native launcher lifecycle were not rerun in this Task 3 fixture. The server was mounted explicitly with an existing verified environment and generated projects directory. M0's first-launch missing-directory failure, idle-CPU finding and stale instance-state finding remain open and were not declared fixed. A manifest field asserting `SOFTWARE_BUILD_VERIFIED` is not a test-linked release gate or clinical evidence.

## All remaining BLOCKER items

All 21 BLOCKER catalog entries remain unaccepted; containment only partially addresses six. Exact broader criteria remain in [TASK_CATALOG.md](TASK_CATALOG.md).

| ID | Remaining acceptance gap |
|---|---|
| B01 | Real camera frame-to-pose inference and permanent source provenance; current live persistence stays disabled. |
| B02 | One strict versioned runtime contract across every producer/consumer, including invalid types, nonfinite values, sequence and summary consistency. |
| B03 | Incremental durable recording and acknowledged saved-through receipts under restart, disk-full and lost acknowledgments. |
| B04 | Atomic finalization and multi-file committed generations. |
| B05 | Stable operation IDs, idempotent retries, concurrency control and one authoritative writer. |
| B06 | Immutable committed expected digests, quarantine on mutation and complete prerequisite gates for native evidence. |
| B07 | Correct index, reversible schema migration and durable audit history; reindex is not an immutable evidence baseline. |
| B08 | Full restore acceptance, broader supported-platform/failure matrix and owner result acceptance; current support is bounded nonconflicting restore only. |
| B09 | Coherent data/index/audit snapshot and full recovery; current restore does not restore the archived database. Process-death, power-loss, disk-full, reindex failure and full recovery drills remain outside the proven publication cases. |
| B10 | Subject/operator identity and asynchronous selection isolation. Removing synthetic patient persistence does not complete identity management. |
| B11 | Valid geometry, confidence/occlusion rejection and calibrated coordinate semantics. |
| B12 | Correct exercise semantics, immutable set lifecycle and protocol-approved feedback. |
| B13 | Run-bound calibration, synchronization and drift validation for supported native stages. |
| B14 | Complete timelines and physically plausible 3D reconstruction with visible missing data. |
| B15 | Validated model scaling, filtering and inverse-kinematics outputs. Software imports/unit round trips do not establish physical validity. |
| B16 | Truthful reproducible reports/exports across native workflows; legacy reports are refused, but general integrity and the canceled browser download remain unresolved. |
| B17 | Independent endpoint-specific reference benchmarks and clinical validation. |
| B18 | Measured freshness, bounded latency/resources, safe interruption and supported-device performance evidence. |
| B19 | Approved privacy/security model, consent, protected storage, encryption/key management, retention and incident response before human recording. |
| B20 | Complete offline package, clean-machine install, reproducible CI/provenance, missing lint/type gates, dependency/model audit, Blender checks and launcher/Tk lifecycle findings. |
| B21 | Measured muscle acquisition, hardware and synchronization if included; otherwise explicit owner-approved exclusion of measurement claims. |

**D01–D08 remain OPEN:** intended endpoints/population; supported devices; muscle/EMG scope; local/cloud access and data policy; recovery objectives; independent reference/acceptance thresholds; native-stage release scope; retention, review and incident responsibility. Task implementation approval did not settle these decisions.

R01–R18 and N01–N05 are still unaccepted. The Required items include protected storage/jobs/recovery, guided setup, history/comparisons, offline/sync policy, honest research analysis, confidence adapters, interoperable export, accessibility/reflow/error states, performance, dependency/model provenance, supported launcher/API, evidence-derived badges/docs, change control, pilot procedures and scheduled recovery monitoring. None is closed by this report. The proposed portable evidence verifier N05 was not implemented; the local package-check script is only task evidence.

## Review, rollback and requested acceptance

The whole scoped application/test diff was reviewed by the same lead engineer; no independent second-agent review is claimed. Scope includes affected callers, refusal contracts, UI state, test fixtures, test command, packaging inputs, source preservation and rollback. Remote skill guidance was advisory only. Read skills included `soren-codex-workflow`, `soren-learning-loop`, Superpowers executing-plans/TDD/debugging/verification, `soren-universal-deployment`, `agent-browser`, Caveman and Chisle. The read-only SOREN `route_task` action ran once. The requested SorenK Unified capability was not exposed; Hindsight reads were unreachable, so no recalled content informed the result and nothing was retained in memory.

Actual skill-file locations read (all local):

- `C:/Users/soren/.codex/skills/soren-codex-workflow/SKILL.md`.
- `C:/Users/soren/.agents/skills/soren-learning-loop/SKILL.md`, `soren-universal-deployment/SKILL.md` and `agent-browser/SKILL.md` under that same skills directory; version-matched browser instructions came from `agent-browser skills get core`.
- `C:/Users/soren/.codex/plugins/cache/openai-curated-remote/superpowers/7.0.1/skills/`: `executing-plans/SKILL.md`, `test-driven-development/SKILL.md`, `systematic-debugging/SKILL.md`, `verification-before-completion/SKILL.md`, plus the TDD test-writing reference.
- `C:/Users/soren/.codex/plugins/cache/caveman/caveman/4.0.1/skills/caveman/SKILL.md` and `C:/Users/soren/.codex/plugins/cache/chisle/chisle/3.8.1/skills/chisle/SKILL.md`.

Rollback was **not executed**. Review `before.patch` and verified `before/` snapshots to reverse only this continuation without losing the earlier uncommitted work. Reverting the complete containment change would restore known unsafe behavior and must not be used with participants. Preserve archives and source/session directories; rollback must not delete or rewrite records. The package and its tested source state must be kept together.

**Owner result decision (2026-10-28): ACCEPTED WITH LIMITATIONS, covering M1 Tasks 1–3 as bounded safety-containment only.** Browser download delivery remains unresolved; all clinical, data-integrity, security, packaging, physical-validation and recovery blockers remain open. All 21 catalog BLOCKER items and D01–D08 remain unaccepted/open. See [the owner's exact acceptance and restrictions](M1_OWNER_ACCEPTANCE_20261028.md). This acceptance does **not** authorize a commit, push, merge, deployment, patient-data access, participant recording, or another milestone. The application remains unsuitable for claimed clinical measurement until future gates are independently approved. The historic [M1 evidence index](M1_EVIDENCE_20261028.json) was generated before the decision and therefore retains its then-accurate PENDING status.
