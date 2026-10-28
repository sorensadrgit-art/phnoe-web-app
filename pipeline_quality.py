"""Measured local calibration, synchronization and two-view reconstruction gates."""
import json
import math
import re
from pathlib import Path
import tempfile
import tomllib

from session_contract import sha256_file


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _save(project, name, report):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=project, suffix=".json", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(report, stream, indent=2, allow_nan=False)
    try:
        temporary.replace(Path(project) / name)
    finally:
        temporary.unlink(missing_ok=True)
    return report


def _calibration_file(project):
    paths = list((project / "calibration").glob("*.toml"))
    if len(paths) != 1:
        raise ValueError("CALIBRATION_INVALID: require exactly one calibration TOML in this session")
    return paths[0]


def validate_calibration(project: Path, session: dict) -> dict:
    project = Path(project)
    report = {"schema": "kinelab.calibration-quality.v1", "session_id": session["session_id"], "ok": False, "errors": []}
    try:
        path = _calibration_file(project)
        calibration = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        names = [key for key in calibration if key not in ("metadata", "capture_volume", "charuco", "checkerboard")]
        if set(names) != set(session["camera_ids"]):
            raise ValueError("CALIBRATION_INVALID: expected exactly cam01/cam02")
        positions = []
        for name in session["camera_ids"]:
            camera = calibration[name]
            if camera.get("name", name) != name or camera.get("size") != [1280, 720]:
                raise ValueError("CALIBRATION_INVALID: camera name or normalized image size mismatch")
            matrix = camera.get("matrix", [])
            if len(matrix) != 3 or any(not isinstance(row, list) or len(row) != 3 or not all(_finite(v) for v in row) for row in matrix):
                raise ValueError("CALIBRATION_INVALID: finite 3x3 matrix required")
            if matrix[0][0] <= 0 or matrix[1][1] <= 0 or matrix[2] != [0, 0, 1]:
                raise ValueError("CALIBRATION_INVALID: invalid intrinsic matrix")
            for key, count in (("rotation", 3), ("translation", 3)):
                if len(camera.get(key, [])) != count or not all(_finite(v) for v in camera[key]):
                    raise ValueError("CALIBRATION_INVALID: invalid " + key)
            if len(camera.get("distortions", [])) < 4 or not all(_finite(v) for v in camera["distortions"]):
                raise ValueError("CALIBRATION_INVALID: invalid distortion vector")
            import cv2
            import numpy as np
            rotation, _ = cv2.Rodrigues(np.asarray(camera["rotation"], dtype=float))
            positions.append(-rotation.T @ np.asarray(camera["translation"], dtype=float))
        if float(np.linalg.norm(positions[0] - positions[1])) <= 1e-9:
            raise ValueError("CALIBRATION_INVALID: coincident camera centers")
        log = (project / "logs.txt").read_text(encoding="utf-8", errors="replace") if (project / "logs.txt").is_file() else ""
        matches = re.findall(r"Residual \(RMS\) calibration errors.*?respectively\s*(\[[^\]]+\])\s*px", log, re.S)
        if not matches:
            raise ValueError("CALIBRATION_INVALID: measured RMS residuals unavailable; metadata.error is a Pose2Sim placeholder")
        numbers = re.sub(r"np\.float(?:32|64)\(([^)]+)\)", r"\1", matches[-1])
        rms = json.loads(numbers)
        if not isinstance(rms, list) or len(rms) != 2 or not all(_finite(v) and 0 <= v <= 2 for v in rms):
            raise ValueError("CALIBRATION_INVALID: fitted RMS must be finite and <=2 px per camera")
        report.update(ok=True, calibration={"path": path.relative_to(project).as_posix(), "sha256": sha256_file(path)},
                      rms_px=dict(zip(names, rms)), residual_source="Pose2Sim calibration log, not metadata.error", physical_scale="unverified until the printed board is measured")
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
    return _save(project, "calibration-quality.json", report)


