"""Physical-check orchestration must restore even after input/transport failure."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_wheel_controlled import FakeSession, wheel

SPEC = importlib.util.spec_from_file_location(
    "verify_wheel", Path(__file__).resolve().parent.parent / "scripts/verify_wheel.py")
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


class GuidedWheelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "trial"
        self.engine = Path(self.temporary.name) / "engine"
        self.engine.write_bytes(b"engine")
        self.session = FakeSession()
        self.original = copy.deepcopy(self.session.snapshots)

    def run_trial(self, answers):
        def prepare(directory, _engine, control):
            wheel.prepare(directory, self.engine, control, lambda _: self.session)
        def stage(name, directory):
            return wheel.run_stage(name, directory, lambda _: self.session)
        with patch("builtins.print"):
            return verify.trial(self.directory, 14, lambda _: next(answers), prepare, stage)

    def test_success_records_observations_and_exact_restore_after_reconnect(self):
        results = self.run_trial(iter(["yes"] * 7))
        self.assertEqual(set(results.values()), {"yes"})
        self.assertEqual(self.session.snapshots, self.original)
        self.assertEqual(json.loads((self.directory / "status.json").read_text())["stage"], "restored")
        self.assertEqual(json.loads((self.directory / "observations.json").read_text()), results)

    def test_failed_output_is_recorded_without_claiming_success(self):
        results = self.run_trial(iter(["yes", "no", "yes", "skip", "yes", "yes"]))
        self.assertEqual(results["b_output"], "no")
        self.assertEqual(results["reconnected"], "skip")
        self.assertNotIn("b_after_reconnect", results)
        self.assertEqual(self.session.snapshots, self.original)

    def test_interruption_during_physical_check_still_restores(self):
        def answers():
            yield "yes"
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_trial(answers())
        self.assertEqual(self.session.snapshots, self.original)
        self.assertEqual(json.loads((self.directory / "status.json").read_text())["stage"], "restored")

    def test_lost_commit_reply_attempts_exact_restore_without_reapplying(self):
        command = self.session.command
        lost_reply = False
        def fail_after_commit(name, **arguments):
            nonlocal lost_reply
            event = command(name, **arguments)
            if name == "onboard_commit" and not lost_reply:
                lost_reply = True
                raise OSError("reply lost after accepted write")
            return event
        self.session.command = fail_after_commit
        with self.assertRaisesRegex(OSError, "reply lost"):
            self.run_trial(iter(["yes"]))
        self.assertEqual(self.session.snapshots, self.original)
        self.assertEqual(self.session.commands.count("onboard_prepare"), 1)
        self.assertEqual(self.session.commands.count("onboard_restore"), 1)

    def test_transient_reconnect_getter_failure_retries_only_reads(self):
        command = self.session.command
        failed = False
        def fail_read(name, **arguments):
            nonlocal failed
            if name == "onboard_read" and "onboard_commit" in self.session.commands and not failed:
                # Fail only after apply's saved snapshot and independent read
                # have completed, when reconnect verification opens a new stage.
                if json.loads((self.directory / "status.json").read_text())["stage"] == "applied":
                    failed = True
                    raise ValueError("Reading slot 1, button 13 (wire 0x34), layer 0: "
                                     "No matching reply to mouse command 02/8c; wake the mouse")
            return command(name, **arguments)
        self.session.command = fail_read
        results = self.run_trial(iter(["yes"] * 8))
        self.assertTrue(failed)
        self.assertEqual(results["reconnect_readback"], "yes")
        self.assertEqual(results["b_after_reconnect"], "yes")
        self.assertEqual(self.session.snapshots, self.original)
        self.assertEqual(self.session.commands.count("onboard_prepare"), 1)
        self.assertEqual(self.session.commands.count("onboard_commit"), 2)
        self.assertEqual(len(json.loads((self.directory / "readback_errors.json").read_text())), 1)

    def test_state_mismatch_is_never_retried(self):
        command = self.session.command
        def fail_read(name, **arguments):
            if name == "onboard_read" and (self.directory / "status.json").exists():
                if json.loads((self.directory / "status.json").read_text())["stage"] == "applied":
                    # The wrapper must stop, but its finally block can still
                    # restore after the status changes to restoring below.
                    self.session.command = command
                    raise ValueError("Another tracked record or device state changed")
            return command(name, **arguments)
        self.session.command = fail_read
        with self.assertRaisesRegex(ValueError, "Another tracked"):
            self.run_trial(iter(["yes"] * 5))
        self.assertEqual(self.session.snapshots, self.original)
        self.assertEqual(self.session.commands.count("onboard_prepare"), 1)


if __name__ == "__main__":
    unittest.main()
