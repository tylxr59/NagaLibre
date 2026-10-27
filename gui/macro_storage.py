"""Onboard macro drafts, stored contents and durable upload acknowledgement."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import uuid

from PySide6.QtCore import QElapsedTimer, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QGroupBox, QHeaderView, QWidget, QProgressBar, QMessageBox,
)
from backend import Backend
from macro_editor import MacroEditor
from model import CONTROL_NAMES, new_profile, runtime_config, save_profile
from onboard import stored_label

PLAYBACK = (("Once", "once"), ("Repeat a fixed count", "counted"),
            ("Repeat while held", "while_held"), ("Toggle repeat", "toggle"),
            ("Sequence", "sequence"))


def macro_config(steps):
    profile = new_profile()
    profile["plate"] = "12"
    profile["plates"]["12"][0].update(mode="macro", trigger="KEY_F24", steps=copy.deepcopy(steps))
    return runtime_config(profile)


def write_macro_backup(profile_path, backup, token):
    if (backup.get("format") != 1 or backup.get("kind") != "onboard_macro_transaction_backup"
            or backup.get("complete_profile") is not False
            or backup.get("contents", {}).get("kind") != "onboard_macro_storage_checkpoint"
            or backup.get("mappings", {}).get("kind") != "paired_mapping_backup"):
        raise ValueError("Not a macro content/mapping transaction backup")
    return _write_macro_backup(profile_path, backup, token, 'macro')


def write_macro_delete_backup(profile_path, backup, token):
    if (backup.get('format') != 1 or backup.get('kind') != 'onboard_macro_delete_backup'
            or backup.get('complete_profile') is not False
            or backup.get('contents', {}).get('kind') != 'onboard_macro_storage_checkpoint'
            or backup.get('mappings', {}).get('kind') != 'paired_mapping_backup'):
        raise ValueError('Not a macro deletion backup')
    return _write_macro_backup(profile_path, backup, token, 'macro-delete')


def _write_macro_backup(profile_path, backup, token, label):
    if not isinstance(token, str) or not token.isdecimal() or len(token) > 40:
        raise ValueError("Invalid macro backup token")
    directory = Path(profile_path).parent / "backups" / "macros"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stat = directory.lstat()
    if directory.is_symlink() or stat.st_uid != os.geteuid() or stat.st_mode & 0o077:
        raise ValueError("Macro backups need a private directory owned by this user")
    serial = re.sub(r"[^A-Za-z0-9_-]", "_", backup["contents"]["inspection"]["guard"]["device"]["serial"])
    path = directory / f"{serial}-{label}-{token}.json"
    if path.exists():
        raise ValueError("Macro backup token already exists")
    save_profile(path, backup)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path, path.with_suffix(".journal.jsonl")


def inventory_rows(snapshot):
    result = []
    for entry in snapshot["storage"]["entries"]:
        raw = bytes(entry["metadata"])
        name = raw[20:120].split(b"\0", 1)[0].decode("utf-8", errors="replace") or "Unnamed / opaque"
        result.append((name, f"{entry['id']:04x}", str(len(entry["data"]))))
    return result


class OnboardMacrosDialog(QDialog):
    operationStatusChanged = Signal(str)

    def __init__(self, profile_path, parent=None, backend=None, steps=None, button=1, layer=0, *, shared=False):
        super().__init__(parent)
        self.profile_path = Path(profile_path)
        if shared and backend is None:
            raise ValueError("A shared editor requires an existing backend")
        self.shared_backend = shared
        self.backend = backend or Backend(self)
        self.backend_attached = True
        self.steps = copy.deepcopy(steps or [])
        self.snapshot = None
        self.busy = False
        self.saved = False
        self.pending = None
        self.pending_write = None
        self.last_journal = None
        self.operation_phase = ''
        self.operation_elapsed = QElapsedTimer()
        self.operation_timer = QTimer(self)
        self.operation_timer.setInterval(1000)
        self.operation_timer.timeout.connect(self.update_operation_status)
        self.setWindowTitle("Onboard macros")
        self.resize(980, 640)
        self.setMinimumSize(840, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        header = QHBoxLayout()
        self.status = QLabel("Create a sequence and assign it to a button.")
        self.status.setWordWrap(True)
        header.addWidget(self.status, 1)
        self.operation_progress = QProgressBar()
        self.operation_progress.setRange(0, 0)
        self.operation_progress.setTextVisible(False)
        self.operation_progress.setFixedWidth(40)
        self.operation_progress.hide()
        header.addWidget(self.operation_progress)
        self.read_button = QPushButton("Refresh")
        self.read_button.clicked.connect(self.read)
        header.addWidget(self.read_button)
        layout.addLayout(header)

        columns = self.columns = QHBoxLayout()
        columns.setSpacing(16)
        sequence_box = self.sequence_box = QGroupBox("Macro sequence")
        sequence_layout = QVBoxLayout(sequence_box)
        name_row = QFormLayout()
        self.name = QLineEdit("New macro")
        self.name.setMaxLength(100)
        self.name.setToolTip("Macro names can use up to 100 UTF-8 bytes.")
        name_row.addRow("Name", self.name)
        sequence_layout.addLayout(name_row)
        self.sequence_editor = MacroEditor(self._steps, add_blank=False)
        sequence_layout.addWidget(self.sequence_editor, 1)
        columns.addWidget(sequence_box, 2)

        self.assignment = QGroupBox("Button assignment")
        self.assignment.setMinimumWidth(240)
        self.assignment.setMaximumWidth(300)
        assignment_layout = QVBoxLayout(self.assignment)
        fields = QFormLayout()
        self.fields = fields
        fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        fields.setVerticalSpacing(10)
        self.target = QComboBox()
        for i in range(1, 17):
            self.target.addItem(f"Button {i}" if i <= 12 else CONTROL_NAMES[i - 13], i)
        self.target.setCurrentIndex(max(0, min(15, button - 1)))
        fields.addRow("Button", self.target)
        self.layer = QComboBox()
        self.layer.addItems(["Normal", "Hypershift"])
        self.layer.setCurrentIndex(layer if layer in (0, 1) else 0)
        fields.addRow("Layer", self.layer)
        self.stored = QLabel("Stored binding: unread")
        self.stored.setWordWrap(True)
        fields.addRow(self.stored)
        self.playback = QComboBox()
        for title, mode in PLAYBACK:
            self.playback.addItem(title, mode)
        fields.addRow("Playback", self.playback)
        self.count = QSpinBox()
        self.count.setRange(1, 255)
        self.count.setValue(3)
        fields.addRow("Repeat count", self.count)
        assignment_layout.addLayout(fields)
        self.playback_hint = QLabel("Press again to stop. Stop playback before changing this assignment.")
        self.playback_hint.setWordWrap(True)
        self.playback_hint.setProperty("role", "muted")
        assignment_layout.addWidget(self.playback_hint)
        assignment_layout.addStretch()
        self.save_button = QPushButton("Save to mouse")
        self.save_button.setProperty("role", "primary")
        self.save_button.setToolTip("Save a new onboard macro and assign it to this button.")
        self.save_button.clicked.connect(self.save)
        assignment_layout.addWidget(self.save_button)
        columns.addWidget(self.assignment, 1)
        layout.addLayout(columns, 1)

        tools = QHBoxLayout()
        self.inventory_button = QPushButton("On mouse")
        self.inventory_button.setCheckable(True)
        tools.addWidget(self.inventory_button)
        self.details_button = QPushButton("Details")
        self.details_button.setCheckable(True)
        tools.addWidget(self.details_button)
        self.undo_button = QPushButton("Restore macro backup…")
        self.undo_button.setToolTip(
            "Restore the button assignments from before a NagaLibre macro save and remove the macro it uploaded. "
            "Requires that save's recovery journal; this does not delete the selected table row.")
        self.undo_button.clicked.connect(self.undo)
        tools.addWidget(self.undo_button)
        tools.addStretch()
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.rejected.connect(self.reject)
        tools.addWidget(self.close_buttons)
        layout.addLayout(tools)

        self.inventory_panel = QWidget()
        inventory_layout = QVBoxLayout(self.inventory_panel)
        inventory_layout.setContentsMargins(0, 0, 0, 0)
        self.capacity = QLabel("Storage: unread")
        inventory_layout.addWidget(self.capacity)
        self.inventory = QTableWidget(0, 3)
        self.inventory.setHorizontalHeaderLabels(["Stored macro", "ID", "Sequence bytes"])
        self.inventory.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.inventory.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.inventory.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.inventory.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.inventory.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.inventory.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.inventory.verticalHeader().hide()
        self.inventory.setMaximumHeight(140)
        inventory_layout.addWidget(self.inventory)
        self.delete_button = QPushButton('Delete selected macro…')
        self.delete_button.setToolTip('Delete an unassigned NagaLibre upload using its original upload journal. Button assignments and the local library stay unchanged.')
        self.delete_button.clicked.connect(self.delete_selected_macro)
        inventory_layout.addWidget(self.delete_button)
        self.inventory.itemSelectionChanged.connect(self.update_delete_button)
        self.inventory_panel.hide()
        self.inventory_button.toggled.connect(self.inventory_panel.setVisible)
        layout.addWidget(self.inventory_panel)

        self.details_panel = QWidget()
        detail_layout = QVBoxLayout(self.details_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel("Experimental native macros · wired Naga V2 Pro, twelve-button plate. "
                      "Representative playback and undo have been tested; "
                      "see docs/MACROS.md for current support and recovery.")
        note.setWordWrap(True)
        detail_layout.addWidget(note)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        detail_layout.addWidget(self.log)
        self.details_panel.hide()
        self.details_button.toggled.connect(self.details_panel.setVisible)
        layout.addWidget(self.details_panel)
        self.target.currentIndexChanged.connect(self.show_binding)
        self.layer.currentIndexChanged.connect(self.show_binding)
        self.playback.currentIndexChanged.connect(lambda *_: self.set_busy(self.busy))
        self.backend.event.connect(self.on_event)
        self.backend.connected.connect(self.connected)
        self.backend.log.connect(self.log.appendPlainText)
        self.show_steps()
        self.set_busy(False)

    @property
    def steps(self):
        if hasattr(self, "sequence_editor"):
            return self.sequence_editor.steps()
        return self._steps

    @steps.setter
    def steps(self, steps):
        self._steps = copy.deepcopy(steps)
        if hasattr(self, "sequence_editor"):
            self.sequence_editor.set_steps(self._steps)

    def show_steps(self):
        self.sequence_editor.set_steps(self._steps)

    def show_binding(self, *_):
        text = "unread"
        if self.snapshot:
            active = self.snapshot["guard"]["active"]
            mapping = next(m for m in self.snapshot["mappings"] if m["normal"]["slot"] == active)
            bank = mapping["hypershift"] if self.layer.currentIndex() else mapping["normal"]
            record = next(b for b in bank["buttons"] + bank["controls"] if b["button"] == self.target.currentData())
            text = stored_label(record)
        self.stored.setText(f"Stored binding: {text}")

    def invalidate(self):
        self.snapshot = None
        self.inventory.setRowCount(0)
        self.inventory_button.setText("On mouse")
        self.capacity.setText("Storage: unread")
        self.show_binding()

    def set_busy(self, busy):
        if busy and not self.busy:
            self.operation_elapsed.start()
            self.operation_timer.start()
        elif not busy:
            self.operation_timer.stop()
            self.operation_phase = ''
        self.operation_progress.setVisible(busy)
        self.busy = busy
        editable = not busy and self.snapshot is not None and not self.saved and self.backend.ready
        self.read_button.setEnabled(not busy)
        self.undo_button.setEnabled(not busy)
        self.save_button.setEnabled(editable)
        for widget in (self.target, self.layer, self.name, self.playback, self.sequence_editor):
            widget.setEnabled(not busy)
        counted = self.playback.currentData() == "counted"
        self.count.setEnabled(not busy and counted)
        self.fields.setRowVisible(self.count, counted)
        self.playback_hint.setVisible(self.playback.currentData() == "toggle")
        self.close_buttons.setEnabled(not busy)
        self.update_delete_button()

    def update_delete_button(self):
        self.delete_button.setEnabled(not self.busy and self.snapshot is not None and not self.saved
            and self.backend.ready and getattr(self.backend, 'macro_deletion', False)
            and bool(self.inventory.selectionModel().selectedRows()))

    def delete_selected_macro(self):
        if not self.delete_button.isEnabled():
            return
        row = self.inventory.selectionModel().selectedRows()[0].row()
        macro_id = int(self.inventory.item(row, 1).text(), 16)
        name = self.inventory.item(row, 0).text()
        directory = self.profile_path.parent / 'backups' / 'macros'
        journals = sorted(directory.glob('*-macro-*.journal.jsonl'), key=lambda p: p.name, reverse=True)
        if not journals:
            self.status.setText('The original NagaLibre upload journal is missing. Only owned uploads can be deleted.')
            return
        if len(journals) > 256:
            self.status.setText('Too many upload journals to search. Use Restore macro backup with the original upload journal.')
            return
        answer = QMessageBox.question(self, 'Delete macro from mouse',
            f'Delete “{name}” (ID {macro_id:04x}) from mouse memory?\n\n'
            'Only unassigned NagaLibre uploads with their original journal can be deleted. '
            'Button assignments and your local macro library will stay unchanged. '
            'Stop any running macro before continuing. This deletion cannot be undone in the GUI.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.saved = False
        self.pending_write = 'macro_delete_prepared'
        self.set_busy(True)
        self.set_operation_status('Checking macro ownership, assignments and recovery backup…')
        try:
            self.send({'command': 'macro_delete_prepare', 'id': macro_id, 'journals': [str(p) for p in journals]})
        except (OSError, ValueError) as error:
            self.error(error)

    def set_operation_status(self, phase):
        self.operation_phase = phase
        self.update_operation_status()

    def update_operation_status(self):
        if not self.busy or not self.operation_phase:
            return
        seconds = self.operation_elapsed.elapsed() // 1000
        text = (f'{self.operation_phase}\nElapsed {seconds // 60}:{seconds % 60:02d} · '
                'Mouse checks can take several minutes. Keep the mouse connected.')
        self.status.setText(text)
        self.operationStatusChanged.emit(text)

    def send(self, message):
        if self.backend.ready:
            if not getattr(self.backend, "onboard_macros", False):
                raise ValueError("Onboard macros require wired Naga V2 Pro and an updated helper.")
            if message["command"] == "macro_read":
                self.backend.send({"command": "faceplate"})
            self.backend.send(message)
        else:
            self.pending = message
            self.backend.start()

    def connected(self, ready):
        if ready:
            if not getattr(self.backend, "onboard_macros", False):
                self.error("Onboard macros require wired Naga V2 Pro and an updated helper.")
                if not self.shared_backend:
                    self.backend.shutdown()
                return
            if self.pending:
                message, self.pending = self.pending, None
                self.send(message)
        elif not self.saved:
            self.pending = None
            self.pending_write = None
            self.invalidate()
            self.set_busy(False)
            self.status.setText("Helper disconnected. Read again; retain any transaction journal for recovery.")

    def read(self):
        self.pending_write = None
        self.invalidate()
        self.saved = False
        self.show_binding()
        self.set_busy(True)
        self.set_operation_status("Reading mouse macro storage…")
        try:
            self.send({"command": "macro_read"})
        except (OSError, ValueError) as error:
            self.error(error)

    def assignment_macro(self):
        return self.name.text(), self.steps

    def upload_guid(self):
        return str(uuid.uuid4())

    def save(self):
        if self.busy or self.snapshot is None or self.saved:
            return
        try:
            name, steps = self.assignment_macro()
            if not name or len(name.encode("utf-8")) > 100 or "\0" in name:
                raise ValueError("Name must contain 1–100 UTF-8 bytes without NUL.")
            playback = {"mode": self.playback.currentData()}
            if playback["mode"] == "counted":
                playback["count"] = self.count.value()
            request = {"trigger": "KEY_F24", "guid": self.upload_guid(), "name": name,
                       "button": self.target.currentData(), "layer": self.layer.currentIndex(),
                       "playback": playback}
            config = macro_config(steps)
        except (ValueError, KeyError, TypeError) as error:
            # Local form errors do not make the last mouse read stale.
            self.status.setText(str(error))
            return
        try:
            self.pending_write = 'macro_prepared'
            self.set_busy(True)
            self.set_operation_status("Preparing recovery backup and checking mouse state…")
            self.send({"command": "macro_prepare", "config": config, "request": request})
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.error(error)

    def undo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the recovery journal for a macro save",
            str(self.last_journal or self.profile_path.parent / "backups" / "macros"), "Macro journals (*.jsonl)")
        if not path:
            return
        self.saved = False
        self.pending_write = None
        self.invalidate()
        self.set_busy(True)
        self.set_operation_status("Restoring macro backup and verifying mouse state…")
        try:
            self.send({"command": "macro_recover", "journal": path})
        except (OSError, ValueError) as error:
            self.error(error)

    def on_event(self, message):
        kind = message.get("type")
        if kind in ("macro_snapshot", "macro_saved", "macro_recovered", "macro_deleted"):
            self.snapshot = message["snapshot"]
            storage = self.snapshot["storage"]
            self.capacity.setText(f"{storage['stored_count']} / {storage['max_macros']} macro entries · "
                                  f"{storage['free_bytes']:,} bytes available · "
                                  f"{storage['reclaimable_bytes']:,} reclaimable (compaction disabled)")
            self.inventory_button.setText(f"On mouse ({storage['stored_count']})")
            rows = inventory_rows(self.snapshot)
            self.inventory.setRowCount(len(rows))
            for row, values in enumerate(rows):
                for column, value in enumerate(values):
                    self.inventory.setItem(row, column, QTableWidgetItem(value))
            self.show_binding()
            self.saved = kind != "macro_snapshot"
            self.set_busy(False)
            if self.saved:
                self.last_journal = message.get("journal", self.last_journal)
                self.status.setText('Macro deleted from mouse. Button assignments and the local library are unchanged.'
                    if kind == 'macro_deleted' else "Macro saved to mouse."
                    if kind == "macro_saved" else "Original macro and button assignments restored.")
            else:
                self.status.setText("Ready.")
        elif kind in ("macro_prepared", "macro_delete_prepared"):
            if not self.busy or self.pending_write != kind:
                return
            self.pending_write = None
            try:
                deleting = kind == 'macro_delete_prepared'
                writer = write_macro_delete_backup if deleting else write_macro_backup
                path, journal = writer(self.profile_path, message["backup"], message["token"])
                self.last_journal = str(journal)
                self.log.appendPlainText(f"Private backup: {path}\nRecovery journal: {journal}")
                commit = {"command": 'macro_delete_commit' if deleting else "macro_commit", "token": message["token"], "journal": str(journal)}
                if not deleting and getattr(self, "batch_keep_open", False):
                    commit["keep_open"] = True
                self.backend.send(commit)
                self.set_operation_status('Deleting macro and verifying mouse state…' if deleting else "Saving macro and verifying mouse state…")
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.backend.shutdown()
                self.error(f"Backup failed; no macro commit sent: {error}")
        elif kind in ("macro_error", "error"):
            self.error(message.get("message", "Macro operation failed"))
        elif kind == "faceplate":
            self.invalidate()
            if not self.busy:
                self.set_busy(False)
                self.status.setText("Mouse plate changed. Read storage again before saving.")

    def error(self, error):
        self.pending_write = None
        self.invalidate()
        self.saved = False
        self.show_binding()
        self.set_busy(False)
        self.status.setText(str(error))
        self.log.appendPlainText(str(error))

    def detach_backend(self):
        if self.backend_attached:
            self.backend.event.disconnect(self.on_event)
            self.backend.connected.disconnect(self.connected)
            self.backend.log.disconnect(self.log.appendPlainText)
            self.backend_attached = False

    def done(self, result):
        if self.busy:
            return
        if not self.shared_backend:
            self.backend.shutdown()
        self.detach_backend()
        super().done(result)

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
