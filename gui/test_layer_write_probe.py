"""The selector write probe persists recovery inputs before invoking its writer."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_hypershift_trial import FakeSession

SPEC = importlib.util.spec_from_file_location(
    "layer_write_probe", Path(__file__).resolve().parent.parent / "scripts/probe_layer_write.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class LayerWriteProbeTests(unittest.TestCase):
    def fixture(self, root):
        engine = root / "debug-helper"
        engine.write_bytes(b"probe helper")
        return root / "private-probe", engine, FakeSession()

    def test_original_backup_is_durable_before_write_and_run_cannot_be_repeated(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, engine, session = self.fixture(Path(temporary))

            def invoke(command, **kwargs):
                self.assertNotIn("onboard_commit", session.commands)
                self.assertEqual(command[:3], ["sudo", str(engine.resolve()), "onboard-layer-write-probe"])
                self.assertEqual(kwargs, {"check": True, "stdout": subprocess.PIPE, "text": True})
                self.assertEqual((directory / "original.json").stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads((directory / "status.json").read_text())["stage"], "attempting")
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({
                    "restored_exactly": True, "result": {"restoration_only": True}}))

            with patch.object(probe.subprocess, "run", side_effect=invoke), patch("builtins.print"):
                probe.run("run", directory, engine, lambda _: session)
            self.assertEqual(json.loads((directory / "status.json").read_text())["stage"], "restored_exactly")
            with self.assertRaisesRegex(ValueError, "fresh directory"):
                probe.run("run", directory, engine, lambda _: session)

    def test_backup_failure_prevents_writer_invocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, engine, session = self.fixture(Path(temporary))
            with patch.object(probe, "durable_plan", side_effect=OSError("fsync failed")), patch.object(
                    probe.subprocess, "run") as invoke, patch("builtins.print"):
                with self.assertRaises(OSError):
                    probe.run("run", directory, engine, lambda _: session)
            invoke.assert_not_called()
            self.assertNotIn("onboard_commit", session.commands)

    def test_failed_attempt_retains_backup_and_restore_uses_restore_flag_without_new_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, engine, session = self.fixture(Path(temporary))
            with patch.object(probe.subprocess, "run", side_effect=subprocess.CalledProcessError(1, [])), patch("builtins.print"):
                with self.assertRaises(subprocess.CalledProcessError):
                    probe.run("run", directory, engine, lambda _: session)
            before = (directory / "original.json").read_bytes()
            commands = list(session.commands)
            with patch.object(probe.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, stdout=json.dumps({"restored_exactly": True, "result": {"restoration_only": True}}))) as invoke, patch("builtins.print"):
                probe.run("restore", directory, engine, lambda _: session)
            self.assertIn("--restore", invoke.call_args.args[0])
            self.assertEqual(session.commands, commands)
            self.assertEqual((directory / "original.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
