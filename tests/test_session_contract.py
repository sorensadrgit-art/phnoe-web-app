import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROLES = ("cam01_intrinsics", "cam02_intrinsics", "cam01_board", "cam02_board", "cam01_trial", "cam02_trial")


class SessionContractTests(unittest.TestCase):
    def setUp(self):
        implementation = ROOT / "session_contract.py"
        self.assertTrue(implementation.is_file(), "session_contract.py implementation missing")
        spec = importlib.util.spec_from_file_location("session_contract", implementation)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        captures = {}
        for role in ROLES:
            path = self.project / "raw" / (role + ".mp4")
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(role.encode())
            captures[role] = {"path": path.relative_to(self.project).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        self.session = {"schema": "kinelab.session.v1", "session_id": "trial-01", "kind": "real", "subject_count": 1,
                        "camera_ids": ["cam01", "cam02"], "created_at": "2026-10-26T09:00:00-04:00", "captures": captures}

    def test_valid_session_and_streamed_hash(self):
        self.assertEqual(self.module.validate_session(self.session, self.project), self.session)
        entry = self.session["captures"][ROLES[0]]
        self.assertEqual(self.module.sha256_file(self.project / entry["path"]), entry["sha256"])

    def test_wrong_schema_camera_subject_and_missing_role_rejected(self):
        for key, value in [("schema", "other"), ("camera_ids", ["cam01"]), ("subject_count", True), ("session_id", "../bad"), ("created_at", "2026-10-26")]:
            with self.subTest(key=key):
                invalid = copy.deepcopy(self.session); invalid[key] = value
                with self.assertRaisesRegex(ValueError, "SESSION_INVALID"):
                    self.module.validate_session(invalid, self.project)
        invalid = copy.deepcopy(self.session); invalid["captures"].pop(ROLES[-1])
        with self.assertRaisesRegex(ValueError, "SESSION_INVALID"):
            self.module.validate_session(invalid, self.project)

    def test_changed_missing_or_bad_hash_inputs_rejected(self):
        invalid = copy.deepcopy(self.session); invalid["captures"][ROLES[0]]["sha256"] = "not-a-hash"
        with self.assertRaisesRegex(ValueError, "SESSION_INVALID"):
            self.module.validate_session(invalid, self.project)
        source = self.project / self.session["captures"][ROLES[0]]["path"]
        source.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "INPUT_CHANGED"):
            self.module.validate_session(self.session, self.project)
        source.unlink()
        with self.assertRaisesRegex(ValueError, "INPUT_MISSING"):
            self.module.validate_session(self.session, self.project)

    def test_path_escape_and_role_alias_rejected(self):
        for bad in ("../outside.mp4", str(self.project / "raw" / "file.mp4")):
            invalid = copy.deepcopy(self.session); invalid["captures"][ROLES[0]]["path"] = bad
            with self.assertRaisesRegex(ValueError, "SESSION_INVALID"):
                self.module.validate_session(invalid, self.project)
        invalid = copy.deepcopy(self.session); invalid["captures"][ROLES[1]] = invalid["captures"][ROLES[0]].copy()
        with self.assertRaisesRegex(ValueError, "SESSION_INVALID"):
            self.module.validate_session(invalid, self.project)

    def test_load_validates_and_rejects_duplicate_json_keys(self):
        path = self.project / "session.json"
        path.write_text(json.dumps(self.session), encoding="utf-8")
        self.assertEqual(self.module.load_session(self.project)["session_id"], "trial-01")
        path.write_text('{"schema":"kinelab.session.v1","schema":"other"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SESSION_INVALID"):
            self.module.load_session(self.project)


if __name__ == "__main__":
    unittest.main()
