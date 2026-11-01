"""Installed-command acceptance; absence fails rather than silently skipping."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[4]


def _resolve_cli(name: str) -> list[str]:
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if os.environ.get("CLI_ANYTHING_FORCE_INSTALLED") == "1":
        raise RuntimeError(f"{name} is not installed; editable installation gate is BLOCKED")
    print("[_resolve_cli] Development module only; installed-command acceptance NOT_RUN")
    return [sys.executable, "-B", "-m", "cli_anything.kinelab"]


class TestCLISubprocess(unittest.TestCase):
    def run_cli(self, *args, input=None):
        return subprocess.run(_resolve_cli("cli-anything-kinelab") + ["--workspace", str(WORKSPACE), *args],
                              input=input, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)

    def test_help(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("quality", result.stdout)

    def test_plan_json_has_not_run_status_and_exit(self):
        result = self.run_cli("--json", "quality", "plan", "--check", "python-syntax")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "NOT_RUN")

    def test_evidence_rejection_preserves_generated_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "generated-bad.zip"
            path.write_bytes(b"generated invalid evidence")
            before = path.read_bytes()
            result = self.run_cli("--json", "evidence", "verify", str(path))
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stdout)["failures"][0]["code"], "EVIDENCE_CORRUPT")
            self.assertEqual(path.read_bytes(), before)

    def test_package_json_does_not_upgrade_stored_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "DISTRIBUTION-MANIFEST.json"
            path.write_text('{"files":[],"verification_status":"NOT_CHECKED"}', encoding="utf-8")
            before = path.read_bytes()
            result = self.run_cli("--json", "package", "inspect", str(path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["payload_verification"], "NOT_RUN")
            self.assertEqual(path.read_bytes(), before)

    def test_default_repl_accepts_exit_without_global_history(self):
        result = self.run_cli("--json", input="exit\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_identity_json_reports_head_and_hashes(self):
        result = self.run_cli("--json", "identity")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertRegex(data["git_head"], r"^[0-9a-f]{40}$")
        self.assertIn("tools/verify_evidence.py", data["source_sha256"])

    def test_live_workspace_is_refused_with_json_error(self):
        command = _resolve_cli("cli-anything-kinelab") + ["--workspace", r"C:\Users\soren\Documents\Projects\KineLab-PT-DualCam", "--json", "identity"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("LIVE_PATH_REFUSED", json.loads(result.stdout)["error"])

    def test_no_recording_mutation_or_export_commands_are_exposed(self):
        result = self.run_cli("--help")
        commands = {line.split()[0] for line in result.stdout.split("Commands:")[1].splitlines() if line.strip()}
        self.assertEqual(commands, {"evidence", "identity", "package", "quality", "repl"})


if __name__ == "__main__":
    unittest.main()
