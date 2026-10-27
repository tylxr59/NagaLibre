"""Mouse-memory macro drafts: validation, upload jobs and the remaining binding edits."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from model import load_profile, new_profile, save_profile
from onboard import edits_change_mouse, layer_edits, onboard_macro_jobs, without_macros
from test_gui_hypershift import paired_state


def macro(library="lib-1", playback=None):
    return {"trigger": "", "mode": "macro", "value": "", "steps": [{"tap": "KEY_B"}],
            "library": library, "playback": playback or {"mode": "once"}}


class OnboardMacroDraftTests(unittest.TestCase):
    def round_trip(self, profile):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            save_profile(path, profile)
            return load_profile(path)

    def test_drafts_round_trip_in_both_layers_and_reject_invalid_playback(self):
        profile = new_profile()
        profile["plates"]["12"][0] = macro(playback={"mode": "counted", "count": 255})
        profile["controls"][3] = macro("lib-2", {"mode": "while_held"})
        profile["hypershift"][15] = macro("lib-3", {"mode": "toggle"})
        loaded = self.round_trip(profile)
        self.assertEqual(loaded["hypershift"][15]["library"], "lib-3")
        for bad in ({"mode": "counted", "count": 0}, {"mode": "counted"}, {"mode": "once", "count": 2},
                    {"mode": "forever"}, "once"):
            broken = copy.deepcopy(profile)
            broken["plates"]["12"][0]["playback"] = bad
            with self.assertRaises(ValueError):
                self.round_trip(broken)
        broken = copy.deepcopy(profile)
        broken["hypershift"][15].pop("library")
        with self.assertRaises(ValueError):
            self.round_trip(broken)

    def test_jobs_exclude_macros_from_binding_edits_and_detect_real_changes(self):
        profile = new_profile()
        profile["plates"]["12"][0] = macro()
        profile["controls"][3] = macro("lib-2")
        profile["hypershift"][2] = macro("lib-3")
        profile["plates"]["12"][2]["mode"] = "keep"  # Button 3 stores an unknown action.
        jobs = onboard_macro_jobs(profile)
        self.assertEqual([(layer, button) for layer, button, _ in jobs], [(0, 1), (0, 16), (1, 3)])
        with self.assertRaises(ValueError):
            layer_edits(profile)
        edits = layer_edits(without_macros(profile))
        self.assertNotIn((0, 1), {(e["layer"], e["action"]["button"]) for e in edits})
        self.assertEqual(profile["plates"]["12"][0]["mode"], "macro")  # The draft itself is untouched.
        self.assertFalse(edits_change_mouse(edits, paired_state()))
        profile["plates"]["12"][1].update(mode="key", value="B")
        self.assertTrue(edits_change_mouse(layer_edits(without_macros(profile)), paired_state()))

    def test_software_macros_without_library_reference_are_not_upload_jobs(self):
        profile = new_profile()
        profile["plates"]["12"][0].update(mode="macro", steps=[{"tap": "KEY_B"}])
        self.assertEqual(onboard_macro_jobs(profile), [])
        self.assertEqual(json.loads(json.dumps(self.round_trip(profile)))["plates"]["12"][0]["mode"], "macro")


if __name__ == "__main__":
    unittest.main()
