"""Presentation for the macro workspace: step previews, storage, status and usage.

Everything here renders local library data and the last macro readback. It
sends no mouse requests; reads and writes stay with MacroAssignmentPanel.
"""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from macro_links import summary
from model import display_key
from workspace import (ACCENT, ACCENT_TEXT, BORDER, BORDER_STRONG, FAINT, INSET, MUTED, RAISED,
                       TEXT, WARN, divider, label, repolish)

TONES = {"live": ACCENT, "warn": WARN, "idle": FAINT}
LAYERS = ("Normal", "Hypershift")


def step_chips(steps):
    chips = []
    for step in steps:
        kind, value = next(iter(step.items()))
        if kind == "wait_ms":
            chips.append((f"{value} ms", "wait"))
        elif kind == "chord":
            chips.append(("+".join(display_key(k) for k in value), "chord"))
        elif kind == "down":
            chips.append(("↓ " + display_key(value), "hold"))
        elif kind == "up":
            chips.append(("↑ " + display_key(value), "hold"))
        else:
            chips.append((display_key(value), "key"))
    return chips


class StepChips(QWidget):
    """A wrapping, read-only timeline of macro steps."""
    LIMIT = 40

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chips = []
        self.empty_text = "No steps"
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_steps(self, steps):
        chips = step_chips(steps or [])
        if len(chips) > self.LIMIT:
            chips = chips[:self.LIMIT] + [(f"+{len(chips) - self.LIMIT} more", "more")]
        self.chips = chips
        self.setToolTip(" › ".join(text for text, _ in chips))
        self.updateGeometry()
        self.update()

    def chip_font(self):
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def layout_chips(self, width):
        metrics = QFontMetrics(self.chip_font())
        x = y = 0
        height = metrics.height() + 8
        placed = []
        for text, kind in self.chips:
            chip = metrics.horizontalAdvance(text) + 16
            if x and x + chip > width:
                x, y = 0, y + height + 6
            placed.append((QRectF(x, y, min(chip, width), height), text, kind))
            x += chip + 14
        return placed, (y + height if placed else height)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.layout_chips(max(width, 1))[1]

    def sizeHint(self):
        return QSize(240, self.heightForWidth(240))

    def minimumSizeHint(self):
        return QSize(60, QFontMetrics(self.chip_font()).height() + 8)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self.chip_font())
        if not self.chips:
            painter.setPen(QColor(FAINT))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.empty_text)
            return
        placed, _ = self.layout_chips(self.width())
        metrics = QFontMetrics(self.chip_font())
        previous = None
        for rect, text, kind in placed:
            if previous is not None and previous.top() == rect.top():
                # A small chevron joins steps on the same row.
                middle = rect.center().y()
                x = previous.right() + 5
                painter.setPen(QPen(QColor(FAINT), 1.2))
                painter.drawLine(QPointF(x, middle - 3), QPointF(x + 3, middle))
                painter.drawLine(QPointF(x + 3, middle), QPointF(x, middle + 3))
            previous = rect
            fill, border, color, style = {
                "key": (QColor(RAISED), QColor(BORDER_STRONG), QColor(TEXT), Qt.PenStyle.SolidLine),
                "chord": (QColor(68, 214, 44, 26), QColor(68, 214, 44, 110), QColor(ACCENT_TEXT), Qt.PenStyle.SolidLine),
                "hold": (QColor(160, 110, 255, 28), QColor(160, 110, 255, 110), QColor("#c9a6ff"), Qt.PenStyle.SolidLine),
                "wait": (QColor(0, 0, 0, 0), QColor(BORDER_STRONG), QColor(MUTED), Qt.PenStyle.DashLine),
                "more": (QColor(0, 0, 0, 0), QColor(0, 0, 0, 0), QColor(FAINT), Qt.PenStyle.SolidLine),
            }[kind]
            painter.setPen(QPen(border, 1, style))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width() - 10)))


