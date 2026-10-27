"""Saved-macro assignment within the selected button's Customize pane."""
import copy
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QPushButton, QGroupBox, QVBoxLayout, QFormLayout, QSizePolicy
from macro_storage import OnboardMacrosDialog


class MacroAssignmentPanel(OnboardMacrosDialog):
    busyChanged = Signal(bool)
    softwareAssigned = Signal(dict)
    manageRequested = Signal(str)
    storageChanged = Signal()

    def __init__(self, profile_path, library_view, parent=None, *, backend):
        self.library_view = library_view
        self.software = False
        self.upload_after_read = False
        self.expected_slot = None
        self.allowed = False
        self.links = None
        self.batch_keep_open = False
        self.upload_entry = None
        super().__init__(profile_path, parent, backend=backend, shared=True)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setObjectName('macroAssignment')
        self.setStyleSheet('QDialog#macroAssignment { background: transparent; }')
        self.setMinimumSize(0, 0)
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.columns.removeWidget(self.sequence_box)
        self.sequence_box.hide()
        self.assignment.setTitle('')
        self.assignment.setStyleSheet('QGroupBox { border: 0; margin: 0; padding: 0; background: transparent; }')
        self.assignment.layout().setContentsMargins(0, 0, 0, 0)
        self.fields.setVerticalSpacing(6)
        self.fields.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.assignment.setMinimumWidth(0)
        self.assignment.setMaximumWidth(16777215)
        self.fields.setRowVisible(self.target, False)
        self.fields.setRowVisible(self.layer, False)
        self.fields.setRowVisible(self.stored, False)
        self.read_button.setText('Read macro storage')
        self.read_button.setToolTip('Read stored macro names, IDs, sequence sizes and available space from the mouse.')
        self.close_buttons.hide()
        tools = self.layout().takeAt(2).layout()
        self.tools_widget = QGroupBox('Macro storage')
        tool_layout = QVBoxLayout(self.tools_widget)
        tool_layout.addLayout(tools)
        header = self.layout().itemAt(0).layout()
        header.removeWidget(self.read_button)
        tools.insertWidget(0, self.read_button)
        header.removeWidget(self.status)
        tool_layout.addWidget(self.status)
        for panel in (self.inventory_panel, self.details_panel):
            self.layout().removeWidget(panel)
            tool_layout.addWidget(panel)
        self.macro_choice = QComboBox()
        self.macro_choice.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.macro_choice.currentIndexChanged.connect(lambda *_: self.set_busy(self.busy))
        self.macro_choice.currentTextChanged.connect(self.macro_choice.setToolTip)
        self.fields.insertRow(0, 'Macro', self.macro_choice)
        manage = QPushButton('Configure macro')
        self.configure_button = manage
        manage.setStyleSheet('padding: 4px 0; border: 0; text-align: left; background: transparent; color: #44d62c;')
        manage.clicked.connect(lambda: self.manageRequested.emit(self.macro_choice.currentData() or ''))
        self.fields.insertRow(1, manage)
        self.status.setText('Read macro storage to list macros stored on this mouse.')
        # Keep read results beside the storage controls, outside the assignment
        # pane. The workspace footer also reports an active operation.
        self.library_view.catalogChanged.connect(self.refresh_macros)
        self.refresh_macros()

    def refresh_macros(self):
        previous = self.macro_choice.currentData()
        self.macro_choice.blockSignals(True)
        self.macro_choice.clear()
        library = self.library_view.library
        for entry in library.entries if library else []:
            label = f"{entry['folder']} / {entry['name']}" if entry.get('folder') else entry['name']
            self.macro_choice.addItem(label, entry['id'])
        self.macro_choice.setCurrentIndex(max(0, self.macro_choice.findData(previous)))
        self.macro_choice.blockSignals(False)
        self.macro_choice.setToolTip(self.macro_choice.currentText())
        self.set_busy(self.busy)

    def set_context(self, button, layer, *, software, slot, allowed):
        self.target.setCurrentIndex(button - 1)
        self.layer.setCurrentIndex(layer)
        self.software, self.expected_slot, self.allowed = software, slot, allowed
        self.set_busy(self.busy)

    def assignment_entry(self):
        library = self.library_view.library
        entry = next((e for e in library.entries if e['id'] == self.macro_choice.currentData()), None) if library else None
        if entry is None:
            raise ValueError('Create and save a macro in Macros first.')
        return copy.deepcopy(entry)

    def assignment_macro(self):
        entry = self.assignment_entry()
        self.upload_entry = entry
        return entry['name'], entry['steps']

    def upload_guid(self):
        guid = super().upload_guid()
        # Link the stored copy to its library entry before the upload is
        # prepared. A failed upload leaves an unused link, which is harmless.
        if self.links is not None and self.upload_entry is not None:
            try:
                self.links.record(guid, self.upload_entry)
            except (OSError, ValueError) as error:
                self.log.appendPlainText(f'Library link not recorded; the upload is unaffected: {error}')
        return guid

    def save(self):
        if self.busy or not self.allowed:
            return
        try:
            entry = self.assignment_entry()
        except ValueError as error:
            self.status.setText(str(error))
            return
        if self.software:
            self.softwareAssigned.emit(entry)
            self.status.setText('Macro selected in the local draft. Apply bindings to run it.')
            return
        if not self.backend.ready or not getattr(self.backend, 'onboard_macros', False):
            self.status.setText('Connect a wired Naga V2 Pro with its twelve-button plate first.')
            return
        self.upload_after_read = True
        self.read()

    def on_event(self, message):
        if not self.busy:
            kind = message.get('type', '')
            if (kind in ('faceplate', 'error', 'macro_error')
                    or kind.startswith('onboard_') and kind.endswith(('snapshot', 'saved', 'activated', 'created'))):
                self.invalidate()
            return
        self.last_result = message.get("type")
        super().on_event(message)
        self.storageChanged.emit()
        if message.get('type') == 'macro_snapshot' and self.upload_after_read:
            self.upload_after_read = False
            if self.snapshot['guard']['active'] != self.expected_slot:
                self.error('The active slot changed. Read the selected active slot before assigning a macro.')
                return
            super().save()
        elif message.get('type') in ('macro_error', 'error'):
            self.upload_after_read = False

    def error(self, error):
        self.upload_after_read = False
        super().error(error)

    def invalidate(self):
        super().invalidate()
        self.storageChanged.emit()

    def connected(self, ready):
        if not ready:
            self.upload_after_read = False
        if self.busy:
            super().connected(ready)
        elif ready:
            self.saved = False
            self.invalidate()
        elif not ready and not self.saved:
            self.invalidate()
            self.set_busy(False)
        self.storageChanged.emit()

    def set_busy(self, busy):
        was_busy = getattr(self, 'busy', False)
        super().set_busy(busy)
        self.operation_progress.hide()
        if hasattr(self, 'macro_choice'):
            self.macro_choice.setEnabled(not busy)
            self.fields.setRowVisible(self.playback, not self.software)
            self.fields.setRowVisible(self.count, not self.software and self.playback.currentData() == 'counted')
            self.playback_hint.setVisible(not self.software and self.playback.currentData() == 'toggle')
            self.read_button.setVisible(not self.software)
            self.inventory_button.hide()
            self.undo_button.setVisible(not self.software)
            self.inventory_button.setChecked(not self.software)
            self.save_button.setText('Use macro' if self.software else 'Save macro to mouse')
            # Mouse-memory assignments are drafts saved by the main Save bindings action.
            self.save_button.setVisible(self.software)
            self.save_button.setEnabled(not busy and self.allowed and self.macro_choice.count() > 0)
        if was_busy != busy:
            self.busyChanged.emit(busy)
