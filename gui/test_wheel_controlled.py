"""Controlled wheel trial gates, exact preservation, and restore without hardware."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from model import new_profile
from onboard import hardware_buttons

SPEC = importlib.util.spec_from_file_location(
    "wheel_controlled", Path(__file__).resolve().parent.parent / "scripts/wheel_controlled_test.py")
wheel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wheel)


class FakeSession:
    def __init__(self):
        original = {"format": 1, "device": {"serial": "TEST", "product": 0xA7, "path": "fake"},
                    "mode": [0, 0], "slot": 1, "active": 1, "slots": [1, 2], "slot_capacity": 5,
                    "primary": [{"button": n, "category": 1, "data": [n]} for n in (1, 2)],
                    "buttons": hardware_buttons(new_profile()),
                    "controls": [{"button": 13, "category": 1, "data": [4]},
                                 {"button": 14, "category": 1, "data": [5]},
                                 {"button": 15, "category": 18, "data": [4]},
                                 {"button": 16, "category": 6, "data": [6]}]}
        self.snapshots = {n: copy.deepcopy(dict(original, slot=n)) for n in (1, 2)}
        self.commands = []
        self.selected = None
        self.pending = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def command(self, name, **arguments):
        self.commands.append(name)
        if name == "onboard_read":
            self.selected = arguments.get("slot") or 1
            return {"type": "onboard_snapshot", "snapshot": copy.deepcopy(self.snapshots[self.selected])}
        if name == "onboard_prepare":
            self.pending = copy.deepcopy(self.snapshots[self.selected])
            self.pending["controls"] = [copy.deepcopy(next((b for b in arguments["controls"] if b["button"] == old["button"]), old))
                                        for old in self.pending["controls"]]
        elif name == "onboard_restore":
            self.selected = arguments["backup"]["slot"]
            self.pending = copy.deepcopy(arguments["backup"])
        elif name == "onboard_commit":
            self.snapshots[self.selected] = self.pending
            return {"type": "onboard_saved", "snapshot": copy.deepcopy(self.pending)}
        else:
            raise AssertionError(name)
        return {"type": "onboard_prepared", "token": "123", "backup": copy.deepcopy(self.snapshots[self.selected])}


class WheelTrialTests(unittest.TestCase):
    def test_plate_events_are_filtered_and_wrong_plate_aborts(self):
        session = wheel.WheelSession(Path("unused"))
        with patch.object(wheel.Session, "receive", side_effect=[
            {"type": "faceplate", "module_id": 3, "buttons": 12},
            {"type": "onboard_snapshot", "snapshot": {}},
        ]):
            self.assertEqual(session.receive()["type"], "onboard_snapshot")
        with patch.object(wheel.Session, "receive", return_value={
            "type": "faceplate", "module_id": 4, "buttons": 6,
        }):
            with self.assertRaises(ValueError):
                session.receive()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.directory = base / "trial"
        self.engine = base / "engine"
        self.engine.write_bytes(b"engine")
        self.session = FakeSession()
        self.original = copy.deepcopy(self.session.snapshots)
        with patch("builtins.print"):
            wheel.prepare(self.directory, self.engine, 13, lambda _: self.session)
        self.session.commands.clear()

    def run_stage(self, stage):
        return wheel.run_stage(stage, self.directory, lambda _: self.session)

    def test_prepare_getters_then_apply_verify_exact_restore_and_no_repeat(self):
        self.assertEqual(self.session.snapshots, self.original)
        def check_commit(path, snapshot, token):
            self.assertEqual(snapshot, self.original[1])
            return original_writer(path, snapshot, token)
        original_writer = wheel.write_backup
        with patch.object(wheel, "write_backup", side_effect=check_commit):
            self.assertIn("Only left tilt", self.run_stage("apply"))
        self.assertEqual(self.session.snapshots[2], self.original[2])
        wheel.verify_changed(self.session.snapshots[1], self.original[1], 13)
        self.assertIn("B readback verified", self.run_stage("verify"))
        with self.assertRaises(ValueError):
            self.run_stage("apply")
        self.assertIn("Exact original", self.run_stage("restore"))
        self.assertEqual(self.session.snapshots, self.original)

    def test_changed_engine_stops_before_session(self):
        self.engine.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.run_stage("apply")
        self.assertEqual(self.session.commands, [])

    def test_backup_failure_prevents_commit(self):
        with patch.object(wheel, "write_backup", side_effect=OSError("fsync failed")):
            with self.assertRaises(OSError):
                self.run_stage("apply")
        self.assertNotIn("onboard_commit", self.session.commands)
        self.assertEqual(self.session.snapshots, self.original)

    def test_other_slot_change_prevents_prepare(self):
        self.session.snapshots[2]["controls"][2]["data"] = [99]
        with self.assertRaises(ValueError):
            self.run_stage("apply")
        self.assertNotIn("onboard_prepare", self.session.commands)

    def test_status_is_consumed_durably_before_commit(self):
        durable = wheel.durable_plan
        def fail_status(path, data):
            if data.get("stage") == "applying":
                raise OSError("directory fsync failed")
            return durable(path, data)
        with patch.object(wheel, "durable_plan", side_effect=fail_status):
            with self.assertRaises(OSError):
                self.run_stage("apply")
        self.assertNotIn("onboard_commit", self.session.commands)


if __name__ == "__main__":
    unittest.main()
