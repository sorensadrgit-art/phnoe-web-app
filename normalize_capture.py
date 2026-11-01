"""Validate six registered originals, then transactionally normalize local footage."""
import argparse
import json
import math
import subprocess
import tempfile
import time
import tomllib
from bisect import bisect_right
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

from session_contract import load_session, sha256_file, strict_json_loads, validate_session

ROOT = Path(__file__).resolve().parent / "projects/kinelab-dualcam"
ROLES = {
    "cam01_intrinsics": "calibration/intrinsics/cam01/intrinsics.mp4",
    "cam02_intrinsics": "calibration/intrinsics/cam02/intrinsics.mp4",
    "cam01_board": "calibration/extrinsics/cam01.mp4",
    "cam02_board": "calibration/extrinsics/cam02.mp4",
    "cam01_trial": "videos/cam01.mp4", "cam02_trial": "videos/cam02.mp4",
}


_PROBE_STDOUT_LIMIT = 64 * 1024 * 1024
_PROBE_STDERR_LIMIT = 64 * 1024
_PROBE_TIMEOUT_S = 120


def _probe_output(command):
    """Bound decoder wall time and both pipes before parsing any output."""
    def limited(stream, cap):
        data = stream.read(cap + 1)
        if len(data) > cap:
            raise ValueError("VIDEO_TIMING_INVALID: decoder output limit exceeded")
        return data

    deadline = time.monotonic() + _PROBE_TIMEOUT_S
    with (subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False) as process,
          ThreadPoolExecutor(max_workers=2) as pool):
        readers = [pool.submit(limited, process.stdout, _PROBE_STDOUT_LIMIT),
                   pool.submit(limited, process.stderr, _PROBE_STDERR_LIMIT)]
        try:
            done, pending = wait(readers, timeout=_PROBE_TIMEOUT_S, return_when=FIRST_EXCEPTION)
            for future in done:
                future.result()
            if pending:
                raise ValueError("VIDEO_TIMING_INVALID: decoder timed out")
            code = process.wait(timeout=max(.001, deadline - time.monotonic()))
            stdout, stderr = (future.result() for future in readers)
            if code != 0 or stderr.strip():
                raise ValueError("VIDEO_TIMING_INVALID: decoder failed or reported an error")
            return stdout.decode("utf-8")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def inspect_video(path: Path) -> dict:
    command = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_frames", "-show_format", "-of", "json", str(path)]
    try:
        data = strict_json_loads(_probe_output(command))
        stream = data["streams"][0]
        timestamps = [float(frame.get("best_effort_timestamp_time", frame.get("pts_time"))) for frame in data["frames"] if frame.get("media_type") == "video"]
        ticks = [int(frame.get("best_effort_timestamp", frame.get("pts"))) for frame in data["frames"] if frame.get("media_type") == "video"]
        rotation = int(stream.get("tags", {}).get("rotate", 0))
        for side in stream.get("side_data_list", []):
            if "rotation" in side:
                rotation = int(side["rotation"])
        duration = float(stream.get("duration", data.get("format", {}).get("duration", 0)))
        return {"width": int(stream["width"]), "height": int(stream["height"]), "rotation": rotation,
                "fps": stream.get("avg_frame_rate", "0/1"), "avg_frame_rate": stream.get("avg_frame_rate", "0/1"),
                "time_base": stream.get("time_base"), "timestamp_ticks": ticks, "timestamps": timestamps, "frame_count": len(timestamps), "duration": duration}
    except FileNotFoundError as error:
        raise ValueError("INPUT_MISSING: FFprobe is required on PATH") from error
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        raise ValueError("VIDEO_TIMING_INVALID: cannot decode timing/geometry for " + str(path)) from error


def probe(path):
    return inspect_video(path)


def _timing(meta, role):
    timestamps = meta.get("timestamps", [])
    if (not timestamps or any(type(value) not in (int, float) or not math.isfinite(value) for value in timestamps)
            or any(b <= a for a, b in pairwise(timestamps))
            or not math.isfinite(meta.get("duration", 0)) or meta.get("duration", 0) <= 0):
        raise ValueError("VIDEO_TIMING_INVALID: finite increasing decoded PTS required for " + role)
    if meta.get("frame_count") != len(timestamps):
        raise ValueError("VIDEO_TIMING_INVALID: decoded frame count mismatch for " + role)
    try:
        if Fraction(meta.get("fps", "0/1")) <= 0:
            raise ValueError("nonpositive FPS")
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError("VIDEO_TIMING_INVALID: invalid rational frame rate for " + role) from error


