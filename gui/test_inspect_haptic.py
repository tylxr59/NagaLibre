"""The first wheel query must follow a durable mapping checkpoint."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("inspect_haptic", Path(__file__).resolve().parent.parent / "scripts/inspect_haptic.py")
inspect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspect)


class HapticCaptureTests(unittest.TestCase):
    def fixtures(self):
        normal = {"device": {"product": 0xa7, "serial": "mock", "path": "mock"},
                  "slots": [1], "slot": 1, "active": 1, "slot_capacity": 5, "mode": [0, 0]}
        slots = [{"format": 1, "normal": normal, "hypershift": {"raw": [255]}}]
        export = {"format": 1, "kind": "haptic_diagnostic", "guard": {
            "device": normal["device"], "slots": [1], "active": 1, "capacity": 5,
            "mode": [0, 0], "module_id": 3}, "state": {"unknown": [255]}}
        return slots, export

    def test_checkpoint_precedes_wheel_request_and_exports_are_private(self):
        slots, export = self.fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "new"
            def query(engine, command):
                self.assertEqual(command, "haptic-read")
                self.assertEqual(json.loads((directory / "mappings-before.json").read_text())["slots"], slots)
                return export
            with patch.object(inspect, "mappings", return_value=slots) as mappings, patch.object(inspect, "query", side_effect=query):
                path, result = inspect.capture(Path("engine"), directory)
            self.assertEqual(result, export)
            self.assertEqual(json.loads(path.read_text()), export)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual(mappings.call_args_list[-1].args, (Path("engine"), slots))

    def test_optional_firmware_read_is_after_checkpoint_and_bound_to_same_guard(self):
        for changed in [False, True]:
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as tmp:
                slots, export = self.fixtures()
                directory = Path(tmp) / "new"
                version = {"format": 1, "kind": "haptic_firmware_diagnostic", "guard": json.loads(json.dumps(export["guard"])),
                           "stable": True, "reported_version": "2.61", "version_bytes": [2, 61], "patch_available": False}
                if changed:
                    version["guard"]["active"] = 2
                commands = []
                def query(_engine, name):
                    commands.append(name)
                    self.assertTrue((directory / "mappings-before.json").exists())
                    return export if name == "haptic-read" else version
                with patch.object(inspect, "mappings", return_value=slots) as mappings, patch.object(inspect, "query", side_effect=query):
                    if changed:
                        with self.assertRaisesRegex(ValueError, "different device"):
                            inspect.capture(Path("engine"), directory, firmware_version=True)
                        self.assertFalse((directory / "firmware.json").exists())
                    else:
                        inspect.capture(Path("engine"), directory, firmware_version=True)
                        self.assertEqual(json.loads((directory / "firmware.json").read_text()), version)
                    self.assertEqual(mappings.call_count, 2)
                self.assertEqual(commands, ["haptic-read", "haptic-firmware"])

    def test_backup_failure_prevents_wheel_queries(self):
        slots, _ = self.fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(inspect, "mappings", return_value=slots), patch.object(inspect, "durable_plan", side_effect=OSError("fsync")), patch.object(inspect, "query") as query:
                with self.assertRaisesRegex(OSError, "fsync"):
                    inspect.capture(Path("engine"), Path(tmp) / "new")
                query.assert_not_called()

    def test_failed_getter_rechecks_mappings_and_keeps_original_checkpoint(self):
        slots, _ = self.fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "new"
            with patch.object(inspect, "mappings", return_value=slots) as mappings, patch.object(inspect, "query", side_effect=subprocess.CalledProcessError(1, [])):
                with self.assertRaises(subprocess.CalledProcessError):
                    inspect.capture(Path("engine"), directory)
            self.assertEqual(mappings.call_count, 2)
            self.assertTrue((directory / "mappings-before.json").is_file())
            self.assertTrue((directory / "mappings-after.json").is_file())
            self.assertFalse((directory / "wheel.json").exists())

    def test_all_slot_changes_are_rejected(self):
        slots, _ = self.fixtures()
        changed = json.loads(json.dumps(slots[0]))
        changed["hypershift"]["raw"] = [254]
        with patch.object(inspect, "query", return_value=changed):
            with self.assertRaisesRegex(ValueError, "Mapping state changed"):
                inspect.mappings(Path("engine"), slots)


if __name__ == "__main__":
    unittest.main()
