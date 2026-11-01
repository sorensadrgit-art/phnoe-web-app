"""Exact recording-contract validation errors; behaviour preservation for numeric field reporting."""
import importlib
import unittest
from unittest import mock

from test_recording_contract import frame, header


class _Float(float):
    pass


class _Int(int):
    pass


class RecordingContractErrorFieldTests(unittest.TestCase):
    def setUp(self):
        self.contract = importlib.import_module("recording_contract")

    def assert_exact(self, call, message):
        with self.assertRaises(ValueError) as caught:
            call()
        error = caught.exception
        self.assertIs(type(error), ValueError)
        self.assertEqual(str(error), message)
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)

    def bad_point(self, joint, axis, value, *, index=0):
        frames = [frame(i + 1, i * 30) for i in range(index + 1)]
        frames[index]["landmarks"][joint][axis] = value
        return frames

    def test_landmark_number_errors_name_exact_field_and_reason(self):
        finite, ranged = "expected finite number", "outside supported range"
        for axis, value, reason in ((0, True, finite), (0, _Float(0.5), finite), (2, _Int(1), finite),
                                    (0, "0.5", finite), (1, None, finite), (0, float("nan"), finite),
                                    (2, float("inf"), finite), (2, -float("inf"), finite), (2, 10 ** 400, finite),
                                    (3, 10 ** 400, finite), (0, -0.1, ranged), (1, 1.0000001, ranged),
                                    (3, 2, ranged)):
            with self.subTest(axis=axis, value=value):
                frames = self.bad_point(3, axis, value)
                self.assert_exact(lambda frames=frames: self.contract.validate_frames(frames),
                                  f"MEASUREMENT_INVALID: frames[0].landmarks[3][{axis}]: {reason}")

    def test_frame_index_and_first_failure_order_are_preserved(self):
        self.assert_exact(lambda: self.contract.validate_frames(self.bad_point(32, 1, -1, index=1)),
                          "MEASUREMENT_INVALID: frames[1].landmarks[32][1]: outside supported range")
        frames = self.bad_point(5, 1, float("nan"))
        frames[0]["landmarks"][3][2] = True
        self.assert_exact(lambda: self.contract.validate_frames(frames),
                          "MEASUREMENT_INVALID: frames[0].landmarks[3][2]: expected finite number")
        frames = self.bad_point(3, 1, True)
        frames[0]["landmarks"][3][0] = -1
        self.assert_exact(lambda: self.contract.validate_frames(frames),
                          "MEASUREMENT_INVALID: frames[0].landmarks[3][0]: outside supported range")

    def test_point_shape_and_non_landmark_number_errors_are_unchanged(self):
        frames = [frame()]
        frames[0]["landmarks"][3] = (0.1, 0.2, 0, 0.9)
        self.assert_exact(lambda: self.contract.validate_frames(frames),
                          "MEASUREMENT_INVALID: frames[0].landmarks[3]: expected x,y,z,confidence or null")
        for key, value, message in (("sequence", True, "frames[0].sequence: expected finite integer"),
                                    ("time_ms", -1, "frames[0].time_ms: outside supported range")):
            bad = frame()
            bad[key] = value
            self.assert_exact(lambda bad=bad: self.contract.validate_frames([bad]), "MEASUREMENT_INVALID: " + message)
        for change, message in ((lambda h: h["coordinates"].update(width=0),
                                 "coordinates.width: outside supported range"),
                                (lambda h: h["protocol"].update(target_angle_degrees=181),
                                 "protocol.target_angle_degrees: outside supported range"),
                                (lambda h: h["protocol"].update(target_angle_degrees="80"),
                                 "protocol.target_angle_degrees: expected finite number")):
            bad = header()
            change(bad)
            self.assert_exact(lambda bad=bad: self.contract.validate_header(bad), "MEASUREMENT_INVALID: " + message)

    def test_valid_edges_return_the_same_list_object(self):
        frames = [frame()]
        frames[0]["landmarks"][3] = [0, 1, -5.0, 0.5]
        frames[0]["landmarks"][4] = [1.0, 0.0, 1e308, 1]
        self.assertIs(self.contract.validate_frames(frames), frames)

    def test_number_and_invalid_remain_the_only_numeric_error_route(self):
        with mock.patch.object(self.contract, "_number", wraps=self.contract._number) as number:
            self.assertEqual(self.contract.validate_frames([frame()]), [frame()])
        self.assertEqual(number.call_count, 2 + 33 * 4)
        with mock.patch.object(self.contract, "invalid", wraps=self.contract.invalid) as invalid:
            self.assert_exact(lambda: self.contract.validate_frames(self.bad_point(3, 1, 1.5)),
                              "MEASUREMENT_INVALID: frames[0].landmarks[3][1]: outside supported range")
        self.assertEqual(invalid.call_args_list, [mock.call("frames[0].landmarks[3][1]", "outside supported range")])


if __name__ == "__main__":
    unittest.main()
