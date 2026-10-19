"""Read-only desktop checks preserve captured encodings and other slots."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from model import new_profile, default_control
from test_wheel_controlled import FakeSession

SPEC = importlib.util.spec_from_file_location(
    "check_defaults", Path(__file__).resolve().parent.parent / "scripts/check_defaults.py")
defaults = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(defaults)


class DefaultsChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "trial"
        self.engine = Path(self.temporary.name) / "engine"
        self.engine.write_bytes(b"engine")
        self.session = FakeSession()
        # Captured factory keyboard encoding: declared length one, two data bytes.
        self.session.snapshots[1]["buttons"][2]["raw_record"] = [2, 1, 0, 32, 0, 0, 0]
        self.original = copy.deepcopy(self.session.snapshots)
        with patch("builtins.print"):
            defaults.prepare(self.directory, self.engine, lambda _: self.session)

    def check(self, stage):
        with patch("builtins.print"), patch.object(defaults, "config_path", return_value=self.directory / "draft.json"):
            defaults.check(stage, self.directory, lambda _: self.session)

    def install_defaults(self):
        definitions = defaults.DEVICE_MODELS["naga_v2_pro"]["defaults"]["controls"]
        self.session.snapshots[1]["controls"] = [dict(button=c["button"], **c["binding"]) for c in definitions]

    def test_staged_saved_and_exact_restored_are_getters_only(self):
        self.check("staged")
        self.install_defaults()
        self.check("saved")
        self.session.snapshots = copy.deepcopy(self.original)
        self.check("restored")
        self.assertEqual(set(self.session.commands), {"onboard_read"})
        self.assertEqual(json.loads((self.directory / "original.json").read_text()), self.original[1])

    def test_draft_only_check_detects_an_actual_write(self):
        self.install_defaults()
        with self.assertRaisesRegex(ValueError, "differs"):
            self.check("staged")
        self.assertEqual(json.loads((self.directory / "status.json").read_text())["stage"], "prepared")

    def test_default_actions_do_not_allow_reencoding_unchanged_captured_records(self):
        self.check("staged")
        self.install_defaults()
        del self.session.snapshots[1]["buttons"][2]["raw_record"]
        with self.assertRaisesRegex(ValueError, "Unchanged records"):
            self.check("saved")

    def test_saved_check_detects_other_slot_change(self):
        self.check("staged")
        self.install_defaults()
        self.session.snapshots[2]["controls"][2]["data"] = [99]
        with self.assertRaisesRegex(ValueError, "differs"):
            self.check("saved")

    def test_tampered_backup_stops_before_opening_session(self):
        (self.directory / "original.json").write_text("{}")
        self.session.commands.clear()
        with self.assertRaisesRegex(ValueError, "backup changed"):
            self.check("restored")
        self.assertEqual(self.session.commands, [])

    def prepare_outputs(self):
        self.directory = Path(self.temporary.name) / "outputs"
        with patch("builtins.print"):
            defaults.prepare(self.directory, self.engine, lambda _: self.session, test="outputs")
        profile = new_profile()
        profile["plates"]["12"][0].update(mode="shortcut", value="Ctrl+A")
        profile["plates"]["12"][1].update(mode="key", value="BTN_RIGHT")
        defaults.durable_plan(self.directory / "draft.json", profile)
        self.check("staged")
        self.session.snapshots[1]["buttons"][:2] = [
            {"button": 1, "category": 2, "data": [1, 4]},
            {"button": 2, "category": 1, "data": [2]},
        ]

    def test_outputs_match_and_restore_with_no_settings_commands(self):
        self.prepare_outputs()
        self.check("saved")
        self.session.snapshots = copy.deepcopy(self.original)
        self.check("restored")
        self.assertEqual(set(self.session.commands), {"onboard_read"})

    def test_outputs_reject_incorrect_modifier(self):
        self.prepare_outputs()
        self.session.snapshots[1]["buttons"][0]["data"] = [0, 4]
        with self.assertRaisesRegex(ValueError, "expected test action"):
            self.check("saved")

    def test_outputs_reject_changed_control_or_unrelated_wire_encoding(self):
        self.prepare_outputs()
        self.session.snapshots[1]["controls"][0]["data"] = [0x68]
        with self.assertRaisesRegex(ValueError, "Another mapping"):
            self.check("saved")
        self.session.snapshots[1]["controls"] = copy.deepcopy(self.original[1]["controls"])
        del self.session.snapshots[1]["buttons"][2]["raw_record"]
        with self.assertRaisesRegex(ValueError, "Another mapping"):
            self.check("saved")

    def test_staged_rejects_factory_tilts_in_saved_draft_before_device_access(self):
        self.prepare_outputs()
        profile = json.loads((self.directory / "draft.json").read_text())
        profile["controls"] = [default_control(factory=True) for _ in range(4)]
        defaults.durable_plan(self.directory / "draft.json", profile)
        self.session.commands.clear()
        with self.assertRaisesRegex(ValueError, "Keep stored binding"):
            self.check("staged")
        self.assertEqual(self.session.commands, [])

    def test_failed_saved_readback_is_kept_as_private_evidence(self):
        self.prepare_outputs()
        self.session.snapshots[1]["controls"][0]["data"] = [0x68]
        with self.assertRaisesRegex(ValueError, "controls 13"):
            self.check("saved")
        captures = list(self.directory.glob("readback-saved-slot-1-*.json"))
        self.assertEqual(len(captures), 1)
        self.assertEqual(json.loads(captures[0].read_text()), self.session.snapshots[1])

    def receiver_session(self):
        for snapshot in self.session.snapshots.values():
            snapshot["device"]["product"] = 0xA8

    def test_receiver_backup_requires_explicit_connection_and_binds_later_checks(self):
        self.receiver_session()
        with self.assertRaisesRegex(ValueError, "Requires usb"):
            defaults.backup(Path(self.temporary.name) / "wrong", self.engine, lambda _: self.session)
        self.directory = Path(self.temporary.name) / "receiver"
        with patch("builtins.print"):
            defaults.prepare(self.directory, self.engine, lambda _: self.session, connection="receiver")
        self.check("staged")
        for snapshot in self.session.snapshots.values():
            snapshot["device"]["product"] = 0xA7
        with self.assertRaisesRegex(ValueError, "differs"):
            self.check("restored")
        self.assertEqual(set(self.session.commands), {"onboard_read"})

    def test_receiver_preparation_rejects_a_wired_mouse(self):
        with self.assertRaisesRegex(ValueError, "Requires receiver"):
            defaults.backup(Path(self.temporary.name) / "wrong", self.engine,
                            lambda _: self.session, connection="receiver")


if __name__ == "__main__":
    unittest.main()
