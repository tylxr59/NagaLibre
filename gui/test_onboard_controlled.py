"""Exercise controlled-test gates and backup-before-commit ordering without hardware."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from model import new_profile
from onboard import hardware_buttons

spec = importlib.util.spec_from_file_location(
    "onboard_controlled_test", Path(__file__).resolve().parent.parent / "scripts/onboard_controlled_test.py"
)
controlled = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controlled)


class FakeSession:
    def __init__(self, original):
        self.current = copy.deepcopy(original)
        self.commands = []
        self.token = 100

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def command(self, name, **arguments):
        self.commands.append(name)
        if name == "onboard_read":
            return {"type": "onboard_snapshot", "snapshot": copy.deepcopy(self.current)}
        if name in ("onboard_prepare", "onboard_restore"):
            if name == "onboard_restore":
                self.next = copy.deepcopy(arguments["backup"])
            else:
                self.next = copy.deepcopy(self.current)
                for i, button in enumerate(arguments["buttons"]):
                    if button["data"] != self.current["buttons"][i]["data"]:
                        self.next["buttons"][i] = copy.deepcopy(button)
            self.token += 1
            return {"type": "onboard_prepared", "token": str(self.token), "backup": copy.deepcopy(self.current)}
        if name == "onboard_commit":
            self.current = self.next
            return {"type": "onboard_saved", "snapshot": copy.deepcopy(self.current)}
        raise AssertionError(name)


class ControlledHardwareTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.path = root / "controlled-hardware-test.json"
        self.original = {
            "format": 1, "device": {"path": "fake", "product": 167, "serial": "TEST"},
            "slots": [1, 2], "active": 1, "slot": 1, "mode": [0, 0],
            "primary": [{"button": i, "category": 1, "data": [i]} for i in (1, 2)],
            "buttons": hardware_buttons(new_profile()),
        }
        for b in self.original["buttons"][2:]:
            b["raw_record"] = [2, 1, *b["data"], 0, 0, 0]
        backup = root / "original.json"
        backup.write_text(json.dumps(self.original))
        engine = root / "engine"
        engine.write_bytes(b"fake engine")
        self.plan = {
            "status": "prepared", "slot": 1,
            "backup": str(backup), "backup_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
            "engine": str(engine), "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
        }
        self.path.write_text(json.dumps(self.plan))
        self.session = FakeSession(self.original)

    def run_stage(self, stage):
        return controlled.run_stage(stage, self.path, lambda _: self.session)

    def test_apply_verify_and_restore_keep_exact_other_records_and_exit_stages(self):
        self.run_stage("apply")
        saved_plan = json.loads(self.path.read_text())
        self.assertEqual(saved_plan["status"], "applied_physical_input_and_reconnect_pending")
        self.assertEqual(json.loads(Path(saved_plan["pre_commit_backup"]).read_text()), self.original)
        self.assertEqual(self.session.current["buttons"][0]["data"], [0, 5])
        self.assertEqual(self.session.current["buttons"][1:], self.original["buttons"][1:])
        self.assertEqual(self.session.commands, ["onboard_read", "onboard_prepare", "onboard_commit", "onboard_read"])
        self.session.commands.clear()
        self.run_stage("verify")
        self.assertEqual(self.session.commands, ["onboard_read"])
        self.session.commands.clear()
        self.run_stage("restore")
        self.assertEqual(self.session.commands, ["onboard_read", "onboard_restore", "onboard_commit", "onboard_read"])
        self.assertEqual(self.session.current, self.original)
        self.assertEqual(json.loads(self.path.read_text())["status"], "restored_exactly_physical_input_check_pending")

    def test_tampered_backup_and_repeated_apply_stop_before_device_access(self):
        for change in ({"backup_sha256": "bad"}, {"status": "applying"}):
            self.path.write_text(json.dumps({**self.plan, **change}))
            with self.assertRaises(ValueError):
                self.run_stage("apply")
            self.assertEqual(self.session.commands, [])

    def test_changed_live_state_stops_before_prepare_or_commit(self):
        self.session.current["buttons"][1]["data"] = [0, 6]
        with self.assertRaises(ValueError):
            self.run_stage("apply")
        self.assertEqual(self.session.commands, ["onboard_read"])

    def test_durable_plan_failure_prevents_commit_acknowledgement(self):
        with patch.object(controlled, "durable_plan", side_effect=OSError("fsync failed")):
            with self.assertRaises(OSError):
                self.run_stage("apply")
        self.assertEqual(self.session.commands, ["onboard_read", "onboard_prepare"])
        self.assertEqual(self.session.current, self.original)
