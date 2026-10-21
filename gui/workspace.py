"""Presentation helpers for the device workspace; no hardware/session ownership."""
from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)


STYLE = """
QMainWindow, QDialog { background: #151a20; color: #e6edf3; }
QWidget { font-size: 13px; }
QWidget#workspacePage { background: #151a20; }
QWidget#buttonGrid { background: #1c232b; }
QLabel, QGroupBox { color: #e6edf3; }
QLabel[role="muted"] { color: #a0aebb; }
QLabel[role="heading"] { font-size: 25px; font-weight: 600; }
QLabel[role="eyebrow"] { color: #71d8bd; font-size: 11px; font-weight: 700; }
QFrame#sidebar { background: #101419; border-right: 1px solid #303943; }
QFrame#context, QFrame#footer { background: #1c232b; border: 1px solid #303943; border-radius: 8px; }
QGroupBox { background: #1c232b; border: 1px solid #303943; border-radius: 8px;
    margin-top: 16px; padding: 18px 14px 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; }
QPushButton { color: #d9e2eb; background: #28323d; border: 1px solid #3e4c5a;
    border-radius: 6px; padding: 8px 12px; }
BindingTile { padding: 10px; }
QPushButton:hover { background: #344452; border-color: #71899b; }
QPushButton:pressed { background: #1b5449; }
QPushButton:checked { background: #204b43; border-color: #64d6b7; color: #b9f5e4; }
QPushButton:disabled { color: #788590; background: #202830; border-color: #303943; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus { border: 1px solid #71d8bd; }
QPushButton[role="nav"] { text-align: left; padding: 12px 16px; border: 1px solid transparent; background: transparent; }
QPushButton[role="nav"]:hover { background: #202a32; }
QPushButton[role="nav"]:checked { background: #203c36; color: #94e8ce; border-color: #345c50; }
QPushButton[role="primary"] { background: #71d8bd; color: #10251f; font-weight: 700; }
QPushButton[role="primary"]:hover { background: #99ecd4; }
QPushButton[role="primary"]:disabled { background: #283830; color: #81938b; }
QComboBox, QLineEdit, QKeySequenceEdit, QSpinBox { color: #e6edf3; background: #12181e;
    border: 1px solid #43515e; border-radius: 5px; padding: 7px; min-height: 18px; }
QComboBox { padding-right: 32px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right;
    width: 28px; border: 0; background: transparent; }
QComboBox::down-arrow { image: url("__DROPDOWN_ARROW__"); width: 10px; height: 6px; }
QComboBox:disabled, QLineEdit:disabled { color: #788590; border-color: #303943; }
QComboBox QAbstractItemView { color: #e6edf3; background: #202a32; selection-background-color: #28594d; }
QPlainTextEdit, QTableWidget, QListWidget { color: #cbd6df; background: #12181e;
    border: 1px solid #36434f; border-radius: 5px; selection-background-color: #28594d; }
QHeaderView::section { color: #cbd6df; background: #28323d; border: 0; padding: 6px; }
QScrollArea, QStackedWidget { background: transparent; border: 0; }
QScrollBar:vertical { background: #151a20; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #465763; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QToolTip { color: #e6edf3; background: #28323d; border: 1px solid #71899b; }
""".replace("__DROPDOWN_ARROW__", (Path(__file__).resolve().parent / "assets" / "chevron-down.svg").as_posix())


def label(text, role=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if role:
        widget.setProperty("role", role)
    return widget


def card(title, text):
    from PySide6.QtWidgets import QGroupBox
    widget = QGroupBox(title)
    layout = QVBoxLayout(widget)
    layout.setSpacing(14)
    layout.addWidget(label(text, "muted"))
    return widget, layout


class Workspace:
    """Persistent navigation and independently scrolling task pages."""
    PAGES = (
        ("Customize", "Button assignments", "Assignments and local drafts for your mouse buttons."),
        ("Mouse memory", "Profiles on your mouse", "Read, activate and manage onboard slots, or recover a saved backup."),
        ("Scrolling", "Wheel settings", "Manage HyperScroll stages independently of button assignments."),
        ("Macros", "Macro sequences", "Create native sequences with playback controls and recoverable uploads."),
        ("Diagnostics", "Connection & support", "Inspect session details and find help for your device."),
    )

    def __init__(self, window):
        window.setStyleSheet(STYLE)
        root = QWidget()
        window.setCentralWidget(root)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(182)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(16, 24, 16, 20)
        nav.setSpacing(7)
        brand = label("NagaLibre", "heading")
        brand.setStyleSheet("font-size: 23px;")
        nav.addWidget(brand)
        nav.addWidget(label("MOUSE WORKSPACE", "eyebrow"))
        nav.addSpacing(30)
        self.group = QButtonGroup(window)
        self.pages = QStackedWidget()
        self.layouts = []
        self.buttons = []
        for index, (name, title, description) in enumerate(self.PAGES):
            button = QPushButton(name)
            button.setProperty("role", "nav")
            button.setCheckable(True)
            self.group.addButton(button, index)
            self.buttons.append(button)
            nav.addWidget(button)
            page = QWidget()
            page.setObjectName("workspacePage")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 8, 0)
            page_layout.setSpacing(14)
            page_layout.addWidget(label(title, "heading"))
            page_layout.addWidget(label(description, "muted"))
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
            self.layouts.append(page_layout)
        nav.addStretch()
        nav.addWidget(label("Independent. Open source.\nBuilt for Linux.", "muted"))
        row.addWidget(sidebar)
        content = QWidget()
        self.content = QVBoxLayout(content)
        self.content.setContentsMargins(20, 20, 20, 18)
        self.content.setSpacing(14)
        row.addWidget(content, 1)
        self.group.idClicked.connect(self.pages.setCurrentIndex)
        self.buttons[0].setChecked(True)

    def show_page(self, index):
        self.buttons[index].setChecked(True)
        self.pages.setCurrentIndex(index)
