"""Launch the local KineLab PT Motion Lab without exposing a network port."""
from __future__ import annotations

import argparse
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "viewer" / "dist"
LOG = ROOT / "launcher.log"
PORTS = range(4173, 4183)
SERVER_MARKER = b"KineLab PT | Motion Lab"


def serving_kinelab(port: int) -> bool:
    """Only reuse a listener if it is really the KineLab viewer."""
    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=0.7) as response:
            return response.status == 200 and SERVER_MARKER in response.read(16000)
    except (OSError, ValueError):
        return False


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.35)
        return client.connect_ex(("127.0.0.1", port)) == 0


def choose_port(ports=PORTS) -> tuple[int, bool]:
    """Return port and whether a new local server is necessary."""
    for port in ports:
        if serving_kinelab(port):
            return port, False
        if not port_in_use(port):
            return port, True
    raise RuntimeError("No available local port in 4173-4182; close an existing local app.")


def start_server(port: int) -> subprocess.Popen:
    """Serve the prebuilt Vite output with Python's built-in HTTP server."""
    if not (DIST / "index.html").is_file():
        raise FileNotFoundError(
            f"Missing built viewer at {DIST}. In viewer run: npm install && npm run build"
        )
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    interpreter = pythonw if pythonw.is_file() else Path(sys.executable)
    log_file = LOG.open("ab", buffering=0)
    try:
        return subprocess.Popen(
            [
                str(interpreter), "-m", "http.server", str(port),
                "--bind", "127.0.0.1", "--directory", str(DIST),
            ],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        log_file.close()


def ensure_running() -> str:
    port, must_start = choose_port()
    if must_start:
        process = start_server(port)
        for _ in range(45):
            if serving_kinelab(port):
                break
            if process.poll() is not None:
                raise RuntimeError(f"Local viewer server exited early; see {LOG}")
            time.sleep(0.2)
        else:
            raise TimeoutError(f"Local viewer did not start; check {LOG}")
    return f"http://127.0.0.1:{port}/"


def main() -> int:
    parser = argparse.ArgumentParser(description="Open KineLab PT Motion Lab")
    parser.add_argument("--no-browser", action="store_true", help="Start/verify without opening browser")
    args = parser.parse_args()
    try:
        url = ensure_running()
        if args.no_browser:
            print(f"KINELAB_READY={url}")
        else:
            if not webbrowser.open(url, new=2):
                raise RuntimeError(f"Could not open browser. Visit {url} manually.")
        return 0
    except Exception as exc:
        with LOG.open("a", encoding="utf-8") as log:
            log.write(f"Launcher error: {type(exc).__name__}: {exc}\n")
        if not args.no_browser and sys.platform == "win32":
            from ctypes import windll
            windll.user32.MessageBoxW(
                None, f"{exc}\n\nDetails: {LOG}", "KineLab PT launcher", 0x10,
            )
        else:
            print(f"Launcher error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
