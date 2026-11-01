# KineLab CLI-Anything analysis and operator contract

Target: the existing isolated KineLab-PT-Production-Agent-Workspace checkout.
Native Codex implementation; the independent evidence verifier remains owned by
Factory. This wrapper does not substitute for its review or acceptance.

Backend mapping:

| Harness operation | Existing backend | Scope |
| --- | --- | --- |
| quality plan/run | `tools/check_quality.py` `run_checks` | Explicit bounded runtime/syntax probes only |
| evidence verify | `tools/verify_evidence.py` command | Explicit archive only; native JSON/exit code preserved |
| package inspect | `tools/build_offline_distribution.py` `reject_link_traversal`, `sha256_file` | Read manifest and hash only |

The distribution builder's `verify_distribution_integrity` rewrites the manifest.
It is deliberately not exposed by this read-only harness. Inspection does not
reimplement or claim payload verification. Existing status fields are reported
as claims. Package construction and launching native stages are not supported.

Use explicit `--workspace` and artifact paths. No workspace search, session scan,
network, global configuration, installation or GUI launch is performed by the
harness. The REPL keeps command history in memory; it does not save global history.
There is no mutable project state, so undo/redo, autosave, locking and mutation
dry-run are not applicable. No preview/render capability is claimed.

Follow CLI-Anything phases from the installed skill. Canonical skill is contained
at `agent-harness/skills/cli-anything-kinelab/SKILL.md` because file ownership is
restricted to agent-harness. The packaged copy is byte-identical. Moving a copy
to workspace-root `skills/` is a separate parent integration step.

Required gates: Click runtime, editable installation, installed-command subprocess
tests, pytest methodology run, backend fixtures and source/package structure.
Missing dependencies remain BLOCKED; static syntax never replaces invocation.
