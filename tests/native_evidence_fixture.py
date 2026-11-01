"""Generated TEST_ONLY contract fixtures, never native inference or physical proof.

The clips are reproducible codec inputs for the real decoded-provenance verifier.
The stored calibration/reconstruction outcomes are synthetic fixture contracts.
"""
import copy
import hashlib
import json
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

NATIVE_FRAME_POLICY = {
    "schema": "kinelab.native-frame-policy.v1",
    "raw": "all-decoded-trial-frames",
    "synchronization": "native-source-minus-offset-positive",
    "association": "derived-common-positive-range",
    "triangulation": "derived-common-positive-range",
    "frame_rate": 30,
}
NATIVE_STAGES = ("poseEstimation", "synchronization", "personAssociation")
STAGES = ("calibration", *NATIVE_STAGES, "triangulation", "filtering",
          "markerAugmentation", "kinematics")


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(root, relative, content):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@lru_cache(maxsize=8)
def _generated_clip(frame_count):
    """Bounded test-only byte reuse; no media from the workstation is read."""
    if type(frame_count) is not int or not 2 <= frame_count <= 10000:
        raise ValueError("TEST_ONLY fixture requires 2..10000 generated frames")
    with tempfile.TemporaryDirectory(prefix="kinelab-TEST_ONLY-codec-") as folder:
        path = Path(folder) / "TEST_ONLY-generated.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30",
            "-frames:v", str(frame_count), "-an", "-c:v", "mpeg4", "-q:v", "31",
            "-threads", "1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
            "-map_metadata", "-1", "-y", str(path),
        ], check=True, capture_output=True)
        return path.read_bytes()


def generated_normalization(root, identity, counts=None):
    """Create real synthetic clips and retain metadata from the real decoder."""
    from normalize_capture import ROLES, inspect_video
    root = Path(root)
    counts = {"cam01": 4, "cam02": 4} if counts is None else dict(counts)
    outputs = {}
    for role, relative in ROLES.items():
        count = counts[role[:5]] if role.endswith("_trial") else 2
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_generated_clip(count))
        observed = inspect_video(path)
        outputs[role] = {"path": relative, "sha256": _digest(path),
                         **{key: observed[key] for key in
                            ("width", "height", "fps", "frame_count", "timestamps")}}
    normalization = _write(root, "normalization.json", json.dumps({
        "schema": "kinelab.normalization.v1", **identity, "outputs": outputs,
    }, allow_nan=False))
    _write(root, "preflight.json", json.dumps({
        "schema": "kinelab.preflight.v1", **identity, "ok": True, "errors": [],
    }, allow_nan=False))
    return {"path": "normalization.json", "sha256": _digest(normalization)}, outputs


def native_chain_fixture(root, identity, *, counts=None, offsets=None,
                         through="personAssociation", people=None):
    """Construct independent expected inventories, never call the gate to pass it."""
    from run_pipeline import QUALITY_POLICY
    root = Path(root)
    counts = {"cam01": 4, "cam02": 4} if counts is None else dict(counts)
    offsets = {"cam01": 0, "cam02": 0} if offsets is None else dict(offsets)
    binding, outputs = generated_normalization(root, identity, counts)
    ranges = {cam: [max(1, -offsets[cam]), counts[cam] - offsets[cam]]
              for cam in counts}
    common = [max(value[0] for value in ranges.values()),
              min(value[1] for value in ranges.values())]
    if common[1] - common[0] < 1:
        raise ValueError("TEST_ONLY source pairs need a nonempty common range")
    if through != "poseEstimation" and any(end - start < 2 for start, end in ranges.values()):
        raise ValueError("TEST_ONLY synchronization requires two distinct frames per camera")
    summary = {
        "schema": "kinelab.decoded-source-coverage.v1", "normalization": binding,
        "native_frame_policy": copy.deepcopy(NATIVE_FRAME_POLICY),
        "cameras": {cam: {
            "path": outputs[cam + "_trial"]["path"],
            "sha256": outputs[cam + "_trial"]["sha256"],
            "decoded_frame_count": counts[cam], "source_range": [0, counts[cam]],
            "offset_frames": None, "synchronized_range": None,
        } for cam in counts},
        "common_range": None,
        "associated_missing_frames": {cam: [] for cam in counts},
        "physical_source_frame_equality": "UNVERIFIED",
    }
    record = {"schema": "kinelab.run.v1", "coordinateSystem": "opensim_y_up",
              "quality_policy": QUALITY_POLICY, **identity,
              "normalization": binding, "native_frame_policy": copy.deepcopy(NATIVE_FRAME_POLICY),
              "stages": [{"name": stage, "status": "not-run", "artifacts": []} for stage in STAGES]}
    for stage in NATIVE_STAGES[:NATIVE_STAGES.index(through) + 1]:
        folder = {"poseEstimation": "pose", "synchronization": "pose-sync",
                  "personAssociation": "pose-associated"}[stage]
        if stage == "synchronization":
            for cam in counts:
                summary["cameras"][cam].update(
                    offset_frames=offsets[cam], synchronized_range=ranges[cam])
            summary["common_range"] = common
        artifacts = []
        for cam in counts:
            raw_people = ([{"pose_keypoints_2d": [10, 20, .9]}]
                          if people is None else people[cam])
            indexes = (range(counts[cam]) if stage == "poseEstimation" else
                       range(*ranges[cam]) if stage == "synchronization" else range(*common))
            for index in indexes:
                source = index if stage == "poseEstimation" else index + offsets[cam]
                payload = {"version": 1.3, "TEST_ONLY_source_index": source, "people": raw_people}
                path = _write(root, f"{folder}/{cam}_json/{cam}_{index:06d}.json",
                              json.dumps(payload, allow_nan=False))
                artifacts.append({"path": path.relative_to(root).as_posix(), "sha256": _digest(path)})
        quality = {"ok": True, "fixture_only": True, "policy": QUALITY_POLICY,
                   "source_coverage": copy.deepcopy(summary)}
        if stage == "synchronization":
            reference = next(cam for cam in counts if offsets[cam] == 0)
            other = next(cam for cam in counts if cam != reference)
            log = _write(root, "logs.txt",
                         f"Camera {reference} and {other}: {offsets[other]} frames offset correlation 0.99\n")
            quality.update(reference=reference, native_correlation=.99,
                cameras={cam: {"offset_frames": offsets[cam], "start_residual_frames": 0,
                               "end_residual_frames": 0} for cam in counts},
                source_frame_pairs=[
                    {"camera": cam, "synchronized_frame_index": index,
                     "source_frame_index": index + offsets[cam]}
                    for cam in counts for index in (ranges[cam][0], ranges[cam][1] - 1)],
                log={"path": "logs.txt", "start": 0, "end": log.stat().st_size, "sha256": _digest(log)})
        record["stages"][STAGES.index(stage)].update(
            status="passed", quality=quality, artifacts=artifacts)
    _write(root, "run.json", json.dumps(record, allow_nan=False))
    return record


