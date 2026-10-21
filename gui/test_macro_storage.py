"""Onboard macro drafts, actual readbacks and backup-before-commit behavior."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from backend import Backend
from macro_storage import OnboardMacrosDialog, inventory_rows, macro_config, write_macro_backup

APP = QApplication.instance() or QApplication([])


class MockBackend(QObject):
    event = Signal(dict)
    connected = Signal(bool)
    log = Signal(str)
    def __init__(self):
        super().__init__()
        self.ready = True
        self.onboard_macros = True
        self.messages = []
        self.stopped = False
    def send(self, message):
        self.messages.append(copy.deepcopy(message))
    def shutdown(self):
        self.stopped = True
    def start(self):
        pass


def snapshot():
    normal = {"slot": 1, "buttons": [{"button": i, "category": 2, "data": [0, 4]} for i in range(1, 13)],
              "controls": [{"button": i, "category": 6, "data": [6]} for i in range(13, 17)]}
    secondary = copy.deepcopy(normal)
    return {"format": 1, "kind": "onboard_macro_diagnostic", "restorable": False,
            "guard": {"active": 1, "device": {"serial": "TEST"}},
            "mappings": [{"normal": normal, "hypershift": secondary}],
            "storage": {"stored_count": 0, "max_macros": 100, "free_bytes": 125696,
                        "reclaimable_bytes": 1024, "entries": []}}


def backup():
    return {"format": 1, "kind": "onboard_macro_transaction_backup", "complete_profile": False,
            "contents": {"kind": "onboard_macro_storage_checkpoint", "inspection": snapshot()},
            "mappings": {"kind": "paired_mapping_backup", "opaque": [255, 42]}}


class MacroStorageGuiTests(unittest.TestCase):
    def dialog(self, root):
        engine = MockBackend()
        dialog = OnboardMacrosDialog(Path(root) / "profiles.json", backend=engine,
                                     steps=[{"tap": "KEY_B"}])
        self.addCleanup(dialog.close)
        dialog.on_event({"type": "macro_snapshot", "snapshot": snapshot()})
        return dialog, engine

    def test_draft_and_playback_changes_do_not_write_and_targets_exclude_primary_clicks(self):
        with tempfile.TemporaryDirectory() as root:
            dialog, engine = self.dialog(root)
            self.assertEqual([dialog.target.itemData(i) for i in range(dialog.target.count())], list(range(1, 17)))
            for mode in range(5):
                dialog.playback.setCurrentIndex(mode)
                dialog.layer.setCurrentIndex(1)
                dialog.target.setCurrentIndex(15)
                self.assertEqual(engine.messages, [])
                self.assertEqual(dialog.snapshot["storage"]["entries"], [])
                self.assertEqual(dialog.count.isEnabled(), mode == 1)
            self.assertIn("125,696", dialog.capacity.text())

    def test_prepare_then_private_durable_backup_precedes_commit(self):
        with tempfile.TemporaryDirectory() as root:
            dialog, engine = self.dialog(root)
            dialog.playback.setCurrentIndex(1)
            dialog.count.setValue(255)
            dialog.save()
            request = engine.messages[-1]
            self.assertEqual(request["command"], "macro_prepare")
            self.assertEqual(request["request"]["playback"], {"mode": "counted", "count": 255})
            self.assertIn("KEY_F24", request["config"])
            self.assertTrue(dialog.busy)
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.on_event({"type": "macro_prepared", "token": "123", "backup": backup()})
            commit = engine.messages[-1]
            self.assertEqual(commit["command"], "macro_commit")
            journal = Path(commit["journal"])
            saved = journal.with_suffix("").with_suffix(".json")
            self.assertEqual(json.loads(saved.read_text()), backup())
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            self.assertEqual(saved.parent.stat().st_mode & 0o777, 0o700)
            self.assertFalse(journal.exists())
            dialog.on_event({"type": "macro_error", "message": "test complete"})

    def test_backup_or_directory_fsync_failure_prevents_commit_and_stops_helper(self):
        for failure in ("save_profile", "os.fsync"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                dialog, engine = self.dialog(root)
                dialog.save()
                with patch("macro_storage." + failure, side_effect=OSError("disk failure")):
                    dialog.on_event({"type": "macro_prepared", "token": "456", "backup": backup()})
                self.assertEqual([m["command"] for m in engine.messages], ["macro_prepare"])
                self.assertTrue(engine.stopped)
                self.assertIn("no macro commit", dialog.status.text())
                self.assertIsNone(dialog.snapshot)

    def test_actual_readback_survives_successful_helper_exit_but_errors_invalidate(self):
        with tempfile.TemporaryDirectory() as root:
            dialog, engine = self.dialog(root)
            after = snapshot()
            after["mappings"][0]["normal"]["buttons"][0] = {"button": 1, "category": 3, "data": [0x12, 0x34, 1]}
            after["storage"]["entries"] = [{"id": 0x1234, "metadata": [0] * 20 + list(b"Copy") + [0] * 226, "data": [1, 5, 2, 5]}]
            after["storage"]["stored_count"] = 1
            dialog.on_event({"type": "macro_saved", "snapshot": after, "journal": "/private/transaction.jsonl"})
            engine.ready = False
            dialog.connected(False)
            self.assertEqual(dialog.snapshot, after)
            self.assertIn("Macro 1234", dialog.stored.text())
            self.assertEqual(dialog.inventory.item(0, 0).text(), "Copy")
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.error("read failed")
            self.assertIsNone(dialog.snapshot)
            self.assertEqual(dialog.inventory.rowCount(), 0)
            self.assertEqual(dialog.capacity.text(), "Storage: unread")

    def test_invalid_names_and_empty_sequences_fail_before_prepare(self):
        for name, steps in [("é" * 51, [{"tap": "KEY_B"}]), ("", [{"tap": "KEY_B"}]), ("Valid", [])]:
            with tempfile.TemporaryDirectory() as root:
                dialog, engine = self.dialog(root)
                dialog.name.setText(name)
                dialog.steps = steps
                dialog.save()
                self.assertEqual(engine.messages, [])

    def test_read_errors_disconnect_and_plate_changes_clear_stored_values(self):
        for kind in ("error", "disconnect", "faceplate"):
            with tempfile.TemporaryDirectory() as root:
                dialog, engine = self.dialog(root)
                if kind == "error":
                    dialog.on_event({"type": "macro_error", "message": "bad getter"})
                elif kind == "disconnect":
                    engine.ready = False
                    dialog.connected(False)
                else:
                    dialog.on_event({"type": "faceplate", "module_id": 4})
                self.assertIsNone(dialog.snapshot)
                self.assertFalse(dialog.save_button.isEnabled())
                self.assertEqual(dialog.capacity.text(), "Storage: unread")

    def test_macro_draft_config_uses_sequence_outputs_without_learning_a_trigger(self):
        config = macro_config([{"down": "CTRL"}, {"tap": "B"}, {"up": "CTRL"}, {"wait_ms": 256}])
        self.assertIn('"KEY_F24"', config)
        self.assertIn('"KEY_LEFTCTRL"', config)
        self.assertIn("wait_ms = 256", config)
        self.assertEqual(config.count("[[binding]]"), 1)
        raw = snapshot()
        raw["storage"]["entries"] = [{"id": 7, "metadata": [255] * 250, "data": [254]}]
        self.assertEqual(inventory_rows(raw)[0][1:], ("0007", "1"))

    def test_private_backup_rejects_reuse_invalid_token_and_public_directory(self):
        with tempfile.TemporaryDirectory() as root:
            profile = Path(root) / "profiles.json"
            write_macro_backup(profile, backup(), "1")
            for token in ("1", "../bad", "", 1):
                with self.assertRaises((ValueError, TypeError)):
                    write_macro_backup(profile, backup(), token)
            (profile.parent / "backups" / "macros").chmod(0o755)
            with self.assertRaises(ValueError):
                write_macro_backup(profile, backup(), "2")

    def test_real_process_bridge_prepares_saves_exits_reconnects_and_undoes(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            state = root / "state.json"
            state.write_text(json.dumps(snapshot()))
            engine = root / "engine"
            engine.write_text("#!/usr/bin/env python3\n" + "\n".join([
                "import json,sys,pathlib,copy",
                f"root=pathlib.Path({str(root)!r});path=root/'state.json'",
                f"original={snapshot()!r};backup={backup()!r}",
                "def emit(v): print(json.dumps(v),flush=True)",
                "emit({'type':'hello','protocol':4,'onboard_macros':True})",
                "for line in sys.stdin:",
                " m=json.loads(line);c=m['command']",
                " if c=='shutdown':break",
                " if c=='faceplate':emit({'type':'faceplate','module_id':3,'buttons':12});continue",
                " if c=='macro_read':emit({'type':'macro_snapshot','snapshot':json.loads(path.read_text())})",
                " elif c=='macro_prepare':emit({'type':'macro_prepared','token':'789','backup':backup})",
                " elif c=='macro_commit':",
                "  assert m['token']=='789'",
                "  assert json.loads((root/'backups/macros/TEST-macro-789.json').read_text())==backup",
                "  journal=pathlib.Path(m['journal']);journal.write_text('owned mock journal')",
                "  s=copy.deepcopy(original);s['storage']['stored_count']=1",
                "  s['storage']['entries']=[{'id':7,'metadata':[0]*250,'data':[1,5,2,5]}]",
                "  path.write_text(json.dumps(s));emit({'type':'macro_saved','snapshot':s,'journal':str(journal)});break",
                " elif c=='macro_recover':",
                "  assert pathlib.Path(m['journal']).read_text()=='owned mock journal'",
                "  path.write_text(json.dumps(original));emit({'type':'macro_recovered','snapshot':original,'journal':m['journal']});break",
                " else:raise ValueError(c)",
            ]))
            engine.chmod(0o700)
            def wait(predicate):
                until = time.monotonic() + 5
                while not predicate() and time.monotonic() < until:
                    APP.processEvents()
                    time.sleep(0.005)
                self.assertTrue(predicate())
            with patch.dict(os.environ, {"NAGALIBRE_BACKEND": str(engine), "NAGALIBRE_NO_PKEXEC": "1"}):
                bridge = Backend()
                dialog = OnboardMacrosDialog(root / "profiles.json", backend=bridge, steps=[{"tap": "KEY_B"}])
                try:
                    dialog.read()
                    wait(lambda: dialog.snapshot is not None)
                    dialog.save()
                    wait(lambda: dialog.saved and not bridge.ready)
                    journal = dialog.last_journal
                    with patch("macro_storage.QFileDialog.getOpenFileName", return_value=(journal, "")):
                        dialog.undo()
                    wait(lambda: dialog.saved and not bridge.ready)
                    self.assertEqual(json.loads(state.read_text()), snapshot())
                    self.assertIn("restored", dialog.status.text())
                finally:
                    bridge.shutdown()
                    dialog.busy = False
                    dialog.close()


if __name__ == "__main__":
    unittest.main()
