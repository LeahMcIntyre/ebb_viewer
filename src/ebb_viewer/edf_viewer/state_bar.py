import numpy as np
from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt

from ebb_viewer.edf_viewer.masks import MaskSet


class StateBar(QtWidgets.QWidget):
    """A thin horizontal strip that renders sleep-state epochs using QPainter.

    Draws colored bands across the full widget width, using a pixel offset
    synced from the trace plot ViewBox so the bands align exactly with the
    trace data area.  Using QPainter directly avoids the pyqtgraph axis-margin
    mismatch that produced blank space at the left edge.

    Hidden until ``set_state_masks`` is called.
    """

    HEIGHT = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state_set: MaskSet = MaskSet()
        self._fs: float = 250.0
        self._t_start: float = 0.0
        self._t_stop: float = 10.0
        # Pixel x of ViewBox left/right edges within this widget's coordinate
        # system.  Set by TraceView via sync_viewport() after layout.
        self._vb_left: int = 0
        self._vb_right: int = 100

        self.setFixedHeight(self.HEIGHT)
        self.setVisible(False)


    def link_x(self, *_) -> None:
        """No-op — kept for API compatibility with TraceView._build_ui."""

    def sync_viewport(self, vb_left: int, vb_right: int) -> None:
        """Tell the bar where the trace ViewBox starts and ends in pixels.

        Called by TraceView on show and on resize so the painted bands stay
        aligned with the trace data area.
        """
        self._vb_left = vb_left
        self._vb_right = vb_right
        self.update()

    def set_state_masks(self, state_set: MaskSet, fs: float) -> None:
        self._state_set = state_set
        self._fs = fs
        self.setVisible(True)

    def update_window(self, t_start: float, t_stop: float) -> None:
        self._t_start = t_start
        self._t_stop = t_stop
        self.update()

    # ------------------------------------------------------------------

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        t_range = self._t_stop - self._t_start
        px_range = self._vb_right - self._vb_left
        if t_range <= 0 or px_range <= 0:
            return

        s0 = int(self._t_start * self._fs)
        s1 = int(np.ceil(self._t_stop * self._fs))

        painter = QtGui.QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)

        for mask in self._state_set:
            if not mask.enabled:
                continue
            r, g, b, a = mask.color
            painter.setBrush(QtGui.QColor(r, g, b, a))

            for span_start, span_end in mask.spans:
                if span_end <= s0 or span_start >= s1:
                    continue
                # Clamp to visible window before converting to pixels
                t_a = max(span_start / self._fs, self._t_start)
                t_b = min(span_end   / self._fs, self._t_stop)
                x1 = self._vb_left + int((t_a - self._t_start) / t_range * px_range)
                x2 = self._vb_left + int((t_b - self._t_start) / t_range * px_range)
                if x2 > x1:
                    painter.drawRect(x1, 0, x2 - x1, self.height())

        painter.end()
