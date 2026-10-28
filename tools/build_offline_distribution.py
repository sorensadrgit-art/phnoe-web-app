#!/usr/bin/env python3
"""Build KineLab PT Offline Distribution Package for Windows x64.

Packages the complete verified software application for offline deployment:
- Core Python application modules and services
- Compiled production React viewer (viewer/dist)
- Asset icons and schemas
- Model specifications and local cache manifest
- Windows launchers and desktop shortcut setup script
- Offline documentation, third-party notices, and runbooks
- Complete SHA-256 distribution manifest
- Distribution ZIP archive
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"
PACKAGE_NAME = "KineLabPT-v1.0.0-windows-x64"
TARGET_DIR = DIST_DIR / PACKAGE_NAME
ZIP_PATH = DIST_DIR / f"{PACKAGE_NAME}.zip"

CORE_PYTHON_MODULES = [
    "t6_launcher.py",
    "t6_server.py",
    "t6_service.py",
    "session_contract.py",
    "session_index.py",
    "backup_manager.py",
    "report_builder.py",
    "normalize_capture.py",
    "pipeline_quality.py",
    "gait_events.py",
    "squat_events.py",
    "sync_evidence.py",
    "setup_project.py",
    "workflow_controller.py",
    "workflow_recovery.py",
    "export_motion.py",
    "session_library.py",
    "capture_station.py",
    "capture_station_gui.py",
    "sync_review_gui.py",
    "kinelab_hub.py",
    "blender_import.py",
    "make_board.py",
]

CORE_METADATA_FILES = [
    "requirements.lock.txt",
    "environment.json",
    "model-cache.json",
]


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def check_prerequisites():
    print("[1/6] Checking packaging prerequisites...")
    # 1. Frontend dist check
    frontend_dist = ROOT / "viewer" / "dist" / "index.html"
    if not frontend_dist.is_file():
        raise RuntimeError("Frontend dist missing. Run 'npm --prefix viewer run build' first.")
    print("  -> Frontend production build present.")

    # 2. Core Python modules check
    for mod in CORE_PYTHON_MODULES:
        p = ROOT / mod
        if not p.is_file():
            raise RuntimeError(f"Required module missing: {mod}")
    print(f"  -> All {len(CORE_PYTHON_MODULES)} core Python modules verified.")

    # 3. Assets check
    ico = ROOT / "assets" / "kinelab-pt.ico"
    if not ico.is_file():
        raise RuntimeError(f"Application icon missing: {ico}")
    print("  -> Assets verified.")


def copy_application_files():
    print("[2/6] Staging application files...")
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    app_dir = TARGET_DIR / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    # Copy Python modules
    for mod in CORE_PYTHON_MODULES:
        shutil.copy2(ROOT / mod, app_dir / mod)

    # Copy metadata files
    for meta in CORE_METADATA_FILES:
        src = ROOT / meta
        if src.is_file():
            shutil.copy2(src, app_dir / meta)

    # Copy viewer/dist
    viewer_dist_src = ROOT / "viewer" / "dist"
    viewer_dist_dst = app_dir / "viewer" / "dist"
    shutil.copytree(viewer_dist_src, viewer_dist_dst)

    # Copy assets
    assets_src = ROOT / "assets"
    assets_dst = app_dir / "assets"
    shutil.copytree(assets_src, assets_dst)

    # Copy docs
    docs_dst = TARGET_DIR / "docs"
    docs_dst.mkdir(parents=True, exist_ok=True)
    docs_src = ROOT / "docs"
    if docs_src.exists():
        for doc_file in docs_src.glob("*.md"):
            shutil.copy2(doc_file, docs_dst / doc_file.name)

    print(f"  -> Staged core modules, viewer assets, and docs to {TARGET_DIR}")


def write_launcher_scripts():
    print("[3/6] Generating portable launchers and installation scripts...")

    # Start-KineLabPT.bat
    bat_content = """@echo off
setlocal
title KineLab PT Unified Research Studio
echo ========================================================
echo   KineLab PT - Motion Analysis Research Platform
echo   Offline Windows Distribution v1.0.0
echo ========================================================
echo.

