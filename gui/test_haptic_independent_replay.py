"""Independent replay uses durable zero-view provenance and its own recovery route."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("independent_replay", Path(__file__).resolve().parent.parent / "scripts/replay_haptic_independent.py")
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)
import replay_haptic_upload as shared


class ReplayTests(unittest.TestCase):
    def prepare(self, tmp):
        engine = Path(tmp) / "engine"
        engine.write_bytes(b"helper")
        checkpoint = Path(tmp) / "checkpoint.json"
        checkpoint.write_text(json.dumps({"format": 1, "kind": "haptic_independent_checkpoint", "table_views": {"stable": True}}))
        directory = Path(tmp) / "trial"
        with patch.object(replay, "invoke"):
            replay.run(engine, directory, checkpoint)
        return engine, checkpoint, directory

    def test_durable_copy_and_helper_hash_precede_independent_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, checkpoint, first = self.prepare(tmp)
            directory = Path(tmp) / "second"

            def invoke(path, **kwargs):
                self.assertEqual(kwargs, {"restore_only": False, "independent": True})
                plan = json.loads((path / "plan.json").read_text())
                self.assertEqual(plan["status"], "probing")
                self.assertEqual(plan["engine_sha256"], shared.checksum(engine))
                self.assertEqual(plan["backup_sha256"], shared.checksum(path / "original-wheel.json"))
                self.assertEqual(json.loads((path / "original-wheel.json").read_text()), json.loads(checkpoint.read_text()))

            with patch.object(replay, "invoke", side_effect=invoke) as called:
                replay.run(engine, directory, checkpoint)
            called.assert_called_once()
            self.assertEqual((directory / "original-wheel.json").stat().st_mode & 0o777, 0o600)

    def test_legacy_checkpoint_or_failed_fsync_never_invokes_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, checkpoint, _ = self.prepare(tmp)
            with patch.object(replay, "durable_plan", side_effect=OSError("fsync")), patch.object(replay, "invoke") as writer:
                with self.assertRaises(OSError):
                    replay.run(engine, Path(tmp) / "failed", checkpoint)
                writer.assert_not_called()
            checkpoint.write_text('{"format":1,"kind":"haptic_settings_backup"}')
            with patch.object(replay, "invoke") as writer, self.assertRaises(ValueError):
                replay.run(engine, Path(tmp) / "legacy", checkpoint)
            writer.assert_not_called()

    def test_independent_arguments_and_receipt_are_required(self):
        for valid in (False, True):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as tmp:
                _, _, directory = self.prepare(tmp)
                report = {"format": 1, "kind": "haptic_independent_replay_result", "restore_only": False,
                          "restored_exactly": True, "probe_passed": True}
                if valid:
                    report["active_table_verification"] = "selector_zero"

                def run(args, **kwargs):
                    self.assertIn("haptic-independent-replay", args)
                    self.assertIn("--checkpoint", args)
                    self.assertNotIn("--backup", args)
                    return subprocess.CompletedProcess(args, 0, json.dumps(report))

                with patch.object(shared.subprocess, "run", side_effect=run):
                    if valid:
                        shared.invoke(directory, restore_only=False, independent=True)
                    else:
                        with self.assertRaisesRegex(ValueError, "independent active-table"):
                            shared.invoke(directory, restore_only=False, independent=True)
                status = json.loads((directory / "plan.json").read_text())["status"]
                self.assertEqual(status, "restored_exactly" if valid else "probing")

    def test_recovery_requires_matching_plan_and_unchanged_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, _, directory = self.prepare(tmp)
            with patch.object(shared.subprocess, "run") as writer:
                with self.assertRaises(ValueError):
                    shared.invoke(directory, restore_only=True)
                engine.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "Helper changed"):
                    shared.invoke(directory, restore_only=True, independent=True)
                writer.assert_not_called()
