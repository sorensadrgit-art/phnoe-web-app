"""KineLab PT single-icon v1 T6 startup, with authenticated localhost reuse.

Reuses only an existing KineLab T6 endpoint proving possession of this user's
instance token. A new instance binds exclusively to 127.0.0.1 and places the
secret in a browser URL fragment, never in a query string or server access log.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from uuid import uuid4

from runtime_config import (
    candidate_home,
    ensure_data_root,
    ensure_directory,
    is_reparse,
    runtime_identity,
    startup_lock,
)

ROOT = Path(__file__).resolve().parent
LOCAL = candidate_home() / "runtime"
STATE = LOCAL / "t6-instance.json"
LOG = LOCAL / "t6-server.log"
PORTS = range(4184, 4204)
SCHEMA = "kinelab.t6.instance.v2"

_SERVER_INSTANCE = None
_SERVER_RUNNING = threading.Event()
_SERVER_THREAD: threading.Thread | None = None
_SERVER_ERRORS: list[BaseException] = []


def port_free(port: int) -> bool:
    if type(port) is not int or not (1024 <= port <= 65535):
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        try:
            client.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def choose_available_port(ports=PORTS) -> int:
    for port in ports:
        if port_free(port):
            return port
    raise RuntimeError("No available local KineLab port. Close unused localhost applications before retrying.")


def read_state(path: Path | None = None) -> dict | None:
    path = STATE if path is None else Path(path)
    try:
        if is_reparse(path):
            return None
        return read_state_dict(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def get_health(instance: dict) -> dict:
    port, token = instance["port"], instance["token"]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/health",
        headers={"Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(req, timeout=0.7) as response:
        if response.status != 200:
            return {}
        return json.loads(response.read(2000))


def verified_running(instance: dict, *, expected_runtime_id: str | None = None) -> bool:
    if read_state_dict(instance) is None or instance["runtime_id"] != expected_runtime_id:
        return False
    try:
        health = get_health(instance)
        return (health.get("app") == "unified_t6" and
                health.get("local_only") is True and
                health.get("name") == "KineLab PT" and
                health.get("runtime_id") == expected_runtime_id)
    except (OSError, ValueError, TimeoutError, KeyError, TypeError):
        return False


def read_state_dict(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    if (data.get("schema") != SCHEMA or
            type(data.get("port")) is not int or
            not 1024 <= data["port"] <= 65535 or
            not isinstance(data.get("token"), str) or
            len(data["token"]) != 64 or
            any(ch not in "0123456789abcdef" for ch in data["token"]) or
            not isinstance(data.get("runtime_id"), str) or len(data["runtime_id"]) != 64 or
            any(ch not in "0123456789abcdef" for ch in data["runtime_id"])):
        return None
    return data


def _save_state(instance: dict):
    ensure_directory(LOCAL)
    staging = LOCAL / (".t6-instance." + uuid4().hex + ".partial")
    try:
        with staging.open("x", encoding="utf-8") as stream:
            json.dump(instance, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(staging, 0o600)
        except OSError:
            pass
        staging.replace(STATE)
    finally:
        staging.unlink(missing_ok=True)


def ensure_running(*, detached: bool = False, data_root: Path | None = None) -> tuple[str, bool]:
    selected_root = ensure_data_root(data_root)
    with startup_lock(LOCAL):
        return _ensure_running(detached=detached, data_root=selected_root)


def _remove_owned_state(instance: dict, *, _locked: bool = False):
    if not _locked:
        with startup_lock(LOCAL):
            return _remove_owned_state(instance, _locked=True)
    current = read_state()
    if current is not None and current == instance:
        STATE.unlink(missing_ok=True)


def _ensure_running(*, detached: bool, data_root: Path) -> tuple[str, bool]:
    global _SERVER_INSTANCE, _SERVER_THREAD
    current = read_state()
    expected = runtime_identity(data_root)
    if current and current["runtime_id"] != expected:
        raise RuntimeError("A different candidate installation or data root owns the instance state; inspect it before starting")
    if current and verified_running(current, expected_runtime_id=expected):
        return ("http://127.0.0.1:" + str(current["port"]) + "/#access=" + current["token"]), False
    if not (ROOT / "viewer" / "dist" / "index.html").is_file():
        raise FileNotFoundError("Unified frontend build missing; run npm --prefix viewer run build")
    ensure_directory(LOCAL)
    if STATE.exists():
        archival = LOCAL / ("t6-stale-" + uuid4().hex + ".json")
        try:
            STATE.replace(archival)
        except OSError:
            try:
                STATE.unlink(missing_ok=True)
            except OSError:
                pass
    chosen = choose_available_port()
    token = secrets.token_hex(32)
    state = {
        "schema": SCHEMA,
        "port": chosen,
        "token": token,
        "runtime_id": expected,
        "created_by": "local_single_icon_launcher"
    }
    _save_state(state)
    target_url = f"http://127.0.0.1:{chosen}/#access={token}"

    if detached:
        # Retain the launcher's selected interpreter; never discover another environment.
        interpreter = sys.executable
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )
        process = subprocess.Popen([
            str(interpreter), "-B", str(ROOT / "t6_server.py"),
            "--port", str(chosen), "--state", str(STATE),
            "--data-root", str(data_root),
        ], cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags)
        for _ in range(60):
            if verified_running(state, expected_runtime_id=expected):
                return target_url, True
            if process.poll() is not None:
                raise RuntimeError("Unified localhost service exited early; see local KineLabPT server log")
            time.sleep(0.20)
        raise TimeoutError("Unified localhost service did not accept its session token")

    # By default, run server directly in-process to guarantee rock-solid lifecycle
    from t6_server import make_server
    from t6_service import IntegratedService
    service = IntegratedService(projects_root=data_root)
    try:
        server = make_server(service, token=token, port=chosen, owns_service=True)
    except BaseException:
        service.close()
        _remove_owned_state(state, _locked=True)
        raise
    _SERVER_INSTANCE = server
    _SERVER_ERRORS.clear()
    _SERVER_RUNNING.set()

    def _serve():
        try:
            server.serve_forever(poll_interval=0.5)
        except BaseException as error:  # noqa: BLE001 - Retain worker failures while completing both cleanup actions.
            _SERVER_ERRORS.append(error)
        finally:
            for cleanup in (server.server_close, lambda: _remove_owned_state(state)):
                try:
                    cleanup()
                except BaseException as error:  # noqa: BLE001 - Cleanup must continue after cancellation or failure.
                    _SERVER_ERRORS.append(error)
            _SERVER_RUNNING.clear()

    server_thread = threading.Thread(target=_serve, daemon=True, name="KineLabServer")
    _SERVER_THREAD = server_thread
    server_thread.start()

    for _ in range(60):
        if verified_running(state, expected_runtime_id=expected):
            return target_url, True
        time.sleep(0.10)
    server.shutdown()
    server_thread.join(timeout=5)
    raise TimeoutError("Unified localhost service did not initialize in time")


def main():
    parser = argparse.ArgumentParser(description="KineLab PT unified desktop launcher")
    parser.add_argument("--no-browser", action="store_true", help="Start/verify without opening the page")
    parser.add_argument("--data-root", type=Path, help="Dedicated candidate data directory; no migration")
    parser.add_argument("--detached", "--no-wait", action="store_true", help="Launch detached subprocess without waiting")
    args = parser.parse_args()
    worker_before = _SERVER_THREAD
    try:
        try:
            url, fresh = ensure_running(detached=getattr(args, "detached", False), data_root=args.data_root)
            safe = url.split("#", 1)[0]
            if args.no_browser:
                print("T6_UNIFIED_READY=" + safe)
                print("T6_NEW_SERVER=" + str(fresh))
            else:
                if not webbrowser.open(url, new=2):
                    raise RuntimeError("Unable to open default browser to the local KineLab app")
                print("T6_UNIFIED_READY=" + safe)

            if fresh and not getattr(args, "detached", False):
                print(f"KineLab PT server running on {safe}")
                print("Ready for motion capture and analysis. Keep this process running or press Ctrl+C to shut down.")
                try:
                    while _SERVER_RUNNING.is_set():
                        time.sleep(0.5)
                except KeyboardInterrupt:
                    print("\nShutting down KineLab PT cleanly...")
                    if _SERVER_INSTANCE:
                        _SERVER_INSTANCE.shutdown()
        finally:
            worker = _SERVER_THREAD
            if not getattr(args, "detached", False) and worker is not None and worker is not worker_before:
                primary = sys.exc_info()[1]
                try:
                    try:
                        if primary is not None and worker.is_alive() and _SERVER_INSTANCE is not None:
                            _SERVER_INSTANCE.shutdown()
                    finally:
                        # Allow the existing 15-second startup lease plus the prior 5-second join allowance.
                        worker.join(timeout=20)
                    if worker.is_alive():
                        raise TimeoutError("Local server cleanup did not complete in time")
                    if _SERVER_ERRORS:
                        raise _SERVER_ERRORS[0]
                except BaseException as cleanup_error:
                    if primary is not None and primary is not cleanup_error:
                        raise primary from cleanup_error
                    raise
        return 0
    except Exception as error:  # noqa: BLE001 - top-level CLI boundary: any failure is logged, surfaced, returned as exit 1
        ensure_directory(LOCAL)
        with LOG.open("a", encoding="utf-8") as record:
            record.write("Launcher failure: " + type(error).__name__ + "\n")
        if args.no_browser:
            print("KineLab T6 launcher error: " + str(error), file=sys.stderr)
        elif os.name == "nt":
            from ctypes import windll
            windll.user32.MessageBoxW(
                None, str(error) + "\n\nSee local KineLabPT server log.",
                "KineLab PT Unified Studio", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
