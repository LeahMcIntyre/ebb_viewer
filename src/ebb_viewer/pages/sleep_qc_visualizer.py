"""Sleep QC visualizer page — review per-animal sleep metrics + spindle masks.

Drives the post-spindle-upload review step: a 3×3 grid of plots (states ×
metrics) for batch comparison, plus a "Spindle Mask" box-and-strip view
for masking-fraction outlier detection. Group mode shows a page of
animals; animal mode shows a single animal.

State of record: ``self._manifest`` (in-memory ``Manifest``, refreshed
on showEvent / poll / decisions) plus ``self._data`` (a tuple of four
dataframes for the project combo: bins, bins_offset, bins_clock,
spindle_fractions).
"""

from __future__ import annotations

import warnings
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib as mpl
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ebb.process.sleep_compute import (
    compute_sleep_bins_df,
    compute_sleep_bins_df_clock_aligned,
    compute_sleep_bins_df_offset,
    compute_spindle_fractions,
)
from ebb_viewer.pipeline.manifest import Manifest, spindle_output_dir
from ebb_viewer.pipeline.theme import STATUS_COLOR_HEX
from ebb_viewer.widgets.notes_dialog import NotesDialog

# Project recordings are all acquired in the Central time zone. Used by the
# offset variant of the sleep-bins computation so the next-`begin_hr`
# rotation honors DST transitions rather than drifting an hour across them.
_RECORDING_TZ = ZoneInfo("America/Chicago")


