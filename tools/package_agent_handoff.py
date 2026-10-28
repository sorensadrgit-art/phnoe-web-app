#!/usr/bin/env python3
"""Create a verified, non-destructive KineLab PT desktop handoff from a clean checkout.

Requires an existing offline ZIP built from this checkout by tools/build_offline_distribution.py.
Creates a NEW desktop directory only. Does not access patient data, modify original launcher,
push git changes, or deploy to Vercel. Python 3.10+ standard library only.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST_NAME = "KineLabPT-v1.0.0-windows-x64"
TODAY = "20261028"


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def safename(name: str) -> Path:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or ":" in name or "\\" in name:
        raise ValueError(f"Unsafe ZIP member: {name!r}")
    return Path(*p.parts)


def verify_and_extract(archive: Path, destination: Path) -> int:
    with zipfile.ZipFile(archive) as zf:
        if (bad := zf.testzip()) is not None:
            raise ValueError(f"ZIP CRC failure: {bad}")
        for info in zf.infolist():
            rel = safename(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise ValueError(f"ZIP symlink forbidden: {info.filename}")
            target = destination / rel
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"ZIP path traversal: {info.filename}")
        zf.extractall(destination)
        return sum(1 for item in zf.infolist() if not item.is_dir())


def verify_dist(directory: Path) -> dict:
    manifest_path = directory / DIST_NAME / "DISTRIBUTION-MANIFEST.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = data["files"]
    if data["total_files"] != len(rows):
        raise ValueError("Distribution manifest count incorrect")
    listed = set()
    bytes_count = 0
    for row in rows:
        relative = safename(row["path"])
        src = manifest_path.parent / relative
        if not src.is_file() or src.stat().st_size != row["size_bytes"]:
            raise ValueError(f"Distribution file missing/wrong size: {relative}")
        if checksum(src) != row["sha256"]:
            raise ValueError(f"Distribution SHA-256 mismatch: {relative}")
        listed.add(relative.as_posix())
        bytes_count += row["size_bytes"]
    if bytes_count != data["total_bytes"]:
        raise ValueError("Distribution byte count mismatch")
    actual = {p.relative_to(manifest_path.parent).as_posix() for p in manifest_path.parent.rglob("*") if p.is_file()}
    if actual != listed | {"DISTRIBUTION-MANIFEST.json"}:
        raise ValueError(f"Unexpected or absent distribution files: {actual ^ (listed | {'DISTRIBUTION-MANIFEST.json'})}")
    return {
        "total_manifest_files": len(rows),
        "verified_sha256_files": len(listed),
        "actual_file_count_including_manifest": len(actual),
        "bytes": bytes_count,
        "software_build_status": data["verification_status"],
        "clinical_validation_status": data["clinical_validation_status"],
    }


def source_files() -> list[str]:
    paths = [p.decode("utf-8") for p in git("ls-files", "-z").split(b"\0") if p]
    if not paths:
        raise RuntimeError("No Git-tracked source files")
    banned = (".env", ".pem", ".key", ".p12", ".pfx", "t6-instance.json", "auth.json")
    for rel in paths:
        lower = rel.lower()
        if lower.startswith(("projects/", "session-data/", "backups/", "snapshots/")):
            raise ValueError(f"Sensitive runtime directory tracked: {rel}")
        if any(lower.endswith(ext) for ext in banned) and not lower.endswith(".env.example"):
            raise ValueError(f"Private credential or key file tracked: {rel}")
        if (ROOT / rel).is_symlink():
            raise ValueError(f"Symlink not allowed in portable source: {rel}")
    return paths


def build_source_zip(archive: Path, paths: list[str], commit: str, branch: str) -> None:
    entries = []
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel in paths:
            item = ROOT / rel
            if not item.is_file():
                raise FileNotFoundError(rel)
            zf.write(item, rel.replace("\\", "/"))
            entries.append({"path": rel.replace("\\", "/"), "bytes": item.stat().st_size, "sha256": checksum(item)})
        zf.writestr("SOURCE-MANIFEST.json", json.dumps({
            "schema": "kinelab.agent.source-manifest.v1",
            "commit": commit, "branch": branch, "total_files": len(entries),
            "files": entries,
        }, indent=2))
    with zipfile.ZipFile(archive) as zf:
        if zf.testzip() is not None:
            raise ValueError("Full source ZIP CRC check failed")


def verify_source_extract(folder: Path, paths: list[str]) -> None:
    doc = json.loads((folder / "SOURCE-MANIFEST.json").read_text(encoding="utf-8"))
    if doc["total_files"] != len(paths):
        raise ValueError("Source file count mismatch")
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    if actual != set(paths) | {"SOURCE-MANIFEST.json"}:
        raise ValueError("Source archive contents do not match tracked files")
    for row in doc["files"]:
        if checksum(folder / row["path"]) != row["sha256"]:
            raise ValueError(f"Source SHA mismatch: {row['path']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop", type=Path, required=True)
    args = parser.parse_args()
    desktop = args.desktop.resolve()
    if not desktop.is_dir():
        raise NotADirectoryError(desktop)
    existing_shortcut = desktop / "KineLab PT.lnk"
    shortcut_before = checksum(existing_shortcut) if existing_shortcut.is_file() else None
    target = desktop / "KineLab PT - Production Handoff"
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing desktop handoff: {target}")
    if git("status", "--porcelain").strip():
        raise RuntimeError("Git working tree is not clean; commit or discard tracked edits first")
    commit = git("rev-parse", "HEAD").decode().strip()
    branch = git("branch", "--show-current").decode().strip()
    if branch != "feat/kinelab-production-readiness-20261028":
        raise RuntimeError(f"Unexpected agent branch: {branch}")
    paths = source_files()
    dist = ROOT / "dist" / f"{DIST_NAME}.zip"
    if not dist.is_file():
        raise FileNotFoundError(f"Build the portable distribution first: {dist}")

    target.mkdir()
    source_archive = target / f"KineLabPT-Full-Source-{TODAY}.zip"
    dist_archive = target / f"{DIST_NAME}.zip"
    source_folder = target / "02-Full-Source-Snapshot"
    app_folder = target / "01-Windows-Portable-App"
    guide = target / "03-Agent-Guide"
    source_folder.mkdir()
    app_folder.mkdir()
    guide.mkdir()

    build_source_zip(source_archive, paths, commit, branch)
    source_count = verify_and_extract(source_archive, source_folder)
    verify_source_extract(source_folder, paths)

    shutil.copy2(dist, dist_archive)
    zip_count = verify_and_extract(dist_archive, app_folder)
    dist_info = verify_dist(app_folder)

    for filename, src in {
        "AGENTS.md": ROOT / "AGENTS.md",
        "PRODUCTION_READINESS_HANDOFF.md": ROOT / "docs" / "PRODUCTION_READINESS_HANDOFF.md",
        "OPEN-AGENT-START.txt": ROOT / "OPEN-AGENT-START.txt",
        "VERCEL_WEB_DEMO.md": ROOT / "docs" / "VERCEL_WEB_DEMO.md",
        "QUALITY_EVIDENCE_POLICY.md": ROOT / "docs" / "QUALITY_EVIDENCE_POLICY.md",
        "BASELINE_QA_20261028.md": ROOT / "docs" / "BASELINE_QA_20261028.md",
    }.items():
        shutil.copy2(src, guide / filename)

    readme = f"""# KineLab PT — Production Agent Handoff

