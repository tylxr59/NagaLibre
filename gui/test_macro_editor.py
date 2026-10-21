"""Embedded controls must stay within their cells through editing and restyling."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QTableWidget
from macro_editor import MacroEditor
from workspace import STYLE

APP = QApplication.instance() or QApplication([])


class MacroEditorGeometryTests(unittest.TestCase):
    def tearDown(self):
        for widget in APP.topLevelWidgets():
            if isinstance(widget, MacroEditor):
                widget.close()
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def flush_layout(self):
        APP.processEvents()
        APP.processEvents()

    def assert_controls_fit(self, table):
        for row in range(table.rowCount()):
            control = table.cellWidget(row, 0)
            value_rect = table.visualItemRect(table.item(row, 1))
            self.assertLess(control.geometry().right(), value_rect.left())
            self.assertGreaterEqual(control.width(), control.minimumWidth())
            self.assertGreater(table.rowHeight(row), control.height())

    def test_header_only_style_measurement_cannot_cover_values(self):
        # Reproduce a platform returning only the Action header's width.
        with patch.object(QTableWidget, 'sizeHintForColumn', return_value=64):
            editor = MacroEditor([{'tap': 'KEY_B'}, {'chord': ['KEY_LEFTCTRL', 'KEY_C']}])
            editor.setStyleSheet(STYLE)
            editor.resize(650, 360)
            editor.show()
            self.flush_layout()
            self.assert_controls_fit(editor.table)
            editor.table.editItem(editor.table.item(0, 1))
            self.flush_layout()
            self.assert_controls_fit(editor.table)
            editor.table.setCurrentCell(1, 0)
            self.flush_layout()
            self.assert_controls_fit(editor.table)
            self.assertEqual(editor.table.item(0, 1).text(), 'KEY_B')

    def test_hidden_rows_and_font_changes_keep_controls_inside_cells(self):
        editor = MacroEditor([], add_blank=False)
        editor.setStyleSheet(STYLE)
        editor.add('tap', 'KEY_B')
        # A stale width while hidden must be corrected when the view appears.
        editor.table.horizontalHeader().resizeSection(0, 64)
        editor.resize(650, 360)
        editor.show()
        self.flush_layout()
        self.assert_controls_fit(editor.table)
        for size in (18, 22):
            editor.setStyleSheet(STYLE + f'QWidget {{ font-size: {size}px; }}')
            editor.add('wait_ms', '100')
            self.flush_layout()
            self.assert_controls_fit(editor.table)