class SleepQCGridPage(QWidget):
    """
    QC page: 3×3 grid (states × metrics) for the project's channel combo.

    Group mode: shows up to MICE_PER_PAGE animals at a time, with optional
    group-median reference line.

    Animal mode: shows one selected animal, with the same optional reference
    line. Animals not yet reviewed appear first in the dropdown.
    """

    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)

    # (display label, internal mode key) pairs for the axis dropdown. Order
    # determines the dropdown's item order and the default (first item).
    _AXIS_MODES = (
        ("Clock-aligned", "clock"),
        ("Rotate to 6AM", "rotate"),
        ("From Start", "start"),
    )

    STATE_ORDER = ["w", "n", "r"]
    STATE_DEF = {"w": "Wake", "n": "NREM", "r": "REM"}
    METRIC_ORDER = [
        ("frac_time", "Fraction of time"),
        ("n_bouts", "# bouts"),
        ("mean_bout_sec", "Mean bout duration (s)"),
    ]

    MICE_PER_PAGE = 10

    # Line colour for the single animal shown in animal mode.
    _ANIMAL_COLOR = (31, 119, 180)

    # Sentinel for ``_refresh_frac_plot``'s optional-but-distinct-from-None
    # ``current_animal`` arg: "read from combo box" vs "clear to None".
    _DEFAULT_ANIMAL = object()

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)

        # Cache: (df_start, df_rotate, df_clock, df_frac). df_start has
        # bin_start_hr counted from sample 0; df_rotate is rotated so bin 0 lands
        # on begin_hr; df_clock places each animal's bins at their true clock
        # position. _axis_mode picks which one feeds _get_df.
        self._data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame] | None = None
        # (n_csvs, newest mtime) of the output folder when _data was loaded.
        self._data_sig: tuple[int, float] | None = None
        self._axis_mode: str = "clock"
        self._mouse_ids: list[str] = []
        self._current_page: int = 0
        self._mode: str = "group"
        self._nav_hint_dest: str = ""
        self._highlighted_animal: str | None = None
        self._show_ref_median: bool = False
        # IQR-outlier set, lazily computed by _get_spindle_outlier_animals.
        # Reset whenever _data is reloaded.
        self._outliers: set[str] | None = None

        # Animals skipped during the offset compute because no preprocessed
        # EDF was found, or whose recording was too short for the begin_hr
        # rotation. Populated by `_load_data`, drained by `_flush_skip_warnings`
        # on the next event-loop tick.
        self._pending_missing_edf: set[str] = set()
        self._pending_too_short: set[str] = set()
        self._skip_popup_scheduled: bool = False

        self._plots: dict[tuple[str, str], pg.PlotItem] = {}

        self._refresh_manifest()

        self._build_ui()
        self._wire()

    @property
    def _combo(self) -> str:
        return self._manifest.combo

    def _refresh_manifest(self) -> None:
        """Reload the manifest from disk."""
        self._manifest = Manifest.load(self.project_root)

    def _poll(self):
        """Lightweight background refresh: reload manifest, pick up newly downloaded CSVs."""
        self._refresh_manifest()
        if self._ensure_data():
            self._refresh_views()
        self._update_nav_hint()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_manifest()
        self._highlighted_animal = None
        self._ensure_data()
        self._refresh_views()
        self._update_nav_hint()

    def _refresh_views(self) -> None:
        """Re-render whichever view is active against the current ``_data``."""
        self.lbl_combo.setText(f"Combo: {self._combo}")
        self._update_page_controls()
        if self.btn_spindle.isChecked():
            self._set_spindle_mask_mode(True)
        elif self._mode == "animal":
            self._refresh_animal_combo()
            self._update_all_plots()
        else:
            self._update_all_plots()

    def _update_nav_hint(self) -> None:
        entries = [e for e in self._manifest if e.has_spindle]
        if not entries:
            self._hint_frame.setVisible(False)
            return
        has_review = any(e.sleep_qc == "needs_review" for e in entries)
        all_have_ok = all(e.sleep_qc == "ok" for e in entries)
        if has_review:
            self._hint_lbl.setText("Check animals flagged for EDF review.")
            self._hint_btn.setText("→ Home (review flagged EDFs)")
            self._nav_hint_dest = "home"
            self._hint_frame.setStyleSheet(
                "QFrame { background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; }"
            )
            self._hint_frame.setVisible(True)
        elif all_have_ok:
            self._hint_lbl.setText("✓ All spindle metrics checked — ready for PSD computation.")
            self._hint_btn.setText("→ PSD Computation")
            self._nav_hint_dest = "psd_compute"
            self._hint_frame.setStyleSheet(
                "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
            )
            self._hint_frame.setVisible(True)
        else:
            self._hint_frame.setVisible(False)

    def _go_nav_hint(self) -> None:
        self.navigate_to.emit(self._nav_hint_dest)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setObjectName("sleepQcPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        lbl = QLabel("Sleep Quality Check Visualizer")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        desc = QLabel(
            "Review sleep staging results for each animal. "
            "Flag animals as ok or needs review based on sleep metrics and the fraction of each state masked by artifact."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(lbl)
        layout.addWidget(desc)

        # --- top bar ---
        # Two logical clusters separated by stretches + small section labels:
        # DISPLAY (Group / Animal / axis / Median; Sleep view only) → VIEW
        # (which top-level view).
        top = QHBoxLayout()
        top.setSpacing(6)

        self.lbl_combo = QLabel(f"Combo: {self._combo}")
        top.addWidget(self.lbl_combo)

        # DISPLAY cluster (sleep-view-only — wrapped so we can hide it whole)
        self._sleep_mode_controls = QWidget()
        smc = QHBoxLayout(self._sleep_mode_controls)
        smc.setContentsMargins(0, 0, 0, 0)
        smc.setSpacing(6)

        smc.addSpacing(12)
        smc.addWidget(_vsep(self))
        smc.addSpacing(6)
        smc.addWidget(_section_label("DISPLAY"))

        # Group / Animal — radio-like; rendered as one "segmented control"
        # by laying the two native buttons flush against each other so they
        # read as a connected pill without overriding the system style.
        self.btn_group = QPushButton("Group")
        self.btn_group.setCheckable(True)
        self.btn_group.setChecked(True)
        self.btn_animal = QPushButton("Animal")
        self.btn_animal.setCheckable(True)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(0)
        mode_row.addWidget(self.btn_group)
        mode_row.addWidget(self.btn_animal)
        mode_wrap = QWidget()
        mode_wrap.setLayout(mode_row)
        smc.addWidget(mode_wrap)

        # Axis mode — three exclusive options behind a compact dropdown.
        # Display labels are tied to the internal mode keys via _AXIS_MODES.
        smc.addWidget(QLabel("Time axis:"))
        self.cmb_axis_mode = QComboBox()
        self.cmb_axis_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for label, _ in self._AXIS_MODES:
            self.cmb_axis_mode.addItem(label)
        smc.addWidget(self.cmb_axis_mode)

        self.btn_median = QPushButton("Median")
        self.btn_median.setCheckable(True)
        self.btn_median.setChecked(False)
        smc.addWidget(self.btn_median)

        self._sleep_mode_controls.setVisible(False)
        top.addWidget(self._sleep_mode_controls)
        top.addStretch(1)

        # VIEW cluster — same flush-pair treatment as Group/Animal.
        top.addWidget(_section_label("VIEW"))
        self.btn_spindle = QPushButton("Spindle Mask")
        self.btn_spindle.setCheckable(True)
        self.btn_spindle.setChecked(True)
        self.btn_view_sleep = QPushButton("Sleep")
        self.btn_view_sleep.setCheckable(True)
        self.btn_view_sleep.setChecked(False)
        view_row = QHBoxLayout()
        view_row.setContentsMargins(0, 0, 0, 0)
        view_row.setSpacing(0)
        view_row.addWidget(self.btn_spindle)
        view_row.addWidget(self.btn_view_sleep)
        view_wrap = QWidget()
        view_wrap.setLayout(view_row)
        top.addWidget(view_wrap)

        top.addSpacing(12)
        top.addWidget(_vsep(self))
        top.addSpacing(6)

        layout.addLayout(top)

        # --- group-mode controls ---
        self._group_controls = QWidget()
        gc = QHBoxLayout(self._group_controls)
        gc.setContentsMargins(0, 0, 0, 0)
        self.btn_prev = QPushButton("◄ Prev")
        self.btn_next = QPushButton("Next ►")
        self.spin_page = QSpinBox()
        self.spin_page.setMinimum(1)
        self.spin_page.setMaximum(1)
        self.lbl_page = QLabel("Page 1 / 1")
        gc.addWidget(self.btn_prev)
        gc.addWidget(self.btn_next)
        gc.addWidget(QLabel("Go to:"))
        gc.addWidget(self.spin_page)
        gc.addWidget(self.lbl_page)
        gc.addStretch(1)
        layout.addWidget(self._group_controls)

        # --- animal-mode controls ---
        self._animal_controls = QWidget()
        ac = QHBoxLayout(self._animal_controls)
        ac.setContentsMargins(0, 0, 0, 0)
        self._lbl_animal = QLabel("Animal:")
        ac.addWidget(self._lbl_animal)
        self.cmb_animal = QComboBox()
        self.cmb_animal.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.cmb_animal.setMinimumWidth(150)
        ac.addWidget(self.cmb_animal)
        self.btn_prev_animal = QPushButton("◄ Prev")
        self.btn_next_animal = QPushButton("Next ►")
        ac.addWidget(self.btn_prev_animal)
        ac.addWidget(self.btn_next_animal)
        ac.addStretch(1)
        self._animal_controls.setVisible(False)
        layout.addWidget(self._animal_controls)

        # --- plot grid ---
        self.grid = pg.GraphicsLayoutWidget()
        self.grid.setBackground("w")
        self.grid.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        for si, state in enumerate(self.STATE_ORDER):
            for mi, (metric, metric_label) in enumerate(self.METRIC_ORDER):
                p: pg.PlotItem = self.grid.addPlot(row=mi, col=si)
                p.showGrid(x=True, y=True, alpha=0.3)
                if mi < len(self.METRIC_ORDER) - 1:
                    p.getAxis("bottom").setStyle(showValues=False)
                else:
                    p.setLabel("bottom", "Time (h)")
                if si == 0:
                    p.setLabel("left", metric_label)
                p.setTitle(f"{self.STATE_DEF[state]}: {metric_label}", size="10pt")
                self._plots[(metric, state)] = p

        self._frac_widget = SpindleFractionPlot()
        self._frac_widget.setVisible(True)
        layout.addWidget(self._frac_widget, stretch=1)

        self.grid.setVisible(False)
        layout.addWidget(self.grid, stretch=1)

        # --- legend (in a scroll area so the plot grid can't collapse it) ---
        self.legend_container = QWidget()
        self.legend_layout = QGridLayout(self.legend_container)
        self.legend_layout.setContentsMargins(2, 2, 2, 2)
        self.legend_layout.setVerticalSpacing(4)
        self.legend_layout.setHorizontalSpacing(40)
        self.legend_layout.setColumnStretch(0, 1)
        self.legend_layout.setColumnStretch(1, 1)

        self._legend_scroll = QScrollArea()
        self._legend_scroll.setWidget(self.legend_container)
        self._legend_scroll.setWidgetResizable(True)
        self._legend_scroll.setFixedHeight(160)
        self._legend_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._legend_scroll)

        # Navigation hint (hidden until all animals are reviewed)
        self._hint_frame = QFrame()
        self._hint_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._hint_frame.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QHBoxLayout(self._hint_frame)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        self._hint_lbl = QLabel()
        hint_layout.addWidget(self._hint_lbl, 1)
        self._hint_btn = QPushButton()
        hint_layout.addWidget(self._hint_btn)
        self._hint_frame.setVisible(False)
        layout.addWidget(self._hint_frame)

    def _wire(self) -> None:
        self.btn_group.clicked.connect(lambda: self._set_mode("group"))
        self.btn_animal.clicked.connect(lambda: self._set_mode("animal"))
        self.cmb_axis_mode.currentIndexChanged.connect(self._on_axis_mode_changed)
        self.btn_median.toggled.connect(self._on_median_toggled)
        self.btn_view_sleep.clicked.connect(lambda: self._set_spindle_mask_mode(False))
        self.btn_spindle.clicked.connect(lambda: self._set_spindle_mask_mode(True))
        self._frac_widget.animal_clicked.connect(self._on_frac_animal_selected)
        self._frac_widget.review_requested.connect(self._on_frac_review_requested)

        self.btn_prev.clicked.connect(self._on_prev_page)
        self.btn_next.clicked.connect(self._on_next_page)
        self.spin_page.valueChanged.connect(self._on_page_spin_changed)

        self._hint_btn.clicked.connect(self._go_nav_hint)

        self.cmb_animal.currentTextChanged.connect(self._on_animal_changed)
        self.btn_prev_animal.clicked.connect(self._on_prev_animal)
        self.btn_next_animal.clicked.connect(self._on_next_animal)

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------
    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        is_group = mode == "group"
        self.btn_group.setChecked(is_group)
        self.btn_animal.setChecked(not is_group)

        if not self.btn_spindle.isChecked():
            self._group_controls.setVisible(is_group)
            self._animal_controls.setVisible(not is_group)

        if not is_group:
            self._refresh_animal_combo()

        self._update_all_plots()

    def _on_axis_mode_changed(self, index: int) -> None:
        self._axis_mode = self._AXIS_MODES[index][1]
        self._ensure_data()
        if self._axis_mode == "rotate":
            self._maybe_show_rotate_skip_warning()
        self._update_all_plots()

    def _set_spindle_mask_mode(self, spindle: bool) -> None:
        self.btn_view_sleep.setChecked(not spindle)
        self.btn_spindle.setChecked(spindle)
        self.grid.setVisible(not spindle)
        self._frac_widget.setVisible(spindle)
        self._sleep_mode_controls.setVisible(not spindle)
        self._legend_scroll.setVisible(not spindle)
        if spindle:
            self._group_controls.setVisible(False)
            self._animal_controls.setVisible(True)
            self._lbl_animal.setText("Highlight:")
            self._refresh_animal_combo()
            self._frac_widget.clear_selection()
            self._refresh_frac_plot()
            self._render_group()
        else:
            self._lbl_animal.setText("Animal:")
            self._set_mode(self._mode)

    def _refresh_frac_plot(self, current_animal: str | None = _DEFAULT_ANIMAL) -> None:
        df_frac = self._get_frac_df()
        if current_animal is self._DEFAULT_ANIMAL:
            current_animal = self.cmb_animal.currentText() or None
        self._frac_widget.set_data(df_frac, title=self._combo, current_animal=current_animal)

    def _on_frac_animal_selected(self, mouse_id: str) -> None:
        """Dot clicked or dismissed — update the highlight without leaving the spindle mask view."""
        if mouse_id:
            self.cmb_animal.setCurrentText(
                mouse_id
            )  # triggers _on_animal_changed → _refresh_frac_plot
            entry = self._manifest.get(mouse_id)
            self._frac_widget.update_strip_status(entry.sleep_qc if entry else None)
        else:
            self._refresh_frac_plot(current_animal=None)  # clear highlight

    def _on_frac_review_requested(self, mouse_id: str) -> None:
        """Flag the selected animal for review from within the spindle mask view."""
        self._flag_sleep_qc(mouse_id, "needs_review")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def _csv_dir(self) -> Path:
        return spindle_output_dir(self._combo, self.project_root)

    def _csv_signature(self) -> tuple[int, float]:
        """(n_csvs, newest mtime) of the output folder — changes when CSVs are added/updated."""
        d = self._csv_dir()
        mtimes = [p.stat().st_mtime for p in d.glob("*.csv")] if d.is_dir() else []
        return len(mtimes), max(mtimes, default=0.0)

    def _ensure_data(self) -> bool:
        """Load the metrics if missing or the CSV folder changed. Returns True if reloaded."""
        sig = self._csv_signature()
        if self._data is not None and sig == self._data_sig:
            return False
        self._load_data(sig)
        return True

    def _load_data(self, sig: tuple[int, float]) -> None:
        """Compute and cache the sleep metrics for the project combo."""
        self._data = None
        self._outliers = None
        self._mouse_ids = []
        self._data_sig = sig
        d = self._csv_dir()
        if not d.is_dir():
            return
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", UserWarning)
                df_start = compute_sleep_bins_df(d)
                df_rotate = compute_sleep_bins_df_offset(
                    d, self.project_root / "standard", tz=_RECORDING_TZ
                )
                df_clock = compute_sleep_bins_df_clock_aligned(
                    d, self.project_root / "standard", tz=_RECORDING_TZ
                )
                df_frac = compute_spindle_fractions(d)
        except Exception as e:
            QMessageBox.critical(
                self, "Error loading sleep metrics", f"Could not load {self._combo}:\n{e}"
            )
            return
        self._record_skip_warnings(caught)
        self._data = (df_start, df_rotate, df_clock, df_frac)
        self._mouse_ids = sorted(df_start["mouse_id"].unique())

    def _record_skip_warnings(self, caught: list) -> None:
        """Collect skip warnings from a compute batch (missing-EDF and
        too-short-for-rotation) and schedule a single dialog to fire once the
        current event-loop tick finishes."""
        missing: set[str] = set()
        too_short: set[str] = set()
        for w in caught:
            msg = str(w.message)
            if msg.startswith("No EDF for animal"):
                # Format: "No EDF for animal 'AM001' in ...; skipping ..."
                try:
                    missing.add(msg.split("'", 2)[1])
                except IndexError:
                    continue
            elif msg.startswith("Recording for ") and "too short for begin_hr" in msg:
                # Format: "Recording for 'GT0582' is too short for begin_hr=6 ..."
                try:
                    too_short.add(msg.split("'", 2)[1])
                except IndexError:
                    continue
        self._pending_missing_edf.update(missing)
        # Too-short animals are NOT auto-popped — they're visible in
        # Clock-aligned (the default), so the warning only surfaces when the
        # user actively switches to Rotate mode (see
        # _maybe_show_rotate_skip_warning).
        self._pending_too_short.update(too_short)
        if missing and not self._skip_popup_scheduled:
            self._skip_popup_scheduled = True
            QTimer.singleShot(0, self._flush_skip_warnings)

    def _flush_skip_warnings(self) -> None:
        self._skip_popup_scheduled = False
        if not self._pending_missing_edf:
            return
        animals = ", ".join(sorted(self._pending_missing_edf))
        self._pending_missing_edf.clear()
        QMessageBox.warning(
            self,
            "Missing preprocessed EDFs",
            "Animals with sleep CSVs but no preprocessed EDF in standard/ "
            "(offset/clock-aligned metrics skipped):\n\n"
            f"  {animals}"
            "\n\nRe-run the Preprocess page for these animals to include them.",
        )

    def _maybe_show_rotate_skip_warning(self) -> None:
        # Surface the too-short warning that _record_skip_warnings stashed.
        # Called from _on_axis_mode_changed when the user picks rotate, so the
        # message is contextual to the mode that actually hides these animals.
        if not self._pending_too_short:
            return
        animals = ", ".join(sorted(self._pending_too_short))
        self._pending_too_short.clear()
        QMessageBox.warning(
            self,
            "Animals hidden in Rotate mode",
            "These recordings were too short to reach the next 6AM and are "
            "skipped in Rotate mode:\n\n"
            f"  {animals}"
            "\n\nSwitch back to Clock-aligned mode to view them at their "
            "true circadian position.",
        )

    # ------------------------------------------------------------------
    # Animal combo (animal mode)
    # ------------------------------------------------------------------
    def _refresh_animal_combo(self) -> None:
        all_mice = sorted(self._mouse_ids)

        def _unreviewed(mid: str) -> bool:
            entry = self._manifest.get(mid)
            return entry is not None and entry.sleep_qc is None

        # Unreviewed animals first, then the rest.
        pending = [m for m in all_mice if _unreviewed(m)]
        reviewed = [m for m in all_mice if not _unreviewed(m)]
        all_mice = pending + reviewed

        self.cmb_animal.blockSignals(True)
        current = self.cmb_animal.currentText()
        self.cmb_animal.clear()
        self.cmb_animal.addItems(all_mice)
        if current in all_mice:
            self.cmb_animal.setCurrentText(current)
        self.cmb_animal.blockSignals(False)
        self._sync_animal_nav()

    def _on_animal_changed(self, _: str) -> None:
        self._sync_animal_nav()
        self._update_all_plots()

    def _sync_animal_nav(self) -> None:
        i = self.cmb_animal.currentIndex()
        n = self.cmb_animal.count()
        self.btn_prev_animal.setEnabled(i > 0)
        self.btn_next_animal.setEnabled(i < n - 1)

    def _on_prev_animal(self) -> None:
        i = self.cmb_animal.currentIndex()
        if i > 0:
            self.cmb_animal.setCurrentIndex(i - 1)

    def _on_next_animal(self) -> None:
        i = self.cmb_animal.currentIndex()
        if i < self.cmb_animal.count() - 1:
            self.cmb_animal.setCurrentIndex(i + 1)

    # ------------------------------------------------------------------
    # Pagination (group mode)
    # ------------------------------------------------------------------
    def _update_page_controls(self) -> None:
        n = len(self._mouse_ids)
        if n == 0:
            self.spin_page.setMaximum(1)
            self.spin_page.setValue(1)
            self.lbl_page.setText("Page 0 / 0")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return

        n_pages = max(1, int(np.ceil(n / self.MICE_PER_PAGE)))
        self._current_page = max(0, min(self._current_page, n_pages - 1))

        self.spin_page.blockSignals(True)
        self.spin_page.setMaximum(n_pages)
        self.spin_page.setValue(self._current_page + 1)
        self.spin_page.blockSignals(False)

        self.lbl_page.setText(f"Page {self._current_page + 1} / {n_pages}")
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(self._current_page < n_pages - 1)

    def _get_page_mice(self) -> list[str]:
        start = self._current_page * self.MICE_PER_PAGE
        return self._mouse_ids[start : start + self.MICE_PER_PAGE]

    def _on_prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._update_page_controls()
            self._update_all_plots()

    def _on_next_page(self) -> None:
        n_pages = max(1, int(np.ceil(len(self._mouse_ids) / self.MICE_PER_PAGE)))
        if self._current_page < n_pages - 1:
            self._current_page += 1
            self._update_page_controls()
            self._update_all_plots()

    def _on_page_spin_changed(self, value: int) -> None:
        self._current_page = max(0, value - 1)
        self._update_page_controls()
        self._update_all_plots()

    # ------------------------------------------------------------------
    # Plotting helpers
    # ------------------------------------------------------------------
    def _get_df(self) -> pd.DataFrame | None:
        if self._data is None:
            return None
        df_start, df_rotate, df_clock, _df_frac = self._data
        return {"start": df_start, "rotate": df_rotate, "clock": df_clock}[self._axis_mode]

    def _get_frac_df(self) -> pd.DataFrame | None:
        return self._data[3] if self._data is not None else None

    @staticmethod
    def _ensure_x_col(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        if "bin_start_hr" in df.columns:
            return df, "bin_start_hr"
        return df.assign(bin_start_hr=df["bin_start_sec"] / 3600.0), "bin_start_hr"

    def _prepare_plots(self) -> None:
        bottom_metric = self.METRIC_ORDER[-1][0]
        for p in self._plots.values():
            p.clear()
        for state in self.STATE_ORDER:
            self._plots[(bottom_metric, state)].getAxis("bottom").setTicks(None)

    def _get_spindle_outlier_animals(self) -> set:
        """Return animal IDs that are IQR × 1.5 outliers in any state of the spindle fraction data.

        Cached to avoid recomputing on every legend rebuild + every render
        pass. Reset by ``_load_data`` when fresh data lands.
        """
        if self._outliers is not None:
            return self._outliers
        df_frac = self._get_frac_df()
        if df_frac is None or df_frac.empty:
            return set()
        outliers: set[str] = set()
        for state in df_frac["state"].unique():
            sdf = df_frac[df_frac["state"] == state].dropna(subset=["fraction"])
            if len(sdf) < 4:
                continue
            fracs = sdf["fraction"].to_numpy(dtype=float)
            q1, q3 = np.percentile(fracs, [25, 75])
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            mask = (fracs < lo) | (fracs > hi)
            outliers.update(sdf["mouse_id"].to_numpy()[mask])
        self._outliers = outliers
        return outliers

    @staticmethod
    def _plot_series(
        plot_item,
        xs,
        ys,
        *,
        color: tuple[int, int, int],
        alpha: int = 255,
        width: float = 1.5,
        style: Qt.PenStyle = Qt.PenStyle.SolidLine,
    ) -> None:
        # pyqtgraph needs >=2 points to draw a visible line segment, so single-
        # point series (e.g. short clock-aligned recordings that span <1 bin)
        # would render as nothing without a marker.
        pen = pg.mkPen(color=(*color, alpha), width=width, style=style)
        if len(xs) <= 1:
            plot_item.plot(
                xs,
                ys,
                pen=None,
                symbol="o",
                symbolBrush=(*color, alpha),
                symbolPen=None,
                symbolSize=7,
            )
        else:
            plot_item.plot(xs, ys, pen=pen)

    def _apply_hour_of_day_ticks(self, x_vals) -> None:
        """Replace bottom-axis tick labels with hour-of-day (x % 24) for offset mode."""
        ticks = [[(float(x), str(int(x) % 24)) for x in sorted(set(x_vals)) if int(x) % 6 == 0]]
        bottom_metric = self.METRIC_ORDER[-1][0]
        for state in self.STATE_ORDER:
            self._plots[(bottom_metric, state)].getAxis("bottom").setTicks(ticks)

    def _update_all_plots(self, *_) -> None:
        if self.btn_spindle.isChecked():
            self._refresh_frac_plot()
            return
        if self._mode == "group":
            self._render_group()
        else:
            self._render_animal()

    def _render_group(self) -> None:
        df = self._get_df()
        mice = self._get_page_mice()

        self._prepare_plots()

        if df is None or df.empty or not mice:
            self._update_legend_group([], {})
            return

        df, x_col = self._ensure_x_col(df)
        mouse_colors = self._build_mouse_color_map(mice)

        for state in self.STATE_ORDER:
            for metric, _ in self.METRIC_ORDER:
                p = self._plots[(metric, state)]
                if metric == self.METRIC_ORDER[-1][0]:
                    label = (
                        "Time (h) From EEG Start"
                        if self._axis_mode == "start"
                        else "Time (h)"
                    )
                    p.setLabel("bottom", label)

        sub = df[df["mouse_id"].isin(mice)]
        for state in self.STATE_ORDER:
            for metric, _ in self.METRIC_ORDER:
                p = self._plots[(metric, state)]
                panel = sub[sub["state"] == state]
                for mid in mice:
                    dm = panel[panel["mouse_id"] == mid].copy()
                    if dm.empty:
                        continue
                    dm[metric] = dm[metric].fillna(0)
                    dm = dm.sort_values(x_col)
                    if self._highlighted_animal:
                        alpha = 255 if mid == self._highlighted_animal else 80
                    else:
                        alpha = 255
                    self._plot_series(
                        p,
                        dm[x_col].to_numpy(),
                        dm[metric].to_numpy(),
                        color=mouse_colors[mid],
                        alpha=alpha,
                    )

        if self._axis_mode != "start" and not df.empty:
            self._apply_hour_of_day_ticks(df[x_col].unique())

        if self._show_ref_median:
            self._draw_ref_median()

        self._update_legend_group(mice, mouse_colors, self._show_ref_median)

    def _render_animal(self) -> None:
        animal = self.cmb_animal.currentText()

        self._prepare_plots()

        df = self._get_df()
        if not animal or df is None or df.empty:
            self._update_legend_animal()
            return

        df, x_col = self._ensure_x_col(df)
        adf = df[df["mouse_id"] == animal]
        if adf.empty:
            self._update_legend_animal()
            return

        outliers = self._get_spindle_outlier_animals()
        alpha = 255 if (not outliers or animal in outliers) else 80
        for state in self.STATE_ORDER:
            for metric, _ in self.METRIC_ORDER:
                dm = adf[adf["state"] == state].copy()
                if dm.empty:
                    continue
                dm[metric] = dm[metric].fillna(0)
                dm = dm.sort_values(x_col)
                self._plot_series(
                    self._plots[(metric, state)],
                    dm[x_col].to_numpy(),
                    dm[metric].to_numpy(),
                    color=self._ANIMAL_COLOR,
                    alpha=alpha,
                    width=2.0,
                )

        # Group median reference overlay — gated by the Median toggle so the
        # button has consistent semantics across group / animal modes.
        if self._show_ref_median:
            self._draw_ref_median()

        if self._axis_mode != "start":
            self._apply_hour_of_day_ticks(adf[x_col].unique())

        self._update_legend_animal(self._show_ref_median)

    # ------------------------------------------------------------------
    # Group median reference overlay
    # ------------------------------------------------------------------
    def _on_median_toggled(self, checked: bool) -> None:
        self._show_ref_median = checked
        self._update_all_plots()

    def _draw_ref_median(self) -> None:
        """Draw group median reference as a dashed line on all plots."""
        df = self._get_df()
        if df is None or df.empty:
            return
        df, x_col = self._ensure_x_col(df)
        metrics = [m for m, _ in self.METRIC_ORDER]
        median_df = df.groupby(["state", x_col])[metrics].median().reset_index()

        ref_pen = pg.mkPen(color=(80, 80, 80), width=2.5, style=Qt.PenStyle.DashLine)
        for state in self.STATE_ORDER:
            for metric, _ in self.METRIC_ORDER:
                panel = median_df[median_df["state"] == state].sort_values(x_col)
                if panel.empty:
                    continue
                self._plots[(metric, state)].plot(
                    panel[x_col].to_numpy(), panel[metric].to_numpy(), pen=ref_pen
                )

    # ------------------------------------------------------------------
    # Legend
    # ------------------------------------------------------------------
    def _on_legend_highlight(self, mid: str, checked: bool) -> None:
        self._highlighted_animal = mid if checked else None
        self._update_all_plots()

    def _clear_legend(self) -> None:
        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _make_legend_row_frame(
        self, color: tuple, status: str | None
    ) -> tuple[QWidget, QHBoxLayout]:
        """Create a styled legend row with a color swatch. Returns (widget, layout)."""
        swatch = QFrame()
        swatch.setFixedSize(30, 4)
        swatch.setStyleSheet(f"background-color: rgb({color[0]}, {color[1]}, {color[2]});")

        row_w = QWidget()
        row_l = QHBoxLayout(row_w)
        row_l.setContentsMargins(4, 2, 4, 2)
        row_l.setSpacing(4)
        row_l.addWidget(swatch)

        bg = STATUS_COLOR_HEX.get(status)
        row_w.setObjectName("legendRow")
        row_w.setStyleSheet(
            f"QWidget#legendRow {{ background-color: {bg or 'transparent'}; border-radius: 3px; }}"
        )
        return row_w, row_l

    def _build_mouse_color_map(self, mice: list[str]) -> dict:
        n = len(mice)
        cmap = mpl.colormaps["tab10"] if n <= 10 else mpl.colormaps["tab20"]
        return {mid: tuple(int(255 * c) for c in cmap(i)[:3]) for i, mid in enumerate(mice)}

    def _build_flag_buttons(
        self,
        row_l: QHBoxLayout,
        *,
        status: str | None,
        on_ok_toggled,
        on_review_toggled,
    ) -> None:
        """Build the OK + Review pair for one legend row.

        Shared by ``_update_legend_group`` (group mode) and
        ``_update_legend_animal`` (animal mode). Click handlers are passed
        in as callables so the helper stays agnostic to which manifest
        method to invoke; each receives the button's new checked state
        (unchecking resets the animal to unreviewed).
        """
        btn_ok = QPushButton("OK")
        btn_ok.setFixedHeight(22)
        btn_ok.setCheckable(True)
        btn_ok.setChecked(status == "ok")
        btn_ok.clicked.connect(on_ok_toggled)
        row_l.addWidget(btn_ok)

        btn_review = QPushButton("Review")
        btn_review.setFixedHeight(22)
        btn_review.setCheckable(True)
        btn_review.setChecked(status == "needs_review")
        btn_review.clicked.connect(on_review_toggled)
        row_l.addWidget(btn_review)

    def _update_legend_group(
        self, mice: list[str], mouse_colors: dict, show_ref: bool = False
    ) -> None:
        self._clear_legend()
        spindle_outliers = self._get_spindle_outlier_animals()

        for i, mid in enumerate(mice):
            color = mouse_colors[mid]
            entry = self._manifest.get(mid)
            status = entry.sleep_qc if entry else None

            row_w, row_l = self._make_legend_row_frame(color, status)
            btn_highlight = QPushButton(str(mid))
            btn_highlight.setFlat(True)
            btn_highlight.setCheckable(True)
            btn_highlight.setChecked(mid == self._highlighted_animal)
            btn_highlight.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_highlight.setStyleSheet(
                "QPushButton { text-align: left; padding: 0 2px; font-weight: normal; }"
                "QPushButton:checked { font-weight: bold; text-decoration: underline; }"
            )
            btn_highlight.clicked.connect(
                lambda checked, m=mid: self._on_legend_highlight(m, checked)
            )
            row_l.addWidget(btn_highlight)
            if mid in spindle_outliers:
                outlier_lbl = QLabel(
                    '<span style="color:#c0392b;font-size:9px;font-style:italic;">[spindle outlier]</span>'
                )
                outlier_lbl.setTextFormat(Qt.TextFormat.RichText)
                row_l.addWidget(outlier_lbl)

            btn_notes = QPushButton("📝")
            btn_notes.setFixedHeight(24)
            btn_notes.setToolTip("Edit notes")
            btn_notes.clicked.connect(lambda _, a=mid: self._open_notes_dialog(a))
            row_l.addWidget(btn_notes)

            row_l.addStretch(1)
            self._build_flag_buttons(
                row_l,
                status=status,
                on_ok_toggled=(
                    lambda checked, m=mid: self._flag_sleep_qc(m, "ok" if checked else None)
                ),
                on_review_toggled=(
                    lambda checked, m=mid: self._flag_sleep_qc(
                        m, "needs_review" if checked else None
                    )
                ),
            )

            self.legend_layout.addWidget(row_w, i // 2, i % 2)

        if show_ref:
            n_rows = (len(mice) + 1) // 2
            ref_lbl = QLabel("─ ─  Group median, all animals")
            ref_lbl.setStyleSheet("color: #999;")
            self.legend_layout.addWidget(ref_lbl, n_rows, 0, 1, 2)

    def _update_legend_animal(self, show_ref: bool = False) -> None:
        self._clear_legend()
        animal = self.cmb_animal.currentText()
        if not animal:
            return
        entry = self._manifest.get(animal)
        status = entry.sleep_qc if entry else None

        row_w, row_l = self._make_legend_row_frame(self._ANIMAL_COLOR, status)

        label_text = animal
        if animal in self._get_spindle_outlier_animals():
            label_text += (
                ' <span style="color:#c0392b;font-size:9px;font-style:italic;">'
                "[spindle outlier]</span>"
            )
        animal_label = QLabel(label_text)
        animal_label.setTextFormat(Qt.TextFormat.RichText)
        row_l.addWidget(animal_label)

        btn_notes = QPushButton("📝")
        btn_notes.setFixedHeight(24)
        btn_notes.setToolTip("Edit notes")
        btn_notes.clicked.connect(lambda _, a=animal: self._open_notes_dialog(a))
        row_l.addWidget(btn_notes)

        # Stretch BEFORE action buttons so they right-align, matching
        # the group-mode legend.
        row_l.addStretch(1)

        self._build_flag_buttons(
            row_l,
            status=status,
            on_ok_toggled=lambda checked: self._flag_sleep_qc(animal, "ok" if checked else None),
            on_review_toggled=lambda checked: self._flag_sleep_qc(
                animal, "needs_review" if checked else None
            ),
        )
        self.legend_layout.addWidget(row_w, 0, 0)

        if show_ref:
            ref_lbl = QLabel("─ ─  Group median, all animals")
            ref_lbl.setStyleSheet("color: #999;")
            self.legend_layout.addWidget(ref_lbl, 1, 0, 1, 2)

    def _open_notes_dialog(self, animal_id: str) -> None:
        """Open the notes editor for an animal and persist any change."""
        entry = self._manifest.get(animal_id)
        initial = entry.notes if entry is not None else ""
        dlg = NotesDialog(animal_id=animal_id, initial_text=initial, parent=self)
        if not dlg.exec():
            return
        self._manifest.set_notes(animal_id, dlg.text())
        self.manifest_changed.emit()

    # ------------------------------------------------------------------
    # Manifest flagging
    # ------------------------------------------------------------------
    def _flag_sleep_qc(self, animal: str, status: str | None) -> None:
        """Set (or, with ``None``, reset) an animal's sleep QC flag and refresh the view."""
        if not animal or self._manifest.get(animal) is None:
            return
        if status is None:
            self._manifest.reset_sleep_qc(animal)
        else:
            self._manifest.flag_sleep_qc(animal, status)
        self.manifest_changed.emit()
        self._update_nav_hint()
        if self._mode == "group" and not self.btn_spindle.isChecked():
            mice = self._get_page_mice()
            self._update_legend_group(mice, self._build_mouse_color_map(mice), self._show_ref_median)
        else:
            self._update_all_plots()


# ---------------------------------------------------------------------------
# Spindle fraction chart
# ---------------------------------------------------------------------------


class SpindleFractionPlot(QWidget):
    """
    Box-and-strip chart showing per-animal spindle mask fraction, grouped by state.

    Each dot is one animal. Outliers (IQR × 1.5 rule) are labelled with their
    mouse_id. The current animal (if provided) is highlighted in blue.

    Clicking a dot selects it and shows an action strip with a "Flag for Review"
    button, so the user can act without leaving this view.
    ``review_requested(mouse_id)`` is emitted when that button is clicked.
    ``animal_clicked(mouse_id)`` is emitted to update the highlight in the chart.
    """

    animal_clicked = pyqtSignal(str)
    review_requested = pyqtSignal(str)

    STATE_ORDER = ["Wake", "NREM", "REM", "Total"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_animal: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._pw = pg.PlotWidget(background="w")
        self._pw.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        pi = self._pw.getPlotItem()
        pi.showGrid(x=False, y=True, alpha=0.3)
        pi.setLabel("left", "Fraction of state masked by spindles")
        pi.getAxis("left").enableAutoSIPrefix(False)
        pi.getAxis("bottom").setStyle(tickTextOffset=8)
        layout.addWidget(self._pw)

        # --- action strip (hidden until a dot is clicked) ---
        self._strip = QFrame()
        self._strip.setFrameShape(QFrame.Shape.StyledPanel)
        self._strip.setStyleSheet(
            "QFrame { background: #f0f4ff; border: 1px solid #b0c4f0; border-radius: 3px; }"
        )
        strip_row = QHBoxLayout(self._strip)
        strip_row.setContentsMargins(10, 4, 6, 4)
        strip_row.setSpacing(8)
        self._strip_lbl = QLabel()
        self._strip_lbl.setStyleSheet("font-weight: bold;")
        strip_row.addWidget(self._strip_lbl)
        strip_row.addStretch(1)
        self._btn_review = QPushButton("Flag for Review")
        self._btn_review.setFixedHeight(24)
        self._btn_review.clicked.connect(self._on_review_clicked)
        strip_row.addWidget(self._btn_review)
        btn_dismiss = QPushButton("×")
        btn_dismiss.setFixedSize(24, 24)
        btn_dismiss.setToolTip("Dismiss")
        btn_dismiss.clicked.connect(self._dismiss)
        strip_row.addWidget(btn_dismiss)
        self._strip.setVisible(False)
        layout.addWidget(self._strip)

    def set_data(
        self,
        df: pd.DataFrame | None,
        title: str = "",
        current_animal: str | None = None,
    ) -> None:
        pi = self._pw.getPlotItem()
        pi.clear()
        pi.setTitle(title, size="11pt")

        ax = pi.getAxis("bottom")
        ax.setTicks([[(i, s) for i, s in enumerate(self.STATE_ORDER)]])

        if df is None or df.empty:
            return

        rng = np.random.default_rng(42)
        box_w = 0.22
        cap_w = box_w * 0.55
        y_max = 0.0
        gray = pg.mkPen((60, 60, 60), width=1.2)
        thick = pg.mkPen((60, 60, 60), width=2.2)
        label_font = QFont()
        label_font.setPointSize(7)

        for xi, state in enumerate(self.STATE_ORDER):
            sdf = df[df["state"] == state].dropna(subset=["fraction"])
            if sdf.empty:
                continue

            fracs = sdf["fraction"].to_numpy(dtype=float)
            mids = sdf["mouse_id"].to_numpy()
            y_max = max(y_max, fracs.max())

            # Box-and-whisker math needs ≥2 points; with len 1 the IQR
            # collapses and `fracs[fracs >= lo_fence].min()` etc. are
            # fragile. Skip the box for tiny cohorts but still draw the
            # scatter point so a single-animal combo shows up.
            if len(fracs) >= 2:
                q1, med, q3 = np.percentile(fracs, [25, 50, 75])
                iqr = q3 - q1
                lo_fence = q1 - 1.5 * iqr
                hi_fence = q3 + 1.5 * iqr
                lo_wh = fracs[fracs >= lo_fence].min()
                hi_wh = fracs[fracs <= hi_fence].max()

                # IQR box
                pi.addItem(
                    pg.PlotCurveItem(
                        [xi - box_w, xi - box_w, xi + box_w, xi + box_w, xi - box_w],
                        [q1, q3, q3, q1, q1],
                        pen=gray,
                    )
                )
                # Median bar
                pi.addItem(pg.PlotCurveItem([xi - box_w, xi + box_w], [med, med], pen=thick))
                # Whiskers
                pi.addItem(pg.PlotCurveItem([xi, xi], [q1, lo_wh], pen=gray))
                pi.addItem(pg.PlotCurveItem([xi, xi], [q3, hi_wh], pen=gray))
                # Whisker caps
                pi.addItem(pg.PlotCurveItem([xi - cap_w, xi + cap_w], [lo_wh, lo_wh], pen=gray))
                pi.addItem(pg.PlotCurveItem([xi - cap_w, xi + cap_w], [hi_wh, hi_wh], pen=gray))

                is_out = (fracs < lo_fence) | (fracs > hi_fence)
            else:
                # Single-point group: no outlier classification possible.
                med = float(fracs[0])
                is_out = np.zeros(len(fracs), dtype=bool)

            # Scatter points (reproducible jitter)
            jitter = rng.uniform(-0.14, 0.14, len(fracs))
            xs = (xi + jitter).astype(float)

            is_current = mids == current_animal

            # Regular inlier points
            regular = ~is_out & ~is_current
            if regular.any():
                sc = pg.ScatterPlotItem(
                    xs[regular],
                    fracs[regular],
                    data=mids[regular],
                    pen=pg.mkPen(None),
                    brush=pg.mkBrush(110, 110, 110, 180),
                    size=7,
                )
                sc.sigClicked.connect(self._on_dot_clicked)
                pi.addItem(sc)

            # Outlier points + labels
            outl = is_out & ~is_current
            if outl.any():
                sc = pg.ScatterPlotItem(
                    xs[outl],
                    fracs[outl],
                    data=mids[outl],
                    pen=pg.mkPen(None),
                    brush=pg.mkBrush(210, 70, 50, 210),
                    size=7,
                )
                sc.sigClicked.connect(self._on_dot_clicked)
                pi.addItem(sc)
                for x_pt, y_pt, mid in zip(xs[outl], fracs[outl], mids[outl], strict=True):
                    anchor = (0.5, 1.2) if y_pt > med else (0.5, -0.2)
                    lbl = pg.TextItem(mid, anchor=anchor, color=(180, 40, 20))
                    lbl.setFont(label_font)
                    lbl.setPos(x_pt, y_pt)
                    pi.addItem(lbl)

            # Current-animal highlight
            if is_current.any():
                sc = pg.ScatterPlotItem(
                    xs[is_current],
                    fracs[is_current],
                    data=mids[is_current],
                    pen=pg.mkPen((30, 80, 200), width=1.5),
                    brush=pg.mkBrush(50, 110, 220, 220),
                    size=10,
                )
                sc.sigClicked.connect(self._on_dot_clicked)
                pi.addItem(sc)

        pi.setXRange(-0.6, len(self.STATE_ORDER) - 0.4)
        if y_max > 0:
            pi.setYRange(0, min(1.0, y_max * 1.15 + 0.01))
        else:
            pi.setYRange(0, 0.5)

    def _on_dot_clicked(self, item, spots, ev) -> None:
        if not spots:
            return
        mid = str(spots[0].data())
        self._selected_animal = mid
        self._strip_lbl.setText(f"Selected: {mid}")
        self._btn_review.setText("Flag for Review")
        self._btn_review.setEnabled(True)
        self._btn_review.setToolTip("")
        self._strip.setVisible(True)
        self.animal_clicked.emit(mid)

    def update_strip_status(self, status: str | None) -> None:
        """Update the action strip button based on the animal's current sleep_qc status."""
        if status == "needs_review":
            self._btn_review.setEnabled(False)
            self._btn_review.setText("Already flagged for review")
            self._btn_review.setToolTip("")
        else:
            self._btn_review.setEnabled(True)
            self._btn_review.setText("Flag for Review")
            self._btn_review.setToolTip("")

    def clear_selection(self) -> None:
        """Reset the action strip without emitting signals (for programmatic resets)."""
        self._selected_animal = None
        self._strip.setVisible(False)
        self._btn_review.setEnabled(True)

    def _on_review_clicked(self) -> None:
        if self._selected_animal:
            self.review_requested.emit(self._selected_animal)
            self._strip_lbl.setText(f"Flagged for review: {self._selected_animal}")
            self._btn_review.setEnabled(False)

    def _dismiss(self) -> None:
        self.clear_selection()
        self.animal_clicked.emit("")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vsep(parent: QWidget) -> QFrame:
    f = QFrame(parent)
    f.setFrameShape(QFrame.Shape.VLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


def _section_label(text: str) -> QLabel:
    """Small italic uppercase label that prefixes a toolbar cluster (Filter,
    View, etc.) so the controls within each cluster read as a group."""
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color: #888; font-size: 10px; font-style: italic; "
        "letter-spacing: 1px; padding-right: 2px;"
    )
    return lbl
