# KineLab read-only harness test plan

Written before test implementation, October 29, 2026.

## Inventory

- `test_core.py`: approximately 8 unit/real-backend integration checks.
- `test_full_e2e.py`: approximately 5 installed-command subprocess checks.

## Unit and backend plan

Exercise backend loading, required workspace identity, bounded quality selections,
quality plan versus execution, missing backend errors, package-manifest inspection
without invoking the mutating distribution verifier, and invalid evidence archives.
Use fresh generated temporary roots/files. Use the actual repository backend
functions and executable for backend checks; no replacement verifier.

## E2E workflows

1. Operator plans and executes only `python-runtime`/`python-syntax` through the
   existing quality tool. Verify its native JSON schema and distinguish NOT_RUN
   from PASS/BLOCKED. No build, broad tests, service or camera command is exposed.
2. Operator checks a generated malformed evidence ZIP through the actual offline
   verifier. Verify exact failure schema/code and unchanged archive digest.
3. Operator inspects a generated distribution manifest. Verify reported versus
   observed status, original digest preservation, and refusal of linked paths.
4. Installed `cli-anything-kinelab`: help, JSON plan, evidence rejection, package
   inspection, and REPL exit. `_resolve_cli()` and
   `CLI_ANYTHING_FORCE_INSTALLED=1` are mandatory for installation acceptance.

## Boundaries and gates

No patient/session database discovery or real media. State mutation, undo/redo,
autosave, save locking and dry-run mutations are not applicable to this read-only
surface. Preview/render/GUI round-trip and publication are NOT_RUN: no renderer or
application launch is authorized. Console JSON is an inspection report, not a
preview bundle. Read-only inspection never upgrades a manifest's stored status.

Initial dependency preflight: project Python 3.13.16 and prompt_toolkit 3.0.53
present; Click, pip, setuptools, wheel, pytest and Jinja2 absent. Conditional
editable installation and pytest/installed-command gates are BLOCKED until the
required dependencies are separately provisioned. No dependency fallback is a
passing result.

## Test Results

Last run: 20261029T080211 UTC, tools-venv Python 3.13.16, pytest 9.2.0, from a fresh temporary cwd with
PYTHONPATH cleared and CLI_ANYTHING_FORCE_INSTALLED=1. The dependency preflight above is superseded:
click, prompt_toolkit, pytest and the editable install are now present in the isolated tools venv only.
Log: dist/fullproject-20261028/factory-R2/W3-harness-installed-tests-FINAL-20261029T080211.log

