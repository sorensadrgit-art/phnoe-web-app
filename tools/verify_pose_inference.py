"""Actual pinned CPU inference on generated drawings; no camera or human image."""
import argparse
import base64
import hashlib
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pose_inference import PoseInference


def drawing(shift=0):
    image = cv2.imread(str(ROOT/'tests/fixtures/pose/generated-body.png'))
    assert image is not None
    return cv2.warpAffine(image,np.float32([[1,0,shift],[0,1,0]]),(640,480),borderValue=(240,240,240))


def verify(models, output):
    output = output.resolve()
    if not output.is_relative_to(ROOT/'dist'): raise ValueError('Evidence must stay in workspace dist')
    output.mkdir(parents=True, exist_ok=False)
    engine = PoseInference(models); operation = str(uuid4()); results = []
    cases = [(-40,drawing(-40)),(0,drawing()),(40,drawing(40)),('blank',np.full((480,640,3),245,np.uint8))]
    for sequence,(label,image) in enumerate(cases,1):
        blob = cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,75])[1].tobytes()
        (output/f'generated-{label}.jpg').write_bytes(blob)
        result = engine.infer({'schema_version': 1,'operation_id': operation,'sequence': sequence,
            'captured_at_ms': int(time.time()*1000),'source': 'TEST_IMAGE','jpeg_base64': base64.b64encode(blob).decode()})
        results.append(dict(case=label,**result))
    receipt = {'status':'FAIL','fixture':'generated drawing; physical accuracy not verified',
               'fixture_sha256':hashlib.sha256((ROOT/'tests/fixtures/pose/generated-body.png').read_bytes()).hexdigest(),'results':results}
    try:
        assert all(r['status']=='AVAILABLE' for r in results[:3]), [(r['status'],r['reason']) for r in results]
        assert results[-1]['reason']=='NO_PERSON'
        centers=[sum(r['landmarks'][i]['x'] for i in (11,12))/2*640 for r in results[:3]]
        assert 20 < centers[1]-centers[0] < 60 and 20 < centers[2]-centers[1] < 60, centers
        assert all(p is None or p['z'] is None for r in results[:3] for p in r['landmarks'])
        receipt.update(status='PASS',shoulder_center_x_pixels=centers)
    finally:
        (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':receipt['status'],'receipt':str(output/'receipt.json')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();verify(args.models,args.out)
