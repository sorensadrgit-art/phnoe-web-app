"""Use only the explicitly selected checkout's real verification backend."""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LEGACY_CHECKOUT_NAME = "kinelab-pt-dualcam"
DATA_ROOT_NAMES = ("kinelabpt-candidate-m1",)
REFUSED_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm")
REFUSED_NAMES = (".env",)
SHORT_NAME = re.compile(r"~\d")
IDENTITY_SOURCES = ("tools/check_quality.py", "tools/verify_evidence.py",
                    "tools/build_offline_distribution.py", "t6_server.py", "viewer/package.json")
HARNESS_SOURCES = ("cli_anything/kinelab/kinelab_cli.py", "cli_anything/kinelab/core/operator.py",
                   "cli_anything/kinelab/utils/kinelab_backend.py", "setup.py")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _refuse_text(candidate: Path) -> None:
    text = str(candidate)
    _drive, rest = os.path.splitdrive(text)
    if ":" in rest:
        raise ValueError(f"LIVE_PATH_REFUSED: alternate data stream or device suffixes are refused: {candidate}")
    lowered = [part.lower() for part in candidate.parts]
    if any(SHORT_NAME.search(part) for part in lowered[1:]):
        raise ValueError(f"LIVE_PATH_REFUSED: 8.3 short-name components are refused; use the long path: {candidate}")
    if LEGACY_CHECKOUT_NAME in lowered:
        raise ValueError(f"LIVE_PATH_REFUSED: the live KineLab-PT-DualCam checkout is never accessed: {candidate}")
    if any(name in lowered for name in DATA_ROOT_NAMES):
        raise ValueError(f"LIVE_PATH_REFUSED: KineLab candidate data roots are never accessed: {candidate}")
    configured = os.environ.get("KINELAB_CANDIDATE_DATA_ROOT")
    if configured:
        root = Path(os.path.normcase(os.path.abspath(configured)))
        if _is_within(Path(os.path.normcase(text)), root):
            raise ValueError(f"LIVE_PATH_REFUSED: the configured candidate data root is never accessed: {candidate}")
    name = candidate.name.lower()
    if name in REFUSED_NAMES or name.endswith(REFUSED_SUFFIXES):
        raise ValueError(f"LIVE_PATH_REFUSED: databases and credential files are never read: {candidate}")


def refuse_live_path(path: Path) -> Path:
    """Refuse the live legacy checkout, candidate data roots, databases and secrets.

    The text form is checked first so a refused location is never touched; only
    then is the path resolved through junctions/symlinks and checked again. The
    unresolved absolute path is returned so later link-traversal checks still see
    the original components.
    """
    candidate = Path(os.path.abspath(Path(path)))
    _refuse_text(candidate)
    _refuse_text(Path(os.path.realpath(candidate)))
    return candidate

def workspace_root(path: Path) -> Path:
    """Validate an explicit checkout; never search for application data roots."""
    root = refuse_live_path(path)
    if not (root / "t6_server.py").is_file() or not (root / "viewer/package.json").is_file():
        raise ValueError("Required KineLab source workspace is unavailable; pass --workspace explicitly")
    return root


def _sha256(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(root: Path) -> str | None:
    """Read the checked-out commit from .git files without running git."""
    git_dir = root / ".git"
    if git_dir.is_file():
        pointer = git_dir.read_text(encoding="utf-8").strip()
        if not pointer.startswith("gitdir:"):
            return None
        git_dir = (root / pointer.split(":", 1)[1].strip()).resolve()
    head_file = git_dir / "HEAD"
    if not head_file.is_file():
        return None
    head = head_file.read_text(encoding="utf-8").strip()
    if not head.startswith("ref:"):
        return head or None
    ref = head.split(":", 1)[1].strip()
    loose = git_dir / ref
    if loose.is_file():
        return loose.read_text(encoding="utf-8").strip()
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    return None


def source_identity(workspace: Path) -> dict:
    """Workspace path, checked-out HEAD and working-tree hashes of the sources used."""
    root = workspace_root(workspace)
    harness = Path(__file__).resolve().parents[3]
    return {
        "schema": "kinelab.harness-identity.v1",
        "workspace": str(root),
        "git_head": git_head(root),
        "source_sha256": {name: _sha256(root / name) for name in IDENTITY_SOURCES},
        "harness_root": str(harness),
        "harness_sha256": {name: _sha256(harness / name) for name in HARNESS_SOURCES},
        "harness_python": sys.executable,
        "note": "Hashes are of the current working tree, which may differ from git_head.",
        "clinical_validation": "UNVERIFIED",
    }


def load_backend(workspace: Path, name: str):
    """Import one allowlisted, existing backend without generating bytecode."""
    if name not in {"check_quality", "build_offline_distribution"}:
        raise ValueError("Unsupported backend")
    path = workspace_root(workspace) / "tools" / (name + ".py")
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Required backend unavailable: tools/{name}.py; no substitute is used")
    spec = importlib.util.spec_from_file_location("kinelab_cli_backend_" + name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Required backend is not importable: tools/{name}.py; no substitute is used")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def evidence_command(workspace: Path, archive: Path) -> tuple[dict, int]:
    """Run the real standalone verifier and preserve its JSON and exit code."""
    root = workspace_root(workspace)
    archive = refuse_live_path(archive)
    backend = root / "tools/verify_evidence.py"
    if not backend.is_file() or backend.is_symlink():
        raise ValueError("Required Factory-owned tools/verify_evidence.py is unavailable; verification BLOCKED")
    package = load_backend(root, "build_offline_distribution")
    package.reject_link_traversal(Path(archive))
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", str(backend), str(Path(archive).absolute())],
        capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except ValueError as error:
        raise ValueError("Evidence backend did not return its required JSON response") from error
    if result.get("schema") != "kinelab.evidence-verification.v1" or completed.returncode not in (0, 1, 2):
        raise ValueError("Evidence backend response contract mismatch")
    return result, completed.returncode
