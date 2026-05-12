"""Sleep QC visualizer page — review per-animal sleep metrics + spindle masks.

Drives the post-spindle-upload review step: a 3×3 grid of plots (states ×
metrics) for batch comparison, plus a "Spindle Mask" box-and-strip view
for masking-fraction outlier detection. Group mode shows a page of
animals for one combo; animal mode overlays all combos for a single
animal. Review mode (entered from the reruns-ready badge) filters the
animal dropdown to pending-rerun candidates and surfaces the
accept/review decision panel.

State of record: ``self._manifest`` (in-memory ``Manifest``, refreshed
on showEvent / poll / decisions) plus ``self._data_cache`` keyed by combo
(a triple of dataframes: bins, bins_offset, spindle_fractions).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
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
    compute_sleep_bins_df_offset,
    compute_spindle_fractions,
)
from ebb_viewer.pipeline.manifest import Manifest, spindle_output_dir
from ebb_viewer.pipeline.theme import COMBO_PLOT_RGB, STATUS_COLOR_HEX


class SleepQCGridPage(QWidget):
    """
    QC page: 3×3 grid (states × metrics).

    Group mode: shows up to MICE_PER_PAGE animals for one channel combo at a time,
    with optional mean ± SD reference band.

    Animal mode: shows all available channel combos overlaid for one selected animal.
    Includes a dashed group-mean reference line for the most prevalent "ok" combo.
    Animals with at least one unreviewed run appear first in the dropdown.

    Review mode: entered by clicking the "● N reruns ready" badge. Filters the animal
    dropdown to only animals with pending rerun decisions and shows a decision panel
    (Accept Rerun / Accept Original / Review) below the plots.
    """

    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)

    STATE_ORDER = ["w", "n", "r"]
    STATE_DEF = {"w": "Wake", "n": "NREM", "r": "REM"}
    METRIC_ORDER = [
        ("frac_time", "Fraction of time"),
        ("n_bouts", "# bouts"),
        ("mean_bout_sec", "Mean bout duration (s)"),
    ]

    MICE_PER_PAGE = 10

    # Status button background colors — "needs_rerun" is intentionally orange
    # here (not red) because these are legend buttons, not table-row alerts.
    _STATUS_BG = {
        **STATUS_COLOR_HEX,
        "needs_rerun": "#fde8ce",  # orange for legend buttons (override red)
        "rejected": "#e8e8e8",
    }

    _COMBO_COLORS = COMBO_PLOT_RGB

    # Sentinel for ``_refresh_frac_plot``'s optional-but-distinct-from-None
    # ``current_animal`` arg: "read from combo box" vs "clear to None".
    _DEFAULT_ANIMAL = object()

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)

        self._available_combos: list[str] = []
        self._data_cache: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}
        self._mouse_ids: list[str] = []
        self._current_page: int = 0
        self._mode: str = "group"
        self._review_mode: bool = False
        self._nav_hint_dest: str = ""
        self._highlighted_animal: str | None = None
        self._show_ref_median: bool = False
        self._pending_rerun_ids: set[str] = set()

        self._plots: dict[tuple[str, str], pg.PlotItem] = {}

        self._refresh_manifest()

        self._build_ui()
        self._wire()

    def _refresh_manifest(self) -> None:
        """Reload the manifest from disk and cache the pending-rerun set.

        ``_pending_rerun_ids`` is the hot lookup used by ``_has_pending_rerun``
        (called per animal in the dropdown sync path); caching it once per
        manifest load avoids one ``glob()`` call per dropdown entry per
        navigation event.
        """
        self._manifest = Manifest.load(self.project_root)
        self._pending_rerun_ids = {
            entry.animal_id for entry, _ in self._manifest.pending_rerun_review()
        }

    def _poll(self):
        """Lightweight background refresh: reload manifest and update the reruns badge."""
        self._refresh_manifest()
        # In review mode the user is actively navigating between animals using the
        # cached combo data. Evicting mid-review would cause combos to disappear for
        # the next animal without being reloaded.  Skip eviction here; the cache is
        # fully refreshed when the user exits and re-enters review mode.
        if not self._review_mode:
            for _, combo in self._manifest.pending_rerun_review():
                self._data_cache.pop(combo, None)
        # Refresh the combo dropdown if new spindle_outputs directories have appeared
        # (e.g. a download completed while this page was already visible).
        if self._discover_combos() != self._available_combos:
            self._refresh_combos()
        self._update_reruns_badge()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_manifest()
        # Evict any cached combo that has a pending rerun — new files may have been
        # downloaded since the last time this combo was loaded.
        for _, combo in self._manifest.pending_rerun_review():
            self._data_cache.pop(combo, None)
        self._highlighted_animal = None
        self._update_reruns_badge()
        self._refresh_combos()
        if self.btn_spindle.isChecked():
            self._set_spindle_mask_mode(True)
        elif self._mode == "animal":
            self._ensure_all_combos_loaded()
            self._refresh_animal_combo()
            self._update_all_plots()

    def _update_reruns_badge(self) -> None:
        pending = self._manifest.pending_rerun_review()
        n = len(pending)
        if self._review_mode:
            self.btn_reruns_ready.setText(f"✕ Exit Review  ({n} remaining)")
            self.btn_reruns_ready.setVisible(True)
            self._lbl_filter.setText(f"(filtered: {n} pending)")
        elif n > 0:
            self.btn_reruns_ready.setText(f"● {n} rerun{'s' if n != 1 else ''} ready for review  →")
            self.btn_reruns_ready.setVisible(True)
        else:
            self.btn_reruns_ready.setVisible(False)
        self._update_nav_hint()

    def _update_nav_hint(self) -> None:
        if self._review_mode:
            self._hint_frame.setVisible(False)
            return
        entries = [e for e in self._manifest if e.runs]
        if not entries:
            self._hint_frame.setVisible(False)
            return
        has_review = any(run.sleep_qc == "needs_review" for e in entries for run in e.runs.values())
        all_have_ok = all(any(run.sleep_qc == "ok" for run in e.runs.values()) for e in entries)
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
            "Review sleep staging results for each animal and channel combination. "
            "Flag animals as ok, needs review, or needs rerun based on sleep metrics and the fraction of each state masked by artifact. "
            "Animals flagged for rerun can be reprocessed with a different channel combination from the Rerun Queue."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(lbl)
        layout.addWidget(desc)

        # --- top bar ---
        top = QHBoxLayout()

        top.addWidget(QLabel("Combo:"))
        self.cmb_combo = QComboBox()
        self.cmb_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.cmb_combo.setMinimumWidth(100)
        top.addWidget(self.cmb_combo)

        self._sleep_mode_controls = QWidget()
        smc = QHBoxLayout(self._sleep_mode_controls)
        smc.setContentsMargins(0, 0, 0, 0)
        smc.setSpacing(top.spacing())

        smc.addWidget(_vsep(self))

        self.btn_group = QPushButton("Group")
        self.btn_group.setCheckable(True)
        self.btn_group.setChecked(True)
        self.btn_animal = QPushButton("Animal")
        self.btn_animal.setCheckable(True)
        smc.addWidget(self.btn_group)
        smc.addWidget(self.btn_animal)

        smc.addWidget(_vsep(self))

        self.btn_offset = QPushButton("6AM Start")
        self.btn_offset.setCheckable(True)
        self.btn_offset.setChecked(True)
        smc.addWidget(self.btn_offset)

        smc.addWidget(_vsep(self))

        self.btn_median = QPushButton("Median")
        self.btn_median.setCheckable(True)
        self.btn_median.setChecked(False)
        smc.addWidget(self.btn_median)

        self._sleep_mode_controls.setVisible(False)
        top.addWidget(self._sleep_mode_controls)
        top.addStretch(1)

        # --- view toggle (right-aligned) ---
        top.addWidget(_vsep(self))
        self.btn_spindle = QPushButton("Spindle Mask")
        self.btn_spindle.setCheckable(True)
        self.btn_spindle.setChecked(True)
        self.btn_view_sleep = QPushButton("Sleep")
        self.btn_view_sleep.setCheckable(True)
        self.btn_view_sleep.setChecked(False)
        top.addWidget(self.btn_spindle)
        top.addWidget(self.btn_view_sleep)

        top.addWidget(_vsep(self))

        self.btn_reruns_ready = QPushButton()
        self.btn_reruns_ready.setCheckable(True)
        self.btn_reruns_ready.setStyleSheet(
            "color: #c96a00; font-weight: bold; border: none; padding: 0;"
        )
        self.btn_reruns_ready.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reruns_ready.setVisible(False)
        top.addWidget(self.btn_reruns_ready)

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
        self._lbl_filter = QLabel("")
        self._lbl_filter.setStyleSheet("color: #666; font-style: italic;")
        self._lbl_filter.setVisible(False)
        ac.addWidget(self._lbl_filter)
        self.btn_prev_animal = QPushButton("◄ Prev")
        self.btn_next_animal = QPushButton("Next ►")
        self.btn_next_rerun = QPushButton("Next Rerun ►")
        self.btn_next_rerun.setEnabled(False)
        ac.addWidget(self.btn_prev_animal)
        ac.addWidget(self.btn_next_animal)
        ac.addWidget(self.btn_next_rerun)
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

        # Navigation hint (hidden until all animals in combo are reviewed)
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
        self.cmb_combo.currentTextChanged.connect(self._on_combo_changed)
        self.btn_group.clicked.connect(lambda: self._set_mode("group"))
        self.btn_animal.clicked.connect(lambda: self._set_mode("animal"))
        self.btn_offset.toggled.connect(self._update_all_plots)
        self.btn_median.toggled.connect(self._on_median_toggled)
        self.btn_view_sleep.clicked.connect(lambda: self._set_spindle_mask_mode(False))
        self.btn_spindle.clicked.connect(lambda: self._set_spindle_mask_mode(True))
        self._frac_widget.animal_clicked.connect(self._on_frac_animal_selected)
        self._frac_widget.review_requested.connect(self._on_frac_review_requested)

        self.btn_prev.clicked.connect(self._on_prev_page)
        self.btn_next.clicked.connect(self._on_next_page)
        self.spin_page.valueChanged.connect(self._on_page_spin_changed)

        self.btn_reruns_ready.toggled.connect(self._on_review_mode_toggled)
        self._hint_btn.clicked.connect(self._go_nav_hint)

        self.cmb_animal.currentTextChanged.connect(self._on_animal_changed)
        self.btn_prev_animal.clicked.connect(self._on_prev_animal)
        self.btn_next_animal.clicked.connect(self._on_next_animal)
        self.btn_next_rerun.clicked.connect(self._on_next_rerun)

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------
    def _set_mode(self, mode: str) -> None:
        if self._review_mode and mode != "animal":
            return  # review mode forces animal mode
        self._mode = mode
        is_group = mode == "group"
        self.btn_group.setChecked(is_group)
        self.btn_animal.setChecked(not is_group)

        if not self.btn_spindle.isChecked():
            self.cmb_combo.setEnabled(is_group)
            self._group_controls.setVisible(is_group)
            self._animal_controls.setVisible(not is_group)

        if not is_group:
            self._ensure_all_combos_loaded()
            self._refresh_animal_combo()

        self._update_all_plots()

    def _set_spindle_mask_mode(self, spindle: bool) -> None:
        self.btn_view_sleep.setChecked(not spindle)
        self.btn_spindle.setChecked(spindle)
        self.grid.setVisible(not spindle)
        self._frac_widget.setVisible(spindle)
        self._sleep_mode_controls.setVisible(not spindle)
        self._legend_scroll.setVisible(not spindle)
        if spindle:
            self.cmb_combo.setEnabled(True)
            self._group_controls.setVisible(False)
            self._animal_controls.setVisible(True)
            self._lbl_animal.setText("Highlight:")
            self._ensure_all_combos_loaded()
            self._refresh_animal_combo()
            self._frac_widget.clear_selection()
            self._refresh_frac_plot()
            self._render_group()
        else:
            if self._review_mode:
                self._lbl_animal.setText("Animal (review):")
            else:
                self._lbl_animal.setText("Animal:")
            self._set_mode(self._mode)

    def _refresh_frac_plot(self, current_animal: str | None = _DEFAULT_ANIMAL) -> None:
        combo = self.cmb_combo.currentText()
        df_frac = self._get_frac_df(combo)
        if current_animal is self._DEFAULT_ANIMAL:
            current_animal = self.cmb_animal.currentText() or None
        self._frac_widget.set_data(df_frac, title=combo, current_animal=current_animal)

    def _on_frac_animal_selected(self, mouse_id: str) -> None:
        """Dot clicked or dismissed — update the highlight without leaving the spindle mask view."""
        if mouse_id:
            self.cmb_animal.setCurrentText(
                mouse_id
            )  # triggers _on_animal_changed → _refresh_frac_plot
            combo = self.cmb_combo.currentText()
            run = self._manifest.get_run(mouse_id, combo)
            status = run.sleep_qc if run else None
            self._frac_widget.update_strip_status(status)
        else:
            self._refresh_frac_plot(current_animal=None)  # clear highlight

    def _on_frac_review_requested(self, mouse_id: str) -> None:
        """Flag the selected animal for review from within the spindle mask view."""
        combo = self.cmb_combo.currentText()
        run = self._manifest.get_run(mouse_id, combo)
        if run and run.sleep_qc == "needs_rerun":
            return  # rerun takes priority; button should already be disabled
        self._flag_sleep_qc(mouse_id, "needs_review")

    def _on_review_mode_toggled(self, checked: bool) -> None:
        if checked:
            self._enter_review_mode()
        else:
            self._exit_review_mode()

    def _enter_review_mode(self) -> None:
        """Enter review mode if there are pending reruns; otherwise no-op.

        Pre-check the pending-reruns count before mutating any UI state.
        Pre-fix this method changed the background, labels, and filter
        visibility, then discovered the dropdown was empty and rolled back
        the boolean — leaving the page in a visually inconsistent half-
        review state.
        """
        self._refresh_manifest()
        if not self._pending_rerun_ids:
            # Nothing to review; bounce the toggle without mutating UI.
            self.btn_reruns_ready.blockSignals(True)
            self.btn_reruns_ready.setChecked(False)
            self.btn_reruns_ready.blockSignals(False)
            QMessageBox.information(
                self, "No Pending Reruns", "No animals have pending rerun decisions."
            )
            return

        self._review_mode = True
        self.btn_group.setEnabled(False)
        self.setStyleSheet("#sleepQcPage { background: #f0f4ff; }")
        self._lbl_animal.setText("Animal (review):")
        self._lbl_filter.setVisible(True)
        self._update_reruns_badge()

        # Re-discover combo dirs and evict stale cache for pending rerun combos.
        new_combos = self._discover_combos()
        for _, combo in self._manifest.pending_rerun_review():
            self._data_cache.pop(combo, None)
        self._available_combos = new_combos
        self._ensure_all_combos_loaded()
        # Always show sleep data in review mode, not the spindle fraction plot.
        self._set_spindle_mask_mode(False)
        if self._mode != "animal":
            self._set_mode("animal")
        else:
            self._refresh_animal_combo()
            self._update_all_plots()

    def _exit_review_mode(self) -> None:
        """Restore non-review UI and refresh the combo list."""
        self._review_mode = False
        self.btn_group.setEnabled(True)
        self.setStyleSheet("")
        self._lbl_animal.setText("Animal:")
        self._lbl_filter.setVisible(False)
        self._update_reruns_badge()
        self._available_combos = self._discover_combos()
        self._ensure_all_combos_loaded()
        self._refresh_animal_combo()
        self._update_all_plots()

    # ------------------------------------------------------------------
    # Combo discovery + loading
    # ------------------------------------------------------------------
    def _discover_combos(self) -> list[str]:
        d = self.project_root / "spindle_outputs"
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_dir())

    def _refresh_combos(self) -> None:
        combos = self._discover_combos()
        self._available_combos = combos

        self.cmb_combo.blockSignals(True)
        current = self.cmb_combo.currentText()
        self.cmb_combo.clear()
        self.cmb_combo.addItems(combos)
        if current in combos:
            self.cmb_combo.setCurrentText(current)
        elif "LFC_RSC" in combos:
            self.cmb_combo.setCurrentText("LFC_RSC")
        self.cmb_combo.blockSignals(False)

        # Trigger a load for the now-selected combo
        selected = self.cmb_combo.currentText()
        if selected:
            self._on_combo_changed(selected)
        else:
            self._update_all_plots()

    def _load_combo(self, combo: str) -> bool:
        """Load and cache data for combo. Returns True on success."""
        if combo in self._data_cache:
            return True
        d = self.project_root / "spindle_outputs" / combo
        if not d.is_dir():
            return False
        try:
            df = compute_sleep_bins_df(d)
            df_offset = compute_sleep_bins_df_offset(d)
            df_frac = compute_spindle_fractions(d)
        except Exception as e:
            QMessageBox.critical(
                self, "Error loading sleep metrics", f"Could not load {combo}:\n{e}"
            )
            return False
        self._data_cache[combo] = (df, df_offset, df_frac)
        return True

    def _ensure_all_combos_loaded(self) -> None:
        for combo in self._available_combos:
            self._load_combo(combo)

    def _on_combo_changed(self, combo: str) -> None:
        if not combo:
            return
        self._highlighted_animal = None
        self._load_combo(combo)
        pair = self._data_cache.get(combo)
        if pair is not None:
            self._mouse_ids = sorted(pair[0]["mouse_id"].unique())
        else:
            self._mouse_ids = []
        self._current_page = 0
        self._update_page_controls()
        if self.btn_spindle.isChecked():
            self._frac_widget.clear_selection()
        self._update_all_plots()

    # ------------------------------------------------------------------
    # Animal combo (animal mode)
    # ------------------------------------------------------------------
    def _refresh_animal_combo(self) -> None:
        all_mice_set = {
            mid for df, *_ in self._data_cache.values() for mid in df["mouse_id"].unique()
        }

        def _has_pending(mid: str) -> bool:
            entry = self._manifest.get(mid)
            return entry is not None and any(run.sleep_qc is None for run in entry.runs.values())

        # Three groups: reruns awaiting decision, other unreviewed, already reviewed
        rerun_pending = sorted(m for m in all_mice_set if self._has_pending_rerun(m))
        if self._review_mode:
            all_mice = rerun_pending
        else:
            other_pending = sorted(
                m for m in all_mice_set if _has_pending(m) and not self._has_pending_rerun(m)
            )
            reviewed = sorted(m for m in all_mice_set if not _has_pending(m))
            all_mice = rerun_pending + other_pending + reviewed

        self.cmb_animal.blockSignals(True)
        current = self.cmb_animal.currentText()
        self.cmb_animal.clear()
        self.cmb_animal.addItems(all_mice)

        # Bold the rerun-pending items so they stand out in the dropdown
        bold_font = QFont()
        bold_font.setBold(True)
        for i in range(len(rerun_pending)):
            self.cmb_animal.setItemData(i, bold_font, Qt.ItemDataRole.FontRole)

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
        has_next_rerun = any(
            self._has_pending_rerun(self.cmb_animal.itemText(j)) for j in range(i + 1, n)
        )
        self.btn_next_rerun.setEnabled(has_next_rerun)

    def _on_prev_animal(self) -> None:
        i = self.cmb_animal.currentIndex()
        if i > 0:
            self.cmb_animal.setCurrentIndex(i - 1)

    def _on_next_animal(self) -> None:
        i = self.cmb_animal.currentIndex()
        if i < self.cmb_animal.count() - 1:
            self.cmb_animal.setCurrentIndex(i + 1)

    def _has_pending_rerun(self, mid: str) -> bool:
        """True if this animal has a rerun run with outputs on disk awaiting review.

        Backed by the ``_pending_rerun_ids`` cache populated in
        ``_refresh_manifest``; lookup is O(1) per call rather than O(combos)
        filesystem probes.
        """
        return mid in self._pending_rerun_ids

    def _jump_to_next_rerun_animal(self) -> bool:
        """Move the dropdown to the next animal with a pending rerun.

        Returns True if a jump happened; False if no later entry has a
        pending rerun. The dropdown's ``currentIndexChanged`` signal does
        the post-jump refresh via ``_on_animal_changed``.
        """
        current = self.cmb_animal.currentIndex()
        for i in range(current + 1, self.cmb_animal.count()):
            if self._has_pending_rerun(self.cmb_animal.itemText(i)):
                self.cmb_animal.setCurrentIndex(i)
                return True
        return False

    def _on_next_rerun(self) -> None:
        """Step forward to the next animal with a pending rerun."""
        self._jump_to_next_rerun_animal()

    def _advance_to_next_rerun(self) -> None:
        """After resolving a rerun, jump to the next pending one or stay and refresh."""
        if not self._jump_to_next_rerun_animal():
            self._update_all_plots()

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
    def _get_df(self, combo: str) -> pd.DataFrame | None:
        pair = self._data_cache.get(combo)
        if pair is None:
            return None
        return pair[1] if self.btn_offset.isChecked() else pair[0]

    def _get_frac_df(self, combo: str) -> pd.DataFrame | None:
        pair = self._data_cache.get(combo)
        return pair[2] if pair is not None else None

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

    def _get_spindle_outlier_animals(self, combo: str) -> set:
        """Return animal IDs that are IQR × 1.5 outliers in any state of the spindle fraction data."""
        df_frac = self._get_frac_df(combo)
        if df_frac is None or df_frac.empty:
            return set()
        outliers: set = set()
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
        return outliers

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
        combo = self.cmb_combo.currentText()
        df = self._get_df(combo)
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
                    label = "Time (h)" if self.btn_offset.isChecked() else "Time (h) From EEG Start"
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
                    p.plot(
                        dm[x_col].to_numpy(),
                        dm[metric].to_numpy(),
                        pen=pg.mkPen(color=(*mouse_colors[mid], alpha), width=1.5),
                    )

        if self.btn_offset.isChecked() and not df.empty:
            self._apply_hour_of_day_ticks(df[x_col].unique())

        ref_combo = self._get_ref_combo() if self._show_ref_median else None
        if ref_combo is not None:
            self._draw_ref_median(ref_combo)

        self._update_legend_group(mice, mouse_colors, ref_combo)

    def _render_animal(self) -> None:
        animal = self.cmb_animal.currentText()

        self._prepare_plots()

        if not animal:
            self._update_legend_animal([])
            return

        drawn_combos = []
        all_x_vals: list[np.ndarray] = []
        for combo in self._available_combos:
            df = self._get_df(combo)
            if df is None or df.empty:
                continue
            df, x_col = self._ensure_x_col(df)
            adf = df[df["mouse_id"] == animal]
            if adf.empty:
                continue
            all_x_vals.append(adf[x_col].to_numpy())
            color = self._COMBO_COLORS.get(combo, (100, 100, 100))
            run = self._manifest.get_run(animal, combo)
            is_rerun = run is not None and run.source_combo is not None
            outlier_combos = self._get_spindle_outlier_animals(combo)
            is_outlier = animal in outlier_combos
            alpha = 255 if (not outlier_combos or is_outlier) else 80
            pen = pg.mkPen(
                color=(*color, alpha),
                width=2.0,
                style=Qt.PenStyle.DashLine if is_rerun else Qt.PenStyle.SolidLine,
            )
            for state in self.STATE_ORDER:
                for metric, _ in self.METRIC_ORDER:
                    dm = adf[adf["state"] == state].copy()
                    if dm.empty:
                        continue
                    dm[metric] = dm[metric].fillna(0)
                    dm = dm.sort_values(x_col)
                    self._plots[(metric, state)].plot(
                        dm[x_col].to_numpy(), dm[metric].to_numpy(), pen=pen
                    )
            drawn_combos.append(combo)

        # Group median reference overlay
        ref_combo = self._get_ref_combo()
        if ref_combo is not None:
            self._draw_ref_median(ref_combo)

        if self.btn_offset.isChecked() and all_x_vals:
            # Union of x values across every drawn combo — using just the
            # last combo's x range can omit ticks when recordings differ in
            # length (e.g. a short rerun missing the original's late bins).
            self._apply_hour_of_day_ticks(np.unique(np.concatenate(all_x_vals)))

        self._update_legend_animal(drawn_combos, ref_combo)

    # ------------------------------------------------------------------
    # Group median reference overlay
    # ------------------------------------------------------------------
    def _on_median_toggled(self, checked: bool) -> None:
        self._show_ref_median = checked
        self._update_all_plots()

    def _get_ref_combo(self) -> str | None:
        """Return combo with most ok animals; prefer LFC_RSC on ties.

        Reference median is only meaningful over OK runs — counting any
        run regardless of status (the pre-fix behavior) could pick a
        combo where most animals failed QC.
        """
        counts: dict[str, int] = {}
        for entry in self._manifest:
            for c, run in entry.runs.items():
                if c in self._available_combos and run.sleep_qc == "ok":
                    counts[c] = counts.get(c, 0) + 1
        if not counts:
            return None
        return "LFC_RSC" if "LFC_RSC" in counts else max(counts, key=counts.get)

    def _draw_ref_median(self, combo: str) -> None:
        """Draw group median reference as a dashed line on all plots."""
        df = self._get_df(combo)
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

    def _flag_accept_combo(self, combo: str) -> None:
        """Accept any combo as ok — cascade-rejects all siblings."""
        animal = self.cmb_animal.currentText()
        if not animal:
            return
        self._manifest.flag_sleep_qc(animal, combo, "ok")
        self.manifest_changed.emit()
        self._after_rerun_decision()

    def _flag_review_again(self, rerun_combo: str) -> None:
        """Send the rerun back through the Home page review queue for re-examination."""
        animal = self.cmb_animal.currentText()
        if not animal:
            return
        self._manifest.flag_sleep_qc(animal, rerun_combo, "needs_review")
        self.manifest_changed.emit()
        self._after_rerun_decision()

    def _after_rerun_decision(self) -> None:
        """Called after any decision in review mode — advance or exit review."""
        self._refresh_manifest()
        self._update_reruns_badge()
        if not self._manifest.pending_rerun_review():
            self._refresh_animal_combo()
            self._update_all_plots()
            QMessageBox.information(
                self, "Review Complete", "All spindle reruns have been checked."
            )
            self.btn_reruns_ready.setChecked(False)
            return
        current = self.cmb_animal.currentText()
        self._refresh_animal_combo()
        if not self._has_pending_rerun(current) and self.cmb_animal.count() > 0:
            self.cmb_animal.setCurrentIndex(0)
        self._update_all_plots()

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

        bg = self._STATUS_BG.get(status)
        row_w.setObjectName("legendRow")
        row_w.setStyleSheet(
            f"QWidget#legendRow {{ background-color: {bg or 'transparent'}; border-radius: 3px; }}"
        )
        return row_w, row_l

    def _build_mouse_color_map(self, mice: list[str]) -> dict:
        n = len(mice)
        cmap = mpl.colormaps["tab10"] if n <= 10 else mpl.colormaps["tab20"]
        return {mid: tuple(int(255 * c) for c in cmap(i)[:3]) for i, mid in enumerate(mice)}

    def _update_legend_group(
        self, mice: list[str], mouse_colors: dict, ref_combo: str | None = None
    ) -> None:
        self._clear_legend()
        combo = self.cmb_combo.currentText()
        spindle_outliers = self._get_spindle_outlier_animals(combo)

        for i, mid in enumerate(mice):
            color = mouse_colors[mid]
            run = self._manifest.get_run(mid, combo) if combo else None
            status = run.sleep_qc if run else None
            rejected_by = run.rejected_by if run else None

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

            row_l.addStretch(1)
            btn_ok = QPushButton("OK")
            btn_ok.setFixedHeight(22)
            btn_ok.setCheckable(True)
            btn_ok.setChecked(status == "ok")
            btn_ok.clicked.connect(
                lambda checked, m=mid: self._flag_sleep_qc(m, "ok" if checked else None)
            )
            row_l.addWidget(btn_ok)

            btn_review = QPushButton("Review")
            btn_review.setFixedHeight(22)
            btn_review.setCheckable(True)
            btn_review.setChecked(status in ("needs_review", "needs_rerun"))
            if status == "needs_rerun":
                btn_review.setText("Rerun Queued")
                btn_review.setEnabled(False)
                btn_review.setToolTip(
                    f"Rerun queued as {run.rerun_combo or '?'}. Change target from the Home page."
                )
            else:
                btn_review.clicked.connect(
                    lambda checked, m=mid: self._flag_sleep_qc(
                        m, "needs_review" if checked else None
                    )
                )
            row_l.addWidget(btn_review)

            if status == "rejected":
                if rejected_by:
                    tip = f"Rejected because {rejected_by} is OK.\nClick OK here to switch, or click Review to re-examine."
                    btn_ok.setToolTip(tip)
                    btn_review.setToolTip(tip)
                else:
                    btn_reset = QPushButton("Reset")
                    btn_reset.setFixedHeight(22)
                    btn_reset.setToolTip("Reset to unreviewed")
                    btn_reset.clicked.connect(
                        lambda _, m=mid, c=combo: self._reset_sleep_qc_group(m, c)
                    )
                    row_l.addWidget(btn_reset)

            self.legend_layout.addWidget(row_w, i // 2, i % 2)

        if ref_combo is not None:
            n_rows = (len(mice) + 1) // 2
            ref_lbl = QLabel(f"─ ─  Group median, all animals ({ref_combo})")
            ref_lbl.setStyleSheet("color: #999;")
            self.legend_layout.addWidget(ref_lbl, n_rows, 0, 1, 2)

    def _update_legend_animal(self, combos: list[str], ref_combo: str | None = None) -> None:
        self._clear_legend()
        animal = self.cmb_animal.currentText()
        for i, combo in enumerate(combos):
            color = self._COMBO_COLORS.get(combo, (100, 100, 100))
            run = self._manifest.get_run(animal, combo) if animal else None
            status = run.sleep_qc if run else None
            rejected_by = run.rejected_by if run else None
            source_combo = run.source_combo if run else None

            row_w, row_l = self._make_legend_row_frame(color, status)

            base_text = f"{combo}  ← rerun of {source_combo}" if source_combo else combo
            if animal and animal in self._get_spindle_outlier_animals(combo):
                base_text += ' <span style="color:#c0392b;font-size:9px;font-style:italic;">[spindle outlier]</span>'
            combo_label = QLabel(base_text)
            combo_label.setTextFormat(Qt.TextFormat.RichText)
            if source_combo:
                combo_label.setStyleSheet("font-style: italic;")
            row_l.addWidget(combo_label)
            # Stretch BEFORE action buttons so they right-align, matching
            # the group-mode legend at L1027.
            row_l.addStretch(1)

            if self._review_mode:
                btn_accept = QPushButton("✓ Accept")
                btn_accept.setFixedHeight(22)
                btn_accept.setToolTip(
                    f"Accept {combo} as the final combo — rejects all others for this animal"
                )
                btn_accept.clicked.connect(lambda _, c=combo: self._flag_accept_combo(c))
                row_l.addWidget(btn_accept)

                is_pending_rerun = (
                    source_combo is not None
                    and status is None
                    and any(spindle_output_dir(combo, self.project_root).glob(f"{animal}_*.csv"))
                )
                if is_pending_rerun:
                    btn_review = QPushButton("Review")
                    btn_review.setFixedHeight(22)
                    btn_review.setToolTip(
                        "Send back to the Home page review queue for re-examination."
                    )
                    btn_review.clicked.connect(lambda _, c=combo: self._flag_review_again(c))
                    row_l.addWidget(btn_review)
            else:
                btn_ok = QPushButton("OK")
                btn_ok.setFixedHeight(22)
                btn_ok.setCheckable(True)
                btn_ok.setChecked(status == "ok")
                btn_ok.clicked.connect(lambda checked, c=combo: self._flag_animal_ok(c, checked))
                row_l.addWidget(btn_ok)

                btn_review = QPushButton("Review")
                btn_review.setFixedHeight(22)
                btn_review.setCheckable(True)
                btn_review.setChecked(status in ("needs_review", "needs_rerun"))
                if status == "needs_rerun":
                    btn_review.setText("Rerun Queued")
                    btn_review.setEnabled(False)
                    btn_review.setToolTip(
                        f"Rerun queued as {run.rerun_combo or '?'}. "
                        "Change target from the Home page."
                    )
                else:
                    btn_review.clicked.connect(
                        lambda checked, c=combo: self._flag_animal_review(c, checked)
                    )
                row_l.addWidget(btn_review)

                if status == "rejected":
                    if rejected_by:
                        tip = f"Rejected because {rejected_by} is OK.\nClick OK here to switch, or click Review to re-examine."
                        btn_ok.setToolTip(tip)
                        btn_review.setToolTip(tip)
                    else:
                        btn_reset = QPushButton("Reset")
                        btn_reset.setFixedHeight(22)
                        btn_reset.setToolTip("Reset to unreviewed")
                        btn_reset.clicked.connect(
                            lambda _, a=animal, c=combo: self._reset_sleep_qc_animal(a, c)
                        )
                        row_l.addWidget(btn_reset)

            self.legend_layout.addWidget(row_w, i // 2, i % 2)

        # Reference line label
        if ref_combo is not None:
            ref_lbl = QLabel(f"─ ─  Group median, all animals ({ref_combo})")
            ref_lbl.setStyleSheet("color: #999;")
            n_rows = (len(combos) + 1) // 2
            self.legend_layout.addWidget(ref_lbl, n_rows, 0, 1, 2)

        # Fraction comparison table (review mode only)
        if self._review_mode and animal:
            frac_widget = self._make_fraction_comparison_widget(animal, combos)
            if frac_widget is not None:
                insert_row = (len(combos) + 1) // 2 + (1 if ref_combo else 0)
                self.legend_layout.addWidget(frac_widget, insert_row, 0, 1, 2)

    def _get_animal_fractions(self, animal: str, combo: str) -> dict[str, float] | None:
        """Return {state: fraction} for one animal from the cache, or None if unavailable."""
        pair = self._data_cache.get(combo)
        if pair is None:
            return None
        df_frac = pair[2]
        rows = df_frac[(df_frac["mouse_id"] == animal) & (df_frac["state"] != "Total")]
        if rows.empty:
            return None
        return dict(zip(rows["state"], rows["fraction"], strict=True))

    def _make_fraction_comparison_widget(self, animal: str, combos: list[str]) -> QWidget | None:
        """Build a compact spindle-fraction comparison table for review mode.

        Shows one row per combo that has fraction data, with rerun combos marked.
        Values are coloured green/red relative to their source combo.
        """
        STATES = ["Wake", "NREM", "REM"]

        # Collect fractions; skip combos with no data
        rows: list[tuple[str, str | None, dict[str, float]]] = []
        for combo in combos:
            run = self._manifest.get_run(animal, combo)
            source_combo = run.source_combo if run else None
            fracs = self._get_animal_fractions(animal, combo)
            if fracs:
                rows.append((combo, source_combo, fracs))

        if len(rows) < 2:
            return None

        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { border: 1px solid #ddd; border-radius: 3px; "
            "background: #fafafa; padding: 2px; }"
        )
        grid = QGridLayout(frame)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setSpacing(4)

        # Header
        hdr = QLabel("Spindle masked fraction:")
        hdr.setStyleSheet("font-size: 10px; color: #666; font-weight: bold;")
        grid.addWidget(hdr, 0, 0, 1, len(STATES) + 1)

        for col, state in enumerate(STATES, start=1):
            lbl = QLabel(state)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 10px; color: #555;")
            grid.addWidget(lbl, 1, col)

        # Data rows
        for row_i, (combo, source_combo, fracs) in enumerate(rows, start=2):
            tag = "  ← rerun" if source_combo else ""
            name_lbl = QLabel(f"{combo}{tag}")
            name_lbl.setStyleSheet(
                "font-size: 10px; font-style: italic;" if source_combo else "font-size: 10px;"
            )
            grid.addWidget(name_lbl, row_i, 0)

            for col, state in enumerate(STATES, start=1):
                val = fracs.get(state)
                if val is None:
                    grid.addWidget(QLabel("—"), row_i, col)
                    continue
                pct_lbl = QLabel(f"{val:.0%}")
                pct_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                pct_lbl.setStyleSheet("font-size: 10px;")
                grid.addWidget(pct_lbl, row_i, col)

        return frame

    # ------------------------------------------------------------------
    # Reset helpers (manually-rejected runs with no cascade history)
    # ------------------------------------------------------------------
    def _reset_sleep_qc_group(self, mid: str, combo: str) -> None:
        """Group-mode reset (manually-rejected runs without cascade)."""
        self._apply_sleep_qc(mid, combo, None, after="legend_group")

    def _reset_sleep_qc_animal(self, animal: str, combo: str) -> None:
        """Animal-mode reset (manually-rejected runs without cascade)."""
        self._apply_sleep_qc(animal, combo, None)

    # ------------------------------------------------------------------
    # Manifest flagging — the manifest enforces the one-ok invariant
    # ------------------------------------------------------------------
    def _apply_sleep_qc(
        self,
        animal: str,
        combo: str,
        status: str | None,
        *,
        after: str = "plots",
    ) -> None:
        """Shared flag/reset path for both group and animal modes.

        Args:
            animal: target animal ID; no-op if not in manifest.
            combo: target combo; no-op if empty.
            status: new ``sleep_qc`` value, or ``None`` to reset.
            after: which refresh to run when done — ``"plots"`` (default),
                ``"legend_group"`` (group-mode legend rebuild only), or
                ``"advance_rerun"`` (jump to the next pending rerun, used
                when an OK flag clears the current rerun decision).
        """
        if not combo or not animal or self._manifest.get(animal) is None:
            return
        if status is None:
            self._manifest.reset_sleep_qc(animal, combo)
        else:
            if self._manifest.get_run(animal, combo) is None:
                self._manifest.add_run(animal, combo)
            self._manifest.flag_sleep_qc(animal, combo, status)
        self.manifest_changed.emit()
        # Manifest state may have changed pending-rerun membership for this
        # animal (e.g. an OK flag clears the cascade). Refresh the cache.
        self._pending_rerun_ids = {
            entry.animal_id for entry, _ in self._manifest.pending_rerun_review()
        }
        self._update_reruns_badge()
        if after == "legend_group":
            mice = self._get_page_mice()
            self._update_legend_group(mice, self._build_mouse_color_map(mice))
        elif after == "advance_rerun":
            self._advance_to_next_rerun()
        else:
            self._update_all_plots()

    def _flag_animal_ok(self, combo: str, checked: bool = True) -> None:
        animal = self.cmb_animal.currentText()
        # OK on an animal with a pending rerun is the decision point — jump
        # forward to the next rerun rather than re-rendering in place.
        if checked and self._has_pending_rerun(animal):
            self._apply_sleep_qc(animal, combo, "ok", after="advance_rerun")
        else:
            self._apply_sleep_qc(animal, combo, "ok" if checked else None)

    def _flag_animal_review(self, combo: str, checked: bool = True) -> None:
        animal = self.cmb_animal.currentText()
        self._apply_sleep_qc(
            animal, combo, "needs_review" if checked else None
        )

    def _flag_sleep_qc(self, mid: str, status: str | None) -> None:
        """Group-mode flag entry: combo comes from the top-bar dropdown."""
        self._apply_sleep_qc(
            mid, self.cmb_combo.currentText(), status, after="legend_group"
        )


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
            # Need ≥2 points for a meaningful box+whisker; the IQR math is
            # degenerate at len 1 (q1 == q3, fences collapse onto the point)
            # and downstream `fracs[fracs >= lo_fence].min()` is fragile.
            if len(sdf) < 2:
                continue

            fracs = sdf["fraction"].to_numpy(dtype=float)
            mids = sdf["mouse_id"].to_numpy()
            y_max = max(y_max, fracs.max())

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

            # Scatter points (reproducible jitter)
            jitter = rng.uniform(-0.14, 0.14, len(fracs))
            xs = (xi + jitter).astype(float)

            is_out = (fracs < lo_fence) | (fracs > hi_fence)
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
        if status == "needs_rerun":
            self._btn_review.setEnabled(False)
            self._btn_review.setText("Rerun already queued")
            self._btn_review.setToolTip(
                "This animal is already queued for a rerun — cannot overwrite."
            )
        elif status == "needs_review":
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
