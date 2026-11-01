"""N01 frame-level reconstruction diagnostics: generated TEST_ONLY regressions.

Every fixture value is generated. None is a measured participant value, physical
accuracy claim or clinical measurement. RED expectation before the N01 patch:
failures are assertions ("N01 MISSING ..." / "ValueError not raised"), never
ImportError or SyntaxError; pipeline_quality and run_pipeline import without
cv2/Pose2Sim. One compatibility guard passes before and after the patch.
"""
import copy
import hashlib
import inspect
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pipeline_quality as quality
import run_pipeline

H = lambda c: c * 64  # generated digest placeholder, never a real file hash
CAMERAS = ["cam01", "cam02"]
REQUIRED = ["Hip", "RHip", "RKnee", "RAnkle", "LHip", "LKnee", "LAnkle"]
SCHEMA = "kinelab.reconstruction-frames.v1"
CRITERIA = {"views": 2, "likelihood": [0.3, 1], "reprojection_px_max": 15, "coverage_min": 0.95, "longest_gap_frames_max": 3}
TRC = {"path": "pose-3d/TEST_ONLY.trc", "sha256": H("7")}
CALIBRATION = {"path": "calibration/TEST_ONLY.toml", "sha256": H("c")}
SESSION = "TEST_ONLY-n01-generated"


def cam(status, likelihood=None, residual=None, depth=None):
    return {"status": status, "likelihood": likelihood, "reprojection_px": residual, "camera_depth": depth}


def good():
    return {"cam01": cam("supported", .9, 2.0, 2.1), "cam02": cam("supported", .8, 3.5, 2.4)}


def generated_observations():
    """TEST_ONLY generated per-frame, per-marker, per-camera observations (6 frames)."""
    rknee = {
        0: good(),
        1: {"cam01": cam("supported", .9, 2.0, 2.1), "cam02": cam("no_pose_file")},
        2: {"cam01": cam("behind_camera", .7, None, -0.4), "cam02": cam("supported", .8, 3.0, 2.4)},
        3: {"cam01": cam("supported", .2, 2.0, 2.1), "cam02": cam("supported", .8, 3.0, 2.4)},
        4: {"cam01": cam("supported", .9, 22.0, 2.1), "cam02": cam("supported", .8, 3.0, 2.4)},
        5: {"cam01": cam("trc_point_missing"), "cam02": cam("trc_point_missing", .6)},
    }
    rows = []
    for frame in range(6):
        for marker in REQUIRED:
            rows.append({"frame": frame, "marker": marker, "cameras": rknee[frame] if marker == "RKnee" else good()})
    return rows


def identity(session="TEST_ONLY-n01-generated"):
    return {"session_id": session, "camera_ids": list(CAMERAS), "source_trc": dict(TRC), "calibration": dict(CALIBRATION)}


def current_rule_samples(rows):
    """Exactly the sample shape validate_reconstruction feeds assess_reconstruction today."""
    samples = []
    for row in rows:
        supported = [row["cameras"][c] for c in CAMERAS if row["cameras"][c]["status"] == "supported"]
        errors = [c["reprojection_px"] for c in supported]
        samples.append({"marker": row["marker"], "frame": row["frame"], "views": len(supported),
                        "likelihoods": [c["likelihood"] for c in supported],
                        "reprojection_px": max(errors) if errors else None, "interpolated": False})
    return samples


class Api(unittest.TestCase):
    def api(self, name):
        fn = getattr(quality, name, None)
        self.assertTrue(callable(fn), "N01 MISSING: pipeline_quality." + name + " is not implemented")
        return fn

    def session_kw(self, fn):
        self.assertIn("session_id", inspect.signature(fn).parameters,
                      "N01 MISSING: " + fn.__name__ + " does not bind the validated session_id")
        return {"session_id": SESSION}

    def build(self, rows=None, ident=None):
        return self.api("build_frame_diagnostics")(generated_observations() if rows is None else rows, REQUIRED,
                                                   identity() if ident is None else ident)


