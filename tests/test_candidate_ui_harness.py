"""Regression and isolation unit tests for tools/verify_candidate_ui.py harness."""
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import verify_candidate_ui as harness


def run_in_fresh_worker(case: unittest.TestCase) -> bool:
    """Run composed browser doubles before any application/Matplotlib import; no native CLI is executed."""
    if os.environ.get("KINELAB_TEST_ONLY_UI_WORKER") == "1":
        return False
    with harness._external_temporary_directory(prefix="test-only-ui-worker-") as tmp:
        owned = Path(tmp)
        environment = {name: os.environ[name] for name in (
            "SYSTEMROOT", "WINDIR", "SystemDrive", "COMSPEC", "ProgramFiles", "ProgramFiles(x86)",
            "ProgramW6432") if name in os.environ}
        for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
                     "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "MPLCONFIGDIR"):
            directory = owned / name
            directory.mkdir()
            environment[name] = str(directory)
        environment.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", KINELAB_TEST_ONLY_UI_WORKER="1", KINELAB_TEST_ONLY_EXTERNAL_TEMP_PARENT=str(owned))
        loader = (
            "import sys,unittest; "
            "sys.path[:0]=[sys.argv[1],sys.argv[1]+'/tests']; "
            "result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName(sys.argv[2])); "
            "raise SystemExit(not result.wasSuccessful())"
        )
        result = subprocess.run([sys.executable, "-I", "-X", "utf8", "-B", "-c", loader, str(ROOT), case.id()],
                                cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
        case.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    return True


class TestCandidateUIHarness(unittest.TestCase):
    def test_harness_guards_refuse_preexisting_paths(self) -> None:
        """Harness must refuse pre-existing log files and non-empty output directories."""
        with tempfile.TemporaryDirectory(prefix="kinelab-harness-guard-") as tmp:
            tmp_path = Path(tmp)
            existing_log = tmp_path / "existing.log"
            existing_log.write_text("old evidence", encoding="utf-8")

            # Must refuse pre-existing log file
            with self.assertRaises(FileExistsError):
                harness.check_path_guards(tmp_path / "out1", existing_log)

            existing_out = tmp_path / "existing_out"
            existing_out.mkdir()
            (existing_out / "evidence.txt").write_text("prior receipt", encoding="utf-8")

            # Must refuse pre-existing non-empty out directory
            with self.assertRaises(FileExistsError):
                harness.check_path_guards(existing_out, tmp_path / "new.log")

    def test_harness_direct_vite_build_target_is_unique(self) -> None:
        """Harness must construct Vite build command targeting an explicit, unique outDir outside viewer/dist."""
        unique_target = ROOT / "dist" / "fullproject-20261028" / "antigravity-R3" / "unique-build"
        cmd = harness.get_vite_build_command(unique_target)

        # Must invoke vite with explicit --outDir and must not use viewer/dist
        self.assertIn("--outDir", cmd)
        outdir_idx = cmd.index("--outDir")
        self.assertEqual(Path(cmd[outdir_idx + 1]).resolve(), unique_target.resolve())
        self.assertNotIn("viewer/dist", " ".join(cmd).replace("\\", "/"))

    def test_check_network_url_valid_and_rejected(self) -> None:
        """Strict network URL validation must accept exact loopback and data/blob URIs while rejecting evasions."""
        port = 8765

        # Valid cases
        valid_loopback, msg1 = harness.check_network_url(f"http://127.0.0.1:{port}/assets/index.js", port)
        self.assertTrue(valid_loopback, msg1)

        valid_data, msg2 = harness.check_network_url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==", port)
        self.assertTrue(valid_data, msg2)

        valid_blob, msg3 = harness.check_network_url(f"blob:http://127.0.0.1:{port}/d6a3f1", port)
        self.assertTrue(valid_blob, msg3)

        # Rejected cases: empty/invalid
        ok_empty, _ = harness.check_network_url("", port)
        self.assertFalse(ok_empty)

        # Rejected cases: scheme (https rejected, only plain http allowed)
        ok_https, msg_https = harness.check_network_url(f"https://127.0.0.1:{port}/resource", port)
        self.assertFalse(ok_https)
        self.assertIn("Forbidden URL scheme", msg_https)

        ok_scheme, msg_scheme = harness.check_network_url(f"ftp://127.0.0.1:{port}/resource", port)
        self.assertFalse(ok_scheme)
        self.assertIn("Forbidden URL scheme", msg_scheme)

        # Rejected cases: blob with foreign origin
        ok_blob_foreign, msg_bf = harness.check_network_url("blob:http://attacker.example/uuid", port)
        self.assertFalse(ok_blob_foreign)
        self.assertIn("Forbidden blob URI origin", msg_bf)

        ok_blob_port, msg_bp = harness.check_network_url(f"blob:http://127.0.0.1:{port + 1}/uuid", port)
        self.assertFalse(ok_blob_port)
        self.assertIn("Forbidden blob URI origin", msg_bp)

        # Rejected cases: malformed port
        ok_malformed_port, msg_mp = harness.check_network_url("http://127.0.0.1:notaport/", port)
        self.assertFalse(ok_malformed_port)
        self.assertIn("Malformed URL port", msg_mp)

        # Rejected cases: subdomain / suffix tricks
        ok_subdomain, msg_sub = harness.check_network_url(f"http://127.0.0.1.attacker.example:{port}/", port)
        self.assertFalse(ok_subdomain)
        self.assertIn("Forbidden non-loopback host", msg_sub)

        # Rejected cases: query string parameter spoofing
        ok_query, msg_q = harness.check_network_url(f"http://attacker.example/?dest=127.0.0.1:{port}", port)
        self.assertFalse(ok_query)
        self.assertIn("Forbidden non-loopback host", msg_q)

        # Rejected cases: localhost name instead of explicit IP
        ok_local, msg_local = harness.check_network_url(f"http://localhost:{port}/", port)
        self.assertFalse(ok_local)
        self.assertIn("Forbidden non-loopback host", msg_local)

        # Rejected cases: port mismatch
        ok_port, msg_port = harness.check_network_url(f"http://127.0.0.1:{port + 1}/", port)
        self.assertFalse(ok_port)
        self.assertIn("Forbidden port mismatch", msg_port)

        # Rejected cases: userinfo tricks in netloc
        ok_userinfo, msg_user = harness.check_network_url(f"http://admin:pass@127.0.0.1:{port}/", port)
        self.assertFalse(ok_userinfo)
        self.assertIn("Forbidden netloc mismatch", msg_user)

    def test_audit_network_requests_enforces_count_and_host(self) -> None:
        """Network request audit must require observed requests > 0 and reject isolation violations."""
        port = 9012

        # Empty observed requests must fail
        with self.assertRaises(AssertionError) as ctx_empty:
            harness.audit_network_requests([], port)
        self.assertIn("observed_request_count > 0", str(ctx_empty.exception))

        # Forbidden external request must fail
        bad_reqs = [
            {"method": "GET", "url": f"http://127.0.0.1:{port}/index.html", "status": 200},
            {"method": "GET", "url": "http://telemetry.example.invalid/collect", "status": 200},
        ]
        with self.assertRaises(AssertionError) as ctx_bad:
            harness.audit_network_requests(bad_reqs, port)
        self.assertIn("Network isolation violation", str(ctx_bad.exception))

        # Valid requests must pass and return audited list
        good_reqs = [
            {"method": "GET", "url": f"http://127.0.0.1:{port}/index.html", "status": 200},
            {"method": "GET", "url": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=", "status": 200},
        ]
        res = harness.audit_network_requests(good_reqs, port)
        self.assertEqual(len(res), 2)

    def test_audit_network_requests_fails_on_http_error(self) -> None:
        """Network request audit must fail closed when any request returns HTTP status >= 400."""
        port = 9012
        requests_with_404 = [
            {"method": "GET", "url": f"http://127.0.0.1:{port}/index.html", "status": 200},
            {"method": "GET", "url": f"http://127.0.0.1:{port}/favicon.svg", "status": 404},
        ]
        with self.assertRaises(AssertionError) as ctx:
            harness.audit_network_requests(requests_with_404, port)
        self.assertIn("unexpected HTTP error response(s) detected", str(ctx.exception))
        self.assertIn("404", str(ctx.exception))
        self.assertIn("/favicon.svg", str(ctx.exception))

        requests_with_500 = [
            {"method": "GET", "url": f"http://127.0.0.1:{port}/api/v1/sessions", "status": 500},
        ]
        with self.assertRaises(AssertionError) as ctx_500:
            harness.audit_network_requests(requests_with_500, port)
        self.assertIn("unexpected HTTP error response(s) detected", str(ctx_500.exception))
        self.assertIn("500", str(ctx_500.exception))

    def test_verify_listener_terminated(self) -> None:
        """Listener termination verification must report active vs terminated socket states,

        distinguishing explicit connection refusal from timeouts or unrelated network errors.
        """
        import errno

        srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv_sock.bind(("127.0.0.1", 0))
        srv_sock.listen(1)
        port = srv_sock.getsockname()[1]

        try:
            # Active listener should return False (not terminated)
            self.assertFalse(harness.verify_listener_terminated("127.0.0.1", port))
        finally:
            srv_sock.close()

        # Terminated socket: explicit ConnectionRefusedError must return True
        with patch("socket.socket.connect", side_effect=ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")):
            self.assertTrue(harness.verify_listener_terminated("127.0.0.1", port))

        # Terminated socket: Windows WSAECONNREFUSED (10061) must return True
        with patch("socket.socket.connect", side_effect=OSError(10061, "WSAECONNREFUSED")):
            self.assertTrue(harness.verify_listener_terminated("127.0.0.1", port))

        # Timeout should return False (not confirmed terminated)
        with patch("socket.socket.connect", side_effect=TimeoutError("timed out")):
            self.assertFalse(harness.verify_listener_terminated("127.0.0.1", port))

        # Unrelated OSError (e.g. EHOSTUNREACH) should return False
        with patch("socket.socket.connect", side_effect=OSError(errno.EHOSTUNREACH, "No route")):
            self.assertFalse(harness.verify_listener_terminated("127.0.0.1", port))

    def test_red_fault_injection_browser_close_failure(self) -> None:
        """Fault injection: browser close failure must not be swallowed; harness must record failure,

        complete independent cleanup of server/service/tempdir, report cleanup_verified=False,
        write receipt with status=FAIL, and re-raise RuntimeError.
        """
        if run_in_fresh_worker(self):
            return
        with tempfile.TemporaryDirectory(prefix="kinelab-fault-close-", dir=ROOT / "dist") as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            log_path = out_dir / "test.log"

            def fake_build(dist_dir: Path, _logger: harness.Logger | None) -> Path:
                dist_dir.mkdir(parents=True, exist_ok=True)
                (dist_dir / "index.html").write_text(
                    "<!doctype html><html><body>Live Tracker REAL CAMERA</body></html>", encoding="utf-8"
                )
                return dist_dir

            frontend = fake_build(tmp_path / "frontend", None)
            cli = tmp_path / "agent-browser.exe"
            cli.write_bytes(b"TEST_ONLY inert CLI bytes; all browser dispatch is doubled")
            cli_sha256 = hashlib.sha256(cli.read_bytes()).hexdigest()
            avatar_state = {"on": True}
            context_state = {"lost": False}
            draw_count = [0]
            port_box = {"port": 0}
            metric_counter = [0]
            modal_focus = {"edge": "last"}

            viewport = {"width": 1280, "height": 800}

            def mock_browser(*args: str, script: str | None = None) -> dict[str, Any]:
                if len(args) == 4 and args[:2] == ("set", "viewport"):
                    viewport.update(width=int(args[2]), height=int(args[3]))
                    return {}
                # Simulate agent-browser close failure during teardown
                if args and args[0] == "close":
                    raise RuntimeError("Simulated agent-browser close failure")
                if args and args[0] == "screenshot":
                    Path(args[1]).write_bytes(b"fake")
                    return {}
                if args and args[0] == "console":
                    return {"messages": []}
                if args and args[0] == "errors":
                    return {"errors": []}
                if args and args[0] == "network" and len(args) > 1 and args[1] == "requests":
                    p = port_box["port"]
                    return {"requests": [{"url": f"http://127.0.0.1:{p}/index.html", "method": "GET", "status": 200}]}
                if args and args[0] == "eval":
                    s = script or ""
                    if "controls.at(-1)?.focus()" in s:
                        modal_focus["edge"] = "last"
                        return {"result": {"count": 2, "lastFocused": True}}
                    if "return document.activeElement === controls[0]" in s:
                        return {"result": modal_focus["edge"] == "first"}
                    if "return document.activeElement === controls.at(-1)" in s:
                        return {"result": modal_focus["edge"] == "last"}
                    if "window.__kinelab_webgl_draw_count" in s:
                        if not context_state["lost"]:
                            draw_count[0] += 5
                        return {"result": draw_count[0]}
                    if "WEBGL_lose_context" in s or "webglcontextlost" in s:
                        context_state["lost"] = True
                        return {"result": {"success": True, "isLost": True}}
                    if ".uw-twin-btn-restore" in s and "click()" in s:
                        context_state["lost"] = False
                        return {"result": True}
                    if "!document.body.textContent.includes('WebGL context lost')" in s:
                        return {"result": not context_state["lost"]}
                    if "document.body.textContent.includes('WebGL context lost')" in s:
                        return {"result": context_state["lost"]}
                    if ".uw-twin-context-lost-overlay" in s and "=== null" in s:
                        return {"result": not context_state["lost"]}
                    if ".uw-twin-context-lost-overlay" in s and "!== null" in s:
                        return {"result": context_state["lost"]}
                    if "deadline = performance.now()" in s:
                        return {"result": True}
                    if "Current exercise metric" in s or ".uw-hud-rom-metric" in s:
                        metric_counter[0] += 1
                        return {"result": f"{metric_counter[0] * 5}°"}
                    if ".uw-pose-status" in s:
                        return {"result": "Left knee UNAVAILABLE, Right knee UNAVAILABLE"}
                    if ".uw-twin-viewport" in s and "canvas" not in s:
                        return {"result": "3D motion UNAVAILABLE"}
                    if ".uw-btn-finish-set" in s and "disabled === false" in s:
                        return {"result": True}
                    if ".uw-btn-finish-set" in s and "disabled" in s:
                        return {"result": True}
                    if "opacity" in s and "btnOutlineStyle" not in s:
                        return {"result": 0.3}
                    if "getUserMedia" in s:
                        return {"result": "NotAllowedError"}
                    if ".uw-live-twin-container" in s:
                        return {
                            "result": (
                                "3D Digital Twin · Model-derived avatar (derived/2D/unverified); "
                                "muscle activity NOT MEASURED · Drag to rotate · Scroll to zoom"
                            )
                        }
                    if "Toggle 3D Digital Twin avatar" in s and "click()" in s:
                        avatar_state["on"] = not avatar_state["on"]
                        return {"result": True}
                    if "Toggle 3D Digital Twin avatar" in s and "includes('OFF')" in s:
                        return {"result": not avatar_state["on"]}
                    if "Toggle 3D Digital Twin avatar" in s and "includes('ON')" in s:
                        return {"result": avatar_state["on"]}
                    if "Toggle 3D Digital Twin avatar" in s:
                        return {"result": "3D Avatar: ON" if avatar_state["on"] else "3D Avatar: OFF"}
                    if "canvas" in s and "=== null" in s:
                        return {"result": not avatar_state["on"]}
                    if "canvas" in s:
                        return {"result": avatar_state["on"]}
                    if ".uw-twin-collapsed-placeholder" in s and "=== null" in s:
                        return {"result": avatar_state["on"]}
                    if ".uw-twin-collapsed-placeholder" in s:
                        return {
                            "result": (
                                "3D Digital Twin collapsed to preserve resources. "
                                "Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED"
                                if not avatar_state["on"]
                                else ""
                            )
                        }
                    if "tab_result" in s or "KeyboardEvent" in s:
                        return {"result": True}
                    if "dialog" in s and "aria-modal" in s:
                        return {"result": True}
                    if "dialog" in s:
                        return {"result": True}
                    if "focus_returned" in s or "uw-btn-finish-set" in s:
                        return {"result": True}
                    if "activeElement" in s:
                        return {"result": True}
                    if "upload_focus_verified" in s or "btnOutlineStyle" in s:
                        return {
                            "result": {
                                "btnOutlineStyle": "solid",
                                "btnOutlineWidth": "2px",
                                "btnBoxShadow": "none",
                                "inputOutlineStyle": "none",
                                "inputOutlineWidth": "0px",
                                "btnOutlineColor": "rgb(133, 255, 220)",
                                "btnVisible": True,
                                "btnOutlineVisible": True,
                            }
                        }
                    if "desktop_layout" in s or "navWidth" in s:
                        return {"result": {"navWidth": 260, "workspaceWidth": 1020, "isMobile": False}}
                    if "mobile_checks" in s or "scrollWidth" in s:
                        return {
                            "result": {
                                "width": viewport["width"],
                                "height": viewport["height"],
                                "scrollWidth": viewport["width"],
                                "clientWidth": viewport["width"],
                                "linksCount": 5,
                                "navControlsVisible": True,
                            }
                        }
                    return {"result": True}
                if args == ("press", "Tab"):
                    modal_focus["edge"] = "first"
                elif args == ("press", "Shift+Tab"):
                    modal_focus["edge"] = "last"
                return {}

            real_make_server = harness.make_server

            def wrap_make_server(*s_args: Any, **s_kwargs: Any) -> Any:
                srv = real_make_server(*s_args, **s_kwargs)
                port_box["port"] = srv.server_port
                return srv

            with (
                patch("tools.verify_candidate_ui.ensure_viewer_build", side_effect=AssertionError("Unexpected build")),
                patch("tools.verify_candidate_ui.make_server", side_effect=wrap_make_server),
                self.assertRaises(RuntimeError) as ctx,
            ):
                harness.verify(out_dir, log_path, frontend_dist=frontend, agent_browser_executable=cli,
                               agent_browser_sha256=cli_sha256, browser_fn=mock_browser)

            self.assertIn("Simulated agent-browser close failure", str(ctx.exception))

            # Receipt assertions
            receipt_path = out_dir / "receipt.json"
            self.assertTrue(receipt_path.exists())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

            self.assertEqual(receipt["status"], "FAIL")
            self.assertIn("Simulated agent-browser close failure", receipt["error"])

            self.assertTrue(receipt["checks"]["synthetic_tracking_progression"]["progression_verified"])
            self.assertEqual(receipt["checks"]["synthetic_tracking_progression"]["draw_delta"], 0)

            cleanup = receipt["cleanup"]
            self.assertFalse(cleanup["browser_closed"])
            self.assertFalse(cleanup["cleanup_verified"])

            # Verify independent cleanup succeeded despite browser close failure
            self.assertTrue(cleanup["server_shutdown"])
            self.assertTrue(cleanup["server_closed"])
            self.assertTrue(cleanup["server_thread_dead"])
            self.assertTrue(cleanup["service_closed"])
            self.assertTrue(cleanup["temp_directory_cleaned"])
            self.assertTrue(cleanup["root_directory_absent"])
            self.assertTrue(cleanup["init_script_absent"])
            self.assertTrue(cleanup["listener_terminated"])

            # Verify cleanup_errors captured the close failure
            self.assertTrue(
                any("Simulated agent-browser close failure" in err for err in receipt["cleanup_errors"])
            )

    def test_browser_session_isolation_and_no_all_flag(self) -> None:
        """Harness browser teardown must NEVER pass --all or target unrelated sessions,

        and must strictly scope all commands to --session <browser_session>.
        """
        if run_in_fresh_worker(self):
            return
        with tempfile.TemporaryDirectory(prefix="kinelab-session-test-", dir=ROOT / "dist") as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            log_path = out_dir / "test.log"

            def fake_build(dist_dir: Path, _logger: harness.Logger | None) -> Path:
                dist_dir.mkdir(parents=True, exist_ok=True)
                (dist_dir / "index.html").write_text("<!doctype html><html><body>Live Tracker</body></html>", encoding="utf-8")
                (dist_dir / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
                return dist_dir

            frontend = fake_build(tmp_path / "frontend", None)
            cli = tmp_path / "agent-browser.exe"
            cli.write_bytes(b"TEST_ONLY inert CLI bytes; subprocess dispatch is doubled")
            cli_sha256 = hashlib.sha256(cli.read_bytes()).hexdigest()
            commands_run: list[list[str]] = []
            viewport = {"width": 1280, "height": 800}
            avatar_state = {"on": True}
            context_lost = [False]
            draws = [5]
            metric_counter = [0]
            port_box = {"port": 0}
            modal_focus = {"edge": "last"}

            import subprocess as real_subprocess

            real_run = real_subprocess.run

            closed_sessions: set[str] = set()

            def mock_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
                if cmd and cmd[0] != str(cli):
                    return real_run(cmd, *args, **kwargs)
                commands_run.append(list(cmd))

                class MockProcResult:
                    def __init__(self, data: dict[str, Any], returncode: int = 0) -> None:
                        self.returncode = returncode
                        self.stdout = json.dumps(data)
                        self.stderr = ""

                session_id = None
                if "--session" in cmd:
                    session_id = cmd[cmd.index("--session") + 1]

                if len(cmd) >= 4 and cmd[-4:-2] == ["set", "viewport"]:
                    viewport.update(width=int(cmd[-2]), height=int(cmd[-1]))
                    return MockProcResult({"success": True, "data": {}})

                # Browser teardown cleanup command: agent-browser --session <id> close
                if cmd[-1] == "close":
                    if session_id:
                        closed_sessions.add(session_id)
                    return MockProcResult({"success": True, "data": {}})

                # TEST_ONLY hypothesis: close-tombstone causes daemon outcome_unknown EOF on reuse; native root cause unproven.
                if "open" in cmd and session_id in closed_sessions:
                    return MockProcResult(
                        {
                            "code": "outcome_unknown",
                            "error": "Invalid response: EOF while parsing a value at line 1 column 0 (the command reached the daemon but no response came back; it may or may not have run, so it was not retried)",
                            "success": False,
                        },
                        returncode=1,
                    )

                if "--stdin" in cmd:
                    script = kwargs.get("input", "")
                    res_val: Any = True
                    if "controls.at(-1)?.focus()" in script:
                        modal_focus["edge"] = "last"
                        res_val = {"count": 2, "lastFocused": True}
                    elif "return document.activeElement === controls[0]" in script:
                        res_val = modal_focus["edge"] == "first"
                    elif "return document.activeElement === controls.at(-1)" in script:
                        res_val = modal_focus["edge"] == "last"
                    elif "window.__kinelab_webgl_draw_count" in script:
                        if not context_lost[0]:
                            draws[0] += 5
                        res_val = draws[0]
                    elif "Current exercise metric" in script or ".uw-hud-rom-metric" in script:
                        metric_counter[0] += 1
                        res_val = f"{metric_counter[0] * 10}°"
                    elif "opacity" in script and "btnOutlineStyle" not in script:
                        res_val = 0.38
                    elif "upload_focus_verified" in script or "btnOutlineStyle" in script:
                        res_val = {
                            "btnOutlineStyle": "solid",
                            "btnOutlineWidth": "2px",
                            "btnBoxShadow": "none",
                            "inputOutlineStyle": "none",
                            "inputOutlineWidth": "0px",
                            "btnOutlineColor": "rgb(133, 255, 220)",
                            "btnVisible": True,
                            "btnOutlineVisible": True,
                        }
                    elif "mobile_checks" in script or "scrollWidth" in script:
                        res_val = {
                            "width": viewport["width"],
                            "height": viewport["height"],
                            "scrollWidth": viewport["width"],
                            "clientWidth": viewport["width"],
                            "linksCount": 5,
                            "navControlsVisible": True,
                        }
                    elif ".uw-live-twin-container" in script:
                        res_val = (
                            "3D Digital Twin · Model-derived avatar (derived/2D/unverified); "
                            "muscle activity NOT MEASURED · Drag to rotate · Scroll to zoom"
                        )
                    elif ".uw-twin-collapsed-placeholder" in script and "=== null" in script:
                        res_val = avatar_state["on"]
                    elif ".uw-twin-collapsed-placeholder" in script and "!== null" in script:
                        res_val = not avatar_state["on"]
                    elif ".uw-twin-collapsed-placeholder" in script:
                        res_val = (
                            "3D Digital Twin collapsed to preserve resources · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED"
                            if not avatar_state["on"]
                            else ""
                        )
                    elif "Toggle 3D Digital Twin avatar" in script and "click()" in script:
                        avatar_state["on"] = not avatar_state["on"]
                        res_val = True
                    elif "Toggle 3D Digital Twin avatar" in script and "includes('OFF')" in script:
                        res_val = not avatar_state["on"]
                    elif "Toggle 3D Digital Twin avatar" in script and "includes('ON')" in script:
                        res_val = avatar_state["on"]
                    elif "Toggle 3D Digital Twin avatar" in script:
                        res_val = "3D Avatar: ON" if avatar_state["on"] else "3D Avatar: OFF"
                    elif "WEBGL_lose_context" in script or "webglcontextlost" in script:
                        context_lost[0] = True
                        res_val = {"success": True, "isLost": True}
                    elif ".uw-twin-btn-restore" in script and "click()" in script:
                        context_lost[0] = False
                        res_val = True
                    elif "canvas" in script and "=== null" in script:
                        res_val = not avatar_state["on"]
                    elif "canvas" in script:
                        res_val = avatar_state["on"]
                    elif ".uw-twin-context-lost-overlay" in script and "=== null" in script:
                        res_val = not context_lost[0]
                    elif ".uw-twin-context-lost-overlay" in script and "!== null" in script:
                        res_val = context_lost[0]
                    elif ".uw-pose-status" in script:
                        res_val = "Left knee UNAVAILABLE, Right knee UNAVAILABLE"
                    elif ".uw-twin-viewport" in script and "canvas" not in script:
                        res_val = "3D motion UNAVAILABLE"
                    elif "getUserMedia" in script:
                        res_val = "NotAllowedError"
                    return MockProcResult({"success": True, "data": {"result": res_val}})

                if "screenshot" in cmd:
                    target_file = Path(cmd[-1])
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_bytes(b"dummy png")
                    return MockProcResult({"success": True, "data": {}})

                if "console" in cmd:
                    return MockProcResult({"success": True, "data": {"messages": []}})

                if "errors" in cmd:
                    return MockProcResult({"success": True, "data": {"errors": []}})

                if "network" in cmd and "requests" in cmd:
                    p = port_box["port"]
                    reqs = [
                        {"method": "GET", "url": f"http://127.0.0.1:{p}/", "status": 200},
                        {"method": "GET", "url": f"http://127.0.0.1:{p}/favicon.svg", "status": 200},
                    ]
                    return MockProcResult({"success": True, "data": {"requests": reqs}})

                if cmd[-2:] == ["press", "Tab"]:
                    modal_focus["edge"] = "first"
                elif cmd[-2:] == ["press", "Shift+Tab"]:
                    modal_focus["edge"] = "last"
                return MockProcResult({"success": True, "data": {}})

            real_make_server = harness.make_server

            def wrap_make_server(*s_args: Any, **s_kwargs: Any) -> Any:
                self.assertFalse(s_args[0].projects_root.is_relative_to(ROOT))
                self.assertFalse(harness.is_reparse(s_args[0].projects_root))
                srv = real_make_server(*s_args, **s_kwargs)
                port_box["port"] = srv.server_port
                return srv

            with (
                patch("shutil.which", side_effect=AssertionError("Unexpected PATH lookup")),
                patch("subprocess.run", side_effect=mock_subprocess_run),
                patch("tools.verify_candidate_ui.ensure_viewer_build", side_effect=AssertionError("Unexpected build")),
                patch("tools.verify_candidate_ui.make_server", side_effect=wrap_make_server),
            ):
                receipt = harness.verify(out_dir, log_path, frontend_dist=frontend,
                                         agent_browser_executable=cli, agent_browser_sha256=cli_sha256)

            self.assertEqual(receipt["status"], "PASS")
            self.assertTrue(receipt["cleanup"]["cleanup_verified"])
            for private_path in receipt["environment_paths"].values():
                self.assertFalse(Path(private_path).is_relative_to(ROOT))
                self.assertFalse(Path(private_path).exists(), "Owned private environment was not cleaned")

            # Assert commands were actually run
            self.assertGreater(len(commands_run), 0)

            # Assert that "--all" was NEVER passed in ANY command
            for cmd in commands_run:
                self.assertNotIn("--all", cmd, f"Command must not pass --all: {cmd}")

            # Assert that no pre-run close was executed on the fresh unique session
            first_open = next(index for index, command in enumerate(commands_run) if "open" in command)
            pre_run_close_cmds = [
                c for index, c in enumerate(commands_run)
                if c[0] == str(cli) and c[-1] == "close" and index < first_open
            ]
            self.assertEqual(len(pre_run_close_cmds), 0, f"Fresh unique session must not pre-close before first open: {pre_run_close_cmds}")
            self.assertEqual(commands_run[0][0], str(cli))
            self.assertIn("open", commands_run[0])

            first_open_cmd = commands_run[first_open]
            self.assertIn("--session", first_open_cmd)
            open_session_idx = first_open_cmd.index("--session")
            self.assertEqual(first_open_cmd[open_session_idx], "--session")
            owned_session = first_open_cmd[open_session_idx + 1]
            self.assertEqual(owned_session, receipt["browser_session"])
            self.assertTrue(owned_session.startswith("kinelab-ui-"))

            # Assert teardown cleanup was executed targeting the exact owned session
            teardown_close_cmds = [
                c for index, c in enumerate(commands_run)
                if c[0] == str(cli) and c[-1] == "close" and index > first_open
            ]
            self.assertEqual(len(teardown_close_cmds), 1)
            self.assertIn("--session", teardown_close_cmds[0])
            teardown_session_idx = teardown_close_cmds[0].index("--session")
            self.assertEqual(teardown_close_cmds[0][teardown_session_idx + 1], owned_session)

            # Assert every single agent-browser command targeted the exact same session
            for cmd in commands_run:
                if cmd[0] == str(cli):
                    self.assertIn("--session", cmd)
                    session_idx = cmd.index("--session")
                    self.assertEqual(cmd[session_idx + 1], owned_session)

    def test_reused_closed_session_fails_with_outcome_unknown_eof(self) -> None:
        """Exercising harness.verify and actual verifier subprocess wrapper with bounded fake CLI reproduces outcome_unknown EOF on closed session reuse."""
        if run_in_fresh_worker(self):
            return
        with tempfile.TemporaryDirectory(prefix="kinelab-session-eof-", dir=ROOT / "dist") as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            log_path = out_dir / "test.log"

            def fake_build(dist_dir: Path, _logger: harness.Logger | None) -> Path:
                dist_dir.mkdir(parents=True, exist_ok=True)
                (dist_dir / "index.html").write_text("<!doctype html><html><body>Live Tracker</body></html>", encoding="utf-8")
                (dist_dir / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
                return dist_dir

            frontend = fake_build(tmp_path / "frontend", None)
            cli = tmp_path / "agent-browser.exe"
            cli.write_bytes(b"TEST_ONLY inert CLI bytes; subprocess dispatch is doubled")
            cli_sha256 = hashlib.sha256(cli.read_bytes()).hexdigest()

            import subprocess as real_subprocess

            real_run = real_subprocess.run

            # TEST_ONLY hypothesis: close-tombstone causes daemon outcome_unknown EOF on reuse; native root cause unproven.
            def mock_tombstone_run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
                if cmd and cmd[0] != str(cli):
                    return real_run(cmd, *args, **kwargs)

                class MockProcResult:
                    def __init__(self, data: dict[str, Any], returncode: int = 0) -> None:
                        self.returncode = returncode
                        self.stdout = json.dumps(data)
                        self.stderr = ""

                # When open command is dispatched to fake CLI boundary, simulate daemon outcome_unknown EOF
                if "open" in cmd:
                    return MockProcResult(
                        {
                            "code": "outcome_unknown",
                            "error": "Invalid response: EOF while parsing a value at line 1 column 0 (the command reached the daemon but no response came back; it may or may not have run, so it was not retried)",
                            "success": False,
                        },
                        returncode=1,
                    )

                return MockProcResult({"success": True, "data": {}})

            with (
                patch.object(real_subprocess, "run", side_effect=mock_tombstone_run),
                patch("tools.verify_candidate_ui.ensure_viewer_build", side_effect=AssertionError("Unexpected build")),
                self.assertRaises(RuntimeError) as ctx,
            ):
                harness.verify(
                    out_dir, log_path, frontend_dist=frontend,
                    agent_browser_executable=cli, agent_browser_sha256=cli_sha256,
                    browser_fn=None,
                )

            # Assert outcome_unknown EOF propagates from actual verifier subprocess wrapper
            self.assertIn("outcome_unknown", str(ctx.exception))
            self.assertIn("EOF while parsing a value at line 1 column 0", str(ctx.exception))

            # Assert owned cleanup completes and writes failure receipt
            receipt_path = out_dir / "receipt.json"
            self.assertTrue(receipt_path.exists())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "FAIL")
            self.assertIn("outcome_unknown", receipt["error"])

            cleanup = receipt["cleanup"]
            self.assertTrue(cleanup["browser_closed"])
            self.assertTrue(cleanup["server_shutdown"])
            self.assertTrue(cleanup["server_closed"])
            self.assertTrue(cleanup["server_thread_dead"])
            self.assertTrue(cleanup["service_closed"])
            self.assertTrue(cleanup["temp_directory_cleaned"])
            self.assertTrue(cleanup["root_directory_absent"])
            self.assertTrue(cleanup["init_script_absent"])
            self.assertTrue(cleanup["listener_terminated"])

    def test_explicit_cli_pin_refuses_before_browser_or_server(self) -> None:
        """An actual bounded pin mismatch must refuse without dispatch, fallback build or server creation."""
        if run_in_fresh_worker(self):
            return
        with tempfile.TemporaryDirectory(prefix="test-only-ui-bad-pin-", dir=ROOT / "dist") as tmp:
            owned = Path(tmp)
            frontend = owned / "frontend"
            frontend.mkdir()
            page = b"<!doctype html><html>TEST_ONLY admission fixture</html>"
            (frontend / "index.html").write_bytes(page)
            cli = owned / "agent-browser.exe"
            original = b"TEST_ONLY inert bytes; execution is forbidden"
            cli.write_bytes(original)
            expected = hashlib.sha256(original).hexdigest()
            wrong_pin = ("0" if expected[0] != "0" else "1") + expected[1:]
            with (
                patch.object(harness, "make_server") as server,
                patch.object(harness, "ensure_viewer_build") as build,
                patch.object(harness.subprocess, "run") as dispatch,
                self.assertRaisesRegex(ValueError, "^BROWSER_CLI_HASH_MISMATCH$"),
            ):
                harness.verify(owned / "out", frontend_dist=frontend, agent_browser_executable=cli,
                               agent_browser_sha256=wrong_pin)
            server.assert_not_called()
            build.assert_not_called()
            dispatch.assert_not_called()
            self.assertEqual(cli.read_bytes(), original)
            self.assertEqual((frontend / "index.html").read_bytes(), page)
            self.assertFalse((owned / "out" / "receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
