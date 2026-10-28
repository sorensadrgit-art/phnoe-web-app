"""Native Capture Station can be opened for the selected integrated session."""
import unittest
from pathlib import Path
from capture_station_gui import CaptureApp

class NativeSessionEntryTests(unittest.TestCase):
    def test_selected_session_becomes_initial_active_capture_session(self):
        app=CaptureApp(initial_session_id='caliscope-walking-test-20261027')
        try:
            app.update_idletasks()
            self.assertEqual(app.project.name,'caliscope-walking-test-20261027')
            self.assertEqual(app.session_choice.get(),app.project.name)
            self.assertFalse(app.library.describe_session(app.project.name)['can_register'])
        finally:
            app.destroy()

if __name__=="__main__":
    unittest.main()
