"""Quality gate contracts use generated roots and controlled subprocess results."""
import contextlib
import fnmatch
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import check_quality
from tools.check_quality import run_checks


class QualityGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "viewer").mkdir()
        (self.root / "viewer" / "package.json").write_text(json.dumps({"scripts": {
            "test": "node --test src/*.test.js", "build": "vite build",
            "build:cloud": "vite build --mode cloud"}}), encoding="utf-8")
        (self.root / "requirements.lock.txt").write_text("Pose2Sim==0.10.49\n", encoding="utf-8")
        self.calls = []

    def runner(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if "import opensim" in " ".join(command):
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                "status": "PASS", "python": [3, 13, 16], "opensim": "4.6",
                "Pose2Sim": "0.10.49", "path_is_junction": True,
                "hashlib_file_digest": True}), stderr="")
        return SimpleNamespace(returncode=0, stdout="generated check completed\n", stderr="")

    def run_gate(self, checks, **kwargs):
        return run_checks(self.root, selected=checks, runner=self.runner,
                          python_executable="generated-python.exe", node="node", npm="npm.cmd", **kwargs)

    def test_plan_never_executes_and_never_reports_pass(self):
        result = self.run_gate(["python-tests", "node-tests", "cloud-build", "desktop-build"])
        self.assertEqual(self.calls, [])
        self.assertEqual(result["status"], "NOT_RUN")
        self.assertTrue(all(item["status"] == "NOT_RUN" for item in result["checks"]))

    def test_native_failure_blocks_dependent_tests_but_not_independent_node_check(self):
        def unavailable(command, **kwargs):
            if "import opensim" in " ".join(command):
                raise FileNotFoundError("generated missing Python")
            return self.runner(command, **kwargs)
        result = run_checks(self.root, selected=["python-tests", "node-runtime"], execute=True,
                            runner=unavailable, python_executable="missing.exe", node="node", npm="npm.cmd")
        statuses = {item["id"]: item["status"] for item in result["checks"]}
        self.assertEqual(statuses["python-runtime"], "BLOCKED")
        self.assertEqual(statuses["python-tests"], "BLOCKED")
        self.assertEqual(statuses["node-runtime"], "PASS")
        self.assertFalse(any("unittest" in command for command, _ in self.calls))

    def test_command_failure_and_timeout_are_not_success(self):
        def fail(command, **kwargs):
            if command[-1] == "--version":
                return SimpleNamespace(returncode=1, stdout="", stderr="generated failure")
            return self.runner(command, **kwargs)
        result = run_checks(self.root, selected=["node-runtime"], execute=True, runner=fail, node="node")
        self.assertEqual(result["status"], "FAIL")
        def timeout(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 1)
        result = run_checks(self.root, selected=["node-runtime"], execute=True, runner=timeout, node="node")
        self.assertEqual(result["status"], "FAIL")

    def test_missing_lint_type_and_advisory_configuration_are_explicit(self):
        result = self.run_gate(["lint", "typecheck", "security-advisories"], execute=True)
        self.assertEqual(result["status"], "BLOCKED")
        for item in result["checks"]:
            if item["selected"]:
                self.assertEqual(item["status"], "BLOCKED")
                self.assertTrue(item["reason"])
        self.assertEqual(self.calls, [])

    def test_selected_commands_use_existing_scripts_utf8_and_no_install(self):
        result = self.run_gate(["python-tests", "node-tests", "cloud-build", "desktop-build"], execute=True)
        self.assertEqual(result["status"], "PASS")
        commands = [command for command, _ in self.calls]
        self.assertIn(["npm.cmd", "--prefix", "viewer", "test"], commands)
        receipts = Path(result["receipts_dir"])
        self.assertIn(["npm.cmd", "--prefix", "viewer", "run", "build:cloud", "--", "--outDir",
                       str(receipts / "cloud-build-dist")], commands)
        self.assertIn(["npm.cmd", "--prefix", "viewer", "run", "build", "--", "--outDir",
                       str(receipts / "desktop-build-dist")], commands)
        self.assertIn(["generated-python.exe", "-X", "utf8", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], commands)
        self.assertTrue(all(call["env"]["PYTHONUTF8"] == "1" for _, call in self.calls))
        for _, call in self.calls:
            data_root = Path(call["env"]["KINELAB_CANDIDATE_DATA_ROOT"])
            self.assertEqual(data_root.parent, self.root / "dist")
            self.assertTrue(data_root.name.startswith("quality-fixtures-"))
        self.assertFalse(any("install" in command or "audit" in command for command in commands))
        self.assertEqual(next(item for item in result["checks"] if item["id"] == "security-advisories")["status"], "NOT_RUN")

    def test_unsupported_runtime_or_required_api_cannot_pass(self):
        for mutation in ({"python": [3, 14, 0]}, {"path_is_junction": False}, {"opensim": ""}):
            def incomplete(command, mutation=mutation, **kwargs):
                result = self.runner(command, **kwargs)
                if "import opensim" in " ".join(command):
                    value = json.loads(result.stdout); value.update(mutation)
                    result.stdout = json.dumps(value)
                return result
            result = run_checks(self.root, selected=["python-runtime"], execute=True, runner=incomplete,
                                python_executable="generated-python.exe")
            self.assertEqual(result["status"], "BLOCKED")

    def test_unknown_check_is_rejected_before_subprocess(self):
        with self.assertRaises(ValueError):
            self.run_gate(["silent-skip"])
        self.assertEqual(self.calls, [])

