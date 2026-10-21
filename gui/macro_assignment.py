"""Saved-macro assignment within the selected button's Customize pane."""
import copy
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QPushButton, QGroupBox, QVBoxLayout, QFormLayout, QSizePolicy
from macro_storage import OnboardMacrosDialog


class MacroAssignmentPanel(OnboardMacrosDialog):
    busyChanged = Signal(bool)
    softwareAssigned = Signal(dict)
    manageRequested = Signal()

    def __init__(self, profile_path, library_view, parent=None, *, backend):
        self.library_view = library_view
        self.software = False
        self.upload_after_read = False
        self.expected_slot = None
        self.allowed = False
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
        self.read_button.setText('Refresh mouse')
        self.close_buttons.hide()
        tools = self.layout().takeAt(2).layout()
        self.tools_widget = QGroupBox('Macro storage')
        tool_layout = QVBoxLayout(self.tools_widget)
        tool_layout.addLayout(tools)
        header = self.layout().itemAt(0).layout()
        header.removeWidget(self.read_button)
        tools.insertWidget(0, self.read_button)
        for panel in (self.inventory_panel, self.details_panel):
            self.layout().removeWidget(panel)
            tool_layout.addWidget(panel)
        self.macro_choice = QComboBox()
        self.macro_choice.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.macro_choice.currentIndexChanged.connect(lambda *_: self.set_busy(self.busy))
        self.macro_choice.currentTextChanged.connect(self.macro_choice.setToolTip)
        self.fields.insertRow(0, 'Macro', self.macro_choice)
        manage = QPushButton('Manage macros')
        manage.setStyleSheet('padding: 4px 0; border: 0; text-align: left; background: transparent; color: #44d62c;')
        manage.clicked.connect(self.manageRequested.emit)
        self.fields.insertRow(1, manage)
        self.status.setText('')
        # The workspace footer owns operation feedback; reserve this pane for
        # assignment fields rather than duplicating a multiline status here.
        self.status.hide()
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
        return entry['name'], entry['steps']

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
            if message.get('type') == 'faceplate':
                self.invalidate()
            return
        self.last_result = message.get("type")
        super().on_event(message)
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

    def connected(self, ready):
        if not ready:
            self.upload_after_read = False
        if self.busy:
            super().connected(ready)
        elif not ready and not self.saved:
            self.invalidate()
            self.set_busy(False)

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
            self.inventory_button.setVisible(not self.software)
            self.undo_button.setVisible(not self.software)
            if self.software:
                self.inventory_button.setChecked(False)
            self.save_button.setText('Use macro' if self.software else 'Save macro to mouse')
            self.save_button.setEnabled(not busy and self.allowed and self.macro_choice.count() > 0)
        if was_busy != busy:
            self.busyChanged.emit(busy)
