"""Launch KineLab PT's unified React + loopback Python workspace.

Single original Windows desktop icon is updated only after runtime QA.
Keeps 4173/4174 legacy websites untouched and chooses a free port >4182.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parent
DIST=ROOT/"viewer"/"dist"
SERVICE=ROOT/"unified_service.py"
PORTS=range(4190,4231)
KEY_REGEX=re.compile(r"[A-Za-z0-9_-]{24,120}\Z")
STATE_DIR=Path(os.environ.get("LOCALAPPDATA",str(Path.home()))) / "KineLabPT"
STATE=STATE_DIR/"unified.state.json"
LOG=STATE_DIR/"unified-service.log"
EDGE_CANDIDATES=(
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as conn:
        conn.settimeout(.32)
        return conn.connect_ex(("127.0.0.1",port))==0


def find_free_port(ports=PORTS,*,is_busy=port_busy) -> int:
    for port in ports:
        if port in PORTS and not is_busy(port):
            return port
    raise RuntimeError("No free local unified-app port in 4190–4230")


def read_state(file=STATE):
    try:
        value=json.loads(Path(file).read_text(encoding="utf-8-sig"))
        if not isinstance(value,dict) or set(value)!={"port","key"}:
            return None
        if type(value["port"]) is not int or value["port"] not in PORTS:
            return None
        if not isinstance(value["key"],str) or not KEY_REGEX.fullmatch(value["key"]):
            return None
        return value
    except (OSError,ValueError,TypeError):
        return None


def write_state(file:Path,value:dict):
    if set(value)!={"port","key"} or type(value["port"]) is not int or (
        value["port"] not in PORTS
    ) or not isinstance(value["key"],str) or not KEY_REGEX.fullmatch(value["key"]):
        raise ValueError("Only a verified bounded local state may be saved")
    file=Path(file)
    file.parent.mkdir(parents=True,exist_ok=True)
    staging=file.with_name(file.name+"."+secrets.token_hex(8)+".partial")
    try:
        with staging.open("x",encoding="utf-8") as f:
            json.dump(value,f)
            f.flush();os.fsync(f.fileno())
        os.replace(staging,file)
    finally:
        staging.unlink(missing_ok=True)


def is_verified_service(port:int,key:str,*,timeout:float=.85)->bool:
    if type(port) is not int or port not in PORTS or not KEY_REGEX.fullmatch(key):
        return False
    base=f"http://127.0.0.1:{port}"
    try:
        with urlopen(Request(base+"/api/health"),timeout=timeout) as resp:
            health=json.load(resp)
        if health.get("app")!="KineLab PT" or health.get("service")!="unified":
            return False
        request=Request(base+"/api/sessions",headers={"X-KineLab-Key":key})
        with urlopen(request,timeout=timeout) as resp:
            result=json.load(resp)
        return isinstance(result.get("sessions"),list)
    except (OSError,ValueError,TypeError,TimeoutError,KeyError):
        return False


def start_server(port,key):
    if not SERVICE.is_file() or not (DIST/"index.html").is_file():
        raise FileNotFoundError("Missing bundled offline React build or local Python service")
    pythonw=ROOT/".venv"/"Scripts"/"pythonw.exe"
    interpreter=pythonw if pythonw.is_file() else Path(sys.executable)
    STATE_DIR.mkdir(parents=True,exist_ok=True)
    log=LOG.open("ab")
    try:
        proc=subprocess.Popen(
            [str(interpreter),str(SERVICE),"--port",str(port),"--key",key],
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
            cwd=str(ROOT),creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),
        )
    finally:
        log.close()
    for _ in range(70):
        if is_verified_service(port,key,timeout=.55):return proc
        if proc.poll() is not None:
            raise RuntimeError("Unified service exited during startup; see local service log")
        time.sleep(.17)
    raise RuntimeError("Unified service startup timed out; see local log")


def ensure_running()->dict:
    previous=read_state()
    if previous is not None and is_verified_service(previous["port"],previous["key"]):
        return previous
    port=find_free_port()
    key=secrets.token_urlsafe(36)
    start_server(port,key)
    state={"port":port,"key":key}
    write_state(STATE,state)
    return state


def open_window(state:dict)->str:
    port,key=state["port"],state["key"]
    url=f"http://127.0.0.1:{port}/#key={key}"
    edge=next((item for item in EDGE_CANDIDATES if item.is_file()),None)
    if edge is not None:
        profile=STATE_DIR/"browser-profile"
        profile.mkdir(parents=True,exist_ok=True)
        subprocess.Popen(
            [str(edge),"--app="+url,"--user-data-dir="+str(profile),
             "--no-first-run","--no-default-browser-check"],
            cwd=str(ROOT),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),
        )
    else:
        if not webbrowser.open(url,new=1):
            raise RuntimeError("Could not open local browser app")
    return f"http://127.0.0.1:{port}/"


def main():
    from runtime_config import retired_entrypoint
    return retired_entrypoint("launch_kinelab_unified.py",
        "It started unified_service.py with the obsolete /api routes, #key URL and X-KineLab-Key header, "
        "legacy %LOCALAPPDATA%\\KineLabPT state and the in-installation projects directory.")


def legacy_main():
    p=argparse.ArgumentParser(description="Open unified KineLab PT desktop workspace")
    p.add_argument("--no-window",action="store_true")
    p.add_argument("--smoke",action="store_true")
    args=p.parse_args()
    try:
        if args.smoke:
            assert DIST.joinpath("index.html").is_file()
            assert SERVICE.is_file()
            assert all(port>4182 for port in PORTS)
            print("KINELAB_T6_LAUNCHER_SMOKE_OK")
            return 0
        state=ensure_running()
        if not args.no_window:open_window(state)
        else:print(f"KINELAB_UNIFIED_READY=http://127.0.0.1:{state['port']}/")
        return 0
    except Exception as exc:  # noqa: BLE001 - retired CLI boundary: any failure is logged, surfaced, returned as exit 1
        STATE_DIR.mkdir(parents=True,exist_ok=True)
        with LOG.open("ab") as f:
            f.write(f"Launcher error: {type(exc).__name__}: {exc}\n".encode())
        if not args.no_window and sys.platform=="win32":
            from ctypes import windll
            windll.user32.MessageBoxW(None,f"{exc}\n\nSee local KineLab logs for details.",
                                      "KineLab PT",0x10)
        else:print(f"Launcher failed: {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
