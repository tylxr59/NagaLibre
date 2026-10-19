"""Read-only hardware-test preparation, without accessing real devices."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "backup_onboard", Path(__file__).resolve().parent.parent / "scripts/backup_onboard.py"
)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class ActiveSlotBackup(unittest.TestCase):
    def test_getter_snapshot_is_saved_privately_with_original_wire_data(self):
        snapshot = {
            "active": 1, "slot": 1, "device": {"serial": "TEST"},
            "buttons": [{"button": 3, "category": 2, "data": [0, 32],
                         "raw_record": [2, 1, 0, 32, 0, 0, 0]}],
        }
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profiles.json"
            with patch.object(backup.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(snapshot))) as run:
                path, actual = backup.backup_active(Path("/fake/engine"), profile)
            self.assertEqual(run.call_args.args[0], ["sudo", "/fake/engine", "onboard-read"])
            self.assertEqual(actual, snapshot)
            self.assertEqual(json.loads(path.read_text()), snapshot)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_getter_or_substituted_slot_does_not_create_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profiles.json"
            with patch.object(backup.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "getter")):
                with self.assertRaises(subprocess.CalledProcessError):
                    backup.backup_active(Path("/fake/engine"), profile)
            with patch.object(backup.subprocess, "run", return_value=SimpleNamespace(stdout='{"active":0,"slot":1}')):
                with self.assertRaises(ValueError):
                    backup.backup_active(Path("/fake/engine"), profile)
            self.assertEqual(list(Path(directory).iterdir()), [])
