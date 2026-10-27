"""Presentation helpers for the device workspace; no hardware/session ownership."""
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QTabBar, QVBoxLayout, QWidget,
)


# Palette. Surfaces step up in lightness; the Razer-adjacent green is reserved
# for selection, focus and the one primary action on each page.
BG = "#101214"
SIDEBAR = "#0b0d0e"
SURFACE = "#171a1d"
RAISED = "#1e2226"
INSET = "#0d0f11"
BORDER = "#262b30"
BORDER_STRONG = "#363c43"
TEXT = "#e7ebee"
MUTED = "#8a949d"
FAINT = "#5c656d"
ACCENT = "#44d62c"
ACCENT_TEXT = "#7be466"
ACCENT_SOFT = "rgba(68, 214, 44, 0.10)"
ACCENT_LINE = "rgba(68, 214, 44, 0.45)"
WARN = "#f2b544"
DANGER = "#ef6461"

ASSETS = Path(__file__).resolve().parent / "assets"

STYLE = """
QMainWindow, QDialog { background: @BG; color: @TEXT; }
QWidget { font-size: 13px; color: @TEXT; }
QWidget#workspacePage, QWidget#content { background: @BG; }
QLabel { background: transparent; }
QLabel[role="muted"] { color: @MUTED; }
QLabel[role="faint"] { color: @FAINT; font-size: 12px; }
QLabel[role="heading"] { font-size: 24px; font-weight: 600; }
QLabel[role="title"] { font-size: 22px; font-weight: 650; }
QLabel[role="subtitle"] { color: @MUTED; }
QLabel[role="cardTitle"] { font-size: 14px; font-weight: 600; }
QLabel[role="eyebrow"] { color: @FAINT; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel[role="brand"] { font-size: 18px; font-weight: 700; }
QLabel[role="pill"] { color: @ACCENT_TEXT; background: @ACCENT_SOFT; border: 1px solid @ACCENT_LINE;
    border-radius: 9px; padding: 1px 8px; font-size: 11px; font-weight: 700; }
QLabel[role="pill"][tone="hypershift"] { color: #c9a6ff; background: rgba(160, 110, 255, 0.12);
    border-color: rgba(160, 110, 255, 0.45); }
QLabel[role="pill"][tone="warn"] { color: #f6cb7a; background: rgba(242, 181, 68, 0.12);
    border-color: rgba(242, 181, 68, 0.45); }
QLabel[role="pill"][tone="idle"] { color: @MUTED; background: @RAISED; border-color: @BORDER_STRONG; }
QLabel[role="readout"] { color: @MUTED; background: @INSET; border: 1px solid @BORDER;
    border-radius: 8px; padding: 9px 11px; }

/* Shell */
QFrame#sidebar { background: @SIDEBAR; border-right: 1px solid @BORDER; }
QFrame#deviceCard { background: @SURFACE; border: 1px solid @BORDER; border-radius: 12px; }
QFrame#header { background: transparent; }
QFrame#footer { background: @SURFACE; border-top: 1px solid @BORDER; }
QFrame#card, QFrame#inspector, QFrame#plateCard { background: @SURFACE; border: 1px solid @BORDER; border-radius: 14px; }
QFrame#plate { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #15181b, stop:1 #0c0e10);
    border: 1px solid @BORDER; border-radius: 22px; }
QFrame#stackPanel { background: @INSET; border: 1px solid @BORDER; border-radius: 10px; }
QFrame#divider { background: @BORDER; max-height: 1px; min-height: 1px; border: 0; }

QGroupBox { background: @SURFACE; border: 1px solid @BORDER; border-radius: 14px;
    margin-top: 0; padding: 44px 18px 16px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: padding; subcontrol-position: top left; left: 20px; top: 16px;
    padding: 0; color: @TEXT; font-size: 14px; }

/* Buttons */
QPushButton { color: @TEXT; background: @RAISED; border: 1px solid @BORDER_STRONG;
    border-radius: 8px; padding: 8px 14px; }
QPushButton:hover { background: #252a2f; border-color: #4a525a; }
QPushButton:pressed { background: #1a1e21; }
QPushButton:checked { background: @ACCENT_SOFT; border-color: @ACCENT; color: @TEXT; }
QPushButton:disabled { color: @FAINT; background: #15181a; border-color: @BORDER; }
QPushButton:focus { border-color: @ACCENT_LINE; }
QPushButton[role="primary"] { background: @ACCENT; color: #0c1a08; border: 1px solid @ACCENT; font-weight: 700; padding: 8px 18px; }
QPushButton[role="primary"]:hover { background: #5fe549; border-color: #5fe549; }
QPushButton[role="primary"]:pressed { background: #39b824; }
QPushButton[role="primary"]:disabled { background: #1b2a18; color: #4f6a49; border-color: #24361f; }
QPushButton[role="ghost"] { background: transparent; border: 1px solid transparent; color: @MUTED; }
QPushButton[role="ghost"]:hover { background: @RAISED; color: @TEXT; border-color: @BORDER; }
QPushButton[role="ghost"]:disabled { background: transparent; border-color: transparent; color: @FAINT; }
QPushButton[role="link"] { background: transparent; border: 0; padding: 2px 0; color: @ACCENT_TEXT; text-align: left; }
QPushButton[role="link"]:hover { color: #a6f297; text-decoration: underline; }
QPushButton[role="danger"] { background: transparent; color: #f19b98; border: 1px solid rgba(239, 100, 97, 0.35); }
QPushButton[role="danger"]:hover { background: rgba(239, 100, 97, 0.12); border-color: @DANGER; color: #ffc2c0; }
QPushButton[role="danger"]:disabled { color: @FAINT; border-color: @BORDER; }
QPushButton[role="nav"] { text-align: left; padding: 9px 12px; border: 1px solid transparent; border-radius: 9px;
    background: transparent; color: @MUTED; font-weight: 500; }
QPushButton[role="nav"]:hover { background: #15191c; color: @TEXT; }
QPushButton[role="nav"]:checked { background: @ACCENT_SOFT; color: @TEXT; border-color: transparent; font-weight: 600; }
QPushButton[role="nav"]:disabled { color: #3f464c; background: transparent; }
QPushButton[role="segment"] { background: transparent; border: 0; border-radius: 7px; padding: 6px 14px; color: @MUTED; font-weight: 500; }
QPushButton[role="segment"]:hover { color: @TEXT; background: #1c2024; }
QPushButton[role="segment"]:checked { background: @BORDER_STRONG; color: @TEXT; font-weight: 600; }
QPushButton[role="segment"]:disabled { color: #3f464c; }
QPushButton[role="useRow"] { text-align: left; padding: 7px 10px; background: @INSET; border: 1px solid @BORDER;
    border-radius: 8px; color: @TEXT; }
QPushButton[role="useRow"]:hover { border-color: @ACCENT_LINE; background: #131719; }
QPushButton[role="useRow"]:disabled { color: @MUTED; background: @INSET; border-color: @BORDER; }
QFrame#segmented { background: @INSET; border: 1px solid @BORDER; border-radius: 9px; }

/* Inputs */
QComboBox, QLineEdit, QKeySequenceEdit, QSpinBox { color: @TEXT; background: @INSET;
    border: 1px solid @BORDER_STRONG; border-radius: 8px; padding: 7px 10px; min-height: 18px;
    selection-background-color: #2f5a27; }
QComboBox:hover, QLineEdit:hover, QSpinBox:hover { border-color: #4a525a; }
QComboBox:focus, QLineEdit:focus, QKeySequenceEdit:focus, QSpinBox:focus { border-color: @ACCENT; }
QComboBox { padding-right: 32px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right;
    width: 28px; border: 0; background: transparent; }
QComboBox::down-arrow { image: url("@ARROW"); width: 10px; height: 6px; }
QSpinBox { padding-right: 26px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 22px; border: 0; background: transparent; }
QSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-arrow { image: url("@UP_ARROW"); width: 10px; height: 6px; }
QSpinBox::down-arrow { image: url("@ARROW"); width: 10px; height: 6px; }
QComboBox:disabled, QLineEdit:disabled { color: @FAINT; border-color: @BORDER; background: #0f1113; }
QComboBox QAbstractItemView { color: @TEXT; background: @RAISED; border: 1px solid @BORDER_STRONG;
    padding: 4px; outline: 0; selection-background-color: #2a4a23; }
QLineEdit[readOnly="true"] { color: @MUTED; }

/* Data views */
QPlainTextEdit, QTableWidget, QListWidget, QTreeWidget, QTableView { color: #cdd3d8; background: @INSET;
    border: 1px solid @BORDER; border-radius: 10px; selection-background-color: #24401f;
    alternate-background-color: #121518; gridline-color: @BORDER; }
QPlainTextEdit { font-family: "JetBrains Mono", "Fira Code", "DejaVu Sans Mono", monospace; font-size: 12px; padding: 6px; }
QTreeWidget::item, QListWidget::item { padding: 6px 4px; border-radius: 6px; }
QTreeWidget::item:hover, QListWidget::item:hover { background: #161a1d; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #22381d; color: @TEXT; }
QHeaderView { background: transparent; }
QHeaderView::section { color: @MUTED; background: @SURFACE; border: 0; border-bottom: 1px solid @BORDER;
    padding: 7px 8px; font-size: 12px; font-weight: 600; }
QTableCornerButton::section { background: @SURFACE; border: 0; }

/* Tabs */
QTabWidget::pane { border: 0; background: transparent; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab { color: @MUTED; background: transparent; padding: 8px 2px; margin-right: 22px;
    border: 0; border-bottom: 2px solid transparent; font-weight: 500; }
QTabBar::tab:selected { color: @TEXT; border-bottom-color: @ACCENT; }
QTabBar::tab:hover:!selected { color: @TEXT; }

/* Scrolling and chrome */
QScrollArea, QStackedWidget { background: transparent; border: 0; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2c3237; border-radius: 3px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: #3c444b; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #2c3237; border-radius: 3px; min-width: 32px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QProgressBar { background: @INSET; border: 0; border-radius: 2px; }
QProgressBar::chunk { background: @ACCENT; border-radius: 2px; }
QToolTip { color: @TEXT; background: @RAISED; border: 1px solid @BORDER_STRONG; padding: 6px 8px; border-radius: 6px; }
QMenu { background: @RAISED; border: 1px solid @BORDER_STRONG; padding: 4px; border-radius: 8px; }
QMenu::item { padding: 6px 18px; border-radius: 5px; }
QMenu::item:selected { background: #2a4a23; }
QCheckBox::indicator, QListWidget::indicator { width: 15px; height: 15px; }
QMessageBox { background: @RAISED; }
"""
for _name, _value in sorted(dict(
        BG=BG, SIDEBAR=SIDEBAR, SURFACE=SURFACE, RAISED=RAISED, INSET=INSET, BORDER_STRONG=BORDER_STRONG,
        BORDER=BORDER, TEXT=TEXT, MUTED=MUTED, FAINT=FAINT, ACCENT_TEXT=ACCENT_TEXT, ACCENT_SOFT=ACCENT_SOFT,
        ACCENT_LINE=ACCENT_LINE, ACCENT=ACCENT, WARN=WARN, DANGER=DANGER,
        ARROW=(ASSETS / "chevron-down.svg").as_posix(),
        UP_ARROW=(ASSETS / "chevron-up.svg").as_posix()).items(), key=lambda item: -len(item[0])):
    STYLE = STYLE.replace("@" + _name, _value)


