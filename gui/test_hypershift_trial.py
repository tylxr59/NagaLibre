"""The trial must persist recovery data before acknowledging a write token."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "hypershift_trial", Path(__file__).resolve().parent.parent / "scripts/hypershift_test.py")
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


def initial():
    normal = {"device": {"path": "fake", "serial": "TEST", "product": 167},
              "slot": 1, "active": 1, "mode": [0, 0], "slots": [1],
              "buttons": [{"button": n, "category": 2, "data": [0, 29+n]} for n in range(1, 13)],
              "controls": [{"button": n, "category": 0, "data": []} for n in range(13, 17)]}
    secondary = {"layer": 1, "primary_inspected": False,
                 "buttons": copy.deepcopy(normal["buttons"]), "controls": copy.deepcopy(normal["controls"]),
                 "echoes": [{"button": n, "layer": 0} for n in range(1, 17)]}
    secondary["buttons"][0]["raw_record"] = [2, 1, 0, 30, 0, 0, 0]
    secondary["controls"][0] = {"button": 13, "category": 14, "data": [104], "raw_record": [14, 1, 104, 0, 20, 0, 0]}
    return {"format": 1, "normal": normal, "hypershift": secondary,
            "normal_echoes": [{"button": n, "layer": 0} for n in range(1,17)]}


class FakeSession:
    def __init__(self):
        self.state = initial()
        self.hello = {"hypershift_transactions": True}
        self.commands = []
        self.restore = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def command(self, name, **arguments):
        self.commands.append(name)
        if name == "onboard_layers_read":
            return {"type": "onboard_layers_snapshot", "snapshot": copy.deepcopy(self.state)}
        if name in ("onboard_layers_prepare", "onboard_layers_restore"):
            self.restore = arguments.get("backup")
            return {"type": "onboard_layers_prepared", "token": "test-token",
                    "backup": {"format": 1, "kind": "paired_mapping_backup", "slots": [
                        {"state": copy.deepcopy(self.state), "middle": {"button": 3, "category": 1, "data": [3]}}]}}
        if name == "onboard_commit":
            if self.restore:
                self.state = copy.deepcopy(self.restore["slots"][0]["state"])
            else:
                self.state["hypershift"]["buttons"][0] = copy.deepcopy(trial.EDITS[0]["action"])
                self.state["normal"]["controls"][3] = copy.deepcopy(trial.EDITS[1]["action"])
                self.state["normal_echoes"][0]["layer"] = 1
                self.state["hypershift"]["echoes"][0]["layer"] = 1
            return {"type": "onboard_layers_saved", "snapshot": copy.deepcopy(self.state)}
        raise AssertionError(name)


class HypershiftTrialTests(unittest.TestCase):
    def setup_trial(self, root):
        engine = root / "engine"
        engine.write_bytes(b"test helper")
        session = FakeSession()
        directory = root / "private"
        trial.prepare(directory, engine, lambda _: session)
        self.assertNotIn("onboard_commit", session.commands)
        self.assertEqual((directory / "original.json").stat().st_mode & 0o777, 0o600)
        return directory, session

    def test_preparation_then_apply_verify_restore_preserves_opaque_raw_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, session = self.setup_trial(Path(temporary))
            for stage in ("apply", "verify", "restore"):
                trial.run_stage(stage, directory, lambda _: session)
            self.assertEqual(session.state, initial())
            self.assertEqual(json.loads((directory / "status.json").read_text())["stage"], "restored")
            with self.assertRaisesRegex(ValueError, "already attempted"):
                trial.run_stage("apply", directory, lambda _: session)

    def test_failed_recovery_backup_never_sends_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, session = self.setup_trial(Path(temporary))
            with patch.object(trial, "durable_plan", side_effect=OSError("fsync failed")):
                with self.assertRaisesRegex(OSError, "fsync failed"):
                    trial.run_stage("apply", directory, lambda _: session)
            self.assertNotIn("onboard_commit", session.commands)
            self.assertEqual(session.state, initial())

    def test_stale_secondary_tail_prevents_prepare_and_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, session = self.setup_trial(Path(temporary))
            session.commands.clear()
            session.state["hypershift"]["controls"][0]["raw_record"][6] = 1
            with self.assertRaisesRegex(ValueError, "record or tracked state changed"):
                trial.run_stage("apply", directory, lambda _: session)
            self.assertNotIn("onboard_layers_prepare", session.commands)
            self.assertNotIn("onboard_commit", session.commands)

    def test_applied_echo_metadata_is_checked_on_both_requests_and_unrelated_echo_changes_fail(self):
        original = initial()
        actual = initial()
        actual["hypershift"]["buttons"][0] = copy.deepcopy(trial.EDITS[0]["action"])
        actual["normal"]["controls"][3] = copy.deepcopy(trial.EDITS[1]["action"])
        actual["normal_echoes"][0]["layer"] = 1
        actual["hypershift"]["echoes"][0]["layer"] = 1
        trial.check_state(actual, original, applied=True)
        for bank in ("normal_echoes", "hypershift"):
            wrong = copy.deepcopy(actual)
            echoes = wrong[bank] if bank == "normal_echoes" else wrong[bank]["echoes"]
            echoes[1]["layer"] = 1
            with self.assertRaisesRegex(ValueError, "record or tracked state changed"):
                trial.check_state(wrong, original, applied=True)

    def test_helper_failure_after_commit_ack_leaves_apply_attempted(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, session = self.setup_trial(Path(temporary))
            original = session.command

            def lost_reply(name, **arguments):
                result = original(name, **arguments)
                if name == "onboard_commit":
                    raise ValueError("Helper reply lost")
                return result

            session.command = lost_reply
            with self.assertRaisesRegex(ValueError, "reply lost"):
                trial.run_stage("apply", directory, lambda _: session)
            self.assertEqual(json.loads((directory / "status.json").read_text())["stage"], "applying")
            self.assertTrue((directory / "apply-recovery.json").is_file())
            with self.assertRaisesRegex(ValueError, "already attempted"):
                trial.run_stage("apply", directory, lambda _: session)


if __name__ == "__main__":
    unittest.main()
