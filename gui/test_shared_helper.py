"""Shared editor lifetime and exclusive event handling, without real devices."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from app import Window
from haptic import WheelDialog
from macro_storage import OnboardMacrosDialog
from test_gui_hypershift import paired_state
from test_haptic import MockBackend as WheelBackend, snapshot as wheel_snapshot, backup as wheel_backup
from test_macro_storage import MockBackend as MacroBackend, snapshot as macro_snapshot, backup as macro_backup


class SharedHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate())

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_one_process_across_main_macros_wheel_and_back_with_fresh_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = root / "engine"
            engine.write_text("#!/usr/bin/env python3\n" + "\n".join([
                "import json,sys,pathlib,os",
                "if sys.argv[1]!='session':print('[]');sys.exit(0)",
                f"root=pathlib.Path({str(root)!r})",
                "with (root/'starts').open('a') as f:f.write(str(os.getpid())+'\\n')",
                "def emit(m):print(json.dumps(m),flush=True)",
                "emit({'type':'hello','protocol':4,'device':{'id':'naga_v2_pro'},'onboard_macros':True,'haptic_settings':True})",
                "plate=False",
                "for line in sys.stdin:",
                " m=json.loads(line);c=m['command']",
                " with (root/'commands').open('a') as f:f.write(line)",
                " if c=='shutdown':break",
                " if c=='faceplate' and not plate:",
                "  plate=True;emit({'type':'faceplate','module_id':3,'buttons':12})",
                f" elif c=='onboard_read':emit({{'type':'onboard_snapshot','snapshot':{paired_state()['normal']!r}}})",
                f" elif c=='macro_read':emit({{'type':'macro_snapshot','snapshot':{macro_snapshot()!r}}})",
                f" elif c=='haptic_read':emit({{'type':'haptic_snapshot','snapshot':{wheel_snapshot()!r}}})",
                " elif c=='monitor':emit({'type':'state','state':'monitoring'})",
            ]))
            engine.chmod(0o700)
            with patch.dict(os.environ, {"NAGALIBRE_BACKEND": str(engine), "NAGALIBRE_NO_PKEXEC": "1"}):
                window = Window(root / "profiles.json")
                window.scan_timer.stop()
                try:
                    window.connect_mouse()
                    self.wait(lambda: window.snapshot is not None and not window.hardware_busy)
                    pid = window.backend.process.processId()
                    window.mode.setCurrentIndex(window.mode.findData("key"))
                    window.key_value.setText("B")

                    def commands():
                        return [json.loads(line)["command"] for line in (root / "commands").read_text().splitlines()]

                    def visit(dialog):
                        self.assertIs(dialog.backend, window.backend)
                        self.assertIs(window.active_editor, dialog)
                        if hasattr(dialog, "hardware_accessed"):
                            self.assertFalse(dialog.hardware_accessed)
                            dialog.read()
                        else:
                            self.assertIsNone(window.snapshot)
                        self.assertFalse(window.apply_button.isEnabled())
                        self.wait(lambda: dialog.snapshot is not None and not dialog.busy)
                        self.assertEqual(window.backend.process.processId(), pid)
                        before = commands().count("onboard_read")
                        window.backend.event.emit({"type": "faceplate", "module_id": 3, "buttons": 12})
                        window.backend.event.emit({"type": "error", "message": "editor-only failure"})
                        self.assertIn("editor-only failure", dialog.status.text())
                        self.assertFalse(window.fault)
                        self.assertEqual(commands().count("onboard_read"), before)
                        dialog.read()
                        self.wait(lambda: dialog.snapshot is not None and not dialog.busy)
                        dialog.reject()
                        self.assertFalse(dialog.backend_attached)
                        self.assertTrue(window.backend.ready)
                        return 0

                    with patch.object(OnboardMacrosDialog, "exec", new=visit):
                        window.open_onboard_macros()
                    self.wait(lambda: window.snapshot is not None and not window.hardware_busy)
                    self.assertEqual(window.buttons()[0]["value"], "B")
                    with patch.object(WheelDialog, "exec", new=visit):
                        window.open_wheel_settings()
                    self.wait(lambda: window.snapshot is not None and not window.hardware_busy)
                    self.assertIsNone(window.active_editor)
                    self.assertEqual(window.backend.process.processId(), pid)
                    self.assertEqual(len((root / "starts").read_text().splitlines()), 1)
                    self.assertNotIn("shutdown", commands())
                finally:
                    window.backend.shutdown()
                    window.quitting = True
                    window.close()
                    window.deleteLater()

    def test_local_library_preserves_running_software_and_does_not_request_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / 'profile.json')
            window.scan_timer.stop()
            window.applying = True
            window.pending_config = 'pending software configuration'

            def visit(dialog):
                self.assertFalse(dialog.hardware_accessed)
                self.assertTrue(window.applying)
                dialog.reject()
                return 0

            try:
                self.assertTrue(window.onboard_macros_button.isEnabled())
                with patch.object(window.backend, 'start') as start, \
                     patch.object(window.backend, 'send') as send, \
                     patch.object(OnboardMacrosDialog, 'exec', new=visit):
                    window.open_onboard_macros()
                    start.assert_not_called()
                    send.assert_not_called()
                self.assertTrue(window.applying)
                self.assertEqual(window.pending_config, 'pending software configuration')
            finally:
                window.quitting = True
                window.close()
                window.deleteLater()

    def test_shared_close_detaches_handlers_and_busy_close_keeps_transaction(self):
        for dialog_type, backend_type in ((WheelDialog, WheelBackend), (OnboardMacrosDialog, MacroBackend)):
            with self.subTest(editor=dialog_type.__name__), tempfile.TemporaryDirectory() as directory:
                backend = backend_type()
                dialog = dialog_type(Path(directory) / "profile.json", backend=backend, shared=True)
                dialog.busy = True
                dialog.reject()
                self.assertTrue(dialog.backend_attached)
                self.assertFalse(backend.stopped)
                dialog.busy = False
                dialog.reject()
                self.assertFalse(dialog.backend_attached)
                self.assertFalse(backend.stopped)
                # A closed editor must not acknowledge a later prepared event.
                backend.event.emit({"type": "macro_prepared" if dialog_type is OnboardMacrosDialog else "haptic_prepared",
                                    "token": "123", "backup": {}})
                self.assertEqual(backend.messages, [])
                dialog.deleteLater()

    def test_macro_navigation_defers_unseen_assignments_until_they_are_needed(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Path(directory) / "profile.json")
            window.scan_timer.stop()
            window.workspace.show_page(3)
            window.backend.ready = True
            window.backend.protocol = 4
            window.backend.onboard_macros = True

            def visit(dialog):
                dialog.on_event({"type": "macro_snapshot", "snapshot": macro_snapshot()})
                dialog.reject()
                return 0

            try:
                with patch.object(window.backend, "send") as send, \
                     patch.object(OnboardMacrosDialog, "exec", new=visit):
                    window.connection_changed(True)
                    window.on_event({"type": "faceplate", "module_id": 3, "buttons": 12})
                    window.open_onboard_macros()
                    commands = lambda: [c.args[0]["command"] for c in send.call_args_list]
                    self.assertNotIn("onboard_read", commands())
                    self.assertEqual(commands().count("macro_read"), 0)
                    self.assertIsNone(window.snapshot)
                    self.assertFalse(window.apply_button.isEnabled())
                    window.workspace.show_page(0)
                    self.assertEqual(commands().count("onboard_read"), 1)
                    window.workspace.show_page(3)
                    window.workspace.show_page(0)
                    self.assertEqual(commands().count("onboard_read"), 1)
            finally:
                window.backend.ready = False
                window.set_hardware_busy(False)
                window.quitting = True
                window.close()
                window.deleteLater()

    def test_shared_backup_failure_still_ends_session_without_commit(self):
        cases = ((WheelDialog, WheelBackend, "haptic", wheel_backup(), "haptic_prepared"),
                 (OnboardMacrosDialog, MacroBackend, "macro_storage", macro_backup(), "macro_prepared"))
        for dialog_type, backend_type, module, backup, kind in cases:
            with self.subTest(editor=dialog_type.__name__), tempfile.TemporaryDirectory() as directory:
                backend = backend_type()
                dialog = dialog_type(Path(directory) / "profile.json", backend=backend, shared=True)
                writer = "write_haptic_backup" if module == "haptic" else "write_macro_backup"
                with patch(f"{module}.{writer}", side_effect=OSError("fsync failed")):
                    backend.event.emit({"type": kind, "token": "123", "backup": backup})
                self.assertTrue(backend.stopped)
                self.assertEqual(backend.messages, [])
                self.assertIn("Backup failed", dialog.status.text())
                dialog.reject()
                dialog.deleteLater()

    def test_saved_editors_end_helper_without_starting_another_connection(self):
        for editor, snapshot, kind in ((WheelDialog, wheel_snapshot(), "haptic_saved"),
                                       (OnboardMacrosDialog, macro_snapshot(), "macro_saved")):
            with self.subTest(editor=editor.__name__), tempfile.TemporaryDirectory() as directory:
                window = Window(Path(directory) / "profile.json")
                window.scan_timer.stop()
                window.backend.ready = True
                window.backend.haptic_settings = window.backend.onboard_macros = True

                def finish(dialog):
                    dialog.on_event({"type": kind, "snapshot": snapshot})
                    self.assertTrue(dialog.saved)
                    dialog.reject()
                    return 0

                def disconnect():
                    window.backend.ready = False
                    window.backend.connected.emit(False)

                try:
                    with patch.object(editor, "exec", new=finish), \
                         patch.object(window.backend, "send"), \
                         patch.object(window.backend, "shutdown", side_effect=disconnect) as shutdown, \
                         patch.object(window.backend, "start") as start, \
                         patch.object(window, "read_mouse") as read:
                        window.run_hardware_editor(editor)
                        shutdown.assert_called_once()
                        start.assert_not_called()
                        read.assert_not_called()
                        self.assertIsNone(window.snapshot)
                        self.assertFalse(window.apply_button.isEnabled())
                finally:
                    window.backend.ready = False
                    window.quitting = True
                    window.close()
                    window.deleteLater()

    def test_disconnect_during_editor_read_invalidates_state_and_allows_close(self):
        for editor, backend_type in ((WheelDialog, WheelBackend), (OnboardMacrosDialog, MacroBackend)):
            with self.subTest(editor=editor.__name__), tempfile.TemporaryDirectory() as directory:
                backend = backend_type()
                dialog = editor(Path(directory) / "profile.json", backend=backend, shared=True)
                dialog.read()
                self.assertTrue(dialog.busy)
                backend.ready = False
                backend.connected.emit(False)
                self.assertIsNone(dialog.snapshot)
                self.assertFalse(dialog.busy)
                self.assertFalse(dialog.save_button.isEnabled())
                dialog.reject()
                self.assertFalse(dialog.backend_attached)
                dialog.deleteLater()