# Single-stroke 24px icons; currentColor is substituted per state.
ICONS = {
    "buttons": '<rect x="6" y="2.5" width="12" height="19" rx="6"/><path d="M12 2.5v6M6 9h12"/>'
               '<circle cx="9.5" cy="13.5" r=".6"/><circle cx="12" cy="13.5" r=".6"/><circle cx="14.5" cy="13.5" r=".6"/>'
               '<circle cx="9.5" cy="16" r=".6"/><circle cx="12" cy="16" r=".6"/><circle cx="14.5" cy="16" r=".6"/>',
    "scroll": '<rect x="8" y="3" width="8" height="18" rx="4"/><path d="M12 7v3M10 14l2 2 2-2"/>',
    "memory": '<rect x="4" y="6" width="16" height="12" rx="2"/><path d="M8 6V3.5M12 6V3.5M16 6V3.5M8 20.5V18M12 20.5V18M16 20.5V18"/>'
              '<rect x="8.5" y="9.5" width="7" height="5" rx="1"/>',
    "macros": '<path d="M4 6h10M4 12h7M4 18h10"/><path d="M16 10.5l4 2.5-4 2.5z"/>',
    "diagnostics": '<path d="M3 12h4l2.5-6 4 12 2.5-6H21"/>',
}


def svg_pixmap(name, color, size=18, ratio=2.0):
    data = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').format(
        c=color, body=ICONS[name])
    renderer = QSvgRenderer(QByteArray(data.encode()))
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, pixmap.width(), pixmap.height()))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def nav_icon(name):
    icon = QIcon()
    icon.addPixmap(svg_pixmap(name, MUTED), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(svg_pixmap(name, ACCENT_TEXT), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(svg_pixmap(name, "#3f464c"), QIcon.Mode.Disabled, QIcon.State.Off)
    return icon


def label(text, role=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if role:
        widget.setProperty("role", role)
    return widget


class ElidedLabel(QLabel):
    """Single-line label that elides instead of demanding its full width."""

    def __init__(self, text="", role=None):
        super().__init__(text)
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        painter.drawText(rect, int(self.alignment()), self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, rect.width()))


def divider():
    line = QFrame()
    line.setObjectName("divider")
    return line


def card(title, text):
    """A titled surface. Returns the frame and its body layout."""
    widget = QFrame()
    widget.setObjectName("card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(20, 18, 20, 20)
    layout.setSpacing(12)
    layout.addWidget(label(title, "cardTitle"))
    if text:
        layout.addWidget(label(text, "muted"))
    return widget, layout


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class StatusDot(QWidget):
    """Small connection indicator; tone is one of idle, live, busy, warn."""
    COLORS = {"idle": FAINT, "live": ACCENT, "busy": WARN, "warn": DANGER}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tone = "idle"
        self.setFixedSize(10, 10)

    def set_tone(self, tone):
        self.tone = tone
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.COLORS.get(self.tone, FAINT))
        if self.tone != "idle":
            halo = QColor(color)
            halo.setAlpha(60)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(0, 0, 10, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(2, 2, 6, 6)


class SegmentedControl(QFrame):
    """A segmented view of an existing QComboBox.

    The combo stays the source of truth (callers and tests keep using it); this
    widget mirrors its items, enabled flags, current index and enabled state.
    """

    def __init__(self, combo, labels=None, parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.combo = combo
        self.labels = labels or {}
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.segments = []
        for index in range(combo.count()):
            button = QPushButton(self.labels.get(combo.itemData(index), combo.itemText(index)))
            button.setProperty("role", "segment")
            button.setMinimumWidth(button.sizeHint().width())
            button.setCheckable(True)
            button.setToolTip(combo.itemText(index))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(button, index)
            row.addWidget(button)
            self.segments.append(button)
        self.group.idClicked.connect(self.combo.setCurrentIndex)
        combo.currentIndexChanged.connect(self.sync)
        combo.model().dataChanged.connect(self.sync)
        combo.installEventFilter(self)
        self.sync()

    def eventFilter(self, watched, event):
        if watched is self.combo and event.type() == QEvent.Type.EnabledChange:
            self.setEnabled(self.combo.isEnabled())
        return False

    def sync(self, *args):
        model = self.combo.model()
        for index, button in enumerate(self.segments):
            item = model.item(index) if hasattr(model, "item") else None
            button.setEnabled(item is None or item.isEnabled())
            button.setChecked(index == self.combo.currentIndex())
        self.setEnabled(self.combo.isEnabled())


class Workspace:
    """Persistent navigation, shared page header and independently scrolling task pages."""
    PAGES = (
        ("Buttons", "Buttons", "Assign actions to the side plate, wheel and DPI controls.", "buttons"),
        ("Onboard memory", "Onboard memory", "Read, activate and create profile slots, or recover from a backup.", "memory"),
        ("Scrolling", "Scrolling", "Pick the HyperScroll stages that the scroll-mode button cycles through.", "scroll"),
        ("Macros", "Macros", "Build key sequences and see where they are stored on your mouse.", "macros"),
        ("Diagnostics", "Diagnostics", "Session details and help for your device.", "diagnostics"),
    )
    NAV_ORDER = (0, 2, 1, 3, 4)

    def __init__(self, window):
        window.setStyleSheet(STYLE)
        root = QWidget()
        window.setCentralWidget(root)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(236)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(16, 20, 16, 18)
        nav.setSpacing(4)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        self.brand_icon = QLabel()
        brand_row.addWidget(self.brand_icon)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(label("NagaLibre", "brand"))
        brand.addWidget(label("Side-button studio", "faint"))
        brand_row.addLayout(brand, 1)
        nav.addLayout(brand_row)
        nav.addSpacing(18)

        # The app fills this card with the detected device and its connect action.
        self.device_card = QFrame()
        self.device_card.setObjectName("deviceCard")
        self.device_layout = QVBoxLayout(self.device_card)
        self.device_layout.setContentsMargins(14, 12, 14, 14)
        self.device_layout.setSpacing(8)
        nav.addWidget(self.device_card)
        nav.addSpacing(18)
        nav.addWidget(label("WORKSPACE", "eyebrow"))
        nav.addSpacing(4)

        self.group = QButtonGroup(window)
        self.pages = QStackedWidget()
        self.layouts = []
        self.buttons = []
        for index, (name, title, description, icon) in enumerate(self.PAGES):
            button = QPushButton(name)
            button.setProperty("role", "nav")
            button.setCheckable(True)
            button.setIcon(nav_icon(icon))
            button.setIconSize(QSize(18, 18))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(button, index)
            self.buttons.append(button)
            page = QWidget()
            page.setObjectName("workspacePage")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(28, 4, 22, 24)
            page_layout.setSpacing(16)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
            self.layouts.append(page_layout)
        for index in self.NAV_ORDER:
            nav.addWidget(self.buttons[index])
        nav.addStretch()
        nav.addWidget(label("Independent, open source,\nbuilt for Linux.", "faint"))
        row.addWidget(sidebar)

        content = QWidget()
        content.setObjectName("content")
        self.content = QVBoxLayout(content)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(0)
        row.addWidget(content, 1)

        header = QFrame()
        header.setObjectName("header")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(28, 20, 28, 12)
        header_row.setSpacing(16)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = label("", "title")
        self.subtitle = ElidedLabel("", "subtitle")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header_row.addLayout(titles, 1)
        self.header_tools = QWidget()
        self.header_tools_layout = QHBoxLayout(self.header_tools)
        self.header_tools_layout.setContentsMargins(0, 0, 0, 0)
        self.header_tools_layout.setSpacing(10)
        self.header_tools.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        header_row.addWidget(self.header_tools, 0, Qt.AlignmentFlag.AlignVCenter)
        self.content.addWidget(header)

        # Retained for callers that expect a device sub-navigation; the
        # sidebar now lists every page directly, so it never shows.
        self.device_tabs = QTabBar()
        self.device_tabs.hide()
        self.device_pages = (0, 2, 1)
        for title in ("Buttons", "Scrolling", "Onboard memory"):
            self.device_tabs.addTab(title)

        self.pages.currentChanged.connect(self.sync_navigation)
        self.group.idClicked.connect(self.show_page)
        self.buttons[0].setChecked(True)
        self.sync_navigation(0)

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        self.sync_navigation(index)

    def sync_navigation(self, index):
        self.buttons[index].setChecked(True)
        _, title, description, _ = self.PAGES[index]
        self.title.setText(title)
        self.subtitle.setText(description)
        self.device_tabs.setVisible(False)

    def set_navigation_enabled(self, enabled):
        for button in self.buttons:
            button.setEnabled(enabled)
        self.device_tabs.setEnabled(enabled)
