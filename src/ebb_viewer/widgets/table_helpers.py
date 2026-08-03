"""Shared helpers for QTableWidget cell construction."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTableWidgetItem


def make_cell(
    text: str,
    bg: QColor | None = None,
    fg: QColor | None = None,
    tooltip: str | None = None,
) -> QTableWidgetItem:
    """Return a non-editable QTableWidgetItem with optional background/foreground/tooltip."""
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if bg is not None:
        item.setBackground(bg)
    if fg is not None:
        item.setForeground(fg)
    if tooltip:
        item.setToolTip(tooltip)
    return item
