"""Durable checkpoint and recovery-only routing for the bounded table replay."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("probe_haptic_table", Path(__file__).resolve().parent.parent / "scripts/probe_haptic_table.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_checkpoint_precedes_helper_and_no_session_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "probe"
            engine = Path(tmp) / "engine"
            engine.write_bytes(b"helper")
            calls = []
            class Session:
                hello = {"haptic_settings": True}
                def __init__(self, _engine): pass
                def __enter__(self): return self
                def __exit__(self, *_): calls.append("closed")
                def command(self, name, **kw):
                    calls.append(name)
                    if name == "haptic_read":
                        return {"type": "haptic_snapshot", "snapshot": {"state": {"slot": 1, "active_position": 1, "stages": [133]}}}
                    if name == "haptic_prepare":
                        return {"type": "haptic_prepared", "backup": {"original": [1, 255]}}
                    raise AssertionError(name)
            def invoke(path, *, restore_only):
                self.assertFalse(restore_only)
                self.assertEqual(calls, ["haptic_read", "haptic_prepare", "closed"])
                plan = json.loads((path / "plan.json").read_text())
                self.assertEqual(plan["status"], "probing")
                self.assertEqual(plan["backup_sha256"], probe.checksum(path / "original-wheel.json"))
                self.assertEqual(json.loads((path / "original-wheel.json").read_text()), {"original": [1, 255]})
            with patch.object(probe, "Session", Session), patch.object(probe, "invoke", invoke):
                probe.run(engine, directory)

    def test_restore_routes_only_to_restore_and_completed_or_changed_hash_blocks(self):
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                engine = directory / "engine"
                engine.write_bytes(b"helper")
                backup = directory / "original-wheel.json"
                backup.write_text('{"original": true}')
                plan = {"status": "probing", "engine": str(engine), "engine_sha256": probe.checksum(engine), "backup_sha256": probe.checksum(backup)}
                probe.durable_plan(directory / "plan.json", plan)
                if changed:
                    backup.write_text('{}')
                def run(args, **kwargs):
                    self.assertIn("--restore", args)
                    self.assertEqual(json.loads((directory / "plan.json").read_text())["status"], "restoring")
                    return subprocess.CompletedProcess(args, 0, json.dumps({"format": 1, "kind": "haptic_table_replay_result", "restore_only": True, "restored_exactly": True, "probe_passed": False}))
                with patch.object(probe.subprocess, "run", side_effect=run) as process:
                    if changed:
                        with self.assertRaisesRegex(ValueError, "checksum"):
                            probe.invoke(directory, restore_only=True)
                        process.assert_not_called()
                    else:
                        probe.invoke(directory, restore_only=True)
                        self.assertFalse(json.loads((directory / "plan.json").read_text())["probe_passed"])
                        with self.assertRaisesRegex(ValueError, "completed"):
                            probe.invoke(directory, restore_only=True)
                        self.assertEqual(process.call_count, 1)

    def test_helper_failure_preserves_outstanding_plan_and_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            engine = directory / "engine"
            engine.write_bytes(b"helper")
            backup = directory / "original-wheel.json"
            backup.write_bytes(b'{"original":true}')
            plan = {"status": "probing", "engine": str(engine), "engine_sha256": probe.checksum(engine), "backup_sha256": probe.checksum(backup)}
            probe.durable_plan(directory / "plan.json", plan)
            with patch.object(probe.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "helper")):
                with self.assertRaises(subprocess.CalledProcessError):
                    probe.invoke(directory, restore_only=False)
            self.assertEqual(json.loads((directory / "plan.json").read_text()), plan)
            self.assertEqual(backup.read_bytes(), b'{"original":true}')
            self.assertFalse((directory / "result.json").exists())

    def test_rejected_but_restored_probe_is_not_reported_as_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            engine = directory / "engine"
            engine.write_bytes(b"helper")
            backup = directory / "original-wheel.json"
            backup.write_bytes(b'{}')
            plan = {"status": "probing", "engine": str(engine), "engine_sha256": probe.checksum(engine), "backup_sha256": probe.checksum(backup)}
            probe.durable_plan(directory / "plan.json", plan)
            report = {"format": 1, "kind": "haptic_table_replay_result", "restore_only": False, "restored_exactly": True, "probe_passed": False,
                      "probe_acknowledgement_error": "Mouse rejected 15/04: status 0x3",
                      "recovery": {"restore_acknowledgement_error": "Mouse rejected 15/04: status 0x3"}}
            with patch.object(probe.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(report))), patch("builtins.print") as output:
                probe.invoke(directory, restore_only=False)
            messages = "\n".join(str(call.args[0]) for call in output.call_args_list)
            self.assertIn("Replay acknowledgement: Mouse rejected 15/04: status 0x3", messages)
            self.assertIn("Original-byte replay acknowledgement: Mouse rejected 15/04: status 0x3", messages)
            saved = json.loads((directory / "plan.json").read_text())
            self.assertEqual(saved["status"], "restored_exactly")
            self.assertFalse(saved["probe_passed"])