def complete_native_fixture(root, trc_text, mot_text=None, through="filtering", *, downstream_trc_text=None):
    from run_pipeline import KINEMATICS_POLICY, QUALITY_POLICY
    root = Path(root)
    session = json.loads((root / "session.json").read_text(encoding="utf-8"))
    identity = {"session_id": session["session_id"], "config_sha256": _digest(root / "Config.toml"),
                "inputs": {key: value["sha256"] for key, value in session["captures"].items()}}
    counts, offsets = {"cam01": 4, "cam02": 4}, {"cam01": 0, "cam02": 0}
    if STAGES.index(through) >= STAGES.index("triangulation"):
        # Bound native fixtures use the required normalized rate. Unbound parser fixtures
        # retain their 29.97 header and all timestamps remain unchanged in both families.
        lines = trc_text.splitlines()
        header = lines[2].split("\t")
        header[:2] = ["30", "30"]
        lines[2] = "\t".join(header)
        trc_text = "\n".join(lines) + "\n"
        if downstream_trc_text is not None:
            downstream_lines = downstream_trc_text.splitlines()
            downstream_header = downstream_lines[2].split("\t")
            downstream_header[:2] = ["30", "30"]
            downstream_lines[2] = "\t".join(downstream_header)
            downstream_trc_text = "\n".join(downstream_lines) + "\n"
        times = [float(line.split()[1]) for line in lines[5:] if line.strip()]
        first, last = round(min(times) * 30), round(max(times) * 30)
        if first < 1 or last < first:
            raise ValueError("TEST_ONLY bound TRC fixture requires a positive, nonempty native interval")
        counts = {"cam01": last + 1, "cam02": max(2, last - first + 1)}
        offsets = {"cam01": 0, "cam02": -first}
    native_through = through if through in NATIVE_STAGES else (
        "personAssociation" if STAGES.index(through) >= 3 else "poseEstimation")
    record = native_chain_fixture(root, identity, counts=counts, offsets=offsets, through=native_through)
    if through == "calibration":
        for item in record["stages"][1:]:
            item.update(status="not-run", artifacts=[])
            item.pop("quality", None)
    calibration = _write(root, "calibration/fixture.toml", "# generated calibration fixture")
    log = root / "logs.txt"
    start = log.stat().st_size if log.is_file() else 0
    with log.open("ab") as stream:
        stream.write(b"Residual (RMS) calibration errors for each camera are respectively [0.2, 0.3] px,\n")
    raw = log.read_bytes()[start:]
    record["stages"][0].update(status="passed",
        artifacts=[{"path": "calibration/fixture.toml", "sha256": _digest(calibration)}],
        quality={"ok": True, "fixture_only": True, "policy": QUALITY_POLICY,
                 "log": {"path": "logs.txt", "start": start, "end": start + len(raw),
                         "sha256": hashlib.sha256(raw).hexdigest()}})
    paths = {"triangulation": "pose-3d/fixture.trc", "filtering": "pose-3d/fixture_filt.trc",
             "markerAugmentation": "pose-3d/fixture_filt_LSTM.trc", "kinematics": "kinematics/fixture.mot"}
    for index in range(4, STAGES.index(through) + 1):
        name = STAGES[index]
        relative = paths[name]
        text = (mot_text if name == "kinematics" else
                downstream_trc_text if name != "triangulation" and downstream_trc_text is not None else trc_text)
        path = _write(root, relative, text)
        artifacts = [{"path": relative, "sha256": _digest(path)}]
        quality = {"ok": True, "fixture_only": True, "policy": QUALITY_POLICY}
        if name == "triangulation":
            quality["source_coverage"] = copy.deepcopy(record["stages"][3]["quality"]["source_coverage"])
        elif name != "kinematics":
            quality["source"] = record["stages"][index - 1]["artifacts"][0]
        else:
            model = _write(root, "kinematics/fixture.osim", "<OpenSimDocument/>")
            artifacts.append({"path": "kinematics/fixture.osim", "sha256": _digest(model)})
            quality.update(policy=KINEMATICS_POLICY, consumed_trc=record["stages"][6]["artifacts"][0])
        record["stages"][index].update(status="passed", quality=quality, artifacts=artifacts)
    manifest = _write(root, "run.json", json.dumps(record, allow_nan=False))
    return manifest, root / paths["filtering"], root / paths["kinematics"]

