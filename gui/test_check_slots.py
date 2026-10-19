"""Desktop slot checks allow only the planned activation/inventory changes."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_wheel_controlled import FakeSession

SPEC = importlib.util.spec_from_file_location(
    "check_slots", Path(__file__).resolve().parent.parent / "scripts/check_slots.py")
slots = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(slots)


class DesktopSlotChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "trial"
        self.engine = Path(self.temporary.name) / "engine"
        self.engine.write_bytes(b"engine")
        self.session = FakeSession()
        self.session.snapshots[1]["buttons"][2]["raw_record"] = [2, 1, 0, 32, 0, 0, 0]
        self.original = copy.deepcopy(self.session.snapshots)
        with patch("builtins.print"):
            slots.prepare(self.directory, self.engine, lambda _: self.session)

    def check(self, stage):
        with patch("builtins.print"):
            slots.check(stage, self.directory, lambda _: self.session)

    def activate(self, active):
        for snapshot in self.session.snapshots.values():
            snapshot["active"] = active

    def create(self):
        self.activate(2)
        self.check("activated")
        self.activate(1)
        self.check("switched-back")
        self.session.snapshots[3] = copy.deepcopy(dict(self.original[2], slot=3))
        for snapshot in self.session.snapshots.values():
            snapshot["slots"] = [1, 2, 3]

    def test_complete_sequence_and_repeat_persistence_checks_only_use_getters(self):
        self.create()
        self.check("created")
        self.activate(3)
        self.check("new-active")
        self.check("new-active")
        self.activate(1)
        self.check("restored")
        self.assertEqual(set(self.session.commands), {"onboard_read"})
        self.assertEqual(self.session.snapshots[1], slots.normalized(self.original[1], 1, [1, 2, 3]))

    def test_original_wire_change_is_rejected_after_activation(self):
        self.activate(2)
        del self.session.snapshots[1]["buttons"][2]["raw_record"]
        with self.assertRaisesRegex(ValueError, "Original slot 1"):
            self.check("activated")

    def test_creation_must_keep_original_slot_active(self):
        self.create()
        self.activate(3)
        with self.assertRaisesRegex(ValueError, "unexpectedly"):
            self.check("created")

    def test_bad_new_defaults_do_not_advance_status(self):
        self.create()
        self.session.snapshots[3]["buttons"][0]["data"] = [0, 5]
        with self.assertRaisesRegex(ValueError, "New grid defaults"):
            self.check("created")
        self.assertEqual(json.loads((self.directory / "status.json").read_text())["stage"], "switched-back")

    def test_new_slot_change_after_creation_is_rejected(self):
        self.create()
        self.check("created")
        self.activate(3)
        self.session.snapshots[3]["controls"][1]["data"] = [99]
        with self.assertRaisesRegex(ValueError, "New slot changed"):
            self.check("new-active")


if __name__ == "__main__":
    unittest.main()
