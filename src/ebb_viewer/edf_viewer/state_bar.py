import numpy as np
import pyqtgraph as pg
from PyQt6 import QtWidgets

from ebb_viewer.edf_viewer.masks import MaskSet


class StateBar(QtWidgets.QWidget):
    """A thin horizontal PlotWidget that renders sleep-state epochs.

    Structurally identical to the trace channel plots (same axis widths,
    same label area) so that ``setXLink`` gives pixel-perfect alignment
    with no sync_viewport machinery needed.

    Hidden until ``set_state_masks`` is called.
    """

    HEIGHT = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state_set: MaskSet = MaskSet()
        self._fs: float = 250.0
        self._overlay_items: list[pg.LinearRegionItem] = []

        self._pw = pg.PlotWidget()
        self._pw.setMenuEnabled(False)

        # Left axis: match trace plots exactly — same setWidth + setLabel so
        # total axis width (tick area + rotated label area) is identical.
        self._pw.setLabel("left", "µV")          # same label as traces
        ax_left = self._pw.getAxis("left")
        ax_left.setWidth(60)
        ax_left.setStyle(showValues=False, tickLength=0)
        ax_left.label.hide()                      # invisible but contributes width

        # Bottom axis: hide completely (no ticks, no values, no height)
        ax_bot = self._pw.getAxis("bottom")
        ax_bot.setStyle(showValues=False, tickLength=0)
        ax_bot.setHeight(0)

        vb = self._pw.getPlotItem().getViewBox()
        vb.setYRange(0, 1, padding=0)
        vb.setMouseEnabled(x=False, y=False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._pw)

        self.setFixedHeight(self.HEIGHT)
        self.setVisible(False)

    # ------------------------------------------------------------------

    def link_x(self, plot: pg.PlotWidget) -> None:
        self._pw.setXLink(plot)

    def sync_viewport(self, *_) -> None:
        """No-op — X alignment is handled by setXLink."""

    def set_state_masks(self, state_set: MaskSet, fs: float) -> None:
        self._state_set = state_set
        self._fs = fs
        self.setVisible(True)

    def update_window(self, t_start: float, t_stop: float) -> None:
        for item in self._overlay_items:
            self._pw.removeItem(item)
        self._overlay_items.clear()

        s0 = int(t_start * self._fs)
        s1 = int(np.ceil(t_stop * self._fs))

        for mask in self._state_set:
            if not mask.enabled:
                continue
            r, g, b, a = mask.color
            brush = pg.mkBrush(r, g, b, a)
            for span_start, span_end in mask.spans:
                if span_end <= s0 or span_start >= s1:
                    continue
                t_a = span_start / self._fs
                t_b = span_end / self._fs
                item = pg.LinearRegionItem(
                    values=(t_a, t_b),
                    movable=False,
                    brush=brush,
                    pen=pg.mkPen(None),
                )
                item.setZValue(-10)
                self._pw.addItem(item)
                self._overlay_items.append(item)
