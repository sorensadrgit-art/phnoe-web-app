# G0 — Audit findings and resume procedure

**Gate status: BLOCKED.** No application source exists in this repository, and no
workstation was reachable from the environment that produced this document.
Every row below was read from the GitHub API or is quoted from the file named;
nothing is inferred from the project plan.

Reads performed: 2026-10-27T22:50Z (initial) and 2026-10-27T23:10Z (confirmation).

---

## 1. Repository state (verified)

| Item | Value | Source |
|---|---|---|
| Visibility / size | private / 4 KB | `GET /repos/sorensadrgit-art/phnoe-web-app` |
| Created | 2026-10-27T18:17:09Z | same |
| Default branch | `main` | same |
| `main` HEAD | `536f493932c9796e2d04c55a43bec621645657ad` — *"Initialize private KineLab source repository with safe upload policy"* | commits API |
| Full root tree at `main` | **exactly 4 blobs**, no directories | contents API |
| … `.gitattributes` | `92681612faab274b4a9ed861a8684fe0a8cc1dc2` (204 B) | contents API |
| … `.gitignore` | `4973518a0dcb0fd07db5f6804b30fc605d2ce697` (1210 B) | contents API |
| … `README.md` | `7d344bf4d39da6d2c44cc29bead512c72e7afec0` (2448 B) | contents API |
| … `SECURITY.md` | `c2e5f3fa6c6485bdab5aca6502e3812a4140e4e0` (1164 B) | contents API |
| Last push | 2026-10-27T22:12:36Z | `GET /repos` |
| Second branch | `bolt/no-op-no-source-tree-13898006703331269008` @ `b029371421c2cdbd7f778a5d6029d84fc148a6c4` | branches API |
| Open issues | 1 | `GET /repos` |

`README.md` states, in its own words:

> The repository has been created, but the complete verified AgentZero source tree
> has **not yet been uploaded**. AgentZero became unavailable during the requested
> GitHub sync. This README and the safety configuration are preparatory only, not a
> claim that the project has been mirrored.

### 1.1 A bot is writing to this repository

`b0293714` was authored by `google-labs-jules[bot]` at 2026-10-27T22:12:35Z:

- message: *"Initial setup verification: no application source code present"*
- tree: `9a0ec610d5791db2ffade83879441daf618bf158` — **identical** to `main`'s tree
- `compare main...bolt/no-op-…` → `ahead_by: 1`, `files: []`, 0 changed files

Implication: an independent automated agent has already confirmed the same
finding, and it can create branches/commits at any time. Branch creation and the
first source push in G0/G8 must check for concurrent automation immediately
before pushing, and must never force-push over a bot ref.

---

## 2. Environment available to the executing agent

**Attempt 1** — isolated Linux container (`e2b.local`):

- Python 3.13.18, numpy 2.3.5, pytest 9.0.3, node present
- **no Pose2Sim, no OpenSim, no FFmpeg** → the native pipeline could not have run even with source
- no mount of `C:\`; the only checkout present (`/home/user/repo`) was an unrelated
  project (`Soren-MCP_1`, a Next.js repository)
- computer-control toolkits `triggercmd`, `orgo`, `needle`: `has_active_connection: false`

**Attempt 2** — no shell surface at all; GitHub read/write and web only.

Consequence, stated plainly: **0 tests executed, 0 media files hashed, 0 bundles
built, 0 screenshots captured.** The historical "189 Python / 33 JavaScript"
figures remain historical and are not re-verified here.

---

## 3. Why this is a stop, not a workaround

The handover plan defines the stop condition it is now hitting:

> STOP G0 if: AgentZero/project inaccessible; unresolvable Git conflict; suspected
> secrets/PHI staged; failing baseline cannot be diagnosed safely.

and separately:

> Stop if inaccessible; never implement against the four-file GitHub placeholder.

Implementing T7–T10 into a four-file repository would be a greenfield rewrite of
T1–T6, which the Object filter explicitly forbids ("Retain rather than rewrite").
There is no subset of G1–G8 that can be executed truthfully in this state.

---

## 4. Divergences from the handover plan

| ID | Plan assumption | Verified reality | Required adjustment |
|---|---|---|---|
| D1 | Source tree is in the private repo (or will be shortly) | 4 scaffolding files; README says upload never happened | G0 must import source before any gate |
| D2 | 189 Python / 33 JS tests are the working baseline | Unverifiable; not present in repo | Re-measure on the machine; treat old counts as historical only |
| D3 | Repo is quiescent, safe to branch | Jules bot pushed `b0293714` today | Add concurrent-automation check before every push |
| D4 | Repository can hold the needed fixtures/artifacts | `.gitignore` excludes `viewer/dist`, all media, `*.mot`, `*.trc`, `*.c3d`, `*.onnx`, `projects/`, `*.sqlite`, `*.db` | See §4.1 — changes G3 and G6 design |
| D5 | AgentZero reachable and read-only commands work | No bridge from this environment | Provide execution surface or run `tools/g0_preflight.ps1` |

### 4.1 Consequences of the committed `.gitignore` (new constraints)

1. **`viewer/dist` is ignored** → the offline bundle (G6) must *build* the Vite
   output at package time. It can never be committed, so packaging cannot assume
   a checked-in `dist`.
2. **`*.mot`, `*.trc`, `*.c3d` are ignored** → G3 fixtures cannot be committed as
   files. Negative tests must *generate* malformed/valid TRC/MOT content at test
   time from code, and the synthetic-fixture generator becomes a test dependency.
3. **`*.sqlite`, `*.db` are ignored** → the G5 index is machine state, not source.
   Migrations must therefore be code-only and re-creatable from an empty state;
   a committed database can never be the migration source of truth.
4. **`.env.*`, `*token*.json`, `instance.json`, `AppData/`, `launchers/`, `*.lnk`
   are ignored** → this part of the safety posture is sound; keep it.

---

## 5. Resume procedure (exact)

1. Copy `tools/g0_preflight.ps1` to the workstation, outside the project tree.
2. Audit-only dry run (no snapshot, no tests — safe, fast):

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\g0_preflight.ps1 -SkipTests -SkipSnapshot
   ```

3. Inspect `g0-report.json`. Any `STOP` row must be resolved before step 4.
4. Full run with real baseline commands:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\g0_preflight.ps1 `
     -PythonTestArgs '-m pytest -q' `
     -JsTestCommand 'npm --prefix viewer test -- --run' `
     -BuildCommand 'npm --prefix viewer run build'
   ```

5. Snapshot is written to `..\KineLab-G0-Snapshots\g0-<timestamp>\` containing
   `worktree\`, `history.bundle`, `uncommitted.patch`, `media_manifest.json`,
   `snapshot_manifest.json`, `g0-report.json`, `G0_REPORT.md`.
6. Only after reviewing the report and the snapshot: re-run with `-CreateBranch`.
7. Hand back `g0-report.json` plus the completed rows of
   `docs/RELEASE_ACCEPTANCE_MATRIX.md`. G1 may then start.

After any real capture session, prove media immutability with:

```powershell
powershell -File .\g0_preflight.ps1 -SkipTests -SkipSnapshot -CompareMediaManifest .\g0-<ts>\media_manifest.json
```

---

## 6. Not claimed by this document

- that any gate has passed
- that the application builds, launches, or is installable
- that the software is complete, offline-capable, or packaged
- any test count, timing, bundle size, or screenshot
- any physical calibration, 3D accuracy, markerless validity, or clinical result

**Final status: BLOCKED.** Physical: `BLOCKED_ON_PHYSICAL_EVIDENCE`. Clinical: `UNVERIFIED`.
