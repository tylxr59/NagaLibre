"""Physical trial orchestration: backup before writes and restore before returning."""
import importlib.util
import json
from pathlib import Path
import subprocess
import os
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("custom_trial", Path(__file__).resolve().parent.parent / "scripts/trial_haptic_custom.py")
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


class CustomTrialTests(unittest.TestCase):
    def test_cli_blocks_new_apply_before_reading_checkpoint_but_preserves_recovery_route(self):
        engine = Path(os.environ.get("NAGALIBRE_TEST_BACKEND", str(Path(__file__).resolve().parent.parent / "target/debug/naga-macros")))
        args = [str(engine), "haptic-unit-velocity-trial", "--checkpoint", "/nonexistent/nagalibre-checkpoint",
                "--journal", "/nonexistent/nagalibre-journal"]
        applied = subprocess.run(args, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(applied.returncode, 0)
        self.assertIn("Custom trial apply is blocked", applied.stderr)
        restored = subprocess.run([*args, "--restore"], capture_output=True, text=True, timeout=5)
        self.assertNotEqual(restored.returncode, 0)
        self.assertNotIn("Custom trial apply is blocked", restored.stderr)

    def test_other_historical_custom_apply_commands_are_gated_before_file_or_device_access(self):
        engine = Path(os.environ.get("NAGALIBRE_TEST_BACKEND", str(Path(__file__).resolve().parent.parent / "target/debug/naga-macros")))
        for name, argument, reason in [
            ("haptic-independent-replay", "--checkpoint", "save/commit lifecycle"),
            ("haptic-upload-replay", "--backup", "stored table getters can alias"),
            ("haptic-table-probe", "--backup", "firmware requires a complete upload"),
        ]:
            with self.subTest(command=name):
                args = [str(engine), name, argument, "/nonexistent/nagalibre-checkpoint", "--journal", "/nonexistent/nagalibre-journal"]
                result = subprocess.run(args, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(reason, result.stderr)
                recovery = subprocess.run([*args,"--restore"], capture_output=True, text=True, timeout=5)
                self.assertNotEqual(recovery.returncode, 0)
                self.assertNotIn(reason, recovery.stderr)

    def fixture(self, tmp):
        engine = Path(tmp) / "engine"
        engine.write_bytes(b"helper")
        checkpoint = Path(tmp) / "checkpoint.json"
        checkpoint.write_text('{"format":1,"kind":"haptic_independent_checkpoint"}')
        self.directory = Path(tmp) / "trial"
        self.calls = []
        self.auto_recovered = False
        return engine, checkpoint

    def helper(self, args, **kwargs):
        self.calls.append(args)
        self.assertIn("haptic-unit-velocity-trial", args)
        plan = json.loads((self.directory / "plan.json").read_text())
        self.assertEqual(plan["backup_sha256"], trial.digest(self.directory / "original-wheel.json"))
        self.assertEqual((self.directory / "original-wheel.json").stat().st_mode & 0o777, 0o600)
        if "--restore" in args:
            self.assertEqual(plan["status"], "restoring")
            result = {"format": 1, "kind": "haptic_independent_replay_result", "restored_exactly": True,
                      "active_table_verification": "selector_zero"}
        else:
            self.assertEqual(plan["status"], "applying")
            (self.directory / "helper-journal.jsonl").write_text("private root journal stand-in")
            result = {"format": 1, "kind": "haptic_unit_velocity_trial_result", "applied": not self.auto_recovered,
                      "restored_exactly": self.auto_recovered, "active_table_verification": "selector_zero"}
        return subprocess.CompletedProcess(args, 0, json.dumps(result))

    def test_trial_observation_and_restored_feel_are_separate_after_exact_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, checkpoint = self.fixture(tmp)
            def after(_):
                self.assertEqual(len(self.calls), 2)
                self.assertIn("--restore", self.calls[1])
                return {"verdict": "yes", "answer": "y; original feel back"}
            with patch.object(trial.subprocess, "run", side_effect=self.helper), patch("builtins.input", return_value="ratcheting; reconnect worked"), patch.object(trial, "ask_match", side_effect=after):
                trial.run(engine, self.directory, checkpoint)
            plan = json.loads((self.directory / "plan.json").read_text())
            self.assertEqual(plan["status"], "restored_exactly")
            self.assertEqual(plan["user_observation"], "ratcheting; reconnect worked")
            self.assertEqual(plan["original_feel_after_restore"]["verdict"], "yes")

    def test_ctrl_c_and_eof_restore_before_propagating(self):
        for failure in (KeyboardInterrupt, EOFError):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                engine, checkpoint = self.fixture(tmp)
                with patch.object(trial.subprocess, "run", side_effect=self.helper), patch("builtins.input", side_effect=failure), self.assertRaises(failure):
                    trial.run(engine, self.directory, checkpoint)
                self.assertEqual(len(self.calls), 2)
                self.assertEqual(json.loads((self.directory / "plan.json").read_text())["status"], "restored_exactly")

    def test_apply_failure_already_recovered_does_not_prompt_or_restore_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, checkpoint = self.fixture(tmp)
            self.auto_recovered = True
            with patch.object(trial.subprocess, "run", side_effect=self.helper), patch("builtins.input") as prompt:
                trial.run(engine, self.directory, checkpoint)
            prompt.assert_not_called()
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(json.loads((self.directory / "plan.json").read_text())["status"], "restored_exactly")

    def test_full_mismatch_receipt_is_saved_in_user_private_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, checkpoint = self.fixture(tmp)
            self.auto_recovered = True
            mismatch = {"slot": 1, "fields": ["tables[2]"], "expected": {"tables": [1]}, "observed": {"tables": [2]}}
            def helper(args, **kwargs):
                result = self.helper(args, **kwargs)
                report = json.loads(result.stdout)
                report["state_mismatch"] = mismatch
                result.stdout = json.dumps(report)
                return result
            with patch.object(trial.subprocess, "run", side_effect=helper), patch("builtins.input") as prompt:
                trial.run(engine, self.directory, checkpoint)
            prompt.assert_not_called()
            path = self.directory / "applied.json"
            self.assertEqual(json.loads(path.read_text())["state_mismatch"], mismatch)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_backup_prevents_hardware_and_wrong_helper_prevents_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, checkpoint = self.fixture(tmp)
            with patch.object(trial, "durable_plan", side_effect=OSError("fsync")), patch.object(trial.subprocess, "run") as helper, self.assertRaises(OSError):
                trial.run(engine, self.directory, checkpoint)
            helper.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp:
            engine, checkpoint = self.fixture(tmp)
            with patch.object(trial.subprocess, "run", side_effect=self.helper), patch("builtins.input", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                trial.run(engine, self.directory, checkpoint)
            plan_path = self.directory / "plan.json"
            plan = json.loads(plan_path.read_text()); plan["status"] = "applied"
            plan_path.write_text(json.dumps(plan)); engine.write_bytes(b"changed")
            with patch.object(trial.subprocess, "run") as helper, self.assertRaisesRegex(ValueError, "Helper changed"):
                trial.invoke(self.directory, restore=True)
            helper.assert_not_called()
