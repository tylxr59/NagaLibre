"""Shared sequence authoring widget for software and onboard macros."""
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from model import display_key, key_code, shortcut


class MacroEditor(QWidget):
    TYPES = [("Tap key", "tap"), ("Shortcut", "chord"), ("Wait (ms)", "wait_ms"), ("Hold key", "down"), ("Release key", "up")]

    def __init__(self, steps, parent=None, *, add_blank=True):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        help_label = QLabel("Add keys, shortcuts and delays in playback order.")
        help_label.setWordWrap(True)
        help_label.setProperty("role", "muted")
        layout.addWidget(help_label)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Action", "Key / shortcut / milliseconds"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        controls = QHBoxLayout()
        for label, callback in [("Add step", lambda: self.add()), ("Remove", self.remove), ("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(1))]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.set_steps(steps)
        if not steps and add_blank:
            self.add()

    def set_steps(self, steps):
        self.table.setRowCount(0)
        for step in steps:
            kind, value = next(iter(step.items()))
            self.add(kind, "+".join(display_key(k) for k in value) if kind == "chord" else str(value))

    def add(self, kind="tap", value=""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        combo = QComboBox()
        combo.setMinimumWidth(160)
        for label, data in self.TYPES:
            combo.addItem(label, data)
        combo.setCurrentIndex(max(0, combo.findData(kind)))
        self.table.setCellWidget(row, 0, combo)
        self.table.setItem(row, 1, QTableWidgetItem(value))
        self.table.setCurrentCell(row, 1)

    def remove(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())

    def move(self, delta):
        row = self.table.currentRow()
        other = row + delta
        if row < 0 or not 0 <= other < self.table.rowCount():
            return
        a, b = self.table.cellWidget(row, 0), self.table.cellWidget(other, 0)
        first = a.currentIndex()
        a.setCurrentIndex(b.currentIndex())
        b.setCurrentIndex(first)
        text = self.table.item(row, 1).text()
        self.table.item(row, 1).setText(self.table.item(other, 1).text())
        self.table.item(other, 1).setText(text)
        self.table.setCurrentCell(other, 1)

    def steps(self):
        steps = []
        for row in range(self.table.rowCount()):
            kind = self.table.cellWidget(row, 0).currentData()
            text = self.table.item(row, 1).text().strip()
            if kind == "wait_ms":
                value = int(text)
                if not 0 <= value <= 60000:
                    raise ValueError("Delays must be between 0 and 60000 ms.")
            elif kind == "chord":
                value = shortcut(text)
            else:
                value = key_code(text)
            steps.append({kind: value})
        if not steps:
            raise ValueError("Add at least one macro action.")
        return steps
