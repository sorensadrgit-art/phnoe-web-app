"""Mounted UI acceptance against generated localhost fixtures; never use a live profile."""
import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_config import is_reparse
from t6_server import make_server
from t6_service import IntegratedService


def _closed_error(code, error):
    # Match the house local_diagnostics exact-type allowlist; never stringify errors.
    labels = {OSError: "OSError", FileNotFoundError: "FileNotFoundError",
              PermissionError: "PermissionError", TimeoutError: "TimeoutError",
              RuntimeError: "RuntimeError", ValueError: "ValueError",
              TypeError: "TypeError", OverflowError: "OverflowError"}
    return {"code": code, "exception_type": labels.get(type(error), "OtherException")}


class _ClosedParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("ARGUMENTS_REJECTED")


def _native_loss_unavailable(args, script, message):
    # Only the exact audit loss command may carry these two closed conditions.
    if (args != ("eval", "--stdin") or type(script) is not str
            or re.fullmatch(r"window\.__avatarAudit\.lose\([1-9][0-9]*\)", script) is None
            or type(message) is not str):
        return False
    # A nonzero JSON-mode CLI can return its failure envelope on stdout.
    if message.startswith("{"):
        try:
            envelope = json.loads(message)
        except (ValueError, TypeError):
            return False
        if type(envelope) is not dict or envelope.get("success") is not False:
            return False
        message = envelope.get("error")
        if type(message) is not str:
            return False
    for prefix in ("page.evaluate: Error: ", "Error: "):
        if message.startswith(prefix):
            message = message[len(prefix):]
            break
    reasons = ("BLOCKED: WEBGL_lose_context unavailable",
               "BLOCKED: native healthy loss precondition")
    return any(message == reason or any(message.startswith(reason + separator)
               for separator in (" ", "\n", "\r\n")) for reason in reasons)


def _closed_console(data):
    messages = data.get("messages", [])
    allowed = ("THREE.WebGLRenderer: Context Lost.", "THREE.WebGLRenderer: Context Restored.")
    return {"observed": len(messages), "safe_messages": [
        {"text": row.get("text")} for row in messages
        if isinstance(row, dict) and row.get("text") in allowed]}


def _closed_page_errors(data):
    return {"count": len(data.get("errors", []))}


class _CleanupFailure(RuntimeError):
    """A callback failed; its caller still attempts the remaining cleanup actions."""


def _cleanup_call(action):
    try:
        return action()
    except Exception as error:
        raise _CleanupFailure("CLEANUP_ACTION_FAILED") from error


def _unlinked_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if ".." in path.parts:
        raise ValueError("Parent traversal is refused for build and evidence paths")
    for part in (*reversed(path.parents), path):
        if is_reparse(part):
            raise ValueError(f"Linked or reparse paths are refused: {part}")
    return path.resolve()


def _frontend_inventory(frontend: Path) -> dict[str, dict[str, object]]:
    inventory: dict[str, dict[str, object]] = {}
    pending = [frontend]
    while pending:
        path = pending.pop()
        before = path.lstat()
        if is_reparse(path):
            raise ValueError(f"Linked or reparse build entries are refused: {path}")
        identity = (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns, before.st_mode)
        entry: dict[str, object] = {"identity": identity}
        if stat.S_ISDIR(before.st_mode):
            entry["kind"] = "directory"
            pending.extend(sorted(path.iterdir(), reverse=True))
        elif stat.S_ISREG(before.st_mode):
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino, opened.st_size) != identity[:3]:
                    raise ValueError(f"Build entry identity changed before reading: {path}")
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                closed = os.fstat(stream.fileno())
                if (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns,
                    closed.st_ctime_ns, closed.st_mode) != (
                        opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns,
                        opened.st_ctime_ns, opened.st_mode):
                    raise ValueError(f"Build entry changed while reading: {path}")
            entry.update(kind="file", sha256=digest.hexdigest())
        else:
            raise ValueError(f"Build entries must be ordinary files or directories: {path}")
        after = path.lstat()
        if is_reparse(path) or identity != (after.st_dev, after.st_ino, after.st_size,
                                           after.st_mtime_ns, after.st_ctime_ns, after.st_mode):
            raise ValueError(f"Build entry changed during inventory: {path}")
        inventory[path.relative_to(frontend).as_posix()] = entry
    return inventory


