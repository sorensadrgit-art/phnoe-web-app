"""Isolated browser acceptance verification for KineLab PT UI and accessibility.

Verifies:
- Unavailable metrics behavior (real camera with missing kinematics displays UNAVAILABLE, never 0)
- 3D Digital Twin attribution banner display and target zone gating
- Modal dialog focus trap, Escape dismissal, and focus return
- Keyboard focus visibility for transparent file upload controls (:focus-visible)
- Responsive viewports (five portrait sizes and their landscape rotations)
- Loopback isolation (127.0.0.1 only), camera/mic access denied, zero external network calls
"""
import argparse
import datetime
import errno
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_config import is_reparse

EVIDENCE_ROOT = ROOT / "dist" / "fullproject-20261028" / "antigravity-R3"
DEFAULT_OUT = EVIDENCE_ROOT / "ui-browser"
DEFAULT_LOG = EVIDENCE_ROOT / "F-ui-browser.log"

UI_SOURCE_FILES = [
    ROOT / "viewer" / "src" / "LiveTrackerStudio.jsx",
    ROOT / "viewer" / "src" / "LiveDigitalTwin.jsx",
    ROOT / "viewer" / "src" / "LiveHUDOverlay.jsx",
    ROOT / "viewer" / "src" / "LiveSetSummaryModal.jsx",
    ROOT / "viewer" / "src" / "GuidedCaptureWizard.jsx",
    ROOT / "viewer" / "src" / "ReportStudio.jsx",
    ROOT / "viewer" / "src" / "VerifiedReview.jsx",
    ROOT / "viewer" / "src" / "UnifiedApp.jsx",
    ROOT / "viewer" / "src" / "avatarLifecycle.js",
    ROOT / "viewer" / "src" / "unifiedModel.js",
    ROOT / "viewer" / "src" / "unified.css",
    ROOT / "viewer" / "src" / "liveDisplayHelper.js",
]


class Logger:
    def __init__(self, log_path: Path):
        self.log_path = Path(log_path).resolve()
        if self.log_path.exists():
            raise FileExistsError(f"Refusing to overwrite existing log evidence: {self.log_path}")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.log_path.open("x", encoding="utf-8")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self.close()

    def log(self, message: str) -> None:
        timestamp = datetime.datetime.now(datetime.UTC).isoformat()
        line = f"[{timestamp}] {message}"
        print(line, flush=True)
        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()


def make_server(*args: Any, **kwargs: Any) -> Any:
    """Keep the existing server seam lazy until the owned environment is active."""
    from t6_server import make_server as create_server
    return create_server(*args, **kwargs)


def check_path_guards(out_dir: Path, log_path: Path) -> None:
    """Enforce evidence preservation guards: refuse pre-existing log files and non-empty output dirs."""
    out_dir = Path(out_dir).resolve()
    log_path = Path(log_path).resolve()
    if log_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing log evidence: {log_path}")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty output evidence directory: {out_dir}")


def get_vite_build_command(out_dir: Path) -> list[str]:
    """Construct Vite build command targeting an explicit, unique outDir outside viewer/dist."""
    npm_cmd = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    return [
        npm_cmd,
        "--prefix",
        str(ROOT / "viewer"),
        "run",
        "build",
        "--",
        "--outDir",
        str(out_dir),
        "--emptyOutDir",
    ]


def ensure_viewer_build(out_dir: Path, logger: Logger) -> Path:
    logger.log(f"Building viewer distribution targeting unique destination: {out_dir}...")
    build_cmd = get_vite_build_command(out_dir)
    proc = subprocess.run(build_cmd, check=True, capture_output=True, text=True, shell=os.name == "nt")
    logger.log(f"Viewer built successfully:\n{proc.stdout}")
    return out_dir


def check_network_url(url: str, expected_port: int) -> tuple[bool, str]:
    """Validate that request URL strictly targets the expected loopback host and port,
    or is an approved data: or loopback blob: URI. Rejects substring tricks, query params, foreign hosts, and non-http schemes."""
    if not url or not isinstance(url, str):
        return False, "Empty or non-string URL"
    if url.startswith("data:"):
        return True, "Allowed data URI"
    if url.startswith("blob:"):
        expected_blob_prefix = f"blob:http://127.0.0.1:{expected_port}/"
        if url.startswith(expected_blob_prefix):
            return True, "Allowed loopback blob URI"
        return False, f"Forbidden blob URI origin: expected prefix {expected_blob_prefix}"

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http":
        return False, f"Forbidden URL scheme (http required): {parsed.scheme}"

    try:
        port = parsed.port
    except ValueError:
        return False, "Malformed URL port"

    if parsed.hostname != "127.0.0.1":
        return False, f"Forbidden non-loopback host: {parsed.hostname} (netloc: {parsed.netloc})"
    if port != expected_port:
        return False, f"Forbidden port mismatch: expected {expected_port}, got {port}"
    if parsed.netloc != f"127.0.0.1:{expected_port}":
        return False, f"Forbidden netloc mismatch: expected 127.0.0.1:{expected_port}, got {parsed.netloc}"
    return True, "Valid loopback URL"


def audit_network_requests(req_items: list[dict[str, Any]], expected_port: int) -> list[dict[str, Any]]:
    """Audit recorded network requests: requires observed_request_count > 0, strict loopback validation,
    and fails closed on any unexpected HTTP error response (status >= 400)."""
    if len(req_items) == 0:
        raise AssertionError(
            "Network isolation audit failed: zero network requests observed (expected observed_request_count > 0)"
        )
    failing_endpoints: list[dict[str, Any]] = []
    for r in req_items:
        url = r.get("url", "")
        valid, reason = check_network_url(url, expected_port)
        if not valid:
            raise AssertionError(f"Network isolation violation: {reason} for URL: {url}")
        status = r.get("status")
        if status is not None:
            try:
                status_code = int(status)
                if status_code >= 400:
                    failing_endpoints.append({
                        "url": url,
                        "method": r.get("method"),
                        "status": status_code,
                    })
            except (ValueError, TypeError):
                pass

    if failing_endpoints:
        raise AssertionError(
            f"Network request audit failed: unexpected HTTP error response(s) detected (status >= 400): {failing_endpoints}"
        )
    return req_items


