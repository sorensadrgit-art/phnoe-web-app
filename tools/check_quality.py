"""Explicit local quality checks; a plan is NOT_RUN, never acceptance.

The scientific runtime (--python, default <root>/.venv) and the developer tooling
interpreter (--tools-python: ruff, mypy, pip-audit) are separate, explicit and
recorded in every report. The gate does not install or upgrade packages, launch
the live app, or inspect source recordings. Selected existing tests run their
normal behavior with a unique candidate data root.

Plan mode (default) never starts a subprocess. --run requires an explicit
--checks selection and writes a fresh receipts directory: one log per executed
gate plus report.json, each receipt naming tool, version, argv, cwd, exit code,
duration and log SHA-256. Overall PASS requires every selected gate to run and
pass. The security-advisories gate (pip-audit) sends installed package names and
versions to the public advisory service, and npm-advisories (npm audit
--package-lock-only) sends the locked viewer package names and versions to the npm
registry advisory endpoint; no source or data is sent and nothing is installed or
fixed. Frontend builds write to fresh directories inside the receipts directory,
never the shared viewer/dist.
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import hashlib
import importlib
import json
import os
import shutil
import stat
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

RUNTIME_PROBE = """
import sys,json,hashlib
from pathlib import Path
result={'status':'PASS','python':list(sys.version_info[:3]),'executable':sys.executable,
        'path_is_junction':hasattr(Path,'is_junction'),
        'hashlib_file_digest':hasattr(hashlib,'file_digest')}
try:
 import opensim
 import Pose2Sim
 import importlib.metadata as metadata
 result.update(opensim=opensim.GetVersion(),Pose2Sim=metadata.version('Pose2Sim'))
except Exception as error:
 result.update(status='BLOCKED',reason=type(error).__name__+': '+str(error))
print(json.dumps(result))
"""
SYNTAX_PROBE = """
import ast
from pathlib import Path
paths=list(Path('.').glob('*.py'))
for directory in ('tools','tests'):
 paths.extend(Path(directory).glob('*.py'))
for path in sorted(paths):
 ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path))
