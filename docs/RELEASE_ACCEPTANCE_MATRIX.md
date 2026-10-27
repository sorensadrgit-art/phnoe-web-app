# Release acceptance matrix

**Rule.** A row may be marked `PASSED` only when it carries all four of:
(a) the exact command, (b) its exit code, (c) the artifact path produced,
(d) the SHA-256 of that artifact. File existence is not evidence. A zero exit
code is not evidence. A green UI badge is not evidence.

Rows are append-only: a later failure never deletes an earlier pass — it adds a
new row referencing the superseded one.

`PASSED` · `FAILED` · `PARTIAL` · `BLOCKED` · `NOT_STARTED` · `BLOCKED_ON_PHYSICAL_EVIDENCE`

---

## Gate table

| Gate | Pri | Scope | Status | Evidence today | Exit criteria |
|---|---|---|---|---|---|
| **G0** | P0 | Audit, safety snapshot, Git alignment | **BLOCKED** | `docs/G0_FINDINGS.md` §1–§4 (4-file tree, no source, no reachable workstation) | `g0-report.json` with no `STOP`; media manifest; verified snapshot + `history.bundle`; baseline exit codes recorded |
| **G1** | P0 | Local service & immutable session contract | NOT_STARTED | — | 401 anonymous, cross-origin denied, unknown Host denied, traversal/symlink refused, upload crash-safe, PID ownership correct; media bytes unchanged |
| **G2** | P0 | Six-role capture wizard + Evidence Passport | NOT_STARTED | — | Six roles explicit; measured board value cannot be fabricated; stale evidence cannot advance |
| **G3** | P0 | Native pipeline & 3D correctness | NOT_STARTED | — | Synthetic positive path + every listed negative gate refuses; no silent interpolation |
| **G4** | P1 | Motion Lab, gait/squat review | NOT_STARTED | — | Shared timeline verified; `.trc` never shown as `.mot`; missing values remain null |
| **G5** | P0 | SQLite index, reports, backup/restore | NOT_STARTED | — | Idempotent reindex; deterministic report; live-DB backup restores into staging; corrupt backup fails closed |
| **G6** | P0 | Offline Windows onedir release | NOT_STARTED | — | Clean VM, network disabled, no Python/Node present; install → use → restart → uninstall; sessions preserved |
| **G7** | P1 | Accessibility, UX, performance | NOT_STARTED | — | Keyboard-only flows, focus restore, reduced motion, 1280 px layout, no console errors |
| **G8** | P0 | Git, docs, release evidence | **PARTIAL** | This branch: 5 docs + 1 unexecuted script; `main` untouched | Source staged with secret/license audit; draft PR; `FINAL_BUILD_REPORT.md` from real logs |
| **G9** | — | Physical & clinical acceptance | **BLOCKED_ON_PHYSICAL_EVIDENCE** | `docs/PHYSICAL_VALIDATION_PENDING.md` | Six real roles + ruler measurement + native calibration/sync/3D evidence + independent reference |

---

## Negative-test checklist (must exist before the owning gate can pass)

| # | Injected fault | Expected behaviour | Gate |
|---|---|---|---|
| 1 | Swapped cam01/cam02 assignment | Refuse; name the mismatch | G2/G3 |
| 2 | Zero or absent board scale | Refuse before calibration | G2/G3 |
| 3 | Missing / ambiguous sync cue | No `SYNC_PASSED`; ask for exact frames | G2/G3 |
| 4 | Unequal FPS between cameras | Block sync; report measured FPS | G2/G3 |
| 5 | Stale calibration (source hash changed) | Invalidate downstream states | G2/G5 |
| 6 | Joint dropout / low landmark score | Nulls and gaps, no interpolation | G3/G4 |
| 7 | Implausible frame timestamp | Reject frame mapping | G3/G4 |
| 8 | Malformed run manifest | Refuse run; preserve partials as `FAILED` | G1/G3 |
| 9 | Interruption mid-write | Atomic publish; original intact | G1 |
| 10 | Registered original altered downstream | `STOP`; hash mismatch reported | G0/G2 |
| 11 | `.trc` presented as `.mot` | Labelled marker-only; no joint-angle claim | G3/G4 |
| 12 | Report requested with absent data | Section reads *unavailable*; no placeholder number | G5 |
| 13 | Corrupted backup restored | Fail closed; nothing overwritten | G5 |
| 14 | `.env`/token accidentally staged | Secret scan blocks the commit | G8 |

---

## Required artifact set per gate

Each gate must leave, in `reports/generated/<gate>/`:

1. `command.txt` — exact invocation, interpreter and version
2. `stdout.log` / `stderr.log` — unedited
3. `exit_code.txt`
4. `artifacts.sha256` — hashes of every produced artifact
5. one- or two-line verdict suitable for pasting into the table above

Absent these, the gate stays `NOT_STARTED`.
