"""Guided presets use verified identities, restore between tests, and stop on uncertainty."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_haptic_trial import trial


class GuidedPresetTests(unittest.TestCase):
    def fixture(self, directory):
        engine = directory / "engine"
        engine.write_bytes(b"mock")
        starting = {"format": 1, "kind": "haptic_diagnostic", "guard": {"device": {"path": "mock", "serial": "TEST"}},
                    "state": {"stages": [133, 129, 132, 131, 130], "active_position": 1}}
        class Session:
            hello = {"haptic_settings": True}
            def __init__(self, engine):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def command(self, command, **arguments):
                if command != "haptic_read":
                    raise AssertionError("Guided coordinator may only read; writes belong to the backed-up trial")
                return {"type": "haptic_snapshot", "snapshot": copy.deepcopy(starting)}
        return engine, starting, Session

    def test_guided_uses_existing_positions_named_presets_and_waits_for_restoration(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            engine, starting, session = self.fixture(directory)
            calls = []
            prompts = []
            def run(engine, child, position, **kwargs):
                calls.append((child.name, position, kwargs))
                return {"status": "restored_exactly", "user_observation": {"verdict": "yes", "answer": "y"}}
            def ask(prompt):
                # Every transition follows a completed trial and a prompt about
                # the original feel, rather than overlapping settings changes.
                self.assertEqual(len(calls), len(prompts) + 1)
                prompts.append(prompt)
                return {"verdict": "yes", "answer": "y"}
            with patch.object(trial, "Session", session), patch.object(trial, "trial", side_effect=run), patch.object(trial, "ask_match", side_effect=ask):
                trial.guided(engine, directory / "guided")
            self.assertEqual([c[1] for c in calls], [2, 5, 4, 3, 1])
            self.assertEqual([c[2]["preset"] for c in calls], [129, 130, 131, 132, 133])
            self.assertTrue(all(c[2]["expected_start"] == starting and c[2]["allow_unchanged"] for c in calls))
            self.assertTrue(all("Smooth Scroll" in prompt for prompt in prompts))
            plan = json.loads((directory / "guided/guided-plan.json").read_text())
            self.assertEqual(plan["status"], "completed")
            self.assertEqual(len(plan["steps"]), 5)

    def test_uncertain_original_feel_stops_before_another_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            engine, _, session = self.fixture(directory)
            with patch.object(trial, "Session", session), patch.object(trial, "trial", return_value={"status": "restored_exactly", "user_observation": {"verdict": "no", "answer": "n"}}) as run, patch.object(trial, "ask_match", return_value={"verdict": "unsure", "answer": "unsure"}):
                trial.guided(engine, directory / "guided")
            run.assert_called_once()
            plan = json.loads((directory / "guided/guided-plan.json").read_text())
            self.assertEqual(plan["status"], "physical_restore_uncertain")
            self.assertEqual(plan["steps"][0]["observation"]["verdict"], "no")

    def test_interrupt_does_not_advance_to_another_trial(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            engine, _, session = self.fixture(directory)
            with patch.object(trial, "Session", session), patch.object(trial, "trial", side_effect=KeyboardInterrupt) as run:
                with self.assertRaises(KeyboardInterrupt):
                    trial.guided(engine, directory / "guided")
            run.assert_called_once()
            plan = json.loads((directory / "guided/guided-plan.json").read_text())
            self.assertEqual(plan["status"], "interrupted")
            self.assertTrue(plan["current_trial"].endswith("preset-standard"))

    def test_invalid_input_reprompts_and_quit_interrupts(self):
        with patch("builtins.input", side_effect=["maybe", "y feels correct"]):
            self.assertEqual(trial.ask_match("Standard?"), {"verdict": "yes", "answer": "y feels correct"})
        with patch("builtins.input", return_value="y; everything is working well"):
            self.assertEqual(trial.ask_match("Restored?")["verdict"], "yes")
        with patch("builtins.input", return_value="q"):
            with self.assertRaises(KeyboardInterrupt):
                trial.ask_match("Standard?")

    def test_missing_or_extra_presets_do_not_start_a_trial_or_assume_a_five_press_cycle(self):
        for stages in [[129, 133], [129, 130, 131, 132, 133, 134]]:
            with self.subTest(stages=stages), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                engine, starting, session = self.fixture(directory)
                starting["state"]["stages"] = stages
                with patch.object(trial, "Session", session), patch.object(trial, "trial") as run:
                    with self.assertRaisesRegex(ValueError, "five built-in presets"):
                        trial.guided(engine, directory / "guided")
                run.assert_not_called()

    def test_starting_state_check_allows_new_path_but_rejects_device_or_wheel_changes(self):
        before = {"guard": {"device": {"path": "old", "serial": "same"}}, "state": {"active_position": 5}}
        after = copy.deepcopy(before)
        after["guard"]["device"]["path"] = "new"
        self.assertTrue(trial.same_starting_state(before, after))
        after["state"]["active_position"] = 1
        self.assertFalse(trial.same_starting_state(before, after))
        self.assertEqual(before["guard"]["device"]["path"], "old")


if __name__ == "__main__":
    unittest.main()
