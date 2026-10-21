"""Presentation helpers for the device workspace; no hardware/session ownership."""
from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QStackedWidget, QTabBar, QVBoxLayout, QWidget,
)


STYLE = """
QMainWindow, QDialog { background: #222222; color: #eeeeee; }
QWidget { font-size: 13px; }
QWidget#workspacePage { background: #222222; }
QWidget#buttonGrid { background: #252525; }
QLabel, QGroupBox { color: #eeeeee; }
QLabel[role="muted"] { color: #aaaaaa; }
QLabel[role="heading"] { font-size: 25px; font-weight: 600; }
QLabel[role="eyebrow"] { color: #44d62c; font-size: 11px; font-weight: 700; }
QFrame#sidebar { background: #171717; border-right: 1px solid #3b3b3b; }
QFrame#context, QFrame#footer { background: #252525; border: 1px solid #3b3b3b; border-radius: 3px; }
QGroupBox { background: #252525; border: 1px solid #3b3b3b; border-radius: 3px;
    margin-top: 16px; padding: 18px 14px 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; }
QPushButton { color: #d9e2eb; background: #303030; border: 1px solid #505050;
    border-radius: 3px; padding: 8px 12px; }
BindingTile { padding: 10px; }
QPushButton:hover { background: #3a3a3a; border-color: #777777; }
QPushButton:pressed { background: #254323; }
QPushButton:checked { background: #294227; border-color: #44d62c; color: #eeeeee; }
QPushButton:disabled { color: #777777; background: #282828; border-color: #3b3b3b; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus { border: 1px solid #44d62c; }
QPushButton[role="nav"] { text-align: left; padding: 12px 16px; border: 1px solid transparent; background: transparent; }
QPushButton[role="nav"]:hover { background: #303030; }
QPushButton[role="nav"]:checked { background: #293b26; color: #44d62c; border-color: #385332; }
QPushButton[role="primary"] { background: #44d62c; color: #132010; font-weight: 700; }
QPushButton[role="primary"]:hover { background: #66e94f; }
QPushButton[role="primary"]:disabled { background: #30352e; color: #858b82; }
QComboBox, QLineEdit, QKeySequenceEdit, QSpinBox { color: #eeeeee; background: #191919;
    border: 1px solid #505050; border-radius: 5px; padding: 7px; min-height: 18px; }
QComboBox { padding-right: 32px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right;
    width: 28px; border: 0; background: transparent; }
QComboBox::down-arrow { image: url("__DROPDOWN_ARROW__"); width: 10px; height: 6px; }
QComboBox:disabled, QLineEdit:disabled { color: #777777; border-color: #3b3b3b; }
QComboBox QAbstractItemView { color: #eeeeee; background: #303030; selection-background-color: #35532d; }
QPlainTextEdit, QTableWidget, QListWidget, QTreeWidget { color: #cccccc; background: #191919;
    border: 1px solid #454545; border-radius: 5px; selection-background-color: #35532d; }
QTreeWidget::item { padding: 6px; }
QTreeWidget::item:selected { background: #35532d; color: #eeeeee; }
QTabWidget::pane { border: 0; background: #222222; }
QTabBar::tab { color: #aaaaaa; background: #252525; padding: 10px 18px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #44d62c; border-bottom-color: #44d62c; }
QTabBar::tab:hover { background: #303030; }
QHeaderView::section { color: #cccccc; background: #303030; border: 0; padding: 6px; }
QScrollArea, QStackedWidget { background: transparent; border: 0; }
QScrollBar:vertical { background: #222222; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #555555; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QToolTip { color: #eeeeee; background: #303030; border: 1px solid #777777; }
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
        ("Macros", "My Macros", "Create and edit sequences. Assign saved macros to buttons in Customize."),
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
            if index in (0, 3, 4):
                button.setText("Mouse" if index == 0 else name)
                nav.addWidget(button)
            else:
                button.hide()
            page = QWidget()
            page.setObjectName("workspacePage")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 8, 0)
            page_layout.setSpacing(14)
            if index not in (0, 2):
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
        self.device_tabs = QTabBar()
        self.device_tabs.setExpanding(False)
        self.device_tabs.setDrawBase(False)
        self.device_pages = (0, 2, 1)
        for title in ('Customize', 'Scrolling', 'Mouse memory'):
            self.device_tabs.addTab(title)
        self.content.addWidget(self.device_tabs)
        self.device_tabs.currentChanged.connect(lambda index: self.show_page(self.device_pages[index]))
        self.pages.currentChanged.connect(self.sync_navigation)
        self.group.idClicked.connect(self.show_page)
        self.buttons[0].setChecked(True)

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        self.sync_navigation(index)

    def sync_navigation(self, index):
        self.buttons[0 if index in self.device_pages else index].setChecked(True)
        self.device_tabs.setVisible(index in self.device_pages)
        if index in self.device_pages:
            self.device_tabs.blockSignals(True)
            self.device_tabs.setCurrentIndex(self.device_pages.index(index))
            self.device_tabs.blockSignals(False)

    def set_navigation_enabled(self, enabled):
        for button in self.buttons:
            button.setEnabled(enabled)
        self.device_tabs.setEnabled(enabled)
