"""One-desktop-icon KineLab hub must preserve and launch each original shortcut."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kinelab_hub import HUB_ENTRIES, resolve_shortcut, launch_shortcut


class HubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.archive = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_menu_is_exactly_seven_existing_launchers(self):
        self.assertEqual(len(HUB_ENTRIES), 7)
        self.assertEqual(len({item["key"] for item in HUB_ENTRIES}), 7)
        self.assertEqual(len({item["filename"] for item in HUB_ENTRIES}), 7)
        self.assertEqual(sum(item["category"] == "core" for item in HUB_ENTRIES), 2)
        self.assertEqual(sum(item["category"] == "test" for item in HUB_ENTRIES), 5)
        self.assertTrue(all(item["filename"].startswith("KineLab PT - ") for item in HUB_ENTRIES))
        self.assertTrue(all(item["filename"].endswith(".lnk") for item in HUB_ENTRIES))

    def test_all_user_shortcuts_reachable_without_a_copy_or_deletion(self):
        for item in HUB_ENTRIES:
            (self.archive / item["filename"]).write_text("test-owned-link-placeholder")
        for item in HUB_ENTRIES:
            with self.subTest(item=item["key"]), patch("kinelab_hub.os.startfile", create=True) as start:
                target=launch_shortcut(item["key"], archive=self.archive)
                self.assertEqual(target, self.archive / item["filename"])
                start.assert_called_once_with(str(target))

    def test_no_unknown_commands_or_path_traversal(self):
        for value in ("../escape", "", "C:/temp/file.lnk", "unknown", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve_shortcut(value, archive=self.archive)

    def test_missing_backup_fails_without_launching_anything(self):
        with patch("kinelab_hub.os.startfile", create=True) as start:
            with self.assertRaises(FileNotFoundError):
                launch_shortcut("capture", archive=self.archive)
            start.assert_not_called()

    def test_symlinked_shortcut_or_archive_escape_is_rejected(self):
        example=HUB_ENTRIES[0]
        outside=Path(self.temp.name).parent / (example["key"] + "-outside-placeholder.lnk")
        outside.write_bytes(b"test only")
        try:
            (self.archive / example["filename"]).symlink_to(outside)
        except (OSError, PermissionError):
            outside.unlink()
            self.skipTest("Windows symlink creation unavailable")
        try:
            with self.assertRaises(ValueError):
                resolve_shortcut(example["key"], archive=self.archive)
        finally:
            outside.unlink(missing_ok=True)

    def test_only_launcher_links_not_patient_media_can_be_launched(self):
        for item in HUB_ENTRIES:
            self.assertNotIn("mp4", item["filename"].lower())
            self.assertNotIn("run.json", item["filename"].lower())
            self.assertNotIn("capture-20261026-trial01", item["filename"].lower())


if __name__ == "__main__":
    unittest.main()