def _pinned_agent_browser(executable, expected_sha256):
    """Validate only the explicit CLI entrypoint; never resolve a supplied pin via PATH."""
    if (not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or any(character not in "0123456789abcdef" for character in expected_sha256)):
        raise ValueError("BROWSER_CLI_INVALID_SHA256")
    requested = Path(executable)
    if not requested.is_absolute():
        raise ValueError("BROWSER_CLI_ABSOLUTE_PATH_REQUIRED")
    path = _unlinked_path(requested)
    if path.stem.casefold() != "agent-browser":
        raise ValueError("BROWSER_CLI_NAME_INVALID")
    before = path.stat(follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or is_reparse(path)
            or before.st_size > 256 * 1024 * 1024):
        raise ValueError("BROWSER_CLI_NOT_ORDINARY_BOUNDED_FILE")
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if identity(before) != identity(opened):
            raise ValueError("BROWSER_CLI_CHANGED")
        total = 0
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            total += len(block)
            if total > 256 * 1024 * 1024:
                raise ValueError("BROWSER_CLI_NOT_ORDINARY_BOUNDED_FILE")
            digest.update(block)
        finished = os.fstat(stream.fileno())
    after_path = _unlinked_path(requested)
    after = after_path.stat(follow_symlinks=False)
    if (after_path != path or identity(before) != identity(after)
            or before.st_ctime_ns != after.st_ctime_ns
            or identity(opened) != identity(finished)
            or opened.st_ctime_ns != finished.st_ctime_ns):
        raise ValueError("BROWSER_CLI_CHANGED")
    if digest.hexdigest() != expected_sha256:
        raise ValueError("BROWSER_CLI_HASH_MISMATCH")
    return str(path)


def _prepare_default_comparison_fixture(service):
    """Generated contracts; only TEST_ONLY normalized clips decoded, no native measurement."""
    from datetime import UTC, datetime
    from unittest.mock import patch

    from export_motion import motion
    from session_contract import ROLES
    from session_metadata_revision import read_metadata_state
    from setup_project import register_captures

    tests_path = str(ROOT / "tests")
    sys.path.insert(0, tests_path)
    try:
        from native_evidence_fixture import complete_native_fixture
        from test_export_motion import trc_text
    finally:
        sys.path.remove(tests_path)
    metadata = {
        "schema": "kinelab.session-metadata.v1",
        "subject_id": "sub-" + uuid4().hex, "operator_id": "op-" + uuid4().hex,
        "task_id": "TEST_ONLY-isolation", "protocol_id": "TEST_ONLY-generated",
        "protocol_version": "TEST_ONLY-v1", "laterality": "not_applicable",
        "confirmed": True, "confirmed_at": datetime.now(UTC).isoformat(),
    }
    session_ids = ("synthetic-race-d", "synthetic-race-e")
    times = tuple(index / 30 for index in (1, 2, 3))
    for sid in session_ids:
        folder = service.index.projects_root / sid
        (folder / "raw").mkdir(parents=True, exist_ok=False)
        (folder / "Config.toml").write_text(
            "# TEST_ONLY generated contract; no measured data\n[project]\n", encoding="utf-8")
        for role in ROLES:
            (folder / "raw" / (role + ".mp4")).write_bytes(
                ("TEST_ONLY non-codec bytes " + sid + " " + role).encode())
        register_captures(folder, sid, kind="demo", metadata=metadata)
        mot = ("TEST_ONLY generated\nnRows=3\nnColumns=2\ninDegrees=yes\nendheader\n"
               "time knee_angle_r\n" + "".join(
                   f"{stamp} {angle}\n" for stamp, angle in zip(times, (0.2, 0.8, 0.5))))
        manifest, _filtered, mot_path = complete_native_fixture(
            folder, trc_text(times=times), mot, through="kinematics")
        augmented = folder / "pose-3d/fixture_filt_LSTM.trc"
        augmented.write_text(augmented.read_text(encoding="utf-8").replace(
            "factory_trial.trc", "TEST_ONLY-generated-augmented.trc", 1), encoding="utf-8")
        run = json.loads(manifest.read_text(encoding="utf-8"))
        run["stages"][6]["artifacts"][0]["sha256"] = hashlib.sha256(augmented.read_bytes()).hexdigest()
        run["stages"][7]["quality"]["consumed_trc"] = dict(run["stages"][6]["artifacts"][0])
        manifest.write_text(json.dumps(run, allow_nan=False), encoding="utf-8")
        (folder / "exports").mkdir()
        exported = motion(augmented, mot_path, run_manifest=manifest)
        (folder / "exports/generated.motion.json").write_text(
            json.dumps(exported, allow_nan=False), encoding="utf-8")
    # Record no dimensions/durations for generated non-codec bytes. Later indexing
    # preserves these first immutable baselines and does not probe them again.
    with patch("session_index.probe_clip", side_effect=ValueError("TEST_ONLY_NONCODEC_SOURCE")):
        service.index.reindex()
    rows = {row["id"]: row for row in service.sessions()}
    bindings = {}
    for sid in session_ids:
        state = read_metadata_state(service.index, sid)
        assert state["status"] == "AVAILABLE" and state["head"] is None, state
        assert rows[sid]["research_source_revision"]["status"] == "AVAILABLE", rows[sid]
        assert service.index.get_passport(sid)["is_test_only"] is True
        bindings[sid] = {"metadata_context_sha256": state["context_sha256"],
                         "origin": state["origin"],
                         "source_observation": rows[sid]["research_source_revision"]}
    return {"evidence_kind": "GENERATED_CONTRACT_FIXTURE_ONLY", "test_only": True,
            "source_video_decoded": False, "normalized_test_only_video_decoded": True,
            "native_compute": "NOT_PERFORMED",
            "physical_accuracy_verified": False, "clinical_validation": "UNVERIFIED",
            "confirmation": "Fixture-only schema confirmation; no human or identity verification",
            "sessions": bindings}