class FrameDiagnosticsBuilder(Api):
    def test_document_binds_exact_identity_and_disclaims_validation(self):
        doc = self.build()
        self.assertEqual(doc["schema"], SCHEMA)
        self.assertEqual(doc["policy"], quality.QUALITY_POLICY)
        self.assertEqual(doc["session_id"], "TEST_ONLY-n01-generated")
        self.assertEqual(doc["source_trc"], TRC)
        self.assertEqual(doc["calibration"], CALIBRATION)
        self.assertEqual(doc["camera_ids"], CAMERAS)
        self.assertEqual(doc["required_markers"], REQUIRED)
        self.assertEqual(doc["classification"], "native_triangulated_unfiltered")
        self.assertEqual(doc["value_kind"], "reconstruction estimate; research diagnostic; not measured physical truth")
        self.assertEqual(doc["physical_accuracy"], "not validated")
        self.assertEqual(doc["clinical_validation"], "UNVERIFIED")
        self.assertIn("UNVERIFIED", doc["frame_index_basis"])
        self.assertIn("UNVERIFIED", doc["camera_depth_units"])
        self.assertNotIn("run", doc, "sidecar must not embed the run manifest hash (circular binding)")

    def test_criteria_reuse_existing_policy_without_new_thresholds(self):
        self.assertEqual(self.build()["criteria"], CRITERIA)

    def test_per_frame_validity_matches_current_assess_reconstruction(self):
        rows = generated_observations()
        doc = self.build(rows)
        summary = quality.assess_reconstruction(current_rule_samples(rows), REQUIRED)
        for marker in REQUIRED:
            valid = sum(frame["markers"][marker]["valid"] for frame in doc["frames"])
            self.assertEqual(valid, summary["markers"][marker]["observed"], marker)
        self.assertEqual([f["synchronized_frame_index"] for f in doc["frames"]], list(range(6)))
        self.assertEqual([f["synchronized_frame_index"] for f in doc["frames"] if f["rejected"]], [1, 2, 3, 4, 5])
        for frame in doc["frames"]:
            self.assertIs(type(frame["rejected"]), bool)
            self.assertEqual(list(frame["markers"]), REQUIRED)
            for marker in frame["markers"].values():
                self.assertIs(type(marker["valid"]), bool)

    def test_missingness_depth_and_residual_are_preserved_not_filled(self):
        frames = self.build()["frames"]
        r = lambda i: frames[i]["markers"]["RKnee"]
        self.assertEqual(r(0)["views"], 2)
        self.assertEqual(r(0)["cameras"]["cam02"], cam("supported", .8, 3.5, 2.4))
        self.assertEqual(r(1)["cameras"]["cam02"], cam("no_pose_file"))
        self.assertEqual(r(1)["views"], 1)
        self.assertEqual(r(2)["cameras"]["cam01"], cam("behind_camera", .7, None, -0.4))
        self.assertEqual(r(5)["cameras"]["cam01"], cam("trc_point_missing"))
        self.assertEqual(r(5)["cameras"]["cam02"], cam("trc_point_missing", .6))
        self.assertEqual(r(5)["views"], 0)
        self.assertFalse(r(4)["valid"])
        self.assertEqual(r(4)["cameras"]["cam01"]["reprojection_px"], 22.0)

    def test_non_finite_projection_becomes_null_and_document_is_strict_json(self):
        rows = generated_observations()
        rows[0]["cameras"]["cam01"] = cam("projection_non_finite", .9, math.nan, 2.1)
        doc = self.build(rows)
        self.assertEqual(doc["frames"][0]["markers"]["Hip"]["cameras"]["cam01"], cam("projection_non_finite", .9, None, 2.1))
        json.dumps(doc, allow_nan=False)

    def test_projection_nonfinite_refuses_boolean_residual(self):
        rows = generated_observations()
        rows[0]["cameras"]["cam01"] = cam("projection_non_finite", .9, True, 2.1)
        with self.assertRaises(ValueError):
            self.build(rows)

    def test_projection_nonfinite_refuses_string_residual(self):
        rows = generated_observations()
        rows[0]["cameras"]["cam01"] = cam("projection_non_finite", .9, "bad", 2.1)
        with self.assertRaises(ValueError):
            self.build(rows)

    def test_behind_camera_refuses_boolean_depth(self):
        rows = generated_observations()
        rows[0]["cameras"]["cam01"] = cam("behind_camera", .7, None, True)
        with self.assertRaises(ValueError):
            self.build(rows)

    def test_behind_camera_refuses_string_depth(self):
        rows = generated_observations()
        rows[0]["cameras"]["cam01"] = cam("behind_camera", .7, None, "bad")
        with self.assertRaises(ValueError):
            self.build(rows)

    def test_numeric_nonfinite_projection_and_depth_remain_missing(self):
        for status, field in (("projection_non_finite", "reprojection_px"), ("behind_camera", "camera_depth")):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(status=status, field=field, value=value):
                    rows = generated_observations()
                    cell = cam(status, .9, None, 2.1 if status == "projection_non_finite" else None)
                    cell[field] = value
                    rows[0]["cameras"]["cam01"] = cell
                    doc = self.build(rows)
                    marker = doc["frames"][0]["markers"]["Hip"]
                    self.assertIsNone(marker["cameras"]["cam01"][field])
                    self.assertFalse(marker["valid"])
                    self.assertTrue(doc["frames"][0]["rejected"])
                    json.dumps(doc, allow_nan=False)

    def test_contradictory_or_unknown_observations_fail_closed(self):
        self.api("build_frame_diagnostics")
        mutations = [
            lambda rows: rows[0]["cameras"]["cam01"].update(status="interpolated"),
            lambda rows: rows[0]["cameras"]["cam01"].update(likelihood=math.nan),
            lambda rows: rows[0]["cameras"]["cam01"].update(likelihood=1.2),
            lambda rows: rows[0]["cameras"]["cam01"].update(likelihood=True),
            lambda rows: rows[0]["cameras"]["cam01"].update(reprojection_px=None),
            lambda rows: rows[0]["cameras"]["cam01"].update(reprojection_px=-1.0),
            lambda rows: rows[0]["cameras"]["cam01"].update(camera_depth=0.0),
            lambda rows: rows[0]["cameras"]["cam01"].update(camera_depth=None),
            lambda rows: rows[0]["cameras"].update(cam01=cam("behind_camera", .7, None, 2.0)),
            lambda rows: rows[0]["cameras"].update(cam01=cam("no_pose_file", .7)),
            lambda rows: rows[0]["cameras"].update(cam01=cam("trc_point_missing", None, 2.0)),
            lambda rows: rows[0]["cameras"].pop("cam02"),
            lambda rows: rows[0]["cameras"].update(cam03=cam("supported", .9, 1.0, 1.0)),
            lambda rows: rows.append(copy.deepcopy(rows[0])),
            lambda rows: rows[0].update(frame=-1),
            lambda rows: rows[0].update(frame=True),
            lambda rows: rows[0].update(marker="NotRequired"),
            lambda rows: rows.pop(0),
        ]
        for number, mutate in enumerate(mutations):
            rows = generated_observations()
            mutate(rows)
            with self.assertRaises(ValueError, msg=f"mutation {number}"):
                self.build(rows)


