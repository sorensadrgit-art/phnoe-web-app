"""Isolated engineering-candidate storage; no discovery or migration of old data."""
import hashlib
import os
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path

INSTALLATION = Path(__file__).resolve().parent
DATA_ROOT_ENV = "KINELAB_CANDIDATE_DATA_ROOT"


SUPPORTED_DESKTOP_COMMAND = "python t6_launcher.py --data-root <new dedicated directory>"


def retired_entrypoint(name: str, reason: str) -> int:
    """Refuse a legacy entry point without starting servers, reading data or writing state."""
    print(f"RETIRED_ENTRYPOINT={name}\n{reason}\n"
          "This entry point is retired and started nothing. Supported desktop launcher: "
          f"{SUPPORTED_DESKTOP_COMMAND} (API /api/v1, per-launch Bearer token, isolated data root). "
          "The synthetic web demonstration is the separate 'npm --prefix viewer run build:cloud' "
          "build and performs no measurement.", file=sys.stderr)
    return 2


def candidate_home() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "KineLabPT-Candidate-M1"


def is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def ensure_directory(path: Path) -> Path:
    """Check every existing ancestor before creating missing empty directories."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        raise ValueError("DATA_ROOT_INVALID: use a dedicated absolute directory")
    for part in (*reversed(path.parents), path):
        if is_reparse(part):
            raise ValueError("DATA_ROOT_UNSAFE: linked or reparse directories are refused")
        if not part.exists():
            try:
                part.mkdir()
            except FileExistsError:
                pass
        if is_reparse(part) or not part.is_dir():
            raise ValueError("DATA_ROOT_UNSAFE: expected an ordinary directory")
    return path.resolve()


def resolve_data_root(value=None) -> Path:
    selected = value if value is not None else (os.environ.get(DATA_ROOT_ENV) or candidate_home() / "data")
    path = Path(selected)
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        raise ValueError("DATA_ROOT_INVALID: use a dedicated absolute directory")
    legacy = candidate_home().parent / "KineLabPT"
    original = INSTALLATION.parent / "KineLab-PT-DualCam"
    for protected in (INSTALLATION, legacy, original, candidate_home() / "runtime"):
        if path == protected or path.is_relative_to(protected) or protected.is_relative_to(path):
            raise ValueError("DATA_ROOT_UNSAFE: application and legacy locations are refused")
    if path == Path.home():
        raise ValueError("DATA_ROOT_UNSAFE: use a dedicated data directory")
    return path


def ensure_data_root(value=None) -> Path:
    return ensure_directory(resolve_data_root(value))


def runtime_identity(data_root: Path, *, installation: Path = INSTALLATION) -> str:
    # Identifiers are compared only after the configured path has been validated.
    parts = [os.path.normcase(os.path.abspath(path)) for path in (installation, data_root)]
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


@contextmanager
def startup_lock(directory: Path, *, timeout: float = 15.0):
    """OS-owned lock serializes candidate launcher starts, including subprocesses."""
    directory = ensure_directory(directory)
    path = directory / "t6-startup.lock"
    if is_reparse(path):
        raise ValueError("DATA_ROOT_UNSAFE: linked startup lock refused")
    with path.open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            stream.seek(0)
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Candidate startup is already in progress") from error
                time.sleep(0.05)
        try:
            yield stream
        finally:
            stream.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
