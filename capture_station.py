"""Explicit, offline phone + webcam capture station for KineLab PT.

No device is opened, recording started, or capture files changed at import.
Participant recording remains blocked pending an independently approved protocol.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import subprocess
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

from local_diagnostics import log_local_failure
from session_contract import ROLES as RAW_ROLES
from take_acceptance import acceptance_lease, checked_path, file_proof, require_no_pending, require_same

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
DEFAULT_PROJECT = ROOT / "projects" / "capture-20261026-trial01"
WEBCAM_ROLES = ("cam02_intrinsics", "cam02_board", "cam02_trial")
ROLE_GUIDE = {
    "cam01_intrinsics": "PHONE | 25-40 sec | move checkerboard around frame and tilt gently",
    "cam02_intrinsics": "WEBCAM | 25-40 sec | move checkerboard around frame and tilt gently",
    "cam01_board": "PHONE | stationary board on floor visible from first frame",
    "cam02_board": "WEBCAM | same stationary board on floor visible from first frame",
    "cam01_trial": "PHONE | full-body squat, start and end visible sync cue",
    "cam02_trial": "WEBCAM | same squat with overlapping recording and same cues",
}
RECOMMENDED_SECONDS = {"cam02_intrinsics": 35, "cam02_board": 12, "cam02_trial": 60}
PARTICIPANT_RECORDING_BLOCKED = (
    "PARTICIPANT_RECORDING_BLOCKED: recording requires an independently approved "
    "privacy, consent, physical-validation and clinical-use protocol."
)
# Only new trial intake is refused; reading and recovering earlier trial takes stays role-agnostic.
PARTICIPANT_TRIAL_ROLES = ("cam01_trial", "cam02_trial")


def clip_path(project: Path, role: str) -> Path:
    if role not in RAW_ROLES:
        raise ValueError("Unknown capture role; never pass an arbitrary filename")
    return Path(project).resolve() / "raw" / (role + ".mp4")


def prepare_recording(project: Path, role: str, seconds: int) -> tuple[Path, Path]:
    if role not in WEBCAM_ROLES:
        raise ValueError("Only webcam cam02_* roles may be recorded by this device")
    if type(seconds) is not int or not 3 <= seconds <= 180:
        raise ValueError("Recording duration must be an integer from 3 to 180 seconds")
    raise ValueError(PARTICIPANT_RECORDING_BLOCKED)


def ffmpeg_command(temp: Path, seconds: int, device: str = "Integrated Webcam") -> list[str]:
    if type(seconds) is not int or not 3 <= seconds <= 180:
        raise ValueError("Invalid duration")
    if not isinstance(device, str) or not device.strip() or any(c in device for c in "\r\n"):
        raise ValueError("Invalid video device")
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-n",
        "-f", "dshow", "-rtbufsize", "256M",
        "-framerate", "30", "-video_size", "1280x720",
        "-pixel_format", "yuyv422", "-i", f"video={device}",
        "-t", str(seconds), "-map", "0:v:0", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-f", "mp4", str(Path(temp)),
    ]


def probe_clip(path: Path) -> dict:
    """Metadata only; doesn't store camera frames or expose videos over a network."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", timeout=25, check=True,
        )
        data = json.loads(result.stdout)
        stream = next(s for s in data["streams"] if s.get("codec_type") == "video")
        rotation = int(stream.get("tags", {}).get("rotate", 0))
        for side in stream.get("side_data_list", []):
            if "rotation" in side:
                rotation = int(side["rotation"])
        duration = float(stream.get("duration") or data["format"].get("duration", 0))
        fps = str(stream.get("avg_frame_rate", "0/1"))
        if min(int(stream["width"]), int(stream["height"])) < 2 or duration <= 0 or not math.isfinite(duration):
            raise ValueError("Invalid geometry/duration")
        if Fraction(fps) <= 0:
            raise ValueError("Invalid frame rate")
        return {
            "width": int(stream["width"]), "height": int(stream["height"]),
            "rotation": rotation, "fps": fps, "duration": duration,
            "frame_count": int(stream.get("nb_frames") or 0),
        }
    except (OSError, ValueError, ZeroDivisionError, KeyError, StopIteration, IndexError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        log_local_failure(logger, logging.WARNING, "capture_probe_failed", error)
        raise ValueError("VIDEO_INVALID: video probe failed; original preserved") from None


def finalize_recording(project: Path, role: str) -> Path:
    """Only publish a readable temporary webcam recording; never overwrite.

    Participant trial roles are refused before any lease, probe or rename.
    """
    if role in PARTICIPANT_TRIAL_ROLES:
        raise ValueError(PARTICIPANT_RECORDING_BLOCKED)
    with acceptance_lease(project):
        require_no_pending(project)
        _require_unregistered(project)
        return _finalize_recording_locked(project, role)


def _require_unregistered(project: Path) -> None:
    if checked_path(Path(project) / "session.json").exists():
        raise ValueError("SESSION_LOCKED: registered media cannot be replaced")


def _finalize_recording_locked(project: Path, role: str) -> Path:
    if role in PARTICIPANT_TRIAL_ROLES:
        raise ValueError(PARTICIPANT_RECORDING_BLOCKED)
    destination = clip_path(project, role)
    checked_path(destination)
    partial = destination.with_name(destination.stem + ".part.mp4")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")
    if not partial.is_file():
        raise FileNotFoundError(f"Missing temporary capture {partial}")
    proof = file_proof(partial)
    info = probe_clip(partial)
    require_same(partial, proof)
    if (info["width"], info["height"], info["rotation"]) != (1280, 720, 0) or info["duration"] < .5:
        raise ValueError("Unexpected webcam output geometry or too-short recording; partial preserved")
    partial.rename(destination)
    return destination


def import_phone_mp4(project: Path, role: str, source: Path) -> Path:
    """Copy an already-exported MP4 byte-for-byte and publish without overwrite.

    Never transcode, rename a MOV extension to MP4, or change the original.
    Participant trial footage is refused before any lease, staging or copy.
    """
    if role == "cam01_trial":
        raise ValueError(PARTICIPANT_RECORDING_BLOCKED)
    with acceptance_lease(project):
        require_no_pending(project)
        _require_unregistered(project)
        return _import_phone_mp4_locked(project, role, source)


def _import_phone_mp4_locked(project: Path, role: str, source: Path) -> Path:
    if role == "cam01_trial":
        raise ValueError(PARTICIPANT_RECORDING_BLOCKED)
    if role not in ("cam01_intrinsics", "cam01_board", "cam01_trial"):
        raise ValueError("Only cam01 phone clips can be imported via this action")
    source = checked_path(source)
    if source.suffix.lower() != ".mp4" or not source.is_file():
        raise ValueError("Select a real MP4 video (not MOV renamed as MP4)")
    destination = clip_path(project, role)
    checked_path(destination)
    staging = destination.with_name(destination.stem + ".copying.mp4")
    checked_path(staging)
    if source == destination or source == staging or destination.exists() or staging.exists():
        raise FileExistsError("Destination or temporary import exists; preserving originals")
    if source.stat().st_size == 0:
        raise ValueError("Phone file is empty")
    import os
    import shutil

    from session_contract import sha256_file
    proof = file_proof(source)
    try:
        with source.open("rb") as src, staging.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if source.stat().st_size != staging.stat().st_size or sha256_file(source) != sha256_file(staging):
            raise ValueError("Imported footage differs from source; refused")
        probe_clip(staging)
        require_same(source, proof)
        if file_proof(staging).sha256 != proof.sha256:
            raise ValueError("INPUT_CHANGED: imported footage changed during inspection")
        # Same NTFS filesystem: hard-link creation refuses an already-existing target.
        os.link(staging, destination)
        return destination
    finally:
        staging.unlink(missing_ok=True)


def save_board_measurement(project: Path, measured_square_mm: float | None, operator: str) -> dict:
    """Record a human-reported physical measurement, not a made-up calibration result."""
    if (measured_square_mm is None or type(measured_square_mm) not in (int, float)
            or not math.isfinite(measured_square_mm) or measured_square_mm <= 0):
        raise ValueError("Measure a printed square with a physical ruler, then enter mm")
    if not isinstance(operator, str) or not operator.strip():
        raise ValueError("Name/initials of measurement operator required")
    project = Path(project).resolve()
    output = project / "board-measurement.json"
    if output.exists():
        raise FileExistsError(f"Measurement already recorded; never silently overwrite {output}")
    result = {
        "schema": "kinelab.board-operator-measurement.v1",
        "expected_square_mm": 20.0,
        "measured_square_mm": float(measured_square_mm),
        "board_squares": [8, 10],
        "inner_corners": [7, 9],
        "measured_by": operator.strip(),
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "source": "operator_measured_not_independently_verified",
        "note": "Self-reported physical ruler measurement only; not a pose/3D accuracy certificate.",
    }
    with output.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return result


def check_readiness(project: Path, *, inspect_existing: bool = True) -> dict:
    try:
        with acceptance_lease(project):
            require_no_pending(project)
            return _check_readiness_locked(project, inspect_existing=inspect_existing)
    except (OSError, ValueError) as error:
        return {"session": str(project), "clips": {}, "missing": [], "board_measurement": None,
                "issues": [str(error)], "ready_to_register": False, "notes": []}


def _check_readiness_locked(project: Path, *, inspect_existing: bool = True) -> dict:
    """Readiness snapshot for fixed callers already holding the shared lease."""
    require_no_pending(project)
    project = Path(project).resolve()
    issues: list[str] = []
    missing: list[str] = []
    clips = {}
    camera_geometries: dict[str, object] = {}
    if not (project / "Config.toml").is_file():
        issues.append("Session configuration missing")
    for role in RAW_ROLES:
        path = clip_path(project, role)
        if not path.is_file():
            missing.append(role)
            continue
        if path.stat().st_size == 0:
            issues.append(role + ": file is empty")
            continue
        if not inspect_existing:
            clips[role] = {"exists": True}
            continue
        try:
            meta = probe_clip(path)
        except ValueError as error:
            issues.append(str(error))
            continue
        clips[role] = meta
        cam = role[:5]
        geom = (meta["width"], meta["height"], meta["rotation"])
        if cam in camera_geometries and camera_geometries[cam] != geom:
            issues.append(f"{cam} video geometry/orientation inconsistent across intrinsics, board and trial")
        camera_geometries[cam] = geom
        if meta["duration"] < (10 if role.endswith(("intrinsics", "trial")) else 2):
            issues.append(f"{role}: too short for recommended calibration/analysis ({meta['duration']:.1f}s)")
    board_file = project / "board-measurement.json"
    board = None
    if board_file.is_file():
        try:
            board = json.loads(board_file.read_text(encoding="utf-8"))
            value = board.get("measured_square_mm")
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not 19.6 <= value <= 20.4 or board.get("source") != "operator_measured_not_independently_verified"):
                issues.append("Measured checkerboard square differs from 20mm by >0.4mm or record invalid; reprint and measure")
        except (OSError, ValueError, TypeError, AttributeError):
            issues.append("Invalid physical board measurement file")
    else:
        if not missing:
            issues.append("Measure printed checkerboard squares with ruler and record board-measurement.json")
    return {
        "session": str(project), "clips": clips, "missing": missing,
        "board_measurement": board,
        "issues": issues,
        "ready_to_register": bool(not missing and not issues and inspect_existing),
        "notes": [
            "Checking files does not prove board view diversity, camera calibration, synchronous capture or physical accuracy.",
            "Registration and processing remain separate user-directed steps.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="KineLab PT zero-cost local capture helper")
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("check", help="Inspect raw clips; never registers or modifies inputs")
    b = subs.add_parser("measure-board", help="Record an operator-measured printed board square")
    b.add_argument("--mm", required=True, type=float)
    b.add_argument("--operator", required=True)
    record = subs.add_parser("record", help="Begin consented timed webcam recording")
    record.add_argument("role", choices=WEBCAM_ROLES)
    record.add_argument("--seconds", type=int, default=None)
    record.add_argument("--device", default="Integrated Webcam")
    record.add_argument("--confirm", action="store_true", help="I am present and agree to start camera recording now")
    args = parser.parse_args()
    if args.action == "check":
        report = check_readiness(args.project)
        print(json.dumps(report, indent=2))
        return 0 if report["ready_to_register"] else 2
    if args.action == "measure-board":
        print(json.dumps(save_board_measurement(args.project, args.mm, args.operator), indent=2))
        return 0
    seconds = args.seconds if args.seconds is not None else RECOMMENDED_SECONDS[args.role]
    dest, partial = prepare_recording(args.project, args.role, seconds)
    if not args.confirm:
        response = input(f"About to record LIVE WEB CAMERA for {seconds}s to {dest.name}. Continue? [yes/NO] ").strip().lower()
        if response != "yes":
            print("Recording not started.")
            return 3
    print(f"RECORDING_CONSENT={args.role}; ends automatically after {seconds}s", flush=True)
    subprocess.run(ffmpeg_command(partial, seconds, args.device), check=True)
    print(f"RECORDED={finalize_recording(args.project, args.role)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
