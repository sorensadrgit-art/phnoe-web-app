#!/usr/bin/env python3
"""Build KineLab PT Offline Distribution Package for Windows x64.

Stages application files for package integrity checks; runtime validation is separate:
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

import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"
PACKAGE_NAME = "KineLabPT-v1.0.0-windows-x64"
TARGET_DIR = DIST_DIR / PACKAGE_NAME
ZIP_PATH = DIST_DIR / f"{PACKAGE_NAME}.zip"

# Roots of the shipped module closure; every other first-party module is derived from their imports.
# capture_station_gui.py is a separately started native window and blender_import.py runs inside an
# external Blender, so neither is reachable from the launcher's import graph.
PACKAGE_ENTRY_POINTS = ["t6_launcher.py", "capture_station_gui.py", "blender_import.py"]

# t6_service opens RUNBOOK.md from the application directory for the runbook action.
REQUIRED_RUNTIME_RESOURCES = ["models/pose-models.json", "RUNBOOK.md"]

# environment.json and model-cache.json hold workstation paths; only sanitized derivatives ship.
CORE_METADATA_FILES = ["requirements.lock.txt"]
WORKSTATION_INVENTORIES = ["environment.json", "model-cache.json"]
# Reviewed public metadata only. Any byte change requires a separate source review.
PUBLIC_MODEL_MANIFEST_SHA256 = "e7b5d4316c9908145f536165a6aee29ea918426c7f9d1f658f4e9aea539c793b"
PUBLIC_MODEL_MANIFEST_BYTES = 1439
UNPROVISIONED_NATIVE = ("python-runtime", "opensim", "pose2sim", "ffmpeg", "ffprobe", "blender",
                        "onnxruntime", "rtmlib", "opencv-python")
# Documentation carrying private workstation identities must not be redistributed.
DOC_BLOCKED_PATTERNS = (re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\s\"'`<>)]*"),
                        re.compile(r"github\.com/sorensadrgit[^/\s]*", re.IGNORECASE))


# Explicit input only: never discover or copy the builder's installed environment.
PREPARED_RUNTIME_MANIFEST = None
PREPARED_INPUT_SCHEMA = "kinelab.prepared-runtime-input.v1"
PREPARED_FILE_LIMIT = 50000
PREPARED_TOTAL_LIMIT = 8 * 1024**3
PREPARED_MEMBER_LIMIT = 1024**3
PREPARED_JSON_LIMIT = 1024**2


def _prepared_refuse(code):
    raise ValueError("PREPARED_RUNTIME_" + code)


def _prepared_exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        _prepared_refuse("SCHEMA")
    return value


def _prepared_path(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 240
            or not re.fullmatch(r"[A-Za-z0-9_./+ -]+", value)):
        _prepared_refuse("PATH")
    parts = value.split("/")
    for part in parts:
        if (part in {"", ".", ".."} or part[-1:] in {" ", "."}
                or part.split(".")[0].upper() in
                {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}):
            _prepared_refuse("PATH")
    lower = value.lower()
    if (parts[0] not in {"runtime", "app"}
            or lower.endswith((".db", ".sqlite", ".sqlite3", ".pem", ".key", ".pfx", ".p12"))
            or any(part.lower() == ".env" or part.lower().startswith(".env.")
                   for part in parts)):
        _prepared_refuse("PATH")
    return value


def _prepared_hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        _prepared_refuse("HASH")
    return value


def _prepared_regular(path, limit):
    reject_link_traversal(path)
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size > limit):
        _prepared_refuse("FILE_BOUND")
    return info


def _prepared_stream(path, expected_size=None, expected_sha=None, destination=None,
                     *, collect=False, limit=PREPARED_MEMBER_LIMIT):
    before = _prepared_regular(path, limit)
    if expected_size is not None and before.st_size != expected_size:
        _prepared_refuse("SIZE")
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size)
    digest, count, pieces = hashlib.sha256(), 0, []
    with path.open("rb") as incoming:
        opened = os.fstat(incoming.fileno())
        if identity(opened) != identity(before):
            _prepared_refuse("SOURCE_CHANGED")
        outgoing = None
        try:
            if destination is not None:
                reject_link_traversal(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                reject_link_traversal(destination)
                outgoing = destination.open("xb")
            while block := incoming.read(min(1024**2, limit - count + 1)):
                count += len(block)
                if count > limit or count > before.st_size:
                    _prepared_refuse("SOURCE_CHANGED")
                digest.update(block)
                if collect:
                    pieces.append(block)
                if outgoing is not None:
                    outgoing.write(block)
            if outgoing is not None:
                outgoing.flush()
                os.fsync(outgoing.fileno())
        finally:
            if outgoing is not None:
                outgoing.close()
        closed = os.fstat(incoming.fileno())
    after = _prepared_regular(path, limit)
    if (identity(before) != identity(closed) or identity(before) != identity(after)
            or opened.st_mtime_ns != closed.st_mtime_ns
            or before.st_mtime_ns != after.st_mtime_ns or count != before.st_size):
        _prepared_refuse("SOURCE_CHANGED")
    actual = digest.hexdigest()
    if expected_sha is not None and actual != expected_sha:
        _prepared_refuse("HASH")
    return (b"".join(pieces) if collect else None), actual, count


def _prepared_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _prepared_refuse("DUPLICATE")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _value: _prepared_refuse("JSON"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("PREPARED_RUNTIME_JSON") from error


def prepared_runtime_input():
    try:
        return _prepared_runtime_input()
    except (OSError, UnicodeError) as error:
        raise ValueError("PREPARED_RUNTIME_INPUT_UNAVAILABLE") from error


def _prepared_runtime_input():
    """Validate byte admission, not scientific compatibility or redistribution clearance."""
    if PREPARED_RUNTIME_MANIFEST is None:
        return None
    manifest_path = Path(os.path.abspath(PREPARED_RUNTIME_MANIFEST))
    if str(manifest_path).startswith(("\\\\", "//")):
        _prepared_refuse("LOCAL_INPUT_REQUIRED")
    reject_link_traversal(manifest_path)
    if manifest_path.name != "prepared-runtime.json":
        _prepared_refuse("MANIFEST_NAME")
    root = manifest_path.parent
    for output in (TARGET_DIR, ZIP_PATH):
        output = Path(os.path.abspath(output))
        reject_link_traversal(output)
        if output == root or output.is_relative_to(root) or root.is_relative_to(output):
            _prepared_refuse("OVERLAP")
    raw, digest, _ = _prepared_stream(manifest_path, collect=True, limit=PREPARED_JSON_LIMIT)
    doc = _prepared_exact(_prepared_json(raw),
                          ("schema", "profile", "source_artifact", "dependencies",
                           "licenses", "entrypoints", "models", "files"))
    if doc["schema"] != PREPARED_INPUT_SCHEMA:
        _prepared_refuse("SCHEMA")
    profile = _prepared_exact(doc["profile"], ("platform", "python_abi",
                              "dependency_resolution_sha256", "cv2_provider_policy_sha256"))
    if profile["platform"] != "windows-amd64" or profile["python_abi"] != "cp313":
        _prepared_refuse("PROFILE")
    source = _prepared_exact(doc["source_artifact"],
                            ("kind", "sha256", "size_bytes", "source_reference"))
    if source["kind"] not in {"PREPARED_TREE", "ORIGINAL_ARTIFACT"}:
        _prepared_refuse("PROVENANCE")
    if source["kind"] == "ORIGINAL_ARTIFACT":
        _prepared_hash(source["sha256"])
        if type(source["size_bytes"]) is not int or source["size_bytes"] <= 0:
            _prepared_refuse("PROVENANCE")
    elif source["sha256"] is not None or source["size_bytes"] is not None:
        _prepared_refuse("PROVENANCE")
    # References are opaque public identifiers, never local paths, credentials or authority.
    references = [source["source_reference"]]
    if not isinstance(doc["licenses"], list) or not 1 <= len(doc["licenses"]) <= 1000:
        _prepared_refuse("LICENSE")
    licenses = {}
    for value in doc["licenses"]:
        item = _prepared_exact(value, ("id", "path", "source_reference",
                                       "redistribution_evidence_reference"))
        if (not isinstance(item["id"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", item["id"])
                or item["id"] in licenses):
            _prepared_refuse("LICENSE")
        path = _prepared_path(item["path"])
        if not path.startswith("runtime/licenses/"):
            _prepared_refuse("LICENSE")
        licenses[item["id"]] = path
        references.extend((item["source_reference"], item["redistribution_evidence_reference"]))
    for value in references:
        if (not isinstance(value, str) or not 1 <= len(value) <= 500
                or not re.fullmatch(r"[A-Za-z0-9_./:+# -]+", value)
                or "\\" in value or "@" in value or "?" in value
                or re.search(r"(^|[ /])[A-Za-z]:/", value)):
            _prepared_refuse("REFERENCE")
    if not isinstance(doc["files"], list) or not 1 <= len(doc["files"]) <= PREPARED_FILE_LIMIT:
        _prepared_refuse("INVENTORY")
    members, folded, total = {}, set(), 0
    for value in doc["files"]:
        item = _prepared_exact(value, ("path", "size_bytes", "sha256", "license_id"))
        path = _prepared_path(item["path"])
        if (not path.startswith(("runtime/python/", "runtime/licenses/", "runtime/policy/"))
                and path not in {"runtime/bin/ffmpeg.exe", "runtime/bin/ffprobe.exe",
                                 "app/models/pose-v1/detector.onnx", "app/models/pose-v1/pose.onnx"}):
            _prepared_refuse("PATH")
        if (not path.startswith(("runtime/python/", "runtime/licenses/", "runtime/policy/"))
                and path not in {"runtime/bin/ffmpeg.exe", "runtime/bin/ffprobe.exe",
                                 "app/models/pose-v1/detector.onnx", "app/models/pose-v1/pose.onnx"}):
            _prepared_refuse("PATH")
        if path.casefold() in folded:
            _prepared_refuse("DUPLICATE")
        folded.add(path.casefold())
        if (type(item["size_bytes"]) is not int or not 0 <= item["size_bytes"] <= PREPARED_MEMBER_LIMIT
                or not isinstance(item["license_id"], str) or item["license_id"] not in licenses):
            _prepared_refuse("INVENTORY")
        _prepared_hash(item["sha256"])
        total += item["size_bytes"]
        if total > PREPARED_TOTAL_LIMIT:
            _prepared_refuse("TOTAL_BOUND")
        members[path] = item
    expected_entries = {"python": "runtime/python/python.exe",
                        "pythonw": "runtime/python/pythonw.exe",
                        "ffmpeg": "runtime/bin/ffmpeg.exe", "ffprobe": "runtime/bin/ffprobe.exe"}
    if doc["entrypoints"] != expected_entries:
        _prepared_refuse("ENTRYPOINT")
    model_raw, model_digest, _ = _prepared_stream(ROOT / "models/pose-models.json",
                                                   collect=True, limit=PREPARED_JSON_LIMIT)
    model_spec = _prepared_json(model_raw)
    models = _prepared_exact(doc["models"], ("model_set_id", "model_manifest_sha256", "files"))
    if (model_spec.get("id") != "rtmlib-coco17-cpu-v1"
            or models["model_set_id"] != model_spec["id"]
            or models["model_manifest_sha256"] != model_digest):
        _prepared_refuse("MODEL_ID")
    expected_models = {f"app/models/pose-v1/{item['filename']}":
                       (item["bytes"], item["sha256"]) for item in model_spec["models"]}
    if set(expected_models) != {"app/models/pose-v1/detector.onnx", "app/models/pose-v1/pose.onnx"}:
        _prepared_refuse("MODEL_ID")
    if models["files"] != sorted(expected_models):
        _prepared_refuse("MODEL_ID")
    mandatory = {*expected_entries.values(), *licenses.values(),
                 "runtime/policy/dependencies.json", "runtime/policy/cv2-provider.json",
                 *expected_models}
    if not mandatory <= set(members):
        _prepared_refuse("INCOMPLETE")
    if any(members[path]["size_bytes"] == 0 for path in mandatory):
        _prepared_refuse("INCOMPLETE")
    for path, proof in expected_models.items():
        if (members[path]["size_bytes"], members[path]["sha256"]) != proof:
            _prepared_refuse("MODEL_ID")
    for key, path in (("dependency_resolution_sha256", "runtime/policy/dependencies.json"),
                      ("cv2_provider_policy_sha256", "runtime/policy/cv2-provider.json")):
        if _prepared_hash(profile[key]) != members[path]["sha256"]:
            _prepared_refuse("POLICY_BINDING")
    dependencies = doc["dependencies"]
    if (not isinstance(dependencies, list) or not dependencies
            or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", value)
                   for value in dependencies)
            or len({value.casefold() for value in dependencies}) != len(dependencies)):
        _prepared_refuse("DEPENDENCIES")
    lock = ROOT / "requirements.lock.txt"
    lock_raw, _, _ = _prepared_stream(lock, collect=True, limit=PREPARED_JSON_LIMIT)
    pinned = [line.strip() for line in lock_raw.decode("utf-8-sig").splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    if sorted(dependencies, key=str.casefold) != sorted(pinned, key=str.casefold):
        _prepared_refuse("DEPENDENCIES")
    actual = set()
    pending, visited = [root], 0
    while pending:
        directory = pending.pop()
        reject_link_traversal(directory)
        for path in directory.iterdir():
            visited += 1
            if visited > 2 * PREPARED_FILE_LIMIT:
                _prepared_refuse("INVENTORY_BOUND")
            reject_link_traversal(path)
            relative = path.relative_to(root).as_posix()
            if path.is_dir():
                _prepared_path(relative)
                if len(relative.split("/")) > 30:
                    _prepared_refuse("PATH")
                pending.append(path)
            elif path == manifest_path:
                _prepared_regular(path, PREPARED_JSON_LIMIT)
            else:
                _prepared_path(relative)
                if relative not in members or len(actual) >= PREPARED_FILE_LIMIT:
                    _prepared_refuse("UNDECLARED")
                actual.add(relative)
    if actual != set(members):
        _prepared_refuse("INCOMPLETE")
    for path, item in members.items():
        _prepared_stream(root / path, item["size_bytes"], item["sha256"])
    if _prepared_stream(manifest_path, collect=True, limit=PREPARED_JSON_LIMIT)[1] != digest:
        _prepared_refuse("SOURCE_CHANGED")
    return {"root": root, "raw": raw, "sha256": digest, "document": doc}


def stage_prepared_runtime(selection):
    try:
        _stage_prepared_runtime(selection)
    except OSError as error:
        raise ValueError("PREPARED_RUNTIME_STAGING_UNAVAILABLE_PARTIAL_RETAINED") from error


def _stage_prepared_runtime(selection):
    """CreateNew only; retain partial output and refuse any changed selection."""
    refreshed = prepared_runtime_input()
    if refreshed is None or refreshed["raw"] != selection["raw"]:
        _prepared_refuse("SOURCE_CHANGED")
    # This persistent PENDING witness is not a completion manifest or runtime authority.
    # Retain it on every outcome so a later process cannot publish partial prepared bytes.
    intent_path = TARGET_DIR / "PREPARED-RUNTIME-STAGING.json"
    reject_link_traversal(intent_path)
    intent = json.dumps({"schema": "kinelab.prepared-runtime-staging-intent.v1",
                         "state": "PENDING", "input_manifest_sha256": selection["sha256"]},
                        sort_keys=True, separators=(",", ":")).encode("utf-8")
    with intent_path.open("xb") as stream:
        stream.write(intent)
        stream.flush()
        os.fsync(stream.fileno())
    for item in selection["document"]["files"]:
        source = selection["root"] / item["path"]
        target = TARGET_DIR / item["path"]
        _prepared_stream(source, item["size_bytes"], item["sha256"], target)
        _prepared_stream(target, item["size_bytes"], item["sha256"])
    final = prepared_runtime_input()
    if final is None or final["raw"] != selection["raw"]:
        _prepared_refuse("SOURCE_CHANGED")
    members = {item["path"]: item for item in selection["document"]["files"]}
    actual, pending, visited = set(), [TARGET_DIR / "runtime", TARGET_DIR / "app/models/pose-v1"], 0
    while pending:
        directory = pending.pop()
        reject_link_traversal(directory)
        for target in directory.iterdir():
            visited += 1
            if visited > 2 * PREPARED_FILE_LIMIT:
                _prepared_refuse("INVENTORY_BOUND")
            reject_link_traversal(target)
            if target.is_dir():
                pending.append(target)
            else:
                relative = target.relative_to(TARGET_DIR).as_posix()
                if relative not in members:
                    _prepared_refuse("STAGED_UNDECLARED")
                item = members[relative]
                _prepared_stream(target, item["size_bytes"], item["sha256"])
                actual.add(relative)
    if actual != set(members):
        _prepared_refuse("STAGED_INCOMPLETE")
    with (TARGET_DIR / "PREPARED-RUNTIME-INPUT.json").open("xb") as stream:
        stream.write(selection["raw"])
        stream.flush()
        os.fsync(stream.fileno())


def packaged_docs():
    """Split docs/*.md into shippable files and private-path exclusions (fail closed)."""
    docs = ROOT / "docs"
    reject_link_traversal(docs)
    included, excluded = [], []
    for path in sorted(docs.glob("*.md")):
        text = path.read_text(encoding="utf-8-sig")
        if any(pattern.search(text) for pattern in DOC_BLOCKED_PATTERNS):
            excluded.append(path.name)
        else:
            included.append(path)
    return included, excluded
FRONTEND_DIST = None  # Explicit fresh build directory; None means the legacy viewer/dist location.
FRONTEND_INPUTS = None  # Path to a frontend input record captured before that build.


def frontend_dist() -> Path:
    return Path(FRONTEND_DIST) if FRONTEND_DIST is not None else ROOT / "viewer" / "dist"


def local_dependencies(root: Path, name: str):
    """Return first-party flat modules referenced by imports or literal script names."""
    tree = ast.parse((root / name).read_text(encoding="utf-8-sig"), filename=name)
    found, packages = set(), set()
    for node in ast.walk(tree):
        stems = []
        if isinstance(node, ast.Import):
            stems = [item.name.split(".")[0] for item in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            stems = [node.module.split(".")[0]]
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and node.value.endswith(".py") and Path(node.value).name == node.value):
            stems = [node.value[:-3]]
        for stem in stems:
            if (root / (stem + ".py")).is_file():
                found.add(stem + ".py")
            elif (root / stem / "__init__.py").is_file():
                packages.add(f"{name} -> {stem}/")
    return found, packages


def runtime_closure(root: Path | None = None):
    """Transitive first-party module closure plus unresolvable prerequisites."""
    root = ROOT if root is None else root
    closure, problems, pending = set(), [], list(PACKAGE_ENTRY_POINTS)
    while pending:
        name = pending.pop()
        if name in closure:
            continue
        path = root / name
        reject_link_traversal(path)
        if not path.is_file():
            problems.append(f"Required module missing: {name}")
            continue
        closure.add(name)
        found, packages = local_dependencies(root, name)
        problems.extend(f"Package-directory import is not staged (flat modules only): {item}"
                        for item in sorted(packages))
        pending.extend(sorted(found - closure))
    return sorted(closure), problems


def runtime_modules(root: Path | None = None):
    modules, problems = runtime_closure(root)
    if problems:
        raise RuntimeError("; ".join(problems))
    return modules


def sha256_file(path: Path) -> str:
    reject_link_traversal(path)
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def reject_link_traversal(path: Path):
    """Reject symlinks and every Windows reparse point before following a path."""
    for part in [Path(path).absolute(), *Path(path).absolute().parents]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Symlink/junction/reparse traversal refused: {part}")


def checked_files(path: Path):
    reject_link_traversal(path)
    if path.is_dir():
        for child in sorted(path.iterdir()):
            yield from checked_files(child)
    elif path.is_file():
        yield path
    else:
        raise ValueError(f"Unsupported package input: {path}")


def validate_destination(*, new_staging=False):
    allowed = ROOT / "dist"
    for path in (allowed, TARGET_DIR, ZIP_PATH):
        reject_link_traversal(path)
    allowed = allowed.resolve()
    for path in (TARGET_DIR, ZIP_PATH):
        resolved = path.resolve()
        if resolved == allowed or not resolved.is_relative_to(allowed):
            raise ValueError("Package destination must be inside workspace dist")
    if new_staging and TARGET_DIR.exists():
        raise FileExistsError(f"Staging destination already exists: {TARGET_DIR}")
    if ZIP_PATH.exists():
        raise FileExistsError(f"Archive destination already exists: {ZIP_PATH}")


def payload_files():
    paths = [(ROOT / name, "app/" + name) for name in
             [*runtime_modules(), *REQUIRED_RUNTIME_RESOURCES]]
    paths += [(ROOT / name, "app/" + name) for name in CORE_METADATA_FILES]
    frontend = frontend_dist()
    paths += [(path, "app/viewer/dist/" + path.relative_to(frontend).as_posix())
              for path in checked_files(frontend)]
    paths += [(path, "app/" + path.relative_to(ROOT).as_posix())
              for path in checked_files(ROOT / "assets")]
    paths += [(path, "docs/" + path.name) for path in packaged_docs()[0]]
    for path, _ in paths:
        reject_link_traversal(path)
    return sorted(paths, key=lambda item: item[1])


def git_identity():
    unavailable = {"status": "UNAVAILABLE", "head": None, "dirty": None}
    if not (ROOT / ".git").exists():
        return unavailable
    environment = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    try:
        def read(*arguments):
            return subprocess.run(["git", "-C", str(ROOT), *arguments], check=True,
                                  capture_output=True, text=True, encoding="utf-8",
                                  timeout=15, env=environment).stdout.strip()
        head = read("rev-parse", "--verify", "HEAD")
        status = read("status", "--porcelain=v1", "--untracked-files=all")
        return {"status": "OBSERVED", "head": head, "dirty": bool(status),
                "status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest()}
    except (OSError, subprocess.SubprocessError):
        return unavailable


def source_snapshot():
    def entry(path, relative):
        return {"path": relative, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
    payload = [entry(path, relative.removeprefix("app/") if relative.startswith("app/")
                     else path.relative_to(ROOT).as_posix()) for path, relative in payload_files()]
    source = [item for item in payload if not item["path"].startswith("viewer/dist/")] + frontend_inputs()
    build = [item for item in payload if item["path"].startswith("viewer/dist/")]
    def digest(entries):
        return hashlib.sha256(json.dumps(sorted(entries, key=lambda item: item["path"]),
                                         sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"schema": "kinelab.package-source.v1", "source_sha256": digest(source),
            "frontend_build_sha256": digest(build), "source_files": source,
            "frontend_build_files": build, "frontend_source_build_match": frontend_match(),
            "git": git_identity()}


FRONTEND_INPUT_PATHS = ("tools/build_offline_distribution.py", "viewer/package.json",
                        "viewer/package-lock.json", "viewer/vite.config.js", "viewer/index.html",
                        "viewer/src", "viewer/public")


def frontend_inputs():
    entries = []
    for relative in FRONTEND_INPUT_PATHS:
        path = ROOT / relative
        reject_link_traversal(path)
        if path.exists():
            entries.extend({"path": item.relative_to(ROOT).as_posix(), "sha256": sha256_file(item),
                            "size_bytes": item.stat().st_size} for item in checked_files(path))
    return sorted(entries, key=lambda item: item["path"])


def capture_frontend_inputs(out: Path):
    """Record frontend source hashes before a build so the package can bind them later."""
    out = Path(out)
    reject_link_traversal(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    record = {"schema": "kinelab.frontend-build-inputs.v1", "captured_utc":
              datetime.datetime.now(datetime.UTC).isoformat(),
              "source_files": [item for item in frontend_inputs()
                               if item["path"] != "tools/build_offline_distribution.py"]}
    with out.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
    return record


def frontend_match():
    if FRONTEND_INPUTS is None:
        return "UNVERIFIED"
    record = json.loads(Path(FRONTEND_INPUTS).read_text(encoding="utf-8"))
    current = [item for item in frontend_inputs() if item["path"] != "tools/build_offline_distribution.py"]
    if record.get("schema") != "kinelab.frontend-build-inputs.v1" or record.get("source_files") != current:
        raise ValueError("Frontend source changed since its build inputs were captured")
    # Matching inputs bind the build to this source; byte-reproducibility is still not established.
    return "INPUTS_MATCH_RECORDED_BUILD_UNREPRODUCED"


def validate_frontend_dist():
    if FRONTEND_DIST is None:
        return
    frontend, allowed = Path(FRONTEND_DIST), ROOT / "dist"
    reject_link_traversal(frontend)
    resolved = frontend.resolve()
    if not resolved.is_relative_to(allowed.resolve()) or resolved == allowed.resolve():
        raise ValueError("Frontend build must be a dedicated directory inside workspace dist")
    for output in (TARGET_DIR, ZIP_PATH):
        if resolved == output.resolve() or resolved.is_relative_to(output.resolve()) \
                or output.resolve().is_relative_to(resolved):
            raise ValueError("Frontend build directory must not overlap the package output")
    if FRONTEND_INPUTS is None:
        raise ValueError("An explicit frontend build requires --frontend-inputs captured before the build")
    record = Path(FRONTEND_INPUTS)
    reject_link_traversal(record)
    if not record.is_file():
        raise ValueError("Frontend input record missing; capture it with --capture-frontend-inputs first")
    # Copied viewer/public assets may keep old mtimes, so staleness is content-based for them.
    captured = record.stat().st_mtime
    recorded = json.loads(record.read_text(encoding="utf-8")).get("source_files", [])
    public_hashes = {item.get("sha256") for item in recorded
                     if str(item.get("path", "")).startswith("viewer/public/")}
    stale = [path for path in checked_files(frontend)
             if path.stat().st_mtime < captured and sha256_file(path) not in public_hashes]
    if stale:
        raise ValueError("Frontend build predates its input record; build into a new directory: "
                         + ", ".join(path.name for path in stale))


def installed_distribution(name: str):
    from importlib import metadata
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    meta = dist.metadata
    license_value = meta.get("License-Expression") or meta.get("License")
    if license_value and (len(license_value) > 120 or "\n" in license_value):
        license_value = "SEE_DISTRIBUTION_LICENSE_TEXT"
    return {"version": dist.version, "license": license_value or "NOT_DECLARED_IN_METADATA"}


def approved_public_model_manifest():
    """Return the exact reviewed public specification buffer; never inspect local caches."""
    path = ROOT / "models/pose-models.json"
    reject_link_traversal(path)
    if path.stat().st_size != PUBLIC_MODEL_MANIFEST_BYTES:
        raise ValueError("PUBLIC_MODEL_METADATA_NOT_APPROVED")
    with path.open("rb") as stream:
        raw = stream.read(PUBLIC_MODEL_MANIFEST_BYTES + 1)
    if (len(raw) != PUBLIC_MODEL_MANIFEST_BYTES
            or hashlib.sha256(raw).hexdigest() != PUBLIC_MODEL_MANIFEST_SHA256):
        raise ValueError("PUBLIC_MODEL_METADATA_NOT_APPROVED")
    return raw


def runtime_provisioning():
    """Sanitized dependency/model/native state; never emits workstation paths."""
    return _runtime_provisioning_from_verified_model(approved_public_model_manifest())


def _runtime_provisioning_from_verified_model(model_raw):
    """Build the report from the captured public buffer, without reopening its path."""
    if (len(model_raw) != PUBLIC_MODEL_MANIFEST_BYTES
            or hashlib.sha256(model_raw).hexdigest() != PUBLIC_MODEL_MANIFEST_SHA256):
        raise ValueError("PUBLIC_MODEL_METADATA_NOT_APPROVED")
    pins, lock = [], ROOT / "requirements.lock.txt"
    if lock.is_file():
        for line in lock.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "==" in line:
                name, version = line.split("==", 1)
                installed = installed_distribution(name)
                pins.append({"name": name, "pinned_version": version,
                             "builder_interpreter_version": installed and installed["version"],
                             "license": installed["license"] if installed else "UNAVAILABLE",
                             "artifact_sha256": None, "artifact_sha256_status": "UNAVAILABLE_NO_WHEEL_HASH",
                             "provisioning": "NOT_PROVISIONED"})
    manifest = json.loads(model_raw)
    models = [{"filename": item.get("filename"), "expected_sha256": item.get("sha256"),
               "expected_bytes": item.get("bytes"), "archive_sha256": item.get("archive_sha256"),
               "source_url": item.get("url"), "provisioning": "NOT_PROVISIONED"}
              for item in manifest.get("models", [])]
    return {"schema": "kinelab.runtime-provisioning.v1",
            "dependency_inventory_source": "requirements.lock.txt" if lock.is_file() else None,
            "dependency_license_source": "builder interpreter installed distribution metadata",
            "dependencies": pins,
            "model_set": {"id": manifest.get("id"), "license": manifest.get("source_license"),
                          "runtime": manifest.get("runtime"), "weights": models,
                          "weights_redistribution": "NOT_ESTABLISHED"},
            "observed_workstation_model_cache": [],
            "workstation_model_cache_status": "NOT_INSPECTED_PRIVATE_INPUT",
            "native": {name: "NOT_PROVISIONED" for name in UNPROVISIONED_NATIVE},
            "vulnerability_scan": "NOT_RUN_BY_PACKAGER",
            "clinical_validation_status": "UNVERIFIED",
            "physical_validation_status": "BLOCKED_ON_PHYSICAL_EVIDENCE"}


def check_prerequisites():
    print("[1/6] Checking packaging prerequisites...")
    prepared_runtime_input()  # Explicit admission completes before any destination is created.
    # Every missing prerequisite is reported together so one repair pass can address them.
    problems = []
    validate_frontend_dist()
    if not (frontend_dist() / "index.html").is_file():
        problems.append("Frontend build missing index.html; build the viewer into a new directory "
                        "under dist and pass it with --frontend-dist")
    modules, closure_problems = runtime_closure()
    problems += closure_problems
    problems += [f"Required runtime resource missing: {resource}"
                 for resource in [*REQUIRED_RUNTIME_RESOURCES, *CORE_METADATA_FILES]
                 if not (ROOT / resource).is_file()]
    if not (ROOT / "assets" / "kinelab-pt.ico").is_file():
        problems.append("Application icon missing: assets/kinelab-pt.ico")
    if problems:
        raise RuntimeError("Missing packaging prerequisites: " + "; ".join(problems))
    approved_public_model_manifest()
    payload_files()  # Reject linked inputs before any content read or staging mutation.
    print(f"  -> {len(modules)} Python sources (derived import closure) and required resources present.")
    included_docs, excluded_docs = packaged_docs()
    for name in excluded_docs:
        print(f"  -> Doc excluded from package (private workstation path or repository): docs/{name}")
    print(f"  -> {len(included_docs)} docs staged, {len(excluded_docs)} excluded.")
    print("  -> Model weights and native tools are not provisioned by this package.")


def copy_application_files():
    print("[2/6] Staging application files...")
    prepared = prepared_runtime_input()
    validate_destination(new_staging=True)
    model_raw = approved_public_model_manifest()
    snapshot = source_snapshot()
    inputs = payload_files()
    TARGET_DIR.mkdir(parents=True, exist_ok=False)
    for source, relative in inputs:
        destination = TARGET_DIR / relative
        reject_link_traversal(source)
        reject_link_traversal(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if relative == "app/models/pose-models.json":
            with destination.open("xb") as outgoing:
                outgoing.write(model_raw)
        else:
            with source.open("rb") as incoming, destination.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
        if sha256_file(destination) != sha256_file(source):
            raise ValueError("Source changed during staging")
    if source_snapshot() != snapshot:
        raise ValueError("Source changed during staging; partial destination retained")
    if prepared is not None:
        stage_prepared_runtime(prepared)
    with (TARGET_DIR / "SOURCE-PROVENANCE.json").open("x", encoding="utf-8") as stream:
        json.dump(snapshot, stream, indent=2)
    with (TARGET_DIR / "RUNTIME-PROVISIONING.json").open("x", encoding="utf-8") as stream:
        record = _runtime_provisioning_from_verified_model(model_raw)
        if prepared is not None:
            record["prepared_input"] = {
                "schema": PREPARED_INPUT_SCHEMA,
                "manifest_sha256": prepared["sha256"],
                "state": "FILES_VERIFIED_PROFILE_UNRESOLVED_NATIVE_NOT_RUN",
                "native_activation": "NOT_RUN", "relocation": "NOT_RUN",
                "clean_host": "NOT_RUN", "dependency_policy_review": "NOT_ESTABLISHED",
                "redistribution_clearance": "NOT_ESTABLISHED",
                "original_artifact": prepared["document"]["source_artifact"],
            }
        json.dump(record, stream, indent=2)

    print(f"  -> Staged core modules, viewer assets, and docs to {TARGET_DIR}")


def _require_resolved_prepared_profile():
    # Admission verifies bytes only. Do not emit legacy PATH/sibling fallback for a selected payload.
    if (PREPARED_RUNTIME_MANIFEST is not None
            or (TARGET_DIR / "PREPARED-RUNTIME-INPUT.json").exists()
            or os.path.lexists(TARGET_DIR / "PREPARED-RUNTIME-STAGING.json")):
        raise RuntimeError("PREPARED_RUNTIME_PROFILE_NOT_ESTABLISHED")


def write_launcher_scripts():
    _require_resolved_prepared_profile()
    print("[3/6] Generating portable launchers and installation scripts...")
    validate_destination()

    provenance_raw, _, _ = _prepared_stream(
        TARGET_DIR / "SOURCE-PROVENANCE.json", collect=True, limit=16 * 1024**2)
    provenance = _prepared_json(provenance_raw)
    bindings = [entry for entry in provenance["source_files"]
                if entry["path"] == "tools/build_offline_distribution.py"]
    if len(bindings) != 1:
        raise ValueError("Standalone verifier source binding missing or ambiguous")
    binding = bindings[0]
    _prepared_stream(Path(__file__).absolute(), binding["size_bytes"], binding["sha256"],
                     destination=TARGET_DIR / "tools/build_offline_distribution.py",
                     limit=1024**2)

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
%PYTHON_EXE% -B t6_launcher.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] KineLab PT exited with error code %errorlevel%.
    pause
    exit /b %errorlevel%
)
endlocal
"""
    with (TARGET_DIR / "Start-KineLabPT.bat").open("x", encoding="utf-8") as stream:
        stream.write(bat_content)

    # Install-DesktopShortcut.ps1
    ps1_content = """# KineLab PT - Desktop Shortcut Installer
# Creates exactly one desktop shortcut for KineLab PT
$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $ScriptDir "app"
$Desktop = [Environment]::GetFolderPath("Desktop")
# A distinct candidate name: the original "KineLab PT.lnk" is never created, modified or replaced.
$ShortcutPath = Join-Path $Desktop "KineLab PT Candidate.lnk"
$OriginalPath = Join-Path $Desktop "KineLab PT.lnk"
$IconPath = Join-Path $AppDir "assets\\kinelab-pt.ico"
$LauncherPy = Join-Path $AppDir "t6_launcher.py"

Write-Host "KineLab PT Candidate Desktop Shortcut Configuration" -ForegroundColor Cyan
Write-Host "Target Shortcut: $ShortcutPath"
if (Test-Path $OriginalPath) {
    Write-Host "Preserving existing original shortcut untouched: $OriginalPath"
}
if (Test-Path $ShortcutPath) {
    Write-Error "Refusing to overwrite existing shortcut: $ShortcutPath. Remove it yourself first."
    exit 1
}

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
    $launcherArguments = ""
} else {
    $target = $pythonw
    $launcherArguments = "-B `"$LauncherPy`""
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $target
if ($launcherArguments) { $Shortcut.Arguments = $launcherArguments }
$Shortcut.WorkingDirectory = $AppDir
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = "$IconPath,0"
}
$Shortcut.Description = "KineLab PT Candidate - Motion Analysis Research Platform"
$Shortcut.Save()

Write-Host "Success: Desktop shortcut 'KineLab PT Candidate' created; no existing shortcut was modified." -ForegroundColor Green
"""
    with (TARGET_DIR / "Install-DesktopShortcut.ps1").open("x", encoding="utf-8") as stream:
        stream.write(ps1_content)

    # README-OFFLINE-INSTALL.md
    readme_content = """# KineLab PT — Offline Distribution Package (v1.0.0)

## Prerequisites and verification scope
- **Target**: Windows x64. Clean-machine installation, compatibility and minimum hardware performance remain UNVERIFIED.
- **Python dependencies**: The source requires Pose2Sim, OpenSim for native processing, rtoml, NumPy, Matplotlib and psutil. `app/requirements.lock.txt` records an environment inventory; it is not a validated offline installer or compatibility matrix.
- **Video tools**: `ffprobe` is required for video inspection; `ffmpeg` is required for normalization and capture. These executables are not provisioned by this package.
- **Optional Blender export**: `blender_import.py` targets Blender 4.5+; Blender is not provisioned or executed by the packager.
- **Live inference**: `app/models/pose-models.json` declares model identities and runtime versions. Model weights, ONNX Runtime, RTMLib and OpenCV are not provisioned by the packager. Missing weights remain unavailable; no automatic download is performed by the local inference adapter.
- **Evidence**: Package integrity covers staged file hashes only. It does not establish software build, runtime, physical or clinical validation. The launch scripts locate Python but do not check its version or dependency compatibility.

## Installation preparation (offline operation remains UNVERIFIED)

Provision and validate the required Python environment, video executables and any approved models separately before attempting offline use. Do not treat the environment or cache inventory as a successful clean-machine installation.

1. **Extract Distribution Archive**:
   Extract `KineLabPT-v1.0.0-windows-x64.zip` to an application directory. Project data is kept outside that directory (see below).

2. **Verify Desktop Shortcut**:
   Run `powershell -ExecutionPolicy Bypass -File .\\Install-DesktopShortcut.ps1` to create the `KineLab PT Candidate` desktop shortcut. The installer refuses to overwrite any existing shortcut and never modifies an original `KineLab PT.lnk`.

3. **Launch Application**:
   Double-click the `KineLab PT Candidate` desktop shortcut or execute `Start-KineLabPT.bat`.
   The application starts a secure localhost server (`127.0.0.1:4184+`) with an instance token and opens the unified workspace in your default web browser.

## Current data storage
- **Project data**: `t6_launcher.py` uses the dedicated candidate data root `%LOCALAPPDATA%\\KineLabPT-Candidate-M1\\data`, or the directory given by `--data-root` / `KINELAB_CANDIDATE_DATA_ROOT`. The application directory, the legacy `%LOCALAPPDATA%\\KineLabPT` location and earlier installations are refused; existing data is never discovered or migrated.
- **Launcher state**: Instance state and launcher/server logs use `%LOCALAPPDATA%\\KineLabPT-Candidate-M1\\runtime`.
- **Provisioning record**: `RUNTIME-PROVISIONING.json` lists pinned dependencies, declared licenses from installed metadata where available, expected model hashes and native tools; every item is marked NOT_PROVISIONED by this package.
- **Source media**: Keep originals and backups separate from package replacement. Package integrity checks do not validate capture preservation or restore behavior.
"""
    with (TARGET_DIR / "README-OFFLINE-INSTALL.md").open("x", encoding="utf-8") as stream:
        stream.write(readme_content.replace("KineLabPT-v1.0.0-windows-x64.zip", ZIP_PATH.name))
    print("  -> Launchers and setup scripts written.")


def generate_manifest():
    print("[4/6] Computing SHA-256 distribution manifest...")
    validate_destination()
    provenance_path = TARGET_DIR / "SOURCE-PROVENANCE.json"
    reject_link_traversal(provenance_path)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if source_snapshot() != provenance:
        raise ValueError("Source changed since staging; refuse manifest")
    list(checked_files(TARGET_DIR))
    manifest_entries = []
    total_bytes = 0

    for root, _, files in os.walk(TARGET_DIR):
        for f in files:
            p = Path(root) / f
            rel = p.relative_to(TARGET_DIR).as_posix()
            if rel == "DISTRIBUTION-MANIFEST.json":
                continue
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
        "built_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "total_files": len(manifest_entries),
        "total_bytes": total_bytes,
        "platform": "windows-x64",
        "verification_status": "PACKAGE_INTEGRITY_NOT_CHECKED",
        "software_build_status": "NOT_RUN",
        "runtime_validation_status": "NOT_RUN",
        "physical_validation_status": "BLOCKED_ON_PHYSICAL_EVIDENCE",
        "clinical_validation_status": "UNVERIFIED",
        "provenance": {key: provenance[key] for key in
                       ("source_sha256", "frontend_build_sha256", "frontend_source_build_match", "git")},
        "source_provenance_sha256": sha256_file(provenance_path),
        "runtime_provisioning_sha256": sha256_file(TARGET_DIR / "RUNTIME-PROVISIONING.json"),
        "files": manifest_entries,
    }

    manifest_path = TARGET_DIR / "DISTRIBUTION-MANIFEST.json"
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest_doc, stream, indent=2)
    print(f"  -> Generated manifest: {len(manifest_entries)} files, {total_bytes:,} bytes.")


def _distribution_signature(path):
    reject_link_traversal(path)
    value = path.stat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ValueError("Package member must be an ordinary file with one link")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _distribution_manifest():
    """Read-only check shared by manifest verification and archive publication."""
    paths = list(checked_files(TARGET_DIR))
    before = {p.relative_to(TARGET_DIR).as_posix(): _distribution_signature(p) for p in paths}
    manifest = TARGET_DIR / "DISTRIBUTION-MANIFEST.json"
    raw, _, _ = _prepared_stream(manifest, collect=True, limit=16 * 1024**2)
    data = _prepared_json(raw)
    if (not isinstance(data, dict) or data.get("schema") != "kinelab.distribution.manifest.v1"
            or data.get("package_name") != PACKAGE_NAME or not isinstance(data.get("files"), list)):
        raise ValueError("Invalid package manifest")
    expected = {}
    for entry in data["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size_bytes"}:
            raise ValueError("Invalid package manifest entry")
        name, size, digest = entry["path"], entry["size_bytes"], entry["sha256"]
        if (not isinstance(name, str) or not name or "\\" in name or ":" in name
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or name == "DISTRIBUTION-MANIFEST.json" or name.casefold() in expected
                or type(size) is not int or size < 0
                or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            raise ValueError("Invalid or duplicate package manifest path, size or hash")
        expected[name.casefold()] = entry
    entries = {entry["path"]: entry for entry in expected.values()}
    actual = set(before) - {"DISTRIBUTION-MANIFEST.json"}
    if set(entries) != actual or data.get("total_files") != len(entries) or type(data.get("total_files")) is not int:
        raise ValueError("Package files differ from manifest (missing, duplicate or unlisted files)")
    total = sum(entry["size_bytes"] for entry in entries.values())
    if type(data.get("total_bytes")) is not int or data["total_bytes"] != total:
        raise ValueError("Invalid package manifest byte count")
    for name, entry in entries.items():
        _prepared_stream(TARGET_DIR / name, entry["size_bytes"], entry["sha256"],
                         limit=entry["size_bytes"])
    after = {p.relative_to(TARGET_DIR).as_posix(): _distribution_signature(p)
             for p in checked_files(TARGET_DIR)}
    if before != after:
        raise ValueError("Package changed while checking manifest")
    return raw, data, entries, after


def create_zip_archive():
    _require_resolved_prepared_profile()
    print("[6/6] Creating ZIP distribution archive...")
    validate_destination()
    raw, data, entries, identities = _distribution_manifest()
    if data.get("verification_status") != "PACKAGE_INTEGRITY_VERIFIED":
        raise ValueError("Package manifest must be verified before archive publication")
    partial = Path(str(ZIP_PATH) + ".partial")
    reject_link_traversal(partial)
    # Retain this CreateNew file on every outcome, including as a successful publication witness.
    # A hard link publishes without replacement; an unsupported filesystem fails closed.
    with partial.open("xb") as outgoing:
        with zipfile.ZipFile(outgoing, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{PACKAGE_NAME}/DISTRIBUTION-MANIFEST.json", raw)
            for name, entry in sorted(entries.items()):
                source = TARGET_DIR / name
                if _distribution_signature(source) != identities[name]:
                    raise ValueError("Package member changed before archive read")
                digest, count = hashlib.sha256(), 0
                with source.open("rb") as incoming, archive.open(f"{PACKAGE_NAME}/{name}", "w") as member:
                    opened = os.fstat(incoming.fileno())
                    if (opened.st_dev, opened.st_ino, opened.st_size) != identities[name][:3]:
                        raise ValueError("Package member identity changed before archive read")
                    while block := incoming.read(65536):
                        count += len(block)
                        if count > entry["size_bytes"]:
                            raise ValueError("Package member grew during archive read")
                        digest.update(block)
                        if member.write(block) != len(block):
                            raise OSError("Short package archive write")
                    closed = os.fstat(incoming.fileno())
                if (count != entry["size_bytes"] or digest.hexdigest() != entry["sha256"]
                        or opened.st_mtime_ns != closed.st_mtime_ns
                        or opened.st_ctime_ns != closed.st_ctime_ns
                        or _distribution_signature(source) != identities[name]):
                    raise ValueError("Package member changed during archive read")
        outgoing.flush()
        os.fsync(outgoing.fileno())
    # Retain one identity and byte digest for the same handle that is decoded.
    partial_identity = _distribution_signature(partial)
    zip_size = partial_identity[2]
    with partial.open("rb") as decoded:
        opened = os.fstat(decoded.fileno())
        opened_identity = (opened.st_dev, opened.st_ino, opened.st_size,
                           opened.st_mtime_ns, opened.st_ctime_ns)
        if opened_identity[:3] != partial_identity[:3]:
            raise ValueError("ZIP identity changed before decoding")

        def require_unchanged_partial():
            current = os.fstat(decoded.fileno())
            identity = (current.st_dev, current.st_ino, current.st_size,
                        current.st_mtime_ns, current.st_ctime_ns)
            if identity != opened_identity or _distribution_signature(partial) != partial_identity:
                raise ValueError("ZIP changed before publication")

        def decoded_digest():
            decoded.seek(0)
            digest, count = hashlib.sha256(), 0
            while block := decoded.read(65536):
                count += len(block)
                if count > zip_size:
                    raise ValueError("ZIP exceeds its admitted size")
                digest.update(block)
            if count != zip_size:
                raise ValueError("ZIP differs from its admitted size")
            require_unchanged_partial()
            return digest.hexdigest()

        zip_sha = decoded_digest()
        # Decode the actual emitted ZIP, not a second description of intended bytes.
        with zipfile.ZipFile(decoded, "r") as archive:
            wanted = {f"{PACKAGE_NAME}/{name}": entry for name, entry in entries.items()}
            manifest_name = f"{PACKAGE_NAME}/DISTRIBUTION-MANIFEST.json"
            if (len(archive.namelist()) != len(wanted) + 1
                    or set(archive.namelist()) != set(wanted) | {manifest_name}
                    or archive.getinfo(manifest_name).file_size != len(raw)
                    or archive.read(manifest_name) != raw):
                raise ValueError("Emitted ZIP membership or manifest differs")
            for name, entry in wanted.items():
                if archive.getinfo(name).file_size != entry["size_bytes"]:
                    raise ValueError("Emitted ZIP member size differs")
                digest, count = hashlib.sha256(), 0
                with archive.open(name) as member:
                    while block := member.read(65536):
                        count += len(block)
                        if count > entry["size_bytes"]:
                            raise ValueError("Emitted ZIP member exceeds manifest")
                        digest.update(block)
                if count != entry["size_bytes"] or digest.hexdigest() != entry["sha256"]:
                    raise ValueError("Emitted ZIP member differs from manifest")
        require_unchanged_partial()
        final_raw, _, _, final_identities = _distribution_manifest()
        if final_raw != raw or final_identities != identities:
            raise ValueError("Package changed before archive publication")
        require_unchanged_partial()
        if decoded_digest() != zip_sha:
            raise ValueError("Decoded ZIP bytes changed before publication")
        validate_destination()
        require_unchanged_partial()
        os.link(partial, ZIP_PATH)  # CreateNew; retain the decoded partial witness.
        reject_link_traversal(ZIP_PATH)
        published, retained = ZIP_PATH.stat(), partial.stat()
        current = os.fstat(decoded.fileno())
        for state in (published, retained, current):
            if ((state.st_dev, state.st_ino, state.st_size) != opened_identity[:3]
                    or state.st_mtime_ns != opened.st_mtime_ns):
                raise ValueError("Published ZIP identity differs from decoded bytes")
    print(f"  -> Created {ZIP_PATH.name} ({zip_size:,} bytes, SHA-256: {zip_sha})")
    return zip_sha, zip_size


def verify_distribution_integrity():
    print("[5/6] Verifying distribution package integrity...")
    validate_destination()
    _, data, entries, _ = _distribution_manifest()
    data["verification_status"] = "PACKAGE_INTEGRITY_VERIFIED"
    data["software_build_status"] = "NOT_RUN"
    data["runtime_validation_status"] = "NOT_RUN"
    manifest_file = TARGET_DIR / "DISTRIBUTION-MANIFEST.json"
    manifest_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  -> Verified {len(entries)} packaged files against distribution manifest: 100% MATCH.")

def main(argv=None):
    global TARGET_DIR, ZIP_PATH, FRONTEND_DIST, FRONTEND_INPUTS, PREPARED_RUNTIME_MANIFEST
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        help="New staging directory inside this workspace's dist; sibling .zip must also be absent")
    parser.add_argument("--frontend-dist", type=Path,
                        help="Fresh, dedicated frontend build directory inside this workspace's dist")
    parser.add_argument("--frontend-inputs", type=Path,
                        help="Frontend input record written by --capture-frontend-inputs before that build")
    parser.add_argument("--capture-frontend-inputs", type=Path, metavar="NEW_RECORD",
                        help="Write the current frontend source hash record to a new file and exit")
    parser.add_argument("--prepared-runtime-manifest", type=Path,
                        help="Explicit local prepared-runtime.json byte-admission input; "
                             "native profile unresolved, so full package/launch remains refused")
    parser.add_argument("--verify-package", type=Path, metavar="ABSROOT",
                        help="Read-only verification of an extracted package; no build prerequisites")
    parser.add_argument("--expected-manifest-sha256", metavar="HEX",
                        help="Required trusted SHA-256 of the exact distribution manifest bytes")
    args = parser.parse_args(argv)
    if args.verify_package is not None or args.expected_manifest_sha256 is not None:
        if (args.verify_package is None or not args.verify_package.is_absolute()
                or not re.fullmatch(r"[a-f0-9]{64}", args.expected_manifest_sha256 or "")
                or any(value is not None for value in
                       (args.out, args.frontend_dist, args.frontend_inputs,
                        args.capture_frontend_inputs, args.prepared_runtime_manifest))):
            print("[VERIFY ERROR] Absolute package root and trusted manifest digest required; no build options",
                  file=sys.stderr)
            return 1
        TARGET_DIR = args.verify_package
        try:
            raw, _, entries, _ = _distribution_manifest()
            if hashlib.sha256(raw).hexdigest() != args.expected_manifest_sha256:
                raise ValueError("Package manifest digest mismatch")
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            print(f"[VERIFY ERROR] {type(exc).__name__}", file=sys.stderr)
            return 1
        print(f"PACKAGE_INTEGRITY_VERIFIED_READ_ONLY={len(entries)}")
        return 0
    def absolute(path):
        return path if path.is_absolute() else ROOT / path
    if args.capture_frontend_inputs is not None:
        try:
            capture_frontend_inputs(absolute(args.capture_frontend_inputs))
            print(f"Frontend inputs recorded: {args.capture_frontend_inputs}")
            return 0
        except Exception as exc:  # noqa: BLE001 - CLI boundary: any capture failure is reported as [BUILD ERROR] + exit 1
            print(f"\n[BUILD ERROR] {exc}", file=sys.stderr)
            return 1
    if args.out is None or args.frontend_dist is None:
        print("\n[BUILD ERROR] --out and --frontend-dist (with --frontend-inputs) are required",
              file=sys.stderr)
        return 1
    TARGET_DIR = absolute(args.out)
    ZIP_PATH = Path(str(TARGET_DIR) + ".zip")
    FRONTEND_DIST = absolute(args.frontend_dist)
    PREPARED_RUNTIME_MANIFEST = (absolute(args.prepared_runtime_manifest)
                                 if args.prepared_runtime_manifest is not None else None)
    FRONTEND_INPUTS = absolute(args.frontend_inputs) if args.frontend_inputs is not None else None
    print("========================================================")
    print(f"  Building {PACKAGE_NAME}")
    print("========================================================")
    try:
        validate_destination(new_staging=True)
        if git_identity()["status"] != "OBSERVED":
            raise RuntimeError("Git HEAD and dirty state unavailable; cannot bind package provenance")
        check_prerequisites()
        copy_application_files()
        write_launcher_scripts()
        generate_manifest()
        verify_distribution_integrity()
        zip_sha, _zip_size = create_zip_archive()
        print("\nDistribution package build completed successfully.")
        print(f"Output directory: {TARGET_DIR}")
        print(f"Output archive:   {ZIP_PATH}")
        print(f"Archive SHA-256:  {zip_sha}")
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary: any build failure is reported as [BUILD ERROR] + exit 1
        print(f"\n[BUILD ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
