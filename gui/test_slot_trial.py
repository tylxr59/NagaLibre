"""Approval and one-shot gates for the hardware trial (no mouse access)."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "slot_trial_runner", Path(__file__).resolve().parent.parent / "scripts/slot_trial.py")
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


class SlotTrialTests(unittest.TestCase):
    def test_prepare_only_reads_and_requires_every_slot_before_plan(self):
        snapshot = {"device": {"product": 0xA7, "serial": "PRIVATE", "path": "fake"},
                    "mode": [0, 0], "active": 1, "slot": 1,
                    "slots": [1, 2], "slot_capacity": 5, "primary": [], "buttons": []}
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            engine = base / "engine"
            engine.write_bytes(b"engine")
            directory = base / "trial"
            with patch.object(trial, "read_slot", side_effect=[snapshot, snapshot, dict(snapshot, slot=2)]) as read:
                with patch("builtins.print"):
                    trial.prepare(directory, engine)
            self.assertEqual([call.args[1:] for call in read.call_args_list], [(), (1,), (2,)])
            plan = json.loads((directory / "plan.json").read_text())
            self.assertEqual(plan["target"], 3)
            self.assertEqual(len(plan["snapshots"]), 2)
            self.assertEqual((directory / "plan.json").stat().st_mode & 0o777, 0o600)
            manifest = json.loads((directory / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "prepared")

    def test_invalid_approval_changed_engine_and_repeat_never_launch(self):
        for case in ("approval", "engine", "repeat", "plan", "runner"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                engine = base / "engine"
                engine.write_bytes(b"engine")
                plan = base / "plan.json"
                trial.durable(plan, {"format": 1, "target": 3, "snapshots": []})
                approval = trial.digest(plan)
                manifest = {"status": "prepared", "engine": str(engine),
                            "engine_sha256": trial.digest(engine),
                            "runner_sha256": trial.digest(Path(trial.__file__)),
                            "plan_sha256": approval}
                if case == "approval":
                    approval = None
                elif case == "engine":
                    engine.write_bytes(b"changed")
                elif case == "repeat":
                    manifest["status"] = "attempted"
                elif case == "plan":
                    plan.write_text("{}")
                else:
                    manifest["runner_sha256"] = "different"
                trial.durable(base / "manifest.json", manifest)
                with patch.object(trial.subprocess, "run") as launch:
                    with self.assertRaises(ValueError):
                        trial.run(base, approval)
                    launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
