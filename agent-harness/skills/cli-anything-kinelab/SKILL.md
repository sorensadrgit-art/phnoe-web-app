---
name: "cli-anything-kinelab"
description: "Read-only KineLab PT engineering verification harness: workspace/source identity, bounded quality probes, offline evidence verification and distribution-manifest inspection. Never records, mutates, exports or claims clinical validity."
---

# cli-anything-kinelab

Read-only wrapper around an explicitly selected KineLab PT source checkout's own
backends (`tools/check_quality.py`, `tools/verify_evidence.py`,
`tools/build_offline_distribution.py`). `CLINICAL_VALIDATION: UNVERIFIED`.

## Installation

Local editable install into an isolated developer-tools environment (not PyPI):

```powershell
<tools-venv>\Scripts\python.exe -m pip install -e agent-harness --no-deps
```

Prerequisites: Python 3.10-3.13 with click and prompt_toolkit; the KineLab
checkout passed via `--workspace`, whose `.venv` is the scientific runtime used
by quality probes; Node.js for `node-runtime`.

## Commands

`--workspace <checkout>` is required on every invocation. Add `--json` for one
JSON object on stdout.

| Command | Purpose | Exit |
| --- | --- | --- |
| `identity` | Workspace path, git HEAD read from `.git`, working-tree SHA-256 of backend and harness sources | 0 |
| `quality plan --check <id>` | Backend plan; nothing executes | 3 (NOT_RUN) |
| `quality run --check <id>` | Bounded `python-runtime`, `python-syntax` or `node-runtime` only | 0 PASS, 1 FAIL, 2 BLOCKED |
| `evidence verify <zip>` | Real offline verifier; native JSON/exit preserved; archive unchanged | 0/1/2 |
| `package inspect <DISTRIBUTION-MANIFEST.json>` | Manifest hash and stored claims; payload verification NOT_RUN | 0 |
| `repl` (default) | Interactive loop over the same commands; in-memory history; `help`, `exit`, `quit` | 0 |

Every JSON report carries `harness_identity` (workspace, git HEAD, hashes).

## Examples

```powershell
cli-anything-kinelab --workspace C:\path\to\checkout --json identity
cli-anything-kinelab --workspace C:\path\to\checkout --json quality plan --check python-syntax
cli-anything-kinelab --workspace C:\path\to\checkout --json quality run --check python-runtime
cli-anything-kinelab --workspace C:\path\to\checkout --json package inspect C:\path\to\DISTRIBUTION-MANIFEST.json
```

## Agent guidance

- Treat exit 3 / `NOT_RUN` and exit 2 / `BLOCKED` as not passing.
- Errors are JSON `{"status": "BLOCKED", "error": ...}` with exit 2.
- `LIVE_PATH_REFUSED`: the live `KineLab-PT-DualCam` checkout, any
  `KineLabPT-Candidate-M1` data root, the configured `KINELAB_CANDIDATE_DATA_ROOT`,
  database files and `.env` are refused before any filesystem access.
- Stored manifest statuses are claims, not current verification.
- There is no recording, capture, mutation, export, preview, undo/redo, build or
  deployment command, and no state file is written.