print('Python syntax parsed:',len(paths),'source files; no compatibility/type claim')
"""
CHECK_IDS = (
    "python-runtime", "python-syntax", "python-dependencies",
    "node-runtime", "node-dependencies", "python-tests", "node-tests",
    "cloud-build", "desktop-build", "lint", "typecheck", "typecheck-harness",
    "security-advisories", "npm-advisories", "workflow-syntax", "measurement-regressions",
)
OUTPUT_TAIL = 8000
WORKFLOW_PATH = Path(".github") / "workflows" / "quality.yml"
YAML_PARSER_PROBE = "import yaml; print('PyYAML ' + yaml.__version__)"


# This scope is software input identity, never an approved physical reference corpus.
MEASUREMENT_SCOPE = "kinelab.first-party-software.v1"
MEASUREMENT_TREES = ("tools", "tests", "agent-harness", "viewer/src", "viewer/public/motion", "models", ".github/workflows")
MEASUREMENT_ROOT_SUFFIXES = {".py", ".json", ".toml", ".ini", ".cfg", ".yaml", ".yml", ".txt"}
MEASUREMENT_VIEWER_FILES = {"package.json", "package-lock.json", "index.html", "vercel.json"}
MEASUREMENT_LIMIT = 32 * 1024 * 1024
MEASUREMENT_TOTAL = 256 * 1024 * 1024
MEASUREMENT_COUNT = 10000
MEASUREMENT_EXCLUDES = {"__pycache__", ".git", ".venv", "node_modules", "build", "dist"}


def _measurement_path(value: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or any(part in {"", ".", ".."} or part.endswith((".", " ")) for part in value.split("/"))
            or any(ord(char) < 32 for char in value) or value.startswith("/")):
        raise ValueError("MEASUREMENT_PATH_UNSAFE")
    return value


def _measurement_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


def _measurement_sha(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _measurement_no_links(path: Path) -> None:
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("MEASUREMENT_REPARSE_REFUSED")


def _measurement_identity(info, *, opening=False):
    common = (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), info.st_size,
              info.st_mtime_ns, getattr(info, "st_birthtime_ns", None))
    # Windows path/fd ctime and inferred executable permissions have different semantics.
    return common if opening else (*common, info.st_mode, info.st_ctime_ns)


def _measurement_read(path: Path, limit=MEASUREMENT_LIMIT) -> bytes:
    path = path.absolute()
    _measurement_no_links(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError("MEASUREMENT_FILE_LIMIT_OR_TYPE")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if _measurement_identity(before, opening=True) != _measurement_identity(opened, opening=True):
            raise ValueError("MEASUREMENT_OPEN_CHANGED")
        data = stream.read(limit + 1)
        closed = os.fstat(stream.fileno())
    _measurement_no_links(path)
    if (len(data) != before.st_size or len(data) > limit
            or _measurement_identity(opened) != _measurement_identity(closed)
            or _measurement_identity(before) != _measurement_identity(path.lstat())):
        raise ValueError("MEASUREMENT_READ_CHANGED")
    return data


def _measurement_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("MEASUREMENT_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _measurement_json(path, expected):
    if not _measurement_sha(expected):
        raise ValueError("MEASUREMENT_SHA_REQUIRED")
    data = _measurement_read(Path(path), 2 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("MEASUREMENT_PIN_MISMATCH")
    document = json.loads(data.decode("utf-8"), object_pairs_hook=_measurement_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError("MEASUREMENT_JSON_NONFINITE")))
    if not isinstance(document, dict):
        raise TypeError("MEASUREMENT_DOCUMENT_REQUIRED")
    return document


def _measurement_in_scope(name):
    parts = name.split("/")
    return ((len(parts) == 1 and Path(name).suffix in MEASUREMENT_ROOT_SUFFIXES)
            or any(name.startswith(tree + "/") for tree in MEASUREMENT_TREES)
            or (len(parts) == 2 and parts[0] == "viewer"
                and (parts[1] in MEASUREMENT_VIEWER_FILES or parts[1].startswith("vite.config."))))


def _measurement_inventory(root: Path) -> dict:
    paths = []
    for path in root.iterdir():
        if path.suffix in MEASUREMENT_ROOT_SUFFIXES:
            paths.append(path)
            if len(paths) > MEASUREMENT_COUNT:
                raise ValueError("MEASUREMENT_COUNT_LIMIT")
    viewer = root / "viewer"
    if viewer.is_dir():
        _measurement_no_links(viewer)
        for path in viewer.iterdir():
            if path.name in MEASUREMENT_VIEWER_FILES or path.name.startswith("vite.config."):
                paths.append(path)
                if len(paths) > MEASUREMENT_COUNT:
                    raise ValueError("MEASUREMENT_COUNT_LIMIT")
    for tree in MEASUREMENT_TREES:
        directory = root / tree
        if not directory.exists():
            continue
        _measurement_no_links(directory)
        for parent, directories, files in os.walk(directory, followlinks=False):
            for name in directories:
                _measurement_no_links(Path(parent) / name)
            directories[:] = [name for name in directories
                              if name not in MEASUREMENT_EXCLUDES and not name.endswith(".egg-info")]
            paths.extend(Path(parent) / name for name in files)
            if len(paths) > MEASUREMENT_COUNT:
                raise ValueError("MEASUREMENT_COUNT_LIMIT")
    result = {}
    folded = set()
    total = 0
    for path in sorted(paths):
        name = _measurement_path(path.relative_to(root).as_posix())
        if name.casefold() in folded:
            raise ValueError("MEASUREMENT_CASE_ALIAS")
        folded.add(name.casefold())
        data = _measurement_read(path)
        total += len(data)
        if total > MEASUREMENT_TOTAL:
            raise ValueError("MEASUREMENT_TOTAL_LIMIT")
        result[name] = hashlib.sha256(data).hexdigest()
    return result


def measurement_binding(root: Path, before_path, before_sha256, matrix_path, matrix_sha256) -> dict:
    """Verify pinned software inputs; a pinned baseline is supplied authority, never auto-created."""
    if before_path is None or matrix_path is None:
        raise ValueError("MEASUREMENT_BEFORE_AND_MATRIX_REQUIRED")
    before = _measurement_json(before_path, before_sha256)
    matrix = _measurement_json(matrix_path, matrix_sha256)
    if (set(before) != {"schema", "scope", "files", "inventory_sha256"}
            or before["schema"] != "kinelab.measurement-before.v1" or before["scope"] != MEASUREMENT_SCOPE):
        raise ValueError("MEASUREMENT_BASELINE_SCHEMA")
    files = before["files"]
    if not isinstance(files, dict) or not files or len(files) > MEASUREMENT_COUNT:
        raise ValueError("MEASUREMENT_BASELINE_INCOMPLETE")
    folded = set()
    for name, digest in files.items():
        _measurement_path(name)
        if not _measurement_in_scope(name) or not _measurement_sha(digest) or name.casefold() in folded:
            raise ValueError("MEASUREMENT_BASELINE_MEMBER")
        folded.add(name.casefold())
    if before["inventory_sha256"] != _measurement_digest(files):
        raise ValueError("MEASUREMENT_BASELINE_DIGEST")
    if (set(matrix) != {"schema", "scope", "rules", "generated_fixtures"}
            or matrix["schema"] != "kinelab.software-regression-matrix.v1" or matrix["scope"] != MEASUREMENT_SCOPE
            or not isinstance(matrix["rules"], list) or not matrix["rules"] or len(matrix["rules"]) > 100
            or not isinstance(matrix["generated_fixtures"], dict) or not matrix["generated_fixtures"]):
        raise ValueError("MEASUREMENT_MATRIX_SCHEMA")
    for rule in matrix["rules"]:
        if (not isinstance(rule, dict) or set(rule) != {"path", "checks"}
                or not isinstance(rule["path"], str) or not rule["path"]
                or "\\" in rule["path"] or ":" in rule["path"] or ".." in rule["path"].split("/")
                or rule["path"].startswith("/") or rule["checks"] != ["python-tests", "node-tests"]):
            raise ValueError("MEASUREMENT_MATRIX_RULE")
    after = _measurement_inventory(root)
    if not after:
        raise ValueError("MEASUREMENT_SOURCE_EMPTY")
    for name, digest in matrix["generated_fixtures"].items():
        _measurement_path(name)
        if not _measurement_sha(digest) or after.get(name) != digest:
            raise ValueError("MEASUREMENT_FIXTURE_PIN_MISMATCH")
    changed = sorted(name for name in files.keys() | after.keys() if files.get(name) != after.get(name))
    for name in changed:
        if not any(fnmatch.fnmatchcase(name, rule["path"]) for rule in matrix["rules"]):
            raise ValueError("MEASUREMENT_CHANGE_UNMAPPED: " + name + " is inside scope " + MEASUREMENT_SCOPE
                             + " but no matrix rule maps it; refused deliberately before any runner")
    # A second complete observation detects added/removed members and mid-scan changes.
    if _measurement_inventory(root) != after:
        raise ValueError("MEASUREMENT_SOURCE_CHANGED")
    return {"schema": "kinelab.measurement-binding.v1", "status": "NOT_RUN",
            "before_manifest_sha256": before_sha256, "matrix_sha256": matrix_sha256,
            "before_inventory_sha256": before["inventory_sha256"],
            "after_inventory_sha256": _measurement_digest(after), "after_files": after,
            "changed": changed, "added": sorted(after.keys() - files.keys()),
            "removed": sorted(files.keys() - after.keys()),
            "required_checks": ["python-tests", "node-tests"] if changed else [],
            "generated_fixtures": matrix["generated_fixtures"], "evidence_verified": False,
            "accuracy": "UNVERIFIED", "physical_coverage": "UNVERIFIED", "device_latency": "UNVERIFIED"}

def validate_workflow_document(text: str, loader: Callable[[str], Any],
                               errors: tuple[type[BaseException], ...] = (ValueError,)) -> dict:
    """Parse with the supplied YAML loader, then require a GitHub workflow shape."""
    try:
        document = loader(text)
    except errors as error:
        return {"valid": False, "reason": f"YAML parse error: {error}"}
    if not isinstance(document, dict):
        return {"valid": False, "reason": "Workflow document is not a mapping"}
    # YAML 1.1 loaders such as PyYAML read the bare key "on" as boolean True.
    if "on" not in document and True not in document:
        return {"valid": False, "reason": "Workflow has no 'on' trigger"}
    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return {"valid": False, "reason": "Workflow has no jobs mapping"}
    for name, job in jobs.items():
        if not isinstance(job, dict) or not ("runs-on" in job or "uses" in job):
            return {"valid": False, "reason": f"Job {name!r} has neither runs-on nor uses"}
        if "steps" in job and not isinstance(job["steps"], list):
            return {"valid": False, "reason": f"Job {name!r} steps is not a list"}
    return {"valid": True, "jobs": sorted(str(name) for name in jobs)}


def python_targets(root: Path) -> list[str]:
    """First-party Python sources: top-level modules plus tools/ and tests/."""
    targets = sorted(path.name for path in root.glob("*.py"))
    return targets + [name for name in ("tools", "tests") if (root / name).is_dir()]


def tool_config_arguments(root: Path) -> tuple[list[str], list[str]]:
    """Pin ruff/mypy to repository configuration only, so user or parent-directory
    configuration on the operator machine cannot change which rules are applied."""
    ruff = next((root / name for name in ("ruff.toml", ".ruff.toml", "pyproject.toml") if (root / name).is_file()), None)
    mypy = next((root / name for name in ("mypy.ini", ".mypy.ini", "pyproject.toml", "setup.cfg") if (root / name).is_file()), None)
    return (["--config", str(ruff)] if ruff else ["--isolated"],
            ["--config-file", str(mypy) if mypy else ""])


def lint_config_note(root: Path) -> str:
    ruff, mypy = tool_config_arguments(root)
    ruff_text = "ruff tool defaults (--isolated, no project configuration)" if ruff == ["--isolated"] else f"ruff repository configuration {ruff[1]}"
    mypy_text = "mypy tool defaults (no project configuration)" if mypy[1] == "" else f"mypy repository configuration {mypy[1]}"
    return f"Lint/type findings use {ruff_text} and {mypy_text}; no finding is suppressed."


def default_site_packages(python_executable: str) -> Path:
    environment = Path(python_executable).parent.parent
    if os.name == "nt":
        return environment / "Lib" / "site-packages"
    candidates = sorted((environment / "lib").glob("python3*/site-packages"))
    return candidates[0] if candidates else environment / "lib" / "site-packages"


def check_definitions(root: Path, python_executable: str, node: str | None, npm: str | None,
                      tools_python: str | None = None, audit_site_packages: Path | None = None,
                      receipts_dir: Path | None = None) -> dict:
    scripts = json.loads((root / "viewer" / "package.json").read_text(encoding="utf-8")).get("scripts", {})
    python = [python_executable, "-X", "utf8", "-B"]
    targets = python_targets(root)
    ruff_config, mypy_config = tool_config_arguments(root)
    receipts_dir = Path(receipts_dir or root / "dist" / "quality-receipts-PLANNED").absolute()
    # A repository configuration owns the scope (ruff include/exclude, mypy files=); the
    # explicit target list is only the fallback for configuration-free tool defaults.
    ruff_scope = ["."] if ruff_config != ["--isolated"] else targets
    mypy_scope = [] if mypy_config[1] else ["--explicit-package-bases", *targets]
    lockfile = root / "viewer" / "package-lock.json"
    workflow = root / WORKFLOW_PATH
    site_packages = Path(audit_site_packages) if audit_site_packages else default_site_packages(python_executable)
    no_tools = "Developer tools interpreter (--tools-python) is not configured; no substitute is used"
    tools = tools_python or None
    harness_ready = bool(tools and mypy_config[1] and (root / "agent-harness").is_dir())
    definitions = {
        "python-runtime": {"command": python + ["-c", RUNTIME_PROBE], "tool": "scientific-python"},
        "python-syntax": {"command": python + ["-c", SYNTAX_PROBE], "requires": ["python-runtime"],
                          "tool": "scientific-python"},
        "python-dependencies": {"command": python + ["-m", "pip", "check"] if (root / "requirements.lock.txt").is_file() else None,
                                "requires": ["python-runtime"], "tool": "scientific-python",
                                "reason": "Required requirements.lock.txt inventory is unavailable"},
        "node-runtime": {"command": [node, "--version"] if node else None, "tool": "node",
                         "reason": "Node executable is unavailable"},
        "node-dependencies": {"command": [npm, "--prefix", "viewer", "ls", "--all", "--offline"] if npm else None,
                              "requires": ["node-runtime"], "tool": "npm",
                              "version_command": [npm, "--version"] if npm else None,
                              "reason": "npm executable is unavailable"},
        "python-tests": {"command": python + ["-m", "unittest", "discover", "-s", "tests", "-v"],
                         "requires": ["python-runtime", "python-syntax", "python-dependencies"],
                         "tool": "scientific-python"},
        "lint": {"command": [tools_python, "-m", "ruff", "check", *ruff_config, "--no-cache", "--output-format", "concise", *ruff_scope] if tools else None,
                 "tool": "ruff", "version_command": [tools_python, "-m", "ruff", "--version"] if tools else None,
                 "reason": no_tools},
        "typecheck": {"command": [tools_python, "-m", "mypy", *mypy_config, "--python-executable", python_executable,
                                               "--cache-dir", str(receipts_dir / "mypy-cache"),
                                               "--no-color-output", *mypy_scope] if tools else None,
                      "tool": "mypy", "version_command": [tools_python, "-m", "mypy", "--version"] if tools else None,
                      "reason": no_tools},
        # agent-harness is installed into the tools interpreter (its click dependency lives there).
        "typecheck-harness": {"command": [tools_python, "-m", "mypy", *mypy_config, "--python-executable", tools_python,
                                                       "--cache-dir", str(receipts_dir / "mypy-harness-cache"),
                                                       "--no-color-output", "agent-harness"] if harness_ready else None,
                              "tool": "mypy", "version_command": [tools_python, "-m", "mypy", "--version"] if harness_ready else None,
                              "reason": no_tools if not tools else "agent-harness/ or repository mypy configuration is unavailable"},
        "security-advisories": {"command": [tools_python, "-m", "pip_audit", "--path", str(site_packages),
                                                         "--progress-spinner", "off", "--format", "columns",
                                                         "--cache-dir", str(receipts_dir / "pip-audit-cache")] if tools else None,
                                "tool": "pip-audit", "requires_path": site_packages,
                                "version_command": [tools_python, "-m", "pip_audit", "--version"] if tools else None,
                                "reason": no_tools},
        "npm-advisories": {"command": [npm, "--prefix", "viewer", "audit", "--json", "--package-lock-only"]
                           if npm and lockfile.is_file() else None,
                           "requires": ["node-runtime"], "tool": "npm",
                           "version_command": [npm, "--version"] if npm else None,
                           # The advisory query needs the registry; every other npm gate stays offline.
                           "env": {"npm_config_offline": "false", "npm_config_audit": "true"},
                           "reason": "npm executable or viewer/package-lock.json is unavailable"},
        "workflow-syntax": {"command": [tools_python, "-X", "utf8", "-B", str(Path(__file__).resolve()),
                                        "--validate-workflow", str(workflow)] if tools and workflow.is_file() else None,
                            "tool": "pyyaml",
                            "version_command": [tools_python, "-c", YAML_PARSER_PROBE, "--version"] if tools else None,
                            "reason": no_tools if not tools else f"Workflow file is unavailable: {workflow}"},
    }
    for name, script in (("node-tests", "test"), ("cloud-build", "build:cloud"), ("desktop-build", "build")):
        command = [npm, "--prefix", "viewer"] + (["test"] if script == "test" else
                                                 ["run", script, "--", "--outDir", str(receipts_dir / f"{name}-dist")])
        definitions[name] = {
            "command": command if npm and script in scripts else None,
            "requires": ["node-runtime", "node-dependencies"], "tool": "npm",
            "version_command": [npm, "--version"] if npm else None,
            "reason": f"npm or required viewer script {script!r} is unavailable",
        }
    definitions["measurement-regressions"] = {
        "command": None, "tool": "local-source-binding",
        "reason": "Explicit pinned before inventory and software regression matrix are required",
    }
    return definitions


def _write_log(path: Path, argv: list[str], cwd: Path, completed, probe: dict | None) -> str:
    sections = ["argv: " + json.dumps(argv), "cwd: " + str(cwd)]
    if probe:
        sections.append("version_probe: " + json.dumps(probe))
    sections += ["exit_code: " + str(completed.returncode),
                 "--- stdout ---", completed.stdout or "", "--- stderr ---", completed.stderr or ""]
    data = "\n".join(sections).encode("utf-8")
    with path.open("xb") as stream:
        stream.write(data)
    return hashlib.sha256(data).hexdigest()


def run_checks(root, selected=None, *, execute=False, runner=None,
               python_executable=None, tools_python=None, node=None, npm=None,
               audit_site_packages=None, receipts_dir=None, timeout=900,
               measurement_before=None, measurement_before_sha256=None,
               regression_matrix=None, regression_matrix_sha256=None):
    runner = runner or subprocess.run
    root = Path(root).resolve()
    python_executable = str(python_executable or root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    node = node or shutil.which("node")
    npm = npm or shutil.which("npm")
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    receipts_dir = (Path(receipts_dir) if receipts_dir else root / "dist" / f"quality-receipts-{stamp}-{uuid.uuid4().hex[:8]}").absolute()
    definitions = check_definitions(root, python_executable, node, npm, tools_python,
                                    audit_site_packages, receipts_dir)
    # The binding needs explicit pinned inputs, so only an explicit selection may require it.
    requested = set(CHECK_IDS) - {"measurement-regressions"} if selected is None else set(selected)
    unknown = requested - set(CHECK_IDS)
    if unknown:
        raise ValueError("Unknown checks: " + ", ".join(sorted(unknown)))
    selected_checks = set(requested)
    binding = None
    binding_error = None
    if "measurement-regressions" in requested:
        try:
            binding = measurement_binding(root, measurement_before, measurement_before_sha256,
                                          regression_matrix, regression_matrix_sha256)
            definitions["measurement-regressions"]["requires"] = binding["required_checks"]
        except (OSError, ValueError, TypeError, KeyError) as error:
            binding_error = str(error)

    def include_dependencies(name):
        for prerequisite in definitions[name].get("requires", []):
            if prerequisite not in selected_checks:
                selected_checks.add(prerequisite)
                include_dependencies(prerequisite)
    for name in tuple(selected_checks):
        include_dependencies(name)

    if execute:
        try:
            receipts_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise ValueError(f"Receipts directory already exists and is never reused: {receipts_dir}") from error

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("MYPYPATH", None)
    # ruff and others treat any FORCE_COLOR value, including "0", as forcing ANSI color.
    environment.pop("FORCE_COLOR", None)
    environment["NO_COLOR"] = "1"
    environment.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
                       PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INDEX="1",
                       npm_config_offline="true", npm_config_audit="false",
                       npm_config_fund="false")
    # Never let test subprocesses inherit a live/default candidate data root.
    isolated_data_root = root / "dist" / ("quality-fixtures-" + uuid.uuid4().hex)
    environment["KINELAB_CANDIDATE_DATA_ROOT"] = str(isolated_data_root)
    runtime_version = None
    results = {}
    for name in CHECK_IDS:
        definition = definitions[name]
        item = {"id": name, "selected": name in selected_checks,
                "requested": name in requested, "status": "NOT_RUN",
                "tool": definition.get("tool"), "command": definition["command"],
                "reason": "Unselected check"}
        results[name] = item
        if not item["selected"]:
            continue
        if binding_error:
            if execute or name == "measurement-regressions":
                item.update(status="BLOCKED", reason="Measurement binding refused: " + binding_error)
            else:
                item["reason"] = "Plan only; no subprocess executed; measurement binding refused: " + binding_error
            continue
        if not execute:
            item["reason"] = "Plan only; no subprocess executed"
            continue
        if name == "measurement-regressions":
            failed = [dependency for dependency in definition.get("requires", [])
                      if results[dependency]["status"] != "PASS"]
            if failed:
                item.update(status="BLOCKED", reason="Required regressions did not pass: " + ", ".join(failed))
                continue
            try:
                final = measurement_binding(root, measurement_before, measurement_before_sha256,
                                            regression_matrix, regression_matrix_sha256)
                if final != binding:
                    raise ValueError("MEASUREMENT_SOURCE_CHANGED")
            except (OSError, ValueError, TypeError, KeyError) as error:
                item.update(status="FAIL", reason="Measurement binding changed: " + str(error))
                continue
            required = list(definition.get("requires", []))
            # A suite can also run because the caller selected it; only "required" is binding evidence.
            ran = [name for name in ("python-tests", "node-tests") if results[name].get("invoked", False)]
            binding = {**binding, "status": "PASS", "regressions_required": required, "regressions_run": ran,
                       "regression_receipts": {
                           dependency: results[dependency]["receipt"] for dependency in required}}
            if required:
                reason = "Pinned software change binding and required checks passed"
            elif ran:
                reason = ("No in-scope software change since the pinned baseline; no regressions were required. "
                          "Separately selected checks ran but are not binding evidence: " + ", ".join(ran))
            else:
                reason = ("No in-scope software change since the pinned baseline; "
                          "no regressions were required or run")
            item.update(status="PASS", binding=binding, reason=reason)
            continue
        if not definition["command"]:
            item.update(status="BLOCKED", reason=definition["reason"])
            continue
        failed_dependencies = [dependency for dependency in definition.get("requires", [])
                               if results[dependency]["status"] != "PASS"]
        if failed_dependencies:
            item.update(status="BLOCKED", reason="Prerequisite did not pass: " + ", ".join(failed_dependencies))
            continue
        required_path = definition.get("requires_path")
        if required_path is not None and not Path(required_path).is_dir():
            item.update(status="BLOCKED", reason=f"Audit target directory is unavailable: {required_path}")
            continue
        probe = None
        tool_version = runtime_version if item["tool"] == "scientific-python" else None
        check_environment = {**environment, **definition.get("env", {})}
        if definition.get("version_command"):
            probe = {"argv": definition["version_command"]}
            try:
                version = runner(definition["version_command"], cwd=root, env=check_environment,
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=60, check=False)
            except (OSError, subprocess.TimeoutExpired) as error:
                item.update(status="BLOCKED", reason=f"Required tool is not runnable: {error}", version_probe=probe)
                continue
            probe.update(exit_code=version.returncode, output=(version.stdout + version.stderr).strip()[-2000:])
            if version.returncode:
                item.update(status="BLOCKED", reason="Required tool version probe failed; tool unavailable",
                            version_probe=probe)
                continue
            tool_version = version.stdout.strip()
        started = datetime.datetime.now(datetime.UTC).isoformat()
        clock = time.perf_counter()
        try:
            completed = runner(definition["command"], cwd=root, env=check_environment,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout, check=False)
        except (FileNotFoundError, PermissionError, OSError) as error:
            item.update(status="BLOCKED", reason=f"Cannot invoke required tool: {error}")
            continue
        except subprocess.TimeoutExpired as error:
            item.update(status="FAIL", invoked=True, reason=f"Check exceeded {error.timeout} seconds")
            continue
        duration = round(time.perf_counter() - clock, 3)
        log_path = receipts_dir / f"{name}.log"
        log_sha256 = _write_log(log_path, definition["command"], root, completed, probe)
        stdout, stderr = completed.stdout or "", completed.stderr or ""
        item.update(invoked=True, exit_code=completed.returncode, stdout=stdout[-OUTPUT_TAIL:], stderr=stderr[-OUTPUT_TAIL:],
                    output_truncated=len(stdout) > OUTPUT_TAIL or len(stderr) > OUTPUT_TAIL)
        item["receipt"] = {"tool": item["tool"], "tool_path": definition["command"][0],
                           "tool_resolved": shutil.which(definition["command"][0]) or definition["command"][0],
                           "tool_version": tool_version, "argv": definition["command"], "cwd": str(root),
                           "exit_code": completed.returncode, "duration_s": duration, "started_utc": started,
                           "log_path": str(log_path), "log_sha256": log_sha256}
        if completed.returncode:
            item.update(status="FAIL", reason="Invoked check returned a nonzero exit")
            continue
        if name == "python-runtime":
            try:
                observed = json.loads(completed.stdout)
                version = observed["python"]
                valid = (observed.get("status") == "PASS" and len(version) >= 2
                         and version[0] == 3 and 10 <= version[1] <= 13
                         and bool(observed.get("opensim")) and bool(observed.get("Pose2Sim"))
                         and observed.get("path_is_junction") is True
                         and observed.get("hashlib_file_digest") is True)
                item["observed_runtime"] = observed
            except (ValueError, KeyError, TypeError):
                item.update(status="FAIL", reason="Runtime probe did not return the required structured evidence")
                continue
            if not valid:
                item.update(status="BLOCKED", reason="Python 3.10-3.13, importable OpenSim/Pose2Sim and required Path/hashlib APIs must all be available")
                continue
            runtime_version = "Python " + ".".join(str(part) for part in version)
            item["receipt"]["tool_version"] = runtime_version
        item.update(status="PASS", reason="Selected command completed with exit 0")
        if name in ("python-tests", "node-tests"):
            item["limitations"] = "Inspect the captured test output for skipped coverage; command success is not physical or clinical acceptance."
    statuses = [item["status"] for item in results.values() if item["selected"]]
    status = ("FAIL" if "FAIL" in statuses else "BLOCKED" if "BLOCKED" in statuses
              else "NOT_RUN" if not statuses or "NOT_RUN" in statuses else "PASS")
    report = {
        "schema": "kinelab.quality-checks.v2", "status": status,
        "scope": "Selected local software checks only",
        "mode": "execute" if execute else "plan",
        "root": str(root),
        "interpreters": {"scientific_python": python_executable, "tools_python": tools_python},
        "receipts_dir": str(receipts_dir) if execute else None,
        "isolated_data_root": str(isolated_data_root),
        "checks": list(results.values()),
        "measurement_binding": binding,
        "limitations": [
            "Dependency consistency is not a vulnerability, license or lock-install reproducibility audit.",
            "pip-audit covers installed Python distributions in the audited site-packages only.",
            "npm audit (npm-advisories) checks the existing viewer/package-lock.json metadata only; it neither installs nor fixes, and any reported advisory fails the gate.",
            "workflow-syntax parses .github/workflows/quality.yml with PyYAML from the tools interpreter and checks workflow structure; it is BLOCKED when PyYAML is absent and is not a GitHub Actions run.",
            "requirements.lock.txt is an environment inventory, not a verified offline installer.",
            lint_config_note(root),
            "No browser, clean-machine, hardware, physical or clinical acceptance is established.",
            "No remote CI invocation is established by this local report.",
        ],
    }
    if execute:
        with (receipts_dir / "report.json").open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
    return report


def validate_workflow_file(path: Path) -> int:
    # PyYAML is an optional parser that neither interpreter currently provides, so it is
    # resolved at run time instead of being a static import.
    try:
        yaml = importlib.import_module("yaml")
    except ImportError as error:
        print(json.dumps({"valid": False, "status": "BLOCKED", "reason": f"PyYAML unavailable: {error}"}))
        return 2
    verdict = validate_workflow_document(path.read_text(encoding="utf-8"), yaml.safe_load, (yaml.YAMLError,))
    print(json.dumps({"path": str(path), **verdict}))
    return 0 if verdict["valid"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run", action="store_true", help="Execute the explicitly selected checks; otherwise only print a NOT_RUN plan")
    parser.add_argument("--checks", nargs="+", choices=CHECK_IDS)
    parser.add_argument("--python", dest="python_executable", help="Scientific runtime interpreter (default <root>/.venv)")
    parser.add_argument("--tools-python", dest="tools_python", help="Developer tooling interpreter providing ruff, mypy and pip-audit")
    parser.add_argument("--audit-site-packages", type=Path, help="site-packages directory audited by pip-audit (default: scientific runtime)")
    parser.add_argument("--receipts-dir", type=Path, help="New receipts directory; an existing directory is never reused")
    parser.add_argument("--measurement-before", type=Path, help="Explicit complete prechange software inventory")
    parser.add_argument("--measurement-before-sha256", help="SHA-256 pin of the accepted prechange inventory")
    parser.add_argument("--regression-matrix", type=Path, help="Versioned local software regression matrix")
    parser.add_argument("--regression-matrix-sha256", help="SHA-256 pin of the selected matrix")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--out", type=Path, help="New JSON evidence file; an existing file is never overwritten")
    parser.add_argument("--validate-workflow", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.validate_workflow:
        return validate_workflow_file(args.validate_workflow)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.run and not args.checks:
        print(json.dumps({"schema": "kinelab.quality-checks.v2", "status": "BLOCKED",
                          "reason": "--run requires an explicit bounded --checks selection", "checks": []}))
        return 2
    try:
        report = run_checks(args.root, selected=args.checks, execute=args.run,
                            python_executable=args.python_executable, tools_python=args.tools_python,
                            audit_site_packages=args.audit_site_packages, receipts_dir=args.receipts_dir,
                            timeout=args.timeout, measurement_before=args.measurement_before,
                            measurement_before_sha256=args.measurement_before_sha256,
                            regression_matrix=args.regression_matrix,
                            regression_matrix_sha256=args.regression_matrix_sha256)
    except (OSError, ValueError, KeyError) as error:
        report = {"schema": "kinelab.quality-checks.v2", "status": "BLOCKED",
                  "reason": "Required source/configuration unavailable: " + str(error), "checks": []}
    output = json.dumps(report, indent=2)
    if args.out:
        try:
            with args.out.open("x", encoding="utf-8") as stream:
                stream.write(output + "\n")
        except OSError as error:
            print(json.dumps({"status": "BLOCKED", "reason": "Evidence write refused: " + str(error)}))
            return 2
    print(output)
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2, "NOT_RUN": 3}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
