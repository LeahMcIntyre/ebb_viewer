"""Multi-channel EEG trace renderer with mask overlays and state bar.

Per-channel y-zoom uses a "sticky center" model:
- ``base_y[ch]`` is the per-channel y-range fitted to the current window
  (``min/max + 5% pad``). It is recalculated only when ``reset_zooms`` runs.
- ``_ch_centers[ch]`` is the user-chosen vertical center for each channel.
  It is set when the user touches a per-channel zoom slider; before that,
  ``_apply_y`` falls back to the midpoint of ``base_y``.
- ``reset_zooms`` resets sliders to 1×, refits ``base_y``, and deliberately
  leaves ``_ch_centers`` intact so the user's chosen centers survive.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal

from ebb_viewer.edf_viewer.annotations import SwdAnnotation
from ebb_viewer.edf_viewer.masks import MaskSet
from ebb_viewer.edf_viewer.state_bar import StateBar
from ebb_viewer.edf_viewer.state_legend import StateLegend

pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")
pg.setConfigOptions(antialias=True)

# Shift+1..9 produces different key codes on most platforms (!, @, # …).
# Map them back to 0-based mask indices.
_STATE_KEYS = {
    Qt.Key.Key_W: "wake",
    Qt.Key.Key_N: "nrem",
    Qt.Key.Key_R: "rem",
}

_SHIFT_NUM_KEYS = {
    Qt.Key.Key_Exclam: 0,  # Shift+1
    Qt.Key.Key_At: 1,  # Shift+2
    Qt.Key.Key_NumberSign: 2,  # Shift+3
    Qt.Key.Key_Dollar: 3,  # Shift+4
    Qt.Key.Key_Percent: 4,  # Shift+5
    Qt.Key.Key_AsciiCircum: 5,  # Shift+6
    Qt.Key.Key_Ampersand: 6,  # Shift+7
    Qt.Key.Key_Asterisk: 7,  # Shift+8
    Qt.Key.Key_ParenLeft: 8,  # Shift+9
}


class TimeClickViewBox(pg.ViewBox):
    """ViewBox that emits a `timeDoubleClicked(t_sec)` signal on left-double-click."""

    timeDoubleClicked = pyqtSignal(float)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pt = self.mapSceneToView(event.scenePos())
            self.timeDoubleClicked.emit(float(pt.x()))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class TraceView(QtWidgets.QWidget):
    """Multi-channel EEG trace plot with horizontal pan, per-channel y-zoom,
    mask overlays, sleep-state bar, and keyboard mask navigation."""

    timeDoubleClicked = pyqtSignal(float)

    def __init__(
        self,
        data: np.ndarray,
        fs: int,
        start_time: datetime,
        ch_names: Sequence[str] = ("LFC", "RSC", "LSC", "EMG"),
        win_sec: float = 10.0,
        parent=None,
    ):

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

        # Zoom states. `base_y` is filled before the first render in __init__
        # via _fit_base_y; it stays in sync only with `reset_zooms` calls
        # (deliberate — user's zoom levels persist across pan/seek).
        self.y_zoom = np.ones(self.nch, dtype=float)
        self.base_y: list[tuple[float, float]] = [(-1.0, 1.0)] * self.nch
        self._ch_centers: list[float | None] = [None] * self.nch

        self.plots: list[pg.PlotWidget] = []
        self.curves: list[pg.PlotDataItem] = []
        self.vlabels: list[QtWidgets.QLabel] = []
        self.vsliders: list[QtWidgets.QSlider] = []

        # Mask overlays
        self.mask_set: MaskSet = MaskSet()
        self.state_set: MaskSet | None = None
        self._overlay_items: list[tuple[pg.PlotWidget, pg.LinearRegionItem]] = []

        # Annotation spans: editable SwdAnnotation objects drawn as draggable
        # regions. Items are tracked alongside their plot widget so teardown
        # doesn't depend on getViewBox() (which can return None after detachment).
        self._annotations: list[SwdAnnotation] = []
        self._annotation_items: list[tuple[pg.PlotWidget, pg.LinearRegionItem]] = []

        # State bar + legend (both hidden until set_state_masks is called)
        self.state_bar = StateBar(self)
        self.state_legend = StateLegend(self)

        self._build_ui()
        # Fit base_y from the initial window so _apply_y has a real range to
        # work with on the first render.
        for ch in range(self.nch):
            self.base_y[ch] = self._fit_base_y(ch)
        self._set_window(0)

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        grid = QtWidgets.QGridLayout()
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid, 1)

        # Row 0: legend + state bar in a single container spanning both columns.
        # This lets the legend extend into the axis dead-space to the left of
        # where the state bar starts drawing.  Hidden until set_state_masks is called.
        self._state_row = QtWidgets.QWidget(self)
        self._state_row.setVisible(False)
        _row_hb = QtWidgets.QHBoxLayout(self._state_row)
        _row_hb.setContentsMargins(0, 0, 0, 0)
        _row_hb.setSpacing(0)
        _row_hb.addWidget(self.state_legend)
        _row_hb.addWidget(self.state_bar, 1)
        grid.addWidget(self._state_row, 0, 0, 1, 2)

        for i in range(self.nch):
            col_left = QtWidgets.QWidget()
            lv = QtWidgets.QVBoxLayout(col_left)
            lv.setContentsMargins(0, 0, 4, 0)

            lbl = QtWidgets.QLabel(f"{self.ch_names[i]}")
            lv.addWidget(lbl)
            self.vlabels.append(lbl)

            sl = QtWidgets.QSlider(Qt.Orientation.Vertical)
            sl.setRange(0, 200)
            sl.setValue(100)
            sl.valueChanged.connect(lambda v, idx=i: self._on_zoom_slider(idx, v))
            lv.addWidget(sl, 1)
            self.vsliders.append(sl)

            grid.addWidget(col_left, i + 1, 0)

            # plot
            vb = TimeClickViewBox()
            vb.timeDoubleClicked.connect(self.timeDoubleClicked)
            plot_item = pg.PlotItem(viewBox=vb, title=self.ch_names[i])
            pw = pg.PlotWidget(plotItem=plot_item)
            pw.setMenuEnabled(False)
            pw.showGrid(x=True, y=True, alpha=0.15)
            pw.setLabel("left", "µV")
            pw.getAxis("left").setWidth(60)

            if i < self.nch - 1:
                pw.getAxis("bottom").setStyle(showValues=False)

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
        start, stop = self.start, min(self.start + self.win, self.n)
        seg = self.data[idx, start:stop]
        if seg.size > 0:
            self._ch_centers[idx] = float(np.median(seg))
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

    @property
    def center_sample(self):
        return int(np.clip(self.start + self.win // 2, 0, max(0, self.n - self.win // 2)))

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_state_bar_viewport)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_state_bar_viewport()

    def _sync_state_bar_viewport(self) -> None:
        """Map the first plot's ViewBox pixel bounds into StateBar local coords.

        Uses global screen coordinates as the bridge so the result is correct
        regardless of where in the container the state bar sits.
        """
        if not self.plots or not self._state_row.isVisible():
            return
        vb = self.plots[0].getPlotItem().getViewBox()
        rect = vb.sceneBoundingRect()
        pw = self.plots[0]
        left_g = pw.mapToGlobal(QPoint(int(rect.left()), 0))
        right_g = pw.mapToGlobal(QPoint(int(rect.right()), 0))
        self.state_bar.sync_viewport(
            self.state_bar.mapFromGlobal(left_g).x(),
            self.state_bar.mapFromGlobal(right_g).x(),
        )

    def jump_to_sample(self, sample: int) -> None:
        """Center the view on `sample`."""
        start = int(np.clip(sample - self.win // 2, 0, max(0, self.n - self.win)))
        self.slider.setValue(start)

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
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            idx = key - Qt.Key.Key_1
            masks = list(self.mask_set)
            if idx < len(masks):
                span = masks[idx].next_span_after(self.center_sample)
                if span is not None:
                    self.jump_to_sample(span[0])
            ev.accept()
            return
        if key in _SHIFT_NUM_KEYS:
            idx = _SHIFT_NUM_KEYS[key]
            masks = list(self.mask_set)
            if idx < len(masks):
                span = masks[idx].prev_span_before(self.center_sample)
                if span is not None:
                    self.jump_to_sample(span[0])
            ev.accept()
            return
        if key in _STATE_KEYS and self.state_set is not None:
            mask = self.state_set.get(_STATE_KEYS[key])
            if mask is not None:
                forward = not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                span = (
                    mask.next_span_after(self.center_sample)
                    if forward
                    else mask.prev_span_before(self.center_sample)
                )
                if span is not None:
                    self.jump_to_sample(span[0])
            ev.accept()
            return
        super().keyPressEvent(ev)

    # Rendering

    def _set_window(self, start: int):
        self.start = start
        stop = min(self.start + self.win, self.n)
        t = np.arange(self.start, stop) / self.fs

        for ch in range(self.nch):
            y = self.data[ch, self.start : stop]
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
        """Replace the active mask set and redraw overlays."""
        self.mask_set = mask_set
        self._set_window(self.start)

    def set_state_masks(self, state_set: MaskSet) -> None:
        """Set the sleep-state masks and reveal the state bar + legend row."""
        self.state_set = state_set
        self.state_bar.set_state_masks(state_set, self.fs)
        self.state_legend.rebuild(state_set)
        self._state_row.setVisible(True)
        self._set_window(self.start)

    def refresh_overlays(self) -> None:
        """Redraw mask overlays without replacing mask data.

        Use after toggling mask visibility or changing colors when the
        underlying ``mask_set`` has not been replaced.
        """
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
            # _ch_centers is intentionally NOT reset — the user's chosen
            # vertical centers persist across reset_zooms calls.
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
        z = max(self.y_zoom[ch], 1e-6)
        if zero_centered:
            center = 0.0
        elif self._ch_centers[ch] is not None:
            center = self._ch_centers[ch]
        else:
            center = 0.5 * (y0 + y1)
        half = 0.5 * (y1 - y0)
        half_eff = half / z
        self.plots[ch].getPlotItem().getViewBox().setYRange(
            center - half_eff, center + half_eff, padding=0
        )

    def _apply_all_y(self):
        for ch in range(self.nch):
            self._apply_y(ch)

    def jump_to_next_annotation(self) -> None:
        if not self._annotations:
            return
        t_current = self.center_sample / self.fs
        # One-sample epsilon so we skip the annotation at the current center
        # without skipping a legitimately-close neighbor.
        epsilon = 1.0 / self.fs
        for ann in sorted(self._annotations, key=lambda a: a.start_sec):
            if ann.start_sec > t_current + epsilon:
                self.jump_to_sample(int(ann.start_sec * self.fs))
                return

    def jump_to_prev_annotation(self) -> None:
        if not self._annotations:
            return
        t_current = self.center_sample / self.fs
        epsilon = 1.0 / self.fs
        for ann in sorted(self._annotations, key=lambda a: a.start_sec, reverse=True):
            if ann.start_sec < t_current - epsilon:
                self.jump_to_sample(int(ann.start_sec * self.fs))
                return

    def set_annotations(self, annotations: list[SwdAnnotation]) -> None:
        """Draw each annotation as an editable onset→offset span on every channel.

        The region on the top channel is draggable; dragging it mutates the
        :class:`SwdAnnotation` in place and mirrors the new bounds onto the
        regions drawn on the lower channels.
        """
        for pw, item in self._annotation_items:
            pw.removeItem(item)
        self._annotation_items.clear()

        self._annotations = annotations
        pen = pg.mkPen(color=(200, 0, 200, 200), width=1.5, style=Qt.PenStyle.DashLine)
        brush = pg.mkBrush(200, 0, 200, 45)
        for ann in annotations:
            bounds = (ann.start_sec, ann.end_sec)
            mirrors: list[pg.LinearRegionItem] = []
            for pw in self.plots[1:]:
                region = pg.LinearRegionItem(values=bounds, movable=False, brush=brush, pen=pen)
                region.setZValue(15)
                pw.addItem(region)
                self._annotation_items.append((pw, region))
                mirrors.append(region)

            master = pg.LinearRegionItem(values=bounds, movable=True, brush=brush, pen=pen)
            master.setZValue(15)
            pg.InfLineLabel(
                master.lines[0],
                text=ann.label,
                position=0.95,
                color=(180, 0, 180),
                fill=(255, 255, 255, 120),
            )
            master.sigRegionChanged.connect(
                lambda m=master, a=ann, ms=mirrors: self._on_annotation_region_changed(m, a, ms)
            )
            self.plots[0].addItem(master)
            self._annotation_items.append((self.plots[0], master))

    def _on_annotation_region_changed(
        self,
        region: pg.LinearRegionItem,
        ann: SwdAnnotation,
        mirrors: list[pg.LinearRegionItem],
    ) -> None:
        """Write the dragged region bounds back to the annotation and mirror them."""
        lo, hi = region.getRegion()
        if hi < lo:
            lo, hi = hi, lo
        ann.start_sec, ann.end_sec = lo, hi
        for m in mirrors:
            m.blockSignals(True)
            m.setRegion((lo, hi))
            m.blockSignals(False)

    def annotation_at_center(self) -> SwdAnnotation | None:
        """Return the annotation under the playhead, else the nearest one.

        Prefers a span containing the current center; otherwise returns the
        annotation whose span is closest in time. ``None`` if there are none.
        """
        if not self._annotations:
            return None
        t = self.center_sample / self.fs
        containing = [a for a in self._annotations if a.start_sec <= t <= a.end_sec]
        if containing:
            return min(containing, key=lambda a: t - a.start_sec)

        def _dist(a: SwdAnnotation) -> float:
            if t < a.start_sec:
                return a.start_sec - t
            if t > a.end_sec:
                return t - a.end_sec
            return 0.0

        return min(self._annotations, key=_dist)
