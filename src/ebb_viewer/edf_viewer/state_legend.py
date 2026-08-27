"""Compact swatch+letter legend rendered next to the trace state bar."""

from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import QSize, Qt

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
