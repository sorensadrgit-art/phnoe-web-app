"""Local, ephemeral 2D inference. No camera access, downloads, or persistence."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
import time
from collections import OrderedDict
from pathlib import Path
from uuid import UUID

MANIFEST = Path(__file__).parent / 'models' / 'pose-models.json'
MAX_AGE_MS = 1500
MIN_CONFIDENCE = .6  # Display filter only; not a calibrated probability of anatomical accuracy.
COCO_TO_DISPLAY = (0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)


class PoseInference:
    def __init__(self, model_dir: Path):
        self.model_dir = Path(model_dir)
        self.models = json.loads(MANIFEST.read_text(encoding='utf-8'))
        self._pipeline = None
        self._lock = threading.Lock()
        self._sequences: OrderedDict[str, int] = OrderedDict()

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline
        paths = []
        for model in self.models['models']:
            path = self.model_dir / model['filename']
            if not path.is_file():
                raise FileNotFoundError('MODELS_UNAVAILABLE')
            if any(p.is_symlink() or p.is_junction() for p in [path, *path.parents]):
                raise ValueError('MODEL_INTEGRITY_FAILED')
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if (path.stat().st_size != model['bytes'] or
                    digest != model['sha256']):
                raise ValueError('MODEL_INTEGRITY_FAILED')
            paths.append(path)
        # RTMLib downloads when a path is absent; verified files are mandatory above.
        from rtmlib import YOLOX, RTMPose
        detector = YOLOX(str(paths[0]), model_input_size=(416, 416), score_thr=.7,
                         backend='onnxruntime', device='cpu')
        pose = RTMPose(str(paths[1]), model_input_size=(192, 256),
                       backend='onnxruntime', device='cpu')
        self._pipeline = detector, pose
        return self._pipeline

    def infer(self, payload: dict) -> dict:
        keys = {'schema_version', 'operation_id', 'sequence', 'captured_at_ms', 'source', 'jpeg_base64'}
        if not isinstance(payload, dict) or set(payload) != keys:
            raise ValueError('POSE_INPUT_INVALID: envelope')
        try:
            operation = UUID(payload['operation_id'])
            if operation.version != 4 or str(operation) != payload['operation_id']:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError('POSE_INPUT_INVALID: operation identity') from None
        sequence, captured = payload['sequence'], payload['captured_at_ms']
        if (type(payload['schema_version']) is not int or payload['schema_version'] != 1 or
                type(sequence) is not int or not 1 <= sequence < 2**31 or
                type(captured) is not int or not -250 <= time.time()*1000 - captured <= MAX_AGE_MS or
                payload['source'] not in ('CAMERA_FRAME', 'TEST_IMAGE')):
            raise ValueError('POSE_INPUT_INVALID: version, sequence, timestamp or source')
        encoded = payload['jpeg_base64']
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= 60000:
            raise ValueError('POSE_INPUT_INVALID: JPEG size')
        from PIL import Image
        try:
            data = base64.b64decode(encoded, validate=True)
            with Image.open(io.BytesIO(data)) as header:
                width, height = header.size
                if header.format != 'JPEG' or not (32 <= width <= 640 and 32 <= height <= 640):
                    raise ValueError()
        except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ValueError('POSE_INPUT_INVALID: bounded JPEG required') from None
        result = {'schema_version': 1, 'operation_id': str(operation), 'sequence': sequence,
                  'captured_at_ms': captured, 'source': payload['source'], 'status': 'UNAVAILABLE',
                  'reason': None, 'landmarks': None, 'width': width, 'height': height,
                  'image_sha256': hashlib.sha256(data).hexdigest(),
                  'model_id': self.models['id'], 'model_hashes': {m['filename']: m['sha256'] for m in self.models['models']},
                  'coordinate_basis': 'NORMALIZED_IMAGE_PLANE_2D', 'mirrored': False,
                  'min_confidence': MIN_CONFIDENCE, 'visible_landmarks': 0, 'inference_ms': 0,
                  'clinical_accuracy_verified': False, 'persistence': 'DISABLED'}
        if not self._lock.acquire(blocking=False):
            return {**result, 'reason': 'INFERENCE_BUSY'}
        started = time.monotonic()
        try:
            if sequence <= self._sequences.get(str(operation), 0):
                raise ValueError('POSE_INPUT_INVALID: old or duplicate sequence')
            self._sequences[str(operation)] = sequence
            self._sequences.move_to_end(str(operation))
            while len(self._sequences) > 128:
                self._sequences.popitem(last=False)
            try:
                detector, pose = self._load()
            except FileNotFoundError:
                return {**result, 'reason': 'MODELS_UNAVAILABLE'}
            except ValueError:
                return {**result, 'reason': 'MODEL_INTEGRITY_FAILED'}
            except (ImportError, RuntimeError, OSError):
                return {**result, 'reason': 'MODEL_RUNTIME_UNAVAILABLE'}
            import cv2
            import numpy as np
            frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None or frame.shape[:2] != (height, width):
                raise ValueError('POSE_INPUT_INVALID: JPEG decode')
            try:
                boxes = np.asarray(detector(frame))
                if boxes.ndim != 2 or boxes.shape[1] != 4 or not np.isfinite(boxes).all():
                    return {**result, 'reason': 'MODEL_OUTPUT_INVALID'}
                if len(boxes) != 1:
                    return {**result, 'reason': 'NO_PERSON' if len(boxes) == 0 else 'MULTIPLE_PEOPLE'}
                # Never invoke RTMPose's whole-image fallback when detection is empty.
                x1, y1, x2, y2 = boxes[0]
                if x2 <= x1 or y2 <= y1 or x2 <= 0 or y2 <= 0 or x1 >= width or y1 >= height:
                    return {**result, 'reason': 'MODEL_OUTPUT_INVALID'}
                points, scores = (np.asarray(v) for v in pose(frame, boxes))
                if points.shape != (1, 17, 2) or scores.shape != (1, 17):
                    return {**result, 'reason': 'MODEL_OUTPUT_INVALID'}
                landmarks: list[dict[str, float | None] | None] = [None] * 33
                for index, display in enumerate(COCO_TO_DISPLAY):
                    x, y = points[0, index]; confidence = float(scores[0, index])
                    if (np.isfinite([x, y, confidence]).all() and 0 <= x < width and 0 <= y < height
                            and MIN_CONFIDENCE <= confidence <= 1):
                        landmarks[display] = {'x': float(x/width), 'y': float(y/height), 'z': None,
                                              'visibility': confidence}
            except Exception:  # noqa: BLE001  native model inference can raise any exception type; fail-closed as MODEL_RUNTIME_ERROR
                return {**result, 'reason': 'MODEL_RUNTIME_ERROR'}
            if time.time()*1000 - captured > MAX_AGE_MS:
                return {**result, 'reason': 'STALE_FRAME'}
            visible = sum(p is not None for p in landmarks)
            return {**result, 'status': 'AVAILABLE' if visible else 'UNAVAILABLE',
                    'reason': None if visible else 'LOW_CONFIDENCE', 'landmarks': landmarks if visible else None,
                    'visible_landmarks': visible, 'inference_ms': round((time.monotonic()-started)*1000, 2)}
        finally:
            self._lock.release()