class FrameDiagnosticsStorage(Api):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.project = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write_raw(self, data):
        digest = hashlib.sha256(data).hexdigest()
        relative = "diagnostics/reconstruction-frames." + digest + ".json"
        (self.project / "diagnostics").mkdir(exist_ok=True)
        (self.project / relative).write_bytes(data)
        return {"path": relative, "sha256": digest, "schema": SCHEMA, "source_trc": dict(TRC),
                "calibration": dict(CALIBRATION), "frames": 6}

    def test_content_addressed_fsynced_write_never_overwrites_bound_bytes(self):
        write = self.api("write_frame_diagnostics")
        order = []
        real_fsync, real_link = os.fsync, os.link
        with mock.patch("os.fsync", side_effect=lambda fd: (order.append("fsync"), real_fsync(fd))[1]), \
                mock.patch("os.link", side_effect=lambda a, b: (order.append("link"), real_link(a, b))[1]):
            binding = write(self.project, self.build())
        self.assertIn("fsync", order, "sidecar bytes must be fsynced before publication")
        self.assertLess(order.index("fsync"), order.index("link"))
        path = self.project / binding["path"]
        self.assertTrue(binding["path"].startswith("diagnostics/reconstruction-frames."))
        self.assertIn(binding["sha256"], binding["path"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), binding["sha256"])
        self.assertEqual(binding, {"path": binding["path"], "sha256": binding["sha256"], "schema": SCHEMA,
                                   "source_trc": TRC, "calibration": CALIBRATION, "frames": 6})
        self.assertEqual([p.name for p in path.parent.iterdir()], [path.name], "no partial file may remain")
        original = path.read_bytes()
        other = write(self.project, self.build(ident=identity("TEST_ONLY-n01-other")))
        self.assertNotEqual(other["path"], binding["path"])
        self.assertEqual(path.read_bytes(), original)
        path.write_bytes(original + b" ")
        with self.assertRaises(ValueError):
            write(self.project, self.build())
        self.assertEqual(path.read_bytes(), original + b" ", "writer must not repair or rewrite an existing reference")

    def test_write_and_read_are_bounded_and_fail_closed(self):
        self.assertTrue(isinstance(getattr(quality, "FRAME_DIAGNOSTICS_MAX_BYTES", None), int),
                        "N01 MISSING: explicit FRAME_DIAGNOSTICS_MAX_BYTES cap")
        write, verify = self.api("write_frame_diagnostics"), self.api("verify_frame_diagnostics")
        binding = write(self.project, self.build())
        with mock.patch.object(quality, "FRAME_DIAGNOSTICS_MAX_BYTES", 64):
            with self.assertRaises(ValueError):
                verify(self.project, binding, **self.session_kw(verify))
            with self.assertRaises(ValueError):
                write(self.project, self.build(ident=identity("TEST_ONLY-n01-large")))
        self.assertEqual(len(list((self.project / "diagnostics").iterdir())), 1, "oversized sidecar must not be published")

    def test_verify_hashes_and_parses_the_same_bytes(self):
        binding = self.api("write_frame_diagnostics")(self.project, self.build())
        verify = self.api("verify_frame_diagnostics")
        self.assertEqual(verify(self.project, binding, **self.session_kw(verify))["session_id"], "TEST_ONLY-n01-generated")
        changed = self.build(ident=identity("TEST_ONLY-n01-swapped"))
        (self.project / binding["path"]).write_text(json.dumps(changed, indent=2, sort_keys=True), encoding="utf-8")
        with (mock.patch.object(quality, "sha256_file", return_value=binding["sha256"]),
              self.assertRaises(ValueError, msg="a separate hash pass must not vouch for different parsed bytes")):
            verify(self.project, binding, **self.session_kw(verify))

    def test_verify_rejects_changed_missing_escaped_or_rebound_sidecar(self):
        binding = self.api("write_frame_diagnostics")(self.project, self.build())
        verify = self.api("verify_frame_diagnostics")
        for change in ({"sha256": H("0")}, {"path": "../outside.json"}, {"path": "diagnostics/absent.json"},
                       {"path": "diagnostics/reconstruction-frames." + H("1") + ".json", "sha256": H("1")},
                       {"source_trc": {"path": TRC["path"], "sha256": H("8")}},
                       {"calibration": {"path": CALIBRATION["path"], "sha256": H("8")}}, {"frames": 5}):
            with self.assertRaises(ValueError, msg=str(change)):
                verify(self.project, {**binding, **change}, **self.session_kw(verify))

    def test_verify_rejects_duplicate_nonfinite_and_contradictory_content(self):
        verify = self.api("verify_frame_diagnostics")
        doc = self.build()
        text = json.dumps(doc, indent=2, sort_keys=True)
        duplicate = text.replace('"schema": "' + SCHEMA + '"', '"schema": "' + SCHEMA + '", "schema": "' + SCHEMA + '"', 1)
        nonfinite = text.replace('"reprojection_px": 2.0', '"reprojection_px": NaN', 1)
        contradictory = copy.deepcopy(doc)
        contradictory["frames"][1]["markers"]["RKnee"]["valid"] = True
        flipped = copy.deepcopy(doc)
        flipped["frames"][0]["rejected"] = True
        typed = copy.deepcopy(doc)
        typed["frames"][0]["markers"]["Hip"]["valid"] = 1
        criteria = copy.deepcopy(doc)
        criteria["criteria"]["reprojection_px_max"] = 20
        for number, data in enumerate([duplicate.encode(), nonfinite.encode(), b"\xff\xfe{}",
                                       *(json.dumps(d, sort_keys=True).encode() for d in (contradictory, flipped, typed, criteria))]):
            with self.assertRaises(ValueError, msg=f"content {number}"):
                verify(self.project, self.write_raw(data), **self.session_kw(verify))

    def test_verify_rejects_symlinked_sidecar(self):
        binding = self.api("write_frame_diagnostics")(self.project, self.build())
        real = self.project / binding["path"]
        outside = self.project / "outside.json"
        real.replace(outside)
        try:
            real.symlink_to(outside)
        except OSError as error:
            self.skipTest("symlink creation unavailable on this host: " + str(error))
        verify = self.api("verify_frame_diagnostics")
        with self.assertRaises(ValueError):
            verify(self.project, binding, **self.session_kw(verify))

    def test_verify_binds_the_validated_session_identity(self):
        verify = self.api("verify_frame_diagnostics")
        kw = self.session_kw(verify)
        write = self.api("write_frame_diagnostics")
        other = write(self.project, self.build(ident=identity("TEST_ONLY-n01-other")))
        own = write(self.project, self.build())
        self.assertEqual({k: v for k, v in other.items() if k not in ("path", "sha256")},
                         {k: v for k, v in own.items() if k not in ("path", "sha256")}, "fixture: identical TRC/calibration/frames")
        with self.assertRaises(ValueError, msg="another session's sidecar with identical source hashes must not pass"):
            verify(self.project, other, **kw)
        self.assertEqual(verify(self.project, own, **kw)["session_id"], SESSION)
        for missing in (None, "", 7):
            with self.assertRaises(ValueError, msg=repr(missing)):
                verify(self.project, own, session_id=missing)

    def observe_read_requests(self, target):
        """Observe the bound while every read and descriptor belongs to a real file."""
        real_open, requests = Path.open, []

        class ObservedStream:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def fileno(self):
                return self.stream.fileno()

            def read(self, size=-1):
                requests.append(size)
                return self.stream.read(size)

        def observed_open(path, *args, **kwargs):
            stream = real_open(path, *args, **kwargs)
            mode = args[0] if args else kwargs.get("mode", "r")
            return ObservedStream(stream) if path == target and mode == "rb" else stream

        return mock.patch.object(Path, "open", new=observed_open), requests

    def test_read_request_tracks_initial_size_and_preserves_byte_cap(self):
        cap = 32
        for size in (0, 5, cap, cap + 1):
            with self.subTest(size=size):
                path = self.project / f"TEST_ONLY-bound-{size}.bin"
                original = b"x" * size
                path.write_bytes(original)
                observer, requests = self.observe_read_requests(path)
                with mock.patch.object(quality, "FRAME_DIAGNOSTICS_MAX_BYTES", cap), observer:
                    if size > cap:
                        with self.assertRaisesRegex(ValueError, "exceed the byte cap"):
                            quality._read_frame_bytes(path)
                    else:
                        self.assertEqual(quality._read_frame_bytes(path), original)
                self.assertEqual(requests, [] if size > cap else [size + 1])
                self.assertEqual(path.read_bytes(), original, "reader must not alter generated bytes")

    def test_read_request_refuses_real_growth_and_shrink_without_repair(self):
        original = b"abcdef"
        for label, changed in (("grow", original + b"!"), ("grow-past-cap", b"x" * 40),
                               ("shrink", original[:2])):
            with self.subTest(change=label):
                path = self.project / f"TEST_ONLY-{label}.bin"
                path.write_bytes(original)

                def mutate_after_open(number, fields, path=path, changed=changed):
                    if number == 1:
                        path.write_bytes(changed)

                descriptor_patch, descriptors = self.descriptor_stat(mutate_after_open)
                observer, requests = self.observe_read_requests(path)
                with (
                    mock.patch.object(quality, "FRAME_DIAGNOSTICS_MAX_BYTES", 32),
                    descriptor_patch,
                    observer,
                    self.assertRaisesRegex(ValueError, "QUALITY_UNVERIFIED:"),
                ):
                    quality._read_frame_bytes(path)
                self.assertEqual(len(descriptors), 2, "both descriptor observations remain mandatory")
                self.assertEqual(requests, [len(original) + 1])
                self.assertEqual(path.read_bytes(), changed, "reader must not repair actual mutation")

    def test_read_request_refuses_inaccurate_stat_sizes_with_a_positive_bound(self):
        original = b"abcdef"
        for reported in (3, 9, -2):
            with self.subTest(reported_size=reported):
                path = self.project / f"TEST_ONLY-reported-{reported}.bin"
                path.write_bytes(original)
                real_stat, real_fstat = Path.stat, os.fstat
                descriptors = []

                def with_size(item, reported=reported):
                    fields = {name: getattr(item, name) for name in dir(item) if name.startswith("st_")}
                    fields["st_size"] = reported
                    return SimpleNamespace(**fields)

                def reported_stat(candidate, *args, real_stat=real_stat, path=path, **kwargs):
                    item = real_stat(candidate, *args, **kwargs)
                    return with_size(item) if candidate == path else item

                def reported_fstat(fd, descriptors=descriptors, real_fstat=real_fstat):
                    descriptors.append(fd)
                    return with_size(real_fstat(fd))

                observer, requests = self.observe_read_requests(path)
                with (
                    mock.patch.object(quality, "FRAME_DIAGNOSTICS_MAX_BYTES", 32),
                    mock.patch.object(Path, "stat", new=reported_stat),
                    mock.patch.object(quality.os, "fstat", side_effect=reported_fstat),
                    observer,
                    self.assertRaisesRegex(ValueError, "frame diagnostics changed while read"),
                ):
                    quality._read_frame_bytes(path)
                self.assertEqual(len(descriptors), 2)
                expected_bound = 1 if reported < 0 else reported + 1
                self.assertEqual(requests, [expected_bound], "no read-all sentinel or cap-sized allocation")
                self.assertEqual(path.read_bytes(), original)

    def descriptor_stat(self, change):
        """House pattern: replace os.fstat results with a changed generated stat view."""
        real, calls = os.fstat, []

        def hooked(fd):
            calls.append(fd)
            item = real(fd)
            fields = {name: getattr(item, name) for name in dir(item) if name.startswith("st_")}
            change(len(calls), fields)
            return SimpleNamespace(**fields)
        return mock.patch.object(quality.os, "fstat", side_effect=hooked), calls

    def test_read_refuses_replacement_between_path_check_and_open(self):
        binding = self.api("write_frame_diagnostics")(self.project, self.build())
        patch, _ = self.descriptor_stat(lambda n, f: f.update(st_ino=f["st_ino"] + 1) if n == 1 else None)
        with patch, self.assertRaises(ValueError, msg="descriptor is not the file whose path was checked"):
            quality._read_frame_bytes(self.project / binding["path"])

    def test_read_refuses_descriptor_change_after_read(self):
        binding = self.api("write_frame_diagnostics")(self.project, self.build())
        patch, _ = self.descriptor_stat(lambda n, f: f.update(st_size=f["st_size"] + 1, st_mtime_ns=f["st_mtime_ns"] + 1) if n == 2 else None)
        with patch, self.assertRaises(ValueError, msg="file grew while it was read"):
            quality._read_frame_bytes(self.project / binding["path"])

    def test_read_refuses_real_growth_and_never_repairs(self):
        binding = self.api("write_frame_diagnostics")(self.project, self.build())
        path = self.project / binding["path"]
        original = path.read_bytes()

        def grow(number, fields):
            if number == 1:
                with path.open("ab") as stream:
                    stream.write(b" ")
        patch, calls = self.descriptor_stat(grow)
        with patch, self.assertRaises(ValueError, msg="growth during the read window"):
            quality._read_frame_bytes(self.project / binding["path"])
        self.assertTrue(calls, "N01 MISSING: reader never checked descriptor identity")
        self.assertEqual(path.read_bytes(), original + b" ", "reader must not repair a changed sidecar")

    def test_windows_ctime_interface_precision_does_not_invent_a_change(self):
        binding = self.api("write_frame_diagnostics")(self.project, self.build())
        patch, _ = self.descriptor_stat(lambda n, f: f.update(st_ctime_ns=f["st_ctime_ns"] + 1))
        with patch:
            self.assertEqual(quality._read_frame_bytes(self.project / binding["path"]), (self.project / binding["path"]).read_bytes())

    def test_reader_refuses_links_and_non_regular_paths_before_opening(self):
        binding = self.api("write_frame_diagnostics")(self.project, self.build())
        real = self.project / binding["path"]
        outside = self.project / "outside.json"
        outside.write_bytes(real.read_bytes())
        link = real.with_name("linked-" + real.name)
        try:
            link.symlink_to(outside)
        except OSError as error:
            self.skipTest("symlink creation unavailable on this host: " + str(error))
        for target in (link, self.project / "diagnostics"):
            patch, calls = self.descriptor_stat(lambda n, f: None)
            with patch:
                try:
                    quality._read_frame_bytes(target)
                except ValueError:
                    pass
                except OSError as error:
                    self.fail("non-regular path must be refused with a coded ValueError before open, not " + type(error).__name__)
                else:
                    self.fail("N01 MISSING: _read_frame_bytes followed a link or read a non-regular path: " + target.name)
            self.assertEqual(calls, [], "external or non-regular target must never be opened")

    def test_read_refuses_same_byte_symlink_after_final_path_stat(self):
        binding = self.api("write_frame_diagnostics")(self.project, self.build())
        path = self.project / binding["path"]
        original = path.read_bytes()
        outside = self.project / "outside-after-final-stat.json"
        outside.write_bytes(original)
        prepared = path.with_name("linked-after-final-stat-" + path.name)
        try:
            prepared.symlink_to(outside)
        except OSError as error:
            self.skipTest("symlink creation unavailable on this host: " + str(error))

        real_stat, real_fstat = Path.stat, os.fstat
        descriptor_stats, swapped = [], []

        def observed_fstat(fd):
            result = real_fstat(fd)
            descriptor_stats.append(result)
            return result

        def swap_after_final_stat(candidate, *args, **kwargs):
            result = real_stat(candidate, *args, **kwargs)
            if (candidate == path and kwargs.get("follow_symlinks", True) is False
                    and len(descriptor_stats) == 2 and not swapped):
                # Preserve the real final stat result, then replace the actual
                # leaf with a prepared same-byte link before that result returns.
                prepared.replace(path)
                swapped.append(result)
            return result

        with (
            mock.patch.object(quality.os, "fstat", side_effect=observed_fstat),
            mock.patch.object(Path, "stat", new=swap_after_final_stat),
            self.assertRaisesRegex(ValueError, "frame diagnostics changed while read"),
        ):
            quality._read_frame_bytes(path)
        self.assertEqual(len(descriptor_stats), 2, "both real descriptor stats must precede the swap")
        self.assertEqual(len(swapped), 1, "the actual leaf must change after final-stat capture")
        self.assertTrue(path.is_symlink(), "reader must preserve, not repair, the substituted link")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(outside.read_bytes(), original)


