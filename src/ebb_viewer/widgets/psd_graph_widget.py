# psd_matrix_page.py
from typing import Dict, List, Tuple
import numpy as np

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QToolBar, QToolButton, QSizePolicy, QStyle, QMenu, QPushButton, QMessageBox,
    QFrame,
)
import pyqtgraph as pg
from fooof.utils import interpolate_spectrum

from ebb_viewer.widgets.range_dialog import FreqBoundsDialog


INVERSE_FILTER = np.array([2.485297985, 1.360646853, 1.145286775, 1.071699399, 1.038017048, 1.018656356, 1.007806318])
FILTER_RANGE = [0.5, 3.5] #Filter applied in filter range (inclusive)

class PSDGridPage(QWidget):

    navigate_to = pyqtSignal(str)
    manifest_changed = pyqtSignal()

    def __init__(
        self,
        parent=None,
        *,
        store,                    # PSDStore-like: animals() -> List[str], states(animal) -> List[str], get(animal, state) -> Dict[ch,(f,y)]
        channel_names: List[str], # e.g., ["LFC","RSC","LSC"]
        states: List[str] = None, # e.g., ["wake","nrem","rem"]
        manifest=None,            # optional Manifest for per-animal flagging
        run_channels: str | None = None,  # channel combo identifying which run this PSD belongs to
        drink_review: bool = False,  # Pass 2 mode: pending = drink_mask_applied animals
    ):
        super().__init__(parent)
        self.store = store
        self.channel_names = list(channel_names)
        self.states = list(states or ["wake", "nrem", "rem"])
        self.manifest = manifest
        self.run_channels = run_channels
        self._drink_review = drink_review

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
        self._update_flag_status()
        self._install_shortcuts()


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
        self.cmb_animal.currentTextChanged.connect(lambda _: self._update_flag_status())
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

        # Flag buttons (only useful when manifest is provided)
        self._act_flag_sep = tb.addSeparator()
        self._btn_flag_ok = QPushButton("✓ OK")
        self._btn_flag_ok.setFixedHeight(26)
        self._btn_flag_ok.setCheckable(True)
        self._btn_flag_ok.setToolTip("Mark current animal's PSD as OK in manifest")
        self._btn_flag_ok.clicked.connect(lambda checked: self._flag_psd_ok())
        self._act_flag_ok = tb.addWidget(self._btn_flag_ok)

        self._btn_flag_drink = QPushButton("Drink Mask")
        self._btn_flag_drink.setFixedHeight(26)
        self._btn_flag_drink.setCheckable(True)
        self._btn_flag_drink.setToolTip("Flag current animal as needing a drink mask PSD rerun")
        self._btn_flag_drink.clicked.connect(lambda checked: self._flag_drink_mask())
        self._act_flag_drink = tb.addWidget(self._btn_flag_drink)

        self._btn_flag_reset = QPushButton("↺ Reset")
        self._btn_flag_reset.setFixedHeight(26)
        self._btn_flag_reset.setToolTip("Clear PSD review status for the current animal")
        self._btn_flag_reset.setEnabled(False)
        self._btn_flag_reset.clicked.connect(lambda: self._reset_psd_status())
        self._act_flag_reset = tb.addWidget(self._btn_flag_reset)

        self._status_label = QLabel("")
        self._status_label.setMinimumWidth(90)
        self._act_status = tb.addWidget(self._status_label)

        if self.manifest is None:
            self._act_flag_sep.setVisible(False)
            self._act_flag_ok.setVisible(False)
            self._act_flag_drink.setVisible(False)
            self._act_flag_reset.setVisible(False)
            self._act_status.setVisible(False)

        self.root.addWidget(tb)

        self._guidance_label = QFrame()
        self._guidance_label.setStyleSheet(
            "QFrame { background: #fff3cd; border-radius: 3px; }"
        )
        hint_layout = QHBoxLayout(self._guidance_label)
        hint_layout.setContentsMargins(10, 5, 10, 5)
        hint_lbl = QLabel(
            "Place <code>drink_masks/&lt;animal_id&gt;.npy</code> in your project folder, "
            "then run the drink mask rerun."
        )
        hint_lbl.setTextFormat(Qt.TextFormat.RichText)
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet("color: #7a3c00; background: transparent;")
        hint_layout.addWidget(hint_lbl, 1)
        btn_go_drink = QPushButton("→ 8. Drink Mask")
        btn_go_drink.setFixedHeight(26)
        btn_go_drink.clicked.connect(lambda: self.navigate_to.emit("drink_mask"))
        hint_layout.addWidget(btn_go_drink)
        self._guidance_label.setVisible(False)
        self.root.addWidget(self._guidance_label)

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



    # ---------------- SHORTCUTS ----------------

    def _install_shortcuts(self):
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for key, slot in [
            (Qt.Key.Key_Left,  self._prev_animal),
            (Qt.Key.Key_Right, self._next_animal),
            ("O",              self._flag_psd_ok),
            ("D",              self._flag_drink_mask),
        ]:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(ctx)
            sc.activated.connect(slot)

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


            





    # ---------------- MANIFEST FLAGGING ----------------

    def _pending_animal_ids(self) -> set[str]:
        if self.manifest is None:
            return set()
        if self._drink_review:
            # Pass 2: animals with drink_mask_applied awaiting verification
            return {entry.animal_id for entry, _ in self.manifest.pending_drink_verification()}
        if self.run_channels is None:
            # Pass 1 (final PKL): any animal pending PSD review
            return {entry.animal_id for entry, _ in self.manifest.pending_psd_review()}
        return {
            entry.animal_id
            for entry, combo in self.manifest.pending_psd_review()
            if combo == self.run_channels
        }

    def _manifest_animal_id(self) -> str | None:
        """Strip _artifact/_drink suffixes from store key to get manifest animal_id."""
        key = self.cmb_animal.currentText()
        if not key:
            return None
        return key.replace("_artifact", "").replace("_drink", "")

    def _resolve_combo(self, animal_id: str | None) -> str | None:
        """Return the channel combo to use for manifest flagging."""
        if self.run_channels is not None:
            return self.run_channels
        if animal_id is None:
            return None
        return self.store.source_combo(animal_id)

    def _flag_psd_ok(self) -> None:
        if self.manifest is None:
            return
        animal_id = self._manifest_animal_id()
        combo = self._resolve_combo(animal_id)
        if animal_id is None or combo is None:
            return
        self.manifest.flag_psd(animal_id, combo, "ok")
        self._update_flag_status()
        self.manifest_changed.emit()

    def _flag_drink_mask(self) -> None:
        if self.manifest is None:
            return
        animal_id = self._manifest_animal_id()
        combo = self._resolve_combo(animal_id)
        if animal_id is None or combo is None:
            return
        self.manifest.flag_psd(animal_id, combo, "needs_drink_mask")
        self._update_flag_status()
        self.manifest_changed.emit()

    def _reset_psd_status(self) -> None:
        if self.manifest is None:
            return
        animal_id = self._manifest_animal_id()
        combo = self._resolve_combo(animal_id)
        if animal_id is None or combo is None:
            return
        self.manifest.reset_psd_status(animal_id, combo)
        self._update_flag_status()
        self.manifest_changed.emit()

    def _update_flag_status(self) -> None:
        if self.manifest is None:
            return
        animal_id = self._manifest_animal_id()
        combo = self._resolve_combo(animal_id)
        run = self.manifest.get_run(animal_id, combo) if (animal_id and combo) else None
        status = run.psd_status if run else None

        self._btn_flag_reset.setEnabled(status is not None)

        if status == "ok":
            self._btn_flag_ok.setChecked(True)
            self._btn_flag_drink.setChecked(False)
            self._status_label.setText("✓ OK")
            self._status_label.setStyleSheet("color: green; font-weight: bold;")
            self._guidance_label.setVisible(False)
        elif status == "needs_drink_mask":
            self._btn_flag_ok.setChecked(False)
            self._btn_flag_drink.setChecked(True)
            self._status_label.setText("⚠ Drink Mask")
            self._status_label.setStyleSheet("color: orange; font-weight: bold;")
            self._guidance_label.setVisible(self.manifest is not None)
        elif animal_id in self._pending_animal_ids():
            self._btn_flag_ok.setChecked(False)
            self._btn_flag_drink.setChecked(False)
            self._status_label.setText("pending")
            self._status_label.setStyleSheet("color: gray;")
            self._guidance_label.setVisible(False)
        else:
            self._btn_flag_ok.setChecked(False)
            self._btn_flag_drink.setChecked(False)
            self._status_label.setText("")
            self._status_label.setStyleSheet("")
            self._guidance_label.setVisible(False)

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


