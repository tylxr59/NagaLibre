"""The controlled wheel trial saves recovery state before commit and restores on interruption."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("haptic_test", Path(__file__).resolve().parent.parent / "scripts/haptic_test.py")
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


class HapticTrialTests(unittest.TestCase):
    def test_commit_has_durable_original_and_interruption_always_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp) / "engine"
            engine.write_bytes(b"mock")
            directory = Path(tmp) / "trial"
            events = []
            class Session:
                hello = {"haptic_settings": True}
                def __init__(self, engine):
                    pass
                def __enter__(self):
                    return self
                def __exit__(self, *_):
                    pass
                def command(self, command, **arguments):
                    events.append(command)
                    if command == "haptic_read":
                        return {"type": "haptic_snapshot", "snapshot": {"state": {"slot": 1, "stages": [129, 130], "active_position": 2}}}
                    if command == "haptic_prepare":
                        return {"type": "haptic_prepared", "token": "123", "backup": {"opaque": [255]}}
                    if command == "haptic_commit":
                        self_test.assertEqual(json.loads((directory / "original-wheel.json").read_text()), {"opaque": [255]})
                        self_test.assertEqual(json.loads((directory / "plan.json").read_text())["status"], "applying")
                        return {"type": "haptic_saved", "snapshot": {"state": "saved"}}
                    raise AssertionError(command)
            self_test = self
            with patch.object(trial, "Session", Session), patch.object(trial, "restore") as restore, patch("builtins.input", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    trial.trial(engine, directory, 1)
            restore.assert_called_once_with(directory)
            self.assertEqual(events, ["haptic_read", "haptic_prepare", "haptic_commit"])

    def test_helper_errors_never_become_success_receipts(self):
        class Session:
            def command(self, *_args, **_kwargs):
                return {"type": "haptic_error", "message": "lost acknowledgement"}
        with self.assertRaisesRegex(ValueError, "lost acknowledgement"):
            trial.command(Session(), "haptic_commit", "haptic_saved", token="123")


if __name__ == "__main__":
    unittest.main()