class RunEvidenceBindsFrameDiagnostics(Api):
    """_verify_quality_binding (called by validate_run_evidence, hence export_motion.bind_run) ignores
    frame_diagnostics today, so the rejection cases are RED by assertion."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.project = Path(self.directory.name)
        self.stages = [{"name": "calibration", "status": "passed", "artifacts": [dict(CALIBRATION)]},
                       {"name": "triangulation", "status": "passed", "artifacts": [dict(TRC)]}]

    def tearDown(self):
        self.directory.cleanup()

    def bind(self, item):
        fn = run_pipeline._verify_quality_binding
        return fn(self.project, item, self.stages, **self.session_kw(fn))

    def item(self, **changes):
        binding = self.api("write_frame_diagnostics")(self.project, self.build())
        return {"name": "triangulation", "quality": {"ok": True, "policy": quality.QUALITY_POLICY,
                                                      "frame_diagnostics": {**binding, **changes}}}

    def test_bound_sidecar_verifies(self):
        self.bind(self.item())

    def test_changed_or_missing_sidecar_fails_run_evidence(self):
        item = self.item()
        path = self.project / item["quality"]["frame_diagnostics"]["path"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            self.bind(item)
        path.unlink()
        with self.assertRaises(ValueError):
            self.bind(item)

    def test_sidecar_bound_to_other_trc_or_calibration_fails_run_evidence(self):
        for change in ({"source_trc": {"path": "pose-3d/other.trc", "sha256": H("8")}},
                       {"calibration": {"path": "calibration/other.toml", "sha256": H("8")}}):
            with self.assertRaises(ValueError, msg=str(change)):
                self.bind(self.item(**change))

    def test_malformed_binding_fails_run_evidence(self):
        for binding in (None, "diagnostics/x.json", {}, []):
            item = {"name": "triangulation", "quality": {"ok": True, "policy": quality.QUALITY_POLICY, "frame_diagnostics": binding}}
            with self.assertRaises(ValueError, msg=repr(binding)):
                self.bind(item)

    def test_legacy_runs_without_frame_diagnostics_remain_valid(self):
        run_pipeline._verify_quality_binding(self.project, {"name": "triangulation", "quality": {"ok": True, "policy": quality.QUALITY_POLICY}}, self.stages)

    def test_legacy_runs_remain_valid_with_session_identity(self):
        legacy = {"name": "triangulation", "quality": {"ok": True, "policy": quality.QUALITY_POLICY}}
        run_pipeline._verify_quality_binding(self.project, legacy, self.stages, **self.session_kw(run_pipeline._verify_quality_binding))

    def test_sidecar_from_another_session_fails_run_evidence(self):
        binding = self.api("write_frame_diagnostics")(self.project, self.build(ident=identity("TEST_ONLY-n01-other")))
        item = {"name": "triangulation", "quality": {"ok": True, "policy": quality.QUALITY_POLICY, "frame_diagnostics": binding}}
        with self.assertRaises(ValueError, msg="other session's content-addressed sidecar with identical source hashes"):
            self.bind(item)
        for session_id in (None, ""):
            with self.assertRaises(ValueError, msg="present binding without validated session identity: " + repr(session_id)):
                run_pipeline._verify_quality_binding(self.project, self.item(), self.stages, session_id=session_id)

    def test_validate_run_evidence_threads_the_validated_session_identity(self):
        config = self.project / "Config.toml"
        config.write_bytes(b"# TEST_ONLY generated configuration\n")
        # TEST_ONLY real normalization satisfies the v4 entry guard; the sentinel
        # below still isolates session identity threading, not native acceptance.
        from native_evidence_fixture import (
            NATIVE_FRAME_POLICY,
            _generated_clip,
            generated_normalization,
        )
        from normalize_capture import ROLES
        source_sha = hashlib.sha256(_generated_clip(3)).hexdigest()
        captures = {role: {"sha256": source_sha} for role in ROLES}
        identity = {"session_id": SESSION,
                    "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
                    "inputs": {role: source_sha for role in ROLES}}
        normalization, _ = generated_normalization(self.project, identity, {"cam01": 3, "cam02": 3})
        stages = [{"name": name, "status": "passed", "artifacts": [dict(CALIBRATION)],
                   "quality": {"ok": True, "policy": quality.QUALITY_POLICY}} for name in run_pipeline.STAGES]
        record = {"schema": "kinelab.run.v1", "coordinateSystem": "opensim_y_up", "session_id": SESSION,
                  "config_sha256": identity["config_sha256"], "inputs": identity["inputs"],
                  "normalization": normalization, "native_frame_policy": dict(NATIVE_FRAME_POLICY),
                  "quality_policy": run_pipeline.QUALITY_POLICY, "stages": stages}
        (self.project / "run.json").write_text(json.dumps(record), encoding="utf-8")
        seen = []

        class Stop(Exception):
            pass

        def capture(*args, **kwargs):
            seen.append(kwargs.get("session_id"))
            raise Stop
        with mock.patch.object(run_pipeline, "_verify_quality_binding", side_effect=capture), self.assertRaises(Stop):
            run_pipeline.validate_run_evidence(self.project, "calibration", session={"session_id": SESSION, "captures": captures})
        self.assertEqual(seen, [SESSION], "validate_run_evidence must pass its validated session_id to the quality binding check")


if __name__ == "__main__":
    unittest.main()