def validate_sources(session: dict, project: Path) -> dict:
    project = Path(project).resolve()
    validate_session(session, project)
    if not (project / "Config.toml").is_file():
        raise ValueError("INPUT_MISSING: Config.toml")
    details: dict[str, dict] = {}
    geometries: dict[str, object] = {}
    for role in ROLES:
        meta = inspect_video(project / session["captures"][role]["path"])
        _timing(meta, role)
        if type(meta.get("width")) is not int or type(meta.get("height")) is not int or min(meta["width"], meta["height"]) < 2 or meta.get("rotation") not in (0, 90, -90, 180, -180, 270):
            raise ValueError("VIDEO_GEOMETRY_INVALID: unsupported dimensions/rotation for " + role)
        camera = role[:5]
        geometry = (meta["width"], meta["height"], meta["rotation"])
        if camera in geometries and geometries[camera] != geometry:
            raise ValueError("VIDEO_GEOMETRY_INVALID: calibration and trial geometry differ for " + camera)
        geometries[camera] = geometry
        details[role] = meta
    return details


def _transform(meta):
    width, height = meta["width"], meta["height"]
    rotation = meta["rotation"] % 360
    filters = []
    if rotation == 90:
        filters.append("transpose=2"); width, height = height, width
    elif rotation == 270:
        filters.append("transpose=1"); width, height = height, width
    elif rotation == 180:
        filters.extend(["hflip", "vflip"])
    scale = min(1280 / width, 720 / height)
    output_width, output_height = max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)
    padding = [(1280 - output_width) // 2, (720 - output_height) // 2]
    filters.extend(["setpts=PTS-STARTPTS", "fps=30:round=down", f"scale={output_width}:{output_height}", f"pad=1280:720:{padding[0]}:{padding[1]}", "setsar=1"])
    return {"rotation": meta["rotation"], "scaled_size": [output_width, output_height], "padding_xy": padding,
            "scale_xy": [output_width / width, output_height / height], "filter": ",".join(filters)}


def _convert(source, destination, meta):
    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-noautorotate", "-i", str(source),
               "-vf", _transform(meta)["filter"], "-r", "30", "-fps_mode", "cfr", "-an", "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", "-metadata:s:v:0", "rotate=0", str(destination)]
    try:
        subprocess.run(command, check=True, capture_output=True)
    except FileNotFoundError as error:
        raise ValueError("INPUT_MISSING: FFmpeg is required on PATH") from error
    except subprocess.CalledProcessError as error:
        raise ValueError("NORMALIZATION_FAILED: FFmpeg could not convert " + source.name) from error


def _validate_output(meta, role):
    _timing(meta, role)
    if (meta["width"], meta["height"]) != (1280, 720) or Fraction(meta["fps"]) != 30 or meta.get("rotation", 0) != 0:
        raise ValueError("VIDEO_GEOMETRY_INVALID: normalized output must be unrotated 1280x720 at 30/1")
    timestamps = meta["timestamps"]
    if abs(timestamps[0]) > .001 or any(abs(b - a - 1/30) > .001 for a, b in pairwise(timestamps)):
        raise ValueError("VIDEO_TIMING_INVALID: normalized output is not zero-origin CFR 30")


def _check_board(path, role, config):
    if not role.endswith(("intrinsics", "board")):
        return None
    import cv2
    calculate = config.get("calibration", {}).get("calculate", {})
    settings = calculate.get("intrinsics", {}) if role.endswith("intrinsics") else calculate.get("extrinsics", {}).get("board", {})
    key = "intrinsics_corners_nb" if role.endswith("intrinsics") else "extrinsics_corners_nb"
    corners = settings.get(key, [7, 9])
    if not isinstance(corners, list) or len(corners) != 2 or any(type(value) is not int or value < 2 for value in corners):
        raise ValueError("CALIBRATION_INVALID: invalid board dimensions in Config.toml")
    capture = cv2.VideoCapture(str(path))
    try:
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        samples = min(12, count) if role.endswith("intrinsics") else 1
        seen = 0
        for index in range(samples):
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(index * max(count - 1, 0) / max(samples - 1, 1)))
            ok, frame = capture.read()
            if ok:
                detected, _ = cv2.findChessboardCorners(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), tuple(corners))
                seen += bool(detected)
        if seen < (6 if role.endswith("intrinsics") else 1):
            raise ValueError("CALIBRATION_INVALID: board not detected in enough samples for " + role + "; extrinsics require the board in the first frame")
        return {"detected_samples": seen, "sample_count": samples, "corners": corners, "view_diversity": "not certified by corner detection"}
    finally:
        capture.release()


