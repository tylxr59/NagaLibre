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
    QPlainTextEdit, QPushButton, QStackedWidget, QSystemTrayIcon,
    QVBoxLayout, QWidget, QKeySequenceEdit, QFileDialog, QScrollArea, QFrame, QSizePolicy,
    QStyle, QStyleOptionButton,
)

from onboard import (hardware_buttons, hardware_controls, write_backup, write_creation_backup,
                     stored_label, FACTORY_CONTROL_LABELS, layer_edits, draft_from_record, write_layer_backup)
from backend import Backend, backend_path
from support import device_issue_url
from workspace import Workspace, card, label as text_label
from macro_editor import MacroEditor
from macro_library_view import MacroLibraryWidget
from macro_assignment import MacroAssignmentPanel
from haptic import WheelPanel
from model import (
    binding_label, config_path, default_button, display_key, load_profile,
    new_profile, reset_plate, runtime_config, save_profile, PROTECTED_INPUTS, DEVICE_MODELS, CONTROL_NAMES, default_control, keep_binding,
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
    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit macro")
        self.resize(570, 420)
        layout = QVBoxLayout(self)
        self.sequence_editor = MacroEditor(steps, self)
        self.table = self.sequence_editor.table
        layout.addWidget(self.sequence_editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add(self, kind="tap", value=""):
        self.sequence_editor.add(kind, value)

    def remove(self):
        self.sequence_editor.remove()

    def move(self, delta):
        self.sequence_editor.move(delta)

    def steps(self):
        return self.sequence_editor.steps()

    def accept_checked(self):
        try:
            self.steps()
        except ValueError as error:
            QMessageBox.warning(self, "Check macro", str(error))
            return
        self.accept()


class BindingTile(QPushButton):
    """Keep the physical grid visible; full stored/draft text stays in the tooltip."""
    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self.render_text()

    def render_text(self):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        contents = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self)
        width = max(0, contents.width())
        super().setText("\n".join(self.fontMetrics().elidedText(line, Qt.TextElideMode.ElideRight, width)
                                  for line in getattr(self, "full_text", "").splitlines()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render_text()


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
        self.active_editor = None
        self.editor_faceplate = None
        self.editor_reconnected = False
        self.hardware_busy = False
        self.hardware_saved = None
        self.snapshot = None
        self.paired_snapshot = None
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
        self.resize(1180, 860)
        self.setMinimumSize(920, 640)
        self.workspace = Workspace(self)
        layout = self.workspace.content
        customize, memory, scrolling, macros, diagnostics = self.workspace.layouts
        context = QFrame()
        context.setObjectName("context")
        context_layout = QVBoxLayout(context)
        context_layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(context)
        layout.insertWidget(1, self.workspace.device_tabs)
        self.workspace.pages.currentChanged.connect(lambda index: context.setVisible(index != 3))
        connection = QHBoxLayout()
        self.device_label = QLabel("Looking for a supported Razer mouse…")
        self.device_label.setWordWrap(True)
        connection.addWidget(self.device_label, 1)
        self.connect_button = QPushButton("Connect mouse")
        self.connect_button.clicked.connect(self.connect_mouse)
        connection.addWidget(self.connect_button)
        context_layout.addLayout(connection)
        support_row = QHBoxLayout()
        self.support_hint = QLabel()
        self.support_hint.setWordWrap(True)
        support_row.addWidget(self.support_hint, 1)
        self.support_button = QPushButton("Request device support…")
        self.support_button.setToolTip("Open a GitHub form with diagnostic instructions. Review and submit it yourself.")
        self.support_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(device_issue_url(self.support_devices))))
        support_row.addWidget(self.support_button)
        diagnostics.addLayout(support_row)
        self.status = QLabel("Offline · edit bindings, then connect to test.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("padding: 4px 0; color: #cccccc;")
        context_layout.addWidget(self.status)
        storage_row = QHBoxLayout()
        self.storage = QComboBox()
        self.storage.addItem("Mouse memory · no background app", "hardware")
        self.storage.addItem("Software · background helper", "software")
        self.storage.setCurrentIndex(max(0, self.storage.findData(self.profile.get("storage", "hardware"))))
        storage_row.addWidget(text_label("Draft destination", "muted"))
        storage_row.addWidget(self.storage, 1)
        self.slots = QComboBox()
        self.slots.addItem("Active mouse slot", None)
        storage_row.addWidget(self.slots)
        self.slots.setToolTip("The selected onboard slot. Read and manage slots in Mouse memory.")
        slot_card, slot_layout = card("Onboard slots", "Reading leaves your local draft unchanged. Activate a slot to use its existing assignments without saving your draft.")
        self.memory_slot_card = slot_card
        memory.addWidget(slot_card)
        slot_actions = QHBoxLayout()
        self.read_button = QPushButton("Read slots")
        self.read_button.clicked.connect(self.read_mouse)
        slot_actions.addWidget(self.read_button)
        self.activate_button = QPushButton("Activate slot")
        self.activate_button.setToolTip("Use this slot's stored bindings without saving your draft.")
        self.activate_button.clicked.connect(self.activate_slot)
        slot_actions.addWidget(self.activate_button)
        self.create_button = QPushButton("Create slot")
        self.create_button.clicked.connect(self.create_slot)
        self.create_button.setToolTip("Create an unused slot with factory bindings. The current slot stays active; save your draft separately.")
        slot_actions.addWidget(self.create_button)
        self.restore_button = QPushButton("Restore backup…")
        self.restore_button.clicked.connect(self.restore_backup)
        slot_layout.addLayout(slot_actions)
        recovery_card, recovery_layout = card("Backup & recovery", "Restore mouse settings from a previously saved backup. Saving bindings creates a durable backup before any settings are written.")
        recovery_layout.addWidget(self.restore_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.memory_recovery_card = recovery_card
        memory.addWidget(recovery_card)
        self.memory_mode_hint = text_label("Onboard slots are available in Mouse memory mode. Change Draft destination above to manage them.", "muted")
        memory.addWidget(self.memory_mode_hint)
        memory.addStretch()
        self.wheel_panel = WheelPanel(self.path, self, self.backend)
        self.wheel_panel.busyChanged.connect(self.wheel_busy_changed)
        self.wheel_panel.layout().itemAt(1).layout().removeWidget(self.wheel_panel.restore_button)
        self.wheel_panel.layout().itemAt(1).layout().addStretch()
        recovery_layout.addWidget(self.wheel_panel.restore_button, 0, Qt.AlignmentFlag.AlignLeft)
        scrolling.addWidget(self.wheel_panel, 1)
        self.macro_library_view = MacroLibraryWidget(self.base_profile_path.parent / "macros.json", self)
        macros.addWidget(self.macro_library_view, 1)
        context_layout.addLayout(storage_row)
        layout.addWidget(self.workspace.pages, 1)
        self.slot_summary = QLabel("Slot capacity: unread")
        self.slot_summary.setWordWrap(True)
        slot_layout.insertWidget(1, self.slot_summary)
        self.memory_hint = QLabel("Each tile shows the stored binding and local draft. Save applies the 12 side-button drafts and explicitly edited wheel controls. Keep stored binding preserves a wheel control. Choose Macro on a button to assign a saved sequence.")
        self.memory_hint.setWordWrap(True)
        self.memory_hint.setProperty("role", "muted")
        slot_layout.addWidget(self.memory_hint)
        columns = QHBoxLayout()
        left = QGroupBox("Mouse buttons")
        left_layout = QVBoxLayout(left)
        self.plate = QComboBox()
        self.plate.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for p in ("12", "6", "2"):
            self.plate.addItem(f"{p}-button plate", p)
        self.plate.setCurrentIndex(self.plate.findData(self.profile["plate"]))
        self.plate.currentIndexChanged.connect(self.change_plate)
        plate_controls = QHBoxLayout()
        plate_controls.addWidget(self.plate, 1)
        self.layer = QComboBox()
        self.layer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.layer.addItem("Normal layer", 0)
        self.layer.addItem("Hypershift · while held", 1)
        self.layer.currentIndexChanged.connect(self.change_layer)
        plate_controls.addWidget(self.layer, 1)
        left_layout.addLayout(plate_controls)
        self.use_stored_button = QPushButton("Use stored bindings as draft")
        self.use_stored_button.setToolTip("Copy both stored layers into your local draft. Unknown actions stay set to Keep stored binding.")
        self.use_stored_button.clicked.connect(self.use_stored_draft)
        slot_layout.addWidget(self.use_stored_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.plate_hint = QLabel("Connect mouse to detect the attached plate automatically.")
        self.plate_hint.setWordWrap(True)
        self.plate_hint.setProperty("role", "muted")
        left_layout.addWidget(self.plate_hint)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("buttonGrid")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 10, 12, 10)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.grid_scroll.setMinimumHeight(180)
        self.grid_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.grid_scroll.setWidget(self.grid_host)
        left_layout.addWidget(self.grid_scroll, 1)
        self.last_input = QLabel("Last press: —")
        self.last_input.setWordWrap(True)
        left_layout.addWidget(self.last_input)
        self.reset_button = QPushButton("Reset plate to defaults")
        self.reset_button.clicked.connect(self.reset_defaults)
        left_layout.addWidget(self.reset_button)
        columns.addWidget(left, 1)
        editor = QGroupBox("Button assignment")
        self.editor = editor
        editor.setMaximumWidth(360)
        edit_layout = QVBoxLayout(editor)
        self.button_title = QLabel()
        self.button_title.setStyleSheet("font-size: 20px; font-weight: 600;")
        edit_layout.addWidget(self.button_title)
        self.stored_binding = QLabel()
        self.stored_binding.setWordWrap(True)
        edit_layout.addWidget(self.stored_binding)
        form = QFormLayout()
        self.binding_form = form
        trigger_row = QHBoxLayout()
        self.trigger = QLineEdit()
        self.trigger.setReadOnly(True)
        self.trigger.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.trigger.setPlaceholderText("Learn this button’s input")
        self.trigger.setToolTip("The key emitted by this physical button, e.g. KEY_1 or BTN_SIDE.")
        trigger_row.addWidget(self.trigger)
        self.learn_button = QPushButton("Learn input")
        self.learn_button.clicked.connect(self.learn_input)
        trigger_row.addWidget(self.learn_button)
        form.addRow("Input", trigger_row)
        self.mode = QComboBox()
        self.mode.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for label, data in [("Default / pass through", "default"), ("Keyboard key", "key"), ("Shortcut", "shortcut"), ("Macro", "macro")]:
            self.mode.addItem(label, data)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        form.addRow("Action", self.mode)
        edit_layout.addLayout(form)
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        default_page = QLabel("Mouse memory: restore this position’s factory key. Software: pass the current input through.")
        self.default_page = default_page
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
        self.macro_assignment = MacroAssignmentPanel(self.path, self.macro_library_view, self, backend=self.backend)
        self.macro_assignment.manageRequested.connect(self.open_onboard_macros)
        self.macro_assignment.softwareAssigned.connect(self.use_library_macro)
        self.macro_assignment.busyChanged.connect(self.macro_busy_changed)
        macro_layout.addWidget(self.macro_assignment)
        memory.insertWidget(memory.count() - 1, self.macro_assignment.tools_widget)
        self.stack.addWidget(macro_page)
        self.mode.addItem("Factory default", "factory")
        factory_page = QLabel("Restore this control's default function. Click Save bindings to mouse to apply.")
        factory_page.setWordWrap(True)
        self.stack.addWidget(factory_page)
        for label, mode, text in (
            ("Keep stored binding", "keep", "Preserve the exact binding already stored on the mouse."),
            ("Disabled", "disabled", "Disable this control in the selected layer."),
            ("Hold for Hypershift", "hypershift", "Hold this normal-layer button to use Hypershift assignments; release it to return to normal."),
        ):
            self.mode.addItem(label, mode)
            page = QLabel(text)
            page.setWordWrap(True)
            self.stack.addWidget(page)
        edit_layout.addWidget(self.stack)
        edit_layout.addStretch()
        per_button_reset = QPushButton("Use default for this button")
        self.per_button_reset = per_button_reset
        per_button_reset.clicked.connect(self.reset_selected)
        edit_layout.addWidget(per_button_reset)
        columns.insertWidget(0, editor, 1)
        customize.addLayout(columns, 1)
        self.assignment_actions = QWidget()
        assignment_actions = QHBoxLayout(self.assignment_actions)
        assignment_actions.setContentsMargins(0, 0, 0, 0)
        self.draft_hint = text_label("Local draft · saving a draft does not activate it.", "muted")
        assignment_actions.addWidget(self.draft_hint, 1)
        actions = QHBoxLayout()
        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(14, 10, 14, 10)
        footer_layout.addLayout(actions)
        context_layout.removeWidget(self.status)
        footer_layout.addWidget(self.status)
        self.workspace.pages.currentChanged.connect(lambda index: self.status.setVisible(index != 3))
        self.stop_button = QPushButton("Stop remapping")
        self.stop_button.clicked.connect(self.stop_remapping)
        actions.addWidget(self.stop_button)
        actions.addStretch()
        save = QPushButton("Save draft")
        save.clicked.connect(self.save)
        assignment_actions.addWidget(save)
        self.apply_button = QPushButton("Apply bindings")
        self.apply_button.setProperty("role", "primary")
        self.apply_button.clicked.connect(self.apply)
        assignment_actions.addWidget(self.apply_button)
        actions.addWidget(self.assignment_actions, 1)
        layout.addWidget(footer)
        self.workspace.pages.currentChanged.connect(self.refresh_hardware_view)
        self.workspace.pages.currentChanged.connect(self.refresh_visible_assignments)
        stop_action = QAction("Stop remapping", self)
        stop_action.setShortcut("Escape")
        stop_action.triggered.connect(self.stop_remapping)
        self.addAction(stop_action)
        quit_action = QAction("Quit NagaLibre", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.quit)
        self.addAction(quit_action)
        footer_layout.addWidget(text_label("Esc  Stop remapping     ·     Ctrl+Q  Quit", "muted"))
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(150)
        self.logs.setMinimumHeight(180)
        self.logs.setPlaceholderText("Connection and validation details appear here.")
        diagnostics.addWidget(text_label("Session log", "eyebrow"))
        diagnostics.addWidget(self.logs, 1)
        diagnostics.addWidget(text_label("Logs describe connection, validation and save results. Include only relevant details when reporting an issue.", "muted"))
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

    def supports_layers(self):
        return (self.device_model["id"] == "naga_v2_pro"
                and self.backend.hypershift_transactions)

    def editing_layer(self):
        return int(self.layer.currentData() or 0) if (hasattr(self, "layer") and self.is_hardware()
                    and self.device_model["id"] == "naga_v2_pro" and self.profile["plate"] == "12") else 0

    def change_layer(self):
        self.commit_fields()
        self.cancel_learning()
        self.rebuild_grid()
        self.select_button(min(self.selected, len(self.buttons())-1), commit=False)

    def use_stored_draft(self):
        if self.paired_snapshot is None or self.current_snapshot() is None:
            return
        self.commit_fields()
        normal = self.paired_snapshot["normal"]
        old_normal = self.profile["plates"]["12"] + self.profile["controls"]
        copied = [draft_from_record(b) for b in normal["buttons"] + normal["controls"]]
        for before, after in zip(old_normal, copied):
            after["trigger"] = before["trigger"]
        self.profile["plates"]["12"] = copied[:12]
        self.profile["controls"] = copied[12:]
        bank = self.paired_snapshot["hypershift"]
        self.profile["hypershift"] = [draft_from_record(b, secondary=True) for b in bank["buttons"] + bank["controls"]]
        self.rebuild_grid()
        self.select_button(self.selected, commit=False)
        self.status.setText("Both stored layers copied into your local draft. Mouse settings are unchanged.")

    def buttons(self):
        if self.editing_layer() == 1:
            return self.profile["hypershift"]
        buttons = self.profile["plates"][self.profile["plate"]]
        if self.is_hardware() and self.profile["plate"] == "12" and self.device_model["id"] == "naga_v2_pro":
            if not self.profile.get("controls"):
                self.profile["controls"] = [default_control() for _ in CONTROL_NAMES]
            elif len(self.profile["controls"]) < len(CONTROL_NAMES):
                self.profile["controls"].extend(default_control() for _ in range(len(CONTROL_NAMES) - len(self.profile["controls"])))
            return buttons + self.profile["controls"]
        return buttons

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

        self.workspace.buttons[4].setText("Diagnostics •" if self.support_hint.text() else "Diagnostics")

    def connect_mouse(self):
        if self.backend.ready:
            # Reconnect obtains fresh model metadata rather than retaining a
            # session pinned to a mouse that may have been replaced.
            self.backend.shutdown()
        try:
            self.status.setText("Connecting… authenticate in the desktop prompt for mouse access.")
            self.backend.start()
        except ValueError as error:
            self.fail(error)

    def is_hardware(self):
        return self.storage.currentData() == "hardware"

    def set_hardware_busy(self, busy):
        self.hardware_busy = busy
        for widget in (self.storage, self.slots, self.read_button, self.activate_button, self.create_button, self.restore_button,
                       self.apply_button, self.plate, self.reset_button, self.stop_button,
                       self.connect_button, self.layer, self.use_stored_button, self.editor, self.grid_host):
            widget.setEnabled(not busy)
        self.refresh_hardware_view()

    def storage_changed(self):
        if hasattr(self, "editing_button"):
            self.commit_fields()
        self.profile["storage"] = self.storage.currentData()
        self.layer.blockSignals(True)
        self.layer.setCurrentIndex(0)
        self.layer.blockSignals(False)
        self.snapshot = None
        self.paired_snapshot = None
        self.hardware_saved = None
        self.save_after_read = False
        self.cancel_learning()
        if self.backend.ready:
            self.backend.shutdown()
        self.selected = 0
        self.rebuild_grid()
        self.select_button(0, commit=False)
        self.update_storage_view()

    def update_storage_view(self):
        hardware = self.is_hardware()
        self.memory_mode_hint.setVisible(not hardware)
        self.memory_slot_card.setVisible(hardware)
        self.memory_recovery_card.setVisible(hardware)
        for widget in (self.slots, self.slot_summary, self.read_button, self.activate_button, self.create_button, self.restore_button, self.memory_hint):
            widget.setVisible(hardware)
        self.learn_button.setEnabled(not hardware)
        self.binding_form.setRowVisible(0, not hardware)
        self.apply_button.setText("Save bindings to mouse" if hardware else "Apply bindings")
        self.status.setText("Mouse memory · read slots, edit your draft, then save to the mouse." if hardware else "Software mode · bindings need the background helper running.")
        self.refresh_hardware_view()

    def connected_hardware_command(self, command):
        command = dict(command)
        if self.supports_layers():
            if command["command"] == "onboard_read":
                command["command"] = "onboard_layers_read"
            elif command["command"] == "onboard_restore":
                command["command"] = "onboard_layers_restore_normal"
        elif command["command"].startswith("onboard_layers_"):
            raise ValueError("Hypershift saves and paired restores require the wired USB connection and an updated helper.")
        return command

    def hardware_command(self, command):
        if not self.device_model["onboard"]:
            raise ValueError("Mouse memory is not enabled for this model. Use Software mode and Learn input.")
        if self.backend.ready:
            if self.backend.protocol < 2:
                raise ValueError("Update naga-macros to version 0.3.0 alongside the app.")
            self.backend.send(self.connected_hardware_command(command))
        else:
            self.pending_onboard = command
            self.connect_mouse()

    def read_mouse(self):
        try:
            self.commit_fields()
            self.snapshot = None
            self.paired_snapshot = None
            self.hardware_saved = None
            self.set_hardware_busy(True)
            self.status.setText("Reading onboard profiles… no settings are being changed.")
            self.hardware_command({"command": "onboard_read", "slot": self.slots.currentData()})
        except (ValueError, OSError) as error:
            self.set_hardware_busy(False)
            self.fail(error)

    def activate_slot(self):
        if not self.activate_button.isEnabled():
            return
        try:
            self.save_after_read = False
            self.hardware_saved = None
            target = self.slots.currentData()
            self.set_hardware_busy(True)
            self.status.setText(f"Preparing to activate slot {target}… your draft will stay unchanged.")
            self.hardware_command({"command": "onboard_activate", "slot": target})
        except (ValueError, OSError) as error:
            self.set_hardware_busy(False)
            self.fail(error)

    def unused_slot(self):
        if self.snapshot is None or self.snapshot.get("slot_capacity") is None:
            return None
        return next((n for n in range(2, self.snapshot["slot_capacity"] + 1)
                     if n not in self.snapshot["slots"]), None)

    def create_slot(self):
        target = self.unused_slot()
        if not self.create_button.isEnabled() or target is None:
            return
        try:
            self.save_after_read = False
            self.hardware_saved = None
            self.set_hardware_busy(True)
            self.status.setText(f"Preparing slot {target}… backing up existing slots first.")
            self.hardware_command({"command": "onboard_create", "slot": target})
        except (ValueError, OSError) as error:
            self.set_hardware_busy(False)
            self.fail(error)

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore side bindings from backup", str(self.path.parent / "backups"), "Hardware backups (*.json)")
        if not path:
            return
        try:
            backup = json.loads(Path(path).read_text())
            if not isinstance(backup, dict):
                raise ValueError("Hardware backup must contain an object.")
            self.set_hardware_busy(True)
            self.hardware_saved = None
            self.status.setText("Preparing backup restoration…")
            if backup.get("kind") == "paired_mapping_backup":
                command = "onboard_layers_restore"
            elif "normal" in backup or "replies" in backup or "records" in backup or "kind" in backup:
                raise ValueError("This diagnostic export is not a restorable mapping backup.")
            else:
                command = "onboard_restore"
            self.hardware_command({"command": command, "backup": backup})
        except (ValueError, OSError) as error:
            self.set_hardware_busy(False)
            self.fail(error)

    def connection_changed(self, connected):
        if self.active_editor is not None:
            self.connect_button.setText("Reconnect / rescan" if connected else "Connect mouse")
            self.editor_reconnected = self.editor_reconnected or connected
            if not connected:
                self.snapshot = self.paired_snapshot = self.hardware_saved = None
            return
        self.connect_button.setText("Reconnect / rescan" if connected else "Connect mouse")
        if connected:
            if not self.supports_layers():
                self.layer.setCurrentIndex(0)
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
                try:
                    self.backend.send(self.connected_hardware_command(command))
                except ValueError as error:
                    self.set_hardware_busy(False)
                    self.fail(error)
            elif self.is_hardware():
                self.status.setText("Connected.")
                self.refresh_visible_assignments()
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
                self.paired_snapshot = None
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
            self.snapshot = self.hardware_saved = self.paired_snapshot = None
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
        button = self.editing_button if hasattr(self, "editing_button") else self.current()
        button["trigger"] = self.trigger.text().strip()
        if not (self.is_hardware() and self.mode.currentData() == "macro"):
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
        if self.editing_layer() == 1:
            if self.paired_snapshot is None:
                return "unread"
            snapshot = self.paired_snapshot["hypershift"]
        record = next((b for b in snapshot["buttons"] + snapshot.get("controls", []) if b["button"] == index + 1), None)
        return stored_label(record) if record else "unknown"

    def tile_text(self, index):
        draft = binding_label(self.buttons()[index])
        if self.is_hardware():
            name = CONTROL_NAMES[index - 12] if index >= 12 else str(index + 1)
            if index >= 12 and self.buttons()[index]["mode"] == "default":
                draft = "Keep stored binding"
            elif index >= 12 and self.buttons()[index]["mode"] == "factory":
                draft = FACTORY_CONTROL_LABELS[index - 12]
            return f"{name}\nStored: {self.stored_text(index)}\nDraft: {draft}"
        return f"{index + 1}\n{draft}"

    def refresh_visible_assignments(self, *args):
        if (self.workspace.pages.currentIndex() in (0, 1) and self.active_editor is None
                and self.backend.ready and self.is_hardware() and self.profile["plate"] == "12"
                and self.snapshot is None and not self.hardware_busy
                and self.plate_detection != "unknown"):
            self.read_mouse()

    def run_hardware_editor(self, editor_type, *, auto_read=True, **kwargs):
        if self.hardware_busy or self.active_editor is not None:
            return
        self.commit_fields()
        self.cancel_learning()
        if auto_read:
            self.pending_config = self.pending_onboard = None
            self.save_after_read = self.applying = False
            self.snapshot = self.paired_snapshot = self.hardware_saved = None
        dialog = editor_type(self.path, self, backend=self.backend, shared=True, **kwargs)
        self.active_editor = dialog
        self.editor_faceplate = None
        self.editor_reconnected = False
        self.refresh_hardware_view()
        try:
            # The read command stops software output in the engine before accessing hardware.
            if auto_read:
                dialog.read()
            dialog.exec()
        finally:
            dialog.detach_backend()
            accessed = auto_read or getattr(dialog, "hardware_accessed", False) or self.editor_faceplate is not None
            if accessed:
                self.pending_config = self.pending_onboard = None
                self.save_after_read = self.applying = False
                self.snapshot = self.paired_snapshot = self.hardware_saved = None
            if dialog.saved:
                # Successful firmware transactions end the engine session. Wait for EOF
                # before considering any fresh reads, even if the final event arrived first.
                self.backend.shutdown()
            if self.editor_faceplate is not None and self.backend.ready:
                # Apply the latest detection without issuing reads into the editor's session.
                self.detected_plate(self.editor_faceplate)
            self.active_editor = None
            self.editor_faceplate = None
            if not accessed:
                self.refresh_hardware_view()
            elif self.editor_reconnected and self.backend.ready and not dialog.saved:
                self.connection_changed(True)
            elif self.backend.ready and not dialog.saved and self.is_hardware() and self.profile["plate"] == "12":
                self.refresh_visible_assignments()
                self.refresh_hardware_view()
            else:
                if dialog.saved or not self.backend.ready:
                    self.connection_changed(False)
                self.refresh_hardware_view()
                if self.backend.ready and not dialog.saved:
                    self.status.setText("Editor closed · software remapping remains stopped. Click Apply when ready.")
            dialog.deleteLater()

    def open_wheel_settings(self):
        self.workspace.show_page(2)

    def wheel_busy_changed(self, busy):
        if busy:
            self.commit_fields()
            self.cancel_learning()
            self.active_editor = self.wheel_panel
            self.editor_faceplate = None
            self.pending_config = self.pending_onboard = None
            self.save_after_read = self.applying = False
            self.snapshot = self.paired_snapshot = self.hardware_saved = None
            self.set_hardware_busy(True)
            self.workspace.set_navigation_enabled(False)
        else:
            QTimer.singleShot(0, self.finish_wheel_operation)

    def finish_wheel_operation(self):
        panel = self.wheel_panel
        if panel.busy or self.active_editor is not panel:
            return
        if self.editor_faceplate is not None and self.backend.ready:
            self.detected_plate(self.editor_faceplate)
        self.editor_faceplate = None
        self.active_editor = None
        if panel.saved:
            self.backend.shutdown()
        self.set_hardware_busy(False)
        self.workspace.set_navigation_enabled(True)
        self.status.setText(panel.status.text())


    def open_onboard_macros(self):
        self.commit_fields()
        self.workspace.show_page(3)
        self.macro_library_view.search.setFocus()

    def use_library_macro(self, entry):
        self.current().update(mode="macro", steps=entry["steps"], value="")
        self.macro_summary.setText(f"{entry['name']} · {len(entry['steps'])} steps · once per press")

    def macro_busy_changed(self, busy):
        panel = self.macro_assignment
        if busy:
            self.commit_fields()
            self.cancel_learning()
            self.active_editor = panel
            self.editor_faceplate = None
            self.pending_config = self.pending_onboard = None
            self.save_after_read = self.applying = False
            self.snapshot = self.paired_snapshot = self.hardware_saved = None
            self.set_hardware_busy(True)
            self.workspace.set_navigation_enabled(False)
        else:
            QTimer.singleShot(0, self.finish_macro_operation)

    def finish_macro_operation(self):
        panel = self.macro_assignment
        if panel.busy or self.active_editor is not panel:
            return
        if self.editor_faceplate is not None and self.backend.ready:
            self.detected_plate(self.editor_faceplate)
        self.editor_faceplate = None
        self.active_editor = None
        self.set_hardware_busy(False)
        self.workspace.set_navigation_enabled(True)
        if panel.snapshot is not None:
            active = panel.snapshot["guard"]["active"]
            slot = active if panel.saved else panel.expected_slot
            mapping = next((m for m in panel.snapshot["mappings"] if m["normal"]["slot"] == slot),
                           next(m for m in panel.snapshot["mappings"] if m["normal"]["slot"] == active))
            if panel.last_result == "macro_saved":
                # Future ordinary saves must preserve this independently uploaded macro.
                self.current().update(mode="keep", value="", steps=[])
            self.on_event({"type": "onboard_layers_snapshot", "snapshot": mapping})
            if panel.saved:
                self.hardware_saved = active
                self.backend.shutdown()
        self.status.setText(panel.status.text())
        self.refresh_hardware_view()

    def refresh_hardware_view(self, *args):
        hardware = self.is_hardware()
        snapshot = self.current_snapshot()
        layer_visible = hardware and self.device_model["id"] == "naga_v2_pro" and self.profile["plate"] == "12"
        self.layer.setVisible(layer_visible)
        self.layer.model().item(1).setEnabled(not self.backend.ready or self.supports_layers())
        self.use_stored_button.setVisible(layer_visible)
        self.use_stored_button.setEnabled(not self.hardware_busy and snapshot is not None and self.paired_snapshot is not None)
        if self.supports_layers():
            self.memory_hint.setText("Normal bindings work normally; hold a button assigned to Hypershift to use the second layer. Save applies both drafts to the active slot. Keep stored binding preserves unknown actions. Use stored bindings as draft starts from the mouse's current assignments.")
        else:
            self.memory_hint.setText("Save applies the normal draft. Connect by USB to edit Hypershift; secondary drafts are retained. Choose Macro on a button to assign a saved sequence; edit sequences in Macros.")
        if self.snapshot is None:
            self.slot_summary.setText("Slot capacity: unread")
        elif self.snapshot.get("slot_capacity") is not None:
            self.slot_summary.setText(f"{len(self.snapshot['slots'])} of {self.snapshot['slot_capacity']} slots initialized.")
        else:
            self.slot_summary.setText(f"{len(self.snapshot['slots'])} slots initialized · total capacity unavailable from this read.")
        self.apply_button.setEnabled(self.active_editor is None and not self.hardware_busy and (not hardware or (self.backend.ready and snapshot is not None)))
        if self.supports_layers() and snapshot is not None:
            self.apply_button.setEnabled(self.apply_button.isEnabled() and self.paired_snapshot is not None
                                         and snapshot["slot"] == snapshot["active"] and snapshot.get("mode") == [0,0])
        selected = self.slots.currentData()
        self.activate_button.setEnabled(hardware and not self.hardware_busy and self.backend.ready
                                        and self.backend.slot_activation and self.snapshot is not None
                                        and selected in self.snapshot["slots"] and selected != self.snapshot["active"]
                                        and self.profile["plate"] == "12" and self.detected_module == 3)
        target = self.unused_slot()
        self.create_button.setToolTip("Create an unused slot with factory bindings; the current slot stays active. Create slots before configuring Hypershift, or restore the paired backup first." if self.supports_layers()
                                      else "Create an unused slot with factory bindings. The current slot stays active; save your draft separately.")
        self.create_button.setText(f"Create slot {target}" if target is not None else "Create slot")
        self.create_button.setEnabled(hardware and not self.hardware_busy and self.backend.ready
                                      and self.backend.slot_creation and target is not None
                                      and self.profile["plate"] == "12" and self.detected_module == 3)
        self.reset_button.setEnabled(not self.hardware_busy)
        self.plate.setEnabled(not self.hardware_busy and self.plate_detection in ("offline", "unavailable", "manual") and len(self.device_model["plates"]) > 1)
        if self.plate_detection in ("pending", "unknown"):
            self.apply_button.setEnabled(False)
            self.reset_button.setEnabled(False)
        if hasattr(self, "assignment_actions"):
            self.assignment_actions.setVisible(self.workspace.pages.currentIndex() == 0
                and not (hardware and self.mode.currentData() == "macro"))
        if hasattr(self, "macro_assignment") and not self.macro_assignment.busy:
            self.refresh_macro_context()
        if hasattr(self, "stored_binding"):
            self.stored_binding.setVisible(hardware)
            if snapshot is None:
                self.stored_binding.setText("Mouse binding unavailable · read the selected slot successfully first. Fields below are your local draft.")
            else:
                active = "active" if snapshot["slot"] == snapshot["active"] else "inactive"
                driver = " · driver mode; firmware bindings may be bypassed" if snapshot.get("mode") == [3, 0] else ""
                self.stored_binding.setText(f"Stored in slot {snapshot['slot']} ({active}): {self.stored_text(self.selected)}{driver}")
        for i, tile in enumerate(getattr(self, "tiles", [])):
            if i < len(self.buttons()):
                tile.setText(self.tile_text(i))

    def rebuild_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.tiles = []
        count = len(self.buttons())
        columns = 3 if count in (6, 12) or count > 12 else 2
        for column in range(6):
            self.grid.setColumnStretch(column, 1 if count > 12 or column < columns else 0)
        for index, button in enumerate(self.buttons()):
            tile = BindingTile()
            tile.setText(self.tile_text(index))
            tile.setMinimumHeight(76)
            tile.setMinimumWidth(80)
            tile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            tile.setCheckable(True)
            tile.setChecked(index == self.selected)
            tile.clicked.connect(lambda checked=False, i=index: self.select_button(i))
            if count > 12:
                # Keep the physical 3-column plate; give long control labels two wider columns.
                if index < 12:
                    self.grid.addWidget(tile, index // 3, (index % 3) * 2, 1, 2)
                else:
                    self.grid.addWidget(tile, 4 + (index - 12) // 2, ((index - 12) % 2) * 3, 1, 3)
            else:
                self.grid.addWidget(tile, index // columns, index % columns)
            self.tiles.append(tile)
        self.reset_button.setText("Clear Hypershift draft" if self.editing_layer() else "Restore defaults")
        self.reset_button.setToolTip("Restore this layout's draft defaults, including wheel and DPI button bindings. Save applies the draft to mouse memory.")

    def select_button(self, index, commit=True):
        if commit:
            self.commit_fields()
            self.cancel_learning()
        self.selected = index
        self.loading = True
        button = self.current()
        self.editing_button = button
        name = CONTROL_NAMES[index - 12] if index >= 12 else f"Button {index + 1}"
        self.button_title.setText(("Hypershift · " if self.editing_layer() else "Normal · ") + name if self.is_hardware() else name)
        self.mode.setItemText(0, "Keep stored binding" if index >= 12 else "Factory key" if self.is_hardware() else "Pass through")
        self.default_page.setText("Preserve this control's currently stored binding. Choose Factory default to restore its standard function." if index >= 12 else "Mouse memory: restore this position’s factory key. Software: pass the current input through.")
        secondary = self.editing_layer() == 1
        if secondary:
            self.mode.setItemText(0, "Normal default (unavailable)")
            self.default_page.setText("Choose Keep stored binding to preserve this secondary action.")
        self.mode.model().item(self.mode.findData("default")).setEnabled(not secondary)
        self.mode.model().item(self.mode.findData("factory")).setEnabled(index >= 12 and not secondary and self.is_hardware())
        self.mode.model().item(self.mode.findData("hypershift")).setEnabled(self.is_hardware() and not secondary
            and self.device_model["id"] == "naga_v2_pro" and self.profile["plate"] == "12" and (not self.backend.ready or self.supports_layers()))
        self.mode.model().item(self.mode.findData("disabled")).setEnabled(self.is_hardware())
        self.mode.model().item(self.mode.findData("keep")).setEnabled(secondary or not self.is_hardware() or not self.backend.ready or self.supports_layers())
        self.mode.model().item(self.mode.findData("macro")).setEnabled(not self.is_hardware() or (self.device_model["id"] == "naga_v2_pro" and self.profile["plate"] == "12"))
        for mode, hidden in (("default", secondary), ("factory", secondary or index < 12 or not self.is_hardware()),
                             ("hypershift", secondary or not self.is_hardware()), ("macro", self.is_hardware() and (self.device_model["id"] != "naga_v2_pro" or self.profile["plate"] != "12")),
                             ("keep", not secondary and (index >= 12 or not self.is_hardware())),
                             ("disabled", not self.is_hardware())):
            self.mode.view().setRowHidden(self.mode.findData(mode), hidden)
        self.per_button_reset.setText("Keep stored for this button" if secondary else "Use default for this button")
        self.trigger.setText(button["trigger"])
        selected_mode = button["mode"]
        if self.is_hardware() and selected_mode == "keep" and self.stored_text(index).startswith("Macro "):
            selected_mode = "macro"
        self.mode.setCurrentIndex(self.mode.findData(selected_mode))
        self.stack.setCurrentIndex(self.mode.currentIndex())
        self.key_value.setText(button["value"] if button["mode"] == "key" else "")
        self.shortcut_value.setText(button["value"] if button["mode"] == "shortcut" else "")
        self.recorder.blockSignals(True)
        self.recorder.clear()
        self.recorder.blockSignals(False)
        self.macro_summary.setText(f"{len(button['steps'])} steps. Executes once per button press.")
        self.macro_summary.setVisible(not self.is_hardware() and bool(button["steps"]))
        self.loading = False
        self.refresh_macro_context()
        for i, tile in enumerate(self.tiles):
            tile.setChecked(i == index)
            tile.setText(self.tile_text(i))

        self.refresh_hardware_view()

    def mode_changed(self):
        self.stack.setCurrentIndex(self.mode.currentIndex())
        if not self.loading and hasattr(self, "macro_assignment"):
            self.refresh_macro_context()
            self.refresh_hardware_view()

    def refresh_macro_context(self):
        snapshot = self.current_snapshot()
        allowed = not self.is_hardware() or (self.backend.ready and getattr(self.backend, "onboard_macros", False)
            and self.profile["plate"] == "12" and snapshot is not None and snapshot["slot"] == snapshot["active"])
        self.macro_assignment.set_context(self.selected + 1, self.editing_layer(), software=not self.is_hardware(),
            slot=self.slots.currentData(), allowed=allowed)


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
        self.paired_snapshot = None
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
            self.paired_snapshot = None
            self.plate_hint.setText("No faceplate attached." if self.detected_module == 0 else f"Unrecognized faceplate ID {self.detected_module}.")
            self.status.setText("Attach a supported faceplate to apply bindings.")
        if not self.is_hardware() and self.backend.ready and self.active_editor is None:
            self.backend.send({"command": "monitor"})
        self.refresh_hardware_view()
        if count == 12:
            self.refresh_visible_assignments()

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
        if self.active_editor is not None:
            if message.get("type") == "faceplate":
                self.editor_faceplate = message
            return
        kind = message.get("type")
        if kind == "faceplate":
            self.detected_plate(message)
        elif kind in ("onboard_layers_snapshot", "onboard_layers_activated", "onboard_snapshot", "onboard_created", "onboard_activated"):
            self.commit_fields()
            self.fault = False
            self.paired_snapshot = message["snapshot"] if kind in ("onboard_layers_snapshot", "onboard_layers_activated") else None
            self.snapshot = self.paired_snapshot["normal"] if self.paired_snapshot else message["snapshot"]
            snapshot = self.snapshot
            self.slots.clear()
            capacity = snapshot.get("slot_capacity")
            for slot in range(1, capacity + 1) if capacity is not None else snapshot["slots"]:
                initialized = slot in snapshot["slots"]
                suffix = " · uninitialized" if not initialized else (" · active" if slot == snapshot["active"] else "")
                self.slots.addItem(f"Slot {slot}{suffix}", slot)
                item = self.slots.model().item(self.slots.count() - 1)
                item.setEnabled(initialized)
                if not initialized:
                    item.setToolTip("This slot is unused. Create slot initializes the next unused slot on supported wired mice.")
            self.slots.setCurrentIndex(self.slots.findData(snapshot["slot"]))
            self.set_hardware_busy(False)
            records = ", ".join(f"{b['button']}:{b['category']:02x}/" + bytes(b['data']).hex() for b in snapshot['buttons'])
            self.log(f"Read slot {snapshot['slot']} · side records {records}")
            self.status.setText(f"Read slot {snapshot['slot']} · tiles show stored bindings and local drafts separately. Save applies your draft and activates this slot.")
            if kind == "onboard_created":
                self.status.setText(f"Created slot {snapshot['slot']} with factory bindings · slot {snapshot['active']} remains active. Save your draft to use the new slot.")
            elif kind == "onboard_activated":
                self.status.setText(f"Slot {snapshot['slot']} active · using stored bindings. Your draft is unchanged; you can quit NagaLibre.")
            if self.supports_layers() and kind in ("onboard_created", "onboard_activated"):
                self.read_mouse()
                return
            if kind == "onboard_layers_activated":
                self.status.setText(f"Slot {snapshot['slot']} active · both stored layers verified unchanged; local drafts are unchanged.")
            elif self.supports_layers():
                self.status.setText(f"Read both layers in slot {snapshot['slot']} · " +
                    ("local drafts are unchanged; save applies both drafts." if snapshot["slot"] == snapshot["active"]
                     else "activate this slot before saving layer drafts."))
            self.select_button(self.selected, commit=False)
            if self.save_after_read:
                self.save_after_read = False
                self.apply()
        elif kind in ("onboard_layers_prepared", "onboard_layers_activation_prepared", "onboard_prepared", "onboard_creation_prepared", "onboard_activation_prepared"):
            try:
                creating = kind == "onboard_creation_prepared"
                writer = write_layer_backup if kind in ("onboard_layers_prepared", "onboard_layers_activation_prepared") else (write_creation_backup if creating else write_backup)
                path = writer(self.path, message["backup"], message["token"])
                if creating and message.get("paired_backup") is not None:
                    paired_path = write_layer_backup(self.path, message["paired_backup"], message["token"])
                    self.log(f"Both-layer backup saved before slot creation: {paired_path}")
                if kind == "onboard_activation_prepared":
                    previous_path = write_backup(self.path, message["previous"], message["token"])
                    self.log(f"Previous active-slot backup saved: {previous_path}")
                self.log(f"Hardware backup saved: {path}")
                self.status.setText("Backups saved. Creating and verifying the new slot…" if creating else "Backup saved. Writing and verifying side bindings…")
                if kind in ("onboard_activation_prepared", "onboard_layers_activation_prepared"):
                    self.status.setText("Backups saved. Activating stored bindings…")
                elif kind == "onboard_layers_prepared":
                    self.status.setText("Both layers backed up. Writing and verifying paired bindings…")
                self.backend.send({"command": "onboard_commit", "token": message["token"]})
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.fault = True
                self.set_hardware_busy(False)
                self.fail(f"Backup failed; mouse was not changed: {error}")
                self.backend.shutdown()
        elif kind in ("onboard_layers_saved", "onboard_saved"):
            self.fault = False
            self.paired_snapshot = message["snapshot"] if kind == "onboard_layers_saved" else None
            self.snapshot = self.paired_snapshot["normal"] if self.paired_snapshot else message["snapshot"]
            self.hardware_saved = self.snapshot["slot"]
            self.save_after_read = False
            self.set_hardware_busy(False)
            self.backend.shutdown()
        elif kind == "error":
            self.fault = True
            self.snapshot = None
            self.paired_snapshot = None
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
        if self.editing_layer() == 1:
            self.profile["hypershift"][self.selected] = keep_binding()
        elif self.selected >= 12:
            self.profile["controls"][self.selected - 12] = default_control(factory=True)
        else:
            self.profile["plates"][self.profile["plate"]][self.selected] = default_button(self.selected, self.profile["plate"], self.device_model["id"])
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
        if self.is_hardware() and self.mode.currentData() == "macro":
            self.macro_assignment.save()
            return
        try:
            if self.plate_detection in ("pending", "unknown"):
                raise ValueError("Wait for a supported faceplate to be detected before applying bindings.")
            self.commit_fields()
            if self.is_hardware():
                paired = self.supports_layers()
                edits = layer_edits(self.profile) if paired else None
                buttons = None if paired else hardware_buttons(self.profile)
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
                if paired:
                    if self.paired_snapshot is None or self.snapshot["slot"] != self.snapshot["active"] or self.snapshot.get("mode") != [0,0]:
                        raise ValueError("Read both layers of the active slot in normal mode before saving. Activate another slot separately if needed.")
                    self.hardware_command({"command": "onboard_layers_prepare", "edits": edits})
                    return
                command = {"command": "onboard_prepare", "buttons": buttons}
                controls = hardware_controls(self.profile)
                if controls:
                    if not self.backend.wheel_controls:
                        raise ValueError("Rebuild the engine for wheel and scroll-mode bindings.")
                    command["controls"] = controls
                self.hardware_command(command)
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
        if self.active_editor is not None or self.hardware_busy:
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
        if self.editing_layer() == 1:
            self.profile["hypershift"] = [keep_binding() for _ in range(16)]
            self.rebuild_grid()
            self.select_button(self.selected, commit=False)
            self.status.setText("Hypershift draft cleared. Stored secondary bindings will be kept; the mouse is unchanged.")
            return
        reset_plate(self.profile, self.profile["plate"])
        if self.is_hardware() and self.profile["plate"] == "12" and self.device_model["id"] == "naga_v2_pro":
            self.profile["controls"] = [default_control(factory=True) for _ in CONTROL_NAMES]
        self.rebuild_grid()
        self.select_button(self.selected, commit=False)
        if self.is_hardware():
            self.status.setText("Defaults restored in your draft. Click Save bindings to mouse to apply.")
        else:
            self.apply()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit(self):
        self.quitting = True
        self.close()

    def closeEvent(self, event):
        if self.active_editor is not None or self.hardware_busy:
            self.status.setText("Finish the hardware operation before closing NagaLibre.")
            event.ignore()
            return
        if not self.macro_library_view.keep_changes():
            self.quitting = False
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