def verify_listener_terminated(host: str, port: int, timeout: float = 3.5) -> bool:
    """Verify that a TCP listener has fully terminated and refuses connections.
    Returns True ONLY if connection is explicitly refused. Returns False if still accepting or on timeout/other error."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return False
    except ConnectionRefusedError:
        return True
    except OSError as err:
        wsa_econnrefused = 10061
        return (
            getattr(err, "winerror", None) == wsa_econnrefused
            or err.errno in (errno.ECONNREFUSED, wsa_econnrefused)
        )
    finally:
        try:
            s.close()
        except OSError:
            pass


@contextmanager
def _external_temporary_directory(*, prefix: str):
    """Own fresh private state outside the installation; never repair an unsafe parent."""
    selected = os.environ.get("KINELAB_TEST_ONLY_EXTERNAL_TEMP_PARENT")
    parent = Path(selected if selected is not None else tempfile.gettempdir()).absolute()
    if (".." in parent.parts or parent == Path(parent.anchor)
            or parent == ROOT or parent.is_relative_to(ROOT) or ROOT.is_relative_to(parent)
            or any(is_reparse(part) for part in (*parent.parents, parent))
            or not parent.is_dir()):
        raise ValueError("EXTERNAL_TEMP_UNSAFE: an ordinary dedicated parent outside the installation is required")
    temporary = tempfile.TemporaryDirectory(prefix=prefix, dir=parent)
    primary = None
    try:
        owned = Path(temporary.name).absolute()
        if (owned.parent != parent or owned.is_relative_to(ROOT)
                or any(is_reparse(part) for part in (*owned.parents, owned))):
            raise ValueError("EXTERNAL_TEMP_UNSAFE: temporary ownership changed")
        yield owned
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            temporary.cleanup()
        except Exception as cleanup_error:
            if primary is None:
                raise
            primary.add_note(f"Owned external temporary cleanup failed: {type(cleanup_error).__name__}")


def verify(
    out_dir: Path, log_path: Path | None = None, *, frontend_dist: Path | None = None,
    agent_browser_executable: Path | None = None, agent_browser_sha256: str | None = None,
    browser_fn: Any = None,
) -> dict[str, Any]:
    """Admit explicit inputs and isolate state before importing the application."""
    if frontend_dist is None or agent_browser_executable is None or agent_browser_sha256 is None:
        raise ValueError("Explicit frontend-dist and pinned agent-browser path/SHA256 are required")
    out_dir = Path(out_dir).absolute()
    log_path = Path(log_path).absolute() if log_path is not None else out_dir / "verification.log"
    for path in (out_dir, log_path):
        if ".." in path.parts or any(is_reparse(part) for part in (*path.parents, path)):
            raise ValueError("Linked, reparse, or traversing evidence paths are refused")
    out_dir, log_path = out_dir.resolve(), log_path.resolve()
    evidence_root = ROOT / "dist"
    if out_dir == evidence_root or not out_dir.is_relative_to(evidence_root):
        raise ValueError("A new dedicated output directory under this workspace's dist is required")
    if not log_path.is_relative_to(out_dir) or log_path == out_dir:
        raise ValueError("The log must be a new file beneath the output directory")
    if "matplotlib" in sys.modules:
        raise RuntimeError("A fresh verifier process is required before application/Matplotlib imports")
    out_dir.mkdir(parents=True, exist_ok=False)
    with _external_temporary_directory(prefix="test-only-candidate-ui-") as private_root:
        environment_root = private_root / "environment"
        environment = {
            "HOME": environment_root / "home", "USERPROFILE": environment_root / "home",
            "APPDATA": environment_root / "roaming", "LOCALAPPDATA": environment_root / "local",
            "TEMP": environment_root / "tmp", "TMP": environment_root / "tmp",
            "XDG_CONFIG_HOME": environment_root / "config", "XDG_CACHE_HOME": environment_root / "cache",
            "XDG_DATA_HOME": environment_root / "data", "MPLCONFIGDIR": environment_root / "matplotlib",
            "KINELAB_CANDIDATE_DATA_ROOT": environment_root / "candidate-data",
        }
        prior_environment = {name: os.environ.get(name) for name in environment}
        prior_tempdir, prior_bytecode = tempfile.tempdir, sys.dont_write_bytecode
        try:
            for directory in set(environment.values()):
                directory.mkdir(parents=True, exist_ok=False)
            os.environ.update({name: str(path) for name, path in environment.items()})
            tempfile.tempdir = str(environment["TEMP"])
            sys.dont_write_bytecode = True
            return _verify_admitted(
                out_dir, log_path, frontend_dist=frontend_dist, runtime_parent=private_root,
                agent_browser_executable=agent_browser_executable, agent_browser_sha256=agent_browser_sha256,
                browser_fn=browser_fn,
            )
        finally:
            tempfile.tempdir, sys.dont_write_bytecode = prior_tempdir, prior_bytecode
            for name, value in prior_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _verify_admitted(
    out_dir: Path, log_path: Path, *, frontend_dist: Path, runtime_parent: Path,
    agent_browser_executable: Path, agent_browser_sha256: str, browser_fn: Any,
) -> dict[str, Any]:
    # Reuse the established ordinary-file, same-byte CLI/build admission helpers.
    from t6_service import IntegratedService
    from tools.verify_browser_isolation import _frontend_inventory, _pinned_agent_browser, _unlinked_path

    viewer_dist = _unlinked_path(frontend_dist)
    if viewer_dist == ROOT / "dist" or not viewer_dist.is_relative_to(ROOT / "dist"):
        raise ValueError("The explicit frontend must be a dedicated directory beneath workspace dist")
    if out_dir.is_relative_to(viewer_dist) or viewer_dist.is_relative_to(out_dir):
        raise ValueError("Frontend and output directories must not overlap")
    if not viewer_dist.is_dir() or not (viewer_dist / "index.html").is_file():
        raise ValueError("The existing frontend distribution requires an ordinary index.html")
    build_before = _frontend_inventory(viewer_dist)
    cli = _pinned_agent_browser(agent_browser_executable, agent_browser_sha256)

    browser_session = "kinelab-ui-" + uuid4().hex[:10]
    receipt: dict[str, Any] = {
        "fixture": "synthetic isolated candidate UI acceptance",
        "browser_session": browser_session,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "browser_engine": "agent-browser",
        "browser_execution": "TEST_DOUBLE" if browser_fn is not None else "NATIVE_PINNED_CLI",
        "browser_cli": {"path": cli, "sha256": agent_browser_sha256},
        "frontend_dist": str(viewer_dist),
        "build_inventory_before": build_before,
        "environment_paths": {name: os.environ[name] for name in (
            "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME", "XDG_DATA_HOME", "MPLCONFIGDIR")},
        "deviation_record": {
            "initial_run_deviation": (
                "Initial harness run compiled into shared viewer/dist and used rmtree on evidence. "
                "Historical repair used Vite --outDir. This revision admits an explicit existing build without rebuilding."
            )
        },
        "source_sha256": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in UI_SOURCE_FILES if p.is_file()
        },
        "dist_sha256": {name: item["sha256"] for name, item in build_before.items() if item["kind"] == "file"},
        "checks": {},
        "screenshots": {},
        "runtime": {},
        "network": {},
        "permissions": {
            "synthetic_get_user_media_stub": {
                "installed": True,
                "denial_tested": False,
                "behavior": "Synthetic navigator.mediaDevices.getUserMedia rejection stub",
                "hardware_isolated": True,
            },
            "native_browser_permission_proof": "NOT_VERIFIED",
            "notes": (
                "Synthetic fixture overrides navigator.mediaDevices to reject without device access. "
                "Native browser/OS permission prompt state is NOT_VERIFIED."
            ),
        },
        "cleanup": {},
        "cleanup_errors": [],
        "status": "PENDING",
        "error": None,
    }

    temp_dir_obj = None
    runtime_path = out_dir / "runtime-not-created"
    init_script_path = runtime_path / "init.js"
    config_path = runtime_path / "config.json"

    service: IntegratedService | None = None
    server: Any = None
    thread: threading.Thread | None = None
    server_port: int = 0
    origin: str = ""

    original_error: BaseException | None = None
    cleanup_errors: list[str] = []
    cleanup_steps: dict[str, Any] = {
        "browser_closed": False,
        "server_shutdown": False,
        "server_closed": False,
        "thread_joined": False,
        "service_closed": False,
        "temp_directory_cleaned": False,
        "root_directory_absent": False,
        "init_script_absent": False,
        "server_thread_dead": False,
        "listener_terminated": False,
        "cleanup_verified": False,
        "frontend_unchanged": False,
    }
    logger = Logger(log_path)

    def cleanup_log(message: str) -> None:
        try:
            logger.log(message)
        except Exception as error:  # noqa: BLE001 -- continue independent cleanup after logging failure
            cleanup_errors.append(f"cleanup_log: {type(error).__name__}")

    try:
        logger.log("Starting isolated candidate UI verification against the admitted existing build...")
        temp_dir_obj = tempfile.TemporaryDirectory(prefix="runtime-", dir=runtime_parent)
        runtime_path = Path(temp_dir_obj.name)
        projects_dir = runtime_path / "projects"
        samples_dir = runtime_path / "samples"
        projects_dir.mkdir()
        samples_dir.mkdir()
        init_script_path = runtime_path / "init.js"
        config_path = runtime_path / "config.json"
        service = IntegratedService(projects_dir)
        service.create_session("synthetic-test-session")

        token = secrets.token_hex(32)
        server = make_server(service, token=token, dist=viewer_dist, samples=samples_dir, port=0)
        server_port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        origin = f"http://127.0.0.1:{server_port}"
        logger.log(f"Isolated server running at {origin} (PID {os.getpid()})")

        with urlopen(origin, timeout=5) as response:
            assert response.status == 200, f"Unexpected server HTTP status: {response.status}"
            body = response.read(512).lower()
            assert b"<!doctype html>" in body or b"<html" in body, "Expected HTML payload from viewer"

        receipt["runtime"] = {
            "origin": origin,
            "port": server_port,
            "process_id": os.getpid(),
            "http_ready": True,
            "status_code": 200,
        }
        receipt["network"] = {
            "allowed_domains": ["127.0.0.1"],
            "expected_port": server_port,
            "external_requests_prevented": True,
            "loopback_only": True,
            "policy": "Local loopback only; synthetic getUserMedia denial stub prevents hardware access",
        }
        logger.log(f"Server readiness verified on {origin} (PID {os.getpid()}, port {server_port})")

        init_script_path.write_text(f"""
