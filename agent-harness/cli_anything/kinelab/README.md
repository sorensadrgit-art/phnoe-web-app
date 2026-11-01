# cli-anything-kinelab

Read-only engineering verification and inspection harness for an explicitly
selected KineLab PT source checkout. It wraps the checkout's own backends
(`tools/check_quality.py`, `tools/verify_evidence.py`,
`tools/build_offline_distribution.py`) and never reimplements them.

Status labels: `SOFTWARE_BUILD_VERIFIED` claims come only from the backend.
`CLINICAL_VALIDATION: UNVERIFIED`. Nothing here records, captures, mutates,
exports, deploys or establishes physical or clinical validity.

## Dependency

The "software" is the KineLab source checkout itself. Pass it with
`--workspace`; there is no search. Quality probes use the checkout's scientific
runtime at `<workspace>/.venv` (Python 3.10-3.13 with OpenSim and Pose2Sim), not
the interpreter running this harness. Node.js is needed for `node-runtime`.

## Install (isolated developer tools environment only)

```powershell
<tools-venv>\Scripts\python.exe -m pip install -e agent-harness --no-deps
```

Requires click and prompt_toolkit in that environment.

## Usage

```powershell
cli-anything-kinelab --workspace <checkout> --json identity
cli-anything-kinelab --workspace <checkout> --json quality plan --check python-syntax
cli-anything-kinelab --workspace <checkout> --json quality run --check python-runtime
cli-anything-kinelab --workspace <checkout> --json evidence verify <archive.zip>
cli-anything-kinelab --workspace <checkout> --json package inspect <DISTRIBUTION-MANIFEST.json>
cli-anything-kinelab --workspace <checkout>        # REPL; type help, exit or quit
```

| Group | Command | Behavior |
| --- | --- | --- |
| identity | `identity` | Workspace path, git HEAD (read from `.git`), working-tree SHA-256 of backend and harness sources |
| quality | `plan`, `run` | Bounded `python-runtime`, `python-syntax`, `node-runtime` only; plan exits 3 (NOT_RUN) |
| evidence | `verify` | Real offline verifier; native JSON and exit code preserved; archive unchanged |
| package | `inspect` | Manifest hash and stored claims; payload verification NOT_RUN; manifest unchanged |
| repl | `repl` | Default when no subcommand; in-memory history only |

Exit codes: 0 PASS/INSPECTED, 1 FAIL, 2 BLOCKED/refused, 3 NOT_RUN.

## Refused locations

Checked lexically before any filesystem access, for `--workspace` and every
artifact argument: any path containing a `KineLab-PT-DualCam` component (the live
legacy checkout), any `KineLabPT-Candidate-M1` component, the configured
`KINELAB_CANDIDATE_DATA_ROOT`, SQLite/database files and `.env`. The refusal is
`LIVE_PATH_REFUSED` with exit 2.

## Tests

```powershell
$env:CLI_ANYTHING_FORCE_INSTALLED='1'
<tools-venv>\Scripts\python.exe -m pytest agent-harness/cli_anything/kinelab/tests -v -s
```

No preview, render, undo/redo or session-file mutation exists, because the
harness has no mutable project state.
