"""Wheel drafts and the durable backup boundary, using a mock helper."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QApplication
from haptic import WheelDialog, stage_edit, write_haptic_backup, describe_custom
from backend import Backend

APP = QApplication.instance() or QApplication([])


class MockBackend(QObject):
    event = Signal(dict)
    connected = Signal(bool)
    log = Signal(str)
    def __init__(self):
        super().__init__()
        self.ready = True
        self.haptic_settings = True
        self.messages = []
        self.stopped = False
    def send(self, message):
        self.messages.append(message)
    def shutdown(self):
        self.stopped = True
    def start(self):
        pass


def snapshot():
    return {"format": 1, "kind": "haptic_diagnostic", "state": {"slot": 1,
            "stages": [129, 130, 133], "active_position": 3,
            "configuration": [1, 6, 1, 1] + [0] * 22, "metadata": [0] * 40,
            "tables": [[], [], []]}}


def backup():
    return {"format": 1, "kind": "haptic_settings_backup", "guard": {
        "device": {"serial": "TEST"}}, "slots": [{"opaque": [255]}]}


class WheelGuiTests(unittest.TestCase):
    def test_real_process_bridge_reads_saves_exits_reconnects_and_restores_stage_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "state.json"
            original = snapshot()
            state_path.write_text(json.dumps(original))
            engine = root / "engine"
            engine.write_text("#!/usr/bin/env python3\n" + "\n".join([
                "import json,sys,pathlib,time,copy",
                f"root=pathlib.Path({str(root)!r});path=root/'state.json'",
                "state=json.loads(path.read_text());pending=None;token=None",
                "def emit(value): print(json.dumps(value),flush=True)",
                "emit({'type':'hello','protocol':4,'haptic_settings':True})",
                "for line in sys.stdin:",
                " m=json.loads(line);name=m['command']",
                " if name=='shutdown':break",
                " if name=='haptic_read':emit({'type':'haptic_snapshot','snapshot':state})",
                " elif name in ('haptic_prepare','haptic_restore'):",
                "  pending=m;token=str(time.time_ns())",
                "  before={'format':1,'kind':'haptic_settings_backup','guard':{'device':{'serial':'TEST'}},'slots':[copy.deepcopy(state['state'])]}",
                "  emit({'type':'haptic_prepared','token':token,'backup':before})",
                " elif name=='haptic_commit':",
                "  assert m['token']==token",
                "  backup=root/'backups'/('TEST-wheel-'+token+'.json')",
                "  assert json.loads(backup.read_text())['kind']=='haptic_settings_backup'",
                "  if pending['command']=='haptic_restore':",
                "   before=pending['backup']['slots'][0]",
                "   edit={k:before[k] for k in ('stages','active_position')}",
                "  else:edit=pending['edit']",
                "  state['state'].update(edit);path.write_text(json.dumps(state))",
                "  emit({'type':'haptic_saved','snapshot':state});break",
                " else:raise ValueError(name)",
            ]))
            engine.chmod(0o700)

            def wait(predicate):
                deadline = time.monotonic() + 4
                while not predicate() and time.monotonic() < deadline:
                    APP.processEvents()
                    time.sleep(0.005)
                self.assertTrue(predicate())

            with patch.dict(os.environ, {"NAGALIBRE_BACKEND": str(engine), "NAGALIBRE_NO_PKEXEC": "1"}):
                dialog = WheelDialog(root / "profiles.json", backend=Backend())
                try:
                    dialog.read()
                    wait(lambda: dialog.snapshot is not None)
                    dialog.defaults()
                    dialog.active.setCurrentIndex(dialog.active.findData(132))
                    dialog.save()
                    wait(lambda: dialog.saved and not dialog.backend.ready)
                    self.assertEqual(dialog.active.currentData(),132)
                    saved = json.loads(state_path.read_text())
                    self.assertEqual(saved['state']['active_position'],4)
                    self.assertEqual(saved['state']['tables'],original['state']['tables'])
                    original_backup = next((root / "backups").glob("TEST-wheel-*.json"))
                    dialog.read()
                    wait(lambda: dialog.snapshot is not None and not dialog.busy)
                    with patch("haptic.QFileDialog.getOpenFileName", return_value=(str(original_backup),"")):
                        dialog.restore()
                    wait(lambda: dialog.saved and not dialog.backend.ready)
                    self.assertEqual(json.loads(state_path.read_text()),original)
                finally:
                    dialog.set_busy(False)
                    dialog.backend.shutdown()
                    dialog.deleteLater()

    def test_all_five_standard_modes_have_descriptions_and_save_correct_positions(self):
        for position, name in enumerate(["Standard", "Distinct", "Ultra-fine", "Adaptive", "Smooth Scroll"], 1):
            with self.subTest(mode=name):
                backend = MockBackend()
                dialog = WheelDialog(Path("profiles.json"), backend=backend)
                dialog.on_event({"type": "haptic_snapshot", "snapshot": snapshot()})
                dialog.defaults()
                self.assertEqual(dialog.active.count(), 5)
                dialog.active.setCurrentIndex(position - 1)
                self.assertEqual(dialog.active.currentText(), name)
                self.assertTrue(dialog.description.text())
                self.assertEqual(backend.messages, [])
                dialog.save()
                self.assertEqual(backend.messages[-1]["edit"], {"stages": [129,130,131,132,133], "active_position": position})
                dialog.set_busy(False)
                dialog.deleteLater()

    def test_disabling_modes_updates_cycle_positions_without_touching_stored_state(self):
        backend = MockBackend()
        dialog = WheelDialog(Path("profiles.json"), backend=backend)
        original = snapshot()
        dialog.on_event({"type": "haptic_snapshot", "snapshot": original})
        dialog.stages.item(1).setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(dialog.active.currentData(), 133)
        self.assertEqual(dialog.snapshot, original)
        self.assertEqual(backend.messages, [])
        dialog.save()
        self.assertEqual(backend.messages[-1]["edit"], {"stages": [129,133], "active_position": 2})
        dialog.set_busy(False)
        dialog.deleteLater()

    def test_existing_custom_is_preserved_by_defaults_and_not_offered_as_editable_mode(self):
        backend = MockBackend()
        dialog = WheelDialog(Path("profiles.json"), backend=backend)
        original = snapshot()
        original["state"]["stages"] = [129,134,133]
        dialog.on_event({"type": "haptic_snapshot", "snapshot": original})
        self.assertEqual(dialog.active.findData(134), -1)
        item = dialog.stages.item(1)
        self.assertFalse(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        self.assertFalse(item.flags() & Qt.ItemFlag.ItemIsDragEnabled)
        dialog.defaults()
        dialog.save()
        self.assertEqual(backend.messages[-1]["edit"], {"stages": [129,130,131,132,133,134], "active_position": 1})
        self.assertEqual(dialog.snapshot, original)
        dialog.set_busy(False)
        dialog.deleteLater()

    def test_active_custom_is_reported_without_silently_selecting_a_standard_draft(self):
        backend = MockBackend()
        dialog = WheelDialog(Path("profiles.json"), backend=backend)
        original = snapshot()
        original["state"]["stages"] = [129,134]
        original["state"]["active_position"] = 2
        dialog.on_event({"type": "haptic_snapshot", "snapshot": original})
        self.assertEqual(dialog.active.currentData(),134)
        self.assertFalse(dialog.active.model().item(dialog.active.currentIndex()).isEnabled())
        dialog.save()
        self.assertEqual(backend.messages, [])
        dialog.active.setCurrentIndex(dialog.active.findData(129))
        dialog.save()
        self.assertEqual(backend.messages[-1]["edit"], {"stages": [129,134], "active_position": 1})
        dialog.set_busy(False)
        dialog.deleteLater()

    def test_empty_draft_is_recoverable_without_losing_snapshot_and_unchanged_save_is_skipped(self):
        backend = MockBackend()
        dialog = WheelDialog(Path("profiles.json"), backend=backend)
        original = snapshot()
        dialog.on_event({"type": "haptic_snapshot", "snapshot": original})
        dialog.save()
        self.assertEqual(backend.messages, [])
        for row in range(dialog.stages.count()):
            dialog.stages.item(row).setCheckState(Qt.CheckState.Unchecked)
        dialog.save()
        self.assertEqual(dialog.snapshot, original)
        self.assertEqual(backend.messages, [])
        dialog.defaults()
        dialog.save()
        self.assertEqual(backend.messages[-1]["command"], "haptic_prepare")
        dialog.set_busy(False)
        dialog.deleteLater()

    def test_unknown_stages_are_readonly_and_closing_cannot_interrupt_save(self):
        backend = MockBackend()
        dialog = WheelDialog(Path("profiles.json"), backend=backend)
        original = snapshot()
        original["state"]["stages"] = [129,144]
        original["state"]["active_position"] = 1
        dialog.on_event({"type": "haptic_snapshot", "snapshot": original})
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertFalse(dialog.defaults_button.isEnabled())
        dialog.set_busy(True)
        dialog.reject()
        self.assertFalse(backend.stopped)
        self.assertFalse(dialog.close_buttons.isEnabled())
        dialog.set_busy(False)
        dialog.reject()
        self.assertTrue(backend.stopped)
        dialog.deleteLater()

    def test_ambiguous_velocity_table_is_identified_as_reported_not_verified_independent_data(self):
        state = snapshot()["state"]
        point = [0] * 8
        state["tables"] = [[point, [1] * 8], [point], [point]]
        text = describe_custom(state)
        self.assertIn("Reported table points", text)
        self.assertIn("independent down/velocity readback is unverified", text)

    def test_stage_positions_are_distinct_from_preset_ids(self):
        self.assertEqual(stage_edit([133, 129], 129), {"stages": [133, 129], "active_position": 2})
        for stages, active in [([], 129), ([129, 129], 129), ([129], 133), ([255], 255)]:
            with self.assertRaises(ValueError):
                stage_edit(stages, active)

    def test_defaults_are_draft_only_and_stored_values_survive(self):
        backend = MockBackend()
        dialog = WheelDialog(Path("profiles.json"), backend=backend)
        state = snapshot()
        dialog.on_event({"type": "haptic_snapshot", "snapshot": state})
        stored = dialog.stored.text()
        dialog.defaults()
        self.assertEqual(dialog.snapshot, state)
        self.assertEqual(dialog.stored.text(), stored)
        self.assertEqual(backend.messages, [])
        dialog.save()
        self.assertEqual(backend.messages[-1]["edit"], {"stages": [129, 130, 131, 132, 133], "active_position": 1})
        self.assertEqual(backend.messages[-1]["known"], state)
        dialog.deleteLater()

    def test_fsync_failure_prevents_commit_and_stops_helper(self):
        backend = MockBackend()
        with tempfile.TemporaryDirectory() as tmp:
            dialog = WheelDialog(Path(tmp) / "profiles.json", backend=backend)
            dialog.on_event({"type": "haptic_snapshot", "snapshot": snapshot()})
            with patch("haptic.os.fsync", side_effect=OSError("disk failure")):
                dialog.on_event({"type": "haptic_prepared", "token": "123", "backup": backup()})
            self.assertEqual(backend.messages, [])
            self.assertTrue(backend.stopped)
            self.assertIsNone(dialog.snapshot)
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.deleteLater()

    def test_durable_backup_precedes_ack_and_saved_disconnect_preserves_readback(self):
        backend = MockBackend()
        with tempfile.TemporaryDirectory() as tmp:
            dialog = WheelDialog(Path(tmp) / "profiles.json", backend=backend)
            dialog.on_event({"type": "haptic_prepared", "token": "123", "backup": backup()})
            path = Path(tmp) / "backups/TEST-wheel-123.json"
            self.assertEqual(json.loads(path.read_text()), backup())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(backend.messages, [{"command": "haptic_commit", "token": "123"}])
            state = snapshot()
            dialog.on_event({"type": "haptic_saved", "snapshot": state})
            dialog.connected(False)
            self.assertEqual(dialog.snapshot, state)
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.deleteLater()

    def test_failed_read_invalidates_stored_and_requires_fresh_read(self):
        backend = MockBackend()
        dialog = WheelDialog(Path("profiles.json"), backend=backend)
        dialog.on_event({"type": "haptic_snapshot", "snapshot": snapshot()})
        dialog.on_event({"type": "haptic_error", "message": "slot changed"})
        self.assertIsNone(dialog.snapshot)
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertIn("unread", dialog.stored.text())
        dialog.deleteLater()

    def test_diagnostics_are_not_accepted_as_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_haptic_backup(Path(tmp) / "profiles.json", snapshot(), "123")


if __name__ == "__main__":
    unittest.main()
