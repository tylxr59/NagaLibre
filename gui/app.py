from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

from PySide6.QtCore import Qt, QTimer, QLockFile, QStandardPaths, QUrl
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QStackedWidget, QSystemTrayIcon, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView, QKeySequenceEdit, QFileDialog,
)

from onboard import hardware_buttons, write_backup, stored_label
from backend import Backend, backend_path
from support import device_issue_url
from model import (
    binding_label, config_path, default_button, display_key, key_code, load_profile,
    new_profile, reset_plate, runtime_config, save_profile, shortcut, PROTECTED_INPUTS, DEVICE_MODELS,
)


def app_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2dc4a2"))
    painter.drawRoundedRect(5, 5, 54, 54, 15, 15)
    painter.setPen(QColor("#10201e"))
    font = painter.font()
    font.setPixelSize(36)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "N")
    painter.end()
    return QIcon(pix)


class MacroDialog(QDialog):
    TYPES = [("Tap key", "tap"), ("Shortcut", "chord"), ("Wait (ms)", "wait_ms"), ("Hold key", "down"), ("Release key", "up")]

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit macro")
        self.resize(570, 420)
        layout = QVBoxLayout(self)
        help_label = QLabel("Actions play in order. Shortcuts use Ctrl+C style names.\nPair every Hold key with a Release key.")
        layout.addWidget(help_label)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Action", "Key / shortcut / milliseconds"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        controls = QHBoxLayout()
        for label, callback in [("Add step", lambda: self.add()), ("Remove", self.remove), ("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(1))]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for step in steps:
            kind, value = next(iter(step.items()))
            self.add(kind, "+".join(display_key(k) for k in value) if kind == "chord" else str(value))
        if not steps:
            self.add()

    def add(self, kind="tap", value=""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        combo = QComboBox()
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

    def accept_checked(self):
        try:
            self.steps()
        except ValueError as error:
            QMessageBox.warning(self, "Check macro", str(error))
            return
        self.accept()


class Window(QMainWindow):
    def __init__(self, profile_path=None):
        super().__init__()
        self.path = profile_path or config_path()
        self.base_profile_path = self.path
        self.device_model = DEVICE_MODELS["naga_v2_pro"]
        self.model_drafts = {}
        self.support_devices = []
        self.load_error = None
        try:
            self.profile = load_profile(self.path)
        except (ValueError, KeyError, TypeError, OSError) as error:
            self.profile = new_profile()
            self.load_error = str(error)
        self.selected = 0
        self.loading = False
        self.learning = False
        self.learn_pending = False
        self.pending_config = None
        self.pending_onboard = None
        self.detected_module = None
        self.plate_detection = "offline"
        self.hardware_busy = False
        self.hardware_saved = None
        self.snapshot = None
        self.save_after_read = False
        self.applying = False
        self.fault = False
        self.quitting = False
        self.backend = Backend(self)
        self.backend.event.connect(self.on_event)
        self.backend.log.connect(self.log)
        self.backend.connected.connect(self.connection_changed)
        self.setWindowTitle("NagaLibre")
        self.setWindowIcon(app_icon())
        self.resize(980, 720)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 24, 28, 20)
        title = QLabel("NagaLibre")
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Your Naga. Your buttons. Linux native."))
        connection = QHBoxLayout()
        self.device_label = QLabel("Looking for a supported Razer mouse…")
        self.device_label.setWordWrap(True)
        connection.addWidget(self.device_label, 1)
        self.connect_button = QPushButton("Connect mouse")
        self.connect_button.clicked.connect(self.connect_mouse)
        connection.addWidget(self.connect_button)
        layout.addLayout(connection)
        support_row = QHBoxLayout()
        self.support_hint = QLabel()
        self.support_hint.setWordWrap(True)
        support_row.addWidget(self.support_hint, 1)
        self.support_button = QPushButton("Request device support…")
        self.support_button.setToolTip("Open a GitHub form with diagnostic instructions. Review and submit it yourself.")
        self.support_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(device_issue_url(self.support_devices))))
        support_row.addWidget(self.support_button)
        layout.addLayout(support_row)
        self.status = QLabel("Offline · edit bindings, then connect to test.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("padding: 10px; background: #24312f; border-radius: 6px; color: #8ce3cb;")
        layout.addWidget(self.status)
        storage_row = QHBoxLayout()
        self.storage = QComboBox()
        self.storage.addItem("Mouse memory · no background app", "hardware")
        self.storage.addItem("Software · background helper", "software")
        self.storage.setCurrentIndex(max(0, self.storage.findData(self.profile.get("storage", "hardware"))))
        storage_row.addWidget(self.storage, 1)
        self.slots = QComboBox()
        self.slots.addItem("Active mouse slot", None)
        storage_row.addWidget(self.slots)
        self.read_button = QPushButton("Read slots")
        self.read_button.clicked.connect(self.read_mouse)
        storage_row.addWidget(self.read_button)
        self.restore_button = QPushButton("Restore backup…")
        self.restore_button.clicked.connect(self.restore_backup)
        storage_row.addWidget(self.restore_button)
        layout.addLayout(storage_row)
        self.memory_hint = QLabel("Each tile shows the stored mouse binding and your local draft separately. Save writes all 12 draft bindings to the selected slot. Macro sequences require software mode.")
        self.memory_hint.setWordWrap(True)
        layout.addWidget(self.memory_hint)
        columns = QHBoxLayout()
        left = QGroupBox("Side buttons")
        left_layout = QVBoxLayout(left)
        self.plate = QComboBox()
        for p in ("12", "6", "2"):
            self.plate.addItem(f"{p}-button plate", p)
        self.plate.setCurrentIndex(self.plate.findData(self.profile["plate"]))
        self.plate.currentIndexChanged.connect(self.change_plate)
        left_layout.addWidget(self.plate)
        self.plate_hint = QLabel("Connect mouse to detect the attached plate automatically.")
        self.plate_hint.setWordWrap(True)
        left_layout.addWidget(self.plate_hint)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 10, 0, 10)
        left_layout.addWidget(self.grid_host, 1)
        self.last_input = QLabel("Last press: —")
        self.last_input.setWordWrap(True)
        left_layout.addWidget(self.last_input)
        self.reset_button = QPushButton("Reset plate to defaults")
        self.reset_button.clicked.connect(self.reset_defaults)
        left_layout.addWidget(self.reset_button)
        columns.addWidget(left, 1)
        editor = QGroupBox("Draft binding · local edits")
        edit_layout = QVBoxLayout(editor)
        self.button_title = QLabel()
        self.button_title.setStyleSheet("font-size: 20px; font-weight: 600;")
        edit_layout.addWidget(self.button_title)
        self.stored_binding = QLabel()
        self.stored_binding.setWordWrap(True)
        edit_layout.addWidget(self.stored_binding)
        form = QFormLayout()
        trigger_row = QHBoxLayout()
        self.trigger = QLineEdit()
        self.trigger.setReadOnly(True)
        self.trigger.setPlaceholderText("Learn this button’s input")
        self.trigger.setToolTip("The key emitted by this physical button, e.g. KEY_1 or BTN_SIDE.")
        trigger_row.addWidget(self.trigger)
        self.learn_button = QPushButton("Learn input")
        self.learn_button.clicked.connect(self.learn_input)
        trigger_row.addWidget(self.learn_button)
        form.addRow("Input", trigger_row)
        self.mode = QComboBox()
        for label, data in [("Default / pass through", "default"), ("Keyboard key (hold supported)", "key"), ("Shortcut", "shortcut"), ("Macro sequence", "macro")]:
            self.mode.addItem(label, data)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        form.addRow("Action", self.mode)
        edit_layout.addLayout(form)
        self.stack = QStackedWidget()
        default_page = QLabel("Mouse memory: restore this position’s factory key. Software: pass the current input through.")
        default_page.setWordWrap(True)
        self.stack.addWidget(default_page)
        key_page = QWidget()
        key_layout = QVBoxLayout(key_page)
        self.key_value = QLineEdit()
        self.key_value.setPlaceholderText("A, F13, Enter, KEY_LEFTCTRL, BTN_SIDE…")
        key_layout.addWidget(self.key_value)
        key_hint = QLabel("Pressing and releasing the mouse button presses and releases this key.")
        key_hint.setWordWrap(True)
        key_layout.addWidget(key_hint)
        self.stack.addWidget(key_page)
        shortcut_page = QWidget()
        shortcut_layout = QVBoxLayout(shortcut_page)
        self.shortcut_value = QLineEdit()
        self.shortcut_value.setPlaceholderText("Ctrl+C, Alt+Tab, Super+E…")
        shortcut_layout.addWidget(self.shortcut_value)
        self.recorder = QKeySequenceEdit()
        self.recorder.setMaximumSequenceLength(1)
        self.recorder.keySequenceChanged.connect(lambda value: self.shortcut_value.setText(value.toString()))
        shortcut_layout.addWidget(QLabel("Or click below and press a shortcut:"))
        shortcut_layout.addWidget(self.recorder)
        self.stack.addWidget(shortcut_page)
        macro_page = QWidget()
        macro_layout = QVBoxLayout(macro_page)
        self.macro_summary = QLabel()
        self.macro_summary.setWordWrap(True)
        macro_layout.addWidget(self.macro_summary)
        macro_button = QPushButton("Edit macro steps…")
        macro_button.clicked.connect(self.edit_macro)
        macro_layout.addWidget(macro_button)
        self.stack.addWidget(macro_page)
        edit_layout.addWidget(self.stack)
        edit_layout.addStretch()
        per_button_reset = QPushButton("Use default for this button")
        per_button_reset.clicked.connect(self.reset_selected)
        edit_layout.addWidget(per_button_reset)
        columns.addWidget(editor, 1)
        layout.addLayout(columns, 1)
        actions = QHBoxLayout()
        self.stop_button = QPushButton("Stop remapping")
        self.stop_button.clicked.connect(self.stop_remapping)
        actions.addWidget(self.stop_button)
        actions.addStretch()
        save = QPushButton("Save draft")
        save.clicked.connect(self.save)
        actions.addWidget(save)
        self.apply_button = QPushButton("Apply bindings")
        self.apply_button.setStyleSheet("QPushButton {background: #2dc4a2; color: #10201e; font-weight: bold; padding: 10px 18px;} QPushButton:disabled {background: #68716f; color: #c4cac8;}")
        self.apply_button.clicked.connect(self.apply)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        stop_action = QAction("Stop remapping", self)
        stop_action.setShortcut("Escape")
        stop_action.triggered.connect(self.stop_remapping)
        self.addAction(stop_action)
        quit_action = QAction("Quit NagaLibre", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.quit)
        self.addAction(quit_action)
        layout.addWidget(QLabel("Keyboard controls: Esc stops remapping · Ctrl+Q quits (with this window focused)."))
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(150)
        self.logs.setMaximumHeight(85)
        self.logs.setPlaceholderText("Connection and validation details appear here.")
        layout.addWidget(self.logs)
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("NagaLibre")
        menu = QMenu(self)
        for title, callback in [("Show NagaLibre", self.show_window), ("Stop remapping", self.stop_remapping), ("Quit", self.quit)]:
            action = QAction(title, self)
            action.triggered.connect(callback)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.slots.currentIndexChanged.connect(self.refresh_hardware_view)
        self.storage.currentIndexChanged.connect(self.storage_changed)
        self.storage_changed()
        self.rebuild_grid()
        self.select_button(0, commit=False)
        if self.load_error:
            self.log("Saved profile could not be loaded: " + self.load_error + " Saving is disabled to preserve it.")
        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self.scan_devices)
        self.scan_timer.start(3000)
        self.scan_devices()
        self.learn_timer = QTimer(self)
        self.learn_timer.setSingleShot(True)
        self.learn_timer.timeout.connect(self.cancel_learning)

    def buttons(self):
        return self.profile["plates"][self.profile["plate"]]

    def current(self):
        return self.buttons()[self.selected]

    def log(self, message):
        self.logs.appendPlainText(message.strip())

    def fail(self, error):
        self.status.setText(str(error))
        self.log(str(error))

    def scan_devices(self):
        try:
            result = subprocess.run([str(backend_path()), "list", "--json", "--all-razer"], capture_output=True, text=True, timeout=1)
            if result.returncode:
                raise ValueError(result.stderr.strip())
            devices = json.loads(result.stdout)
            if not isinstance(devices, list) or any(not isinstance(d, dict) for d in devices):
                raise ValueError("Invalid device inventory from input engine; rebuild the engine and app together.")
            self.support_devices = devices
            names = sorted({(d.get("model") or {}).get("name", d.get("name", "Razer mouse")) for d in devices})
            description = ", ".join(names) if devices else "No supported Razer mouse connected"
            if any(d.get("model") and not d["model"]["verified"] for d in devices):
                description += " · experimental, hardware unverified"
            self.device_label.setText(description)
            if any(d.get("model") is None for d in devices):
                self.support_hint.setText("Unrecognized Razer device detected. Request support with its diagnostics.")
            elif any(not d["model"]["verified"] for d in devices):
                self.support_hint.setText("Experimental model: report your results to help verify support.")
            else:
                self.support_hint.clear()
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            self.support_devices = []
            self.support_hint.setText("Need help? Open a device support request with diagnostic output.")
            self.device_label.setText(f"Input engine unavailable: {error}")

    def connect_mouse(self):
        if self.backend.ready:
            # Reconnect obtains fresh model metadata rather than retaining a
            # session pinned to a mouse that may have been replaced.
            self.backend.shutdown()
        try:
            self.status.setText("Connecting… approve the desktop prompt for mouse access.")
            self.backend.start()
        except ValueError as error:
            self.fail(error)

    def is_hardware(self):
        return self.storage.currentData() == "hardware"

    def set_hardware_busy(self, busy):
        self.hardware_busy = busy
        for widget in (self.storage, self.slots, self.read_button, self.restore_button,
                       self.apply_button, self.plate, self.reset_button, self.stop_button,
                       self.connect_button):
            widget.setEnabled(not busy)
        self.refresh_hardware_view()

    def storage_changed(self):
        self.profile["storage"] = self.storage.currentData()
        self.snapshot = None
        self.hardware_saved = None
        self.save_after_read = False
        self.cancel_learning()
        if self.backend.ready:
            self.backend.shutdown()
        self.update_storage_view()

    def update_storage_view(self):
        hardware = self.is_hardware()
        for widget in (self.slots, self.read_button, self.restore_button, self.memory_hint):
            widget.setVisible(hardware)
        self.learn_button.setEnabled(not hardware)
        self.apply_button.setText("Save 12 bindings to mouse" if hardware else "Apply bindings")
        self.status.setText("Mouse memory · read slots, edit your draft, then save to the mouse." if hardware else "Software mode · bindings need the background helper running.")
        self.refresh_hardware_view()

    def hardware_command(self, command):
        if not self.device_model["onboard"]:
            raise ValueError("Mouse memory is not enabled for this model. Use Software mode and Learn input.")
        if self.backend.ready:
            if self.backend.protocol < 2:
                raise ValueError("Update naga-macros to version 0.3.0 alongside the app.")
            self.backend.send(command)
        else:
            self.pending_onboard = command
            self.connect_mouse()

    def read_mouse(self):
        try:
            self.snapshot = None
            self.hardware_saved = None
            self.set_hardware_busy(True)
            self.status.setText("Reading onboard profiles… no settings are being changed.")
            self.hardware_command({"command": "onboard_read", "slot": self.slots.currentData()})
        except (ValueError, OSError) as error:
            self.set_hardware_busy(False)
            self.fail(error)

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore side bindings from backup", str(self.path.parent / "backups"), "Hardware backups (*.json)")
        if not path:
            return
        try:
            backup = json.loads(Path(path).read_text())
            self.set_hardware_busy(True)
            self.hardware_saved = None
            self.status.setText("Preparing backup restoration…")
            self.hardware_command({"command": "onboard_restore", "backup": backup})
        except (ValueError, OSError) as error:
            self.set_hardware_busy(False)
            self.fail(error)

    def connection_changed(self, connected):
        self.connect_button.setText("Reconnect / rescan" if connected else "Connect mouse")
        if connected:
            if self.backend.device is not None:
                self.select_device_model(self.backend.device["id"])
            if self.backend.protocol >= 3 and self.device_model["faceplate"]:
                self.detected_module = None
                self.plate_detection = "pending"
                self.plate_hint.setText("Detecting attached faceplate…")
                self.plate.setEnabled(False)
                self.backend.send({"command": "faceplate"})
                # A queued config was built before we knew the attached plate.
                self.pending_config = None
                self.applying = False
            else:
                if self.device_model["faceplate"]:
                    self.plate_hint.setText("This helper requires manual plate selection. Rebuild the engine for automatic detection.")
                else:
                    self.plate_detection = "manual"
                    self.plate_hint.setText("Experimental model · select the layout and use Learn input. Hardware behavior is unverified.")
            if self.pending_onboard is not None:
                command, self.pending_onboard = self.pending_onboard, None
                if self.backend.protocol < 2:
                    self.set_hardware_busy(False)
                    self.fail("Update naga-macros to version 0.3.0 alongside the app.")
                    return
                self.backend.send(command)
            elif self.is_hardware():
                self.read_mouse()
            elif self.pending_config is not None:
                self.backend.send({"command": "apply", "config": self.pending_config})
                self.pending_config = None
            else:
                self.backend.send({"command": "monitor"})
        else:
            self.detected_module = None
            self.plate_detection = "offline"
            self.plate_hint.setText("Connect mouse to detect the attached plate automatically." if self.device_model["faceplate"] else "Select the layout and use Learn input · experimental model.")
            self.applying = False
            self.pending_config = None
            self.pending_onboard = None
            if self.hardware_saved is None:
                self.snapshot = None
            self.set_hardware_busy(False)
            self.cancel_learning()
            if self.hardware_saved is not None:
                self.status.setText(f"Saved on mouse · slot {self.hardware_saved} active · helper stopped. You can quit NagaLibre.")
            elif not self.fault:
                self.status.setText("Helper disconnected · saved mouse settings remain active.")

    def select_device_model(self, device_id):
        model = DEVICE_MODELS[device_id]
        if model["id"] != self.device_model["id"]:
            self.commit_fields()
            self.model_drafts[self.device_model["id"]] = (self.profile, self.load_error)
            self.path = self.base_profile_path if device_id == "naga_v2_pro" else self.base_profile_path.parent / "devices" / device_id / self.base_profile_path.name
            if device_id in self.model_drafts:
                self.profile, self.load_error = self.model_drafts[device_id]
            else:
                self.load_error = None
                try:
                    self.profile = load_profile(self.path, device_id)
                except (ValueError, KeyError, TypeError, OSError) as error:
                    self.profile = new_profile(device_id)
                    self.load_error = str(error)
                    self.log(f"Saved profile could not be loaded: {error}. Saving is disabled to preserve it.")
            self.device_model = model
            self.pending_config = self.pending_onboard = None
            self.snapshot = self.hardware_saved = None
            self.save_after_read = False
            self.cancel_learning()
            self.detected_module = None
            self.plate_detection = "offline"
            self.selected = 0
            self.storage.blockSignals(True)
            self.storage.setCurrentIndex(self.storage.findData(self.profile.get("storage", "hardware") if model["onboard"] else "software"))
            self.storage.blockSignals(False)
            self.plate.blockSignals(True)
            self.plate.clear()
            for plate in model["plates"]:
                self.plate.addItem(f"{plate}-button layout", plate)
            self.plate.setCurrentIndex(self.plate.findData(self.profile["plate"]))
            self.plate.blockSignals(False)
            self.rebuild_grid()
            self.select_button(0, commit=False)
            self.update_storage_view()
        self.storage.model().item(self.storage.findData("hardware")).setEnabled(model["onboard"])
        self.device_label.setText(model["name"] + (" · experimental, hardware unverified" if not model["verified"] else ""))

    def commit_fields(self):
        if self.loading:
            return
        button = self.current()
        button["trigger"] = self.trigger.text().strip()
        button["mode"] = self.mode.currentData()
        if button["mode"] == "key":
            button["value"] = self.key_value.text().strip()
        elif button["mode"] == "shortcut":
            button["value"] = self.shortcut_value.text().strip()

    def current_snapshot(self):
        if self.snapshot is not None and self.snapshot["slot"] == self.slots.currentData() and self.profile["plate"] == "12":
            return self.snapshot
        return None

    def stored_text(self, index):
        snapshot = self.current_snapshot()
        if snapshot is None:
            return "unread"
        record = next((b for b in snapshot["buttons"] if b["button"] == index + 1), None)
        return stored_label(record) if record else "unknown"

    def tile_text(self, index):
        draft = binding_label(self.buttons()[index])
        if self.is_hardware():
            return f"{index + 1}\nStored: {self.stored_text(index)}\nDraft: {draft}"
        return f"{index + 1}\n{draft}"

    def refresh_hardware_view(self, *args):
        hardware = self.is_hardware()
        snapshot = self.current_snapshot()
        self.apply_button.setEnabled(not self.hardware_busy and (not hardware or (self.backend.ready and snapshot is not None)))
        self.reset_button.setEnabled(not self.hardware_busy and (not hardware or (self.backend.ready and snapshot is not None)))
        self.plate.setEnabled(not self.hardware_busy and self.plate_detection in ("offline", "unavailable", "manual") and len(self.device_model["plates"]) > 1)
        if self.plate_detection in ("pending", "unknown"):
            self.apply_button.setEnabled(False)
            self.reset_button.setEnabled(False)
        if hasattr(self, "stored_binding"):
            self.stored_binding.setVisible(hardware)
            if snapshot is None:
                self.stored_binding.setText("Mouse binding unavailable · read the selected slot successfully first. Fields below are your local draft.")
            else:
                active = "active" if snapshot["slot"] == snapshot["active"] else "inactive"
                driver = " · driver mode; firmware bindings may be bypassed" if snapshot.get("mode") == [3, 0] else ""
                self.stored_binding.setText(f"Stored in slot {snapshot['slot']} ({active}): {self.stored_text(self.selected)}{driver}")
        for i, tile in enumerate(getattr(self, "tiles", [])):
            tile.setText(self.tile_text(i))

    def rebuild_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.tiles = []
        count = len(self.buttons())
        columns = 3 if count in (6, 12) else 2
        for index, button in enumerate(self.buttons()):
            tile = QPushButton(self.tile_text(index))
            tile.setMinimumHeight(64)
            tile.setCheckable(True)
            tile.setChecked(index == self.selected)
            tile.clicked.connect(lambda checked=False, i=index: self.select_button(i))
            self.grid.addWidget(tile, index // columns, index % columns)
            self.tiles.append(tile)
        self.reset_button.setText("Reset 12 buttons → 1…9, 0, -, =" if count == 12 and self.device_model["verified"] else "Reset layout bindings")

    def select_button(self, index, commit=True):
        if commit:
            self.commit_fields()
            self.cancel_learning()
        self.selected = index
        self.loading = True
        button = self.current()
        self.button_title.setText(f"Button {index + 1}")
        self.trigger.setText(button["trigger"])
        self.mode.setCurrentIndex(self.mode.findData(button["mode"]))
        self.stack.setCurrentIndex(self.mode.currentIndex())
        self.key_value.setText(button["value"] if button["mode"] == "key" else "")
        self.shortcut_value.setText(button["value"] if button["mode"] == "shortcut" else "")
        self.recorder.blockSignals(True)
        self.recorder.clear()
        self.recorder.blockSignals(False)
        self.macro_summary.setText(f"{len(button['steps'])} steps. Executes once per button press.")
        self.loading = False
        for i, tile in enumerate(self.tiles):
            tile.setChecked(i == index)
            tile.setText(self.tile_text(i))

        self.refresh_hardware_view()

    def mode_changed(self):
        self.stack.setCurrentIndex(self.mode.currentIndex())

    def change_plate(self):
        self.commit_fields()
        self.cancel_learning()
        self.profile["plate"] = self.plate.currentData()
        self.selected = 0
        if self.backend.ready and not self.is_hardware():
            self.backend.send({"command": "monitor"})
        self.rebuild_grid()
        self.select_button(0, commit=False)
        self.status.setText("Plate selected manually · bindings are stopped. Learn inputs if needed, then Apply.")

    def detected_plate(self, message):
        self.commit_fields()
        self.cancel_learning()
        self.pending_config = None
        self.snapshot = None
        self.hardware_saved = None
        self.save_after_read = False
        self.applying = False
        self.detected_module = message.get("module_id")
        count = message.get("buttons")
        if count in (2, 6, 12):
            self.plate_detection = "auto"
            plate = str(count)
            changed = self.profile["plate"] != plate
            if changed:
                self.profile["plate"] = plate
                self.selected = 0
                self.plate.blockSignals(True)
                self.plate.setCurrentIndex(self.plate.findData(plate))
                self.plate.blockSignals(False)
                self.rebuild_grid()
                self.select_button(0, commit=False)
            self.plate_hint.setText(f"Detected {count}-button plate · updates automatically when swapped.")
            self.status.setText(f"Detected {count}-button plate · " + ("read slots before saving." if self.is_hardware() else "bindings stopped. Click Apply when ready."))
        elif self.detected_module is None:
            self.plate_detection = "unavailable"
            self.plate_hint.setText("Automatic detection unavailable · select the plate manually.")
            self.status.setText("Faceplate detection unavailable · bindings stopped. Select the plate manually before applying.")
            self.log(message.get("message", "Faceplate could not be read."))
        else:
            self.plate_detection = "unknown"
            self.snapshot = None
            self.plate_hint.setText("No faceplate attached." if self.detected_module == 0 else f"Unrecognized faceplate ID {self.detected_module}.")
            self.status.setText("Attach a supported faceplate to apply bindings.")
        if not self.is_hardware() and self.backend.ready:
            self.backend.send({"command": "monitor"})
        self.refresh_hardware_view()
        if self.is_hardware() and count == 12 and self.backend.ready and not self.hardware_busy:
            self.read_mouse()

    def learn_input(self):
        self.commit_fields()
        self.learn_pending = True
        self.learning = False
        self.status.setText(f"Preparing to learn button {self.selected + 1}…")
        if self.backend.ready:
            self.backend.send({"command": "monitor"})
        else:
            self.connect_mouse()

    def cancel_learning(self):
        self.learning = self.learn_pending = False
        if hasattr(self, "learn_timer"):
            self.learn_timer.stop()
        self.learn_button.setText("Learn input")

    def on_event(self, message):
        kind = message.get("type")
        if kind == "faceplate":
            self.detected_plate(message)
        elif kind == "onboard_snapshot":
            self.fault = False
            self.snapshot = message["snapshot"]
            snapshot = self.snapshot
            self.slots.clear()
            for slot in snapshot["slots"]:
                self.slots.addItem(f"Slot {slot}" + (" · active" if slot == snapshot["active"] else ""), slot)
            self.slots.setCurrentIndex(self.slots.findData(snapshot["slot"]))
            self.set_hardware_busy(False)
            records = ", ".join(f"{b['button']}:{b['category']:02x}/" + bytes(b['data']).hex() for b in snapshot['buttons'])
            self.log(f"Read slot {snapshot['slot']} · side records {records}")
            self.status.setText(f"Read slot {snapshot['slot']} · tiles show stored bindings and local drafts separately. Save writes all 12 draft bindings and activates this slot.")
            if self.save_after_read:
                self.save_after_read = False
                self.apply()
        elif kind == "onboard_prepared":
            try:
                path = write_backup(self.path, message["backup"], message["token"])
                self.log(f"Hardware backup saved: {path}")
                self.status.setText("Backup saved. Writing and verifying side bindings…")
                self.backend.send({"command": "onboard_commit", "token": message["token"]})
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.fault = True
                self.set_hardware_busy(False)
                self.fail(f"Backup failed; mouse was not changed: {error}")
                self.backend.shutdown()
        elif kind == "onboard_saved":
            self.fault = False
            self.snapshot = message["snapshot"]
            self.hardware_saved = self.snapshot["slot"]
            self.save_after_read = False
            self.set_hardware_busy(False)
            self.backend.shutdown()
        elif kind == "error":
            self.fault = True
            self.snapshot = None
            self.save_after_read = False
            self.set_hardware_busy(False)
            self.applying = False
            self.cancel_learning()
            self.fail(("Mouse read/save failed. Stored bindings are unavailable; displayed drafts are not active bindings.\n" if self.is_hardware() else "") + message["message"])
        elif kind == "state":
            state = message["state"]
            if state == "monitoring":
                self.fault = False
                self.applying = False
                if self.learn_pending:
                    self.learn_pending = False
                    self.learning = True
                    self.learn_button.setText("Press mouse button…")
                    self.status.setText(f"Press physical button {self.selected + 1} once. Remapping is paused.")
                    self.learn_timer.start(15000)
                else:
                    self.status.setText("Connected · original buttons active. Click Apply to use your bindings.")
            elif state == "running":
                self.fault = False
                self.applying = False
                self.status.setText(f"Active · {self.profile['plate']}-button profile · close to tray to keep it running.")
            elif state == "idle" and not self.applying and not self.fault:
                self.status.setText("Input stopped · original mouse buttons active.")
        elif kind == "input":
            code, value = message["key"], message["value"]
            self.last_input.setText(f"Last input: {display_key(code)} · {'pressed' if value else 'released'}")
            if self.learning and value == 1:
                if code in PROTECTED_INPUTS:
                    self.status.setText("Main mouse clicks are ignored during learning. Press a side button instead.")
                    return
                if any(i != self.selected and b["trigger"] == code for i, b in enumerate(self.buttons())):
                    self.status.setText(f"{code} is already assigned to another physical button. Press a different button.")
                    return
                self.current()["trigger"] = code
                self.trigger.setText(code)
                self.cancel_learning()
                self.select_button(self.selected)
                self.status.setText(f"Learned button {self.selected + 1}: {display_key(code)}. Save or Apply to keep it.")
            for i, button in enumerate(self.buttons()):
                if button["trigger"] == code:
                    self.tiles[i].setStyleSheet("background: #267d6b; color: white;" if value else "")

    def edit_macro(self):
        dialog = MacroDialog(self.current()["steps"], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.current()["steps"] = dialog.steps()
            self.macro_summary.setText(f"{len(self.current()['steps'])} steps. Executes once per button press.")

    def reset_selected(self):
        self.commit_fields()
        trigger = self.current()["trigger"]
        self.buttons()[self.selected] = default_button(self.selected, self.profile["plate"])
        if self.profile["plate"] != "12" and trigger not in PROTECTED_INPUTS:
            self.current()["trigger"] = trigger
        self.select_button(self.selected, commit=False)

    def persist(self):
        if self.load_error:
            raise ValueError(f"Saved profile is invalid and was preserved at {self.path}. Rename it before saving a new profile.")
        save_profile(self.path, self.profile)

    def save(self):
        try:
            self.commit_fields()
            self.persist()
            self.rebuild_grid()
            self.status.setText("Draft saved locally. Use the apply/save-to-mouse button to activate it.")
        except (ValueError, OSError) as error:
            self.fail(error)

    def checked_config(self):
        text = runtime_config(self.profile)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml") as config:
            config.write(text)
            config.flush()
            result = subprocess.run([str(backend_path()), "check", config.name], capture_output=True, text=True, timeout=3)
        if result.returncode:
            raise ValueError(result.stderr.strip())
        return text

    def apply(self):
        try:
            if self.plate_detection in ("pending", "unknown"):
                raise ValueError("Wait for a supported faceplate to be detected before applying bindings.")
            self.commit_fields()
            if self.is_hardware():
                buttons = hardware_buttons(self.profile)
                self.persist()
                self.rebuild_grid()
                self.hardware_saved = None
                self.fault = False
                if not self.backend.ready or self.snapshot is None or self.snapshot["slot"] != self.slots.currentData():
                    self.save_after_read = True
                    self.read_mouse()
                    return
                self.set_hardware_busy(True)
                self.status.setText("Checking current mouse state before backup…")
                self.hardware_command({"command": "onboard_prepare", "buttons": buttons})
                return
            config = self.checked_config()
            self.persist()
            self.rebuild_grid()
            self.cancel_learning()
            self.applying = True
            self.status.setText("Applying… release all mouse buttons.")
            if self.backend.ready:
                command = {"command": "apply", "config": config}
                if self.backend.protocol >= 3 and self.detected_module is not None:
                    command["module_id"] = self.detected_module
                self.backend.send(command)
            else:
                self.pending_config = config
                self.connect_mouse()
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            self.applying = False
            self.set_hardware_busy(False)
            self.fail(error)

    def stop_remapping(self):
        if self.hardware_busy:
            return
        if self.is_hardware():
            self.backend.shutdown()
            self.status.setText("Helper stopped · saved mouse settings remain active.")
            return
        self.pending_config = None
        self.cancel_learning()
        if self.backend.ready:
            self.backend.send({"command": "monitor"})
        self.status.setText("Remapping stopped · original mouse buttons active.")

    def reset_defaults(self):
        if not self.is_hardware():
            self.stop_remapping()
        self.commit_fields()
        reset_plate(self.profile, self.profile["plate"])
        self.rebuild_grid()
        self.select_button(self.selected, commit=False)
        self.apply()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit(self):
        self.quitting = True
        self.close()

    def closeEvent(self, event):
        if self.hardware_busy:
            self.status.setText("Finish the hardware operation before closing NagaLibre.")
            event.ignore()
            return
        self.commit_fields()
        if not self.load_error:
            try:
                self.persist()
            except OSError as error:
                self.log(f"Could not save profile: {error}")
        if not self.quitting and self.backend.ready and self.tray.isVisible():
            self.hide()
            event.ignore()
            return
        self.backend.shutdown()
        self.tray.hide()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="NagaLibre Qt desktop app")
    parser.add_argument("--screenshot", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("NagaLibre")
    app.setOrganizationName("NagaLibre")
    app.setWindowIcon(app_icon())
    lock_directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))
    lock_directory.mkdir(parents=True, exist_ok=True)
    instance_lock = QLockFile(str(lock_directory / "app.lock"))
    if not instance_lock.tryLock(0):
        QMessageBox.information(None, "NagaLibre", "NagaLibre is already running. Open it from the system tray.")
        return
    window = Window()
    signal.signal(signal.SIGINT, lambda *args: window.quit())
    signal.signal(signal.SIGTERM, lambda *args: window.quit())
    app.aboutToQuit.connect(window.backend.shutdown)
    window.show()
    if args.screenshot:
        def screenshot():
            window.grab().save(str(args.screenshot))
            window.quitting = True
            app.quit()
        QTimer.singleShot(400, screenshot)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
