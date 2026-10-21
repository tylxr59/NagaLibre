"""Onboard macro drafts, stored contents and durable upload acknowledgement."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import uuid

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)
from backend import Backend
from model import CONTROL_NAMES, display_key, key_code, new_profile, runtime_config, save_profile
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
    if not isinstance(token, str) or not token.isdecimal() or len(token) > 40:
        raise ValueError("Invalid macro backup token")
    if (backup.get("format") != 1 or backup.get("kind") != "onboard_macro_transaction_backup"
            or backup.get("complete_profile") is not False
            or backup.get("contents", {}).get("kind") != "onboard_macro_storage_checkpoint"
            or backup.get("mappings", {}).get("kind") != "paired_mapping_backup"):
        raise ValueError("Not a macro content/mapping transaction backup")
    directory = Path(profile_path).parent / "backups" / "macros"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stat = directory.lstat()
    if directory.is_symlink() or stat.st_uid != os.geteuid() or stat.st_mode & 0o077:
        raise ValueError("Macro backups need a private directory owned by this user")
    serial = re.sub(r"[^A-Za-z0-9_-]", "_", backup["contents"]["inspection"]["guard"]["device"]["serial"])
    path = directory / f"{serial}-macro-{token}.json"
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
        self.last_journal = None
        self.setWindowTitle("Onboard macros")
        self.resize(680, 690)
        layout = QVBoxLayout(self)
        note = QLabel("Experimental wired support · twelve-button plate. Uploads are read back before binding. "
                      "Playback and reconnect behavior still need physical verification. "
                      "Stop a toggle with its button before changing or undoing it.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel("Read mouse storage to begin. Editing changes the local draft.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.read_button = QPushButton("Read mouse")
        self.read_button.clicked.connect(self.read)
        row.addWidget(self.read_button)
        self.undo_button = QPushButton("Undo upload…")
        self.undo_button.clicked.connect(self.undo)
        row.addWidget(self.undo_button)
        layout.addLayout(row)
        self.capacity = QLabel("Storage: unread")
        layout.addWidget(self.capacity)
        self.inventory = QTableWidget(0, 3)
        self.inventory.setHorizontalHeaderLabels(["Stored macro", "ID", "Sequence bytes"])
        self.inventory.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.inventory.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.inventory)
        fields = QFormLayout()
        self.target = QComboBox()
        for i in range(1, 17):
            self.target.addItem(f"Grid {i}" if i <= 12 else CONTROL_NAMES[i - 13], i)
        self.target.setCurrentIndex(max(0, min(15, button - 1)))
        fields.addRow("Target", self.target)
        self.layer = QComboBox()
        self.layer.addItems(["Normal", "Hypershift"])
        self.layer.setCurrentIndex(layer if layer in (0, 1) else 0)
        fields.addRow("Layer", self.layer)
        self.stored = QLabel("Stored binding: unread")
        fields.addRow(self.stored)
        self.name = QLineEdit("New macro")
        self.name.setMaxLength(100)
        fields.addRow("Name (100 UTF-8 bytes)", self.name)
        self.playback = QComboBox()
        for title, mode in PLAYBACK:
            self.playback.addItem(title, mode)
        fields.addRow("Playback", self.playback)
        self.count = QSpinBox()
        self.count.setRange(1, 255)
        self.count.setValue(3)
        fields.addRow("Repeat count", self.count)
        layout.addLayout(fields)
        self.edit_button = QPushButton("Edit sequence…")
        self.edit_button.clicked.connect(self.edit)
        layout.addWidget(self.edit_button)
        self.sequence = QPlainTextEdit()
        self.sequence.setReadOnly(True)
        self.sequence.setMaximumHeight(110)
        layout.addWidget(self.sequence)
        self.save_button = QPushButton("Save macro to mouse")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(95)
        layout.addWidget(self.log)
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.rejected.connect(self.reject)
        layout.addWidget(self.close_buttons)
        self.target.currentIndexChanged.connect(self.show_binding)
        self.layer.currentIndexChanged.connect(self.show_binding)
        self.playback.currentIndexChanged.connect(lambda *_: self.set_busy(self.busy))
        self.backend.event.connect(self.on_event)
        self.backend.connected.connect(self.connected)
        self.backend.log.connect(self.log.appendPlainText)
        self.show_steps()
        self.set_busy(False)

    def show_steps(self):
        lines = []
        for index, step in enumerate(self.steps, 1):
            try:
                if not isinstance(step, dict) or len(step) != 1:
                    raise ValueError("Invalid sequence step")
                kind, value = next(iter(step.items()))
                if kind == "wait_ms":
                    text = f"Wait {value} ms"
                elif kind == "chord":
                    text = "Shortcut " + "+".join(display_key(key_code(k)) for k in value)
                else:
                    text = {"tap": "Tap", "down": "Hold", "up": "Release"}[kind] + " " + display_key(key_code(value))
            except (ValueError, KeyError, TypeError):
                text = "Invalid step — edit the sequence"
            lines.append(f"{index}. {text}")
        self.sequence.setPlainText("\n".join(lines) if lines else "No sequence drafted")

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
        self.capacity.setText("Storage: unread")
        self.show_binding()

    def set_busy(self, busy):
        self.busy = busy
        editable = not busy and self.snapshot is not None and not self.saved and self.backend.ready
        self.read_button.setEnabled(not busy)
        self.undo_button.setEnabled(not busy)
        self.save_button.setEnabled(editable)
        for widget in (self.target, self.layer, self.name, self.playback, self.edit_button):
            widget.setEnabled(not busy)
        self.count.setEnabled(not busy and self.playback.currentData() == "counted")
        self.close_buttons.setEnabled(not busy)

    def edit(self):
        from app import MacroDialog
        dialog = MacroDialog(self.steps, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.steps = dialog.steps()
            self.show_steps()

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
            self.invalidate()
            self.set_busy(False)
            self.status.setText("Helper disconnected. Read again; retain any transaction journal for recovery.")

    def read(self):
        self.invalidate()
        self.saved = False
        self.show_binding()
        self.set_busy(True)
        self.status.setText("Reading macro storage and paired mappings twice…")
        try:
            self.send({"command": "macro_read"})
        except (OSError, ValueError) as error:
            self.error(error)

    def save(self):
        if self.busy or self.snapshot is None or self.saved:
            return
        try:
            name = self.name.text()
            if not name or len(name.encode("utf-8")) > 100 or "\0" in name:
                raise ValueError("Name must contain 1–100 UTF-8 bytes without NUL.")
            if not self.steps:
                raise ValueError("Create a sequence first.")
            playback = {"mode": self.playback.currentData()}
            if playback["mode"] == "counted":
                playback["count"] = self.count.value()
            request = {"trigger": "KEY_F24", "guid": str(uuid.uuid4()), "name": name,
                       "button": self.target.currentData(), "layer": self.layer.currentIndex(),
                       "playback": playback}
            config = macro_config(self.steps)
            self.set_busy(True)
            self.status.setText("Checking current storage and preparing a private recovery backup…")
            self.send({"command": "macro_prepare", "config": config, "request": request})
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.error(error)

    def undo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Recover an onboard macro transaction",
            str(self.last_journal or self.profile_path.parent / "backups" / "macros"), "Macro journals (*.jsonl)")
        if not path:
            return
        self.saved = False
        self.invalidate()
        self.set_busy(True)
        self.status.setText("Restoring original bindings before cleaning up this upload…")
        try:
            self.send({"command": "macro_recover", "journal": path})
        except (OSError, ValueError) as error:
            self.error(error)

    def on_event(self, message):
        kind = message.get("type")
        if kind in ("macro_snapshot", "macro_saved", "macro_recovered"):
            self.snapshot = message["snapshot"]
            storage = self.snapshot["storage"]
            self.capacity.setText(f"{storage['stored_count']} / {storage['max_macros']} macro entries · "
                                  f"{storage['free_bytes']:,} bytes available · "
                                  f"{storage['reclaimable_bytes']:,} reclaimable (compaction disabled)")
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
                self.status.setText("Upload and binding read back; helper stopped. Playback remains experimental."
                                    if kind == "macro_saved" else "Original macro contents and scoped bindings restored; owned allocation removed.")
            else:
                self.status.setText("Storage read. Existing macro contents are preserved; Save uploads a fresh entry.")
        elif kind == "macro_prepared":
            try:
                path, journal = write_macro_backup(self.profile_path, message["backup"], message["token"])
                self.last_journal = str(journal)
                self.log.appendPlainText(f"Private backup: {path}\nRecovery journal: {journal}")
                self.backend.send({"command": "macro_commit", "token": message["token"], "journal": str(journal)})
                self.status.setText("Uploading, verifying contents, then binding the sequence…")
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
