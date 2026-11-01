"""R10 request/overflow regressions compose the existing generated browser fixture."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import test_candidate_ui_harness as existing_fixture
from tools import verify_candidate_ui as harness

PAIRS = ((320, 568), (568, 320), (390, 844), (844, 390),
         (768, 1024), (1024, 768), (1024, 1366), (1366, 1024),
         (1440, 1920), (1920, 1440))


class CandidateResponsiveVerifierTests(unittest.TestCase):
    def compose_fixture(self, *, overflow=False):
        requested = []
        state = {"width": 1280, "height": 800, "overflow_injected": False}
        receipts = []
        sweep_boundaries = []
        self.observation = {"requested": requested, "state": state, "receipts": receipts,
                            "sweep_boundaries": sweep_boundaries}
        real_verify = harness.verify

        def observed_verify(*args, **kwargs):
            fixture_run = harness.subprocess.run
            real_log = harness.Logger.log

            def observed_log(logger, message):
                if message == "CHECK 5: Verifying responsive viewports...":
                    sweep_boundaries.append(("start", len(requested)))
                elif message == "CHECK 5 PASSED.":
                    sweep_boundaries.append(("end", len(requested)))
                return real_log(logger, message)

            def browser(command, *run_args, **run_kwargs):
                if "set" in command:
                    index = command.index("set")
                    if command[index:index + 2] == ["set", "viewport"]:
                        state["width"], state["height"] = map(int, command[index + 2:index + 4])
                        requested.append((state["width"], state["height"]))
                script = run_kwargs.get("input", "") or ""
                if "--stdin" in command and ("scrollWidth" in script or "mobile_checks" in script):
                    excessive = overflow and (state["width"], state["height"]) == PAIRS[0]
                    state["overflow_injected"] |= excessive
                    value = {"scrollWidth": state["width"] + int(excessive),
                             "clientWidth": state["width"], "linksCount": 5,
                             "navControlsVisible": True, "width": state["width"],
                             "height": state["height"]}
                    return subprocess.CompletedProcess(command, 0,
                        json.dumps({"success": True, "data": {"result": value}}), "")
                return fixture_run(command, *run_args, **run_kwargs)

            with (
                patch.object(harness.Logger, "log", new=observed_log),
                patch.object(harness.subprocess, "run", side_effect=browser),
            ):
                try:
                    return real_verify(*args, **kwargs)
                finally:
                    receipt = Path(args[0]) / "receipt.json"
                    if receipt.is_file():
                        receipts.append(json.loads(receipt.read_text(encoding="utf-8")))

        fixture = existing_fixture.TestCandidateUIHarness(
            methodName="test_browser_session_isolation_and_no_all_flag")
        with patch.object(harness, "verify", side_effect=observed_verify):
            fixture.test_browser_session_isolation_and_no_all_flag()
        return requested, state, receipts

    def test_all_ten_portrait_landscape_pairs_are_actually_requested(self):
        if existing_fixture.run_in_fresh_worker(self):
            return
        requested, _state, receipts = self.compose_fixture()
        # Modal checks may revisit these dimensions outside the responsive sweep.
        boundaries = self.observation["sweep_boundaries"]
        self.assertEqual([event for event, _offset in boundaries], ["start", "end"],
                         f"Expected one completed responsive sweep: {boundaries}")
        start, end = (offset for _event, offset in boundaries)
        self.assertEqual(tuple(requested[start:end]), PAIRS,
                         f"Required responsive viewport sequence absent/duplicated: {requested[start:end]}")
        self.assertEqual(receipts[-1]["status"], "PASS")
        self.assertTrue(receipts[-1]["cleanup"]["cleanup_verified"])

    def test_320_pixel_overflow_cannot_be_reported_as_pass(self):
        if existing_fixture.run_in_fresh_worker(self):
            return
        with self.assertRaisesRegex(AssertionError, "overflow|horizontal"):
            self.compose_fixture(overflow=True)
        self.assertTrue(self.observation["state"]["overflow_injected"], "Required320-width overflow was not exercised")
        self.assertEqual(self.observation["receipts"][-1]["status"], "FAIL")
        self.assertTrue(self.observation["receipts"][-1]["cleanup"]["cleanup_verified"])
