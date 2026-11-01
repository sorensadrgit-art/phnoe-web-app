"""Native Capture Station opens only a fresh generated session in this test."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capture_station_gui import CaptureApp
from session_library import SessionLibrary


class NativeSessionEntryTests(unittest.TestCase):
    def test_selected_session_becomes_initial_active_capture_session(self):
        with tempfile.TemporaryDirectory(prefix="kinelab-generated-native-") as directory:
            root = Path(directory)
            projects = root / "projects"
            projects.mkdir()
            session_id = "generated-native-selection"
            SessionLibrary(projects).create_session(session_id, kind="real")
            with patch("capture_station_gui.ROOT", root):
                app = CaptureApp(initial_session_id=session_id)
                try:
                    app.withdraw()
                    app.update_idletasks()
                    self.assertEqual(app.project.name, session_id)
                    self.assertEqual(app.session_choice.get(), app.project.name)
                    self.assertEqual(app.library.describe_session(app.project.name)["captured_roles"], 0)
                    self.assertFalse((app.project / "session.json").exists())
                finally:
                    app.destroy()


if __name__ == "__main__":
    unittest.main()