localStorage.clear();
localStorage.setItem('kinelab_active_tab', 'live');
localStorage.setItem('kinelab_selected_session', 'synthetic-test-session');
localStorage.setItem('kinelab_t6_token', '{token}');
Object.defineProperty(navigator, 'mediaDevices', {{
  value: {{
    enumerateDevices: async () => [],
    getUserMedia: async () => {{
      throw new DOMException('Permission denied by test harness', 'NotAllowedError');
    }}
  }}
}});

window.__kinelab_webgl_draw_count = 0;
const _origGetContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(...args) {{
  const ctx = _origGetContext.apply(this, args);
  if (ctx && (args[0] === 'webgl' || args[0] === 'webgl2')) {{
    this.__kinelab_gl = ctx;
    window.__kinelab_active_gl = ctx;
    window.__kinelab_active_canvas = this;
    if (!ctx.__draw_hooked) {{
      ctx.__draw_hooked = true;
      const _origDrawElements = ctx.drawElements;
      ctx.drawElements = function(...dArgs) {{
        if (!this.isContextLost()) {{
          window.__kinelab_webgl_draw_count++;
          window.__kinelab_active_gl = this;
          window.__kinelab_active_canvas = this.canvas;
        }}
        return _origDrawElements.apply(this, dArgs);
      }};
      const _origDrawArrays = ctx.drawArrays;
      ctx.drawArrays = function(...dArgs) {{
        if (!this.isContextLost()) {{
          window.__kinelab_webgl_draw_count++;
          window.__kinelab_active_gl = this;
          window.__kinelab_active_canvas = this.canvas;
        }}
        return _origDrawArrays.apply(this, dArgs);
      }};
    }}
  }}
  return ctx;
}};
""", encoding="utf-8")

        config_path.write_text("{}", encoding="utf-8")

        downloads = runtime_path / "downloads"
        downloads.mkdir()
        # Explicit paths plus a new namespace avoid user configuration, auth replay, or shared sessions.
        # A persistent --profile is intentionally absent: it is incompatible with allowed-domains containment.
        browser_environment = {name: os.environ[name] for name in (
            "SYSTEMROOT", "WINDIR", "SystemDrive", "COMSPEC", "ProgramFiles", "ProgramFiles(x86)",
            "ProgramW6432", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
            "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME") if name in os.environ}
        browser_environment["PATH"] = os.path.join(os.environ["SYSTEMROOT"], "System32") if os.name == "nt" else os.defpath
        prefix = [
            cli,
            "--session", browser_session,
            "--namespace", browser_session,
            "--config", str(config_path),
            "--json",
            "--allowed-domains", "127.0.0.1",
            "--download-path", str(downloads),
            "--restore-save", "never",
        ]

        if browser_fn is not None:
            browser = browser_fn
        else:
            def browser(*args: str, script: str | None = None) -> dict[str, Any]:
                _pinned_agent_browser(cli, agent_browser_sha256)
                cmd = [*prefix, *args]
                res = subprocess.run(
                    cmd, check=False, input=script, capture_output=True, text=True, encoding="utf-8", timeout=40,
                    cwd=runtime_path, env=browser_environment,
                )
                if res.returncode:
                    raise RuntimeError(f"agent-browser failed ({res.returncode}): {res.stderr or res.stdout}")
                payload = json.loads(res.stdout)
                if not payload.get("success"):
                    raise RuntimeError(f"agent-browser error: {payload}")
                return payload.get("data", {})

            # Fresh uniquely generated session opens directly; daemon must not be pre-closed.

        def evaluate(js: str) -> Any:
            return browser("eval", "--stdin", script=js).get("result")

        def wait_for(expr: str, timeout_s: float = 12.0) -> Any:
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                res = evaluate(f"Boolean({expr})")
                if bool(res):
                    return True
                time.sleep(0.05)
            raise TimeoutError(f"Condition timed out after {timeout_s}s: {expr}")

        logger.log("Navigating to isolated workspace origin...")
        browser("open", origin, "--init-script", str(init_script_path))
        browser("set", "viewport", "1280", "800")
        wait_for(
            "document.body.textContent.includes('Live Tracker') || "
            "document.body.textContent.includes('SYNTHETIC') || "
            "document.body.textContent.includes('REAL CAMERA')"
        )
        logger.log("App loaded into Live Tracker Studio view.")

        # ========================================================
        # CHECK 1: Real Camera Missing Kinematics Unavailable State
        # ========================================================
        logger.log("CHECK 1: Verifying UNAVAILABLE metrics under real camera feed without kinematics...")
        wait_for("document.body.textContent.includes('REAL CAMERA')")

        pose_status_text = evaluate("document.querySelector('.uw-pose-status')?.textContent || ''")
        logger.log(f"Pose status line: {pose_status_text}")
        assert "Left knee UNAVAILABLE" in pose_status_text, f"Left knee must be UNAVAILABLE, got: {pose_status_text}"
        assert "Right knee UNAVAILABLE" in pose_status_text, f"Right knee must be UNAVAILABLE, got: {pose_status_text}"

        twin_unavail_text = evaluate("document.querySelector('.uw-twin-viewport')?.textContent || ''")
        logger.log(f"Digital Twin text in real camera: {twin_unavail_text}")
        assert "3D motion UNAVAILABLE" in twin_unavail_text, "3D motion should be unavailable when 3D points are missing"

        finish_btn_disabled = evaluate("document.querySelector('.uw-btn-finish-set')?.disabled")
        logger.log(f"Finish button disabled state: {finish_btn_disabled}")
        assert finish_btn_disabled is True, "Finish button must be disabled when no measured set data is available"

        finish_btn_opacity = evaluate(
            "parseFloat(window.getComputedStyle(document.querySelector('.uw-btn-finish-set')).opacity)"
        )
        logger.log(f"Finish button disabled computed opacity: {finish_btn_opacity}")
        assert finish_btn_opacity <= 0.5, f"Disabled finish button must have opacity <= 0.5, got {finish_btn_opacity}"

        # Test synthetic getUserMedia denial stub to observe it rejects safely without touching hardware
        logger.log("Verifying synthetic getUserMedia rejection stub...")
        stub_rejection = evaluate("""(async () => {
  try {
    await navigator.mediaDevices.getUserMedia({ video: true });
    return 'allowed';
  } catch (e) {
    return e.name;
  }
})()""")
        logger.log(f"Synthetic getUserMedia denial stub response: {stub_rejection}")
        assert stub_rejection == "NotAllowedError", f"Expected NotAllowedError from stub, got: {stub_rejection}"
        receipt["permissions"]["synthetic_get_user_media_stub"]["denial_tested"] = True

        ss_unavail = out_dir / "01-metric-unavailable.png"
        browser("screenshot", str(ss_unavail))
        receipt["screenshots"]["metric_unavailable"] = str(ss_unavail)
        receipt["checks"]["metric_unavailable_never_zero"] = True
        receipt["checks"]["finish_button_disabled_appearance"] = {
            "disabled": finish_btn_disabled,
            "opacity": finish_btn_opacity,
        }
        logger.log("CHECK 1 PASSED.")

        # ========================================================
        # CHECK 2: Synthetic Feed, 3D Digital Twin Attribution & Target Zone
        # ========================================================
        logger.log("CHECK 2: Switching to synthetic feed and verifying Digital Twin attribution...")
        browser("find", "role", "button", "click", "--name", "Feed: REAL CAMERA", "--exact")
        wait_for(
            "document.body.textContent.includes('Feed: SYNTHETIC TEST') || "
            "document.body.textContent.includes('SYNTHETIC SQUATS ANIMATION')"
        )

        twin_container_text = evaluate("document.querySelector('.uw-live-twin-container')?.textContent || ''")
        expected_attribution = (
            "3D Digital Twin · Model-derived avatar (derived/2D/unverified); "
            "muscle activity NOT MEASURED · Drag to rotate · Scroll to zoom"
        )
        logger.log(f"Digital twin container text: {twin_container_text}")
        assert expected_attribution in twin_container_text, (
            f"Digital twin must display exact attribution notice. Got: {twin_container_text}"
        )

        finish_btn_now_enabled = evaluate("document.querySelector('.uw-btn-finish-set')?.disabled === false")
        assert finish_btn_now_enabled is True, "Finish Synthetic Set button should be enabled in synthetic test mode"

        ss_twin = out_dir / "02-digital-twin-disclaimer.png"
        browser("screenshot", str(ss_twin))
        receipt["screenshots"]["digital_twin_attribution"] = str(ss_twin)
        receipt["checks"]["digital_twin_disclaimer_verified"] = True
        logger.log("CHECK 2 PASSED.")

        # ========================================================
        # CHECK 2B: Avatar Toggle & WebGL Lifecycle Teardown / Recreation
        # ========================================================
        logger.log("CHECK 2B: Verifying 3D Avatar collapsible control and WebGL canvas unmount/remount...")
        avatar_btn_text_initial = evaluate(
            "document.querySelector('button[aria-label=\"Toggle 3D Digital Twin avatar\"]')?.textContent || ''"
        )
        logger.log(f"Avatar toggle button text initially: {avatar_btn_text_initial}")
        assert "3D Avatar: ON" in avatar_btn_text_initial, f"Expected '3D Avatar: ON', got: {avatar_btn_text_initial}"

        has_canvas_initial = evaluate("document.querySelector('.uw-twin-viewport canvas') !== null")
        logger.log(f"Canvas present initially: {has_canvas_initial}")
        assert has_canvas_initial is True, "WebGL canvas must be mounted when 3D Avatar is ON"

        # Toggle 3D Avatar OFF
        logger.log("Toggling 3D Avatar OFF...")
        evaluate("document.querySelector('button[aria-label=\"Toggle 3D Digital Twin avatar\"]')?.click()")
        wait_for("document.querySelector('button[aria-label=\"Toggle 3D Digital Twin avatar\"]')?.textContent.includes('OFF')")

        avatar_btn_text_off = evaluate(
            "document.querySelector('button[aria-label=\"Toggle 3D Digital Twin avatar\"]')?.textContent || ''"
        )
        logger.log(f"Avatar toggle button text after collapse: {avatar_btn_text_off}")
        assert "3D Avatar: OFF" in avatar_btn_text_off, f"Expected '3D Avatar: OFF', got: {avatar_btn_text_off}"

        canvas_unmounted = evaluate("document.querySelector('.uw-twin-viewport canvas') === null")
        logger.log(f"Canvas unmounted from DOM: {canvas_unmounted}")
        assert canvas_unmounted is True, "WebGL canvas must be unmounted from DOM when avatar is collapsed"

        placeholder_text = evaluate("document.querySelector('.uw-twin-collapsed-placeholder')?.textContent || ''")
        logger.log(f"Collapsed placeholder text: {placeholder_text}")
        assert "3D Digital Twin collapsed to preserve resources" in placeholder_text, (
            f"Collapsed placeholder missing expected notice: {placeholder_text}"
        )
        assert "Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED" in placeholder_text, (
            f"Collapsed placeholder missing unverified/NOT MEASURED disclaimer: {placeholder_text}"
        )

        finish_still_enabled = evaluate("document.querySelector('.uw-btn-finish-set')?.disabled === false")
        logger.log(f"Finish button still enabled while avatar collapsed: {finish_still_enabled}")
        assert finish_still_enabled is True, "Nonvisual tracking/recording must continue while avatar is collapsed"

        ss_collapsed = out_dir / "02b-avatar-collapsed.png"
        browser("screenshot", str(ss_collapsed))
        receipt["screenshots"]["avatar_collapsed"] = str(ss_collapsed)

        # Toggle 3D Avatar back ON
        logger.log("Toggling 3D Avatar back ON...")
        evaluate("document.querySelector('button[aria-label=\"Toggle 3D Digital Twin avatar\"]')?.click()")
        wait_for("document.querySelector('button[aria-label=\"Toggle 3D Digital Twin avatar\"]')?.textContent.includes('ON')")

        wait_for("document.querySelector('.uw-twin-viewport canvas') !== null")
        canvas_remounted = evaluate("document.querySelector('.uw-twin-viewport canvas') !== null")
        placeholder_removed = evaluate("document.querySelector('.uw-twin-collapsed-placeholder') === null")
        logger.log(f"Canvas remounted: {canvas_remounted}, placeholder removed: {placeholder_removed}")
        assert canvas_remounted is True, "WebGL canvas must be remounted when 3D Avatar is toggled back ON"
        assert placeholder_removed is True, "Collapsed placeholder must be removed when avatar is restored"

        ss_remounted = out_dir / "02c-avatar-remounted.png"
        browser("screenshot", str(ss_remounted))
        receipt["screenshots"]["avatar_remounted"] = str(ss_remounted)

        receipt["checks"]["avatar_lifecycle_teardown_recreation"] = {
            "initial_canvas_mounted": True,
            "collapsed_button_text": avatar_btn_text_off.strip(),
            "canvas_unmounted_on_collapse": canvas_unmounted,
            "placeholder_notice_verified": True,
            "nonvisual_operation_continued": finish_still_enabled,
            "canvas_remounted_on_restore": canvas_remounted,
            "placeholder_removed_on_restore": placeholder_removed,
        }
        logger.log("CHECK 2B PASSED.")

        # ========================================================
        # CHECK 2C: Mounted-Browser Real WebGL Context Loss & Restoration (N03)
        # ========================================================
        logger.log("CHECK 2C: Exercising real WebGL context loss and restoration on mounted Digital Twin...")

        # Step 1: Capture active WebGL draw progression before loss
        time.sleep(0.2)
        draws_before = evaluate("window.__kinelab_webgl_draw_count || 0")
        logger.log(f"WebGL draw calls before context loss: {draws_before}")
        assert draws_before > 0, f"Expected WebGL draw calls before context loss (got {draws_before})"

        # Step 2: Trigger real context loss strictly via WEBGL_lose_context extension
        loss_result = evaluate("""(() => {
  const canvas = window.__kinelab_active_canvas || document.querySelector('.uw-twin-viewport canvas');
  if (!canvas) return { success: false, error: 'Canvas element not found' };
  const gl = window.__kinelab_active_gl || canvas.__kinelab_gl || canvas.getContext('webgl2') || canvas.getContext('webgl');
  if (!gl) return { success: false, error: 'WebGL context not found' };
  if (gl.isContextLost()) return { success: false, error: 'WebGL context already lost before test' };
  const ext = gl.getExtension('WEBGL_lose_context') || gl.getExtension('WEBKIT_WEBGL_lose_context');
  if (!ext) return { success: false, error: 'WEBGL_lose_context extension unavailable' };
  ext.loseContext();
  return { success: true, isLost: gl.isContextLost() };
})()""")
        if not loss_result.get("success"):
            err = loss_result.get("error", "Unknown error")
            raise RuntimeError(
                f"WEBGL_lose_context extension unavailable: real context loss cannot be exercised (BLOCKED/NOT_VERIFIED): {err}"
            )
        assert loss_result.get("isLost") is True, f"gl.isContextLost() must be true after ext.loseContext(), got: {loss_result}"

        # Step 3: Wait for context lost overlay
        wait_for("document.querySelector('.uw-twin-context-lost-overlay') !== null")
        overlay_present = evaluate("document.querySelector('.uw-twin-context-lost-overlay') !== null")
        logger.log(f"Context-lost overlay present: {overlay_present}")
        assert overlay_present is True, "WebGL context-lost overlay must appear when context is lost"

        # Step 4: Prove WebGL draw calls are paused (zero draw delta) while real 2D synthetic tracking progresses
        draws_at_loss = evaluate("window.__kinelab_webgl_draw_count || 0")
        metric_at_loss = evaluate("document.querySelector('output[aria-label=\"Current exercise metric\"], .uw-hud-rom-metric')?.textContent || ''")
        logger.log(f"Draw calls at context loss: {draws_at_loss}, HUD metric at loss: {metric_at_loss}")

        # Bounded polling loop (up to 1.5s, sleep 0.15s) until metric changes from metric_at_loss
        progression_deadline = time.time() + 1.5
        metric_during_loss = metric_at_loss
        progression_observed = False
        while time.time() < progression_deadline:
            time.sleep(0.15)
            current_metric = evaluate("document.querySelector('output[aria-label=\"Current exercise metric\"], .uw-hud-rom-metric')?.textContent || ''")
            if current_metric and current_metric != metric_at_loss:
                metric_during_loss = current_metric
                progression_observed = True
                break

        draws_during_loss = evaluate("window.__kinelab_webgl_draw_count || 0")
        logger.log(
            f"Draw calls during loss: {draws_during_loss}, HUD metric during loss: {metric_during_loss}, "
            f"progression_observed: {progression_observed}"
        )

        assert progression_observed is True, (
            f"Synthetic 2D tracking progression must be observed during context loss (metric remained '{metric_at_loss}')"
        )
        draw_delta = draws_during_loss - draws_at_loss
        assert draw_delta == 0, f"WebGL rendering must be suspended during context loss (draw calls increased by {draw_delta})"

        finish_during_loss = evaluate("document.querySelector('.uw-btn-finish-set')?.disabled === false")
        logger.log(f"Finish button still enabled during context loss: {finish_during_loss}")
        assert finish_during_loss is True, "Finish button must remain enabled during WebGL context loss"

        receipt["checks"]["synthetic_tracking_progression"] = {
            "metric_before_loss": metric_at_loss,
            "metric_during_loss": metric_during_loss,
            "draws_at_loss": draws_at_loss,
            "draws_during_loss": draws_during_loss,
            "draw_delta": draw_delta,
            "progression_verified": bool(progression_observed and draw_delta == 0),
        }

        ss_context_lost = out_dir / "02c-digital-twin-context-lost.png"
        browser("screenshot", str(ss_context_lost))
        receipt["screenshots"]["digital_twin_context_lost"] = str(ss_context_lost)

        # Step 5: Exercise restoration via the real supported recreate action button
        logger.log("Exercising restore action via .uw-twin-btn-restore button...")
        evaluate("document.querySelector('.uw-twin-btn-restore')?.click()")
        wait_for("document.querySelector('.uw-twin-context-lost-overlay') === null")

        canvas_restored = evaluate("document.querySelector('.uw-twin-viewport canvas') !== null")
        overlay_dismissed = evaluate("document.querySelector('.uw-twin-context-lost-overlay') === null")
        finish_after_restore = evaluate("document.querySelector('.uw-btn-finish-set')?.disabled === false")
        logger.log(
            f"Restoration results: canvas_restored={canvas_restored}, "
            f"overlay_dismissed={overlay_dismissed}, finish_enabled={finish_after_restore}"
        )
        assert canvas_restored is True, "Canvas must be restored after clicking Restore 3D View"
        assert overlay_dismissed is True, "Context-lost overlay must be dismissed after restoration"
        assert finish_after_restore is True, "Finish button must remain enabled after restoration"

        # Step 6: Prove WebGL draw progression resumed after restore
        time.sleep(0.25)
        draws_after_restore = evaluate("window.__kinelab_webgl_draw_count || 0")
        logger.log(f"Draw calls after restore: {draws_after_restore}")
        assert draws_after_restore > draws_during_loss, (
            f"WebGL draw progression must resume after restore (got {draws_after_restore} vs {draws_during_loss})"
        )

        receipt["checks"]["webgl_context_loss_and_restore_verified"] = {
            "draws_before_loss": draws_before,
            "draws_during_loss_static": draws_during_loss == draws_at_loss,
            "draw_calls_suspended_count": draws_during_loss,
            "draws_resumed_after_restore": draws_after_restore > draws_during_loss,
            "draws_final_count": draws_after_restore,
            "synthetic_2d_tracking_continued": bool(
                progression_observed and finish_during_loss and finish_after_restore
            ),
            "context_lost_overlay_displayed": overlay_present,
            "context_lost_overlay_dismissed": overlay_dismissed,
            "recreate_action_tested": True,
        }
        logger.log("CHECK 2C PASSED.")

        # ========================================================
        # CHECK 3: Modal Dialog Focus Trap, Escape, Focus Return
        # ========================================================
        logger.log("CHECK 3: Verifying LiveSetSummaryModal focus trap, Escape dismissal, and focus return...")
        trigger_button = evaluate("document.querySelector('.uw-btn-finish-set') !== null")
        assert trigger_button, "Finish button must be present"

        browser("find", "role", "button", "click", "--name", "Finish Synthetic Set", "--exact")
        wait_for("document.querySelector('dialog')?.open === true")

        modal_open = evaluate("document.querySelector('dialog')?.open === true")
        is_aria_modal = evaluate("document.querySelector('dialog')?.getAttribute('aria-modal') === 'true'")
        assert modal_open is True, "Modal dialog must be open"
        assert is_aria_modal is True, "Modal dialog must have aria-modal='true'"

        focus_inside = evaluate("document.querySelector('dialog').contains(document.activeElement)")
        logger.log(f"Focus initially inside dialog: {focus_inside}")
        assert focus_inside is True, "Focus must be moved into the modal dialog upon opening"

        # Bound the mounted card, then reach real content with native keyboard scrolling.
        vertical_viewports = []
        for width, height in ((320, 568), (568, 320)):
            browser("set", "viewport", str(width), str(height))
            wait_for(f"window.innerWidth === {width} && window.innerHeight === {height}")
            contained = evaluate("""(() => {
  const card = document.querySelector('dialog[open] .uw-modal-card');
  if (!card || card.children.length !== 3) return false;
  const [header, body, footer] = card.children;
  const fits = element => {
    if (!element) return false;
    const r = element.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.left >= -1 && r.right <= innerWidth + 1
      && r.top >= -1 && r.bottom <= innerHeight + 1;
  };
  const textFits = element => {
    const range = document.createRange(); range.selectNodeContents(element);
    return [...range.getClientRects()].every(r => r.top >= -1 && r.bottom <= innerHeight + 1
      && r.left >= -1 && r.right <= innerWidth + 1);
  };
  const h = header.getBoundingClientRect(), b = body.getBoundingClientRect(), f = footer.getBoundingClientRect();
  return [card, header, body, footer, header.querySelector('[data-dialog-close]'),
    ...footer.querySelectorAll('button')].every(fits)
    && [header.querySelector('h2'), header.querySelector('[data-dialog-close]'),
      ...footer.querySelectorAll('button')].every(element => element && textFits(element))
    && body.clientHeight > 0 && b.top >= h.bottom - 1 && b.bottom <= f.top + 1;
})()""")
            assert contained is True, f"Summary header, close, footer and body must fit vertically at {width}x{height}"
            evaluate("document.querySelector('dialog[open] [data-dialog-close]').focus()")
            browser("press", "Tab")
            assert evaluate("document.activeElement === document.querySelector('dialog[open] .uw-modal-card').children[1]") is True, "Tab from Close must reach the scrollable summary body"
            body_visible = """(target => {
  const body = document.querySelector('dialog[open] .uw-modal-card').children[1];
  const element = target === 'warning'
    ? [...body.querySelectorAll('[role="status"]')].find(el => el.textContent.includes('SYNTHETIC TEST ONLY.'))
    : [...body.querySelectorAll('span')].find(el => el.textContent.trim() === 'Set Time')?.parentElement.querySelector('small');
  if (!element || !element.textContent.trim()) return false;
  const b = body.getBoundingClientRect(), r = element.getBoundingClientRect();
  const range = document.createRange(); range.selectNodeContents(element);
  const rects = [...range.getClientRects()];
  return r.height > 0 && r.top >= b.top - 1 && r.bottom <= b.bottom + 1
    && rects.length > 0 && rects.every(t => t.top >= b.top - 1 && t.bottom <= b.bottom + 1
      && t.left >= b.left - 1 && t.right <= b.right + 1);
})"""
            browser("press", "Home")
            wait_for("document.querySelector('dialog[open] .uw-modal-card').children[1].scrollTop <= 1")
            browser("press", "End")
            wait_for(body_visible + "('warning')")
            assert evaluate("document.querySelector('dialog[open] .uw-modal-card').children[1].scrollTop > 0") is True, "Native End must actually scroll the summary body"
            warning_screenshot = out_dir / f"03-modal-warning-{width}x{height}.png"
            browser("screenshot", str(warning_screenshot))
            receipt["screenshots"][f"modal_warning_{width}x{height}"] = str(warning_screenshot)
            browser("press", "Home")
            wait_for("document.querySelector('dialog[open] .uw-modal-card').children[1].scrollTop <= 1")
            for _ in range(24):
                if evaluate(body_visible + "('last_metric')") is True:
                    break
                browser("press", "PageDown")
                time.sleep(0.1)
            assert evaluate(body_visible + "('last_metric')") is True, "Elapsed test time description must be reachable by native paging"
            metric_screenshot = out_dir / f"03-modal-last-description-{width}x{height}.png"
            browser("screenshot", str(metric_screenshot))
            receipt["screenshots"][f"modal_last_description_{width}x{height}"] = str(metric_screenshot)
            vertical_viewports.append({"width": width, "height": height, "chrome_contained": True,
                                       "warning_reached_by_end": True, "last_description_reached_by_paging": True})
            browser("press", "Home")
            wait_for("document.querySelector('dialog[open] .uw-modal-card').children[1].scrollTop <= 1")
        browser("set", "viewport", "1280", "800")
        wait_for("window.innerWidth === 1280 && window.innerHeight === 800")
        evaluate("document.querySelector('dialog[open] [data-dialog-close]').focus()")
        receipt["checks"]["modal_vertical_access"] = vertical_viewports

        modal_focusables = """
  const dialog = document.querySelector('dialog');
  const controls = [...dialog.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])')]
    .filter(element => !element.hidden && element.getClientRects().length > 0);