Prepared from private Git main baseline ffde4be (source branch commit `{commit[:12]}`).
**This is an agent-ready engineering kit, NOT a clinically validated production system.**

## Use these items
- `01-Windows-Portable-App\\{DIST_NAME}\\` — EXTRACTED desktop package with Python launcher, compiled offline UI, documentation and verified manifest. Dependencies/runtime and pretrained models are not bundled; see `README-OFFLINE-INSTALL.md`. Do not run `Install-DesktopShortcut.ps1` because it would replace the current working shortcut.
- `02-Full-Source-Snapshot\\` — ALL Git-tracked project files, including source, tests, assets, examples and configuration (read-only reference; excludes Git history and untracked PHI).
- `03-Agent-Guide\\AGENTS.md` and `PRODUCTION_READINESS_HANDOFF.md` — production milestones, baseline QA evidence, scientific evidence gates, explicit agent instructions.
- `KineLabPT-Full-Source-{TODAY}.zip` and `{DIST_NAME}.zip` — portable verified archives.
- `KineLabPT-FULL-AGENT-KIT-{TODAY}.zip` — one ZIP containing BOTH archives, guides and SHA-256 verification.

## Editable agent workspace (not the snapshot)
`{ROOT}`
Working branch: `{branch}`
Open `KineLab PT - Agent Workspace.lnk` on the desktop to navigate to this Git repository.
The working clone has `viewer/node_modules`, compiled `viewer/dist`, an isolated Python `.venv`, and can run the test and build commands.

