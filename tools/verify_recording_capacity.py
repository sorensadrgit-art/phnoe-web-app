"""Accelerated 30-minute generated recording/restart acceptance, not a camera benchmark."""
import argparse
import json
import sys
import tempfile
import tracemalloc
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from recording_contract import canonical_json, digest
from recording_store import RecordingStore
from session_index import SessionIndex
from test_recording_contract import frame, header
from test_recording_store import chunk


def verify(output):
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / "dist") or output.exists():
        raise ValueError("Use a new evidence file under this workspace's dist directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": "generated frames only", "simulation": "accelerated 30 minutes at 20 samples/s"}
    started = perf_counter()
    with tempfile.TemporaryDirectory(prefix="kinelab-capacity-") as temporary:
        root = Path(temporary); projects = root / "projects"; projects.mkdir()
        index = SessionIndex(root / "index.db", projects)
        tracemalloc.start()
        try:
            store = RecordingStore(index); sid = header()["session_id"]
            store.create(header()); latency = []
            for first in range(1, 36001, 16):
                frames = [frame(i, (i - 1) * 50) for i in range(first, first + 16)]
                payload = chunk(first)
                payload.update(frames_json=canonical_json(frames), sha256=digest(frames))
                assert len(json.dumps(payload).encode("utf-8")) < 64 * 1024
                before = perf_counter(); result = store.append(sid, payload)
                latency.append(perf_counter() - before)
                assert result["saved_through"] == first + 15
            final = store.finalize(sid, header()["operation_id"], 36000)
            assert final["manifest"]["frame_count"] == 36000
            expected_audit = index.verify_audit()
            index.close(); index = SessionIndex(root / "index.db", projects)
            store = RecordingStore(index)
            assert store.verify(sid)["manifest_sha256"] == final["manifest_sha256"]
            assert index.verify_audit() == expected_audit
            count = 0
            for count, actual in enumerate(store.iter_frames(sid), 1):
                assert actual == frame(count, (count - 1) * 50)
            assert count == 36000
            receipt.update(status="PASS", frames=count, chunks=len(latency),
                append_median_ms=sorted(latency)[len(latency)//2]*1000,
                append_p95_ms=sorted(latency)[int(len(latency)*.95)]*1000,
                append_max_ms=max(latency)*1000, database_bytes=index.db_path.stat().st_size,
                python_peak_traced_bytes=tracemalloc.get_traced_memory()[1],
                wall_seconds=perf_counter()-started,
                limitations="Accelerated storage replay; real-time 30-minute camera/browser/device and physical power-loss testing NOT RUN")
        finally:
            tracemalloc.stop(); index.close()
    output.write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    verify(parser.parse_args().out)
