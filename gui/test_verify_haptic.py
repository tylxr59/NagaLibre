"""Post-restore evidence uses only getters and never alters completed trial state."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("verify_haptic", Path(__file__).resolve().parent.parent / "scripts/verify_haptic.py")
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class HapticVerificationTests(unittest.TestCase):
    def setup_trial(self, directory):
        engine = directory / "engine"
        engine.write_bytes(b"mock")
        guard = {"device": {"serial": "mock", "product": 167, "path": "old"}, "slots": [1], "active": 1}
        state = {"slot": 1, "active_position": 5, "stages": [129, 133], "records": [{"rejection": 3}]}
        mappings = {"normal": {"device": copy.deepcopy(guard["device"]), "slot": 1}, "hypershift": {"opaque": [255]}}
        backup = {"format": 1, "kind": "haptic_settings_backup", "guard": guard, "slots": [state], "mappings": {"slots": [{"state": mappings}]}}
        backup_path = directory / "original-wheel.json"
        backup_path.write_text(json.dumps(backup))
        plan = {"status": "restored_exactly", "engine": str(engine), "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(), "backup_sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest()}
        (directory / "plan.json").write_text(json.dumps(plan))
        return backup

    def test_matching_state_writes_separate_private_receipt_and_preserves_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            backup = self.setup_trial(directory)
            original = {p.name: p.read_bytes() for p in directory.iterdir()}
            calls = []
            def query(engine, command, *arguments):
                calls.append((command, arguments))
                self.assertEqual(arguments, ("--slot", "1"))
                if command == "onboard-layers":
                    value = copy.deepcopy(backup["mappings"]["slots"][0]["state"])
                    value["normal"]["device"]["path"] = "new"
                    return value
                self.assertEqual(command, "haptic-read")
                value = {"format": 1, "kind": "haptic_diagnostic", "guard": copy.deepcopy(backup["guard"]), "state": copy.deepcopy(backup["slots"][0])}
                value["guard"]["device"]["path"] = "new"
                return value
            with patch.object(check, "query", side_effect=query):
                path, receipt = check.verify(directory)
            self.assertTrue(receipt["matches_original"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual([c[0] for c in calls], ["haptic-read", "onboard-layers", "haptic-read"])
            for name, data in original.items():
                self.assertEqual((directory / name).read_bytes(), data)

    def test_changed_position_and_unstable_capture_are_reported_without_restoration(self):
        for unstable in [False, True]:
            with self.subTest(unstable=unstable), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                backup = self.setup_trial(directory)
                reads = 0
                def query(engine, command, *_arguments):
                    nonlocal reads
                    if command == "onboard-layers":
                        return copy.deepcopy(backup["mappings"]["slots"][0]["state"])
                    reads += 1
                    state = copy.deepcopy(backup["slots"][0])
                    state["active_position"] = 1 if not unstable or reads == 1 else 2
                    return {"format": 1, "kind": "haptic_diagnostic", "guard": backup["guard"], "state": state}
                with patch.object(check, "query", side_effect=query):
                    _, receipt = check.verify(directory)
                self.assertFalse(receipt["matches_original"])
                self.assertIn("active_position", receipt["slots"][0]["changed_wheel_fields"])
                self.assertEqual(receipt["slots"][0]["stable"], not unstable)
                self.assertEqual(json.loads((directory / "plan.json").read_text())["status"], "restored_exactly")

    def test_changed_backup_hash_prevents_all_device_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.setup_trial(directory)
            (directory / "original-wheel.json").write_text("{}")
            with patch.object(check, "query") as query:
                with self.assertRaisesRegex(ValueError, "checksum changed"):
                    check.verify(directory)
                query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