## Do not affect the currently working app
The original `KineLab PT.lnk` still targets the existing local application. Leave it in place.
Production Vercel remains a **synthetic demo**. No backend or patient recordings have been uploaded.
A clinical release requires physical and scientific validation plus privacy/security acceptance.

## Next agent step
Read `03-Agent-Guide/OPEN-AGENT-START.txt`, `03-Agent-Guide/AGENTS.md` and `03-Agent-Guide/PRODUCTION_READINESS_HANDOFF.md`.
"""
    (target / "README-FIRST.md").write_text(readme, encoding="utf-8")

    report = {
        "prepared_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "desktop": str(target),
        "agent_workspace": str(ROOT),
        "git_branch": branch,
        "git_head": commit,
        "baseline_main": "ffde4be70d0a501980d1d22aac3dea1c91006ff9",
        "source_zip": {"file": source_archive.name, "sha256": checksum(source_archive),
                       "bytes": source_archive.stat().st_size, "tracked_files": len(paths),
                       "extracted_files": source_count},
        "runtime_zip": {"file": dist_archive.name, "sha256": checksum(dist_archive),
                       "bytes": dist_archive.stat().st_size, "zip_entries": zip_count, **dist_info},
        "safety": {"original_desktop_shortcut_preserved": shortcut_before is not None and existing_shortcut.is_file() and checksum(existing_shortcut) == shortcut_before,
                   "original_shortcut_sha256": shortcut_before,
                   "phi_copied": False, "runtime_dependencies_bundled": False,
                   "clinical_validation": "UNVERIFIED"},
    }
    report_path = target / "VERIFICATION.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    kit = target / f"KineLabPT-FULL-AGENT-KIT-{TODAY}.zip"
    kit_items = [source_archive, dist_archive, target / "README-FIRST.md", report_path]
    kit_items.extend(p for p in guide.glob("*") if p.is_file())
    with zipfile.ZipFile(kit, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in kit_items:
            arcname = f"03-Agent-Guide/{item.name}" if item.parent == guide else item.name
            zf.write(item, arcname)
    with zipfile.ZipFile(kit) as zf:
        if zf.testzip() is not None:
            raise ValueError("Complete agent kit ZIP CRC failure")

    hashes = [f"{checksum(item)}  {item.name}" for item in [source_archive, dist_archive, kit]]
    (target / "SHA256-CHECKSUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")
    print(json.dumps({"status": "KIT_READY_VERIFIED", "target": str(target),
                      "git_head": commit, "branch": branch,
                      "source_files": len(paths), "manifest": dist_info,
                      "zip_sha256": hashes}, indent=2))


if __name__ == "__main__":
    main()