def validate_sync(project: Path, session: dict, cue_observations: dict) -> dict:
    project = Path(project)
    report = {"schema": "kinelab.sync.v1", "session_id": session["session_id"], "ok": False, "errors": []}
    try:
        data = cue_observations
        if not isinstance(data, dict) or data.get("session_id") != session["session_id"] or data.get("reference") not in ("cam01", "cam02") or data.get("fps") != 30:
            raise ValueError("SYNC_UNCERTAIN: require this session, native camera reference and 30 fps")
        cameras = data["cameras"]
        if not isinstance(cameras, dict) or set(cameras) != {"cam01", "cam02"}:
            raise ValueError("SYNC_UNCERTAIN: both camera observations required")
        for name, camera in cameras.items():
            if not isinstance(camera, dict) or type(camera.get("offset_frames")) is not int or (name == data["reference"] and camera["offset_frames"] != 0):
                raise ValueError("SYNC_UNCERTAIN: invalid offset sign/reference")
            start, end = camera.get("start_residual_frames"), camera.get("end_residual_frames")
            if not all(_finite(v) and abs(v) <= 1 for v in (start, end)) or abs(end - start) > 1:
                raise ValueError("SYNC_UNCERTAIN: independent cue residual/drift exceeds one frame")
        pairs = data.get("source_frame_pairs", [])
        if not isinstance(pairs, list) or not pairs:
            raise ValueError("SYNC_UNCERTAIN: independent source/synchronized frame pairs required")
        measured = {name: [] for name in cameras}
        for pair in pairs:
            if not isinstance(pair, dict) or pair.get("camera") not in cameras:
                raise ValueError("SYNC_UNCERTAIN: invalid camera observation")
            camera = cameras[pair["camera"]]
            source, synchronized = pair["source_frame_index"], pair["synchronized_frame_index"]
            if not all(type(v) is int and v >= 0 for v in (source, synchronized)) or abs(source - synchronized - camera["offset_frames"]) > 1:
                raise ValueError("SYNC_UNCERTAIN: source = synchronized + offset sign mismatch")
            measured[pair["camera"]].append((synchronized, source, source - synchronized - camera["offset_frames"]))
        for name, observations in measured.items():
            observations.sort()
            if len(observations) < 2 or any(right[0] <= left[0] or right[1] <= left[1] for left, right in zip(observations, observations[1:])):
                raise ValueError("SYNC_UNCERTAIN: distinct ordered start/end frame pairs required for each camera")
            start, end = observations[0][2], observations[-1][2]
            if abs(end - start) > 1 or start != cameras[name]["start_residual_frames"] or end != cameras[name]["end_residual_frames"]:
                raise ValueError("SYNC_UNCERTAIN: declared residuals disagree with observed cues or measured drift exceeds one frame")
        if session.get("captures"):
            if data.get("inputs") != {role: item["sha256"] for role, item in session["captures"].items()}:
                raise ValueError("SYNC_UNCERTAIN: cue observations are not bound to these recordings")
        log = (project / "logs.txt").read_text(encoding="utf-8", errors="replace")
        matches = re.findall(r"Camera (cam0[12]) and (cam0[12]):\s*(-?\d+) frames offset[^\n]*correlation\s+([-\d.]+)", log)
        if not matches:
            raise ValueError("SYNC_UNCERTAIN: native Pose2Sim offset/correlation evidence missing")
        reference, other, offset, correlation = matches[-1]
        if reference != data["reference"] or reference == other or int(offset) != cameras[other]["offset_frames"] or not 0.5 < float(correlation.rstrip(".")) <= 1:
            raise ValueError("SYNC_UNCERTAIN: independent cues disagree with native alignment or correlation is ambiguous")
        report.update(ok=True, reference=reference, cameras=cameras, source_frame_pairs=pairs,
                      convention="source_frame_index = synchronized_frame_index + offset_frames", native_correlation=float(correlation.rstrip(".")))
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
    return _save(project, "sync.json", report)


def assess_reconstruction(samples: list, required_markers: list) -> dict:
    errors, markers = [], {}
    if not samples or not required_markers:
        return {"ok": False, "errors": ["RECONSTRUCTION_REJECTED: no observed samples/required markers"], "markers": {}}
    frames = sorted({row["frame"] for row in samples if type(row.get("frame")) is int and row["frame"] >= 0})
    for name in required_markers:
        rows = {row["frame"]: row for row in samples if row.get("marker") == name}
        observed, residuals, gap, longest = 0, [], 0, 0
        for frame in frames:
            row = rows.get(frame, {})
            residual = row.get("reprojection_px")
            likelihoods = row.get("likelihoods", [])
            valid = (row.get("views") == 2 and len(likelihoods) == 2 and all(_finite(v) and 0.3 <= v <= 1 for v in likelihoods)
                     and _finite(residual) and 0 <= residual <= 15 and row.get("interpolated") is False)
            if valid:
                observed += 1; residuals.append(residual); gap = 0
            else:
                gap += 1; longest = max(longest, gap)
        coverage = observed / len(frames) if frames else 0
        p95 = sorted(residuals)[max(0, math.ceil(len(residuals) * .95) - 1)] if residuals else None
        markers[name] = {"observed": observed, "total": len(frames), "coverage": coverage, "p95_reprojection_px": p95, "longest_gap_frames": longest}
        if coverage < .95 or longest > 3:
            errors.append("RECONSTRUCTION_REJECTED: insufficient two-view support for " + name)
    return {"ok": not errors, "errors": errors, "markers": markers}


