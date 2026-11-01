"""Synthetic contracts only. Never process or change original recordings."""
import copy
import hashlib
import importlib.util
import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import export_motion as exporter


def trc_text(times=(2, 2.1, 2.4), units="m"):
    lines = [
        "PathFileType\t4\t(X/Y/Z)\tfactory_trial.trc",
        "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits",
        f"29.97002997002997\t30\t{len(times)}\t2\t{units}",
        "Frame#\tTime\tHip\t\t\tRHip\t\t",
        "\t\tX1\tY1\tZ1\tX2\tY2\tZ2",
    ]
    lines += [f"{i}\t{t}\t1\t2\t3\t4\t5\t6" for i, t in enumerate(times, 1)]
    return "\n".join(lines) + "\n"


def mot_text(times=(2, 2.1, 2.4), degrees="no"):
    return (f"factory_trial\nnRows={len(times)}\nnColumns=3\ninDegrees={degrees}\nendheader\n"
            "time knee_angle_r pelvis_tx\n" +
            "".join(f"{t} {math.pi / 2} 0.25\n" for t in times))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="factory_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.trc = self.write("factory_trial.trc", trc_text())
        self.mot = self.write("factory_trial.mot", mot_text())

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def manifest(self, with_mot=False, *, session_id="factory_session"):
        roles = ("cam01_intrinsics", "cam02_intrinsics", "cam01_board",
                 "cam02_board", "cam01_trial", "cam02_trial")
        captures = {}
        for role in roles:
            path = self.write("factory_" + role + ".mp4", role)
            captures[role] = {"path": path.name, "sha256": digest(path)}
        self.write("Config.toml", "[project]\n")
        session = {"schema": "kinelab.session.v1", "session_id": session_id,
                   "kind": "real", "subject_count": 1, "camera_ids": ["cam01", "cam02"],
                   "created_at": "2026-10-26T12:00:00+00:00", "captures": captures}
        self.write("session.json", json.dumps(session))
        from native_evidence_fixture import complete_native_fixture
        manifest, trc, mot = complete_native_fixture(self.root, self.trc.read_text(), self.mot.read_text(),
            through="kinematics" if with_mot else "filtering")
        self.trc, self.mot = trc, mot if with_mot else self.mot
        return manifest

    def test_legacy_and_millimeters_preserve_actual_times(self):
        self.trc.write_text(trc_text((2, 2.000000001, 2.4), "mm"))
        data = exporter.motion(self.trc)
        self.assertEqual(data["schema"], "kinelab.motion.v1")
        self.assertNotIn("provenance", data)
        self.assertEqual(data["frames"][0]["xyz"][0], [0.001, 0.002, 0.003])
        self.assertEqual(data["frames"][1]["t"], 2.000000001)
        self.assertEqual(data["bones"], [[0, 1]])

    def test_omitted_native_prerequisites_cannot_produce_verified_export(self):
        manifest = self.manifest()
        run = json.loads(manifest.read_text())
        run["stages"] = [s for s in run["stages"] if s["name"] in ("calibration", "filtering")]
        manifest.write_text(json.dumps(run))
        with self.assertRaisesRegex(ValueError, "ARTIFACT_MISMATCH"):
            exporter.motion(self.trc, run_manifest=manifest)

    def test_served_export_must_match_bound_source_values(self):
        manifest = self.manifest()
        path = self.root / "exports/fixture.motion.json"
        path.parent.mkdir()
        data = exporter.motion(self.trc, run_manifest=manifest)
        path.write_text(json.dumps(data))
        self.assertTrue(callable(getattr(exporter, "load_verified_motion", None)), "verified motion reader required")
        self.assertEqual(exporter.load_verified_motion(self.root, path), data)
        data["frames"][0]["xyz"][0][0] += 1
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "EVIDENCE_INVALID"):
            exporter.load_verified_motion(self.root, path)

    def test_trc_rejects_malformed_series_and_headers(self):
        good = trc_text()
        bad = [
            trc_text((2, 1, 3)), trc_text((2, 2, 3)), trc_text((2, "nan", 3)),
            good.replace("\t3\t2\tm", "\t4\t2\tm"),
            good.replace("29.97002997002997", "0"),
            good.replace("\t30\t3\t2", "\tnan\t3\t2"),
            good.replace("\t2\tm", "\t2\tcm"),
            good.replace("RHip", "Hip"),
            good.replace("X2\tY2\tZ2", "X2\tZ2\tY2"),
            good.replace("1\t2\t3\t4\t5\t6", "1\t2\t3\t4\t5"),
            good.replace("1\t2\t3\t4\t5\t6", "1\t2\t3\t4\t5\t6\t7"),
            good.replace("\t1\t2\t3\t", "\tnan\t2\t3\t"),
            good.replace("\t1\t2\t3\t", "\t\t2\t3\t"),
            good.replace("2\t2.1\t", "1\t2.1\t"),
        ]
        for text in bad:
            with self.subTest(text=text):
                self.trc.write_text(text)
                with self.assertRaisesRegex(ValueError, "TRC_INVALID"):
                    exporter.parse_trc(self.trc)

    def test_trc_blank_marker_is_explicitly_missing(self):
        self.trc.write_text(trc_text().replace("\t1\t2\t3\t", "\t\t\t\t"))
        self.assertIsNone(exporter.parse_trc(self.trc)[1][0]["xyz"][0])

    def test_mot_distinguishes_lengths_and_angles_without_converting_source(self):
        kin = exporter.parse_mot(self.mot)
        self.assertFalse(kin["inDegrees"])
        self.assertEqual(kin["columnTypes"], {"knee_angle_r": "angular", "pelvis_tx": "translation"})
        self.assertAlmostEqual(kin["rows"][0][1], math.pi / 2)
        self.assertEqual(kin["rows"][0][2], 0.25)

    def test_native_model_coordinates_have_explicit_units(self):
        fixture = json.loads((PROJECT / "tests/factory_opensim_units.json").read_text())
        names = fixture["angular"] + fixture["nativeRadians"] + fixture["translations"]
        self.mot.write_text("factory\nversion=1\ninDegrees=yes\nendheader\ntime " +
                            " ".join(names) + "\n2 " + " ".join(["1.5"] * len(names)) + "\n")
        kin = exporter.parse_mot(self.mot)
        for name in fixture["angular"]:
            self.assertEqual(kin["columnUnits"][name], "deg")
        for name in fixture["nativeRadians"]:
            self.assertEqual(kin["columnUnits"][name], "rad")
        for name in fixture["translations"]:
            self.assertEqual(kin["columnTypes"][name], "translation")
            self.assertEqual(kin["columnUnits"][name], "m")

    def test_native_opensim_software_unit_round_trip(self):
        import opensim
        root = PROJECT / ".venv/Lib/site-packages/Pose2Sim/OpenSim_Setup"
        fixture = json.loads((PROJECT / "tests/factory_opensim_units.json").read_text())
        for filename in ("Model_Pose2Sim_simple.osim", "Model_Pose2Sim_muscles_flex.osim"):
            model = opensim.Model(str(root / filename))
            model.initSystem()
            names = [c.getName() for c in model.getCoordinateSet()]
            self.mot.write_text("factory\nversion=1\nnRows=1\nnColumns=" + str(len(names) + 1) +
                                "\ninDegrees=no\nendheader\ntime " + " ".join(names) +
                                "\n2 " + " ".join([str(math.pi / 2)] * len(names)) + "\n")
            parsed = exporter.parse_mot(self.mot)
            storage = opensim.Storage(str(self.mot))
            model.getSimbodyEngine().convertRadiansToDegrees(storage)
            converted = storage.getStateVector(0).getData()
            for i, name in enumerate(names):
                expected = math.pi / 2 if name in fixture["translations"] + fixture["nativeRadians"] else 90
                self.assertAlmostEqual(converted.get(i), expected)
                self.assertAlmostEqual(parsed["rows"][0][i + 1], math.pi / 2)
            degrees_path = self.root / "factory_degrees.mot"
            opensim.Storage.printResult(storage, "factory_degrees", str(self.root), -1, ".mot")
            degrees = exporter.parse_mot(degrees_path)
            self.assertTrue(degrees["inDegrees"])
            self.assertAlmostEqual(degrees["rows"][0][names.index("knee_angle_r") + 1], 90)
            model.getSimbodyEngine().convertDegreesToRadians(storage)
            for i in range(len(names)):
                self.assertAlmostEqual(storage.getStateVector(0).getData().get(i), math.pi / 2)

    def test_mot_rejects_invalid_counts_units_columns_and_times(self):
        good = mot_text()
        for text in [mot_text((2, 1, 3)), mot_text((2, 2, 3)), mot_text((2, "nan", 3)),
                     good.replace("nRows=3", "nRows=4"), good.replace("nColumns=3", "nColumns=4"),
                     good.replace("inDegrees=no", "inDegrees=maybe"),
                     good.replace("pelvis_tx", "knee_angle_r"),
                     good.replace("pelvis_tx", "unknown_coordinate"),
                     good.replace("0.25", "inf"), good.replace("0.25", "0.25 1")]:
            with self.subTest(text=text):
                self.mot.write_text(text)
                with self.assertRaisesRegex(ValueError, "MOT_INVALID"):
                    exporter.parse_mot(self.mot)

    def test_distant_or_gapped_mot_is_rejected(self):
        self.trc.write_text(trc_text((2, 2.1, 2.2, 2.4)))
        for times in [(20, 20.1, 20.4), (2, 20), (2, 2.4)]:
            with self.subTest(times=times):
                self.mot.write_text(mot_text(times))
                with self.assertRaisesRegex(ValueError, "MOT_INVALID"):
                    exporter.motion(self.trc, self.mot)

    def test_mot_exactly_one_trc_interval_away_is_allowed(self):
        self.mot.write_text(mot_text((2, 2.4)))
        self.assertIsNotNone(exporter.motion(self.trc, self.mot)["kinematics"])

    def test_v2_binds_exact_session_config_and_artifacts(self):
        manifest = self.manifest(with_mot=True)
        data = exporter.motion(self.trc, self.mot, run_manifest=manifest)
        self.assertEqual(data["schema"], "kinelab.motion.v2")
        self.assertEqual(data["sessionId"], "factory_session")
        self.assertEqual(data["kind"], "real")
        self.assertEqual(data["provenance"]["runManifestSha256"], digest(manifest))
        self.assertEqual(data["provenance"]["trcSha256"], digest(self.trc))
        self.assertEqual(data["provenance"]["motSha256"], digest(self.mot))
        self.assertEqual(data["quality"], {"status": "passed", "mode": "kinematics"})
        self.assertEqual(data["time"], {"unit": "s", "origin": "synchronized_trial_start"})

    def test_v2_marker_only_is_explicit_and_no_provenance_is_fabricated(self):
        manifest = self.manifest()
        data = exporter.motion(self.trc, run_manifest=manifest)
        self.assertIsNone(data["provenance"]["motSha256"])
        self.assertEqual(data["quality"]["mode"], "marker-only")
        del data["provenance"]["calibrationSha256"]
        with self.assertRaises(ValueError):
            exporter.validate_motion(data)

    def test_v2_accepts_the_shared_safe_session_name_contract(self):
        manifest = self.manifest(session_id="factory.session-01")
        self.assertEqual(exporter.motion(self.trc, run_manifest=manifest)["sessionId"], "factory.session-01")

    def test_v2_rejects_stale_mismatched_unpassed_or_unbound_files(self):
        manifest = self.manifest()
        good = json.loads(manifest.read_text())
        mutations = [
            lambda r: r.update(session_id="other"),
            lambda r: r.update(config_sha256="0" * 64),
            lambda r: r["inputs"].update(cam01_trial="0" * 64),
            lambda r: r["stages"][1].update(status="failed"),
            lambda r: r["stages"][1]["artifacts"][0].update(sha256="0" * 64),
            lambda r: r["stages"][1]["artifacts"][0].update(path="../factory_trial.trc"),
            lambda r: r.pop("coordinateSystem"),
        ]
        for mutate in mutations:
            run = copy.deepcopy(good)
            mutate(run)
            manifest.write_text(json.dumps(run))
            with self.subTest(run=run), self.assertRaises(ValueError):
                exporter.motion(self.trc, run_manifest=manifest)
        manifest.write_text(json.dumps(good))
        self.trc.write_text(trc_text((2, 2.2, 2.4)))
        with self.assertRaisesRegex(ValueError, "ARTIFACT_MISMATCH"):
            exporter.motion(self.trc, run_manifest=manifest)

    def test_cli_manifest_never_discovers_unbound_latest_files(self):
        manifest = self.manifest()
        out = self.root / "factory_out.json"
        result = subprocess.run([sys.executable, "-B", str(PROJECT / "export_motion.py"),
                                 "--project", str(self.root), "--run-manifest", str(manifest),
                                 "--out", str(out)], capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(out.exists())
        # Keep every lookup inside this generated owned temporary root.
        unindexed_project = self.root / "unindexed-session"
        unindexed_project.mkdir()
        result = subprocess.run([sys.executable, "-B", str(PROJECT / "export_motion.py"),
                                 "--project", str(unindexed_project), "--data-root", str(self.root),
                                 "--trc", str(self.trc), "--no-mot", "--run-manifest", str(manifest),
                                 "--out", str(out)], capture_output=True, text=True, check=False)
        # Native-v2 publication needs an existing indexed local audit context.
        # Genuine indexed subprocess success is covered by test_cli_motion_export_audit.
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EXPORT_INDEX_REQUIRED:", result.stderr)
        self.assertFalse(out.exists())
        self.assertFalse((self.root / ".kinelab_index.db").exists())

    def test_json_boundary_rejects_bad_shapes_and_nonfinite_values(self):
        good = exporter.motion(self.trc, self.mot)
        changes = [
            lambda d: d.update(fps=0), lambda d: d.update(units="mm"),
            lambda d: d.update(coordinateSystem="unknown"),
            lambda d: d.update(markers=["Hip", "Hip"]),
            lambda d: d.update(bones=[[0, 2]]), lambda d: d.update(bones=[[0, True]]),
            lambda d: d["frames"][0].update(xyz=[[1, 2, 3]]),
            lambda d: d["frames"][0]["xyz"].__setitem__(0, [1, math.inf, 3]),
            lambda d: d["frames"][1].update(t=2),
            lambda d: d["kinematics"].update(inDegrees="no"),
            lambda d: d["kinematics"].update(timeTolerance=-1),
            lambda d: d["kinematics"].update(columnUnits={"knee_angle_r": "m", "pelvis_tx": "m"}),
            lambda d: d["kinematics"].update(columnTypes={"knee_angle_r": "translation", "pelvis_tx": "translation"}),
        ]
        for change in changes:
            data = copy.deepcopy(good)
            change(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                exporter.validate_motion(data)

    def test_existing_demo_remains_readable(self):
        demo = exporter.load_json(PROJECT / "viewer/public/motion/demo.motion.json")
        self.assertEqual(len(exporter.validate_motion(demo)["frames"]), 97)
        self.trc.write_text(trc_text(tuple(2 + i / 30 for i in range(97))))
        parsed = exporter.motion(self.trc)
        self.assertEqual(len(parsed["frames"]), 97)


class BlenderTests(unittest.TestCase):
    setUp = ExportTests.setUp
    write = ExportTests.write
    # Kept in this owned test file; the adapter's pure helpers import without bpy.
    def test_blender_rational_timing_and_basis(self):
        spec = importlib.util.spec_from_file_location("factory_blender", PROJECT / "blender_import.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        data = exporter.motion(self.trc)
        fps, base, keys = adapter.animation_timing(data)
        self.assertEqual((fps, base), (30000, 1001))
        self.assertAlmostEqual(keys[0], 1)
        self.assertAlmostEqual(keys[1], 3.997002997003)
        self.assertAlmostEqual(keys[-1], 12.988011988012)
        self.assertEqual(adapter.basis_coordinates([1, 2, 3]), (1, -3, 2))
        self.assertEqual(adapter.basis_coordinates([1, 0, 0]), (1, 0, 0))
        self.assertEqual(adapter.basis_coordinates([0, 1, 0]), (0, 0, 1))
        self.assertEqual(adapter.basis_coordinates([0, 0, 1]), (0, -1, 0))
        data["fps"] = 1e-20
        with self.assertRaisesRegex(ValueError, "MOTION_INVALID"):
            adapter.animation_timing(data)

    def test_real_blender_accepts_v2_and_rejects_bad_json_before_writing(self):
        blender = PROJECT / "tools/blender-4.5.15-windows-x64/blender.exe"
        if not blender.is_file():
            self.skipTest("Installed Blender executable unavailable; no v2 Blender export verified")
        manifest = ExportTests.manifest(self)
        data = exporter.motion(self.trc, run_manifest=manifest)
        inp = self.write("factory_v2.json", json.dumps(data))
        blend, glb = self.root / "factory_v2.blend", self.root / "factory_v2.glb"
        command = [str(blender), "-b", "--python-exit-code", "1", "--python",
                   str(PROJECT / "blender_import.py"), "--", str(inp), str(blend), str(glb)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(blend.is_file() and glb.is_file())
        inp = self.write("factory_bad.json", json.dumps({**data, "bones": [[0, 20]]}))
        bad_blend, bad_glb = self.root / "factory_bad.blend", self.root / "factory_bad.glb"
        command[-3:] = [str(inp), str(bad_blend), str(bad_glb)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MOTION_INVALID", result.stdout + result.stderr)
        self.assertFalse(bad_blend.exists() or bad_glb.exists())

    def test_real_blender_exports_timestamps_and_refuses_existing_destinations(self):
        blender = PROJECT / "tools/blender-4.5.15-windows-x64/blender.exe"
        if not blender.is_file():
            self.skipTest("Installed Blender executable unavailable; no Blender export verified")
        self.trc.write_text(trc_text((2, 2.137, 2.4)))
        data = exporter.motion(self.trc)
        data["frames"][1]["xyz"][0] = [2, 2, 3]
        data["frames"][2]["xyz"][0] = [3, 2, 3]
        data["frames"][1]["xyz"][1] = None
        inp = self.write("factory_motion.json", json.dumps(data))
        blend, glb = self.root / "factory_motion.blend", self.root / "factory_motion.glb"
        command = [str(blender), "-b", "--python-exit-code", "1", "--python",
                   str(PROJECT / "blender_import.py"), "--", str(inp), str(blend), str(glb)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(blend.is_file())
        inspect = subprocess.run([str(blender), "-b", str(blend), "--python-exit-code", "1",
                                  "--python-expr",
                                  ("import bpy; s=bpy.context.scene; "
                                   "assert (s.render.fps,s.render.fps_base)==(30000,1001.0); "
                                   "assert list(s['kinelab_source_times_s'])==[2.0,2.137,2.4]; "
                                   "assert tuple(bpy.data.objects['Joint | Hip'].location)==(1.0,-3.0,2.0); "
                                   "keys=bpy.data.objects['Joint | Hip'].animation_data.action.fcurves[0].keyframe_points; "
                                   "assert abs(keys[1].co.x-5.105894105894)<1e-5; "
                                   "assert abs(keys[-1].co.x-12.988011988012)<1e-5; "
                                   "s.frame_set(2); assert tuple(bpy.data.objects['Joint | RHip'].location)==(4.0,-6.0,5.0); "
                                   "s.frame_set(6); assert tuple(bpy.data.objects['Joint | RHip'].scale)==(0.0,0.0,0.0); "
                                   "print('FACTORY_BLEND_VERIFIED')")],
                                 capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(inspect.returncode, 0, inspect.stdout + inspect.stderr)
        self.assertIn("FACTORY_BLEND_VERIFIED", inspect.stdout)
        raw = glb.read_bytes()
        size = struct.unpack_from("<I", raw, 12)[0]
        doc = json.loads(raw[20:20 + size])
        accessors = doc["accessors"]
        samplers = doc["animations"][0]["samplers"]
        time_accessors = [accessors[s["input"]] for s in samplers]
        self.assertTrue(all(abs(a["max"][0] - 0.4) < 1e-5 and abs(a["min"][0]) < 1e-5 for a in time_accessors), time_accessors)
        binary_start = 20 + size + 8
        def values(index, components):
            accessor = accessors[index]
            view = doc["bufferViews"][accessor["bufferView"]]
            offset = binary_start + view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            stride = view.get("byteStride", components * 4)
            return [struct.unpack_from("<" + "f" * components, raw, offset + i * stride)
                    for i in range(accessor["count"])]
        hip = next(i for i, node in enumerate(doc["nodes"]) if node.get("name") == "Joint | Hip")
        for animation in doc["animations"]:
            for channel in animation["channels"]:
                if channel["target"] == {"node": hip, "path": "translation"}:
                    sampler = animation["samplers"][channel["sampler"]]
                    for got, want in zip(values(sampler["input"], 1), [0, .137, .4]):
                        self.assertAlmostEqual(got[0], want, places=5)
                    self.assertEqual(values(sampler["output"], 3), [(1, 2, 3), (2, 2, 3), (3, 2, 3)])
        before = (digest(blend), digest(glb))
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OUTPUT_EXISTS", result.stdout + result.stderr)
        self.assertEqual((digest(blend), digest(glb)), before)


if __name__ == "__main__":
    unittest.main()
