"""Reusable offline macro authoring page."""
import copy
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QFormLayout,
    QGroupBox, QTreeWidget, QTreeWidgetItem, QLineEdit, QComboBox, QPushButton,
    QLabel, QMessageBox, QSizePolicy)
from macro_editor import MacroEditor
from macro_library import MacroLibrary


class MacroLibraryWidget(QWidget):
    catalogChanged = Signal()

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

    def __init__(self, library_path, parent=None):
        super().__init__(parent)
        self.identity = self.baseline = self.library = None
        self.busy = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        browser = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search macros')
        browser.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(180)
        self.tree.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        browser.addWidget(self.tree, 1)
        for title, callback in [('New macro', self.new_macro), ('Duplicate', self.duplicate_macro), ('Delete local macro', self.delete_macro)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            browser.addWidget(button)
        layout.addLayout(browser, 1)
        group = QGroupBox('Macro sequence')
        editor = QVBoxLayout(group)
        fields = QFormLayout()
        self.name = QLineEdit('New macro')
        self.name.setMaxLength(100)
        fields.addRow('Name', self.name)
        self.folder = QComboBox()
        self.folder.setEditable(True)
        self.folder.setToolTip('Choose a folder or type a new folder name.')
        fields.addRow('Folder', self.folder)
        editor.addLayout(fields)
        self.sequence_editor = MacroEditor([], add_blank=False)
        self.sequence_editor.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        editor.addWidget(self.sequence_editor, 1)
        self.local_status = QLabel('Create a macro, then assign it to a button in Customize.')
        self.local_status.setWordWrap(True)
        editor.addWidget(self.local_status)
        controls = QHBoxLayout()
        discard = QPushButton('Discard changes')
        discard.clicked.connect(self.discard_changes)
        controls.addWidget(discard)
        self.local_save = QPushButton('Save macro')
        self.local_save.setProperty('role', 'primary')
        self.local_save.clicked.connect(self.save_local)
        controls.addWidget(self.local_save)
        editor.addLayout(controls)
        layout.addWidget(group, 3)
        self.search.textChanged.connect(self.populate_tree)
        self.tree.currentItemChanged.connect(self.select_macro)
        try:
            self.library = MacroLibrary(library_path)
            self.refresh_library()
            if self.library.entries:
                self.load_entry(self.library.entries[0])
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.library = None
            self.local_status.setText(f'Cannot open library; file left untouched: {error}')
        self.local_save.setEnabled(self.library is not None)
        self.baseline = self.draft_state()

    @property
    def steps(self):
        return self.sequence_editor.steps()

    @steps.setter
    def steps(self, value):
        self.sequence_editor.set_steps(copy.deepcopy(value))

    def refresh_library(self):
        folder = self.folder.currentText()
        self.folder.clear()
        self.folder.addItem('')
        self.folder.addItems(sorted({e.get('folder', '') for e in self.library.entries} - {''}))
        self.folder.setCurrentText(folder)
        self.populate_tree()
        self.catalogChanged.emit()

    def closeEvent(self, event):
        if self.keep_changes():
            event.accept()
        else:
            event.ignore()