def validate_reconstruction(project: Path, session: dict) -> dict:
    project = Path(project)
    report = {"schema": "kinelab.quality.v1", "session_id": session["session_id"], "ok": False, "errors": []}
    try:
        import numpy as np
        import cv2
        from anytree import RenderTree
        from Pose2Sim.skeletons import HALPE_26
        from export_motion import parse_trc
        config = tomllib.loads((project / "Config.toml").read_text(encoding="utf-8-sig"))
        if config.get("pose", {}).get("pose_model") != "Body_with_feet":
            raise ValueError("RECONSTRUCTION_REJECTED: first pilot supports configured Body_with_feet only")
        run = json.loads((project / "run.json").read_text(encoding="utf-8"))
        if run.get("native_triangulation_policy") != {"interpolation": "none", "fill_large_gaps_with": "nan"}:
            raise ValueError("RECONSTRUCTION_REJECTED: unfiltered no-gap-fill provenance required")
        paths = [path for path in (project / "pose-3d").glob("*.trc") if "filt" not in path.name and "LSTM" not in path.name]
        if len(paths) != 1:
            raise ValueError("RECONSTRUCTION_REJECTED: exactly one current unfiltered TRC required")
        names, frames, fps = parse_trc(paths[0])
        ids = {node.name: node.id for _, _, node in RenderTree(HALPE_26) if node.id is not None}
        required = ["Hip", "RHip", "RKnee", "RAnkle", "LHip", "LKnee", "LAnkle"]
        if any(name not in names or name not in ids for name in required):
            raise ValueError("RECONSTRUCTION_REJECTED: required lower-limb landmarks absent")
        calibration = _calibration_file(project)
        cal = tomllib.loads(calibration.read_text(encoding="utf-8-sig"))
        camera_names = [name for name in cal if name in session["camera_ids"]]
        if set(camera_names) != {"cam01", "cam02"}:
            raise ValueError("RECONSTRUCTION_REJECTED: expected two calibrated cameras")
        projections = []
        for camera_name in camera_names:
            camera = cal[camera_name]
            rotation, _ = cv2.Rodrigues(np.asarray(camera["rotation"], dtype=float))
            extrinsics = np.column_stack((rotation, np.asarray(camera["translation"], dtype=float)))
            projections.append(np.asarray(camera["matrix"], dtype=float) @ extrinsics)
        files = {}
        for camera in camera_names:
            folder = project / "pose-associated" / (camera + "_json")
            files[camera] = {int(match.group(1)): path for path in folder.glob("*.json") if (match := re.search(r"(\d+)\.json$", path.name))}
        samples = []
        for frame in frames:
            index = round(frame["t"] * fps)
            poses = {}
            for camera in camera_names:
                path = files[camera].get(index)
                data = json.loads(path.read_text(encoding="utf-8")) if path else {}
                people = data.get("people", [])
                poses[camera] = people[0].get("pose_keypoints_2d", []) if len(people) == 1 else []
            for name in required:
                point = frame["xyz"][names.index(name)]
                likelihoods, errors = [], []
                for camera, projection in zip(camera_names, projections):
                    keypoint = poses[camera][ids[name] * 3:ids[name] * 3 + 3]
                    if point is None or len(keypoint) != 3 or not all(_finite(value) for value in keypoint):
                        continue
                    # Pose2Sim zup2yup permutes native (x,y,z) to (y,z,x).
                    projected = projection @ np.asarray([point[2], point[0], point[1], 1.0])
                    if not np.isfinite(projected).all() or abs(projected[2]) < 1e-12:
                        continue
                    likelihoods.append(keypoint[2]); errors.append(float(np.linalg.norm(projected[:2] / projected[2] - keypoint[:2])))
                samples.append({"marker": name, "frame": index, "views": len(likelihoods), "likelihoods": likelihoods,
                                "reprojection_px": max(errors) if errors else None, "interpolated": False})
        report.update(assess_reconstruction(samples, required))
        report.update(method="native unfiltered TRC reprojected into associated two-camera poses; no gap filling", source_trc=paths[0].name,
                      accepted_time_range_s=[frames[0]["t"], frames[-1]["t"]], physical_accuracy="not validated")
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        report["errors"].append(str(error))
    return _save(project, "quality.json", report)
