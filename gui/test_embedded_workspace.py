"""Navigation, embedded editors, and selected-button macro transactions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QFormLayout, QMessageBox, QProxyStyle, QStyle
from app import Window
from test_macro_storage import APP, snapshot, backup
from test_gui_hypershift import paired_state
from test_haptic import snapshot as wheel_snapshot
from test_macro_bindings import bindings_snapshot
import copy
import uuid


class FixedFieldStyle(QProxyStyle):
    """Reproduce desktop styles whose form fields do not grow by default."""
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_FormLayoutFieldGrowthPolicy:
            return QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint.value
        return super().styleHint(hint, option, widget, returnData)


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

    def test_assignment_dropdown_remains_usable_with_fixed_field_desktop_style(self):
        window = self.window
        style = FixedFieldStyle()
        style.setParent(window.editor)
        window.editor.setStyle(style)
        window.show()
        for width, height in ((1178, 755), (920, 640)):
            window.resize(width, height)
            for destination in ('hardware', 'software'):
                window.storage.setCurrentIndex(window.storage.findData(destination))
                for index in (0, 1, 11):
                    window.select_button(index)
                    APP.processEvents()
                    self.assertTrue(window.mode.isVisible())
                    self.assertGreaterEqual(window.mode.width(), window.mode.minimumSizeHint().width())
                    self.assertTrue(window.editor.rect().contains(window.mode.geometry()))
                    window.mode.setCurrentIndex(window.mode.findData('key'))
                    window.key_value.setText('B')
                    window.commit_fields()
                    self.assertEqual(window.current()['mode'], 'key')
                    self.assertEqual(window.current()['value'], 'B')

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

    def test_library_assignment_and_configure_links_keep_saved_identity_and_cancel_edits(self):
        window = self.window
        view = self.save_macro()
        first = view.identity
        second = view.library.put('Second', [{'tap': 'KEY_C'}])
        view.refresh_library()
        window.select_button(5)
        window.workspace.show_page(3)
        with patch.object(window.backend, 'send') as send, patch.object(window.backend, 'start') as start:
            view.assign_button.click()
            self.assertEqual(window.workspace.pages.currentIndex(), 0)
            self.assertEqual(window.selected, 5)
            self.assertEqual(window.mode.currentData(), 'macro')
            self.assertEqual(window.macro_assignment.macro_choice.currentData(), first)
            view.name.setText('Unsaved name')
            window.macro_assignment.macro_choice.setCurrentIndex(window.macro_assignment.macro_choice.findData(second))
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
                window.macro_assignment.configure_button.click()
            self.assertEqual(window.workspace.pages.currentIndex(), 0)
            self.assertEqual(view.identity, first)
            self.assertEqual(view.name.text(), 'Unsaved name')
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
                window.macro_assignment.configure_button.click()
            self.assertEqual(window.workspace.pages.currentIndex(), 3)
            self.assertEqual(window.macro_tabs.currentIndex(), 0)
            self.assertEqual(view.identity, second)
            send.assert_not_called()
            start.assert_not_called()

    def test_key_binds_read_filters_and_opens_inactive_layer_without_writes_or_draft_changes(self):
        window = self.window
        self.save_macro()
        window.show()
        with patch.object(window.backend, 'send') as send:
            self.connect_fixture()
            window.workspace.show_page(3)
            window.macro_tabs.setCurrentIndex(1)
            self.assertEqual(window.macro_bindings.table.rowCount(), 0)
            send.assert_not_called()
            window.macro_bindings.read_button.click()
            self.assertFalse(window.macro_tabs.tabBar().isEnabled())
            self.assertIn('Reading mouse', window.macro_bindings.status.text())
            window.backend.event.emit({'type': 'macro_snapshot', 'snapshot': bindings_snapshot()})
            APP.processEvents()
            binds = window.macro_bindings
            self.assertEqual(binds.table.rowCount(), 4)
            binds.filter.setCurrentIndex(binds.filter.findData(8))
            self.assertEqual(binds.table.rowCount(), 2)
            self.assertIn('unrecognized', binds.scope.text())
            before = copy.deepcopy(window.profile)
            binds.table.selectRow(1)
            binds.show_button.click()
            self.assertEqual(window.workspace.pages.currentIndex(), 0)
            self.assertEqual(window.slots.currentData(), 2)
            self.assertEqual(window.editing_layer(), 1)
            self.assertEqual(window.selected, 15)
            self.assertEqual(window.profile, before)
            self.assertFalse(window.apply_button.isEnabled())  # Inactive slots require explicit activation.
            self.assertEqual([c.args[0]['command'] for c in send.call_args_list], ['faceplate', 'macro_read'])
            window.backend.event.emit({'type': 'onboard_layers_saved', 'snapshot': paired_state()})
            self.assertEqual(binds.table.rowCount(), 0)
            self.assertIn('unread', binds.scope.text())

    def test_key_binds_keeps_primary_clicks_read_only_and_clears_disconnected_readback(self):
        window = self.window
        with patch.object(window.backend, 'send') as send:
            self.connect_fixture()
            window.workspace.show_page(3)
            window.macro_tabs.setCurrentIndex(1)
            window.macro_bindings.read_button.click()
            state = bindings_snapshot()
            state['mappings'][0]['normal']['primary'][0].update(category=3, data=[0, 7, 1])
            window.backend.event.emit({'type': 'macro_snapshot', 'snapshot': state})
            APP.processEvents()
            binds = window.macro_bindings
            binds.table.selectRow(0)
            self.assertIn('Left click', binds.table.item(0, 3).text())
            self.assertFalse(binds.show_button.isEnabled())
            window.backend.ready = False
            window.backend.connected.emit(False)
            APP.processEvents()
            self.assertEqual(binds.table.rowCount(), 0)
            self.assertFalse(binds.show_button.isEnabled())
            self.assertIn('unread', binds.scope.text())
            self.assertEqual([c.args[0]['command'] for c in send.call_args_list], ['faceplate', 'macro_read'])

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

    def test_on_mouse_tab_reads_storage_without_assigning_or_uploading(self):
        window = self.window
        panel = window.macro_assignment
        window.show()
        with patch.object(window.backend, 'send') as send:
            self.connect_fixture()
            window.workspace.show_page(3)
            window.macro_tabs.setCurrentIndex(1)
            APP.processEvents()
            self.assertTrue(window.macro_bindings.read_button.isVisible())
            self.assertTrue(panel.inventory.isVisible())
            self.assertTrue(window.macro_bindings.status.isVisible())
            self.assertFalse(panel.inventory_button.isVisible())
            self.assertFalse(panel.tools_widget.isVisible())
            window.macro_bindings.read_button.click()
            self.assertIs(window.active_editor, panel)
            self.assertIn('Reading mouse macro storage', panel.status.text())
            self.assertEqual([call.args[0]['command'] for call in send.call_args_list],
                             ['faceplate', 'macro_read'])
            state = self.macro_snapshot()
            state['storage'].update(stored_count=1, entries=[{'id': 7, 'metadata': [0] * 250, 'data': [1, 5]}])
            window.backend.event.emit({'type': 'macro_snapshot', 'snapshot': state})
            APP.processEvents()
            self.assertIsNone(window.active_editor)
            self.assertFalse(window.hardware_busy)
            self.assertEqual(panel.inventory.rowCount(), 1)
            self.assertEqual(panel.inventory.item(0, 1).text(), '0007')
            self.assertIn('1 / 100', panel.capacity.text())
            self.assertIn('1 of 100', window.macro_meter.toolTip())
            self.assertEqual(panel.inventory.item(0, 4).text(), 'Unused')
            self.assertEqual(panel.inventory.item(0, 3).text(), 'Not linked')
            self.assertEqual(window.workspace.pages.currentIndex(), 3)
            self.assertNotIn('macro_prepare', [call.args[0]['command'] for call in send.call_args_list])
            panel.read_button.click()
            window.backend.event.emit({'type': 'macro_error', 'message': 'Storage read failed'})
            APP.processEvents()
            self.assertEqual(panel.status.text(), 'Storage read failed')
            self.assertEqual(panel.inventory.rowCount(), 0)
            self.assertEqual(panel.capacity.text(), 'Storage: unread')
            self.assertFalse(window.hardware_busy)

    def test_selected_macro_deletion_releases_shared_helper_and_keeps_library_and_draft(self):
        window = self.window
        self.save_macro()
        panel = window.macro_assignment
        before = dict(window.current())
        entries = list(window.macro_library_view.library.entries)
        directory = Path(self.root.name) / 'backups/macros'
        directory.mkdir(parents=True, mode=0o700)
        source = directory / 'TEST-macro-1.journal.jsonl'
        source.write_text('mock upload journal')
        with patch.object(window.backend, 'send') as send, patch.object(window.backend, 'shutdown') as shutdown:
            self.connect_fixture()
            window.backend.macro_deletion = True
            window.workspace.show_page(1)
            panel.read()
            state = self.macro_snapshot()
            state['storage'].update(stored_count=1, entries=[{'id': 7, 'metadata': [0] * 250, 'data': [1, 5]}])
            window.backend.event.emit({'type': 'macro_snapshot', 'snapshot': state})
            APP.processEvents()
            panel.inventory.selectRow(0)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                panel.delete_selected_macro()
            self.assertIs(window.active_editor, panel)
            self.assertTrue(window.hardware_busy)
            deletion = backup()
            deletion.update(kind='onboard_macro_delete_backup', id=7, source_journal=str(source))
            window.backend.event.emit({'type': 'macro_delete_prepared', 'token': '123', 'backup': deletion})
            self.assertEqual(send.call_args.args[0]['command'], 'macro_delete_commit')
            window.backend.event.emit({'type': 'macro_deleted', 'snapshot': self.macro_snapshot(), 'journal': send.call_args.args[0]['journal']})
            APP.processEvents()
            self.assertIsNone(window.active_editor)
            self.assertFalse(window.hardware_busy)
            self.assertTrue(window.workspace.buttons[3].isEnabled())
            self.assertEqual(window.current(), before)
            self.assertEqual(window.macro_library_view.library.entries, entries)
            self.assertEqual(panel.inventory.rowCount(), 0)
            self.assertIn('deleted from mouse', window.status.text())
            shutdown.assert_called_once()

    def test_inline_macro_selector_fills_pane_and_save_reports_progress(self):
        window = self.window
        self.save_macro()
        panel = window.macro_assignment
        style = FixedFieldStyle()
        style.setParent(panel.assignment)
        panel.assignment.setStyle(style)
        window.show()
        with patch.object(window.backend, 'send'):
            self.connect_fixture()
            window.mode.setCurrentIndex(window.mode.findData('macro'))
            for width, height in ((1178, 755), (920, 640)):
                window.resize(width, height)
                APP.processEvents()
                self.assertGreaterEqual(panel.macro_choice.width(), panel.assignment.width() * .8)
                self.assertEqual(panel.macro_choice.toolTip(), 'Saved sequence')
            panel.save()
            APP.processEvents()
            self.assertTrue(panel.operation_timer.isActive())
            self.assertTrue(window.macro_progress.isVisible())
            self.assertFalse(panel.status.isVisible())
            self.assertGreaterEqual(panel.save_button.y(), panel.fields.geometry().bottom())
            self.assertIn('Reading mouse', window.status.text())
            self.assertIn('in progress', window.stored_binding.text())
            window.backend.event.emit({'type': 'macro_snapshot', 'snapshot': self.macro_snapshot()})
            self.assertIn('Preparing recovery backup', window.status.text())
            with patch.object(panel.operation_elapsed, 'elapsed', return_value=125000):
                panel.update_operation_status()
            self.assertIn('Elapsed 2:05', window.status.text())
            self.assertTrue(window.hardware_busy)
            window.backend.event.emit({'type': 'macro_error', 'message': 'Getter failed'})
            APP.processEvents()
            self.assertFalse(panel.operation_timer.isActive())
            self.assertFalse(window.macro_progress.isVisible())
            self.assertFalse(window.hardware_busy)
            self.assertIsNone(window.active_editor)
            self.assertEqual(window.status.text(), 'Getter failed')

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
            self.assertIn('Saving macro and verifying', window.status.text())
            commit = send.call_args.args[0]
            self.assertEqual(commit['command'], 'macro_commit')
            self.assertTrue(Path(commit['journal'].replace('.journal.jsonl', '.json')).exists())
            final = self.macro_snapshot()
            final['mappings'][0]['hypershift']['controls'][3].update(category=3, data=[0, 1, 1])
            window.backend.event.emit({'type': 'macro_saved', 'snapshot': final, 'journal': commit['journal']})
            APP.processEvents()
            self.assertIsNone(window.active_editor)
            self.assertFalse(window.hardware_busy)
            self.assertFalse(panel.operation_timer.isActive())
            self.assertTrue(window.workspace.buttons[3].isEnabled())
            self.assertEqual(window.current()['mode'], 'keep')
            self.assertIn('Macro 0001', window.stored_text(15))
            self.assertEqual(window.hardware_saved, 1)
            shutdown.assert_called_once()
            window.backend.ready = False
            window.backend.connected.emit(False)
            self.assertIn('Macro 0001', window.stored_text(15))

    def test_upload_links_stored_copy_to_library_and_reports_later_edits(self):
        window = self.window
        view = self.save_macro()
        identity = view.identity
        with patch.object(window.backend, 'send') as send, patch.object(window.backend, 'shutdown'):
            self.connect_fixture()
            window.select_button(0)
            window.mode.setCurrentIndex(window.mode.findData('macro'))
            self.assertEqual(window.macro_preview.chips, [('B', 'key')])
            window.macro_assignment.save()
            window.backend.event.emit({'type': 'macro_snapshot', 'snapshot': self.macro_snapshot()})
            request = send.call_args.args[0]
            self.assertEqual(request['command'], 'macro_prepare')
            guid = request['request']['guid']
            self.assertEqual(window.macro_links.lookup(guid)['library_id'], identity)
            window.backend.event.emit({'type': 'macro_prepared', 'token': '123', 'backup': backup()})
            final = self.macro_snapshot()
            final['mappings'][0]['normal']['buttons'][0].update(category=3, data=[0, 1, 1])
            raw = uuid.UUID(guid).bytes_le
            final['storage'].update(stored_count=1, entries=[{'id': 1, 'data': [1, 5],
                'metadata': list(raw + bytes(4) + b'Saved sequence' + bytes(216))}])
            window.backend.event.emit({'type': 'macro_saved', 'snapshot': final, 'journal': send.call_args.args[0]['journal']})
            APP.processEvents()
        inventory = window.macro_assignment.inventory
        self.assertEqual(inventory.item(0, 3).text(), 'Saved sequence · current')
        self.assertEqual(inventory.item(0, 4).text(), '1')
        self.assertEqual(len(window.macro_status[identity]['uses']), 1)
        self.assertIn('matches', window.macro_link_status.text())
        self.assertIn('“Saved sequence”', window.tiles[0].text())
        self.assertIn('Macro 0001', window.stored_text(0))
        window.open_onboard_macros(identity)
        self.assertIn('ON MOUSE · 1 BUTTON', window.macro_usage.badge.text())
        view.steps = [{'tap': 'KEY_C'}]
        self.assertTrue(view.save_local())
        self.assertEqual(inventory.item(0, 3).text(), 'Saved sequence · older version')
        self.assertTrue(window.macro_status[identity]['differs'])
        self.assertIn('CHANGED SINCE UPLOAD', window.macro_usage.badge.text())

    def test_link_write_failure_never_blocks_the_upload(self):
        window = self.window
        self.save_macro()
        with patch.object(window.backend, 'send') as send, \
             patch.object(window.macro_links, 'record', side_effect=OSError('read-only')):
            self.connect_fixture()
            window.mode.setCurrentIndex(window.mode.findData('macro'))
            window.macro_assignment.save()
            window.backend.event.emit({'type': 'macro_snapshot', 'snapshot': self.macro_snapshot()})
            self.assertEqual(send.call_args.args[0]['command'], 'macro_prepare')
            self.assertIn('Library link not recorded', window.macro_assignment.log.toPlainText())

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
