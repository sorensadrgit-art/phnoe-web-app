"""Read-only bounded commands; backend evidence remains authoritative."""
import json
import tempfile
from pathlib import Path

from cli_anything.kinelab.utils.kinelab_backend import (
    evidence_command,
    load_backend,
    refuse_live_path,
    source_identity,
    workspace_root,
)

BOUNDED_CHECKS = ("python-runtime", "python-syntax", "node-runtime")


def identity(workspace: Path) -> dict:
    """Report the explicit workspace, checked-out HEAD and current source hashes."""
    return source_identity(workspace)


def quality(workspace: Path, checks: list[str], *, execute: bool = False) -> dict:
    """Plan or execute allowlisted runtime/syntax probes; never full suites/builds.

    The scientific runtime is the workspace's own .venv chosen by the backend,
    never the interpreter that happens to run this harness.
    """
    if not checks or set(checks) - set(BOUNDED_CHECKS):
        raise ValueError("Only explicit bounded runtime/syntax checks are supported")
    root = workspace_root(workspace)
    backend = load_backend(root, "check_quality")
    receipts = None
    if execute:
        receipts = Path(tempfile.mkdtemp(prefix="kinelab-harness-quality-")) / "receipts"
    report = backend.run_checks(root, selected=checks, execute=execute, receipts_dir=receipts, timeout=60)
    report["harness_identity"] = source_identity(root)
    return report


def verify_evidence(workspace: Path, archive: Path) -> tuple[dict, int]:
    """Verify one explicitly selected archive with the real independent backend."""
    result, code = evidence_command(workspace, archive)
    result["harness_identity"] = source_identity(workspace)
    return result, code


class ManifestShapeError(ValueError):
    """Manifest JSON parsed but is not the expected document shape (untrusted input, so a ValueError)."""


def inspect_package(workspace: Path, manifest: Path) -> dict:
    """Inspect stored claims and manifest digest; do not rewrite or verify payload."""
    path = refuse_live_path(manifest)
    backend = load_backend(workspace, "build_offline_distribution")
    backend.reject_link_traversal(path)
    if path.name != "DISTRIBUTION-MANIFEST.json" or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Select a bounded existing DISTRIBUTION-MANIFEST.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise ManifestShapeError("Invalid distribution manifest shape")
    fields = ("verification_status", "software_build_status", "runtime_validation_status",
              "clinical_validation", "physical_validation")
    return {"schema": "kinelab.package-inspection.v1", "status": "INSPECTED",
            "manifest": str(path), "sha256": backend.sha256_file(path),
            "declared_file_count": len(data["files"]),
            "stored_claims": {key: data.get(key) for key in fields},
            "payload_verification": "NOT_RUN", "clinical_validation": "UNVERIFIED",
            "harness_identity": source_identity(workspace),
            "limitations": ["Stored status is a claim, not current verification.",
                            "The builder verifier rewrites manifests and is outside this read-only command."]}