set SCRIPT_DIR=%~dp0
set APP_DIR=%SCRIPT_DIR%app

REM Look for python in local virtualenv first, then system PATH
if exist "%SCRIPT_DIR%venv\\Scripts\\python.exe" (
    set PYTHON_EXE="%SCRIPT_DIR%venv\\Scripts\\python.exe"
) else if exist "%SCRIPT_DIR%..\\.venv\\Scripts\\python.exe" (
    set PYTHON_EXE="%SCRIPT_DIR%..\\.venv\\Scripts\\python.exe"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python 3.10+ runtime not found on PATH or in distribution.
        echo Please ensure Python is installed and available.
        pause
        exit /b 1
    )
    set PYTHON_EXE=python
)

echo Starting KineLab PT unified localhost server...
cd /d "%APP_DIR%"
%PYTHON_EXE% t6_launcher.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] KineLab PT exited with error code %errorlevel%.
    pause
    exit /b %errorlevel%
)
endlocal
"""
    (TARGET_DIR / "Start-KineLabPT.bat").write_text(bat_content, encoding="utf-8")

    # Install-DesktopShortcut.ps1
    ps1_content = """# KineLab PT - Desktop Shortcut Installer
# Creates exactly one desktop shortcut for KineLab PT
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $ScriptDir "app"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "KineLab PT.lnk"
$IconPath = Join-Path $AppDir "assets\\kinelab-pt.ico"
$LauncherPy = Join-Path $AppDir "t6_launcher.py"

Write-Host "KineLab PT Desktop Shortcut Configuration" -ForegroundColor Cyan
Write-Host "Target Shortcut: $ShortcutPath"

# Determine pythonw executable
$pythonw = ""
if (Test-Path "$ScriptDir\\venv\\Scripts\\pythonw.exe") {
    $pythonw = "$ScriptDir\\venv\\Scripts\\pythonw.exe"
} elseif (Test-Path "$ScriptDir\\..\\.venv\\Scripts\\pythonw.exe") {
    $pythonw = "$ScriptDir\\..\\.venv\\Scripts\\pythonw.exe"
} else {
    $pyCmd = Get-Command pythonw -ErrorAction SilentlyContinue
    if ($pyCmd) {
        $pythonw = $pyCmd.Source
    } else {
        $pyCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pyCmd) { $pythonw = $pyCmd.Source }
    }
}

