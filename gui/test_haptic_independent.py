"""Private independent checkpoint capture never invokes a settings writer."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("haptic_independent", Path(__file__).resolve().parent.parent / "scripts/backup_haptic_independent.py")
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


class IndependentTests(unittest.TestCase):
    def test_private_checkpoint_fsynced_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp) / "engine"
            engine.write_bytes(b"helper")
            directory = Path(tmp) / "capture"
            result = {"format": 1, "kind": "haptic_independent_checkpoint", "table_views": {"stable": True}}
            with patch.object(backup, "query", return_value=result) as query:
                path, checkpoint = backup.capture(engine, directory)
            query.assert_called_once_with(engine, "haptic-independent-checkpoint")
            self.assertEqual(json.loads(path.read_text()), checkpoint)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)

    def test_failed_initial_fsync_prevents_hardware_and_invalid_results_are_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp) / "engine"
            engine.write_bytes(b"helper")
            with patch.object(backup, "durable_plan", side_effect=OSError("fsync")), patch.object(backup, "query") as query:
                with self.assertRaises(OSError):
                    backup.capture(engine, Path(tmp) / "failed")
                query.assert_not_called()
            with patch.object(backup, "query", return_value={"format": 1, "kind": "haptic_diagnostic"}):
                with self.assertRaises(ValueError):
                    backup.capture(engine, Path(tmp) / "wrong")
            self.assertFalse((Path(tmp) / "wrong/checkpoint.json").exists())

    def test_changed_helper_prevents_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp) / "engine"
            engine.write_bytes(b"helper")
            directory = Path(tmp) / "capture"

            def query(*_):
                engine.write_bytes(b"changed")
                return {"format": 1, "kind": "haptic_independent_checkpoint", "table_views": {"stable": True}}

            with patch.object(backup, "query", side_effect=query), self.assertRaisesRegex(ValueError, "Helper changed"):
                backup.capture(engine, directory)
            self.assertFalse((directory / "checkpoint.json").exists())