"""
        boundary = evaluate("(() => {" + modal_focusables + """
  controls.at(-1)?.focus();
  return {count: controls.length, lastFocused: document.activeElement === controls.at(-1)};
})()""")
        assert boundary["count"] > 1 and boundary["lastFocused"] is True, "Modal must expose distinct focus boundaries"
        browser("press", "Tab")
        forward_tab = evaluate("(() => {" + modal_focusables + "return document.activeElement === controls[0];})()")
        assert forward_tab is True, "Native Tab from the last modal control must wrap to the first"
        browser("press", "Shift+Tab")
        reverse_tab = evaluate("(() => {" + modal_focusables + "return document.activeElement === controls.at(-1);})()")
        assert reverse_tab is True, "Native Shift+Tab from the first modal control must wrap to the last"
        tab_result = forward_tab is True and reverse_tab is True
        assert tab_result is True, "Tab navigation must keep focus trapped inside the dialog"
        receipt["checks"]["modal_native_tab_boundaries"] = {"controls": boundary["count"], "forward": forward_tab,
                                                            "reverse": reverse_tab}

        # All four real mounted metrics must fit without horizontal scrolling.
        # Vertical scrolling in the existing modal body remains allowed on phones.
        metric_viewports = []
        for width, height in ((1280, 800), (390, 844), (320, 568)):
            browser("set", "viewport", str(width), str(height))
            wait_for(f"window.innerWidth === {width} && window.innerHeight === {height}")
            metrics_visible = evaluate("""(() => {
  const dialog = document.querySelector('dialog[open]');
  if (!dialog) return false;
  const labels = ['Total Reps', 'Average Depth', 'Best Depth', 'Set Time'];
  const cards = labels.map(label => [...dialog.querySelectorAll('span')]
    .find(element => element.textContent.trim() === label)?.parentElement);
  if (cards.some(card => !card) || new Set(cards).size !== 4) return false;
  // The real synthetic empty-set fixture exercises the wide missing-value text.
  if (cards.filter(card => card.querySelector('strong')?.textContent.trim() === 'UNAVAILABLE').length < 2) return false;
  return cards.every(card => {
    const bounds = card.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0 || bounds.left < -1 || bounds.right > innerWidth + 1) return false;
    // A card outside any containing box can be clipped despite a fitting page.
    for (let parent = card.parentElement; parent; parent = parent.parentElement) {
      const clip = parent.getBoundingClientRect();
      if (bounds.left < clip.left - 1 || bounds.right > clip.right + 1) return false;
      if (parent === dialog) break;
    }
    const fields = [...card.children];
    if (fields.length !== 3) return false;
    return fields.every(field => {
      if (!field.textContent.trim() || getComputedStyle(field).visibility !== 'visible') return false;
      const range = document.createRange();
      range.selectNodeContents(field);
      const rects = [...range.getClientRects()];
      return rects.length > 0 && rects.every(rect => rect.width > 0 && rect.height > 0
        && rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1);
    });
  });
})()""")
            assert metrics_visible is True, (
                f"Every summary metric label, value and description must fit horizontally at {width}x{height}"
            )
            metric_viewports.append({"width": width, "height": height, "all_four_metrics_fit": True})
            metric_screenshot = out_dir / f"03-modal-metrics-{width}x{height}.png"
            browser("screenshot", str(metric_screenshot))
            receipt["screenshots"][f"modal_metrics_{width}x{height}"] = str(metric_screenshot)
        browser("set", "viewport", "1280", "800")
        wait_for("window.innerWidth === 1280 && window.innerHeight === 800")
        receipt["checks"]["modal_metric_horizontal_visibility"] = metric_viewports

        ss_modal_open = out_dir / "03-modal-dialog-open.png"
        browser("screenshot", str(ss_modal_open))
        receipt["screenshots"]["modal_open"] = str(ss_modal_open)

        logger.log("Testing Escape key dismissal and focus return...")
        browser("press", "Escape")
        wait_for("document.querySelector('dialog') === null || document.querySelector('dialog')?.open === false")

        modal_closed = evaluate("document.querySelector('dialog') === null || !document.querySelector('dialog')?.open")
        assert modal_closed is True, "Escape must close the modal dialog"

        focus_returned = evaluate("""(() => {
  const active = document.activeElement;
  return active && active.classList.contains('uw-btn-finish-set');
})()""")
        logger.log(f"Focus returned to trigger finish button: {focus_returned}")
        assert focus_returned is True, "Focus must return to the triggering element after dialog dismissal"

        ss_modal_closed = out_dir / "04-modal-dialog-closed.png"
        browser("screenshot", str(ss_modal_closed))
        receipt["screenshots"]["modal_closed"] = str(ss_modal_closed)
        receipt["checks"]["modal_trap_escape_focus_return"] = True
        logger.log("CHECK 3 PASSED.")

        # ========================================================
        # CHECK 4: Transparent File Upload Keyboard Focus Visibility
        # ========================================================
        logger.log("CHECK 4: Verifying visible focus styling for transparent file upload controls...")
        evaluate("""(() => {
  const navBtns = Array.from(document.querySelectorAll('.uw-sidebar nav button, .uw-nav-link'));
  const captureBtn = navBtns.find(b => b.textContent.includes('Capture'));
  if (captureBtn) captureBtn.click();
})()""")
        wait_for("!!document.querySelector('.uw-capture-wizard')")
        wait_for("document.querySelector('.uw-upload-btn input[type=file]') !== null")

        evaluate("document.querySelector('.uw-flight-check-card button')?.focus();")
        browser("press", "Tab")
        if not evaluate("document.activeElement === document.querySelector('.uw-upload-btn input[type=file]')"):
            browser("press", "Tab")

        active_is_upload = evaluate("document.activeElement === document.querySelector('.uw-upload-btn input[type=file]')")
        logger.log(f"Active element is upload input: {active_is_upload}")
        assert active_is_upload is True, "Tab navigation must land on the file upload control"

        upload_focus_verified = evaluate(r"""(() => {
  const fileInput = document.querySelector('.uw-upload-btn input[type=file]');
  const btn = fileInput.closest('.uw-upload-btn');
  const btnStyle = window.getComputedStyle(btn);
  const inputStyle = window.getComputedStyle(fileInput);
  const rect = btn.getBoundingClientRect();
  const color = btnStyle.outlineColor.match(/^rgba?\(([^)]+)\)$/);
  const channels = color ? color[1].split(',').map(Number) : [];
  const outlineAlpha = channels.length === 4 ? channels[3] : channels.length === 3 ? 1 : 0;
  const btnVisible = rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
    rect.left < window.innerWidth && rect.top < window.innerHeight && btnStyle.display !== 'none' &&
    btnStyle.visibility === 'visible' && Number(btnStyle.opacity) > 0;
  return {
    btnOutlineStyle: btnStyle.outlineStyle,
    btnOutlineWidth: btnStyle.outlineWidth,
    btnBoxShadow: btnStyle.boxShadow,
    inputOutlineStyle: inputStyle.outlineStyle,
    inputOutlineWidth: inputStyle.outlineWidth,
    btnOutlineColor: btnStyle.outlineColor,
    btnVisible,
    btnOutlineVisible: btnVisible && parseFloat(btnStyle.outlineWidth) > 0 &&
      !['none', 'hidden'].includes(btnStyle.outlineStyle) && outlineAlpha > 0,
  };
})()""")
        logger.log(f"Upload button focus evaluation: {upload_focus_verified}")
        has_visible_focus = upload_focus_verified.get("btnOutlineVisible") is True
        assert has_visible_focus, f"Visible focus styling required on .uw-upload-btn: {upload_focus_verified}"

        ss_upload = out_dir / "05-upload-keyboard-focus.png"
        browser("screenshot", str(ss_upload))
        receipt["screenshots"]["upload_focus"] = str(ss_upload)
        receipt["checks"]["upload_focus_visible"] = upload_focus_verified
        logger.log("CHECK 4 PASSED.")

        # ========================================================
        # CHECK 5: Responsive Viewports (Portrait and Landscape)
        # ========================================================
        logger.log("CHECK 5: Verifying responsive viewports...")
        desktop_layout = evaluate(
            "window.innerWidth >= 1200 && window.getComputedStyle(document.querySelector('.uw-sidebar')).display !== 'none'"
        )
        assert desktop_layout is True, "Desktop viewport must show sidebar"
        ss_desktop = out_dir / "06-viewport-desktop.png"
        browser("screenshot", str(ss_desktop))
        receipt["screenshots"]["viewport_desktop"] = str(ss_desktop)

        viewport_checks: list[dict[str, Any]] = []
        receipt["checks"]["responsive_viewports"] = {
            "desktop_1280x800": True,
            "viewports": viewport_checks,
            "real_browser_zoom": "NOT_RUN",
        }
        for width, height in ((320, 568), (568, 320), (390, 844), (844, 390),
                              (768, 1024), (1024, 768), (1024, 1366), (1366, 1024),
                              (1440, 1920), (1920, 1440)):
            logger.log(f"Testing responsive viewport {width}x{height}...")
            browser("set", "viewport", str(width), str(height))
            wait_for(f"window.innerWidth === {width} && window.innerHeight === {height}")
            observed = evaluate("""(() => {
  const nav = document.querySelector('.uw-sidebar nav, nav[aria-label="KineLab views"]');
  const links = document.querySelectorAll('.uw-nav-link');
  const navControlsVisible = nav !== null && window.getComputedStyle(nav).display !== 'none';
  const linksCount = links.length;
  const scrollWidth = document.documentElement.scrollWidth;
  const clientWidth = document.documentElement.clientWidth;
  return {
    navControlsVisible,
    linksCount,
    scrollWidth,
    clientWidth,
    width: window.innerWidth,
    height: window.innerHeight,
  };
})()""")
            logger.log(f"Responsive navigation and overflow checks: {observed}")
            viewport_checks.append({"requested": {"width": width, "height": height},
                                    "observed": observed})
            screenshot = out_dir / f"07-viewport-{width}x{height}.png"
            browser("screenshot", str(screenshot))
            receipt["screenshots"][f"viewport_{width}x{height}"] = str(screenshot)
            assert observed["width"] == width and observed["height"] == height, (
                f"Browser viewport does not match requested dimensions: {observed}"
            )
            assert observed["navControlsVisible"] is True, f"Navigation must be visible at {width}x{height}"
            assert observed["linksCount"] > 0, f"Navigation links must be present at {width}x{height}"
            assert observed["scrollWidth"] <= observed["clientWidth"], (
                f"Page must not have horizontal overflow at {width}x{height}: {observed}"
            )
            if (width, height) == (390, 844):
                receipt["screenshots"]["viewport_mobile"] = str(screenshot)
                receipt["checks"]["responsive_viewports"].update(
                    mobile_390x844=True, mobile_nav_controls_visible=True, mobile_scroll_width_bounded=True)
        logger.log("CHECK 5 PASSED.")

        receipt["console"] = browser("console")
        receipt["page_errors"] = browser("errors")
        page_errs = receipt["page_errors"].get("errors", []) if isinstance(receipt["page_errors"], dict) else []
        assert not page_errs, f"Browser errors logged: {receipt['page_errors']}"

        # ========================================================
        # Network isolation & strict loopback URL audit
        # ========================================================
        logger.log("Auditing browser network requests for strict loopback isolation...")
        net_requests = browser("network", "requests")
        req_items = net_requests.get("requests", []) if isinstance(net_requests, dict) else []
        logger.log(f"Observed {len(req_items)} browser network requests.")

        audit_network_requests(req_items, server_port)

        receipt["network"]["observed_request_count"] = len(req_items)
        receipt["network"]["external_calls_detected"] = False
        receipt["network"]["observed_requests_sample"] = [
            {"method": r.get("method"), "url": r.get("url"), "status": r.get("status")}
            for r in req_items[:15]
        ]
        logger.log(
            f"Network isolation confirmed: strictly loopback targeting port {server_port} across {len(req_items)} calls."
        )

        receipt["status"] = "PASS"
        logger.log("All Isolated Browser Verification checks PASSED!")

    except BaseException as err:  # noqa: BLE001 -- preserve the primary error through all cleanup attempts, then re-raise
        original_error = err
        receipt["status"] = "FAIL"
        receipt["error"] = str(err)
        cleanup_log(f"Browser Verification FAILED: {err}")

    finally:
        # Step 1: Independent browser close attempt (NEVER swallow error)
        try:
            if "browser" in locals():
                browser("close")
            cleanup_steps["browser_closed"] = True
            cleanup_log("Browser closed successfully.")
        except Exception as ex:  # noqa: BLE001
            cleanup_steps["browser_closed"] = False
            cleanup_errors.append(f"browser_close: {ex}")
            cleanup_log(f"Browser close error recorded: {ex}")

        # Step 2: Server shutdown attempt
        if server is not None:
            try:
                if thread is not None and thread.is_alive():
                    server.shutdown()
                cleanup_steps["server_shutdown"] = True
                cleanup_log("Server shutdown completed.")
            except Exception as ex:  # noqa: BLE001
                cleanup_steps["server_shutdown"] = False
                cleanup_errors.append(f"server_shutdown: {ex}")
                cleanup_log(f"Server shutdown error recorded: {ex}")
        else:
            cleanup_steps["server_shutdown"] = True

        # Step 3: Server socket close attempt
        if server is not None:
            try:
                server.server_close()
                cleanup_steps["server_closed"] = True
                cleanup_log("Server socket closed.")
            except Exception as ex:  # noqa: BLE001
                cleanup_steps["server_closed"] = False
                cleanup_errors.append(f"server_close: {ex}")
                cleanup_log(f"Server close error recorded: {ex}")
        else:
            cleanup_steps["server_closed"] = True

        # Step 4: Server thread join attempt
        if thread is not None:
            try:
                thread.join(timeout=5)
                thread_dead = not thread.is_alive()
                cleanup_steps["thread_joined"] = thread_dead
                cleanup_steps["server_thread_dead"] = thread_dead
                if not thread_dead:
                    cleanup_errors.append("server_thread: thread still alive after join timeout")
                cleanup_log(f"Server thread joined (alive={thread.is_alive()}).")
            except Exception as ex:  # noqa: BLE001
                cleanup_steps["thread_joined"] = False
                cleanup_steps["server_thread_dead"] = False
                cleanup_errors.append(f"thread_join: {ex}")
                cleanup_log(f"Server thread join error recorded: {ex}")
        else:
            cleanup_steps["thread_joined"] = True
            cleanup_steps["server_thread_dead"] = True

        # Step 5: Service close attempt
        if service is not None:
            try:
                service.close()
                cleanup_steps["service_closed"] = True
                cleanup_log("Service closed.")
            except Exception as ex:  # noqa: BLE001
                cleanup_steps["service_closed"] = False
                cleanup_errors.append(f"service_close: {ex}")
                cleanup_log(f"Service close error recorded: {ex}")
        else:
            cleanup_steps["service_closed"] = True

        # Step 6: Temporary directory cleanup
        try:
            init_script_path.unlink(missing_ok=True)
            config_path.unlink(missing_ok=True)
        except Exception as ex:  # noqa: BLE001
            cleanup_errors.append(f"init_script_unlink: {ex}")

        try:
            if temp_dir_obj is not None:
                temp_dir_obj.cleanup()
            cleanup_steps["temp_directory_cleaned"] = True
            cleanup_log("Temporary directory cleanup completed.")
        except Exception as ex:  # noqa: BLE001
            cleanup_steps["temp_directory_cleaned"] = False
            cleanup_errors.append(f"temp_dir_cleanup: {ex}")
            cleanup_log(f"Temporary directory cleanup error: {ex}")

        # Step 7: Post-cleanup observations (verified AFTER context exit)
        try:
            cleanup_steps["root_directory_absent"] = not runtime_path.exists()
            cleanup_steps["init_script_absent"] = not init_script_path.exists()
            if not cleanup_steps["root_directory_absent"] or not cleanup_steps["init_script_absent"]:
                cleanup_errors.append("owned_runtime_or_init_script_still_exists")
        except Exception as ex:  # noqa: BLE001 -- preserve primary error and continue postconditions
            cleanup_errors.append(f"owned_path_postconditions: {type(ex).__name__}")

        try:
            cleanup_steps["listener_terminated"] = server_port <= 0 or verify_listener_terminated("127.0.0.1", server_port)
            if not cleanup_steps["listener_terminated"]:
                cleanup_errors.append("owned_listener_still_accepting")
        except Exception as ex:  # noqa: BLE001 -- independent listener evidence must not replace the primary error
            cleanup_errors.append(f"listener_postcondition: {type(ex).__name__}")

        try:
            build_after = _frontend_inventory(viewer_dist)
            receipt["build_inventory_after"] = build_after
            cleanup_steps["frontend_unchanged"] = build_before == build_after
            if not cleanup_steps["frontend_unchanged"]:
                cleanup_errors.append("frontend_changed_during_verification")
        except Exception as ex:  # noqa: BLE001 -- preserve primary failure and finish evidence cleanup
            cleanup_errors.append(f"frontend_post_inventory: {type(ex).__name__}")

        cleanup_log("Cleanup attempts completed; closing the owned log before the final receipt.")
        try:
            logger.close()
        except Exception as ex:  # noqa: BLE001 -- receipt still records the independent close fault
            cleanup_errors.append(f"logger_close: {type(ex).__name__}")

        # Overall cleanup verification decision
        cleanup_verified = (
            len(cleanup_errors) == 0
            and cleanup_steps.get("browser_closed", False)
            and cleanup_steps.get("server_shutdown", False)
            and cleanup_steps.get("server_closed", False)
            and cleanup_steps.get("server_thread_dead", False)
            and cleanup_steps.get("service_closed", False)
            and cleanup_steps.get("temp_directory_cleaned", False)
            and cleanup_steps.get("root_directory_absent", False)
            and cleanup_steps.get("init_script_absent", False)
            and cleanup_steps.get("listener_terminated", False)
            and cleanup_steps.get("frontend_unchanged", False)
        )
        cleanup_steps["cleanup_verified"] = cleanup_verified
        receipt["cleanup"] = cleanup_steps
        receipt["cleanup_errors"] = cleanup_errors

        if original_error is not None:
            receipt["status"] = "FAIL"
            receipt["error"] = str(original_error)
        elif not cleanup_verified:
            receipt["status"] = "FAIL"
            receipt["error"] = f"Cleanup verification failed: {'; '.join(cleanup_errors)}"

        receipt_file = out_dir / "receipt.json"
        try:
            with receipt_file.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(receipt, indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            if original_error is not None:
                raise original_error
            raise

        # Re-raise original error or raise cleanup failure
        if original_error is not None:
            raise original_error
        if not cleanup_verified:
            raise RuntimeError(f"Cleanup verification failed: {'; '.join(cleanup_errors)}")

    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="NEW dedicated directory beneath workspace dist")
    parser.add_argument("--log", type=Path, help="NEW file beneath --out; defaults to verification.log")
    parser.add_argument("--frontend-dist", type=Path, required=True, help="Existing admitted desktop build; never rebuilt")
    parser.add_argument("--agent-browser-executable", type=Path, required=True)
    parser.add_argument("--agent-browser-sha256", required=True)
    args = parser.parse_args()
    verify(args.out, args.log, frontend_dist=args.frontend_dist,
           agent_browser_executable=args.agent_browser_executable, agent_browser_sha256=args.agent_browser_sha256)
