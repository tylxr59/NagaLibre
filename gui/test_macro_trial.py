"""Controlled macro trial checkpoints and mandatory recovery; no hardware."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import macro_controlled_test as trial


def state():
    normal = {"device": {"path": "mock", "serial": "TEST", "product": 0xa7},
              "slot": 1, "buttons": [{"button": 1, "category": 2, "data": [0, 4]}]}
    return {"guard": {"device": normal["device"].copy(), "active": 1},
            "mappings": [{"normal": normal, "hypershift": {"opaque": [255]}}],
            "storage": {"max_macros": 100, "storage_bytes": 126976, "stored_count": 0,
                        "free_bytes": 125696, "reclaimable_bytes": 1024, "entries": []}}


class MacroTrialTests(unittest.TestCase):
    def run_trial(self, directory, *, failure=None, physical=False, timeline="keys"):
        original = state()
        backup = {"kind": "onboard_macro_transaction_backup", "complete_profile": False,
                  "contents": {"inspection": original}}
        entry = {"id": 7, "metadata": [0] * 250, "data": [1, 5, 2, 5]}
        after = copy.deepcopy(original)
        after["storage"].update(stored_count=1, entries=[entry])
        commands = []
        def query(engine, command, *args):
            commands.append(command)
            if command == "onboard-macro-prepare":
                return backup
            if command == "onboard-macro-apply":
                self.assertEqual(json.loads(Path(args[0]).read_text()), backup)
                self.assertTrue((directory / "offline-plan.json").is_file())
                Path(args[1]).write_text("owned test journal")
                if failure == "apply":
                    raise subprocess.CalledProcessError(1, "apply")
                result = copy.deepcopy(after)
                if failure == "readback":
                    result["storage"]["entries"][0]["data"].append(255)
                return result
            self.assertEqual(command, "onboard-macro-recover")
            return copy.deepcopy(original)
        offline = subprocess.CompletedProcess([], 0, json.dumps({"entry": entry}))
        with patch.object(trial, "query", side_effect=query), \
                patch.object(trial.subprocess, "run", return_value=offline):
            if failure:
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    trial.trial(Path("engine"), directory, "once", physical=physical, observe=lambda _: "passed", timeline=timeline)
            else:
                trial.trial(Path("engine"), directory, "once", physical=physical, observe=lambda _: "user observation", timeline=timeline)
        return commands

    def test_backup_plan_apply_and_final_recovery_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "trial"
            commands = self.run_trial(directory)
            self.assertEqual(commands, ["onboard-macro-prepare", "onboard-macro-apply", "onboard-macro-recover"])
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            for name in ("trial.toml", "request.json", "backup.json", "before.json", "applied.json", "recovered.json"):
                self.assertEqual((directory / name).stat().st_mode & 0o777, 0o600)
            observations = json.loads((directory / "observations.json").read_text())
            self.assertFalse(observations["physical_testing_requested"])
            self.assertIsNone(observations["outputs"])

    def test_lost_apply_ack_or_readback_mismatch_always_attempts_recovery(self):
        for failure in ("apply", "readback"):
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "trial"
                commands = self.run_trial(directory, failure=failure)
                self.assertEqual(commands[-1], "onboard-macro-recover")
                self.assertTrue((directory / "recovered.json").is_file())

    def test_physical_observations_are_saved_separately_from_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "trial"
            self.run_trial(directory, physical=True)
            observed = json.loads((directory / "observations.json").read_text())
            self.assertEqual(observed["outputs"], "user observation")
            self.assertEqual(observed["reconnect"], "user observation")

    def test_shortcut_trial_failure_still_recovers_and_invalid_mode_never_prepares(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "trial"
            commands = self.run_trial(directory, timeline="shortcut", failure="readback")
            self.assertEqual(commands[-1], "onboard-macro-recover")
            with patch.object(trial, "query") as query:
                with self.assertRaises(ValueError):
                    trial.trial(Path("engine"), Path(tmp) / "invalid", "toggle", timeline="shortcut")
                query.assert_not_called()
                self.assertFalse((Path(tmp) / "invalid").exists())

    def test_failed_backup_prevents_apply_and_new_guard_or_content_is_not_accepted_as_restored(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(trial, "query", return_value={
                "kind": "onboard_macro_transaction_backup", "complete_profile": False}) as query, \
                patch.object(trial, "durable_plan", side_effect=OSError("fsync")):
            with self.assertRaises(OSError):
                trial.trial(Path("engine"), Path(tmp) / "trial", "once", physical=False)
            query.assert_not_called()
        for key in ("guard", "mappings", "storage"):
            original = state()
            after = copy.deepcopy(original)
            if key == "guard":
                after["guard"]["active"] = 2
            elif key == "mappings":
                after["mappings"][0]["normal"]["buttons"][0]["data"] = [0, 5]
            else:
                after["storage"]["entries"].append({"id": 7})
            with self.assertRaises(ValueError):
                trial.restored(original, after)


if __name__ == "__main__":
    unittest.main()
