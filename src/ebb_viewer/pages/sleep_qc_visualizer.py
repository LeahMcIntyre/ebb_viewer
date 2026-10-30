"""Sleep QC visualizer page — flag and review per-animal sleep metrics.

Drives the post-spindle-upload review step: a 3×3 grid of plots (states ×
metrics) for batch comparison, plus an "Overview" of boxplots of the
flagging metrics (``ebb.process.sleep_flagging``) where animals past a
threshold are highlighted and can be flagged for review. Group mode shows
a page of animals; animal mode shows a single animal.

State of record: ``self._manifest`` (in-memory ``Manifest``, refreshed
on showEvent / poll / decisions) plus ``self._data`` (a tuple of four
dataframes for the project combo: bins, bins_offset, bins_clock,
flagging metrics).
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
from PyQt6.QtGui import QGuiApplication
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

from ebb.core.naming import parse_animal_id
from ebb.io.spindle_csv import FINAL_COLUMN, read_state_column
from ebb.process.sleep_compute import (
    compute_sleep_bins_df,
    compute_sleep_bins_df_clock_aligned,
    compute_sleep_bins_df_offset,
    compute_spindle_fractions,
    read_rawstate_column,
)
from ebb.process.sleep_flagging import METRIC_BY_KEY, flagged_metrics, metrics_table
from ebb_viewer.pipeline.manifest import (
    READY_STATUSES,
    STAGE_SLEEP_QC,
    Manifest,
    spindle_output_dir,
)
from ebb_viewer.pipeline.swd_review import swd_review_gaps
from ebb_viewer.pipeline.theme import STATUS_COLOR_HEX
from ebb_viewer.widgets.exclude_dialog import exclude_with_reason
from ebb_viewer.widgets.notes_dialog import NotesDialog
from ebb_viewer.widgets.page_help import title_row
from ebb_viewer.widgets.sleep_flag_overview import FlagOverview
from ebb_viewer.widgets.spindle_fraction_plot import SpindleFractionPlot
from ebb_viewer.widgets.worker_helpers import run_keeping_gui_alive

# Project recordings are all acquired in the Central time zone. Used by the
# offset variant of the sleep-bins computation so the next-`begin_hr`
# rotation honors DST transitions rather than drifting an hour across them.
_RECORDING_TZ = ZoneInfo("America/Chicago")


def overview_hint_text(manifest: Manifest) -> str:
    """Reminder that the Overview is not the review; empty once every animal has a decision."""
    animals = [e for e in manifest if e.has_spindle]
    todo = sum(1 for e in animals if e.sleep_qc not in READY_STATUSES)
    if not todo:
        return ""
    return (
        f"<b>{todo} of {len(animals)} animals still need a decision.</b> The Overview only "
        "highlights outliers. Open the <b>Sleep</b> view and go through every animal, "
        "marking each OK, Review or Exclude."
    )


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

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)

        # Cache: (df_start, df_rotate, df_clock, df_flags). df_flags holds the
        # flagging metrics (one row per animal). df_start has
        # bin_start_hr counted from sample 0; df_rotate is rotated so bin 0 lands
        # on begin_hr; df_clock places each animal's bins at their true clock
        # position. _axis_mode picks which one feeds _get_df.
        self._data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame] | None = None
        # (n_csvs, newest mtime) of the output folder when _data was loaded.
        self._data_sig: tuple[int, float] | None = None
        # Same four tables computed from each CSV's ``final_state`` column (written
        # by the Reclassify page). Built lazily the first time Reclassify is
        # switched on for a given CSV folder state, and dropped whenever _data
        # is reloaded.
        self._data_reclass: (
            tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame] | None
        ) = None
        # Animals whose CSV has a ``final_state`` column (the rest stay raw).
        self._reclassed: set[str] = set()
        # Reclassified (final_state) is the default view; the button shows the originals.
        self._show_original: bool = False
        self._axis_mode: str = "clock"
        self._mouse_ids: list[str] = []
        self._current_page: int = 0
        self._mode: str = "group"
        self._nav_hint_dest: str = ""
        # Animals flagged for review automatically (past a threshold) when the data loaded.
        self._auto_flagged: list[str] = []
        self._highlighted_animal: str | None = None
        self._show_ref_median: bool = False
        # Spindle-mask percentages per state, keyed by whether reclassified states are shown;
        # dropped whenever _data is reloaded.
        self._frac_cache: dict[bool, pd.DataFrame] = {}
        self._mask_selected: str | None = None

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
        self._update_swd_label()  # the first manifest load ran before the label existed

    @property
    def _combo(self) -> str:
        return self._manifest.combo

    def _refresh_manifest(self) -> None:
        """Reload the manifest from disk."""
        self._manifest = Manifest.load(self.project_root)
        self._update_swd_label()
        self._update_overview_hint()

    def _update_overview_hint(self) -> None:
        """Show the "go through every animal" reminder while the Overview is open."""
        frame = getattr(self, "_overview_hint", None)  # first call happens before the UI exists
        if frame is None:
            return
        self.lbl_overview_hint.setText(overview_hint_text(self._manifest))
        frame.setVisible(self.btn_overview.isChecked() and bool(self.lbl_overview_hint.text()))

    def _update_swd_label(self) -> None:
        """Note that SWD review is unfinished (no dialog: Sleep QC stays usable)."""
        label = getattr(self, "lbl_swd", None)  # first call happens before the UI exists
        if label is None:
            return
        gaps = swd_review_gaps(self.project_root, self._manifest)
        label.setVisible(bool(gaps))
        if gaps:
            parts = []
            if gaps.missing:
                parts.append(f"{len(gaps.missing)} without an SWD file")
            if gaps.unfinished:
                parts.append(f"{len(gaps.unfinished)} not finished")
            label.setText("SWD review incomplete: " + ", ".join(parts))
            tip = []
            if gaps.missing:
                tip.append("No SWD file: " + ", ".join(gaps.missing))
            if gaps.unfinished:
                tip.append("Not finished: " + ", ".join(gaps.unfinished))
            label.setToolTip("\n".join(tip))
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
        if self.btn_overview.isChecked():
            self._set_view("overview")
        elif self.btn_spindle.isChecked():
            self._set_view("mask")
        elif self._mode == "animal":
            self._refresh_animal_combo()
            self._update_all_plots()
        else:
            self._update_all_plots()

    def _update_auto_label(self) -> None:
        """Name the animals flagged automatically that are still waiting for a decision."""
        waiting = [
            a
            for a in self._auto_flagged
            if (entry := self._manifest.get(a)) is not None and entry.sleep_qc == "needs_review"
        ]
        if waiting:
            self.lbl_auto.setText(
                f"<b>Flagged for review automatically</b> (past a threshold): {', '.join(waiting)}. "
                "Click Review on an animal to clear its flag."
            )
        self.lbl_auto.setVisible(bool(waiting))

    def _auto_flag_for_review(self) -> None:
        """Flag undecided animals past a threshold for review (never touches a decision).

        Uses the reclassified states; without them (Reclassify not run) nothing is flagged,
        since the metrics would be the original SPINDLE ones.
        """
        if self._data_reclass is None:
            return
        table = self._data_reclass[3]
        if table is None or not set(self._manifest.flag_thresholds) <= set(table.columns):
            return
        flagged = self._flagged_animals(table)
        done = self._manifest.auto_flag_for_review(flagged)
        if done:
            self._auto_flagged = sorted(set(self._auto_flagged) | set(done))
            self.manifest_changed.emit()

    def _update_nav_hint(self) -> None:
        self._update_auto_label()
        entries = [e for e in self._manifest if e.has_spindle]
        if not entries:
            self._hint_frame.setVisible(False)
            return
        n_review = sum(1 for e in entries if e.sleep_qc == "needs_review")
        has_review = n_review > 0
        all_decided = all(e.sleep_qc in READY_STATUSES for e in entries)  # ok or excluded
        if has_review:
            self._hint_lbl.setText(
                f"{n_review} animal{'s' if n_review != 1 else ''} flagged for review. EDFs open "
                "from <b>Home</b>: use the open button on the animal's Needs Attention card, "
                "inspect the trace, then come back and mark it OK or Exclude."
            )
            self._hint_btn.setText("→ Home (open EDFs)")
            self._nav_hint_dest = "home"
            self._hint_frame.setStyleSheet(
                "QFrame { background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; }"
            )
            self._hint_frame.setVisible(True)
        elif all_decided:
            n_excluded = sum(1 for e in entries if e.sleep_qc == "excluded")
            excluded = f" ({n_excluded} excluded)" if n_excluded else ""
            self._hint_lbl.setText(
                f"✓ All spindle metrics checked{excluded} — ready for PSD computation."
            )
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

        lbl = title_row("Sleep Quality Check Visualizer", "sleep_qc")
        desc = QLabel(
            "Review sleep staging results for each animal. "
            "Flag animals as ok or needs review based on sleep metrics and the fraction of each state masked by artifact."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(lbl)
        layout.addWidget(desc)

        self.lbl_auto = QLabel()
        self.lbl_auto.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_auto.setWordWrap(True)
        self.lbl_auto.setStyleSheet("color: #b02a2a; font-size: 11px;")
        self.lbl_auto.setVisible(False)
        layout.addWidget(self.lbl_auto)

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

        # Reclassify status sits left of the VIEW cluster so its changing width
        # is absorbed by the stretch above rather than shifting the buttons.
        self.lbl_reclass = QLabel("")
        self.lbl_reclass.setStyleSheet("color: gray;")
        self.lbl_reclass.setVisible(False)
        top.addWidget(self.lbl_reclass)
        # Shown only while SWD review is on but unfinished (reclassified states are still valid).
        self.lbl_swd = QLabel("")
        self.lbl_swd.setStyleSheet("color: #d97706;")
        self.lbl_swd.setVisible(False)
        top.addWidget(self.lbl_swd)
        top.addSpacing(12)

        # VIEW cluster — same flush-pair treatment as Group/Animal.
        top.addWidget(_section_label("VIEW"))
        self.btn_overview = QPushButton("Overview")
        self.btn_overview.setCheckable(True)
        self.btn_overview.setChecked(True)
        self.btn_view_sleep = QPushButton("Sleep")
        self.btn_view_sleep.setCheckable(True)
        self.btn_view_sleep.setChecked(False)
        self.btn_spindle = QPushButton("Spindle mask")
        self.btn_spindle.setCheckable(True)
        self.btn_spindle.setChecked(False)
        self.btn_spindle.setToolTip(
            "Percent of each state (and the total) masked as spindle artifact, per file"
        )
        view_row = QHBoxLayout()
        view_row.setContentsMargins(0, 0, 0, 0)
        view_row.setSpacing(0)
        view_row.addWidget(self.btn_overview)
        view_row.addWidget(self.btn_view_sleep)
        view_row.addWidget(self.btn_spindle)
        view_wrap = QWidget()
        view_wrap.setLayout(view_row)
        top.addWidget(view_wrap)

        top.addSpacing(8)
        self.btn_original = QPushButton("Show original")
        self.btn_original.setCheckable(True)
        self.btn_original.setChecked(False)
        self.btn_original.setToolTip(
            "Plot the original SPINDLE states in both views instead of the reclassified "
            "states (the final_state column written by the Reclassify step). "
            "Nothing is written to disk."
        )
        top.addWidget(self.btn_original)

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
        # Floor so the plots stay legible; below this the page scrolls
        # (MainWindow wraps every page in a QScrollArea).
        self.grid.setMinimumSize(560, 420)

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

        # Overview only highlights outliers; every animal still needs a decision in the Sleep view.
        self._overview_hint = QFrame()
        self._overview_hint.setStyleSheet(
            "QFrame { background: #e8f0fb; border: 1px solid #1a5fa8; border-radius: 4px; }"
        )
        hint_row = QHBoxLayout(self._overview_hint)
        hint_row.setContentsMargins(8, 4, 8, 4)
        self.lbl_overview_hint = QLabel("")
        self.lbl_overview_hint.setWordWrap(True)
        self.lbl_overview_hint.setStyleSheet("border: none;")
        hint_row.addWidget(self.lbl_overview_hint, 1)
        btn_hint_sleep = QPushButton("Open Sleep view →")
        btn_hint_sleep.clicked.connect(lambda: self._set_view("sleep"))
        hint_row.addWidget(btn_hint_sleep)
        layout.addWidget(self._overview_hint)
        self._update_overview_hint()

        self._overview = FlagOverview()
        self._overview.setMinimumSize(560, 300)
        layout.addWidget(self._overview, stretch=1)

        self._frac_widget = SpindleFractionPlot()
        self._frac_widget.setMinimumSize(560, 300)
        self._frac_widget.setVisible(False)
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
        self._hint_lbl.setWordWrap(True)
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
        self.btn_view_sleep.clicked.connect(lambda: self._set_view("sleep"))
        self.btn_overview.clicked.connect(lambda: self._set_view("overview"))
        self.btn_spindle.clicked.connect(lambda: self._set_view("mask"))
        self._frac_widget.animal_clicked.connect(self._on_mask_animal_selected)
        self.btn_original.toggled.connect(self._on_original_toggled)
        self._overview.animal_clicked.connect(self._on_overview_animal_selected)
        self._overview.flag_requested.connect(self._on_overview_flag_requested)

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

        if self.btn_view_sleep.isChecked():
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

    def _set_view(self, view: str) -> None:
        """Show one of the three views: ``"overview"``, ``"sleep"`` or ``"mask"``."""
        sleep = view == "sleep"
        self.btn_overview.setChecked(view == "overview")
        self.btn_view_sleep.setChecked(sleep)
        self.btn_spindle.setChecked(view == "mask")
        self.grid.setVisible(sleep)
        self._overview.setVisible(view == "overview")
        self._frac_widget.setVisible(view == "mask")
        self._update_overview_hint()
        self._sleep_mode_controls.setVisible(sleep)
        self._legend_scroll.setVisible(sleep)
        if sleep:
            self._set_mode(self._mode)
            return
        self._group_controls.setVisible(False)
        self._animal_controls.setVisible(False)
        if view == "overview":
            self._refresh_overview()
        else:
            self._refresh_mask_view()

    def _get_frac_df(self) -> pd.DataFrame | None:
        """Spindle-mask fraction per animal and state, for the states currently shown."""
        d = self._csv_dir()
        if self._data is None or not d.is_dir():
            return None
        reclass = self._reclass_active
        if reclass not in self._frac_cache:
            states: dict[str, list[str]] = {}
            for path in sorted(d.glob("*.csv")):
                animal = parse_animal_id(path)
                if reclass and animal in self._reclassed:
                    states[animal] = read_state_column(path, FINAL_COLUMN)
                else:
                    states[animal] = read_rawstate_column(path)
            try:
                self._frac_cache[reclass] = compute_spindle_fractions(d, states_by_animal=states)
            except Exception as e:
                QMessageBox.critical(
                    self, "Error computing spindle mask", f"Could not read {self._combo}:\n{e}"
                )
                return None
        return self._frac_cache[reclass]

    def _refresh_mask_view(self) -> None:
        title = f"{self._combo} ({'reclassified' if self._reclass_active else 'original'})"
        gated = self._gated_animals()
        if gated:
            title += f" - orange ring = EMG gate applied ({len(gated)})"
        self._frac_widget.set_data(
            self._get_frac_df(), title=title, selected=self._mask_selected, gated=gated
        )

    def _on_mask_animal_selected(self, animal: str) -> None:
        """Dot clicked or dismissed: redraw so the selection is highlighted."""
        self._mask_selected = animal or None
        self._refresh_mask_view()

    def _refresh_overview(self, selected: str | None = None) -> None:
        """Redraw the boxplots from the cached flagging metrics."""
        statuses = {e.animal_id: e.sleep_qc for e in self._manifest}
        self._update_overview_hint()
        self._overview.set_data(
            self._get_flag_table(),
            self._manifest.flag_thresholds,
            statuses,
            selected=selected,
        )

    def _on_overview_animal_selected(self, animal: str) -> None:
        """Dot clicked or dismissed: redraw so the selection is highlighted."""
        self._refresh_overview(selected=animal or None)

    def _on_overview_flag_requested(self, animal: str) -> None:
        """Flag the selected animal for review from the overview."""
        self._flag_sleep_qc(animal, "needs_review")

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
        self._ensure_reclass()
        self._auto_flag_for_review()
        self.btn_original.setEnabled(self._data_reclass is not None)
        self._update_reclass_label()
        return True

    def _compute_tables(
        self, d: Path, states_by_animal, *, record_skips: bool = False
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """The sleep-bin tables and the flagging metrics for the CSV folder ``d``. ``states_by_animal`` must
        cover every CSV: the compute functions default to ``final_state`` and raise
        for animals that lack it, so this page always passes states explicitly."""
        std = self.project_root / "standard"

        def compute():
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", UserWarning)
                tables = (
                    compute_sleep_bins_df(d, states_by_animal=states_by_animal),
                    compute_sleep_bins_df_offset(
                        d, std, tz=_RECORDING_TZ, states_by_animal=states_by_animal
                    ),
                    compute_sleep_bins_df_clock_aligned(
                        d, std, tz=_RECORDING_TZ, states_by_animal=states_by_animal
                    ),
                    metrics_table(d, std, states_by_animal=states_by_animal),
                )
            return tables, caught

        tables, caught = run_keeping_gui_alive("Computing sleep metrics…", compute)
        if record_skips:  # same skips either way; report them once
            self._record_skip_warnings(caught)
        return tables

    def _load_data(self, sig: tuple[int, float]) -> None:
        """Compute and cache the sleep metrics for the project combo."""
        self._data = None
        self._data_reclass = None
        self._frac_cache = {}
        self._reclassed = set()
        self._mouse_ids = []
        self._data_sig = sig
        d = self._csv_dir()
        if not d.is_dir():
            return
        try:
            originals = {parse_animal_id(p): read_rawstate_column(p) for p in sorted(d.glob("*.csv"))}
            self._data = self._compute_tables(d, originals, record_skips=True)
        except Exception as e:
            QMessageBox.critical(
                self, "Error loading sleep metrics", f"Could not load {self._combo}:\n{e}"
            )
            return
        self._mouse_ids = sorted(self._data[0]["mouse_id"].unique())

    # ------------------------------------------------------------------
    # NREM reclassification
    # ------------------------------------------------------------------
    @property
    def _reclass_active(self) -> bool:
        return not self._show_original and self._data_reclass is not None

    def _ensure_reclass(self) -> bool:
        """Build the reclassified tables if missing. Returns True when available."""
        if self._data_reclass is not None:
            return True
        d = self._csv_dir()
        if self._data is None or not d.is_dir():
            return False
        # Every CSV is passed explicitly: final_state where present, else the original
        # states (those animals are counted as "not reclassified" in the label).
        states: dict[str, list[str]] = {}
        reclassed: set[str] = set()
        for path in sorted(d.glob("*.csv")):
            animal = parse_animal_id(path)
            try:
                states[animal] = read_state_column(path, FINAL_COLUMN)
                reclassed.add(animal)
            except ValueError:
                states[animal] = read_rawstate_column(path)
        if not reclassed:
            return False  # nothing reclassified: stay on the original states (label says so)
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            tables = self._compute_tables(d, states)
        except Exception as e:
            QMessageBox.critical(
                self, "Error loading reclassified states", f"Could not read {self._combo}:\n{e}"
            )
            return False
        finally:
            QGuiApplication.restoreOverrideCursor()
        self._reclassed = reclassed
        self._data_reclass = tables
        return True

    def _gated_animals(self) -> set[str]:
        """Animals whose reclassification applied the EMG gate (empty unless Reclassify is on)."""
        if not self._reclass_active:
            return set()
        return {
            a for a in self._reclassed if (e := self._manifest.get(a)) and e.reclass_gate_applied
        }

    def _gate_tag_html(self, animal: str) -> str:
        """Legend tag for an animal the EMG gate was applied to, else ''."""
        if animal not in self._gated_animals():
            return ""
        return (
            '<span style="color:#d97706;font-size:9px;font-style:italic;" '
            'title="Gap fill fragmented NREM, so flips were EMG-gated">[EMG gate]</span>'
        )

    def _update_reclass_label(self) -> None:
        """Say which states are plotted; loud when the Reclassify step hasn't been run."""
        if self._data is None:
            self.lbl_reclass.setVisible(False)
            return
        if self._data_reclass is None:
            text = "Not reclassified (run the Reclassify step); showing original states"
            self.lbl_reclass.setStyleSheet("color: #d97706; font-weight: bold;")
            self.lbl_reclass.setText(text)
            self.lbl_reclass.setToolTip("")
            self.lbl_reclass.setVisible(True)
            return
        self.lbl_reclass.setStyleSheet("color: gray;")
        if self._show_original:
            self.lbl_reclass.setText("Showing original SPINDLE states")
            self.lbl_reclass.setToolTip("")
            self.lbl_reclass.setVisible(True)
            return
        gated = sorted(self._gated_animals())
        missing = len(self._mouse_ids) - len(self._reclassed)
        text = f"EMG gate on {len(gated)} of {len(self._reclassed)} reclassified files"
        if missing:
            text += f"; {missing} not reclassified (run Reclassify), kept original"
        self.lbl_reclass.setText(text)
        self.lbl_reclass.setToolTip("EMG gate applied to: " + (", ".join(gated) or "none"))
        self.lbl_reclass.setVisible(True)

    def _on_original_toggled(self, checked: bool) -> None:
        self._show_original = checked
        self._update_reclass_label()
        self._refresh_views()

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
        data = self._active_data()
        if data is None:
            return None
        df_start, df_rotate, df_clock, _flags = data
        return {"start": df_start, "rotate": df_rotate, "clock": df_clock}[self._axis_mode]

    def _get_flag_table(self) -> pd.DataFrame | None:
        data = self._active_data()
        return data[3] if data is not None else None

    def _active_data(self):
        """The raw tables, or the reclassified ones while Reclassify is on."""
        return self._data_reclass if self._reclass_active else self._data

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

    def _flagged_animals(self, table: pd.DataFrame | None = None) -> dict[str, list[str]]:
        """``{animal: [metric keys past a threshold]}`` for the active states (or ``table``)."""
        table = self._get_flag_table() if table is None else table
        if table is None:
            return {}
        thresholds = self._manifest.flag_thresholds
        out = {}
        for animal, row in table.iterrows():
            keys = flagged_metrics(row.to_dict(), thresholds)
            if keys:
                out[str(animal)] = keys
        return out

    _TAG_MAX_NAMES = 2

    def _flag_tag_html(self, animal: str) -> str:
        """Short red legend tag for the metrics past a threshold ('' if none).

        Names at most ``_TAG_MAX_NAMES`` metrics, then ``+N``; ``_flag_tooltip`` has the detail.
        """
        keys = self._flagged_animals().get(animal)
        if not keys:
            return ""
        names = [METRIC_BY_KEY[k].short for k in keys[: self._TAG_MAX_NAMES]]
        extra = len(keys) - self._TAG_MAX_NAMES
        text = ", ".join(names) + (f" +{extra}" if extra > 0 else "")
        return f'<span style="color:#c0392b;font-size:9px;font-style:italic;">[{text}]</span>'

    def _flag_tooltip(self, animal: str) -> str:
        """One line per metric past a threshold: full name, value and threshold."""
        table = self._get_flag_table()
        keys = self._flagged_animals().get(animal, [])
        if table is None or not keys:
            return ""
        thresholds = self._manifest.flag_thresholds
        return "\n".join(
            f"{METRIC_BY_KEY[k].label}: {table.loc[animal, k]:.1f} "
            f"({METRIC_BY_KEY[k].direction} {thresholds[k]:g})"
            for k in keys
        )

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
        if self.btn_overview.isChecked():
            self._refresh_overview(selected=self._overview.selected)
            return
        if self.btn_spindle.isChecked():
            self._refresh_mask_view()
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
                    entry = self._manifest.get(mid)
                    if entry is not None and entry.sleep_qc == "excluded":
                        alpha = 50  # greyed out
                    elif self._highlighted_animal:
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
        text = "color: #8a8a8a;" if status == "excluded" else ""
        row_w.setStyleSheet(
            f"QWidget#legendRow {{ background-color: {bg or 'transparent'}; border-radius: 3px; {text} }}"
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
        on_exclude_toggled,
    ) -> None:
        """Build the OK + Review + Exclude buttons for one legend row.

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

        btn_exclude = QPushButton("Exclude")
        btn_exclude.setFixedHeight(22)
        btn_exclude.setCheckable(True)
        btn_exclude.setChecked(status == "excluded")
        btn_exclude.setToolTip("Exclude this animal from analysis (a reason is required)")
        btn_exclude.clicked.connect(on_exclude_toggled)
        row_l.addWidget(btn_exclude)

    def _update_legend_group(
        self, mice: list[str], mouse_colors: dict, show_ref: bool = False
    ) -> None:
        self._clear_legend()

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
            flag_tag = self._flag_tag_html(mid)
            if flag_tag:
                flag_lbl = QLabel(flag_tag)
                flag_lbl.setTextFormat(Qt.TextFormat.RichText)
                flag_lbl.setToolTip(self._flag_tooltip(mid))
                row_l.addWidget(flag_lbl)
            gate_tag = self._gate_tag_html(mid)
            if gate_tag:
                gate_lbl = QLabel(gate_tag)
                gate_lbl.setTextFormat(Qt.TextFormat.RichText)
                row_l.addWidget(gate_lbl)

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
                on_exclude_toggled=lambda checked, m=mid: self._exclude_sleep_qc(m, checked),
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
        flag_tag = self._flag_tag_html(animal)
        if flag_tag:
            label_text += " " + flag_tag
        gate_tag = self._gate_tag_html(animal)
        if gate_tag:
            label_text += " " + gate_tag
        animal_label = QLabel(label_text)
        animal_label.setTextFormat(Qt.TextFormat.RichText)
        animal_label.setToolTip(self._flag_tooltip(animal))
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
            on_exclude_toggled=lambda checked: self._exclude_sleep_qc(animal, checked),
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
    def _exclude_sleep_qc(self, animal: str, excluded: bool) -> None:
        """Exclude ``animal`` (asking for a reason) or, when un-excluding, send it back to review."""
        if not animal or self._manifest.get(animal) is None:
            return
        if excluded:
            if not exclude_with_reason(self, self._manifest, animal, STAGE_SLEEP_QC):
                self._refresh_legend()  # cancelled: pop the toggle back out
                return
            self.manifest_changed.emit()
            self._update_nav_hint()
            self._refresh_legend()
        else:
            self._flag_sleep_qc(animal, "needs_review")

    def _refresh_legend(self) -> None:
        if self._mode == "group" and self.btn_view_sleep.isChecked():
            mice = self._get_page_mice()
            self._update_legend_group(mice, self._build_mouse_color_map(mice), self._show_ref_median)
        else:
            self._update_all_plots()

    def _flag_sleep_qc(self, animal: str, status: str | None) -> None:
        """Set (or, with ``None``, reset) an animal's sleep QC flag and refresh the view."""
        if not animal or self._manifest.get(animal) is None:
            return
        if status is None:
            self._manifest.reset_sleep_qc(animal)
        else:
            reasons = self._flagged_keys(animal) if status == "needs_review" else None
            self._manifest.flag_sleep_qc(animal, status, reasons)
        self.manifest_changed.emit()
        self._update_nav_hint()
        self._refresh_legend()

    def _flagged_keys(self, animal: str) -> list[str]:
        """Metric keys currently past their threshold for ``animal`` (empty without metrics)."""
        table = self._get_flag_table()
        if table is None or animal not in table.index:
            return []
        return flagged_metrics(table.loc[animal].to_dict(), self._manifest.flag_thresholds)


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
