"""Local authoring and saved-macro assignment as separate workspaces."""
import copy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from model import display_key
from macro_library import MacroLibrary
from macro_storage import OnboardMacrosDialog


class MacroWorkspaceDialog(OnboardMacrosDialog):
    def __init__(self, profile_path, *args, library_path=None, **kwargs):
        self.hardware_accessed = False
        self.library = None
        self.identity = None
        self.baseline = None
        super().__init__(profile_path, *args, **kwargs)
        self.setWindowTitle('Macros')
        self.read_button.setText('Read mouse')
        self.tabs = QTabWidget()
        authoring = QWidget()
        authoring.setObjectName("workspacePage")
        author_layout = QHBoxLayout(authoring)
        author_layout.setContentsMargins(0, 8, 0, 0)
        browser = QWidget()
        browser.setObjectName("workspacePage")
        browser.setMaximumWidth(270)
        browser_layout = QVBoxLayout(browser)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search macros')
        browser_layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        browser_layout.addWidget(self.tree, 1)
        self.local_controls = []
        for title, callback in [('New macro', self.new_macro), ('Duplicate', self.duplicate_macro), ('Delete local macro', self.delete_macro)]:
            control = QPushButton(title)
            control.clicked.connect(callback)
            browser_layout.addWidget(control)
            self.local_controls.append(control)
        author_layout.addWidget(browser)
        self.columns.removeWidget(self.sequence_box)
        self.columns.removeWidget(self.assignment)
        author_layout.addWidget(self.sequence_box, 1)
        self.folder = QComboBox()
        self.folder.setEditable(True)
        self.folder.setToolTip('Choose a folder or type a new folder name.')
        self.sequence_box.layout().itemAt(0).layout().addRow('Folder', self.folder)
        self.local_status = QLabel('Saved locally; assigning to the mouse is a separate step.')
        self.local_status.setWordWrap(True)
        self.sequence_box.layout().addWidget(self.local_status)
        local_buttons = QHBoxLayout()
        self.discard_button = QPushButton('Discard changes')
        self.discard_button.clicked.connect(self.discard_changes)
        local_buttons.addWidget(self.discard_button)
        self.local_save = QPushButton('Save macro')
        self.local_save.setProperty('role', 'primary')
        self.local_save.clicked.connect(self.save_local)
        local_buttons.addWidget(self.local_save)
        self.sequence_box.layout().addLayout(local_buttons)
        self.tabs.addTab(authoring, 'My Macros')

        binds = QWidget()
        binds.setObjectName("workspacePage")
        binds_layout = QHBoxLayout(binds)
        binds_layout.setContentsMargins(0, 8, 0, 0)
        selection = QVBoxLayout()
        selection.addWidget(QLabel('Read the mouse, then assign a saved macro to the active slot.'))
        selection.addWidget(QLabel('Saved macro'))
        self.macro_choice = QComboBox()
        selection.addWidget(self.macro_choice)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        selection.addWidget(self.preview, 1)
        hint = QLabel('Assignments use the saved local version. Editing or deleting a local macro does not change existing mouse assignments.')
        hint.setWordWrap(True)
        selection.addWidget(hint)
        binds_layout.addLayout(selection, 1)
        binds_layout.addWidget(self.assignment)
        self.tabs.addTab(binds, 'Key Binds')
        # Replace the now-empty columns while keeping inventory/recovery tools below.
        self.layout().removeItem(self.columns)
        self.layout().insertWidget(1, self.tabs, 1)
        self.search.textChanged.connect(self.populate_tree)
        self.tree.currentItemChanged.connect(self.select_macro)
        self.macro_choice.currentIndexChanged.connect(self.show_preview)
        self.tabs.currentChanged.connect(self.change_view)
        try:
            self.library = MacroLibrary(library_path or Path(profile_path).parent / 'macros.json')
            self.refresh_library()
            if self.library.entries and not self._steps:
                self.load_entry(self.library.entries[0])
            else:
                self.baseline = (self.name.text(), self.folder.currentText(), ())
            self.status.setText('Create and organize macros locally. Use Key Binds to assign a saved macro.')
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.library = None
            self.status.setText(f'Cannot open local library: {error}')
            self.local_status.setText('Library file left untouched. Correct it and reopen this window.')
        self.set_busy(False)
        self.change_view(0)

    def draft_state(self):
        table = self.sequence_editor.table
        return (self.name.text(), self.folder.currentText(), tuple(
            (table.cellWidget(row, 0).currentData(), table.item(row, 1).text())
            for row in range(table.rowCount())))

    def keep_changes(self):
        if self.baseline is None or self.draft_state() == self.baseline:
            return True
        answer = QMessageBox.question(self, 'Unsaved macro', 'Save changes to this local macro?',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        return self.save_local() if answer == QMessageBox.StandardButton.Save else True

    def refresh_library(self):
        chosen = self.macro_choice.currentData()
        entries = self.library.entries
        self.macro_choice.blockSignals(True)
        self.macro_choice.clear()
        for entry in entries:
            label = f"{entry['folder']} / {entry['name']}" if entry.get('folder') else entry['name']
            self.macro_choice.addItem(label, entry['id'])
        self.macro_choice.setCurrentIndex(max(0, self.macro_choice.findData(chosen)))
        self.macro_choice.blockSignals(False)
        folder = self.folder.currentText()
        self.folder.clear()
        self.folder.addItem('')
        self.folder.addItems(sorted({e.get('folder', '') for e in entries} - {''}))
        self.folder.setCurrentText(folder)
        self.populate_tree()
        self.show_preview()

    def populate_tree(self, *_):
        self.tree.blockSignals(True)
        self.tree.clear()
        groups = {}
        if self.library:
            for entry in sorted(self.library.entries, key=lambda e: (e.get('folder', '').casefold(), e['name'].casefold())):
                folder = entry.get('folder', '')
                if self.search.text().casefold() not in (folder + ' ' + entry['name']).casefold():
                    continue
                parent = self.tree
                if folder:
                    if folder not in groups:
                        groups[folder] = QTreeWidgetItem(self.tree, [folder])
                        groups[folder].setExpanded(True)
                    parent = groups[folder]
                item = QTreeWidgetItem(parent, [entry['name']])
                item.setData(0, Qt.ItemDataRole.UserRole, entry['id'])
                if entry['id'] == self.identity:
                    self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)

    def load_entry(self, entry):
        self.identity = entry['id']
        self.name.setText(entry['name'])
        self.folder.setCurrentText(entry.get('folder', ''))
        self.steps = entry['steps']
        self.baseline = self.draft_state()
        self.local_status.setText('Saved locally. Changes take effect on the mouse only after an assignment.')
        self.populate_tree()

    def select_macro(self, current, previous):
        identity = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if not identity or identity == self.identity:
            return
        if not self.keep_changes():
            self.populate_tree()
            return
        self.load_entry(next(e for e in self.library.entries if e['id'] == identity))

    def new_macro(self):
        if not self.keep_changes():
            return
        self.identity = None
        self.name.setText('New macro')
        self.folder.setCurrentText('')
        self.steps = []
        self.baseline = self.draft_state()
        self.local_status.setText('New local macro. Add steps, then save.')
        self.populate_tree()

    def save_local(self):
        if not self.library or self.busy:
            return False
        try:
            self.identity = self.library.put(self.name.text(), self.steps, self.folder.currentText(), self.identity)
            self.baseline = self.draft_state()
            self.refresh_library()
            self.local_status.setText('Macro saved locally.')
            return True
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.local_status.setText(str(error))
            return False

    def duplicate_macro(self):
        if not self.library or not self.keep_changes():
            return
        entry = next((e for e in self.library.entries if e['id'] == self.identity), None)
        if entry:
            try:
                identity = self.library.put((entry['name'][:20] + ' copy'), entry['steps'], entry.get('folder', ''))
                self.refresh_library()
                self.load_entry(next(e for e in self.library.entries if e['id'] == identity))
            except (OSError, ValueError) as error:
                self.local_status.setText(str(error))

    def delete_macro(self):
        if not self.library or not self.identity:
            return
        if QMessageBox.question(self, 'Delete local macro', 'Delete this macro from the local library? Existing mouse assignments will remain.',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.library.remove(self.identity)
            self.baseline = None
            self.new_macro()
            self.refresh_library()
        except (OSError, ValueError) as error:
            self.local_status.setText(str(error))

    def discard_changes(self):
        entry = next((e for e in self.library.entries if e['id'] == self.identity), None) if self.library else None
        if entry:
            self.load_entry(entry)
        else:
            self.baseline = None
            self.new_macro()

    def assignment_macro(self):
        entry = next((e for e in self.library.entries if e['id'] == self.macro_choice.currentData()), None) if self.library else None
        if entry is None:
            raise ValueError('Save a macro in My Macros first.')
        return entry['name'], copy.deepcopy(entry['steps'])

    def show_preview(self, *_):
        try:
            name, steps = self.assignment_macro()
            titles = {data: title for title, data in self.sequence_editor.TYPES}
            self.preview.setPlainText(name + '\n\n' + '\n'.join(
                f"{i}. {titles[kind]}: {' + '.join(display_key(k) for k in value) if isinstance(value, list) else value if kind == 'wait_ms' else display_key(value)}"
                for i, step in enumerate(steps, 1) for kind, value in step.items()))
        except ValueError:
            self.preview.setPlainText('Create and save a macro in My Macros to get started.')
        self.set_busy(self.busy)

    def change_view(self, index):
        self.read_button.setVisible(index == 1)
        self.inventory_button.setVisible(index == 1)
        self.undo_button.setVisible(index == 1)
        if index == 0:
            self.inventory_button.setChecked(False)
        elif self.identity is not None:
            selected = self.macro_choice.findData(self.identity)
            if selected >= 0:
                self.macro_choice.setCurrentIndex(selected)
        # Opening the library never starts a helper. Device access is explicit.

    def send(self, message):
        self.hardware_accessed = True
        super().send(message)

    def set_busy(self, busy):
        super().set_busy(busy)
        if hasattr(self, 'tabs'):
            self.tabs.tabBar().setEnabled(not busy)
            self.tree.setEnabled(not busy)
            self.search.setEnabled(not busy)
            self.macro_choice.setEnabled(not busy)
            self.local_save.setEnabled(not busy and self.library is not None)
            self.discard_button.setEnabled(not busy)
            self.folder.setEnabled(not busy)
            for control in self.local_controls:
                control.setEnabled(not busy and self.library is not None)
            self.save_button.setEnabled(self.save_button.isEnabled() and self.macro_choice.count() > 0)

    def done(self, result):
        if self.busy or not self.keep_changes():
            return
        super().done(result)
