"""KineLab PT single-icon v1 T6 startup, with authenticated localhost reuse.

Reuses only an existing KineLab T6 endpoint proving possession of this user's
instance token. A new instance binds exclusively to 127.0.0.1 and places the
secret in a browser URL fragment, never in a query string or server access log.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "KineLabPT"
STATE = LOCAL / "t6-instance.json"
LOG = LOCAL / "t6-server.log"
PORTS = range(4184, 4204)
SCHEMA = "kinelab.t6.instance.v1"


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


def read_state(path: Path = STATE) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("schema") != SCHEMA or
                type(data.get("port")) is not int or not 1024 <= data["port"] <= 65535 or
                not isinstance(data.get("token"), str) or len(data["token"]) != 64 or
                any(ch not in "0123456789abcdef" for ch in data["token"])):
            return None
        return data
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


def verified_running(instance: dict) -> bool:
    if read_state_dict(instance) is None:
        return False
    try:
        health = get_health(instance)
        return (health.get("app") == "unified_t6" and
                health.get("local_only") is True and
                health.get("name") == "KineLab PT")
    except (OSError, ValueError, TimeoutError, KeyError, TypeError):
        return False


def read_state_dict(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    if (data.get("schema") != SCHEMA or
            type(data.get("port")) is not int or
            not 1024 <= data["port"] <= 65535 or
            not isinstance(data.get("token"), str) or
            len(data["token"]) != 64):
        return None
    return data


def _save_state(instance: dict):
    LOCAL.mkdir(parents=True, exist_ok=True)
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


def ensure_running() -> tuple[str, bool]:
    current = read_state()
    if current and verified_running(current):
        return ("http://127.0.0.1:" + str(current["port"]) + "/#access=" + current["token"]), False
    if not (ROOT / "viewer" / "dist" / "index.html").is_file():
        raise FileNotFoundError("Unified frontend build missing; run npm --prefix viewer run build")
    LOCAL.mkdir(parents=True, exist_ok=True)
    if STATE.exists():
        archival = LOCAL / ("t6-stale-" + uuid4().hex + ".json")
        STATE.replace(archival)
    chosen = choose_available_port()
    state = {"schema": SCHEMA, "port": chosen,
             "token": secrets.token_hex(32), "created_by": "local_single_icon_launcher"}
    _save_state(state)
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    interpreter = pythonw if pythonw.is_file() else Path(sys.executable)
    log = LOG.open("ab", buffering=0)
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        process = subprocess.Popen([
            str(interpreter), str(ROOT / "t6_server.py"),
            "--port", str(chosen), "--state", str(STATE),
        ], cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=creationflags)
    finally:
        log.close()
    for _ in range(55):
        if verified_running(state):
            return ("http://127.0.0.1:" + str(chosen) + "/#access=" + state["token"]), True
        if process.poll() is not None:
            raise RuntimeError("Unified localhost service exited early; see local KineLabPT server log")
        time.sleep(0.20)
    raise TimeoutError("Unified localhost service did not accept its session token")


def main():
    parser = argparse.ArgumentParser(description="KineLab PT unified desktop launcher")
    parser.add_argument("--no-browser", action="store_true", help="Start/verify without opening the page")
    args = parser.parse_args()
    try:
        url, fresh = ensure_running()
        if args.no_browser:
            # Deliberately omit the URL fragment (the secret access token).
            safe = url.split("#", 1)[0]
            print("T6_UNIFIED_READY=" + safe)
            print("T6_NEW_SERVER=" + str(fresh))
        elif not webbrowser.open(url, new=2):
            raise RuntimeError("Unable to open default browser to the local KineLab app")
        return 0
    except Exception as error:
        LOCAL.mkdir(parents=True, exist_ok=True)
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
