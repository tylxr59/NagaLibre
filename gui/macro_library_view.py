"""Reusable offline macro authoring page."""
import copy
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QFormLayout,
    QGroupBox, QTreeWidget, QTreeWidgetItem, QLineEdit, QInputDialog, QMenu, QPushButton,
    QLabel, QMessageBox, QSizePolicy, QStyle)
from macro_editor import MacroEditor
from macro_library import MacroLibrary


class MacroLibraryWidget(QWidget):
    catalogChanged = Signal()
    assignRequested = Signal(str)
    entryChanged = Signal()

    def open_macro(self, identity):
        entry = next((e for e in self.library.entries if e['id'] == identity), None) if self.library else None
        if entry is None:
            return False
        if identity != self.identity:
            if not self.keep_changes():
                return False
            self.load_entry(entry)
        self.search.clear()
        return True

    def update_assignment_action(self, *_):
        if hasattr(self, 'assign_button'):
            saved = bool(self.library and self.identity and self.baseline is not None
                         and self.draft_state() == self.baseline and not self.busy)
            self.assign_button.setEnabled(saved)

    def assign_macro(self):
        self.update_assignment_action()
        if self.assign_button.isEnabled():
            self.assignRequested.emit(self.identity)

    def draft_state(self):
        table = self.sequence_editor.table
        return (self.name.text(), self.current_folder, tuple(
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
        if self.library:
            query = self.search.text().casefold()
            entries = self.library.entries
            for folder in [''] + self.library.folders:
                matching = [e for e in entries if e.get('folder', '') == folder
                            and query in (folder + ' ' + e['name']).casefold()]
                if query and query not in folder.casefold() and not matching:
                    continue
                group = QTreeWidgetItem(self.tree, [folder or 'Uncategorized'])
                group.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                group.setData(0, Qt.ItemDataRole.UserRole + 1, folder)
                group.setExpanded(True)
                if self.selected_node == ('folder', folder):
                    self.tree.setCurrentItem(group)
                for entry in sorted(matching, key=lambda e: e['name'].casefold()):
                    item = QTreeWidgetItem(group, [entry['name']])
                    item.setData(0, Qt.ItemDataRole.UserRole, entry['id'])
                    if self.selected_node == ('macro', entry['id']):
                        self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)

    def load_entry(self, entry):
        self.identity = entry['id']
        self.name.setText(entry['name'])
        self.current_folder = entry.get('folder', '')
        self.selected_folder = self.current_folder
        self.selected_node = ('macro', self.identity)
        self.show_location()
        self.steps = entry['steps']
        self.baseline = self.draft_state()
        self.local_status.setText('Saved locally. Changes take effect on the mouse only after an assignment.')
        self.populate_tree()
        self.update_assignment_action()
        self.entryChanged.emit()

    def select_macro(self, current, previous):
        identity = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if current is not None and identity is None:
            self.selected_folder = current.data(0, Qt.ItemDataRole.UserRole + 1)
            self.selected_node = ('folder', self.selected_folder)
            return
        if not identity:
            return
        if identity == self.identity:
            self.selected_folder = self.current_folder
            self.selected_node = ('macro', identity)
            return
        if not self.keep_changes():
            self.populate_tree()
            return
        self.load_entry(next(e for e in self.library.entries if e['id'] == identity))

    def new_macro(self):
        folder = self.selected_folder
        if not self.keep_changes():
            return
        self.identity = None
        self.name.setText('New macro')
        self.current_folder = self.selected_folder = folder
        self.selected_node = ('folder', folder)
        self.show_location()
        self.steps = []
        self.baseline = self.draft_state()
        self.local_status.setText('New local macro. Add steps, then save.')
        self.populate_tree()
        self.update_assignment_action()
        self.entryChanged.emit()

    def save_local(self):
        if not self.library or self.busy:
            return False
        try:
            self.identity = self.library.put(self.name.text(), self.steps, self.current_folder, self.identity)
            self.selected_node = ('macro', self.identity)
            self.selected_folder = self.current_folder
            self.baseline = self.draft_state()
            self.refresh_library()
            self.local_status.setText('Macro saved locally.')
            self.update_assignment_action()
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
            self.selected_folder = self.current_folder
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
            self.selected_folder = self.current_folder
            self.new_macro()

    def __init__(self, library_path, parent=None):
        super().__init__(parent)
        self.identity = self.baseline = self.library = None
        self.busy = False
        self.current_folder = self.selected_folder = ''
        self.selected_node = ('folder', '')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        browser = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search macros')
        browser.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_tree_menu)
        self.tree.setMinimumWidth(180)
        self.tree.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        browser.addWidget(self.tree, 1)
        create = QHBoxLayout()
        browser.addLayout(create)
        for title, callback in [('New macro', self.new_macro), ('New folder', self.new_folder)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            create.addWidget(button)
        for title, callback in [('Duplicate', self.duplicate_macro), ('Delete local macro', self.delete_macro)]:
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
        self.location = QLabel('Uncategorized')
        self.location.setWordWrap(True)
        fields.addRow('Location', self.location)
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
        self.assign_button = QPushButton('Assign to mouse…')
        self.assign_button.setToolTip('Save this macro first, then choose its button and playback in Customize.')
        self.assign_button.clicked.connect(self.assign_macro)
        controls.addWidget(self.assign_button)
        editor.addLayout(controls)
        layout.addWidget(group, 3)
        self.search.textChanged.connect(self.populate_tree)
        self.name.textChanged.connect(self.update_assignment_action)
        self.sequence_editor.changed.connect(self.update_assignment_action)
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
        self.update_assignment_action()

    @property
    def steps(self):
        return self.sequence_editor.steps()

    @steps.setter
    def steps(self, value):
        self.sequence_editor.set_steps(copy.deepcopy(value))

    def show_location(self):
        self.location.setText(self.current_folder or 'Uncategorized')

    def new_folder(self):
        if not self.library or self.busy:
            return
        name, accepted = QInputDialog.getText(self, 'New folder', 'Folder name')
        if not accepted:
            return
        try:
            folder = self.library.add_folder(name)
            self.selected_folder = folder
            self.selected_node = ('folder', folder)
            self.search.clear()
            self.refresh_library()
            self.local_status.setText(f'Folder “{folder}” created. Choose New macro to add a sequence here.')
        except (OSError, ValueError) as error:
            self.local_status.setText(str(error))

    def show_tree_menu(self, position):
        item = self.tree.itemAt(position)
        identity = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if identity is None:
            return
        self.tree.setCurrentItem(item)
        if self.identity != identity:
            return
        menu = QMenu(self)
        action = menu.addAction('Move to folder…')
        if menu.exec(self.tree.viewport().mapToGlobal(position)) == action:
            self.move_to_folder()

    def move_to_folder(self):
        if not self.library or self.busy:
            return
        folders = ['Uncategorized'] + [f'Folder: {name}' for name in self.library.folders]
        index = self.library.folders.index(self.current_folder) + 1 if self.current_folder in self.library.folders else 0
        name, accepted = QInputDialog.getItem(self, 'Move macro', 'Folder', folders, index, False)
        if accepted:
            self.current_folder = '' if name == 'Uncategorized' else self.library.folders[folders.index(name) - 1]
            self.show_location()
            self.local_status.setText('Location changed in the draft. Save macro to keep the move.')
            self.update_assignment_action()

    def refresh_library(self):
        self.populate_tree()
        self.catalogChanged.emit()

    def closeEvent(self, event):
        if self.keep_changes():
            event.accept()
        else:
            event.ignore()
