"""Independent wheel-settings drafts and the durable backup acknowledgement boundary."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import struct

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QPlainTextEdit, QSizePolicy, QVBoxLayout,
)
from backend import Backend
from model import save_profile
from haptic_presets import PRESET_NAMES as PRESETS, PRESET_DESCRIPTIONS, BUILTIN_PRESETS


def write_haptic_backup(profile_path, backup, token):
    if not token.isdecimal() or len(token) > 40:
        raise ValueError("Invalid wheel backup token")
    if backup.get("format") != 1 or backup.get("kind") != "haptic_settings_backup" or not backup.get("slots"):
        raise ValueError("Not a complete wheel-settings backup")
    serial = re.sub(r"[^A-Za-z0-9_-]", "_", backup["guard"]["device"]["serial"])
    path = profile_path.parent / "backups" / f"{serial}-wheel-{token}.json"
    save_profile(path, backup)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def stage_edit(stages, active):
    stages = list(stages)
    if not stages or len(stages) > 6 or len(set(stages)) != len(stages) or any(s not in PRESETS for s in stages):
        raise ValueError("Enable one to six distinct supported wheel stages")
    if active not in stages:
        raise ValueError("Choose an enabled active stage")
    return {"stages": stages, "active_position": stages.index(active) + 1}


def describe_custom(state):
    metadata = state["metadata"]
    lines = []
    if len(metadata) == 40:
        lines.append(f"Editor metadata — Up: tension {metadata[4]}, {metadata[3]} steps/revolution; "
                     f"Down: tension {metadata[6]}, {metadata[5]} steps/revolution.")
        lines.append("Up/down editor linkage: " + ("linked" if metadata[2] == 1 else "independent or unknown"))
    else:
        lines.append(f"Unknown editor metadata format ({len(metadata)} bytes); preserved unchanged.")
    configuration = bytes(state["configuration"])
    if len(configuration) == 26:
        cw_deadzone, cw_tick, ccw_deadzone, ccw_tick = struct.unpack("<ffff", configuration[4:20])
        lines.append(f"Stored tick angles — Up: {cw_tick:g}°; Down: {ccw_tick:g}°.")
        lines.append(f"Deadzone reduction — Up: {cw_deadzone:g}°; Down: {ccw_deadzone:g}°.")
    lines.append("Reported table points (up, down, velocity): " + ", ".join(str(len(t)) for t in state["tables"]))
    tables = state["tables"]
    if len(tables) == 3 and tables[2] and tables[0][:len(tables[2])] == tables[2]:
        lines.append("Warning: velocity replies overlap the up table; independent down/velocity readback is unverified.")
    lines.append("Metadata describes the editor settings; actual firmware tables are preserved separately.")
    return "\n".join(lines)


class WheelDialog(QDialog):
    def __init__(self, profile_path, parent=None, backend=None, *, shared=False):
        super().__init__(parent)
        self.profile_path = Path(profile_path)
        if shared and backend is None:
            raise ValueError("A shared editor requires an existing backend")
        self.shared_backend = shared
        self.backend = backend or Backend(self)
        self.backend_attached = True
        self.snapshot = None
        self.busy = False
        self.pending = None
        self.saved = False
        self.setWindowTitle("HyperScroll Pro wheel")
        self.resize(630, 650)
        layout = QVBoxLayout(self)
        self.status = QLabel("Connect to read wheel settings. Opening this window stops software remaps.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.read_button = QPushButton("Read wheel")
        self.read_button.clicked.connect(self.read)
        row.addWidget(self.read_button)
        self.restore_button = QPushButton("Restore wheel backup…")
        self.restore_button.clicked.connect(self.restore)
        row.addWidget(self.restore_button)
        layout.addLayout(row)
        self.stored = QLabel("Stored wheel settings: unread")
        self.stored.setWordWrap(True)
        layout.addWidget(self.stored)
        box = QGroupBox("Wheel stage draft")
        form = QVBoxLayout(box)
        hint = QLabel("Check the stages to include in cycling. Drag to reorder them, then choose the active stage.")
        hint.setWordWrap(True)
        form.addWidget(hint)
        self.stages = QListWidget()
        self.stages.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.stages.itemChanged.connect(self.update_active)
        self.stages.model().rowsMoved.connect(self.update_active)
        form.addWidget(self.stages)
        self.active = QComboBox()
        fields = QFormLayout()
        fields.addRow("Active stage", self.active)
        form.addLayout(fields)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.active.currentIndexChanged.connect(self.describe_active)
        form.addWidget(self.description)
        self.defaults_button = QPushButton("Use wheel stage defaults as draft")
        self.defaults_button.clicked.connect(self.defaults)
        form.addWidget(self.defaults_button)
        layout.addWidget(box)
        custom = QGroupBox("Custom settings")
        custom_layout = QVBoxLayout(custom)
        notice = QLabel("Custom editing is deferred. Existing Custom settings are preserved when saving standard modes.")
        notice.setWordWrap(True)
        custom_layout.addWidget(notice)
        self.details_button = QPushButton("Show read-only wheel details")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self.show_details)
        custom_layout.addWidget(self.details_button)
        self.custom = QLabel("Unread")
        self.custom.setWordWrap(True)
        self.custom.hide()
        custom_layout.addWidget(self.custom)
        layout.addWidget(custom)
        self.save_button = QPushButton("Save wheel stages to mouse")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(90)
        layout.addWidget(self.log)
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.rejected.connect(self.reject)
        layout.addWidget(self.close_buttons)
        self.backend.event.connect(self.on_event)
        self.backend.connected.connect(self.connected)
        self.backend.log.connect(self.log.appendPlainText)
        self.set_busy(False)

    def set_busy(self, value):
        self.busy = value
        editable = (not value and self.snapshot is not None and not self.saved
                    and all(s in PRESETS for s in self.snapshot["state"]["stages"]))
        self.read_button.setEnabled(not value)
        self.restore_button.setEnabled(editable)
        self.save_button.setEnabled(editable)
        self.stages.setEnabled(editable)
        self.active.setEnabled(editable)
        self.defaults_button.setEnabled(editable)
        self.close_buttons.setEnabled(not value)

    def show_details(self, checked):
        self.custom.setVisible(checked)
        self.details_button.setText("Hide read-only wheel details" if checked else "Show read-only wheel details")

    def describe_active(self, *_):
        stage = self.active.currentData()
        description = PRESET_DESCRIPTIONS.get(stage, "Choose an enabled standard mode.")
        if stage is not None and stage not in BUILTIN_PRESETS:
            description = "Existing nonstandard mode is preserved. Choose a standard mode to change the active feel; Custom editing is deferred."
        self.description.setText(description)

    def send(self, payload):
        if self.backend.ready:
            if not getattr(self.backend, "haptic_settings", False):
                raise ValueError("Wheel settings require wired Naga V2 Pro and an updated helper.")
            self.backend.send(payload)
        else:
            self.pending = payload
            self.backend.start()

    def connected(self, ready):
        if ready:
            if not self.backend.haptic_settings:
                self.error("Wheel settings require wired Naga V2 Pro and an updated helper.")
                if not self.shared_backend:
                    self.backend.shutdown()
                return
            if self.pending:
                payload, self.pending = self.pending, None
                self.backend.send(payload)
        elif not self.saved:
            self.snapshot = None
            self.pending = None
            self.stored.setText("Stored wheel settings: unread · helper disconnected")
            self.set_busy(False)

    def read(self):
        self.snapshot = None
        self.saved = False
        self.stored.setText("Stored wheel settings: unread")
        self.set_busy(True)
        self.status.setText("Loading wheel settings…")
        try:
            self.send({"command": "haptic_read", "slot": None})
        except (OSError, ValueError) as error:
            self.error(error)

    def populate(self, stages, active):
        self.stages.blockSignals(True)
        self.stages.clear()
        order = list(stages) + [s for s in BUILTIN_PRESETS if s not in stages]
        for stage in order:
            item = QListWidgetItem(PRESETS.get(stage, f"Unknown stage {stage:02x}"))
            if stage not in BUILTIN_PRESETS:
                item.setText(item.text() + " (preserved; editing deferred)")
            item.setToolTip(PRESET_DESCRIPTIONS.get(stage, "Unknown firmware preset; its behavior is unverified."))
            item.setData(Qt.ItemDataRole.UserRole, stage)
            if stage in BUILTIN_PRESETS:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            else:
                item.setFlags(item.flags() & ~(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled))
            item.setCheckState(Qt.CheckState.Checked if stage in stages else Qt.CheckState.Unchecked)
            self.stages.addItem(item)
        self.stages.blockSignals(False)
        self.update_active()
        self.active.setCurrentIndex(self.active.findData(active))
        self.describe_active()

    def update_active(self, *_args):
        active = self.active.currentData()
        self.active.blockSignals(True)
        self.active.clear()
        for row in range(self.stages.count()):
            item = self.stages.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                stage = item.data(Qt.ItemDataRole.UserRole)
                original_active = None
                if self.snapshot:
                    state = self.snapshot["state"]
                    original_active = state["stages"][state["active_position"] - 1]
                if stage in BUILTIN_PRESETS or stage == original_active:
                    self.active.addItem(item.text(), stage)
                    if stage not in BUILTIN_PRESETS:
                        self.active.model().item(self.active.count() - 1).setEnabled(False)
        if active is not None and self.active.findData(active) >= 0:
            self.active.setCurrentIndex(self.active.findData(active))
        self.active.blockSignals(False)
        self.describe_active()

    def defaults(self):
        if not self.snapshot:
            return
        preserved = [s for s in self.snapshot["state"]["stages"] if s not in BUILTIN_PRESETS]
        if any(s not in PRESETS for s in preserved):
            self.status.setText("Unknown stored stages make this snapshot read-only.")
            return
        self.populate([*BUILTIN_PRESETS, *preserved], 0x81)
        self.status.setText("Wheel stage defaults staged locally. Save to apply; custom curves and button bindings are preserved.")

    def save(self):
        if self.snapshot is None or self.busy or self.saved:
            return
        try:
            stages = [self.stages.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.stages.count())
                      if self.stages.item(row).checkState() == Qt.CheckState.Checked]
            if not any(stage in BUILTIN_PRESETS for stage in stages):
                raise ValueError("Keep at least one standard mode enabled.")
            edit = stage_edit(stages, self.active.currentData())
            original = self.snapshot["state"]
            if set(stages) - set(BUILTIN_PRESETS) != set(original["stages"]) - set(BUILTIN_PRESETS):
                raise ValueError("Existing Custom stages must be preserved; Custom editing is deferred.")
        except ValueError as error:
            self.status.setText(str(error))
            return
        if edit == {"stages": original["stages"], "active_position": original["active_position"]}:
            self.status.setText("Stage draft already matches stored settings.")
            return
        try:
            self.set_busy(True)
            self.saved = False
            self.status.setText("Preparing wheel-state and mapping backups…")
            self.send({"command": "haptic_prepare", "known": copy.deepcopy(self.snapshot), "edit": edit})
        except (OSError, ValueError) as error:
            self.error(error)

    def restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore wheel stage settings", str(self.profile_path.parent / "backups"), "JSON (*.json)")
        if not path:
            return
        try:
            backup = json.loads(Path(path).read_text())
            if backup.get("kind") != "haptic_settings_backup":
                raise ValueError("Choose a wheel-settings backup. Diagnostic and binding backups cannot restore wheel settings.")
            self.set_busy(True)
            self.saved = False
            self.send({"command": "haptic_restore", "backup": backup, "slot": self.snapshot["state"]["slot"]})
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.error(error)

    def on_event(self, message):
        kind = message.get("type")
        if kind in ("haptic_snapshot", "haptic_saved"):
            self.snapshot = message["snapshot"]
            state = self.snapshot["state"]
            active = state["stages"][state["active_position"] - 1]
            self.stored.setText(f"Stored slot {state['slot']} · active: {PRESETS.get(active, f'unknown {active:02x}')} · "
                                f"cycling: {', '.join(PRESETS.get(s, f'{s:02x}') for s in state['stages'])}")
            self.custom.setText(describe_custom(state))
            self.populate(state["stages"], active)
            self.saved = kind == "haptic_saved"
            self.set_busy(False)
            self.status.setText("Saved and verified on mouse · helper stopped. Read again before another save." if self.saved else "Wheel settings read. Editing only changes the local draft.")
            if any(s not in PRESETS for s in state["stages"]):
                self.status.setText("Unknown stored stages: settings are read-only and preserved.")
            if self.saved:
                self.save_button.setEnabled(False)
                self.restore_button.setEnabled(False)
        elif kind == "haptic_prepared":
            try:
                path = write_haptic_backup(self.profile_path, message["backup"], message["token"])
                self.log.appendPlainText(f"Wheel backup: {path}")
                self.backend.send({"command": "haptic_commit", "token": message["token"]})
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.backend.shutdown()
                self.error(f"Backup failed; no wheel commit sent: {error}")
        elif kind in ("haptic_error", "error"):
            self.error(message.get("message", "Wheel operation failed"))

    def error(self, error):
        self.snapshot = None
        self.pending = None
        self.saved = False
        self.stored.setText("Stored wheel settings: unread")
        self.status.setText(str(error))
        self.log.appendPlainText(str(error))
        self.set_busy(False)

    def detach_backend(self):
        if self.backend_attached:
            self.backend.event.disconnect(self.on_event)
            self.backend.connected.disconnect(self.connected)
            self.backend.log.disconnect(self.log.appendPlainText)
            self.backend_attached = False

    def done(self, result):
        if self.busy:
            self.status.setText("Wait for the wheel operation to finish before closing.")
            return
        if not self.shared_backend:
            self.backend.shutdown()
        self.detach_backend()
        super().done(result)

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
            self.status.setText("Wait for the wheel operation to finish before closing.")
            return
        super().closeEvent(event)


class WheelPanel(WheelDialog):
    """Persistent device-tab editor; takes helper ownership only for an operation."""
    busyChanged = Signal(bool)

    def __init__(self, profile_path, parent=None, backend=None):
        super().__init__(profile_path, parent, backend, shared=True)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.close_buttons.hide()
        self.log.hide()
        # Show every stage without scrolling; the list takes any spare page height.
        self.stages.setMinimumHeight(6 * 38 + 8)
        self.stages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        stage_box = self.stages.parentWidget()
        stage_box.layout().setStretchFactor(self.stages, 1)
        self.active.setMinimumWidth(220)
        self.status.setText('Read the mouse to configure wheel stages.')
        details = self.details_button.parentWidget()
        details.layout().removeWidget(self.details_button)
        self.layout().removeWidget(details)
        self.layout().insertWidget(5, self.details_button)
        self.layout().insertWidget(6, details)
        details.hide()
        self.details_button.toggled.connect(details.setVisible)
        self.details_button.toggled.connect(self.log.setVisible)
        self.save_button.setProperty('role', 'primary')
        self.status.setProperty('role', 'muted')
        self.stored.setProperty('role', 'readout')
        self.layout().setSpacing(14)
        self.layout().setStretchFactor(stage_box, 1)

    def set_busy(self, value):
        previous = getattr(self, 'busy', False)
        super().set_busy(value)
        if value != previous:
            self.busyChanged.emit(value)

    def connected(self, ready):
        if self.busy or not ready:
            super().connected(ready)

    def on_event(self, message):
        if self.busy:
            super().on_event(message)
        elif message.get('type') == 'faceplate':
            self.snapshot = None
            self.set_busy(False)
