"""Channel × state grid of PSD plots for one animal, with manifest-flagging UI.

Used in two modes:
- **Pass 1 PSD review** (`drink_review=False`): pending = animals whose
  ``psd_status[run_name]`` is unset; user flags ``ok`` or ``needs_drink_mask``.
- **Pass 2 drink review** (`drink_review=True`): pending = animals whose
  ``psd_status[run_name] == "drink_mask_applied"``; user verifies the mask
  worked and flags ``ok``.
"""

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from specparam.utils import interpolate_spectrum

from ebb.process.state_presets import gather_states_from_store
from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.widgets.exclude_dialog import exclude_with_reason
from ebb_viewer.widgets.notes_dialog import NotesDialog
from ebb_viewer.widgets.range_dialog import FreqBoundsDialog

# Default interpolation range shown to bridge the line-noise gap in the PSD
# plot. Widened to [56, 64] when the run's psd_params.json has
# apply_notch=True, since the notch filter's stopband is 57-63 Hz (see
# `_NOTCH_HALFWIDTH_HZ` in `ebb.process.psd_compute`) and the wider range
# also covers its rolloff. Purely a display default — the user can still
# override it via the interp-range toolbar action.
_DEFAULT_INTERP_RANGE = [58, 62]
_NOTCH_INTERP_RANGE = [56, 64]

# Inverse-filter coefficients applied in FILTER_RANGE Hz (inclusive) when the
# Inverse Filter toggle is on, to compensate for hardware-induced amplitude
# roll-off at low frequencies.
# TODO: document coefficient source (preamp model + derivation).
INVERSE_FILTER = np.array(
    [2.485297985, 1.360646853, 1.145286775, 1.071699399, 1.038017048, 1.018656356, 1.007806318]
)
FILTER_RANGE = [0.5, 3.5]


