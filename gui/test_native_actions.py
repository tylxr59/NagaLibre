"""Traced native records, draft scope and read-only sensitivity/profile decoding."""
import copy
from pathlib import Path
import tempfile
import unittest

from model import new_profile, load_profile, save_profile, runtime_config, keep_binding, binding_label
from native_actions import NATIVE_ACTIONS, native_action
from onboard import draft_from_record, stored_label, layer_edits, hardware_buttons, hardware_controls


class NativeActions(unittest.TestCase):
    def test_traced_media_byte_order_and_profile_sensitivity_shapes(self):
        self.assertEqual(native_action("play_pause"), {"category": 10, "data": [0, 0xcd]})
        self.assertEqual(native_action("scroll_left"), {"category": 1, "data": [0x68]})
        for record, label in [
            ({"category": 6, "data": [5, 3, 32, 6, 64]}, "Temporary DPI · X 800, Y 1600 (release unverified)"),
            ({"category": 6, "data": [3, 2]}, "DPI stage selector 2"),
            ({"category": 6, "data": [7]}, "Cycle DPI stages down"),
            ({"category": 7, "data": [1]}, "Previous onboard profile"),
            ({"category": 7, "data": [2]}, "Next onboard profile"),
            ({"category": 7, "data": [4]}, "Cycle onboard profiles up"),
            ({"category": 7, "data": [5]}, "Cycle onboard profiles down"),
        ]:
            self.assertEqual(stored_label(record), label)
            self.assertEqual(draft_from_record({"button": 1, **record})["mode"], "keep")
        for category, data in [(10, [1, 0xcd]), (10, [0xcd, 0]), (10, [0, 0xb0]),
                               (6, [5, 3, 32]), (6, [3, 2, 0]), (7, [3])]:
            self.assertTrue(stored_label({"category": category, "data": data}).startswith("Action "))

    def test_known_records_become_native_drafts_without_altering_wire_metadata(self):
        for action in NATIVE_ACTIONS:
            record = {"button": 1, "category": action["category"], "data": action["data"],
                      "raw_record": [action["category"], len(action["data"]), *action["data"],
                                     *([17] * (5-len(action["data"])))]}
            original = copy.deepcopy(record)
            for secondary in (False, True):
                draft = draft_from_record(record, secondary)
                self.assertEqual(draft["mode"], "native")
                self.assertEqual(draft["value"], action["id"])
                self.assertEqual(binding_label(draft), action["label"])
                self.assertEqual(stored_label(record), action["label"])
            self.assertEqual(record, original)

    def test_both_layers_roundtrip_and_legacy_and_software_paths_reject(self):
        profile = new_profile()
        profile["plates"]["12"] = [keep_binding() for _ in range(12)]
        profile["plates"]["12"][0].update(mode="native", value="play_pause")
        profile["controls"][0].update(mode="native", value="volume_up")
        profile["hypershift"][15].update(mode="native", value="scroll_right")
        self.assertEqual(layer_edits(profile), [
            {"layer": 0, "action": {"button": 1, "category": 10, "data": [0, 0xcd]}},
            {"layer": 0, "action": {"button": 13, "category": 10, "data": [0, 0xe9]}},
            {"layer": 1, "action": {"button": 16, "category": 1, "data": [0x69]}},
        ])
        for convert in (hardware_buttons, hardware_controls, runtime_config):
            with self.assertRaises(ValueError):
                convert(profile)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            save_profile(path, profile)
            self.assertEqual(load_profile(path), profile)
            for value in ("launch_program", "temporary_dpi", "profile_cycle", "", None, []):
                profile["hypershift"][15]["value"] = value
                save_profile(path, profile)
                with self.assertRaises(ValueError):
                    load_profile(path)
                with self.assertRaises(ValueError):
                    layer_edits(profile)
            profile = new_profile()
            profile["plates"]["6"][0].update(mode="native", value="play_pause")
            save_profile(path, profile)
            with self.assertRaises(ValueError):
                load_profile(path)
