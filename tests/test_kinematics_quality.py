"""Native OpenSim tests for kinematics_quality.validate_kinematics_stage.

Every fixture is synthetic: a tiny OpenSim model is built programmatically in a
fresh TemporaryDirectory, a MOT is written from known coordinate trajectories,
and the TRC is produced from that model's own forward kinematics.
"""
import hashlib
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import kinematics_quality as kq

REJECTED = "KINEMATICS_QUALITY_REJECTED"
UNAVAILABLE = "KINEMATICS_QUALITY_UNAVAILABLE"

Q1_RANGE = (-1.2, 1.2)      # rad, PinJoint about z
Q2_RANGE = (-0.2, 0.2)      # m, SliderJoint along x
RATE = 50.0
FRAMES = 21
MARKERS = {                 # name -> (body, location in body frame, m)
    "mA": ("link1", (0.10, 0.50, 0.00)),
    "mB": ("link1", (-0.05, 0.30, 0.08)),
    "mC": ("link2", (0.12, 0.05, -0.04)),
    "mD": ("link2", (0.00, 0.20, 0.06)),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_model(path, coord_names=("q1", "q2"), q1_range=Q1_RANGE, q2_range=Q2_RANGE, clamped=True):
    import opensim as osim
    model = osim.Model()
    model.setName("kinelab_synthetic_two_link")
    ground = model.getGround()
    link1 = osim.Body("link1", 1.0, osim.Vec3(0, 0.25, 0), osim.Inertia(0.01, 0.01, 0.01))
    link2 = osim.Body("link2", 0.5, osim.Vec3(0, 0.10, 0), osim.Inertia(0.005, 0.005, 0.005))
    pin = osim.PinJoint("pin1", ground, osim.Vec3(0, 1.0, 0), osim.Vec3(0, 0, 0),
                        link1, osim.Vec3(0, 0, 0), osim.Vec3(0, 0, 0))
    slide = osim.SliderJoint("slide2", link1, osim.Vec3(0, 0.5, 0), osim.Vec3(0, 0, 0),
                             link2, osim.Vec3(0, 0, 0), osim.Vec3(0, 0, 0))
    for joint, name, (lo, hi) in ((pin, coord_names[0], q1_range), (slide, coord_names[1], q2_range)):
        coord = joint.updCoordinate()
        coord.setName(name)
        coord.setRangeMin(lo)
        coord.setRangeMax(hi)
        coord.set_clamped(clamped)
    model.addBody(link1)
    model.addBody(link2)
    model.addJoint(pin)
    model.addJoint(slide)
    bodies = {"link1": link1, "link2": link2}
    for name, (body, loc) in MARKERS.items():
        model.addMarker(osim.Marker(name, bodies[body], osim.Vec3(*loc)))
    model.finalizeConnections()
    model.printToXML(str(path))
    return path


def trajectories(q1_amp=0.8, q2_amp=0.1):
    times = [i / RATE for i in range(FRAMES)]
    return [(t, q1_amp * math.sin(2 * math.pi * t), q2_amp * math.cos(2 * math.pi * t)) for t in times]


def forward_markers(model_path, rows):
    """Model-own forward kinematics: rows of (t, q1 rad, q2 m) -> {name: [(x,y,z) m]}."""
    import opensim as osim
    model = osim.Model(str(model_path))
    state = model.initSystem()
    coords = model.getCoordinateSet()
    out = {name: [] for name in MARKERS}
    for _, q1, q2 in rows:
        coords.get(0).setValue(state, q1, False)
        coords.get(1).setValue(state, q2, False)
        model.realizePosition(state)
        for name in MARKERS:
            loc = model.getMarkerSet().get(name).getLocationInGround(state)
            out[name].append((loc.get(0), loc.get(1), loc.get(2)))
    return out


def write_mot(path, rows, names=("q1", "q2"), in_degrees=True, times=None):
    lines = ["Coordinates", "version=1", f"nRows={len(rows)}", f"nColumns={1 + len(names)}",
             f"inDegrees={'yes' if in_degrees else 'no'}", "",
             "Units are S.I. units (second, meters, Newtons, ...)",
             ("If the header above contains a line with 'inDegrees', this indicates whether "
              "rotational values are in degrees (yes) or radians (no)."), "", "endheader",
             "\t".join(("time",) + tuple(names))]
    for i, (t, q1, q2) in enumerate(rows):
        t = times[i] if times is not None else t
        values = [math.degrees(q1) if in_degrees else q1, q2][:len(names)]
        lines.append("\t".join(f"{v:.10f}" for v in [t] + values))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_trc(path, times, markers, units="mm", blank=None):
    """markers: {name: [(x,y,z) m]}; blank: {(frame_index, name)} written as empty triples."""
    blank = blank or set()
    names = list(markers)
    scale = 1000.0 if units == "mm" else 1.0
    lines = ["PathFileType\t4\t(X/Y/Z)\tsynthetic.trc",
             "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames",
             f"{RATE:g}\t{RATE:g}\t{len(times)}\t{len(names)}\t{units}\t{RATE:g}\t0\t{len(times)}",
             "\t".join(["Frame#", "Time"] + [x for n in names for x in (n, "", "")]),
             "\t".join(["", ""] + [f"{a}{i}" for i in range(1, len(names) + 1) for a in "XYZ"]), ""]
    for f, t in enumerate(times):
        row = [str(f), f"{t:.6f}"]
        for n in names:
            if (f, n) in blank:
                row += ["", "", ""]
            else:
                row += [f"{v * scale:.8f}" for v in markers[n][f]]
        lines.append("\t".join(row))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class KinematicsQualityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "session"
        (self.project / "kinematics").mkdir(parents=True)
        (self.project / "pose-3d").mkdir()
        self.model = build_model(self.project / "kinematics" / "fitted.osim")
        self.rows = trajectories()
        self.times = [r[0] for r in self.rows]
        self.markers = forward_markers(self.model, self.rows)
        self.mot = write_mot(self.project / "kinematics" / "ik.mot", self.rows)
        self.trc = write_trc(self.project / "pose-3d" / "filtered.trc", self.times, self.markers)

    def tearDown(self):
        self._tmp.cleanup()

    def run_check(self, **overrides):
        args = {"model_path": self.model, "mot_path": self.mot, "trc_path": self.trc}
        args.update(overrides)
        return kq.validate_kinematics_stage(self.project, **args)

    def assert_rejected(self, result, fragment):
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["code"], REJECTED, result)
        self.assertEqual(result["policy"], kq.KINEMATICS_QUALITY_POLICY)
        self.assertEqual(result["classification"], "derived_research_only")
        self.assertTrue(any(fragment.lower() in e.lower() for e in result["errors"]),
                        f"expected {fragment!r} in {result['errors']}")

    # Positive paths -------------------------------------------------------
    def test_model_own_forward_kinematics_passes_with_hashes_and_metrics(self):
        result = self.run_check()
        self.assertTrue(result["ok"], result["errors"])
        self.assertIsNone(result["code"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(kq.KINEMATICS_QUALITY_POLICY, "kinelab.kinematics-quality.v1")
        self.assertEqual(result["policy"], "kinelab.kinematics-quality.v1")
        self.assertEqual(result["classification"], "derived_research_only")
        m = result["metrics"]
        self.assertEqual(m["frames"], FRAMES)
        self.assertEqual(m["coordinates"], 2)
        self.assertEqual(m["matched_markers"], 4)
        self.assertEqual(m["min_matched_markers_required"], kq.DEFAULT_MIN_MATCHED_MARKERS)
        self.assertLess(m["rms_marker_error_m"], 1e-5)
        self.assertLess(m["max_marker_error_m"], 1e-5)
        self.assertEqual(m["trc_units"], "mm")
        self.assertTrue(m["mot_in_degrees"])
        self.assertEqual(result["sources"], {
            "model": {"path": "kinematics/fitted.osim", "sha256": sha(self.model)},
            "mot": {"path": "kinematics/ik.mot", "sha256": sha(self.mot)},
            "trc": {"path": "pose-3d/filtered.trc", "sha256": sha(self.trc)},
        })
        self.assertTrue(any("not clinical accuracy" in x for x in result["limitations"]))

    def test_radians_mot_and_metre_trc_pass(self):
        mot = write_mot(self.project / "kinematics" / "ik_rad.mot", self.rows, in_degrees=False)
        trc = write_trc(self.project / "pose-3d" / "filtered_m.trc", self.times, self.markers, units="m")
        result = self.run_check(mot_path=mot, trc_path=trc)
        self.assertTrue(result["ok"], result["errors"])
        self.assertFalse(result["metrics"]["mot_in_degrees"])
        self.assertEqual(result["metrics"]["trc_units"], "m")

    def test_relative_paths_resolve_against_project(self):
        result = kq.validate_kinematics_stage(self.project, model_path="kinematics/fitted.osim",
                                              mot_path="kinematics/ik.mot", trc_path="pose-3d/filtered.trc")
        self.assertTrue(result["ok"], result["errors"])

    # Model / coordinate checks -------------------------------------------
    def test_mismatched_model_coordinate_names_rejected(self):
        other = build_model(self.project / "kinematics" / "other.osim", coord_names=("hip", "knee"))
        self.assert_rejected(self.run_check(model_path=other), "unknown coordinate")

    def test_mot_missing_model_coordinate_rejected(self):
        mot = write_mot(self.project / "kinematics" / "partial.mot", self.rows, names=("q1",))
        self.assert_rejected(self.run_check(mot_path=mot), "missing model coordinate")

    def test_coordinate_beyond_model_declared_range_rejected(self):
        rows = trajectories(q1_amp=1.5)          # model declares q1 in [-1.2, 1.2] rad
        markers = forward_markers(self.model, rows)
        mot = write_mot(self.project / "kinematics" / "wide.mot", rows)
        trc = write_trc(self.project / "pose-3d" / "wide.trc", self.times, markers)
        result = self.run_check(mot_path=mot, trc_path=trc)
        self.assert_rejected(result, "outside model range")
        self.assertLess(result["metrics"]["rms_marker_error_m"], 1e-5)  # residual alone would pass

    def test_unclamped_coordinate_beyond_declared_range_also_rejected(self):
        model = build_model(self.project / "kinematics" / "unclamped.osim", clamped=False)
        rows = trajectories(q2_amp=0.3)          # model declares q2 in [-0.2, 0.2] m
        markers = forward_markers(model, rows)
        mot = write_mot(self.project / "kinematics" / "slide.mot", rows)
        trc = write_trc(self.project / "pose-3d" / "slide.trc", self.times, markers)
        self.assert_rejected(self.run_check(model_path=model, mot_path=mot, trc_path=trc), "outside model range")

    def test_nonfinite_coordinate_rejected(self):
        text = Path(self.mot).read_text(encoding="utf-8").splitlines()
        cells = text[-3].split("\t")
        cells[1] = "nan"
        text[-3] = "\t".join(cells)
        Path(self.mot).write_text("\n".join(text) + "\n", encoding="utf-8")
        self.assert_rejected(self.run_check(), "finite")

    def test_mot_without_in_degrees_header_rejected(self):
        text = Path(self.mot).read_text(encoding="utf-8").replace("inDegrees=yes\n", "")
        Path(self.mot).write_text(text, encoding="utf-8")
        self.assert_rejected(self.run_check(), "inDegrees")

    def test_degrees_mislabelled_as_radians_rejected(self):
        text = Path(self.mot).read_text(encoding="utf-8").replace("inDegrees=yes", "inDegrees=no")
        Path(self.mot).write_text(text, encoding="utf-8")
        self.assertFalse(self.run_check()["ok"])
        self.assertEqual(self.run_check()["code"], REJECTED)

    # Residual checks ------------------------------------------------------
    def test_large_marker_residual_rejected(self):
        shifted = {n: [(x + 0.05, y, z) for x, y, z in pts] for n, pts in self.markers.items()}
        trc = write_trc(self.project / "pose-3d" / "shifted.trc", self.times, shifted)
        result = self.run_check(trc_path=trc)
        self.assert_rejected(result, "rms marker residual")
        self.assertGreater(result["metrics"]["rms_marker_error_m"], 0.02)

    def test_trc_units_mislabelled_rejected(self):
        trc = write_trc(self.project / "pose-3d" / "badunits.trc", self.times,
                        {n: [(x * 1000, y * 1000, z * 1000) for x, y, z in p] for n, p in self.markers.items()},
                        units="m")
        self.assert_rejected(self.run_check(trc_path=trc), "residual")

    def test_threshold_is_configurable_and_enforced(self):
        shifted = {n: [(x + 0.005, y, z) for x, y, z in pts] for n, pts in self.markers.items()}
        trc = write_trc(self.project / "pose-3d" / "small.trc", self.times, shifted)
        self.assertTrue(self.run_check(trc_path=trc)["ok"])
        self.assert_rejected(self.run_check(trc_path=trc, max_rms_marker_error_m=0.001), "rms marker residual")

    # Time checks ----------------------------------------------------------
    def test_shifted_mot_timestamps_rejected(self):
        mot = write_mot(self.project / "kinematics" / "late.mot", self.rows,
                        times=[t + 0.5 for t in self.times])
        self.assert_rejected(self.run_check(mot_path=mot), "time")

    def test_rescaled_mot_timestamps_rejected(self):
        mot = write_mot(self.project / "kinematics" / "slow.mot", self.rows,
                        times=[t * 2 for t in self.times])
        self.assert_rejected(self.run_check(mot_path=mot), "time")

    def test_non_increasing_mot_timestamps_rejected(self):
        times = list(self.times)
        times[5] = times[4]
        mot = write_mot(self.project / "kinematics" / "dup.mot", self.rows, times=times)
        self.assert_rejected(self.run_check(mot_path=mot), "strictly increase")

    def test_mot_frame_count_differs_from_trc_rejected(self):
        mot = write_mot(self.project / "kinematics" / "short.mot", self.rows[:-3])
        self.assert_rejected(self.run_check(mot_path=mot), "frame")

    # Marker identity / count checks --------------------------------------
    def test_renamed_trc_markers_rejected(self):
        renamed = {f"X{i}": pts for i, pts in enumerate(self.markers.values())}
        trc = write_trc(self.project / "pose-3d" / "renamed.trc", self.times, renamed)
        result = self.run_check(trc_path=trc)
        self.assert_rejected(result, "matched")
        self.assertEqual(result["metrics"]["matched_markers"], 0)

    def test_swapped_marker_identity_rejected(self):
        swapped = dict(self.markers)
        swapped["mA"], swapped["mC"] = self.markers["mC"], self.markers["mA"]
        trc = write_trc(self.project / "pose-3d" / "swapped.trc", self.times, swapped)
        self.assert_rejected(self.run_check(trc_path=trc), "residual")

    def test_too_few_matched_markers_rejected(self):
        two = {n: self.markers[n] for n in ("mA", "mC")}
        trc = write_trc(self.project / "pose-3d" / "two.trc", self.times, two)
        self.assert_rejected(self.run_check(trc_path=trc), "matched")

    def test_too_few_finite_markers_in_one_frame_rejected(self):
        trc = write_trc(self.project / "pose-3d" / "gap.trc", self.times, self.markers,
                        blank={(7, "mA"), (7, "mB")})
        self.assert_rejected(self.run_check(trc_path=trc), "frame 7")

    def test_explicit_min_matched_markers_enforced_and_validated(self):
        self.assert_rejected(self.run_check(min_matched_markers=5), "matched")
        self.assert_rejected(self.run_check(min_matched_markers=0), "min_matched_markers")
        self.assertTrue(self.run_check(min_matched_markers=4)["ok"])

    # Path / file checks ---------------------------------------------------
    def test_path_outside_project_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            outside = write_trc(Path(other) / "outside.trc", self.times, self.markers)
            self.assert_rejected(self.run_check(trc_path=outside), "outside project")
        self.assert_rejected(self.run_check(mot_path="../escape.mot"), "outside project")

    def test_missing_file_rejected(self):
        result = self.run_check(mot_path=self.project / "kinematics" / "absent.mot")
        self.assert_rejected(result, "missing")
        self.assertIsNone(result["sources"]["mot"]["sha256"])
        self.assertEqual(result["sources"]["model"]["sha256"], sha(self.model))

    def test_corrupt_model_rejected_without_raising(self):
        Path(self.model).write_text("<OpenSimDocument><broken", encoding="utf-8")
        self.assert_rejected(self.run_check(), "model")

    def test_opensim_import_failure_is_unavailable(self):
        with mock.patch.dict(sys.modules, {"opensim": None}):
            result = self.run_check()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], UNAVAILABLE)
        self.assertEqual(result["policy"], kq.KINEMATICS_QUALITY_POLICY)
        self.assertTrue(any("opensim" in e.lower() for e in result["errors"]))
        self.assertEqual(result["sources"]["trc"]["sha256"], sha(self.trc))


if __name__ == "__main__":
    unittest.main()
