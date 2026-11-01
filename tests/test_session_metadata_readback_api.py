"""Generated TEST_ONLY loopback metadata readback; no capture or identity attestation."""
from __future__ import annotations

import copy
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import take_acceptance as takes
from session_contract import ROLES
from t6_server import make_server
from t6_service import IntegratedService


def metadata():
    return {"schema": "kinelab.session-metadata.v1", "subject_id": "sub-" + "1" * 32,
            "operator_id": "op-" + "2" * 32, "task_id": "TEST_ONLY-task",
            "protocol_id": "TEST_ONLY-protocol", "protocol_version": "1",
            "laterality": "bilateral", "confirmed": True,
            "confirmed_at": "2026-10-29T13:00:00+00:00"}


class BinaryRead:
    """Instrument a real generated-file stream, retaining its actual descriptor."""
    def __init__(self, stream, transform):
        self.stream, self.transform = stream, transform

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def fileno(self):
        return self.stream.fileno()

    def read(self, size=-1):
        return self.transform(self.stream, size)


class MetadataReadbackApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.service = IntegratedService(projects_root=self.projects)
        self.addCleanup(self.service.close)
        dist = self.root / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<title>TEST_ONLY</title>", encoding="utf-8")
        samples = self.root / "samples"
        samples.mkdir()
        self.server = make_server(self.service, token="a" * 50, dist=dist, samples=samples, port=0)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=4)

    def request(self, method, suffix="", body=None, *, authorized=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=6)
        try:
            headers = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json",
                       "Origin": f"http://127.0.0.1:{self.port}"}
            if authorized:
                headers["Authorization"] = "Bearer " + "a" * 50
            connection.request(method, "/api/v1/sessions" + suffix,
                               None if body is None else json.dumps(body).encode(), headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def create(self, sid="generated-readback", **kwargs):
        status, result = self.request("POST", body={"id": sid, "kind": "real", **kwargs})
        self.assertEqual(status, 201, result)
        return result

    def assert_available(self, result, sid, filename, expected):
        confirmation = result["metadata_confirmation"]
        self.assertEqual(confirmation["schema"], "kinelab.session-metadata-readback.v1")
        self.assertEqual(confirmation["session_id"], sid)
        self.assertEqual(confirmation["status"], "AVAILABLE", confirmation)
        self.assertEqual(confirmation["metadata"], expected)
        self.assertEqual(confirmation["source"], {"path": filename, "sha256": hashlib.sha256(
            (self.projects / sid / filename).read_bytes()).hexdigest()})

    def assert_unavailable(self, result):
        confirmation = result["metadata_confirmation"]
        self.assertEqual(confirmation["status"], "UNAVAILABLE")
        self.assertIsNone(confirmation["metadata"])
        self.assertIsNone(confirmation["source"])
        self.assertTrue(confirmation["reason"])

    def test_actual_create_and_reload_return_same_persisted_bytes(self):
        result = self.create(metadata=metadata())
        self.assert_available(result, "generated-readback", "session-template.json", metadata())
        project = self.projects / "generated-readback"
        before = {p: p.read_bytes() for p in (project / "Config.toml", project / "session-template.json")}
        status, detail = self.request("GET", "/generated-readback")
        self.assertEqual(status, 200, detail)
        self.assert_available(detail, "generated-readback", "session-template.json", metadata())
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_absent_and_null_stay_unavailable_without_backfill(self):
        for sid, kwargs in (("generated-absent", {}), ("generated-null", {"metadata": None})):
            with self.subTest(sid=sid):
                self.assert_unavailable(self.create(sid, **kwargs))
                source = self.projects / sid / "session-template.json"
                before = source.read_bytes()
                status, detail = self.request("GET", "/" + sid)
                self.assertEqual(status, 200)
                self.assert_unavailable(detail)
                self.assertEqual(source.read_bytes(), before)
                self.assertNotIn("metadata", json.loads(before))

    def test_malformed_source_never_becomes_confirmation(self):
        self.create(metadata=metadata())
        source = self.projects / "generated-readback/session-template.json"
        original = json.loads(source.read_bytes())
        wrong_id = {**original, "session_id": "different-session"}
        wrong_metadata = copy.deepcopy(original)
        wrong_metadata["metadata"]["confirmed"] = "true"
        for content in (b'{"schema":1,"schema":2}', json.dumps(wrong_id).encode(),
                        json.dumps(wrong_metadata).encode(), b'not-json'):
            with self.subTest(content=content[:40]):
                source.write_bytes(content)
                status, detail = self.request("GET", "/generated-readback")
                self.assertEqual(status, 200, detail)
                self.assert_unavailable(detail)
                self.assertEqual(source.read_bytes(), content)

    def test_registered_source_is_authoritative_and_not_rewritten(self):
        self.create(metadata=metadata())
        project = self.projects / "generated-readback"
        for role in ROLES:
            (project / "raw" / (role + ".mp4")).write_bytes(("TEST_ONLY " + role).encode())
        with patch("session_library._check_readiness_locked", return_value={
                "ready_to_register": True, "issues": [], "missing": []}):
            status, result = self.request("POST", "/generated-readback/register", {"confirm": True})
        self.assertEqual(status, 200, result)
        template = project / "session-template.json"
        changed = json.loads(template.read_bytes())
        changed["metadata"]["subject_id"] = "sub-" + "3" * 32
        template.write_text(json.dumps(changed), encoding="utf-8")
        originals = {p: p.read_bytes() for p in [template, project / "session.json", *(project / "raw").glob("*.mp4")]}
        status, detail = self.request("GET", "/generated-readback")
        self.assertEqual(status, 200, detail)
        self.assert_available(detail, "generated-readback", "session.json", metadata())
        self.assertEqual(originals, {p: p.read_bytes() for p in originals})
        session = project / "session.json"
        session.write_bytes(b'{"schema":"broken"}')
        status, detail = self.request("GET", "/generated-readback")
        self.assertEqual(status, 200, detail)
        self.assert_unavailable(detail)
        self.assertEqual(session.read_bytes(), b'{"schema":"broken"}')

    def test_digest_binds_the_bytes_actually_parsed(self):
        self.create(metadata=metadata())
        source = self.projects / "generated-readback/session-template.json"
        before = source.read_bytes()
        real_open, reads = Path.open, []
        def changed_read(stream, size):
            self.assertGreaterEqual(size, 0)
            self.assertLessEqual(size, 64 * 1024 + 1)
            reads.append(size)
            data = stream.read(size)
            return data.replace(b'"bilateral"', b'"left"') if len(reads) == 1 else data
        def opened(path, *args, **kwargs):
            stream = real_open(path, *args, **kwargs)
            return BinaryRead(stream, changed_read) if path == source and args[:1] == ("rb",) else stream
        with patch.object(Path, "open", opened):
            status, detail = self.request("GET", "/generated-readback")
        self.assertEqual(status, 200, detail)
        self.assert_unavailable(detail)
        self.assertEqual(len(reads), 2)
        self.assertEqual(source.read_bytes(), before)

    def test_linked_metadata_source_is_refused(self):
        self.create(metadata=metadata())
        source = self.projects / "generated-readback/session-template.json"
        external = self.root / "TEST_ONLY-external.json"
        external.write_bytes(source.read_bytes())
        source.unlink()
        try:
            source.symlink_to(external)
        except OSError as error:
            self.skipTest("Host does not permit generated file symlink: " + str(error))
        status, detail = self.request("GET", "/generated-readback")
        self.assertEqual(status, 200, detail)
        self.assert_unavailable(detail)

    def test_access_and_capture_refusals_remain(self):
        status, _ = self.request("POST", body={"id": "unauthorized", "metadata": metadata()}, authorized=False)
        self.assertEqual(status, 401)
        self.assertFalse((self.projects / "unauthorized").exists())
        self.create(metadata=metadata())
        with patch("t6_service.subprocess.Popen") as process:
            status, result = self.request("POST", "/generated-readback/capture",
                                          {"role": "cam02_trial", "seconds": 12, "confirm": True})
        self.assertEqual(status, 409, result)
        self.assertIn("PARTICIPANT_RECORDING_BLOCKED", json.dumps(result))
        process.assert_not_called()

    def test_oversized_metadata_source_refused_before_full_hash_and_preserved(self):
        self.create(metadata=metadata())
        source = self.projects / "generated-readback/session-template.json"
        before = b" " * (64 * 1024 + 1) + source.read_bytes()
        source.write_bytes(before)
        with patch("session_library.takes.file_proof", wraps=takes.file_proof) as proof:
            status, detail = self.request("GET", "/generated-readback")
        self.assertEqual(status, 200, detail)
        self.assert_unavailable(detail)
        self.assertIn("METADATA_SOURCE_TOO_LARGE", detail["metadata_confirmation"]["reason"])
        self.assertFalse(any(Path(call.args[0]) == source for call in proof.call_args_list))
        self.assertEqual(source.read_bytes(), before)

    def test_source_growth_during_stream_read_is_bounded_and_unavailable(self):
        self.create(metadata=metadata())
        source = self.projects / "generated-readback/session-template.json"
        before, real_open, reads = source.read_bytes(), Path.open, []
        def growing_read(stream, size):
            self.assertGreaterEqual(size, 0)
            self.assertLessEqual(size, 64 * 1024 + 1)
            reads.append(size)
            with real_open(source, "ab") as writer:
                writer.write(b" " * (64 * 1024 + 1))
            return stream.read(size)
        def opened(path, *args, **kwargs):
            stream = real_open(path, *args, **kwargs)
            return BinaryRead(stream, growing_read) if path == source and args[:1] == ("rb",) else stream
        with patch.object(Path, "open", opened):
            status, detail = self.request("GET", "/generated-readback")
        self.assertEqual(status, 200, detail)
        self.assert_unavailable(detail)
        self.assertIn("METADATA_SOURCE_TOO_LARGE", detail["metadata_confirmation"]["reason"])
        self.assertEqual(reads, [64 * 1024 + 1])
        self.assertEqual(source.read_bytes(), before + b" " * (64 * 1024 + 1))

    def test_windows_stat_interface_ctime_precision_does_not_invent_source_change(self):
        self.create(metadata=metadata())
        source = self.projects / "generated-readback/session-template.json"
        before = source.stat(follow_symlinks=False)
        real_fstat = takes.os.fstat
        def descriptor_stat(fd):
            item = real_fstat(fd)
            if (item.st_dev, item.st_ino) != (before.st_dev, before.st_ino):
                return item
            fields = {name: getattr(item, name) for name in dir(item) if name.startswith("st_")}
            # Windows path/descriptor stat interfaces can have different ctime
            # precision. Both interfaces must remain individually unchanged.
            fields["st_ctime_ns"] += 1
            return SimpleNamespace(**fields)
        with patch("session_library.os.fstat", descriptor_stat):
            status, detail = self.request("GET", "/generated-readback")
        self.assertEqual(status, 200, detail)
        self.assert_available(detail, "generated-readback", "session-template.json", metadata())


if __name__ == "__main__":
    unittest.main()