class QualityReceiptAndDevToolTests(unittest.TestCase):
    """Dev tooling is a separate explicit interpreter; every execution leaves a receipt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "viewer").mkdir()
        (self.root / "viewer" / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}}), encoding="utf-8")
        (self.root / "tools").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "module_a.py").write_text("x = 1\n", encoding="utf-8")
        self.site = self.root / "generated-site-packages"
        self.site.mkdir()
        self.receipts = self.root / "receipts-new"
        self.calls = []

    def runner(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="generated-tool 9.9.9\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="generated gate output\n", stderr="")

    def gate(self, checks, runner=None, **kwargs):
        options = {"runner": runner or self.runner, "python_executable": "generated-python.exe",
                   "tools_python": "tools-python.exe", "node": "node", "npm": "npm.cmd",
                   "audit_site_packages": self.site, "receipts_dir": self.receipts}
        options.update(kwargs)
        return run_checks(self.root, selected=checks, **options)

    def test_dev_gates_use_tools_interpreter_and_scientific_runtime_separately(self):
        result = self.gate(["lint", "typecheck", "security-advisories"], execute=True)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["interpreters"], {"scientific_python": "generated-python.exe",
                                                  "tools_python": "tools-python.exe"})
        commands = [command for command, _ in self.calls if command[-1] != "--version"]
        ruff = next(c for c in commands if c[:3] == ["tools-python.exe", "-m", "ruff"])
        self.assertIn("--no-cache", ruff)
        self.assertIn("module_a.py", ruff)
        mypy = next(c for c in commands if c[:3] == ["tools-python.exe", "-m", "mypy"])
        self.assertEqual(mypy[mypy.index("--python-executable") + 1], "generated-python.exe")
        audit = next(c for c in commands if c[:3] == ["tools-python.exe", "-m", "pip_audit"])
        self.assertEqual(audit[audit.index("--path") + 1], str(self.site))
        self.assertFalse(any("--fix" in c or "--ignore-vuln" in c or "install" in c for c in commands))
        self.assertIn("--isolated", ruff)
        self.assertTrue(any("no project configuration" in text for text in result["limitations"]))
        self.assertEqual(mypy[mypy.index("--config-file") + 1], "")

    def test_repository_tool_configuration_is_used_explicitly_when_present(self):
        (self.root / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
        result = self.gate(["lint", "typecheck"], execute=True)
        self.assertTrue(any(str(self.root.resolve() / "pyproject.toml") in text for text in result["limitations"]))
        self.assertFalse(any("no project configuration" in text for text in result["limitations"]))
        commands = [command for command, _ in self.calls if command[-1] != "--version"]
        ruff = next(c for c in commands if "ruff" in c)
        mypy = next(c for c in commands if "mypy" in c)
        self.assertEqual(ruff[ruff.index("--config") + 1], str(self.root.resolve() / "pyproject.toml"))
        self.assertEqual(mypy[mypy.index("--config-file") + 1], str(self.root.resolve() / "pyproject.toml"))
        self.assertNotIn("--isolated", ruff)

    def test_each_executed_gate_writes_hashed_receipt_log(self):
        result = self.gate(["lint"], execute=True)
        item = next(i for i in result["checks"] if i["id"] == "lint")
        receipt = item["receipt"]
        for key in ("tool", "tool_version", "argv", "cwd", "exit_code", "duration_s", "log_path", "log_sha256", "started_utc"):
            self.assertIn(key, receipt)
        self.assertEqual(receipt["tool_version"], "generated-tool 9.9.9")
        self.assertEqual(receipt["cwd"], str(self.root.resolve()))
        self.assertEqual(receipt["exit_code"], 0)
        log = Path(receipt["log_path"])
        self.assertEqual(log.parent, self.receipts)
        self.assertEqual(hashlib.sha256(log.read_bytes()).hexdigest(), receipt["log_sha256"])
        self.assertIn("generated gate output", log.read_text(encoding="utf-8"))
        report = json.loads((self.receipts / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "PASS")

    def test_existing_receipts_directory_is_never_reused(self):
        self.receipts.mkdir()
        with self.assertRaises(ValueError):
            self.gate(["lint"], execute=True)
        self.assertEqual(self.calls, [])

    def test_plan_mode_creates_no_receipts_and_calls_nothing(self):
        result = self.gate(["lint", "typecheck", "security-advisories", "node-tests"])
        self.assertEqual(result["status"], "NOT_RUN")
        self.assertEqual(self.calls, [])
        self.assertFalse(self.receipts.exists())

    def test_missing_tools_interpreter_or_unrunnable_tool_is_blocked(self):
        result = self.gate(["lint", "typecheck", "security-advisories"], execute=True, tools_python=None)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self.calls, [])

        def missing_module(command, **kwargs):
            self.calls.append((command, kwargs))
            return SimpleNamespace(returncode=1, stdout="", stderr="No module named ruff")
        self.receipts = self.root / "receipts-second"
        result = self.gate(["lint"], execute=True, runner=missing_module)
        lint = next(i for i in result["checks"] if i["id"] == "lint")
        self.assertEqual(lint["status"], "BLOCKED")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual([c for c, _ in self.calls if c[-1] != "--version"], [])

    def write_repo_configs(self):
        (self.root / "ruff.toml").write_text("line-length = 120\n", encoding="utf-8")
        (self.root / "mypy.ini").write_text("[mypy]\nfiles = *.py, tools, tests\n", encoding="utf-8")
        (self.root / "agent-harness").mkdir()

    def test_repository_configs_define_lint_and_type_scope(self):
        self.write_repo_configs()
        result = self.gate(["lint", "typecheck", "typecheck-harness"], execute=True)
        self.assertEqual(result["status"], "PASS")
        commands = [command for command, _ in self.calls if command[-1] != "--version"]
        ruff = next(c for c in commands if c[:3] == ["tools-python.exe", "-m", "ruff"])
        self.assertEqual(ruff[ruff.index("--config") + 1], str(self.root.resolve() / "ruff.toml"))
        self.assertEqual(ruff[-1], ".")
        self.assertNotIn("--isolated", ruff)
        mypys = [c for c in commands if c[:3] == ["tools-python.exe", "-m", "mypy"]]
        self.assertEqual(len(mypys), 2)
        scientific = next(c for c in mypys if c[c.index("--python-executable") + 1] == "generated-python.exe")
        harness = next(c for c in mypys if c[c.index("--python-executable") + 1] == "tools-python.exe")
        for command in (scientific, harness):
            self.assertEqual(command[command.index("--config-file") + 1], str(self.root.resolve() / "mypy.ini"))
            self.assertIn("--no-color-output", command)
        # Scope comes from mypy.ini files=, never a second hand-maintained list.
        self.assertFalse({"module_a.py", "tools", "tests", "agent-harness"} & set(scientific))
        self.assertEqual(harness[-1], "agent-harness")
        caches = {c[c.index("--cache-dir") + 1] for c in mypys}
        self.assertEqual(len(caches), 2)
        self.assertTrue(all(Path(cache).parent == self.receipts for cache in caches))

    def test_harness_typecheck_requires_harness_and_tools_interpreter(self):
        result = self.gate(["typecheck-harness"], execute=True)
        self.assertEqual(result["status"], "BLOCKED")
        self.receipts = self.root / "receipts-second"
        self.write_repo_configs()
        result = self.gate(["typecheck-harness"], execute=True, tools_python=None)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self.calls, [])

    def test_frontend_builds_write_unique_explicit_output_directories(self):
        (self.root / "viewer" / "package.json").write_text(json.dumps({"scripts": {
            "test": "node --test", "build": "vite build", "build:cloud": "vite build --mode cloud"}}), encoding="utf-8")
        result = self.gate(["cloud-build", "desktop-build"], execute=True)
        self.assertEqual(result["status"], "PASS")
        outputs = {}
        for command, _ in self.calls:
            if "run" in command:
                self.assertEqual(command[-3:-1], ["--", "--outDir"])
                outputs[command[command.index("run") + 1]] = Path(command[-1])
        self.assertEqual(set(outputs), {"build", "build:cloud"})
        self.assertNotEqual(outputs["build"], outputs["build:cloud"])
        for output in outputs.values():
            self.assertTrue(output.is_absolute())
            self.assertEqual(output.parent, self.receipts)
            self.assertNotEqual(output, self.root / "viewer" / "dist")

    def test_npm_audit_reads_existing_lockfile_metadata_only(self):
        result = self.gate(["npm-advisories"], execute=True)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual([c for c, _ in self.calls if c[-1] != "--version"], [])
        (self.root / "viewer" / "package-lock.json").write_text("{}", encoding="utf-8")
        self.receipts = self.root / "receipts-second"
        self.calls.clear()
        result = self.gate(["npm-advisories"], execute=True)
        self.assertEqual(result["status"], "PASS")
        audit = [(c, k) for c, k in self.calls if "audit" in c]
        self.assertEqual(len(audit), 1)
        command, call = audit[0]
        self.assertEqual(command, ["npm.cmd", "--prefix", "viewer", "audit", "--json", "--package-lock-only"])
        self.assertFalse(any(word in command for word in ("fix", "install", "ci", "--force")))
        self.assertEqual(call["env"]["npm_config_offline"], "false")
        self.assertTrue(any("npm audit" in text for text in result["limitations"]))

    def test_npm_audit_findings_fail(self):
        (self.root / "viewer" / "package-lock.json").write_text("{}", encoding="utf-8")
        def vulnerable(command, **kwargs):
            if "audit" in command:
                return SimpleNamespace(returncode=1, stdout='{"metadata":{"vulnerabilities":{"high":1}}}', stderr="")
            return self.runner(command, **kwargs)
        result = self.gate(["npm-advisories"], execute=True, runner=vulnerable)
        self.assertEqual(result["status"], "FAIL")

    def test_workflow_yaml_is_parsed_by_available_parser_or_blocked(self):
        workflow = self.root / ".github" / "workflows" / "quality.yml"
        result = self.gate(["workflow-syntax"], execute=True)
        self.assertEqual(result["status"], "BLOCKED")
        workflow.parent.mkdir(parents=True)
        workflow.write_text("name: generated\non:\n  workflow_dispatch:\njobs: {}\n", encoding="utf-8")
        self.receipts = self.root / "receipts-second"
        result = self.gate(["workflow-syntax"], execute=True)
        self.assertEqual(result["status"], "PASS")
        command = next(c for c, _ in self.calls if c[-1] != "--version" and str(workflow) in c)
        self.assertEqual(command[0], "tools-python.exe")
        probe = next(c for c, _ in self.calls if c[-1] == "--version")
        self.assertIn("import yaml", " ".join(probe))

        def no_parser(command, **kwargs):
            self.calls.append((command, kwargs))
            if command[-1] == "--version":
                return SimpleNamespace(returncode=1, stdout="", stderr="No module named 'yaml'")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        self.receipts = self.root / "receipts-third"
        self.calls.clear()
        result = self.gate(["workflow-syntax"], execute=True, runner=no_parser)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual([c for c, _ in self.calls if c[-1] != "--version"], [])

    def test_workflow_document_structure_is_validated_after_parsing(self):
        def broken(text):
            raise ValueError("generated parser error")
        valid_jobs = {"a": {"runs-on": "x", "steps": []}}
        # PyYAML (YAML 1.1) loads the bare key "on" as boolean True.
        for loader in (broken, lambda text: ["list"], lambda text: {"name": "x", "on": "push"},
                       lambda text: {"jobs": valid_jobs}, lambda text: {"on": "push", "jobs": {}},
                       lambda text: {True: "push", "jobs": {"a": {"steps": []}}}):
            with self.subTest(loader=loader):
                self.assertFalse(check_quality.validate_workflow_document("generated", loader)["valid"])
        for trigger in ("on", True):
            verdict = check_quality.validate_workflow_document("generated", lambda text, trigger=trigger: {trigger: {}, "jobs": valid_jobs})
            self.assertTrue(verdict["valid"], verdict)

    def test_missing_audit_site_packages_is_blocked(self):
        result = self.gate(["security-advisories"], execute=True, audit_site_packages=self.root / "absent")
        self.assertEqual(result["status"], "BLOCKED")

    def test_gate_findings_fail_overall_and_are_recorded(self):
        def findings(command, **kwargs):
            if command[-1] == "--version":
                return self.runner(command, **kwargs)
            return SimpleNamespace(returncode=1, stdout="module_a.py:1:1: F401 generated finding\n", stderr="")
        result = self.gate(["lint", "node-runtime"], execute=True, runner=findings)
        self.assertEqual(result["status"], "FAIL")
        lint = next(i for i in result["checks"] if i["id"] == "lint")
        self.assertEqual(lint["receipt"]["exit_code"], 1)
        self.assertIn("F401", Path(lint["receipt"]["log_path"]).read_text(encoding="utf-8"))


class QualityCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "viewer").mkdir()
        (self.root / "viewer" / "package.json").write_text(json.dumps({"scripts": {}}), encoding="utf-8")

    def test_run_without_explicit_checks_is_refused_before_any_gate(self):
        with mock.patch.object(check_quality, "run_checks") as gate, \
                mock.patch.object(check_quality.subprocess, "run") as process, \
                contextlib.redirect_stdout(io.StringIO()):
            code = check_quality.main(["--root", str(self.root), "--run"])
        self.assertEqual(code, 2)
        gate.assert_not_called()
        process.assert_not_called()

    def test_cli_plan_never_invokes_subprocess(self):
        output = io.StringIO()
        with mock.patch.object(check_quality.subprocess, "run", side_effect=AssertionError("invoked")) as process, \
                contextlib.redirect_stdout(output):
            code = check_quality.main(["--root", str(self.root), "--checks", "lint", "typecheck",
                                       "security-advisories", "node-tests", "--tools-python", "tools-python.exe"])
        self.assertEqual(code, 3)
        process.assert_not_called()
        report = json.loads(output.getvalue())
        self.assertEqual(report["interpreters"]["tools_python"], "tools-python.exe")
        self.assertEqual(report["status"], "NOT_RUN")

class MeasurementRegressionBindingTests(unittest.TestCase):
    """Generated software observations cannot confer physical acceptance."""

    def setUp(self):
        QualityGateTests.setUp(self)
        (self.root / "geometry.py").write_text("THRESHOLD = 1\n", encoding="utf-8")
        (self.root / "tests" / "fixtures").mkdir(parents=True)
        (self.root / "tests" / "fixtures" / "generated.json").write_text('{"test_only":true}', encoding="utf-8")
        self.before = Path(self.tmp.name).parent / (self.root.name + "-before.json")
        self.matrix = Path(self.tmp.name).parent / (self.root.name + "-matrix.json")
        self.addCleanup(self.before.unlink, missing_ok=True)
        self.addCleanup(self.matrix.unlink, missing_ok=True)
        self.old_files = check_quality._measurement_inventory(self.root)
        self.matrix_document = {
            "schema": "kinelab.software-regression-matrix.v1", "scope": check_quality.MEASUREMENT_SCOPE,
            "rules": [{"path": pattern, "checks": ["python-tests", "node-tests"]}
                      for pattern in ("*.py", "tests/*", "viewer/*", "requirements*.txt")],
            "generated_fixtures": {"tests/fixtures/generated.json": self.old_files["tests/fixtures/generated.json"]},
        }
        self.write_before(self.old_files)
        self.write_matrix()

    runner = QualityGateTests.runner
    run_gate = QualityGateTests.run_gate

    def write_before(self, files):
        data = {"schema": "kinelab.measurement-before.v1", "scope": check_quality.MEASUREMENT_SCOPE,
                "files": files, "inventory_sha256": hashlib.sha256(json.dumps(
                    files, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()}
        self.before.write_text(json.dumps(data), encoding="utf-8")

    def write_matrix(self):
        self.matrix.write_text(json.dumps(self.matrix_document), encoding="utf-8")

    def bound(self, *, execute=False, runner=None, **options):
        return run_checks(self.root, selected=["measurement-regressions"], execute=execute,
                          runner=runner or self.runner, python_executable="generated-python.exe",
                          node="node", npm="npm.cmd",
                             measurement_before=self.before,
                             measurement_before_sha256=hashlib.sha256(self.before.read_bytes()).hexdigest(),
                             regression_matrix=self.matrix,
                             regression_matrix_sha256=hashlib.sha256(self.matrix.read_bytes()).hexdigest(), **options)

    def change(self):
        (self.root / "geometry.py").write_text("THRESHOLD = 2\n", encoding="utf-8")

    def test_measurement_change_runs_both_existing_suites_and_binds_inputs(self):
        self.change()
        result = self.bound(execute=True)
        checks = {item["id"]: item for item in result["checks"]}
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(checks["python-tests"]["status"], "PASS")
        self.assertEqual(checks["node-tests"]["status"], "PASS")
        binding = result["measurement_binding"]
        self.assertEqual(binding["changed"], ["geometry.py"])
        self.assertEqual(binding["before_manifest_sha256"], hashlib.sha256(self.before.read_bytes()).hexdigest())
        self.assertEqual(binding["matrix_sha256"], hashlib.sha256(self.matrix.read_bytes()).hexdigest())
        self.assertEqual(binding["generated_fixtures"], self.matrix_document["generated_fixtures"])
        self.assertEqual(binding["after_files"], check_quality._measurement_inventory(self.root))
        for name in ("python-tests", "node-tests"):
            self.assertEqual(binding["regression_receipts"][name], checks[name]["receipt"])
        self.assertFalse(binding["evidence_verified"])
        for field in ("accuracy", "physical_coverage", "device_latency"):
            self.assertEqual(binding[field], "UNVERIFIED")

    def test_identical_complete_snapshot_does_not_invent_changes_or_run_suites(self):
        result = self.bound(execute=True)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["measurement_binding"]["changed"], [])
        self.assertEqual(result["measurement_binding"]["required_checks"], [])
        self.assertEqual(self.calls, [])

    def test_added_removed_and_renamed_sources_are_all_observed(self):
        (self.root / "geometry.py").rename(self.root / "model.py")
        result = self.bound()
        binding = result["measurement_binding"]
        self.assertEqual(binding["changed"], ["geometry.py", "model.py"])
        self.assertEqual(binding["removed"], ["geometry.py"])
        self.assertEqual(binding["added"], ["model.py"])
        self.assertEqual(self.calls, [])
        self.assertEqual(result["status"], "NOT_RUN")

    def test_unmapped_change_refuses_before_any_runner(self):
        (self.root / "camera.toml").write_text("threshold = 2\n", encoding="utf-8")
        result = self.bound(execute=True)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self.calls, [])
        self.assertIn("MEASUREMENT_CHANGE_UNMAPPED", next(item for item in result["checks"]
                                                        if item["id"] == "measurement-regressions")["reason"])

    def test_missing_evidence_is_blocked_and_never_runs(self):
        result = self.run_gate(["measurement-regressions"], execute=True)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self.calls, [])
        self.assertIn("measurement-regressions", check_quality.CHECK_IDS)

    def test_malformed_stale_and_unsafe_inputs_refuse_before_runner(self):
        self.change()
        for mutation in ("digest", "duplicate", "unsafe", "case-alias", "matrix-rule"):
            with self.subTest(mutation=mutation):
                self.write_before(self.old_files)
                self.write_matrix()
                if mutation == "digest":
                    data = json.loads(self.before.read_text(encoding="utf-8"))
                    data["inventory_sha256"] = "0" * 64
                    self.before.write_text(json.dumps(data), encoding="utf-8")
                elif mutation == "duplicate":
                    self.before.write_text('{"schema":1,"schema":2}', encoding="utf-8")
                elif mutation in ("unsafe", "case-alias"):
                    files = dict(self.old_files)
                    files["../source.py" if mutation == "unsafe" else "GEOMETRY.py"] = "0" * 64
                    self.write_before(files)
                else:
                    self.matrix_document["rules"][0]["checks"] = ["node-runtime"]
                    self.write_matrix()
                result = self.bound(execute=True)
                self.assertEqual(result["status"], "BLOCKED", result)
                self.assertEqual(self.calls, [])

    def test_pin_mismatch_and_changed_generated_fixture_refuse_before_runner(self):
        for mutation in ("pin", "fixture"):
            with self.subTest(mutation=mutation):
                if mutation == "pin":
                    result = self.run_gate(["measurement-regressions"], execute=True,
                                          measurement_before=self.before, measurement_before_sha256="0" * 64,
                                          regression_matrix=self.matrix,
                                          regression_matrix_sha256=hashlib.sha256(self.matrix.read_bytes()).hexdigest())
                else:
                    (self.root / "tests/fixtures/generated.json").write_text("{}", encoding="utf-8")
                    result = self.bound(execute=True)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(self.calls, [])

    def test_failed_prerequisite_or_regression_blocks_binding_acceptance(self):
        self.change()
        for failure in ("runtime", "python-tests", "node-tests"):
            with self.subTest(failure=failure):
                def failed(command, failure=failure, **kwargs):
                    if ((failure == "runtime" and "import opensim" in " ".join(command))
                            or (failure == "python-tests" and "unittest" in command)
                            or (failure == "node-tests" and command[-1] == "test")):
                        return SimpleNamespace(returncode=1, stdout="generated regression failure", stderr="")
                    return self.runner(command, **kwargs)
                result = self.bound(execute=True, runner=failed)
                binding = next(item for item in result["checks"] if item["id"] == "measurement-regressions")
                self.assertEqual(binding["status"], "BLOCKED", result)
                self.assertNotEqual(result["status"], "PASS")

    def test_plan_records_pins_without_subprocess_or_receipts(self):
        self.change()
        result = self.bound()
        self.assertEqual(result["status"], "NOT_RUN")
        self.assertEqual(self.calls, [])
        self.assertEqual(result["measurement_binding"]["required_checks"], ["python-tests", "node-tests"])
        self.assertIsNone(result["receipts_dir"])

    def test_source_mutation_during_regressions_fails_binding(self):
        self.change()
        def mutates(command, **kwargs):
            if command[-1] == "test":
                (self.root / "model.py").write_text("scale = 3\n", encoding="utf-8")
            return self.runner(command, **kwargs)
        result = self.bound(execute=True, runner=mutates)
        binding = next(item for item in result["checks"] if item["id"] == "measurement-regressions")
        self.assertEqual(binding["status"], "FAIL", result)
        self.assertEqual(result["status"], "FAIL")


class MeasurementSelectionAndReasonTests(unittest.TestCase):
    """Selection, reasons and shipped scope must describe exactly what happened."""

    setUp = MeasurementRegressionBindingTests.setUp
    runner = QualityGateTests.runner
    write_before = MeasurementRegressionBindingTests.write_before
    write_matrix = MeasurementRegressionBindingTests.write_matrix
    bound = MeasurementRegressionBindingTests.bound

    def item(self, result, name):
        return next(item for item in result["checks"] if item["id"] == name)

    def test_default_plan_does_not_select_unrequested_measurement_binding(self):
        result = run_checks(self.root, runner=self.runner, python_executable="generated-python.exe",
                            node="node", npm="npm.cmd")
        measurement = self.item(result, "measurement-regressions")
        self.assertFalse(measurement["selected"])
        self.assertEqual(measurement["status"], "NOT_RUN")
        self.assertIsNone(result["measurement_binding"])
        self.assertEqual(result["status"], "NOT_RUN", result)
        self.assertEqual(self.calls, [])

    def test_cli_default_plan_is_not_run_without_measurement_inputs(self):
        output = io.StringIO()
        with mock.patch.object(check_quality.subprocess, "run", side_effect=AssertionError("invoked")) as process, \
                contextlib.redirect_stdout(output):
            code = check_quality.main(["--root", str(self.root)])
        process.assert_not_called()
        self.assertEqual(code, 3, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "NOT_RUN")

    def test_plan_reasons_of_selected_checks_name_the_binding_refusal(self):
        result = run_checks(self.root, selected=["measurement-regressions", "node-runtime"],
                            runner=self.runner, python_executable="generated-python.exe", node="node",
                            npm="npm.cmd", measurement_before=self.before, measurement_before_sha256="0" * 64,
                            regression_matrix=self.matrix,
                            regression_matrix_sha256=hashlib.sha256(self.matrix.read_bytes()).hexdigest())
        node = self.item(result, "node-runtime")
        self.assertTrue(node["selected"])
        self.assertEqual(node["status"], "NOT_RUN")
        self.assertNotEqual(node["reason"], "Unselected check")
        self.assertIn("measurement binding refused: MEASUREMENT_PIN_MISMATCH", node["reason"])
        self.assertEqual(self.item(result, "measurement-regressions")["status"], "BLOCKED")
        self.assertEqual(self.calls, [])

    def test_no_change_pass_states_that_no_regressions_ran(self):
        result = self.bound(execute=True)
        measurement = self.item(result, "measurement-regressions")
        self.assertEqual(measurement["status"], "PASS", result)
        self.assertIn("no regressions were required or run", measurement["reason"])
        self.assertNotIn("checks passed", measurement["reason"])
        self.assertEqual(result["measurement_binding"]["regressions_run"], [])
        self.assertEqual(result["measurement_binding"]["regressions_required"], [])
        self.assertEqual(result["measurement_binding"]["regression_receipts"], {})
        self.assertEqual(self.calls, [])

    def test_no_change_with_explicit_suite_reports_it_ran_but_was_not_required(self):
        result = run_checks(self.root, selected=["measurement-regressions", "python-tests"], execute=True,
                            runner=self.runner, python_executable="generated-python.exe", node="node",
                            npm="npm.cmd", measurement_before=self.before,
                            measurement_before_sha256=hashlib.sha256(self.before.read_bytes()).hexdigest(),
                            regression_matrix=self.matrix,
                            regression_matrix_sha256=hashlib.sha256(self.matrix.read_bytes()).hexdigest())
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(self.item(result, "python-tests")["status"], "PASS")
        self.assertTrue(any("unittest" in command for command, _ in self.calls))
        measurement = self.item(result, "measurement-regressions")
        self.assertNotIn("or run", measurement["reason"])
        self.assertIn("not binding evidence: python-tests", measurement["reason"])
        binding = result["measurement_binding"]
        self.assertEqual(binding["regressions_required"], [])
        self.assertEqual(binding["regressions_run"], ["python-tests"])
        self.assertEqual(binding["regression_receipts"], {})

    def assert_mixed_failure_accounting(self, *, timed_out):
        def failed_suite(command, **kwargs):
            completed = self.runner(command, **kwargs)
            if "unittest" in command:
                if timed_out:
                    raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                return SimpleNamespace(returncode=7, stdout="TEST_ONLY failed suite\n", stderr="")
            return completed

        result = run_checks(self.root, selected=["measurement-regressions", "python-tests"], execute=True,
                            runner=failed_suite, python_executable="generated-python.exe", node="node",
                            npm="npm.cmd", measurement_before=self.before,
                            measurement_before_sha256=hashlib.sha256(self.before.read_bytes()).hexdigest(),
                            regression_matrix=self.matrix,
                            regression_matrix_sha256=hashlib.sha256(self.matrix.read_bytes()).hexdigest())
        self.assertEqual(result["status"], "FAIL", result)
        suite = self.item(result, "python-tests")
        self.assertEqual(suite["status"], "FAIL")
        self.assertTrue(suite.get("invoked", False), "Selected failed suite was invoked")
        self.assertTrue(any("unittest" in command for command, _ in self.calls))
        if timed_out:
            self.assertIn("exceeded", suite["reason"])
            self.assertNotIn("receipt", suite)
        else:
            self.assertEqual(suite["exit_code"], 7)
            self.assertEqual(suite["receipt"]["exit_code"], 7)
        measurement = self.item(result, "measurement-regressions")
        self.assertEqual(measurement["status"], "PASS")
        self.assertNotIn("or run", measurement["reason"])
        self.assertNotIn("checks passed", measurement["reason"])
        self.assertIn("not binding evidence: python-tests", measurement["reason"])
        binding = result["measurement_binding"]
        self.assertEqual(binding["changed"], [])
        self.assertEqual(binding["required_checks"], [])
        self.assertEqual(binding["regressions_required"], [])
        self.assertEqual(binding["regressions_run"], ["python-tests"])
        self.assertEqual(binding["regression_receipts"], {})
        self.assertFalse(self.item(result, "node-tests")["selected"])

    def test_no_change_explicit_nonzero_suite_reports_failed_invocation(self):
        self.assert_mixed_failure_accounting(timed_out=False)

    def test_no_change_explicit_timed_out_suite_reports_failed_invocation(self):
        self.assert_mixed_failure_accounting(timed_out=True)

    def test_changed_binding_records_the_regressions_that_ran(self):
        (self.root / "geometry.py").write_text("THRESHOLD = 2\n", encoding="utf-8")
        result = self.bound(execute=True)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["measurement_binding"]["regressions_run"], ["python-tests", "node-tests"])
        self.assertEqual(result["measurement_binding"]["regressions_required"], ["python-tests", "node-tests"])

    def test_unmapped_refusal_documents_scope_and_deliberate_refusal(self):
        (self.root / "camera.toml").write_text("threshold = 2\n", encoding="utf-8")
        result = self.bound(execute=True)
        reason = self.item(result, "measurement-regressions")["reason"]
        self.assertIn("MEASUREMENT_CHANGE_UNMAPPED: camera.toml", reason)
        self.assertIn(check_quality.MEASUREMENT_SCOPE, reason)
        self.assertIn("refused deliberately", reason)
        self.assertEqual(self.calls, [])

    def test_shipped_matrix_maps_every_inventory_area(self):
        matrix = json.loads(Path(check_quality.__file__).with_name("measurement-regressions.v1.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(matrix["scope"], check_quality.MEASUREMENT_SCOPE)
        samples = ["sample" + suffix for suffix in sorted(check_quality.MEASUREMENT_ROOT_SUFFIXES)]
        samples += [tree + "/nested/sample.dat" for tree in check_quality.MEASUREMENT_TREES]
        samples += ["viewer/" + name for name in sorted(check_quality.MEASUREMENT_VIEWER_FILES)]
        samples.append("viewer/vite.config.js")
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(check_quality._measurement_in_scope(sample))
                self.assertTrue(any(fnmatch.fnmatchcase(sample, rule["path"]) for rule in matrix["rules"]))
        for rule in matrix["rules"]:
            self.assertEqual(rule["checks"], ["python-tests", "node-tests"])


if __name__ == "__main__":
    unittest.main()

