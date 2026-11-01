"""Raw synthetic frame contract: no source promotion or invented measurements."""
import hashlib
import importlib
import importlib.util
import json
import unittest
from pathlib import Path


def header():
    from recording_contract import SYNTHETIC_MODEL_SHA256
    return {"schema": "kinelab.recording.v1", "session_id": "synthetic-fixture-recording",
            "operation_id": "1" * 32, "subject_id": "synthetic-subject", "operator_id": "synthetic-operator",
            "source": {"kind": "synthetic", "capture_id": "2" * 32, "model_id": "kinelab-synthetic-33",
                       "model_version": "1", "model_sha256": SYNTHETIC_MODEL_SHA256},
            "protocol": {"id": "squat-research-v1", "version": 1, "exercise": "squat", "side": "bilateral",
                         "target_angle_degrees": 80, "target_hold_ms": None},
            "coordinates": {"space": "image-normalized", "units": "normalized", "z_units": "relative",
                            "width": 640, "height": 480, "mirrored": False}}


def frame(sequence=1, time_ms=0):
    return {"sequence": sequence, "time_ms": time_ms, "valid": True, "reasons": [],
            "landmarks": [[.1 + (i % 5) * .1, .1 + (i // 5) * .1, 0, .9] for i in range(33)]}


class RecordingContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("recording_contract"), "versioned recording contract is required")
        self.contract = importlib.import_module("recording_contract")

    def test_generator_source_is_pinned_and_unregistered_hash_is_refused(self):
        source = Path(__file__).resolve().parents[1] / "viewer/src/syntheticPose.js"
        self.assertTrue(source.is_file(), "standalone pinned synthetic generator required")
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), self.contract.SYNTHETIC_MODEL_SHA256)
        bad = header(); bad["source"]["model_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "model_sha256"):
            self.contract.validate_header(bad)

    def test_header_and_frames_round_trip_without_modification(self):
        original = header()
        frames = [frame(), frame(2, 33.333)]
        self.assertEqual(self.contract.validate_header(original), original)
        self.assertEqual(self.contract.validate_frames(frames), frames)
        self.assertEqual(json.loads(self.contract.canonical_json(original)), original)

    def test_source_namespace_and_future_versions_fail_closed(self):
        for change in (lambda h: h.update(schema="kinelab.recording.v99"),
                       lambda h: h.update(session_id="measured-subject"),
                       lambda h: h["source"].update(kind="camera"),
                       lambda h: h["source"].update(model_id="unknown"),
                       lambda h: h["source"].update(model_version="99"),
                       lambda h: h["source"].update(model_sha256="bad"),
                       lambda h: h["coordinates"].update(units="m"),
                       lambda h: h["coordinates"].update(width=True),
                       lambda h: h["protocol"].update(exercise="unknown"),
                       lambda h: h.update(patient_name="must not be accepted")):
            with self.subTest(change=change):
                bad = header(); change(bad)
                with self.assertRaises(ValueError):
                    self.contract.validate_header(bad)

    def test_nonfinite_wrong_shape_and_contradictory_validity_rejected(self):
        for change in (lambda f: f.update(time_ms=float("nan")), lambda f: f.update(time_ms=-1),
                       lambda f: f.update(sequence=True), lambda f: f.update(valid="false"),
                       lambda f: f.update(landmarks=[]), lambda f: f["landmarks"][0].__setitem__(0, float("inf")),
                       lambda f: f["landmarks"][0].__setitem__(3, 2),
                       lambda f: f.update(valid=True, reasons=["MISSING"]),
                       lambda f: f.update(valid=False, reasons=[]),
                       lambda f: f.update(summary={"valid_frames": 99})):
            bad = frame(); change(bad)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.contract.validate_frames([bad])

    def test_missing_observation_is_explicit_not_zero_filled(self):
        missing = {"sequence": 1, "time_ms": 0, "valid": False,
                   "reasons": ["NO_POSE"], "landmarks": None}
        self.assertEqual(self.contract.validate_frames([missing]), [missing])

    def test_oversized_integer_is_a_validation_error(self):
        bad = frame(); bad["time_ms"] = 10 ** 400
        with self.assertRaisesRegex(ValueError, "MEASUREMENT_INVALID"):
            self.contract.validate_frames([bad])
        bad = frame(); bad["landmarks"][0][2] = 10 ** 400
        with self.assertRaisesRegex(ValueError, "MEASUREMENT_INVALID"):
            self.contract.validate_frames([bad])

    def test_chunks_require_contiguous_sequences_and_monotonic_time(self):
        for frames in ([frame(), frame(3, 30)], [frame(), frame(1, 30)],
                       [frame(1, 30), frame(2, 30)], [frame(1, 30), frame(2, 10)],
                       [frame(i + 1, i * 30) for i in range(17)], []):
            with self.subTest(frames=frames), self.assertRaises(ValueError):
                self.contract.validate_frames(frames)


if __name__ == "__main__":
    unittest.main()
