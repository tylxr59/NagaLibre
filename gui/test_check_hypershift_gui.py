"""Independent GUI verification uses getters and rejects unrelated changes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_hypershift_trial import FakeSession

SPEC = importlib.util.spec_from_file_location(
    "check_hypershift_gui", Path(__file__).resolve().parent.parent / "scripts/check_hypershift_gui.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class GuiHypershiftChecks(unittest.TestCase):
    def test_prepare_staged_saved_and_restored_never_commit_and_preserve_original_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "private"
            session = FakeSession()
            factory = lambda _: session
            checker.run("prepare", directory, Path("engine"), factory)
            original = (directory / "original.json").read_bytes()
            checker.run("staged", directory, Path("engine"), factory)
            session.state["normal"]["controls"][3].update(category=12, data=[1])
            session.state["hypershift"]["buttons"][0] = {"button": 1, "category": 2, "data": [0, 5]}
            session.state["normal_echoes"][0]["layer"] = 1
            session.state["hypershift"]["echoes"][0]["layer"] = 1
            checker.run("saved", directory, Path("engine"), factory)
            session.state = json.loads(original)["slots"][0]["state"]
            checker.run("restored", directory, Path("engine"), factory)
            self.assertEqual((directory / "original.json").read_bytes(), original)
            self.assertNotIn("onboard_commit", session.commands)
            self.assertTrue(all(name in ("onboard_layers_read", "onboard_layers_prepare") for name in session.commands))
            self.assertEqual((directory / "original.json").stat().st_mode & 0o777, 0o600)

    def test_staged_rejects_changes_in_raw_secondary_tail(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "private"
            session = FakeSession()
            checker.run("prepare", directory, Path("engine"), lambda _: session)
            session.state["hypershift"]["controls"][0]["raw_record"][6] = 1
            with self.assertRaisesRegex(ValueError, "tracked state changed"):
                checker.run("staged", directory, Path("engine"), lambda _: session)
            self.assertNotIn("onboard_commit", session.commands)

    def test_middle_click_is_compared_separately_from_changed_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "private"
            session = FakeSession()
            checker.run("prepare", directory, Path("engine"), lambda _: session)
            original_command = session.command

            def changed_middle(name, **arguments):
                result = original_command(name, **arguments)
                if result["type"] == "onboard_layers_prepared":
                    result["backup"]["slots"][0]["middle"]["data"] = [2]
                return result

            session.command = changed_middle
            with self.assertRaises(ValueError):
                checker.run("staged", directory, Path("engine"), lambda _: session)
            self.assertNotIn("onboard_commit", session.commands)
