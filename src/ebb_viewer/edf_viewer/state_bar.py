import numpy as np
import pyqtgraph as pg
from PyQt6 import QtWidgets

from ebb_viewer.edf_viewer.masks import MaskSet


class StateBar(QtWidgets.QWidget):
    """A thin horizontal strip pinned above the trace grid that renders
    sleep-state epochs (Wake / NREM / REM) as solid colored bands.

    The bar is hidden until ``set_state_masks`` is called, so the TraceView
    layout is unaffected when no CSV is loaded.
    """

    HEIGHT = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state_set: MaskSet = MaskSet()
        self._fs: float = 1.0
        self._items: list[pg.LinearRegionItem] = []

        self._pw = pg.PlotWidget()
        self._pw.setFixedHeight(self.HEIGHT)
        self._pw.setMenuEnabled(False)
        self._pw.hideButtons()
        self._pw.setMouseEnabled(x=False, y=False)

        for axis in ("left", "right", "top", "bottom"):
            self._pw.getPlotItem().hideAxis(axis)

        self._pw.setYRange(0, 1, padding=0)
        self._pw.setBackground("w")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._pw)

        self.setVisible(False)

    # ------------------------------------------------------------------

    def link_x(self, plot: pg.PlotWidget) -> None:
        """X-link this bar to *plot* so scrolling stays in sync."""
        self._pw.setXLink(plot)

    def set_state_masks(self, state_set: MaskSet, fs: float) -> None:
        self._state_set = state_set
        self._fs = fs
        self.setVisible(True)

    def update_window(self, t_start: float, t_stop: float) -> None:
        for item in self._items:
            self._pw.removeItem(item)
        self._items.clear()

        s0 = int(t_start * self._fs)
        s1 = int(np.ceil(t_stop * self._fs))

        for mask in self._state_set:
            if not mask.enabled:
                continue
            brush = pg.mkBrush(*mask.color)
            for span_start, span_end in mask.spans:
                if span_end <= s0 or span_start >= s1:
                    continue
                item = pg.LinearRegionItem(
                    values=(span_start / self._fs, span_end / self._fs),
                    movable=False,
                    brush=brush,
                    pen=pg.mkPen(None),
                )
                item.setZValue(1)
                self._pw.addItem(item)
                self._items.append(item)
