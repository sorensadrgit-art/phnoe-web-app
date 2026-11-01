"""Ephemeral image inference: generated pixels only, no camera or source session."""
import base64
import tempfile
import threading
import time
import unittest
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image

from pose_inference import PoseInference


def request(**changes):
    ok, encoded = cv2.imencode('.jpg', np.full((240, 320, 3), 240, np.uint8))
    assert ok
    return dict(schema_version=1, operation_id=str(uuid4()), sequence=1,
                captured_at_ms=int(time.time() * 1000), source='TEST_IMAGE',
                jpeg_base64=base64.b64encode(encoded).decode(), **changes)


class PoseInferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = PoseInference(Path(self.tmp.name))
        self.boxes = np.array([[10., 10., 300., 230.]])
        self.points = np.full((1, 17, 2), 100.)
        self.scores = np.full((1, 17), .9)
        self.detector = lambda image: self.boxes
        self.pose = lambda image, boxes: (self.points, self.scores)
        self.loader = patch.object(self.engine, '_load', return_value=(self.detector, self.pose))
        self.loader.start()

    def tearDown(self):
        self.loader.stop()
        self.tmp.cleanup()

    def test_maps_only_supported_confident_points_without_depth_or_persistence(self):
        payload = request(); result = self.engine.infer(payload)
        self.assertEqual(result['status'], 'AVAILABLE')
        self.assertEqual(result['operation_id'], payload['operation_id'])
        self.assertEqual(result['sequence'], 1)
        self.assertEqual((result['width'], result['height']), (320, 240))
        self.assertEqual(len(result['image_sha256']), 64)
        self.assertEqual(sum(p is not None for p in result['landmarks']), 17)
        self.assertEqual(result['landmarks'][11], {'x': 100/320, 'y': 100/240, 'z': None, 'visibility': .9})
        self.assertIsNone(result['landmarks'][31])
        self.assertFalse(result['clinical_accuracy_verified'])
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_no_person_and_multiple_person_never_call_full_image_pose_fallback(self):
        for boxes, reason in [(np.empty((0, 4)), 'NO_PERSON'), (np.ones((2, 4)), 'MULTIPLE_PEOPLE')]:
            with self.subTest(reason=reason), patch.object(self.engine, '_load', return_value=(lambda image, _boxes=boxes: _boxes, lambda *a: self.fail('pose fallback'))):
                result = self.engine.infer(request())
                self.assertEqual(result['status'], 'UNAVAILABLE')
                self.assertEqual(result['reason'], reason)
                self.assertIsNone(result['landmarks'])

    def test_occluded_nonfinite_and_outside_points_are_missing(self):
        self.scores[0, 5] = .1
        self.points[0, 6, 0] = np.nan
        self.points[0, 13, 1] = 300
        result = self.engine.infer(request())
        for index in [11, 12, 25]:
            self.assertIsNone(result['landmarks'][index])
        self.assertEqual(result['visible_landmarks'], 14)

    def test_rejects_invalid_envelopes_and_images_before_loading_models(self):
        cases = [{'sequence': True}, {'sequence': 0}, {'operation_id': '../x'},
                 {'schema_version': 2}, {'source': 'MEASURED'}, {'captured_at_ms': 0},
                 {'captured_at_ms': float('nan')}, {'jpeg_base64': 'a'*70000},
                 {'jpeg_base64': 'not image'}, {'extra': 'unknown'}]
        for changes in cases:
            payload = request(); payload.update(changes)
            with (self.subTest(changes=changes.keys()),
                    patch.object(self.engine, '_load', side_effect=AssertionError('must not load')),
                    self.assertRaises(ValueError)):
                self.engine.infer(payload)

    def test_rejects_oversize_or_non_jpeg_dimensions(self):
        for image, ext in [(np.zeros((480, 641, 3), np.uint8), '.jpg'), (np.zeros((2, 2, 3), np.uint8), '.jpg'), (np.zeros((240, 320, 3), np.uint8), '.png')]:
            payload = request(); payload['jpeg_base64'] = base64.b64encode(cv2.imencode(ext, image)[1]).decode()
            with self.assertRaises(ValueError): self.engine.infer(payload)

    def test_compressed_oversize_headers_are_input_errors_before_decode_or_models(self):
        for dimension in (65535, 10000):
            with self.subTest(dimension=dimension):
                payload = request()
                data = bytearray(base64.b64decode(payload['jpeg_base64']))
                start_of_frame = data.index(b'\xff\xc0')
                data[start_of_frame + 5:start_of_frame + 9] = dimension.to_bytes(2, 'big') * 2
                payload['jpeg_base64'] = base64.b64encode(data).decode()
                self.assertLess(len(payload['jpeg_base64']), 60000)
                with warnings.catch_warnings(), \
                        patch('cv2.imdecode', side_effect=AssertionError('must not decode')), \
                        patch.object(self.engine, '_load', side_effect=AssertionError('must not load')):
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with self.assertRaisesRegex(ValueError, 'POSE_INPUT_INVALID: bounded JPEG required'):
                        self.engine.infer(payload)

    def test_old_sequence_and_stale_completion_cannot_become_current(self):
        payload = request(); self.engine.infer(payload)
        with self.assertRaises(ValueError): self.engine.infer(payload)
        with patch('pose_inference.time.time', side_effect=[payload['captured_at_ms']/1000, payload['captured_at_ms']/1000 + 5]):
            payload['sequence'] = 2
            self.assertEqual(self.engine.infer(payload)['reason'], 'STALE_FRAME')

    def test_missing_models_fail_closed_without_network(self):
        self.loader.stop()
        with patch('urllib.request.urlopen', side_effect=AssertionError('no download')):
            result = self.engine.infer(request())
        self.assertEqual(result['reason'], 'MODELS_UNAVAILABLE')

    def test_corrupt_model_is_never_loaded(self):
        self.loader.stop()
        for name in ['detector.onnx', 'pose.onnx']:
            (Path(self.tmp.name)/name).write_bytes(b'bad')
        result = self.engine.infer(request())
        self.assertEqual(result['reason'], 'MODEL_INTEGRITY_FAILED')

    def test_bad_model_output_fails_closed(self):
        self.points = np.zeros((1, 18, 2))
        self.assertEqual(self.engine.infer(request())['reason'], 'MODEL_OUTPUT_INVALID')

    def test_busy_request_is_bounded(self):
        started = threading.Event(); release = threading.Event()
        def detector(image):
            started.set(); release.wait(3); return self.boxes
        with patch.object(self.engine, '_load', return_value=(detector, self.pose)), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.engine.infer, request()); self.assertTrue(started.wait(2))
            self.assertEqual(self.engine.infer(request())['reason'], 'INFERENCE_BUSY')
            release.set(); self.assertEqual(first.result()['status'], 'AVAILABLE')

