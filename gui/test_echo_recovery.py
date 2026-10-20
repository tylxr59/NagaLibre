"""Recovery checkpoints must precede helper invocation and prevent retries."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_hypershift_trial import FakeSession, trial

SPEC = importlib.util.spec_from_file_location(
    "echo_recovery", Path(__file__).resolve().parent.parent / "scripts/recover_layer_echo.py")
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


class EchoRecoveryTests(unittest.TestCase):
    def fixture(self, root):
        engine = root / "original-engine"
        engine.write_bytes(b"original helper")
        directory = root / "trial"
        trial.prepare(directory, engine, lambda _: FakeSession())
        status_path = directory / "status.json"
        status = json.loads(status_path.read_text())
        status["stage"] = "applying"
        trial.durable_plan(status_path, status)
        evidence = directory / "selector-evidence-1"
        evidence.mkdir()
        (evidence / "observations.json").write_text(json.dumps({
            "kind": "unverified_selector_observations", "bank_identity_verified": False, "slot": 1}))
        debug = root / "debug-helper"
        debug.write_bytes(b"recovery helper")
        return directory, debug

    def test_checkpoint_precedes_single_helper_invocation_and_original_plan_stays_intact(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, engine = self.fixture(Path(temporary))
            original = {name: (directory / name).read_bytes() for name in ("original.json", "plan.json")}

            def run(command, **kwargs):
                self.assertEqual(command[:3], ["sudo", str(engine), "onboard-recover-grid-one-echo"])
                self.assertEqual(kwargs, {"check": True})
                self.assertTrue((directory / "echo-recovery-status.json").exists())
                for flag in ("--backup", "--evidence"):
                    self.assertTrue(Path(command[command.index(flag)+1]).is_file())
                return subprocess.CompletedProcess(command, 0)

            with patch.object(recovery.subprocess, "run", side_effect=run) as invoke, patch("builtins.print"):
                recovery.recover(directory, engine=engine)
            invoke.assert_called_once()
            for name, content in original.items():
                self.assertEqual((directory / name).read_bytes(), content)
            self.assertEqual(json.loads((directory / "status.json").read_text())["stage"], "restored")

    def test_backup_or_fsync_failure_prevents_invocation(self):
        for corrupt in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                directory, engine = self.fixture(Path(temporary))
                if corrupt:
                    (directory / "original.json").write_text("changed")
                with patch.object(recovery.subprocess, "run") as invoke, patch.object(
                        recovery, "durable_plan", side_effect=OSError("fsync failed")):
                    with self.assertRaises((ValueError, OSError)):
                        recovery.recover(directory, engine=engine)
                invoke.assert_not_called()

    def test_lost_helper_reply_leaves_attempt_checkpoint_and_blocks_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, engine = self.fixture(Path(temporary))
            with patch.object(recovery.subprocess, "run", side_effect=subprocess.CalledProcessError(1, [])), patch("builtins.print"):
                with self.assertRaises(subprocess.CalledProcessError):
                    recovery.recover(directory, engine=engine)
            self.assertEqual(json.loads((directory / "echo-recovery-status.json").read_text())["stage"], "attempting")
            with patch.object(recovery.subprocess, "run") as invoke:
                with self.assertRaisesRegex(ValueError, "already attempted"):
                    recovery.recover(directory, engine=engine)
            invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
