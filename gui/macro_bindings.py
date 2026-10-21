"""Macro reference overview from mouse readback, independent of local drafts."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QComboBox,
)
from model import CONTROL_NAMES
from macro_storage import inventory_rows


def binding_rows(snapshot):
    """Names are display metadata; firmware IDs keep equal names distinct."""
    names = {int(row[1], 16): row[0] for row in inventory_rows(snapshot)}
    rows, unknown = [], 0
    known = {0, 1, 2, 6, 7, 9, 10, 11, 12, 13, 14, 17, 18, 21}
    for mapping in snapshot['mappings']:
        slot = mapping['normal']['slot']
        for layer, bank in enumerate((mapping['normal'], mapping['hypershift'])):
            for primary, records in ((True, bank.get('primary', []) if layer == 0 else []),
                                     (False, bank['buttons'] + bank.get('controls', []))):
                for record in records:
                    category, data = record['category'], record['data']
                    if category not in (3, 4, 5, 15):
                        unknown += category not in known
                        continue
                    if len(data) != (3 if category == 3 else 2):
                        unknown += 1
                        continue
                    identity = data[0] * 256 + data[1]
                    button = record['button']
                    if primary:
                        control = {1: 'Left click', 2: 'Right click', 3: 'Middle click'}.get(button, 'Primary click')
                    else:
                        control = f'Button {button}' if button <= 12 else (
                            CONTROL_NAMES[button - 13] if button <= 16 else f'Control {button}')
                    playback = {4: 'While held', 5: 'Toggle repeat', 15: 'Sequence'}.get(category)
                    if category == 3:
                        playback = 'Once' if data[2] == 1 else f'Repeat {data[2]} times'
                    rows.append({'id': identity, 'name': names.get(identity, 'Missing stored macro'),
                                 'slot': slot, 'layer': layer, 'button': button, 'primary': primary,
                                 'control': control, 'playback': playback})
    return rows, unknown


class MacroBindingsWidget(QWidget):
    readRequested = Signal()
    showButtonRequested = Signal(int, int, int)
    storageRequested = Signal()

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.rows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel('Mouse memory assignments · read the mouse to see which buttons use each stored macro. '
                      'Names here describe stored copies; editing a library macro does not update them automatically.')
        note.setWordWrap(True)
        layout.addWidget(note)
        actions = QHBoxLayout()
        self.read_button = QPushButton('Read mouse assignments')
        self.read_button.clicked.connect(self.readRequested.emit)
        actions.addWidget(self.read_button)
        self.filter = QComboBox()
        self.filter.addItem('All stored macros', None)
        self.filter.currentIndexChanged.connect(self.render_rows)
        actions.addWidget(self.filter, 1)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Macro / ID', 'Slot', 'Layer', 'Button', 'Playback'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.scope = QLabel()
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        footer = QHBoxLayout()
        self.show_button = QPushButton('Show button in Customize')
        self.show_button.clicked.connect(self.show_selected)
        footer.addWidget(self.show_button)
        storage = QPushButton('Manage mouse storage…')
        storage.clicked.connect(self.storageRequested.emit)
        footer.addWidget(storage)
        layout.addLayout(footer)
        self.table.itemSelectionChanged.connect(self.update_selection)
        panel.storageChanged.connect(self.refresh)
        panel.busyChanged.connect(lambda *_: self.refresh())
        panel.operationStatusChanged.connect(self.status.setText)
        self.refresh()

    def refresh(self):
        selected = self.filter.currentData()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem('All stored macros', None)
        self.rows = []
        snapshot = self.panel.snapshot
        if snapshot is not None:
            self.rows, unknown = binding_rows(snapshot)
            for identity, name in sorted({r['id']: r['name'] for r in self.rows}.items()):
                self.filter.addItem(f'{name} · {identity:04x}', identity)
            self.scope.setText(f'{len(self.rows)} inspected macro assignments across {len(snapshot["mappings"])} slots. '
                               'Other plates and primary clicks in Hypershift are not listed.'
                               + (f' {unknown} unrecognized assignments are not shown.' if unknown else ''))
        else:
            self.scope.setText('Assignments unread. Local drafts do not establish what is stored on the mouse.')
        self.filter.setCurrentIndex(max(0, self.filter.findData(selected)))
        self.filter.blockSignals(False)
        self.status.setText(('Last verified readback · reconnect to refresh. ' if snapshot is not None
                            and not self.panel.backend.ready else '') + self.panel.status.text())
        self.read_button.setEnabled(not self.panel.busy)
        self.filter.setEnabled(not self.panel.busy and snapshot is not None)
        self.table.setEnabled(not self.panel.busy)
        self.render_rows()

    def render_rows(self, *_):
        selected = self.filter.currentData()
        self.visible_rows = [r for r in self.rows if selected is None or r['id'] == selected]
        self.table.setRowCount(len(self.visible_rows))
        for index, row in enumerate(self.visible_rows):
            values = [f'{row["name"]} · {row["id"]:04x}', str(row['slot']),
                      'Hypershift' if row['layer'] else 'Normal', row['control'], row['playback']]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(index, column, item)
        self.update_selection()

    def update_selection(self):
        selected = self.table.selectionModel().selectedRows()
        row = self.visible_rows[selected[0].row()] if selected and selected[0].row() < len(self.visible_rows) else None
        self.show_button.setEnabled(not self.panel.busy and row is not None and not row['primary']
                                    and 1 <= row['button'] <= 16)

    def show_selected(self):
        if self.show_button.isEnabled():
            row = self.visible_rows[self.table.selectionModel().selectedRows()[0].row()]
            self.showButtonRequested.emit(row['slot'], row['layer'], row['button'])
