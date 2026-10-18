from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

from PySide6.QtCore import Qt, QTimer, QLockFile, QStandardPaths
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QStackedWidget, QSystemTrayIcon, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView, QKeySequenceEdit,
)

from backend import Backend, backend_path
from model import (
    binding_label, config_path, default_button, display_key, key_code, load_profile,
    new_profile, reset_plate, runtime_config, save_profile, shortcut, PROTECTED_INPUTS,
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
        self.device_label = QLabel("Looking for a Razer Naga V2 Pro…")
        self.device_label.setWordWrap(True)
        connection.addWidget(self.device_label, 1)
        self.connect_button = QPushButton("Connect mouse")
        self.connect_button.clicked.connect(self.connect_mouse)
        connection.addWidget(self.connect_button)
        layout.addLayout(connection)
        self.status = QLabel("Offline · edit bindings, then connect to test.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("padding: 10px; background: #24312f; border-radius: 6px; color: #8ce3cb;")
        layout.addWidget(self.status)
        columns = QHBoxLayout()
        left = QGroupBox("Side buttons")
        left_layout = QVBoxLayout(left)
        self.plate = QComboBox()
        for p in ("12", "6", "2"):
            self.plate.addItem(f"{p}-button plate", p)
        self.plate.setCurrentIndex(self.plate.findData(self.profile["plate"]))
        self.plate.currentIndexChanged.connect(self.change_plate)
        left_layout.addWidget(self.plate)
        plate_hint = QLabel("Plate selection is manual. Use Learn input to check a different plate.")
        plate_hint.setWordWrap(True)
        left_layout.addWidget(plate_hint)
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
        editor = QGroupBox("Button binding")
        edit_layout = QVBoxLayout(editor)
        self.button_title = QLabel()
        self.button_title.setStyleSheet("font-size: 20px; font-weight: 600;")
        edit_layout.addWidget(self.button_title)
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
        default_page = QLabel("Use the key this button already sends. No remapping is applied.")
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
        save = QPushButton("Save profile")
        save.clicked.connect(self.save)
        actions.addWidget(save)
        self.apply_button = QPushButton("Apply bindings")
        self.apply_button.setStyleSheet("background: #2dc4a2; color: #10201e; font-weight: bold; padding: 10px 18px;")
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
            result = subprocess.run([str(backend_path()), "list", "--json"], capture_output=True, text=True, timeout=1)
            if result.returncode:
                raise ValueError(result.stderr.strip())
            devices = json.loads(result.stdout)
            self.device_label.setText("Razer Naga V2 Pro · " + ", ".join(d["path"].rsplit("/", 1)[-1] for d in devices) if devices else "No Naga V2 Pro connected")
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            self.device_label.setText(f"Input engine unavailable: {error}")

    def connect_mouse(self):
        try:
            self.status.setText("Connecting… approve the desktop prompt for mouse access.")
            self.backend.start()
        except ValueError as error:
            self.fail(error)

    def connection_changed(self, connected):
        self.connect_button.setText("Reconnect / rescan" if connected else "Connect mouse")
        if connected:
            if self.pending_config is not None:
                self.backend.send({"command": "apply", "config": self.pending_config})
                self.pending_config = None
            else:
                self.backend.send({"command": "monitor"})
        else:
            self.applying = False
            self.pending_config = None
            self.cancel_learning()
            self.status.setText("Disconnected · original mouse input is restored. See connection details below.")

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

    def rebuild_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.tiles = []
        count = len(self.buttons())
        columns = 3 if count in (6, 12) else 2
        for index, button in enumerate(self.buttons()):
            tile = QPushButton(f"{index + 1}\n{binding_label(button)}")
            tile.setMinimumHeight(64)
            tile.setCheckable(True)
            tile.setChecked(index == self.selected)
            tile.clicked.connect(lambda checked=False, i=index: self.select_button(i))
            self.grid.addWidget(tile, index // columns, index % columns)
            self.tiles.append(tile)
        self.reset_button.setText("Reset 12 buttons → 1…9, 0, -, =" if count == 12 else "Reset plate to defaults")

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
            tile.setText(f"{i + 1}\n{binding_label(self.buttons()[i])}")

    def mode_changed(self):
        self.stack.setCurrentIndex(self.mode.currentIndex())

    def change_plate(self):
        self.commit_fields()
        self.cancel_learning()
        self.profile["plate"] = self.plate.currentData()
        self.selected = 0
        if self.backend.ready:
            self.backend.send({"command": "monitor"})
        self.rebuild_grid()
        self.select_button(0, commit=False)
        self.status.setText("Plate selected manually · bindings are stopped. Learn inputs if needed, then Apply.")

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
        if kind == "error":
            self.fault = True
            self.applying = False
            self.cancel_learning()
            self.fail(message["message"])
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
            self.status.setText("Profile saved. Click Apply to activate changes.")
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
            self.commit_fields()
            config = self.checked_config()
            self.persist()
            self.rebuild_grid()
            self.cancel_learning()
            self.applying = True
            self.status.setText("Applying… release all mouse buttons.")
            if self.backend.ready:
                self.backend.send({"command": "apply", "config": config})
            else:
                self.pending_config = config
                self.connect_mouse()
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            self.applying = False
            self.fail(error)

    def stop_remapping(self):
        self.pending_config = None
        self.cancel_learning()
        if self.backend.ready:
            self.backend.send({"command": "monitor"})
        self.status.setText("Remapping stopped · original mouse buttons active.")

    def reset_defaults(self):
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
