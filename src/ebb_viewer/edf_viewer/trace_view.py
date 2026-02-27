from datetime import datetime, timedelta
from typing import Sequence

import numpy as np

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import Qt
import pyqtgraph as pg

from ebb_viewer.edf_viewer.masks import MaskSet
from ebb_viewer.edf_viewer.state_bar import StateBar
#from ebb_viewer.edf_viewer.state_legend import StateLegend

pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")

class TraceView(QtWidgets.QWidget):

    def __init__(self, 
                 data: np.ndarray, 
                 fs: int, 
                 start_time: datetime, 
                 ch_names: Sequence[str] = ("LFC", "RSC", "LSC", "EMG"), 
                 win_sec: float =10.0, 
                 parent=None):
        
        super().__init__(parent)

        # Save data and assert shape
        self.data = np.asarray(data)
        assert self.data.ndim == 2, "data must be 2D (channels, samples)"
        self.nch, self.n = self.data.shape

        self.fs = float(fs)
        self.start_time = start_time
        self.ch_names = list(ch_names)

        # Windowing
        self.win_sec = float(win_sec)
        self.win = max(1, int(self.fs * self.win_sec))
        self.start = 0

        # Zoom states
        self.y_zoom = np.ones(self.nch, dtype=float)
        self.base_y: list[tuple[float | None, float | None]] = [(None, None)] * self.nch


        self.plots: list[pg.PlotWidget] = []
        self.curves: list[pg.PlotDataItem] = []
        self.vlabels: list[QtWidgets.QLabel] = []
        self.vsliders: list[QtWidgets.QSlider] = []

        # Mask overlays
        self.mask_set: MaskSet = MaskSet()
        self._overlay_items: list[tuple[pg.PlotWidget, pg.LinearRegionItem]] = []

        # State bar + legend (both hidden until set_state_masks is called)
        self.state_bar    = StateBar(self)
        #self.state_legend = StateLegend(self)

        self._build_ui()
        self._set_window(0)
        self.reset_zooms()
        

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        grid = QtWidgets.QGridLayout()
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid, 1)

        # Row 0: state legend (col 0) + state bar (col 1).
        # Both hidden until set_state_masks is called; grid collapses row when hidden.
        #grid.addWidget(self.state_legend, 0, 0)
        grid.addWidget(self.state_bar, 0, 1)

        for i in range(self.nch):
            col_left = QtWidgets.QWidget()
            lv = QtWidgets.QVBoxLayout(col_left)
            lv.setContentsMargins(0, 0, 4, 0)

            lbl = QtWidgets.QLabel(f"{self.ch_names[i]}")
            #lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lv.addWidget(lbl)
            self.vlabels.append(lbl)


            sl = QtWidgets.QSlider(Qt.Orientation.Vertical)
            sl.setRange(0, 200)
            sl.setValue(100)
            sl.valueChanged.connect(
                lambda v, idx=i: self._on_zoom_slider(idx, v)
            )
            lv.addWidget(sl, 1)
            self.vsliders.append(sl)


            grid.addWidget(col_left, i + 1, 0)

            # plot
            pw = pg.PlotWidget(title=self.ch_names[i])
            pw.setMenuEnabled(False)
            pw.showGrid(x=True, y=True, alpha=0.15)
            pw.setLabel("left", "µV")
            pw.getAxis("left").setWidth(60)

            if i < self.nch - 1:
                pw.getAxis("bottom").setStyle(showValues=False)

            vb = pw.getPlotItem().getViewBox()
            try:
                vb.enableAutoRange(axis=pg.ViewBox.XAxis, enable=True)
                vb.enableAutoRange(axis=pg.ViewBox.YAxis, enable=False)
            except AttributeError:
                vb.disableAutoRange(axis=pg.ViewBox.YAxis)

            curve = pw.plot(pen=pg.mkPen((0, 0, 0, 180), width=1.2))


            self.plots.append(pw)
            self.curves.append(curve)
            grid.addWidget(pw, i + 1, 1)

        # link X across all channels and state bar
        for i in range(1, self.nch):
            self.plots[i].setXLink(self.plots[0])
        self.state_bar.link_x(self.plots[0])

        # bottom controls (nav)
        controls = self._build_controls_row()
        outer.addLayout(controls)



    def _build_controls_row(self) -> QtWidgets.QLayout:
        layout = QtWidgets.QGridLayout()

        # position + datetime labels
        self.pos_lbl = QtWidgets.QLabel("t = 0.00 s")
        self.dt_lbl = QtWidgets.QLabel(f"dt = {self.start_time}")

        info_box = QtWidgets.QWidget()
        vb = QtWidgets.QVBoxLayout(info_box)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(2)
        vb.addWidget(self.pos_lbl)
        vb.addWidget(self.dt_lbl)

        # horizontal slider
        self.slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, max(0, self.n - self.win))
        self.slider.setSingleStep(max(1, self.win // 2))
        self.slider.valueChanged.connect(self._on_slide)

        pair = QtWidgets.QWidget()
        hb = QtWidgets.QHBoxLayout(pair)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(4)
        hb.addWidget(info_box)
        hb.addWidget(self.slider)

        layout.addWidget(pair, 0, 0, 1, 4)

        # seconds / view
        self.xscale = QtWidgets.QDoubleSpinBox()
        self.xscale.setRange(0.5, 1200.0)
        self.xscale.setValue(self.win_sec)
        self.xscale.valueChanged.connect(self._on_seconds_per_view)

        spair = QtWidgets.QWidget()
        shb = QtWidgets.QHBoxLayout(spair)
        shb.setContentsMargins(0, 0, 0, 0)
        shb.setSpacing(4)
        shb.addWidget(QtWidgets.QLabel("seconds / view"))
        shb.addWidget(self.xscale)

        layout.addWidget(spair, 1, 0)

        # jump to
        self.jump = QtWidgets.QDoubleSpinBox()
        self.jump.setRange(0, self.n / self.fs)
        self.jump.setDecimals(3)
        self.jump.valueChanged.connect(self._on_jump)

        jpair = QtWidgets.QWidget()
        jhb = QtWidgets.QHBoxLayout(jpair)
        jhb.setContentsMargins(0, 0, 0, 0)
        jhb.setSpacing(4)
        jhb.addWidget(QtWidgets.QLabel("jump to (s):"))
        jhb.addWidget(self.jump)

        layout.addWidget(jpair, 1, 1)

        # reset zooms
        self.reset_btn = QtWidgets.QPushButton("Reset Y Zooms")
        self.reset_btn.clicked.connect(self.reset_zooms)
        layout.addWidget(self.reset_btn, 1, 3, alignment=Qt.AlignmentFlag.AlignRight)

        return layout

    # Navigation
    @staticmethod
    def _slider_to_zoom(v: int) -> float:
        # 0..200 → ~0.01x..100x (log-ish)
        return 10.0 ** ((v - 100) / 50.0)

    def _on_zoom_slider(self, idx: int, val: int):
        z = self._slider_to_zoom(val)
        self.y_zoom[idx] = z
        self.vlabels[idx].setText(f"{self.ch_names[idx]}\n{z:.2f}×")
        self._apply_y(idx)


    def _on_seconds_per_view(self, sec: float):
        center = self.start + self.win // 2
        self.win_sec = float(sec)
        self.win = max(1, int(self.fs * self.win_sec))
        self.start = int(np.clip(center - self.win // 2, 0, self.n - self.win))
        self.slider.setRange(0, max(0, self.n - self.win))
        self.slider.setValue(self.start)
        self._set_window(self.start)  

    def _on_jump(self, sec: float):
        self.start = int(np.clip(float(sec) * self.fs, 0, max(0, self.n - self.win)))
        # Triggers on_slide
        self.slider.setValue(self.start)

    def _on_slide(self, start: int):
        self.start = int(np.clip(start, 0, max(0, self.n - self.win)))
        self._set_window(self.start)


    def keyPressEvent(self, ev: QtGui.QKeyEvent):
        key = ev.key()
        if key == Qt.Key.Key_Right:
            # triggers _on_slide
            self.slider.setValue(self.start + max(1, self.win // 2))
            ev.accept()
            return
        if key == Qt.Key.Key_Left:
            # triggers _on_slide
            self.slider.setValue(self.start - max(1, self.win // 2))
            ev.accept()
            return
        super().keyPressEvent(ev)
    
    # Rendering

    def _set_window(self, start: int):
        self.start = start
        stop = min(self.start + self.win, self.n)
        t = np.arange(self.start, stop) / self.fs

        for ch in range(self.nch):
            y = self.data[ch, self.start:stop]
            self.curves[ch].setData(t, y)

        if t.size:
            self.plots[0].setXRange(t[0], t[-1], padding=0)

        seconds = self.start / self.fs
        self.pos_lbl.setText(f"t = {seconds:.2f} s")
        dt = self.start_time + timedelta(seconds=np.round(seconds, 0))
        self.dt_lbl.setText(f"dt = {dt}")
        # Blocks signal and will not trigger on_slide
        self.jump.blockSignals(True)
        self.jump.setMaximum(self.n / self.fs)
        self.jump.setValue(self.start / self.fs)
        self.jump.blockSignals(False)

        self._apply_all_y()
        if t.size:
            self._update_mask_overlays(t[0], t[-1])
            self.state_bar.update_window(t[0], t[-1])


    def set_masks(self, mask_set: MaskSet) -> None:
        self.mask_set = mask_set
        self._set_window(self.start)

    def set_state_masks(self, state_set: MaskSet) -> None:
        self.state_bar.set_state_masks(state_set, self.fs)
        #self.state_legend.rebuild(state_set)
        self._set_window(self.start)

    def refresh_overlays(self) -> None:
        stop = min(self.start + self.win, self.n)
        t = np.arange(self.start, stop) / self.fs
        if t.size:
            self._update_mask_overlays(t[0], t[-1])

    def _update_mask_overlays(self, t_start: float, t_stop: float) -> None:
        for pw, item in self._overlay_items:
            pw.removeItem(item)
        self._overlay_items.clear()

        s0 = int(t_start * self.fs)
        s1 = int(np.ceil(t_stop * self.fs))

        for mask in self.mask_set:
            if not mask.enabled:
                continue
            brush = pg.mkBrush(*mask.color)
            for span_start, span_end in mask.spans:
                if span_end <= s0 or span_start >= s1:
                    continue
                t_a = span_start / self.fs
                t_b = span_end / self.fs
                for pw in self.plots:
                    item = pg.LinearRegionItem(
                        values=(t_a, t_b),
                        movable=False,
                        brush=brush,
                        pen=pg.mkPen(None),
                    )
                    item.setZValue(-10)
                    pw.addItem(item)
                    self._overlay_items.append((pw, item))


    def reset_zooms(self):
        for ch in range(self.nch):
            self.y_zoom[ch] = 1.0
            self.vsliders[ch].blockSignals(True)
            self.vsliders[ch].setValue(100)
            self.vsliders[ch].blockSignals(False)
            self.vlabels[ch].setText(f"{self.ch_names[ch]}\n1.00×")

            self.base_y[ch] = self._fit_base_y(ch)
            self._apply_y(ch)


    def _fit_base_y(self, ch: int) -> tuple[float, float]:
        start, stop = self.start, min(self.start + self.win, self.n)
        seg = self.data[ch, start:stop]
        if seg.size == 0:
            return (-1.0, 1.0)
        y0, y1 = float(seg.min()), float(seg.max())
        if y0 == y1:
            y0, y1 = y0 - 1.0, y1 + 1.0
        pad = 0.05 * (y1 - y0)
        return (y0 - pad, y1 + pad)
        
    
    def _apply_y(self, ch: int, zero_centered: bool = False):
        y0, y1 = self.base_y[ch]
        if y0 is None:
            y0, y1 = self._fit_base_y(ch)
            self.base_y[ch] = (y0, y1)
        z = max(self.y_zoom[ch], 1e-6)
        center = 0 if zero_centered else 0.5 * (y0 + y1)
        half = 0.5 * (y1 - y0)
        half_eff = half / z
        self.plots[ch].getPlotItem().getViewBox().setYRange(
            center - half_eff, center + half_eff, padding=0
        )

    def _apply_all_y(self):
        for ch in range(self.nch):
            self._apply_y(ch)    
        
    