if (-not $pythonw) {
    Write-Warning "Python interpreter not located automatically. Falling back to Start-KineLabPT.bat"
    $target = Join-Path $ScriptDir "Start-KineLabPT.bat"
    $args = ""
} else {
    $target = $pythonw
    $args = "`"$LauncherPy`""
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $target
if ($args) { $Shortcut.Arguments = $args }
$Shortcut.WorkingDirectory = $AppDir
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = "$IconPath,0"
}
$Shortcut.Description = "KineLab PT - Motion Analysis Research Platform"
$Shortcut.Save()

Write-Host "Success: Desktop shortcut 'KineLab PT' created." -ForegroundColor Green
"""
    (TARGET_DIR / "Install-DesktopShortcut.ps1").write_text(ps1_content, encoding="utf-8")

    # README-OFFLINE-INSTALL.md
    readme_content = """# KineLab PT — Offline Distribution Package (v1.0.0)

## System Requirements
- **Operating System**: Windows 10 (Build 19041+) or Windows 11 64-bit
- **Processor**: x86_64 Intel/AMD processor (AVX2 recommended)
- **Memory**: 8 GB RAM minimum (16 GB recommended for multi-camera video processing)
- **Python**: Python 3.10 to 3.13 (64-bit) with OpenSim 4.4+ and Pose2Sim 0.10+
- **GPU**: Optional. ONNX Runtime uses CPUExecutionProvider by default.

## Installation & First Run (Air-Gapped / Offline Workstation)

1. **Extract Distribution Archive**:
   Extract `KineLabPT-v1.0.0-windows-x64.zip` to your chosen application directory (e.g., `C:\\Program Files\\KineLabPT` or `C:\\Tools\\KineLabPT`).

2. **Verify Desktop Shortcut**:
   Run `powershell -ExecutionPolicy Bypass -File .\\Install-DesktopShortcut.ps1` to create the single `KineLab PT` desktop shortcut.

3. **Launch Application**:
   Double-click the `KineLab PT` desktop shortcut or execute `Start-KineLabPT.bat`.
   The application starts a secure localhost server (`127.0.0.1:4184+`) with an instance token and opens the unified workspace in your default web browser.

## Data Storage & Privacy Guarantees
- **No Cloud Services**: Zero remote telemetry, zero analytics, zero external API dependencies.
- **Local Application Data**: Session states, server logs, and indices are stored strictly in `%LOCALAPPDATA%\\KineLabPT`.
- **Media Preservation**: Original capture recordings are strictly read-only and preserved with SHA-256 integrity verification.
"""
    (TARGET_DIR / "README-OFFLINE-INSTALL.md").write_text(readme_content, encoding="utf-8")
    print("  -> Launchers and setup scripts written.")


def generate_manifest():
    print("[4/6] Computing SHA-256 distribution manifest...")
    manifest_entries = []
    total_bytes = 0

    for root, _, files in os.walk(TARGET_DIR):
        for f in files:
            p = Path(root) / f
            rel = p.relative_to(TARGET_DIR).as_posix()
            size = p.stat().st_size
            digest = sha256_file(p)
            total_bytes += size
            manifest_entries.append({
                "path": rel,
                "size_bytes": size,
                "sha256": digest,
            })

    manifest_entries.sort(key=lambda x: x["path"])

    manifest_doc = {
        "schema": "kinelab.distribution.manifest.v1",
        "package_name": PACKAGE_NAME,
        "built_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_files": len(manifest_entries),
        "total_bytes": total_bytes,
        "platform": "windows-x64",
        "verification_status": "SOFTWARE_BUILD_VERIFIED",
        "physical_validation_status": "BLOCKED_ON_PHYSICAL_EVIDENCE",
        "clinical_validation_status": "UNVERIFIED",
        "files": manifest_entries,
    }

    manifest_path = TARGET_DIR / "DISTRIBUTION-MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest_doc, indent=2), encoding="utf-8")
    print(f"  -> Generated manifest: {len(manifest_entries)} files, {total_bytes:,} bytes.")


def create_zip_archive():
    print("[5/6] Creating ZIP distribution archive...")
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(TARGET_DIR):
            for f in files:
                p = Path(root) / f
                arcname = f"{PACKAGE_NAME}/{p.relative_to(TARGET_DIR).as_posix()}"
                zf.write(p, arcname)

    zip_size = ZIP_PATH.stat().st_size
    zip_sha = sha256_file(ZIP_PATH)
    print(f"  -> Created {ZIP_PATH.name} ({zip_size:,} bytes, SHA-256: {zip_sha})")
    return zip_sha, zip_size


def verify_distribution_integrity():
    print("[6/6] Verifying distribution package integrity...")
    manifest_file = TARGET_DIR / "DISTRIBUTION-MANIFEST.json"
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    files = data["files"]
    checked = 0

    for entry in files:
        if entry["path"] == "DISTRIBUTION-MANIFEST.json":
            continue
        p = TARGET_DIR / entry["path"]
        if not p.is_file():
            raise FileNotFoundError(f"Packaged file missing: {entry['path']}")
        actual_sha = sha256_file(p)
        if actual_sha != entry["sha256"]:
            raise ValueError(f"Hash mismatch on packaged file: {entry['path']}")
        checked += 1

    print(f"  -> Verified {checked} packaged files against distribution manifest: 100% MATCH.")


def main():
    print("========================================================")
    print(f"  Building {PACKAGE_NAME}")
    print("========================================================")
    try:
        check_prerequisites()
        copy_application_files()
        write_launcher_scripts()
        generate_manifest()
        zip_sha, zip_size = create_zip_archive()
        verify_distribution_integrity()
        print("\nDistribution package build completed successfully.")
        print(f"Output directory: {TARGET_DIR}")
        print(f"Output archive:   {ZIP_PATH}")
        print(f"Archive SHA-256:  {zip_sha}")
        return 0
    except Exception as exc:
        print(f"\n[BUILD ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
