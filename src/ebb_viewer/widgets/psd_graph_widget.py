# psd_matrix_page.py
from typing import Dict, List, Tuple
import numpy as np

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QToolBar, QToolButton, QSizePolicy, QStyle, QMenu
)
import pyqtgraph as pg
from fooof.utils import interpolate_spectrum

from ebb_viewer.widgets.range_dialog import FreqBoundsDialog

INVERSE_FILTER = np.array([2.485297985, 1.360646853, 1.145286775, 1.071699399, 1.038017048, 1.018656356, 1.007806318])
FILTER_RANGE = [0.5, 3.5] #Filter applied in filter range (inclusive)

class PSDGridPage(QWidget):



    def __init__(
        self,
        parent=None,
        *,
        store,                    # PSDStore-like: animals() -> List[str], states(animal) -> List[str], get(animal, state) -> Dict[ch,(f,y)]
        channel_names: List[str], # e.g., ["LFC","RSC","LSC"]
        states: List[str] = None  # e.g., ["wake","nrem","rem"]
    ):
        super().__init__(parent)
        self.store = store
        self.channel_names = list(channel_names)
        self.states = list(states or ["wake", "nrem", "rem"])

        # View preferences
        self.xrange: Tuple[float, float] = (0.5, 110)  # default window to show
        self.interp_range = [58,62]
        self.xlog = False
        self.ylog = True
        self.invfil = False
        self.interpolate = False


        # PyQtGraph global styling
        pg.setConfigOptions(antialias=True)
        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")

        # Root layout
        self.root = QVBoxLayout(self)
        self._build_tool_bar()
        self._build_grid()

        # Initial render
        if self.cmb_animal.count():
            self._render()

        print("New PSD Window")


    # ---------------- UI BUILDERS ----------------

    def _build_tool_bar(self):
        tb = QToolBar(self)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.setStyleSheet("""
            QToolBar { padding: 4px; spacing: 8px; }
            QToolButton { padding: 3px 8px; }
        """)

        """ # Left: export
        act_export = QAction("Export PNG", self)
        act_export.setShortcut(QKeySequence("Ctrl+E"))
        act_export.triggered.connect(self._export_png)
        tb.addAction(act_export)"""

        # Log-X toggle
        act_logx = _make_toggle(self, "Log-X", checked=self.xlog, slot=self._on_logx_toggled)
        tb.addAction(act_logx)

        # Log-Y toggle
        act_logy = _make_toggle(self, "Log-Y", checked=self.ylog, slot=self._on_logy_toggled)
        tb.addAction(act_logy)

        # Inverse Filter toggle
        act_invfil = _make_toggle(self, "Inverse Filter", checked=self.invfil, slot=self._on_inverse_toggled)
        tb.addAction(act_invfil)

        act_invfil = _make_toggle(self, "Interpolate", checked=self.interpolate, slot=self._on_interpolate)
        tb.addAction(act_invfil)

        tb.addSeparator()


        act_xrange = QAction("Set X-Range", self)
        act_xrange.triggered.connect(self._on_set_xrange)
        tb.addAction(act_xrange)

        act_irange = QAction("Set Interp-Range", self)
        act_irange.triggered.connect(self._on_set_interp_range)
        tb.addAction(act_irange)

        # Middle spacer
        tb.addWidget(_toolbar_spacer(self))

        # Right: animal selector + nav
        self.cmb_animal = QComboBox()
        self.cmb_animal.addItems(self.store.animals())
        self.cmb_animal.currentTextChanged.connect(self._render)
        tb.addWidget(_labeled_combo(self, "Animal:", self.cmb_animal))

        tb.addSeparator()
        tb.addWidget(_make_nav_button(self, "Prev", QStyle.StandardPixmap.SP_ArrowBack, self._prev_animal))
        tb.addWidget(_make_nav_button(self, "Next", QStyle.StandardPixmap.SP_ArrowForward, self._next_animal))

        # (Optional) overflow menu
        more = QToolButton(self)
        more.setText("More")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(more)
        m.addAction("Reset zoom")
        m.triggered.connect(self._on_reset_zoom)
        more.setMenu(m)
        tb.addWidget(more)

        self.root.addWidget(tb)

    def _build_grid(self):
        # Grid container
        self.glw = pg.GraphicsLayoutWidget()
        self.root.addWidget(self.glw, 1)

        # Subplot registry
        self.plots: Dict[Tuple[str, str], pg.PlotItem] = {}
        self.curves: Dict[Tuple[str, str], pg.PlotDataItem] = {}

        # Column header row (states)
        self.glw.addLabel("", row=0, col=0)  # corner cell
        for c, state in enumerate(self.states, start=1):
            self.glw.addLabel(f"<b>{state.upper()}</b>", row=0, col=c, justify="center")

        # Build matrix: row = channel, col = state
        self.first_plot = None
        for r, ch in enumerate(self.channel_names, start=1):
            # Row header (channel name)
            self.glw.addLabel(f"<b>{ch}</b>", row=r, col=0, angle=0, justify="right")
            for c, state in enumerate(self.states, start=1):
                p = self.glw.addPlot(row=r, col=c)
                p.enableAutoRange(x=True, y=True)
                p.showGrid(x=True, y=True, alpha=0.18)
                p.setLabel("bottom", "Frequency (Hz)")
                p.setLabel("left",   "Power (uV²/Hz)")
                p.setMouseEnabled(x=True, y=True)
                p.setLogMode(self.xlog, self.ylog)  # start with your prefs

                curve = pg.PlotDataItem(pen=pg.mkPen((0, 0, 0), width=1.5))
                curve.setDownsampling(auto=False, method="peak")
                curve.setClipToView(True)
                p.addItem(curve)

                self.plots[(ch, state)] = p
                self.curves[(ch, state)] = curve

                # Link X across all cells
                if self.first_plot is None:
                    self.first_plot = p
                else:
                    p.setXLink(self.first_plot)



    # ---------------- TOGGLES / NAV ----------------

    def _on_interpolate(self, on:bool):
        self.interpolate = bool(on)
        self._render()

    def _on_logx_toggled(self, on: bool):
        self.xlog = bool(on)
        self._render()  # refresh data, range, and ticks

    def _on_logy_toggled(self, on: bool):
        self.ylog = bool(on)
        self._render()

    def _on_inverse_toggled(self, on:bool):
        self.invfil = bool(on)
        self._render()

    def _on_set_xrange(self):
        f_range = self.store.freq_range()
        dlg = FreqBoundsDialog(
            fmin=f_range[0],
            fmax=f_range[1],
            xrange=self.xrange,
            fres=self.store.freq_res(),
            parent=self
        )
        if dlg.exec():  # QDialog.Accepted
            xrange = dlg.values()
            self.xrange = xrange
            print(self.xrange)
            self._render()

    def _on_set_interp_range(self):
        f_range = self.store.freq_range()
        dlg = FreqBoundsDialog(
            fmin=f_range[0],
            fmax=f_range[1],
            xrange=self.interp_range,
            fres=self.store.freq_res(),
            title="Set Frequency Range to Interpolate Over (Line Noise)",
            parent=self
        )
        if dlg.exec():  # QDialog.Accepted
            interp_range = dlg.values()
            self.interp_range = interp_range
            self._render()

    def _on_reset_zoom(self):
        self.xrange = (0.5, 110)
        self._render()

        
    def _prev_animal(self):
        i = self.cmb_animal.currentIndex()
        if i > 0:
            self.cmb_animal.setCurrentIndex(i - 1)

    def _next_animal(self):
        i = self.cmb_animal.currentIndex()
        if i < self.cmb_animal.count() - 1:
            self.cmb_animal.setCurrentIndex(i + 1)

    # ---------------- RENDERING ----------------

    def _render(self, *_):
        animal = self.cmb_animal.currentText()
        if not animal:
            self._clear_all()
            return

        # Some animals might not have all states
        available = set(self.store.states(animal))
        data_by_state = {s: (self.store.get(animal, s) if s in available else {}) for s in self.states}

        # Clamp for log-x safety
        xmin, xmax = self.xrange
        if self.xlog:
            xmin = max(xmin, 1e-12)

        # Fill curves
        for ch in self.channel_names:
            for state in self.states:
                curve = self.curves[(ch, state)]
                cell = data_by_state[state].get(ch)
                if not cell:
                    curve.setData([], [])
                    continue

                f, y = cell
                f = np.asarray(f, float)
                y = np.asarray(y, float)
                y_copy = y.copy()


                # Apply inverse filter if toggle on
                if self.invfil:
                    filter_mask = (f>=FILTER_RANGE[0]) & (f<=FILTER_RANGE[1])
                    y_copy[filter_mask] = y_copy[filter_mask] * INVERSE_FILTER

                if self.interpolate:
                    _, y_copy = interpolate_spectrum(f, y_copy, self.interp_range)

                # Data-space mask; ensure >0 for log axes
                m = (f > 0.0) & (f >= xmin) & (f <= xmax)
                if self.ylog:
                    y = np.clip(y_copy, 1e-12, None)

                curve.setData(f[m], y_copy[m])

        # Apply same x-range to all
        for p in self.plots.values():
            p.setLogMode(self.xlog, self.ylog)
            ylevels = [(10,0), (1,0)] if self.ylog else None
            xlevels = [(10,0), (1,0)] if self.xlog else None
            p.getAxis("left").setTickSpacing(levels=ylevels)
            p.getAxis("bottom").setTickSpacing(levels=xlevels)
            p.getAxis("bottom").setTickDensity(density=0.8)


            





    def _clear_all(self):
        for curve in self.curves.values():
            curve.setData([], [])


    # ---------------- EXPORT ----------------

    def _export_png(self):
        # TODO: Implement export of the entire grid or active view.
        print("Export!")


# ---------------- Toolbar helpers ----------------

def _labeled_combo(parent, label_text: str, combo: QComboBox) -> QWidget:
    w = QWidget(parent)
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    lab = QLabel(label_text, w)
    lab.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
    combo.setMinimumWidth(160)
    h.addWidget(lab)
    h.addWidget(combo)
    return w

def _toolbar_spacer(parent) -> QWidget:
    sp = QWidget(parent)
    sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return sp

def _make_nav_button(parent, text: str, std_icon: QStyle.StandardPixmap, slot):
    btn = QToolButton(parent)
    btn.setText(text)
    btn.setIcon(parent.style().standardIcon(std_icon))
    btn.clicked.connect(slot)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    return btn

def _make_toggle(parent, text: str, checked: bool, slot):
    act = QAction(text, parent, checkable=True)
    act.setChecked(checked)
    act.toggled.connect(slot)
    return act


