"""Navigation, embedded editors, and selected-button macro transactions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox
from app import Window
from test_macro_storage import APP, snapshot, backup
from test_gui_hypershift import paired_state
from test_haptic import snapshot as wheel_snapshot


class EmbeddedWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.window = Window(Path(self.root.name) / 'profiles.json')
        self.window.scan_timer.stop()

    def tearDown(self):
        window = self.window
        window.macro_assignment.busy = window.wheel_panel.busy = False
        window.active_editor = None
        window.hardware_busy = False
        window.quitting = True
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
            window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()
        self.root.cleanup()

    def save_macro(self):
        view = self.window.macro_library_view
        view.name.setText('Saved sequence')
        view.steps = [{'tap': 'KEY_B'}]
        self.assertTrue(view.save_local())
        return view

    def connect_fixture(self):
        window = self.window
        window.backend.ready = True
        window.backend.protocol = 4
        window.backend.onboard_macros = True
        window.backend.haptic_settings = True
        window.backend.hypershift_transactions = True
        window.detected_module = 3
        window.plate_detection = 'auto'
        window.on_event({'type': 'onboard_layers_snapshot', 'snapshot': paired_state()})

    def macro_snapshot(self, active=1):
        state = snapshot()
        state['guard']['active'] = active
        mapping = paired_state()
        mapping['normal'].update(slot=active, active=active)
        state['mappings'] = [mapping]
        return state

    def test_macros_and_scrolling_contain_editors_with_no_launcher_or_modal(self):
        window = self.window
        view = self.save_macro()
        view.steps = [{'tap': 'KEY_C'}]
        with patch.object(window.backend, 'start') as start, patch.object(window.backend, 'send') as send:
            window.open_onboard_macros()
            self.assertEqual(window.workspace.pages.currentIndex(), 3)
            self.assertFalse(window.workspace.device_tabs.isVisible())
            window.workspace.show_page(0)
            window.open_wheel_settings()
            self.assertEqual(window.workspace.pages.currentIndex(), 2)
            window.workspace.show_page(3)
            self.assertEqual(view.steps, [{'tap': 'KEY_C'}])
            self.assertIsNone(window.active_editor)
            self.assertFalse(hasattr(window, 'onboard_macros_button'))
            self.assertFalse(hasattr(window, 'wheel_settings_button'))
            start.assert_not_called()
            send.assert_not_called()

    def test_saved_library_macro_is_assigned_to_selected_software_button(self):
        window = self.window
        self.save_macro().steps = [{'tap': 'KEY_C'}]
        window.storage.setCurrentIndex(window.storage.findData('software'))
        window.select_button(5)
        window.mode.setCurrentIndex(window.mode.findData('macro'))
        with patch.object(window.backend, 'send') as send, patch.object(window.backend, 'start') as start:
            window.macro_assignment.save()
            self.assertEqual(window.current()['steps'], [{'tap': 'KEY_B'}])
            self.assertEqual(window.current()['mode'], 'macro')
            self.assertEqual(window.buttons()[0]['steps'], [])
            send.assert_not_called()
            start.assert_not_called()

    def test_selected_hypershift_control_upload_keeps_backup_before_commit(self):
        window = self.window
        self.save_macro().steps = [{'tap': 'KEY_C'}]
        with patch.object(window.backend, 'send') as send, patch.object(window.backend, 'shutdown') as shutdown:
            self.connect_fixture()
            window.layer.setCurrentIndex(1)
            window.select_button(15)
            window.mode.setCurrentIndex(window.mode.findData('macro'))
            panel = window.macro_assignment
            panel.save()
            self.assertIs(window.active_editor, panel)
            self.assertTrue(window.hardware_busy)
            self.assertFalse(window.workspace.buttons[3].isEnabled())
            window.backend.event.emit({'type': 'macro_snapshot', 'snapshot': self.macro_snapshot()})
            request = send.call_args.args[0]
            self.assertEqual(request['command'], 'macro_prepare')
            self.assertEqual(request['request']['button'], 16)
            self.assertEqual(request['request']['layer'], 1)
            self.assertIn('KEY_B', request['config'])
            self.assertNotIn('KEY_C', request['config'])
            self.assertNotIn('macro_commit', [c.args[0]['command'] for c in send.call_args_list])
            window.backend.event.emit({'type': 'macro_prepared', 'token': '123', 'backup': backup()})
            commit = send.call_args.args[0]
            self.assertEqual(commit['command'], 'macro_commit')
            self.assertTrue(Path(commit['journal'].replace('.journal.jsonl', '.json')).exists())
            final = self.macro_snapshot()
            final['mappings'][0]['hypershift']['controls'][3].update(category=3, data=[0, 1, 1])
            window.backend.event.emit({'type': 'macro_saved', 'snapshot': final, 'journal': commit['journal']})
            APP.processEvents()
            self.assertIsNone(window.active_editor)
            self.assertFalse(window.hardware_busy)
            self.assertTrue(window.workspace.buttons[3].isEnabled())
            self.assertEqual(window.current()['mode'], 'keep')
            self.assertIn('Macro 0001', window.stored_text(15))
            self.assertEqual(window.hardware_saved, 1)
            shutdown.assert_called_once()
            window.backend.ready = False
            window.backend.connected.emit(False)
            self.assertIn('Macro 0001', window.stored_text(15))

    def test_slot_change_aborts_assignment_before_preparation(self):
        window = self.window
        self.save_macro()
        with patch.object(window.backend, 'send') as send:
            self.connect_fixture()
            window.mode.setCurrentIndex(window.mode.findData('macro'))
            window.macro_assignment.save()
            window.backend.event.emit({'type': 'macro_snapshot', 'snapshot': self.macro_snapshot(active=2)})
            APP.processEvents()
            self.assertNotIn('macro_prepare', [c.args[0]['command'] for c in send.call_args_list])
            self.assertIsNone(window.active_editor)
            self.assertIsNone(window.snapshot)
            self.assertIn('active slot changed', window.status.text())

    def test_backup_failure_never_commits_and_releases_embedded_operation(self):
        window = self.window
        self.save_macro()
        with patch.object(window.backend, 'send') as send, patch.object(window.backend, 'shutdown') as shutdown:
            self.connect_fixture()
            window.mode.setCurrentIndex(window.mode.findData('macro'))
            window.macro_assignment.save()
            window.backend.event.emit({'type': 'macro_snapshot', 'snapshot': self.macro_snapshot()})
            with patch('macro_storage.write_macro_backup', side_effect=OSError('Disk full')):
                window.backend.event.emit({'type': 'macro_prepared', 'token': '123', 'backup': backup()})
            APP.processEvents()
            self.assertNotIn('macro_commit', [c.args[0]['command'] for c in send.call_args_list])
            self.assertIsNone(window.active_editor)
            self.assertFalse(window.hardware_busy)
            shutdown.assert_called_once()

    def test_disconnect_cancels_pending_upload_before_later_inventory_read(self):
        window = self.window
        self.save_macro()
        with patch.object(window.backend, 'send') as send:
            self.connect_fixture()
            window.mode.setCurrentIndex(window.mode.findData('macro'))
            panel = window.macro_assignment
            panel.save()
            window.backend.ready = False
            window.backend.connected.emit(False)
            APP.processEvents()
            self.assertFalse(panel.upload_after_read)
            self.assertIsNone(window.active_editor)
            window.backend.ready = True
            panel.read()
            window.backend.event.emit({'type': 'macro_snapshot', 'snapshot': self.macro_snapshot()})
            APP.processEvents()
            self.assertNotIn('macro_prepare', [c.args[0]['command'] for c in send.call_args_list])
            self.assertIsNone(window.active_editor)

    def test_cancel_quit_preserves_unsaved_library_without_stopping_helper(self):
        window = self.window
        view = self.save_macro()
        view.steps = [{'tap': 'KEY_C'}]
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel), \
             patch.object(window.backend, 'shutdown') as shutdown:
            window.quitting = True
            self.assertFalse(window.close())
            self.assertFalse(window.quitting)
            self.assertEqual(view.steps, [{'tap': 'KEY_C'}])
            shutdown.assert_not_called()

    def test_inline_wheel_read_owns_helper_and_defers_assignment_refresh(self):
        window = self.window
        with patch.object(window.backend, 'send') as send:
            self.connect_fixture()
            window.open_wheel_settings()
            panel = window.wheel_panel
            panel.read()
            self.assertIs(window.active_editor, panel)
            self.assertTrue(window.hardware_busy)
            window.backend.event.emit({'type': 'haptic_snapshot', 'snapshot': wheel_snapshot()})
            APP.processEvents()
            self.assertIsNone(window.active_editor)
            self.assertFalse(window.hardware_busy)
            self.assertTrue(panel.save_button.isEnabled())
            self.assertNotIn('onboard_layers_read', [c.args[0]['command'] for c in send.call_args_list])
            window.workspace.show_page(0)
            self.assertEqual([c.args[0]['command'] for c in send.call_args_list].count('onboard_layers_read'), 1)
