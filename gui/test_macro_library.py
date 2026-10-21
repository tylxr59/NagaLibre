"""Local persistence, offline editing and saved-version assignment regressions."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox
from macro_library import MacroLibrary
from macro_library_view import MacroLibraryWidget
from test_macro_storage import APP, MockBackend


class MacroLibraryTests(unittest.TestCase):
    def test_reopen_rename_duplicate_and_remove_preserve_independent_sequences(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'macros.json'
            library = MacroLibrary(path)
            identity = library.put('Copy', [{'chord': ['KEY_LEFTCTRL', 'KEY_C']}], 'Editing')
            library.put('Renamed', [{'tap': 'KEY_B'}], 'Work', identity)
            duplicate = library.put('Duplicate', library.entries[0]['steps'])
            library.remove(identity)
            self.assertEqual(MacroLibrary(path).entries, [{'id': duplicate, 'name': 'Duplicate', 'folder': '', 'steps': [{'tap': 'KEY_B'}]}])

    def test_failed_atomic_write_keeps_saved_catalog(self):
        with tempfile.TemporaryDirectory() as root:
            library = MacroLibrary(Path(root) / 'macros.json')
            identity = library.put('Original', [{'tap': 'KEY_A'}])
            original = library.path.read_bytes()
            with patch('macro_library.save_profile', side_effect=OSError('Disk full')):
                with self.assertRaisesRegex(OSError, 'Disk full'):
                    library.put('Changed', [{'tap': 'KEY_B'}], identity=identity)
            self.assertEqual(library.path.read_bytes(), original)
            self.assertEqual(library.entries[0]['name'], 'Original')

    def test_corrupt_future_and_stale_catalogs_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'macros.json'
            first = MacroLibrary(path)
            stale = MacroLibrary(path)
            first.put('First', [{'tap': 'KEY_A'}])
            with self.assertRaisesRegex(ValueError, 'another window'):
                stale.put('Second', [{'tap': 'KEY_B'}])
            for contents in ('{broken', '{"version": 2, "macros": []}'):
                path.write_text(contents)
                with self.assertRaises(ValueError):
                    MacroLibrary(path)
                self.assertEqual(path.read_text(), contents)


class MacroWorkspaceTests(unittest.TestCase):
    def tearDown(self):
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
            for widget in APP.topLevelWidgets():
                if isinstance(widget, MacroLibraryWidget):
                    widget.busy = False
                    widget.close()
                    widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def test_offline_create_rename_folder_duplicate_and_reopen_never_start_helper(self):
        with tempfile.TemporaryDirectory() as root:
            backend = MockBackend()
            backend.ready = False
            with patch.object(backend, 'start') as start:
                dialog = MacroLibraryWidget(Path(root) / 'macros.json')
                dialog.name.setText('Copy')
                dialog.folder.setCurrentText('Editing')
                dialog.steps = [{'chord': ['KEY_LEFTCTRL', 'KEY_C']}]
                self.assertTrue(dialog.save_local())
                identity = dialog.identity
                dialog.name.setText('Copy selection')
                self.assertTrue(dialog.save_local())
                self.assertEqual(dialog.identity, identity)
                dialog.duplicate_macro()
                self.assertNotEqual(dialog.identity, identity)
                self.assertEqual(len(dialog.library.entries), 2)
                self.assertEqual(backend.messages, [])
                start.assert_not_called()
                dialog.close()
                reopened = MacroLibraryWidget(Path(root) / 'macros.json')
                self.assertEqual(len(reopened.library.entries), 2)
                self.assertEqual(reopened.tree.topLevelItemCount(), 1)
                self.assertEqual(reopened.library.entries[0]["folder"], "Editing")

    def test_unsaved_sequence_edits_leave_saved_assignment_source_intact(self):
        with tempfile.TemporaryDirectory() as root:
            view = MacroLibraryWidget(Path(root) / 'macros.json')
            view.name.setText('Saved')
            view.steps = [{'tap': 'KEY_A'}]
            self.assertTrue(view.save_local())
            view.name.setText('Unsaved')
            view.steps = [{'tap': 'KEY_B'}]
            self.assertEqual(view.library.entries[0]['name'], 'Saved')
            self.assertEqual(view.library.entries[0]['steps'], [{'tap': 'KEY_A'}])

    def test_unsaved_cancel_preserves_draft_and_discard_restores_saved_macro(self):
        with tempfile.TemporaryDirectory() as root:
            dialog = MacroLibraryWidget(Path(root) / 'macros.json')
            dialog.steps = [{'tap': 'KEY_A'}]
            dialog.save_local()
            dialog.steps = [{'tap': 'KEY_B'}]
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
                dialog.new_macro()
                dialog.close()
            self.assertEqual(dialog.steps, [{'tap': 'KEY_B'}])
            self.assertNotEqual(dialog.draft_state(), dialog.baseline)
            dialog.discard_changes()
            self.assertEqual(dialog.steps, [{'tap': 'KEY_A'}])

    def test_corrupt_library_blocks_writes_without_blocking_window_close(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'macros.json'
            path.write_text('{broken')
            dialog = MacroLibraryWidget(Path(root) / 'macros.json')
            self.assertFalse(dialog.local_save.isEnabled())
            self.assertFalse(dialog.save_local())
            self.assertEqual(path.read_text(), '{broken')
            dialog.close()
            self.assertTrue(dialog.close())