def verify(output, scenario=None, *, frontend_dist=None, fixture=None, fixture_cleanup=None, agent_browser_executable=None, agent_browser_sha256=None):
    frontend = _unlinked_path(frontend_dist if frontend_dist is not None else ROOT / "viewer/dist")
    evidence_root = _unlinked_path(ROOT / "dist")
    output = _unlinked_path(output)
    if frontend_dist is not None and (frontend == evidence_root or not frontend.is_relative_to(evidence_root)):
        raise ValueError("Explicit frontend build must be a dedicated directory under this workspace's dist")
    if output == evidence_root or not output.is_relative_to(evidence_root):
        raise ValueError("Evidence output must be a dedicated directory under this workspace's dist")
    if output.is_relative_to(frontend) or frontend.is_relative_to(output):
        raise ValueError("Frontend build and evidence output must not overlap")
    if not frontend.is_dir() or is_reparse(frontend / "index.html") or not (frontend / "index.html").is_file():
        raise ValueError("Selected frontend build requires an ordinary index.html; no build fallback is used")
    build_before = _frontend_inventory(frontend)
    if (agent_browser_executable is None) != (agent_browser_sha256 is None):
        raise ValueError("BROWSER_CLI_PATH_AND_SHA_REQUIRED_TOGETHER")
    cli = (_pinned_agent_browser(agent_browser_executable, agent_browser_sha256)
           if agent_browser_executable is not None else shutil.which("agent-browser"))
    if not cli:
        raise RuntimeError("BLOCKED: installed agent-browser CLI required")
    output.mkdir(parents=True, exist_ok=False)
    browser_session = "kinelab-isolation-" + uuid4().hex[:10]
    receipt = {"fixture": "generated software fixtures only", "checks": {},
               "build_inventory_before": build_before,
               "build_sha256": {name: item["sha256"] for name, item in build_before.items()
                                if item["kind"] == "file"}}
    temporary = tempfile.TemporaryDirectory(prefix="kinelab-browser-fixture-")
    service = server = thread = init = None
    browser_started = False
    try:
        runtime = Path(temporary.name)
        projects, samples = runtime / "projects", runtime / "samples"
        projects.mkdir(); samples.mkdir()
        service = IntegratedService(projects)
        for suffix in ("a", "b", "c"):
            service.create_session("synthetic-race-" + suffix)
        if scenario is None:
            receipt["comparison_fixture"] = _prepare_default_comparison_fixture(service)
        if fixture is not None:
            receipt['fixture_context'] = fixture(service)
        token = secrets.token_hex(32)
        server = make_server(service, token=token, dist=frontend, samples=samples, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        init = runtime / "init.js"
        init.write_text("""localStorage.clear();
localStorage.setItem('kinelab_active_tab','overview');
localStorage.setItem('kinelab_selected_session','synthetic-race-a');
localStorage.setItem('kinelab_t6_token','TOKEN');
window.__holdA=true;window.__heldA=[];window.__heldCompare=[];
window.__releaseA=()=>{window.__holdA=false;window.__heldA.splice(0).forEach(r=>r());};
window.__releaseCompare=()=>{window.__holdCompare=false;window.__heldCompare.splice(0).forEach(r=>r());};
window.__cameraRequests=0;
Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[],getUserMedia:async()=>{
 window.__cameraRequests++;if(window.__testCamera)return window.__testCamera();
 throw new DOMException('Device access forbidden in synthetic fixture','NotAllowedError');}}});
const originalFetch=window.fetch.bind(window);
window.fetch=async(input,options)=>{
 const url=String(input);let response=await originalFetch(input,options);
 if(window.__wrongB && url.endsWith('/sessions/synthetic-race-b/passport')){
  const body=await response.json();body.session_id='synthetic-race-a';
  response=new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
 }
 if(window.__holdA&&url.includes('/sessions/synthetic-race-a'))await new Promise(r=>window.__heldA.push(r));
 if(window.__holdCompare&&url.includes('/api/v1/compare?'))await new Promise(r=>window.__heldCompare.push(r));
 return response;
};
""".replace("TOKEN", token), encoding="utf-8")
        if scenario:
            init.write_text(init.read_text(encoding="utf-8").replace("'overview'", "'live'").replace("window.__holdA=true", "window.__holdA=false"), encoding="utf-8")
        config = runtime / "config.json"
        config.write_text("{}")
        prefix = [cli, "--session", browser_session, "--config", str(config), "--json",
                  "--download-path", str(runtime / 'downloads')]

        def browser(*args, script=None):
            nonlocal browser_started
            if 'open' in args:
                browser_started = True
            if agent_browser_executable is not None:
                _pinned_agent_browser(cli, agent_browser_sha256)
            result = subprocess.run([*prefix, *args], input=script, capture_output=True,
                                    text=True, encoding="utf-8", timeout=35, check=False)
            if result.returncode:
                if _native_loss_unavailable(args, script, result.stderr or result.stdout):
                    raise RuntimeError("BROWSER_NATIVE_LOSS_UNAVAILABLE")
                raise RuntimeError("BROWSER_CLI_NONZERO_EXIT")
            payload = json.loads(result.stdout)
            if not payload.get("success"):
                if _native_loss_unavailable(args, script, payload.get("error")):
                    raise RuntimeError("BROWSER_NATIVE_LOSS_UNAVAILABLE")
                raise RuntimeError("BROWSER_CLI_COMMAND_FAILED")
            return payload.get("data", {})

        def evaluate(script):
            return browser("eval", "--stdin", script=script).get("result")

        def wait_for(expression):
            return evaluate("(async()=>{const deadline=performance.now()+10000;while(!(" + expression +
                ")&&performance.now()<deadline)await new Promise(r=>setTimeout(r,20));if(!(" + expression +
                "))throw Error('Acceptance condition timed out');return true;})()")

        def select(suffix):
            browser("select", '[aria-label="Select active session"]', "synthetic-race-" + suffix)

        def passport(suffix):
            wait_for("document.querySelector('.uw-passport code')?.textContent==='projects/synthetic-race-" + suffix + "/raw/'")

        def navigate(name):
            browser("snapshot", "-i")
            browser("find", "role", "button", "click", "--name", name)

        restart_count = 0

        def reopen():
            nonlocal restart_count
            browser("close")
            restart_count += 1
            prefix[2] = f"{browser_session}-restart-{restart_count}"
            browser("--allowed-domains", "127.0.0.1", "open", origin, "--init-script", str(init))

        with urlopen(origin, timeout=5) as response:
            assert response.status == 200 and b'<!doctype html>' in response.read(512).lower()
        receipt['runtime'] = {'http_ready': True}
        browser("--allowed-domains", "127.0.0.1", "open", origin, "--init-script", str(init))
        browser("snapshot", "-i")
        if not evaluate("!!document.querySelector('[aria-label=\"Select active session\"]')"):
            raise RuntimeError("Desktop build required: run npm --prefix viewer run build after build:cloud")
        if scenario:
            scenario(browser, evaluate, wait_for, service, output, receipt["checks"], reopen)
        else:
            wait_for("window.__heldA.length>=5")
            select("b"); passport("b")
            state = evaluate("""(async()=>{window.__releaseA();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
 return {selected:document.querySelector('[aria-label="Select active session"]').value,
 passport:document.querySelector('.uw-passport code')?.textContent};})()""")
            assert state == {"selected": "synthetic-race-b", "passport": "projects/synthetic-race-b/raw/"}, state
            receipt["checks"]["delayed_A_cannot_replace_B"] = state

            evaluate("window.__wrongB=true;")
            select("a"); passport("a"); select("b")
            wait_for("document.body.textContent.includes('Session identity mismatch')")
            assert evaluate("document.querySelector('.uw-passport code')===null")
            receipt["checks"]["mismatched_response_identity_refused"] = True
            evaluate("window.__wrongB=false;")
            select("a"); passport("a"); select("b"); passport("b")

            evaluate("window.__holdA=true;window.__heldA=[];")
            select("a")
            count = evaluate("(async()=>{await new Promise(r=>setTimeout(r,7800));const n=window.__heldA.length;window.__releaseA();return n;})()")
            assert count == 5, f"Overlapping selected-session requests: {count}"
            receipt["checks"]["slow_poll_bounded_to_one_group"] = count
            select("b"); passport("b")

            navigate("3D Motion Synchronized skeleton viewer")
            wait_for("document.querySelector('.chip')?.textContent.includes('UNAVAILABLE')")
            wait_for("document.body.textContent.includes('Cannot load motion for synthetic-race-b')")
            receipt["checks"]["empty_selected_session_never_falls_back_to_demo"] = True
            browser("screenshot", str(output / "unavailable-motion.png"))

            navigate("Reports Local evidence and exports")
            select("d")
            browser("snapshot", "-i")
            browser("select", ".uw-report-studio .uw-form-inline select", "synthetic-race-e")
            evaluate("window.__holdCompare=true;")
            browser("find", "role", "button", "click", "--name", "Compare", "--exact")
            wait_for("window.__heldCompare.length===1")
            select("c")
            stale = evaluate("""(async()=>{window.__releaseCompare();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
 return {selected:document.querySelector('[aria-label="Select active session"]').value,
 result:document.querySelector('.uw-compare-result')?.textContent||null};})()""")
            assert stale == {"selected": "synthetic-race-c", "result": None}, stale
            receipt["checks"]["late_comparison_cannot_cross_session"] = stale
            browser("screenshot", str(output / "session-isolation.png"))
        receipt["console"] = _closed_console(browser("console"))
        receipt["page_errors"] = _closed_page_errors(browser("errors"))
        assert receipt["page_errors"]["count"] == 0, "PAGE_ERRORS_OBSERVED"
        receipt["status"] = "PASS"
    except Exception as error:
        receipt["status"] = "FAIL"
        receipt["error"] = _closed_error("VERIFICATION_FAILED", error)
        if browser_started:
            try:
                receipt["console"] = _closed_console(browser("console"))
                receipt["page_errors"] = _closed_page_errors(browser("errors"))
            except Exception as diagnostic_error:
                receipt["diagnostics_error"] = _closed_error("DIAGNOSTICS_UNAVAILABLE", diagnostic_error)
        raise
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_errors = []
        actions = []
        if browser_started:
            actions.append(("browser.close", lambda: browser("close")))
        if server is not None and thread is not None and thread.is_alive():
            actions.append(("server.shutdown", server.shutdown))
        if server is not None:
            actions.append(("server.server_close", server.server_close))
        if thread is not None and thread.ident is not None:
            def join_thread():
                thread.join(5)
                if thread.is_alive():
                    raise RuntimeError("server thread still alive after 5-second join")
            actions.append(("thread.join", join_thread))
        if service is not None:
            if fixture_cleanup is not None:
                actions.append(("fixture.cleanup", lambda: fixture_cleanup(service)))
            actions.append(("service.close", service.close))
        if init is not None:
            actions.append(("init.unlink", lambda: init.unlink(missing_ok=True)))
        actions.append(("temporary.cleanup", temporary.cleanup))
        for name, close in actions:
            try:
                _cleanup_call(close)
            except _CleanupFailure as cleanup_error:
                cleanup_errors.append({"action": name, **_closed_error("CLEANUP_ACTION_FAILED", cleanup_error.__cause__)})
        build_error = None
        try:
            receipt["build_inventory_after"] = _frontend_inventory(_unlinked_path(frontend))
            if receipt["build_inventory_after"] != build_before:
                build_error = "Selected frontend build changed during verification"
        except (OSError, ValueError) as error:
            build_error = _closed_error("BUILD_REVALIDATION_FAILED", error)
        if build_error is not None:
            receipt["build_error"] = build_error
        if primary_error is not None or cleanup_errors or build_error is not None:
            receipt["status"] = "FAIL"
        if primary_error is not None:
            receipt.setdefault("error", _closed_error("VERIFICATION_FAILED", primary_error))
        if cleanup_errors:
            receipt["cleanup_errors"] = cleanup_errors
        try:
            _cleanup_call(
                lambda: (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            )
        except _CleanupFailure as receipt_error:
            cleanup_errors.append({"action": "receipt.write", **_closed_error("RECEIPT_WRITE_FAILED", receipt_error.__cause__)})
            receipt["cleanup_errors"] = cleanup_errors
            receipt["status"] = "FAIL"
        if primary_error is None and (cleanup_errors or build_error is not None):
            raise RuntimeError("CLEANUP_OR_BUILD_FAILED")
    print(json.dumps({"status": receipt["status"], "checks": len(receipt["checks"])}))


def main():
    try:
        parser = _ClosedParser(description=__doc__)
        parser.add_argument("--out", type=Path, required=True)
        parser.add_argument("--frontend-dist", type=Path)
        parser.add_argument("--agent-browser-executable", type=Path)
        parser.add_argument("--agent-browser-sha256")
        parser.add_argument("--recording", action="store_true")
        parser.add_argument("--reports", action="store_true")
        parser.add_argument("--evidence-export", action="store_true")
        parser.add_argument("--pose", action="store_true")
        parser.add_argument("--recording-lifecycle", choices=("empty-start", "retry-clock", "batching", "duration"))
        args = parser.parse_args()
        if args.evidence_export and (args.agent_browser_executable is None or args.agent_browser_sha256 is None):
            parser.error("--evidence-export requires explicit --agent-browser-executable and --agent-browser-sha256")
        if args.evidence_export:
            from tools import verify_evidence_export_browser
            verify(args.out, verify_evidence_export_browser.run_checks, frontend_dist=args.frontend_dist, agent_browser_executable=args.agent_browser_executable, agent_browser_sha256=args.agent_browser_sha256,
                   fixture=verify_evidence_export_browser.prepare_fixture,
                   fixture_cleanup=verify_evidence_export_browser.cleanup_fixture)
        elif args.pose:
            from tools import verify_pose_browser
            verify(args.out, verify_pose_browser.run_checks, frontend_dist=args.frontend_dist, agent_browser_executable=args.agent_browser_executable, agent_browser_sha256=args.agent_browser_sha256)
        elif args.reports:
            from tools import verify_report_browser
            verify(args.out, verify_report_browser.run_checks, frontend_dist=args.frontend_dist, agent_browser_executable=args.agent_browser_executable, agent_browser_sha256=args.agent_browser_sha256,
                   fixture=verify_report_browser.prepare_fixture)
        elif args.recording_lifecycle:
            from functools import partial

            from tools import verify_recording_lifecycle_browser
            verify(args.out, partial(verify_recording_lifecycle_browser.run_checks, case=args.recording_lifecycle),
                   frontend_dist=args.frontend_dist, agent_browser_executable=args.agent_browser_executable, agent_browser_sha256=args.agent_browser_sha256)
        elif args.recording:
            from tools import verify_recording_browser
            verify(args.out, verify_recording_browser.run_checks, frontend_dist=args.frontend_dist, agent_browser_executable=args.agent_browser_executable, agent_browser_sha256=args.agent_browser_sha256)
        else:
            verify(args.out, frontend_dist=args.frontend_dist, agent_browser_executable=args.agent_browser_executable, agent_browser_sha256=args.agent_browser_sha256)
    except Exception as error:
        print(json.dumps({"status": "FAIL", **_closed_error("BROWSER_VERIFY_FAILED", error)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
