"""Compact swatch+letter legend rendered next to the trace state bar."""

from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal

from ebb_viewer.edf_viewer.masks import MaskSet


class StateLegend(QtWidgets.QWidget):
    """Compact legend drawn next to the state bar (grid col 0, row 0).

    Renders each state as a colored square swatch and an abbreviated label
    (first letter of the name) using QPainter.  Hidden until
    ``rebuild`` is called with a non-empty MaskSet.

    Also hosts a small checkable "R" pill that toggles the NREM
    reclassification; it is disabled until ``set_reclass_enabled(True)``.
    """

    reclass_toggled = pyqtSignal(bool)

    SWATCH = 10  # square size in px
    GAP = 3  # gap between swatch and text, and between entries
    PILL_W = 14
    PILL_GAP = 3  # space between the swatches and the pill

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[tuple[tuple[int, int, int, int], str]] = []
        self._reclass_checked = False
        self._reclass_enabled = False
        self.setVisible(False)

    def set_reclass_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self._reclass_enabled = enabled
        self.setToolTip(tooltip)
        self.updateGeometry()
        self.update()

    def set_reclass_checked(self, checked: bool) -> None:
        """Set the pill's state without emitting ``reclass_toggled``."""
        self._reclass_checked = checked
        self.update()

    def _content_width(self, fm: QtGui.QFontMetrics) -> int:
        entry_w = self.SWATCH + self.GAP + fm.horizontalAdvance("W")
        total_w = len(self._entries) * entry_w + (len(self._entries) - 1) * self.GAP
        return total_w + self.PILL_GAP + self.PILL_W

    def _pill_rect(self, fm: QtGui.QFontMetrics) -> QRect:
        x0 = max(0, (self.width() - self._content_width(fm)) // 2)
        entries_w = self._content_width(fm) - self.PILL_GAP - self.PILL_W
        return QRect(x0 + entries_w + self.PILL_GAP, 2, self.PILL_W, self.height() - 4)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        fm = QtGui.QFontMetrics(self.font())
        if (
            self._reclass_enabled
            and event.button() == Qt.MouseButton.LeftButton
            and self._pill_rect(fm).contains(event.position().toPoint())
        ):
            self._reclass_checked = not self._reclass_checked
            self.update()
            self.reclass_toggled.emit(self._reclass_checked)
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        if not self._entries:
            return QSize(0, 0)
        fm = QtGui.QFontMetrics(self.font())
        return QSize(self._content_width(fm), 20)

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

        # Centre the swatches + pill inside the widget
        x = max(0, (self.width() - self._content_width(fm)) // 2)
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

        self._paint_pill(painter, self._pill_rect(fm))
        painter.end()

    def _paint_pill(self, painter: QtGui.QPainter, rect: QRect) -> None:
        if self._reclass_checked:
            painter.setBrush(QtGui.QColor(217, 119, 6))
            text_color = QtGui.QColor(255, 255, 255)
        else:
            painter.setBrush(QtGui.QColor(220, 220, 220))
            text_color = QtGui.QColor(60, 60, 60)
        if not self._reclass_enabled:
            painter.setOpacity(0.4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "R")