def _identity(session, project):
    return {"schema": "kinelab.preflight.v1", "session_id": session["session_id"], "config_sha256": sha256_file(project / "Config.toml"),
            "inputs": {role: entry["sha256"] for role, entry in session["captures"].items()}, "ok": True, "errors": []}


def _commit(project, staged):
    committed = []
    backups = {}
    try:
        for source, destination in staged:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup = source.parent / (source.name + ".previous")
                destination.replace(backup); backups[destination] = backup
            source.replace(destination); committed.append(destination)
    except BaseException:
        for destination in reversed(committed):
            destination.unlink(missing_ok=True)
        for destination, backup in backups.items():
            if backup.exists(): backup.replace(destination)
        raise


def normalize_session(session: dict, project: Path, overwrite: bool = False) -> dict:
    project = Path(project).resolve()
    sources = validate_sources(session, project)
    destinations = {role: project / relative for role, relative in ROLES.items()}
    originals = {(project / item["path"]).resolve() for item in session["captures"].values()}
    for destination in destinations.values():
        if destination.resolve() in originals:
            raise ValueError("OUTPUT_EXISTS: a normalized destination aliases an original capture")
        if destination.exists() and not overwrite:
            raise ValueError("OUTPUT_EXISTS: " + str(destination))
    config = tomllib.loads((project / "Config.toml").read_text(encoding="utf-8-sig"))
    report = _identity(session, project)
    normalization = {"schema": "kinelab.normalization.v1", "session_id": session["session_id"], "config_sha256": report["config_sha256"], "inputs": report["inputs"], "outputs": {}}
    with tempfile.TemporaryDirectory(prefix=".normalize-", dir=project) as directory:
        staging = Path(directory); staged = []
        for role, destination in destinations.items():
            source = project / session["captures"][role]["path"]
            temporary = staging / (role + ".mp4")
            _convert(source, temporary, sources[role])
            output = inspect_video(temporary); _validate_output(output, role)
            board = _check_board(temporary, role, config)
            ticks = sources[role]["timestamp_ticks"]
            time_base = Fraction(sources[role]["time_base"])
            bins = [int((tick - ticks[0]) * time_base * 30) for tick in ticks]
            mapping = [max(0, min(len(bins) - 1, bisect_right(bins, round(t * 30)) - 1)) for t in output["timestamps"]]
            normalization["outputs"][role] = {"path": ROLES[role], "sha256": sha256_file(temporary), "width": output["width"], "height": output["height"],
                "fps": output["fps"], "frame_count": output["frame_count"], "timestamps": output["timestamps"], "source": sources[role],
                "transform": _transform(sources[role]), "output_to_source_frame": mapping,
                "mapping_note": "FFmpeg fps=30:round=down; last source frame whose exact PTS rounds down to the output frame index", "board": board}
            staged.append((temporary, destination))
        validate_session(session, project)
        for name, data in (("normalization.json", normalization), ("preflight.json", report)):
            temporary = staging / name; temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
            staged.append((temporary, project / name))
        _commit(project, staged)
    return report


def check_normalized(session, project):
    project = Path(project).resolve(); validate_session(session, project)
    try:
        record = json.loads((project / "normalization.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("PREFLIGHT_INVALID: normalization.json missing or invalid") from error
    report = _identity(session, project)
    if any(record.get(key) != report[key] for key in ("session_id", "config_sha256", "inputs")):
        raise ValueError("INPUT_CHANGED: normalization belongs to different recordings/configuration")
    config = tomllib.loads((project / "Config.toml").read_text(encoding="utf-8-sig"))
    for role, relative in ROLES.items():
        path = project / relative
        if not path.is_file() or record.get("outputs", {}).get(role, {}).get("sha256") != sha256_file(path):
            raise ValueError("INPUT_CHANGED: normalized output missing/changed for " + role)
        _validate_output(inspect_video(path), role); _check_board(path, role, config)
    with tempfile.TemporaryDirectory(prefix=".preflight-", dir=project) as directory:
        temporary = Path(directory) / "preflight.json"; temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(project / "preflight.json")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--check-only", action="store_true", help="Verify normalized files; writes only the preflight report")
    for role in ROLES: parser.add_argument("--" + role.replace("_", "-"), type=Path)
    args = parser.parse_args(); project = args.project.resolve()
    try:
        session = load_session(project)
        for role in ROLES:
            explicit = getattr(args, role)
            if explicit is not None and explicit.resolve() != (project / session["captures"][role]["path"]).resolve():
                raise ValueError("INPUT_CHANGED: explicit source differs from registered " + role)
        report = check_normalized(session, project) if args.check_only else normalize_session(session, project, args.overwrite)
        print(json.dumps(report, indent=2)); print("CAPTURE_PREFLIGHT_PASS")
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