```
============================= test session starts =============================
platform win32 -- Python 3.13.16, pytest-9.2.0, pluggy-1.7.0 -- C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace\dist\fullproject-20261028\tools-venv\Scripts\python.exe
rootdir: C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness
plugins: platformdirs-4.14.0
collecting ... collected 20 items

..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestCore::test_broad_or_mutating_checks_are_rejected SUBPASSED(check='python-tests')
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestCore::test_broad_or_mutating_checks_are_rejected SUBPASSED(check='desktop-build')
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestCore::test_broad_or_mutating_checks_are_rejected SUBPASSED(check='cloud-build')
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestCore::test_broad_or_mutating_checks_are_rejected SUBPASSED(check='security-advisories')
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestCore::test_broad_or_mutating_checks_are_rejected PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestCore::test_invalid_package_manifest_is_rejected PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestCore::test_missing_backend_is_an_error PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestCore::test_package_inspection_preserves_manifest_and_does_not_claim_verification PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestCore::test_quality_plan_is_not_execution PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestCore::test_real_evidence_backend_rejects_generated_bad_archive_without_changes PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestCore::test_real_quality_runtime_probe_has_explicit_scope PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_configured_candidate_data_root_is_refused PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_data_roots_databases_and_secrets_are_refused_as_artifacts SUBPASSED(path=WindowsPath('C:/Users/soren/AppData/Local/Temp/tmpoc0xbz0i/KineLab-PT-DualCam/DISTRIBUTION-MANIFEST.json'))
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_data_roots_databases_and_secrets_are_refused_as_artifacts SUBPASSED(path=WindowsPath('C:/Users/soren/AppData/Local/Temp/tmpoc0xbz0i/KineLabPT-Candidate-M1/data/DISTRIBUTION-MANIFEST.json'))
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_data_roots_databases_and_secrets_are_refused_as_artifacts SUBPASSED(path=WindowsPath('C:/Users/soren/AppData/Local/Temp/tmpoc0xbz0i/sessions.sqlite'))
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_data_roots_databases_and_secrets_are_refused_as_artifacts SUBPASSED(path=WindowsPath('C:/Users/soren/AppData/Local/Temp/tmpoc0xbz0i/kinelab.db'))
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_data_roots_databases_and_secrets_are_refused_as_artifacts SUBPASSED(path=WindowsPath('C:/Users/soren/AppData/Local/Temp/tmpoc0xbz0i/.env'))
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_data_roots_databases_and_secrets_are_refused_as_artifacts PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_identity_names_workspace_head_and_current_source_hashes PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_live_legacy_checkout_is_refused_before_filesystem_access SUBPASSED(path=WindowsPath('C:/Users/soren/Documents/Projects/KineLab-PT-DualCam'))
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_live_legacy_checkout_is_refused_before_filesystem_access SUBPASSED(path=WindowsPath('C:/Users/soren/Documents/Projects/kinelab-pt-dualcam/viewer'))
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_live_legacy_checkout_is_refused_before_filesystem_access PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_core.py::TestBoundaryAndIdentity::test_quality_uses_explicit_scientific_runtime_not_harness_interpreter PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_full_e2e.py::TestCLISubprocess::test_default_repl_accepts_exit_without_global_history [_resolve_cli] Using installed command: C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace\dist\fullproject-20261028\tools-venv\Scripts\cli-anything-kinelab.EXE
PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_full_e2e.py::TestCLISubprocess::test_evidence_rejection_preserves_generated_file [_resolve_cli] Using installed command: C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace\dist\fullproject-20261028\tools-venv\Scripts\cli-anything-kinelab.EXE
PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_full_e2e.py::TestCLISubprocess::test_help [_resolve_cli] Using installed command: C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace\dist\fullproject-20261028\tools-venv\Scripts\cli-anything-kinelab.EXE
PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_full_e2e.py::TestCLISubprocess::test_identity_json_reports_head_and_hashes [_resolve_cli] Using installed command: C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace\dist\fullproject-20261028\tools-venv\Scripts\cli-anything-kinelab.EXE
PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_full_e2e.py::TestCLISubprocess::test_live_workspace_is_refused_with_json_error [_resolve_cli] Using installed command: C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace\dist\fullproject-20261028\tools-venv\Scripts\cli-anything-kinelab.EXE
PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_full_e2e.py::TestCLISubprocess::test_no_recording_mutation_or_export_commands_are_exposed [_resolve_cli] Using installed command: C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace\dist\fullproject-20261028\tools-venv\Scripts\cli-anything-kinelab.EXE
PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_full_e2e.py::TestCLISubprocess::test_package_json_does_not_upgrade_stored_claims [_resolve_cli] Using installed command: C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace\dist\fullproject-20261028\tools-venv\Scripts\cli-anything-kinelab.EXE
PASSED
..\..\..\..\Documents\Projects\KineLab-PT-Production-Agent-Workspace\agent-harness\cli_anything\kinelab\tests\test_full_e2e.py::TestCLISubprocess::test_plan_json_has_not_run_status_and_exit [_resolve_cli] Using installed command: C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace\dist\fullproject-20261028\tools-venv\Scripts\cli-anything-kinelab.EXE
PASSED

=================== 20 passed, 11 subtests passed in 5.72s ====================
```

Coverage notes: quality execution covers python-runtime only (real scientific .venv probe); evidence
verification covers a generated corrupt archive only; package inspection uses generated manifests. Live-path
refusal is lexical and tested without touching the live checkout. No GUI, preview, recording or round-trip
test exists because the harness exposes none of those capabilities.
