"""Compact swatch+letter legend rendered next to the trace state bar."""

from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import QSize, Qt, pyqtSignal

from ebb_viewer.edf_viewer.masks import MaskSet


class StateLegend(QtWidgets.QWidget):
    """Compact legend drawn next to the state bar (grid col 0, row 0).

    Renders each state as a colored square swatch and an abbreviated label
    (first letter of the name) using QPainter.  Hidden until
    ``rebuild`` is called with a non-empty MaskSet.
    """

    SWATCH = 10  # square size in px
    GAP = 3  # gap between swatch and text, and between entries

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[tuple[tuple[int, int, int, int], str]] = []
        self.setVisible(False)

    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        if not self._entries:
            return QSize(0, 0)
        fm = QtGui.QFontMetrics(self.font())
        entry_w = self.SWATCH + self.GAP + fm.horizontalAdvance("W")
        total_w = len(self._entries) * entry_w + (len(self._entries) - 1) * self.GAP
        return QSize(total_w, 20)

    def rebuild(self, state_set: MaskSet) -> None:
        """Populate entries from *state_set* and make the widget visible."""
        self._entries = [(m.color, m.name[0].upper()) for m in state_set]
        self.setVisible(bool(self._entries))
        self.updateGeometry()
        self.update()

    # ------------------------------------------------------------------

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        if not self._entries:
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        fm = painter.fontMetrics()
        entry_w = self.SWATCH + self.GAP + fm.horizontalAdvance("W")
        total_w = len(self._entries) * entry_w + (len(self._entries) - 1) * self.GAP

        # Centre the whole legend inside the widget
        x = max(0, (self.width() - total_w) // 2)
        y_top = max(0, (self.height() - self.SWATCH) // 2)

        for (r, g, b, _a), letter in self._entries:
            # Swatch — use fully opaque version of the state color
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(r, g, b, 255))
            painter.drawRoundedRect(x, y_top, self.SWATCH, self.SWATCH, 2, 2)

            # Letter label
            painter.setPen(QtGui.QColor(60, 60, 60))
            painter.drawText(
                x + self.SWATCH + self.GAP,
                y_top + fm.ascent(),
                letter,
            )

            x += entry_w + self.GAP

        painter.end()


class ReclassPill(QtWidgets.QWidget):
    """Small checkable "R" pill that toggles the NREM reclassification display.

    Sits right of the state bar. Disabled (dimmed, click ignored) until
    ``set_available(True)``; ``toggled`` fires only on user clicks.
    """

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = False
        self._available = False
        self.setFixedSize(18, 20)
        self.setVisible(False)

    def set_available(self, available: bool, tooltip: str = "") -> None:
        self._available = available
        self.setToolTip(tooltip)
        self.update()

    def set_checked(self, checked: bool) -> None:
        """Set the pill's state without emitting ``toggled``."""
        self._checked = checked
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._available and event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.update()
            self.toggled.emit(self._checked)
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if self._checked:
            painter.setBrush(QtGui.QColor(217, 119, 6))
            text_color = QtGui.QColor(255, 255, 255)
        else:
            painter.setBrush(QtGui.QColor(220, 220, 220))
            text_color = QtGui.QColor(60, 60, 60)
        if not self._available:
            painter.setOpacity(0.4)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = self.rect().adjusted(1, 2, -1, -2)
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "R")
        painter.end()