class PSDGridPage(QWidget):
    """Channel × state PSD plot grid with toolbar, navigation, and flagging.

    See module docstring for the Pass 1 / Pass 2 mode distinction.
    """

    DEFAULT_XRANGE: tuple[float, float] = (0.5, 110)

    navigate_to = pyqtSignal(str)
    manifest_changed = pyqtSignal()

    def __init__(
        self,
        parent=None,
        *,
        store,  # PSDStore-like: animals() -> List[str], states(animal) -> List[str], get(animal, state) -> Dict[ch,(f,y)]
        channel_names: list[str],  # e.g., ["LFC","RSC","LSC"]
        states: list[str] = None,  # e.g., ["wake","nrem","rem"]
        manifest=None,  # optional Manifest for per-animal flagging
        drink_review: bool = False,  # Pass 2 mode: pending = drink_mask_applied animals
        run_name: str = "default",  # PSD run name for manifest flag scoping
        project_root=None,  # Path for drink-mask hint
    ):
        super().__init__(parent)
        self.store = store
        self.channel_names = list(channel_names)
        if states is None:
            self.states = gather_states_from_store(store)
        else:
            self.states = list(states)
        self.manifest = manifest
        self.drink_review = drink_review
        self._run_name = run_name
        self._project_root = project_root

        # View preferences
        self.xrange: tuple[float, float] = self.DEFAULT_XRANGE
        self.interp_range = self._default_interp_range()
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
        self._mark_excluded_items()
        self._update_flag_status()
        self._install_shortcuts()

    def _default_interp_range(self) -> list[float]:
        """[56, 64] if this run's psd_params.json has apply_notch=True, else
        the narrower non-notch default. Missing/unreadable params (e.g. a
        run computed before the notch filter existed) are treated as
        apply_notch=False, since no notch was ever applied for those runs."""
        if self._project_root is not None:
            params = psd_params.load(self._project_root, self._run_name)
            if params is not None and params.get("apply_notch", False):
                return list(_NOTCH_INTERP_RANGE)
        return list(_DEFAULT_INTERP_RANGE)

    # ---------------- UI BUILDERS ----------------

    def _build_tool_bar(self):
        # View options live in a short QToolBar; everything review-related
        # lives in a plain widget row (``_build_review_bar``) so the OK /
        # Drink Mask buttons can never be pushed into a toolbar overflow
        # chevron on a narrow window.
        tb = QToolBar(self)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setStyleSheet("""
            QToolBar { padding: 4px; spacing: 8px; }
            QToolButton { padding: 3px 8px; }
        """)

        tb.addAction(_make_toggle(self, "Log-X", checked=self.xlog, slot=self._on_logx_toggled))
        tb.addAction(_make_toggle(self, "Log-Y", checked=self.ylog, slot=self._on_logy_toggled))
        tb.addAction(
            _make_toggle(self, "Inverse Filter", checked=self.invfil, slot=self._on_inverse_toggled)
        )
        tb.addAction(
            _make_toggle(self, "Interpolate", checked=self.interpolate, slot=self._on_interpolate)
        )
        tb.addSeparator()

        for text, slot in (
            ("Set X-Range", self._on_set_xrange),
            ("Set Interp-Range", self._on_set_interp_range),
            ("Reset zoom", self._on_reset_zoom),
        ):
            act = QAction(text, self)
            act.triggered.connect(slot)
            tb.addAction(act)

        tb.addWidget(_toolbar_spacer(self))

        # Notes (manifest only). Text/tooltip reflect whether a note exists.
        self._act_notes = QAction("📝 Notes", self)
        self._act_notes.triggered.connect(self._open_notes_dialog)
        self._act_notes.setVisible(self.manifest is not None)
        tb.addAction(self._act_notes)

        self.root.addWidget(tb)
        self._build_review_bar()

        self._guidance_label = QFrame()
        self._guidance_label.setStyleSheet("QFrame { background: #fff3cd; border-radius: 3px; }")
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

        # Shown during Pass 1 when animal has an existing drink mask on disk
        self._mask_hint_frame = QFrame()
        self._mask_hint_frame.setStyleSheet("QFrame { background: #e8f4fd; border-radius: 3px; }")
        mask_hint_layout = QHBoxLayout(self._mask_hint_frame)
        mask_hint_layout.setContentsMargins(10, 5, 10, 5)
        self._mask_hint_lbl = QLabel("")
        self._mask_hint_lbl.setStyleSheet("color: #1a3a5c; background: transparent;")
        self._mask_hint_lbl.setWordWrap(True)
        mask_hint_layout.addWidget(self._mask_hint_lbl, 1)
        self._btn_quick_flag_drink = QPushButton("Flag for drink mask")
        self._btn_quick_flag_drink.setFixedHeight(26)
        self._btn_quick_flag_drink.clicked.connect(self._flag_drink_mask)
        mask_hint_layout.addWidget(self._btn_quick_flag_drink)
        self._mask_hint_frame.setVisible(False)
        self.root.addWidget(self._mask_hint_frame)

    def _build_review_bar(self):
        """Animal selector, prev/next and the OK / Drink Mask flag buttons."""
        bar = QWidget(self)
        h = QHBoxLayout(bar)
        h.setContentsMargins(4, 0, 4, 0)
        h.setSpacing(8)

        self.cmb_animal = QComboBox()
        self.cmb_animal.addItems(self.store.animals())
        self.cmb_animal.currentTextChanged.connect(self._render)
        self.cmb_animal.currentTextChanged.connect(lambda _: self._update_flag_status())
        h.addWidget(_labeled_combo(self, "Animal:", self.cmb_animal))
        h.addWidget(
            _make_nav_button(self, "Prev", QStyle.StandardPixmap.SP_ArrowBack, self._prev_animal)
        )
        h.addWidget(
            _make_nav_button(self, "Next", QStyle.StandardPixmap.SP_ArrowForward, self._next_animal)
        )
        h.addStretch(1)

        # Flag controls (only useful when a manifest is provided)
        self._flag_controls = QWidget(bar)
        fh = QHBoxLayout(self._flag_controls)
        fh.setContentsMargins(0, 0, 0, 0)
        fh.setSpacing(8)

        self._status_label = QLabel("")
        self._status_label.setMinimumWidth(90)
        fh.addWidget(self._status_label)

        self._btn_flag_reset = QPushButton("↺ Reset")
        self._btn_flag_reset.setToolTip("Clear PSD review status for the current animal")
        self._btn_flag_reset.setEnabled(False)
        self._btn_flag_reset.clicked.connect(lambda: self._reset_psd_status())
        fh.addWidget(self._btn_flag_reset)

        self._btn_flag_drink = QPushButton("Drink Mask  (D)")
        self._btn_flag_drink.setCheckable(True)
        self._btn_flag_drink.setToolTip("Flag current animal as needing a drink mask PSD rerun")
        self._btn_flag_drink.clicked.connect(lambda checked: self._flag_drink_mask())
        fh.addWidget(self._btn_flag_drink)

        self._btn_flag_ok = QPushButton("✓ OK  (O)")
        self._btn_flag_ok.setCheckable(True)
        self._btn_flag_ok.setToolTip("Mark current animal's PSD as OK in manifest")
        self._btn_flag_ok.clicked.connect(lambda checked: self._flag_psd_ok())
        fh.addWidget(self._btn_flag_ok)

        # No keyboard shortcut: an exclusion should be deliberate.
        self._btn_flag_exclude = QPushButton("Exclude")
        self._btn_flag_exclude.setCheckable(True)
        self._btn_flag_exclude.setToolTip(
            "Exclude this animal from analysis (a reason is required). "
            "Click again to send it back to Sleep QC review."
        )
        self._btn_flag_exclude.clicked.connect(self._flag_exclude)
        fh.addWidget(self._btn_flag_exclude)

        for btn in (self._btn_flag_ok, self._btn_flag_drink, self._btn_flag_exclude):
            btn.setMinimumHeight(28)
            btn.setStyleSheet(_FLAG_BUTTON_QSS)
        self._btn_flag_ok.setProperty("flag", "ok")
        self._btn_flag_drink.setProperty("flag", "drink")
        self._btn_flag_exclude.setProperty("flag", "exclude")

        h.addWidget(self._flag_controls)
        self._flag_controls.setVisible(self.manifest is not None)
        self.root.addWidget(bar)

    def _build_grid(self):
        # Banner for animals excluded in Sleep QC (hidden otherwise)
        self._excluded_banner = QLabel()
        self._excluded_banner.setWordWrap(True)
        self._excluded_banner.setStyleSheet(
            "background: #e3e3e3; color: #444; border: 1px solid #b5b5b5; "
            "border-radius: 4px; padding: 6px 10px;"
        )
        self._excluded_banner.setVisible(False)
        self.root.addWidget(self._excluded_banner)

        # Grid container
        self.glw = pg.GraphicsLayoutWidget()
        self.root.addWidget(self.glw, 1)

        # Subplot registry
        self.plots: dict[tuple[str, str], pg.PlotItem] = {}
        self.curves: dict[tuple[str, str], pg.PlotDataItem] = {}

        # Column header row (states)
        self.glw.addLabel("", row=0, col=0)  # corner cell
        for c, state in enumerate(self.states, start=1):
            self.glw.addLabel(f"<b>{state.upper()}</b>", row=0, col=c, justify="center")

        # Build matrix: row = channel, col = state
        first_plot = None
        for r, ch in enumerate(self.channel_names, start=1):
            # Row header (channel name)
            self.glw.addLabel(f"<b>{ch}</b>", row=r, col=0, angle=0, justify="right")
            for c, state in enumerate(self.states, start=1):
                p = self.glw.addPlot(row=r, col=c)
                p.enableAutoRange(x=True, y=True)
                p.showGrid(x=True, y=True, alpha=0.18)
                p.setLabel("bottom", "Frequency (Hz)")
                p.setLabel("left", "Power (uV²/Hz)")
                p.setMouseEnabled(x=True, y=True)
                p.setLogMode(self.xlog, self.ylog)  # start with your prefs

                curve = pg.PlotDataItem(pen=pg.mkPen((0, 0, 0), width=1.5))
                curve.setDownsampling(auto=False, method="peak")
                curve.setClipToView(True)
                p.addItem(curve)

                self.plots[(ch, state)] = p
                self.curves[(ch, state)] = curve

                # Link X across all cells
                if first_plot is None:
                    first_plot = p
                else:
                    p.setXLink(first_plot)

    # ---------------- SHORTCUTS ----------------

    def _install_shortcuts(self):
        # Window-wide (while this page is visible) so the shortcuts work even
        # when focus is on the sidebar or the Plot PSDs button.
        ctx = Qt.ShortcutContext.WindowShortcut
        for key, slot in [
            (Qt.Key.Key_Left, self._prev_animal),
            (Qt.Key.Key_Right, self._next_animal),
            ("O", self._flag_psd_ok),
            ("D", self._flag_drink_mask),
        ]:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(ctx)
            sc.activated.connect(slot)

    # ---------------- TOGGLES / NAV ----------------

    def _on_interpolate(self, on: bool):
        self.interpolate = bool(on)
        self._render()

    def _on_logx_toggled(self, on: bool):
        self.xlog = bool(on)
        self._render()  # refresh data, range, and ticks

    def _on_logy_toggled(self, on: bool):
        self.ylog = bool(on)
        self._render()

    def _on_inverse_toggled(self, on: bool):
        self.invfil = bool(on)
        self._render()

    def _on_set_xrange(self):
        f_range = self.store.freq_range()
        dlg = FreqBoundsDialog(
            fmin=f_range[0],
            fmax=f_range[1],
            xrange=self.xrange,
            fres=self.store.freq_res(),
            parent=self,
        )
        if dlg.exec():  # QDialog.Accepted
            self.xrange = dlg.values()
            self._render()

    def _on_set_interp_range(self):
        f_range = self.store.freq_range()
        dlg = FreqBoundsDialog(
            fmin=f_range[0],
            fmax=f_range[1],
            xrange=self.interp_range,
            fres=self.store.freq_res(),
            title="Set Frequency Range to Interpolate Over (Line Noise)",
            parent=self,
        )
        if dlg.exec():  # QDialog.Accepted
            interp_range = dlg.values()
            self.interp_range = interp_range
            self._render()

    def _on_reset_zoom(self):
        self.xrange = self.DEFAULT_XRANGE
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
        data_by_state = {
            s: (self.store.get(animal, s) if s in available else {}) for s in self.states
        }

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
                    filter_mask = (f >= FILTER_RANGE[0]) & (f <= FILTER_RANGE[1])
                    y_copy[filter_mask] = y_copy[filter_mask] * INVERSE_FILTER

                if self.interpolate:
                    _, y_copy = interpolate_spectrum(f, y_copy, self.interp_range)

                # Data-space mask; ensure >0 for log axes
                m = (f > 0.0) & (f >= xmin) & (f <= xmax)
                if self.ylog:
                    # Clip to a tiny positive floor so pyqtgraph's log mode
                    # doesn't produce NaN gaps at zero/negative power bins.
                    y_copy = np.clip(y_copy, 1e-12, None)

                curve.setData(f[m], y_copy[m])

        # Apply same x-range to all
        for p in self.plots.values():
            p.setLogMode(self.xlog, self.ylog)
            ylevels = [(10, 0), (1, 0)] if self.ylog else None
            xlevels = [(10, 0), (1, 0)] if self.xlog else None
            p.getAxis("left").setTickSpacing(levels=ylevels)
            p.getAxis("bottom").setTickSpacing(levels=xlevels)
            p.getAxis("bottom").setTickDensity(density=0.8)

    # ---------------- MANIFEST FLAGGING ----------------

    def _pending_animal_ids(self) -> set[str]:
        if self.manifest is None:
            return set()
        if self.drink_review:
            return {e.animal_id for e in self.manifest.pending_drink_verification(self._run_name)}
        return {e.animal_id for e in self.manifest.pending_psd_review(self._run_name)}

    def _manifest_animal_id(self) -> str | None:
        """Strip _artifact/_drink suffixes from store key to get manifest animal_id."""
        key = self.cmb_animal.currentText()
        if not key:
            return None
        return self._animal_id_of(key)

    def _flag_psd_ok(self) -> None:
        if self.manifest is None:
            return
        animal_id = self._manifest_animal_id()
        if animal_id is None:
            return
        self.manifest.flag_psd(animal_id, "ok", self._run_name)
        self._update_flag_status()
        self.manifest_changed.emit()

    def _flag_drink_mask(self) -> None:
        if self.manifest is None:
            return
        animal_id = self._manifest_animal_id()
        if animal_id is None:
            return
        self.manifest.flag_psd(animal_id, "needs_drink_mask", self._run_name)
        self._update_flag_status()
        self.manifest_changed.emit()

    def _flag_exclude(self, checked: bool) -> None:
        """Exclude the current animal (asking for a reason) or send it back to Sleep QC review."""
        if self.manifest is None:
            return
        animal_id = self._manifest_animal_id()
        if animal_id is None or self.manifest.get(animal_id) is None:
            return
        if checked:
            if not exclude_with_reason(self, self.manifest, animal_id):
                self._update_flag_status()  # cancelled: pop the toggle back out
                return
        else:
            self.manifest.flag_sleep_qc(animal_id, "needs_review")
        self._mark_excluded_items()
        self._update_flag_status()
        self.manifest_changed.emit()

    def _reset_psd_status(self) -> None:
        if self.manifest is None:
            return
        animal_id = self._manifest_animal_id()
        if animal_id is None:
            return
        self.manifest.reset_psd_status(animal_id, self._run_name)
        self._update_flag_status()
        self.manifest_changed.emit()

    def _open_notes_dialog(self) -> None:
        """Open the notes editor for the current animal and persist any change."""
        if self.manifest is None:
            return
        animal_id = self._manifest_animal_id()
        if animal_id is None:
            return
        entry = self.manifest.get(animal_id)
        initial = entry.notes if entry is not None else ""
        dlg = NotesDialog(animal_id=animal_id, initial_text=initial, parent=self)
        if not dlg.exec():
            return
        self.manifest.set_notes(animal_id, dlg.text())
        self._update_flag_status()
        self.manifest_changed.emit()

    def _mark_excluded_items(self) -> None:
        """Grey out excluded animals in the animal dropdown (the item text is the store key)."""
        manifest = self.manifest
        if manifest is None and self._project_root is not None:
            manifest = Manifest.load(self._project_root)
        if manifest is None:
            return
        for i in range(self.cmb_animal.count()):
            entry = manifest.get(self._animal_id_of(self.cmb_animal.itemText(i)))
            excluded = entry is not None and entry.sleep_qc == "excluded"
            self.cmb_animal.setItemData(
                i, QColor(140, 140, 140) if excluded else None, Qt.ItemDataRole.ForegroundRole
            )
            self.cmb_animal.setItemData(
                i, "Excluded in Sleep QC" if excluded else None, Qt.ItemDataRole.ToolTipRole
            )

    @staticmethod
    def _animal_id_of(key: str) -> str:
        """Strip _artifact/_drink suffixes from a store key to get the manifest animal_id."""
        return key.replace("_artifact", "").replace("_drink", "")

    def _excluded_notes(self) -> str | None:
        """The current animal's notes if it is excluded in Sleep QC, else None.

        Reads the manifest on disk when none was passed, so animals are marked in
        views that do not flag.
        """
        animal_id = self._manifest_animal_id()
        if animal_id is None:
            return None
        manifest = self.manifest
        if manifest is None and self._project_root is not None:
            manifest = Manifest.load(self._project_root)
        entry = manifest.get(animal_id) if manifest is not None else None
        if entry is None or entry.sleep_qc != "excluded":
            return None
        return entry.notes.strip()

    def _update_excluded_marker(self) -> None:
        """Banner and grey curves while the current animal is excluded in Sleep QC."""
        notes = self._excluded_notes()
        excluded = notes is not None
        self._excluded_banner.setVisible(excluded)
        if excluded:
            self._excluded_banner.setText(
                "<b>EXCLUDED in Sleep QC</b> — shown for reference; the analysis leaves this "
                "animal out." + (f"<br>{notes.replace(chr(10), '<br>')}" if notes else "")
            )
        pen = pg.mkPen((140, 140, 140) if excluded else (0, 0, 0), width=1.5)
        for curve in self.curves.values():
            curve.setPen(pen)

    def _update_flag_status(self) -> None:
        self._update_excluded_marker()
        if self.manifest is None:
            return
        self._btn_flag_exclude.setChecked(self._excluded_notes() is not None)
        animal_id = self._manifest_animal_id()
        entry = self.manifest.get(animal_id) if animal_id else None
        status = entry.psd_status.get(self._run_name) if entry else None

        self._btn_flag_reset.setEnabled(status is not None)

        has_notes = bool(entry is not None and entry.notes.strip())
        self._act_notes.setText("📝 Notes •" if has_notes else "📝 Notes")
        self._act_notes.setToolTip(entry.notes if has_notes else "Edit notes for this animal")

        # Drink-mask-on-disk hint: show during Pass 1 when status is not yet set
        show_mask_hint = (
            not self.drink_review
            and status is None
            and animal_id is not None
            and self._project_root is not None
            and (self._project_root / f"drink_masks/{animal_id}.npy").exists()
        )
        if show_mask_hint:
            self._mask_hint_lbl.setText(
                "⚠ drink mask on disk from a previous run — flag for drink mask?"
            )
            self._mask_hint_frame.setVisible(True)
        else:
            self._mask_hint_frame.setVisible(False)

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
            excluded = self._excluded_notes() is not None
            self._status_label.setText("excluded" if excluded else "")
            self._status_label.setStyleSheet("color: gray;" if excluded else "")
            self._guidance_label.setVisible(False)

    def _clear_all(self):
        for curve in self.curves.values():
            curve.setData([], [])


_FLAG_BUTTON_QSS = """
    QPushButton { font-weight: bold; padding: 2px 10px; }
    QPushButton[flag="ok"]:checked { background: #2e8b57; color: white; }
    QPushButton[flag="drink"]:checked { background: #e08a00; color: white; }
    QPushButton[flag="exclude"]:checked { background: #7a7a7a; color: white; }
"""


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