class CapacityMeter(QWidget):
    """Stored entry count against the reported maximum, with byte details."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.storage = None
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_storage(self, storage):
        self.storage = storage
        if storage:
            self.setToolTip(f"{storage['stored_count']} of {storage['max_macros']} macro entries · "
                            f"{storage['free_bytes']:,} bytes available · "
                            f"{storage['reclaimable_bytes']:,} reclaimable (compaction disabled)")
        else:
            self.setToolTip("Read your mouse to see macro storage.")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = QFont(self.font())
        small.setPixelSize(12)
        painter.setFont(small)
        metrics = QFontMetrics(small)
        storage = self.storage
        top = QRectF(0, 0, self.width(), metrics.height())
        painter.setPen(QColor(MUTED))
        if storage:
            left = f"{storage['stored_count']} of {storage['max_macros']} macro slots used"
            right = f"{storage['free_bytes']:,} bytes free"
        else:
            left, right = "Macro storage unread", ""
        painter.drawText(top, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, left)
        painter.setPen(QColor(FAINT))
        painter.drawText(top, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right)
        bar = QRectF(0, metrics.height() + 8, self.width(), 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(INSET))
        painter.drawRoundedRect(bar, 4, 4)
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(bar.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        if storage and storage["max_macros"]:
            fraction = min(1.0, storage["stored_count"] / storage["max_macros"])
            if fraction:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(WARN if fraction > .85 else ACCENT))
                painter.drawRoundedRect(QRectF(bar.left(), bar.top(), max(8, bar.width() * fraction), bar.height()), 4, 4)


class MacroStatusDelegate(QStyledItemDelegate):
    """Draws each library macro's mouse status beside its name."""

    def __init__(self, status_for, parent=None):
        super().__init__(parent)
        self.status_for = status_for

    def paint(self, painter, option, index):
        identity = index.data(Qt.ItemDataRole.UserRole)
        text, tone = summary(self.status_for(identity), compact=True) if identity else ("", "idle")
        if not text:
            super().paint(painter, option, index)
            return
        view = QStyleOptionViewItem(option)
        self.initStyleOption(view, index)
        name = view.text
        view.text = ""
        widget = option.widget
        style = widget.style() if widget else None
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, view, painter, widget)
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, view, widget).adjusted(2, 0, -6, 0)
        painter.save()
        small = QFont(option.font)
        small.setPixelSize(11)
        small_metrics = QFontMetrics(small)
        badge_width = min(small_metrics.horizontalAdvance(text) + 14, rect.width() // 2)
        badge = QRectF(rect.right() - badge_width, rect.top(), badge_width, rect.height())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TONES[tone]))
        painter.drawEllipse(QPointF(badge.left() + 4, badge.center().y()), 3, 3)
        painter.setFont(small)
        painter.setPen(QColor(MUTED if tone != "warn" else WARN))
        painter.drawText(badge.adjusted(12, 0, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         small_metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(badge.width() - 12)))
        painter.setFont(option.font)
        painter.setPen(QColor(TEXT))
        name_rect = QRectF(rect.left(), rect.top(), rect.width() - badge_width - 8, rect.height())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(option.font).elidedText(name, Qt.TextElideMode.ElideRight, int(name_rect.width())))
        painter.restore()

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        return QSize(hint.width(), max(hint.height(), 30))


def use_label(use):
    layer = LAYERS[use["layer"]]
    return f"Slot {use['slot']} · {layer} · {use['control']}"


class MacroUsagePanel(QFrame):
    """Where the selected library macro lives on the mouse."""
    readRequested = Signal()
    showRequested = Signal(int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(240)
        self.setMaximumWidth(330)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(label("On your mouse", "cardTitle"))
        self.badge = QLabel()
        self.badge.setProperty("role", "pill")
        badge_row = QHBoxLayout()
        badge_row.addWidget(self.badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)
        self.message = label("", "muted")
        layout.addWidget(self.message)
        self.read_button = QPushButton("Read mouse")
        self.read_button.clicked.connect(self.readRequested.emit)
        layout.addWidget(self.read_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.copies_title = label("STORED COPIES", "eyebrow")
        layout.addWidget(self.copies_title)
        self.copies = QVBoxLayout()
        self.copies.setSpacing(4)
        layout.addLayout(self.copies)
        self.uses_title = label("USED BY", "eyebrow")
        layout.addWidget(self.uses_title)
        self.uses = QVBoxLayout()
        self.uses.setSpacing(4)
        layout.addLayout(self.uses)
        layout.addStretch()
        layout.addWidget(divider())
        layout.addWidget(label("Library edits never change the mouse by themselves. Assign the macro "
                               "to a button again to upload the new version.", "faint"))
        self.set_state(None, None, readable=False, busy=False)

    def clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def set_state(self, entry, status, *, readable, busy, stale=False):
        self.clear(self.copies)
        self.clear(self.uses)
        read = status is not None
        self.read_button.setVisible(not read or stale)
        self.read_button.setEnabled(readable and not busy)
        if entry is None:
            text, tone = "Select a macro", "idle"
            message = "Choose a saved macro to see where it is stored."
        elif not read:
            text, tone = "Mouse unread", "idle"
            message = ("Read your mouse to see whether this macro is stored and which buttons use it."
                       if readable else "Connect a wired Naga V2 Pro with the 12-button plate in Mouse memory mode "
                                        "to see where this macro is stored.")
        else:
            text, tone = summary(status)
            if not status["copies"]:
                message = "Not stored on the mouse. Use Assign to mouse… to pick a button and upload it."
            elif status["differs"]:
                message = ("This macro changed after it was uploaded; the buttons below still play the old "
                           "version. Assign it again to upload the new version, then delete the old unused copy "
                           "under On mouse.")
            elif not status["uses"]:
                message = "A copy is stored but no inspected button plays it. You can delete it under On mouse."
            else:
                message = "Stored copies match this library version."
            if stale:
                message = "Last readback · reconnect to refresh. " + message
        self.badge.setText(text.upper())
        self.badge.setProperty("tone", {"warn": "warn", "live": "", "idle": "idle"}[tone])
        repolish(self.badge)
        self.message.setText(message)
        copies = status["copies"] if read else []
        uses = status["uses"] if read else []
        self.copies_title.setVisible(bool(copies))
        self.uses_title.setVisible(bool(uses))
        for copy in copies:
            state = "matches library" if copy["state"] == "current" else "older version"
            row = label(f"ID {copy['id']:04x} · {copy['size']:,} bytes · {state}", "muted")
            self.copies.addWidget(row)
        for use in uses:
            button = QPushButton(f"{use_label(use)}\n{use['playback']}")
            button.setProperty("role", "useRow")
            button.setEnabled(not use["primary"] and 1 <= use["button"] <= 16 and not busy)
            button.setToolTip("Primary clicks are read-only." if use["primary"] else "Show this stored assignment in Buttons.")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, u=use: self.showRequested.emit(u["slot"], u["layer"], u["button"]))
            self.uses.addWidget(button)
