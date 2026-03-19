from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QComboBox, QLabel, QPushButton, QSizePolicy,
    QMessageBox, QSpinBox, QFrame, QScrollArea,
)
from ebb_viewer.pipeline.manifest import Manifest, spindle_output_dir


import pyqtgraph as pg
import matplotlib as mpl
from ebb.process.sleep_compute import compute_sleep_bins_df, compute_sleep_bins_df_offset


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

    STATE_ORDER = ["w", "n", "r"]
    STATE_DEF = {"w": "Wake", "n": "NREM", "r": "REM"}
    METRIC_ORDER = [
        ("frac_time", "Fraction of time"),
        ("n_bouts", "# bouts"),
        ("mean_bout_sec", "Mean bout duration (s)"),
    ]

    MICE_PER_PAGE = 10

    _STATUS_BG = {
        "ok":           "#d4edda",
        "needs_review": "#fff3cd",
        "needs_rerun":  "#fde8ce",
        "rejected":     "#e8e8e8",
    }

    _COMBO_COLORS = {
        "LFC_RSC": (31,  119, 180),
        "LFC_LSC": (255, 127, 14),
        "RSC_LSC": (44,  160, 44),
        "LFC":     (214, 39,  40),
        "RSC":     (148, 103, 189),
        "LSC":     (140, 86,  75),
    }

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)

        self._available_combos: list[str] = []
        self._data_cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
        self._mouse_ids: list[str] = []
        self._current_page: int = 0
        self._mode: str = "group"
        self._review_mode: bool = False

        self._plots: dict[tuple[str, str], pg.PlotItem] = {}

        self._manifest = Manifest.load(project_root)

        self._build_ui()
        self._wire()

    def _poll(self):
        """Lightweight background refresh: reload manifest and update the reruns badge."""
        self._manifest = Manifest.load(self.project_root)
        for _, combo in self._manifest.pending_rerun_review():
            self._data_cache.pop(combo, None)
        self._update_reruns_badge()

    def showEvent(self, event):
        super().showEvent(event)
        self._manifest = Manifest.load(self.project_root)
        # Evict any cached combo that has a pending rerun — new files may have been
        # downloaded since the last time this combo was loaded.
        for _, combo in self._manifest.pending_rerun_review():
            self._data_cache.pop(combo, None)
        self._update_reruns_badge()
        self._refresh_combos()
        if self._mode == "animal":
            self._ensure_all_combos_loaded()
            self._refresh_animal_combo()
            self._update_all_plots()

    def _update_reruns_badge(self) -> None:
        pending = self._manifest.pending_rerun_review()
        n = len(pending)
        if self._review_mode:
            self.btn_reruns_ready.setText(f"✕ Exit Review  ({n} remaining)")
            self.btn_reruns_ready.setVisible(True)
        elif n > 0:
            self.btn_reruns_ready.setText(
                f"● {n} rerun{'s' if n != 1 else ''} ready for review  →"
            )
            self.btn_reruns_ready.setVisible(True)
        else:
            self.btn_reruns_ready.setVisible(False)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # --- top bar ---
        top = QHBoxLayout()

        top.addWidget(QLabel("Combo:"))
        self.cmb_combo = QComboBox()
        self.cmb_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.cmb_combo.setMinimumWidth(100)
        top.addWidget(self.cmb_combo)

        top.addWidget(_vsep(self))

        self.btn_group = QPushButton("Group")
        self.btn_group.setCheckable(True)
        self.btn_group.setChecked(True)
        self.btn_animal = QPushButton("Animal")
        self.btn_animal.setCheckable(True)
        top.addWidget(self.btn_group)
        top.addWidget(self.btn_animal)

        top.addWidget(_vsep(self))

        self.btn_offset = QPushButton("6AM Start")
        self.btn_offset.setCheckable(True)
        self.btn_offset.setChecked(False)
        top.addWidget(self.btn_offset)

        top.addStretch(1)

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
        ac.addWidget(QLabel("Animal:"))
        self.cmb_animal = QComboBox()
        self.cmb_animal.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.cmb_animal.setMinimumWidth(150)
        self.btn_prev_animal = QPushButton("◄ Prev")
        self.btn_next_animal = QPushButton("Next ►")
        self.btn_next_rerun = QPushButton("Next Rerun ►")
        self.btn_next_rerun.setEnabled(False)
        ac.addWidget(self.cmb_animal)
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

        layout.addWidget(self.grid, stretch=1)

        # --- legend (in a scroll area so the plot grid can't collapse it) ---
        self.legend_container = QWidget()
        self.legend_layout = QGridLayout(self.legend_container)
        self.legend_layout.setContentsMargins(2, 2, 2, 2)
        self.legend_layout.setVerticalSpacing(4)
        self.legend_layout.setHorizontalSpacing(40)
        self.legend_layout.setColumnStretch(0, 1)
        self.legend_layout.setColumnStretch(1, 1)

        legend_scroll = QScrollArea()
        legend_scroll.setWidget(self.legend_container)
        legend_scroll.setWidgetResizable(True)
        legend_scroll.setFixedHeight(140)
        legend_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(legend_scroll)

    def _wire(self) -> None:
        self.cmb_combo.currentTextChanged.connect(self._on_combo_changed)
        self.btn_group.clicked.connect(lambda: self._set_mode("group"))
        self.btn_animal.clicked.connect(lambda: self._set_mode("animal"))
        self.btn_offset.toggled.connect(self._update_all_plots)

        self.btn_prev.clicked.connect(self._on_prev_page)
        self.btn_next.clicked.connect(self._on_next_page)
        self.spin_page.valueChanged.connect(self._on_page_spin_changed)

        self.btn_reruns_ready.toggled.connect(self._on_review_mode_toggled)

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
        is_group = (mode == "group")
        self.btn_group.setChecked(is_group)
        self.btn_animal.setChecked(not is_group)
        self.cmb_combo.setEnabled(is_group)
        self._group_controls.setVisible(is_group)
        self._animal_controls.setVisible(not is_group)

        if not is_group:
            self._ensure_all_combos_loaded()
            self._refresh_animal_combo()

        self._update_all_plots()

    def _on_review_mode_toggled(self, checked: bool) -> None:
        self._review_mode = checked
        self.btn_group.setEnabled(not checked)
        self._update_reruns_badge()
        if checked:
            self._manifest = Manifest.load(self.project_root)
            # Re-discover combo dirs and evict stale cache for pending rerun combos.
            new_combos = self._discover_combos()
            for _, combo in self._manifest.pending_rerun_review():
                self._data_cache.pop(combo, None)
            self._available_combos = new_combos
            self._ensure_all_combos_loaded()
            if self._mode != "animal":
                self._set_mode("animal")
            else:
                self._refresh_animal_combo()
                self._update_all_plots()
            if self.cmb_animal.count() == 0:
                QMessageBox.information(
                    self, "No Pending Reruns", "No animals have pending rerun decisions."
                )
                self.btn_reruns_ready.blockSignals(True)
                self.btn_reruns_ready.setChecked(False)
                self.btn_reruns_ready.blockSignals(False)
                self._review_mode = False
                self.btn_group.setEnabled(True)
                self._update_reruns_badge()
        else:
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
        except Exception as e:
            QMessageBox.critical(self, "Error loading sleep metrics",
                                 f"Could not load {combo}:\n{e}")
            return False
        self._data_cache[combo] = (df, df_offset)
        return True

    def _ensure_all_combos_loaded(self) -> None:
        for combo in self._available_combos:
            self._load_combo(combo)

    def _on_combo_changed(self, combo: str) -> None:
        if not combo:
            return
        self._load_combo(combo)
        pair = self._data_cache.get(combo)
        if pair is not None:
            self._mouse_ids = sorted(pair[0]["mouse_id"].unique())
        else:
            self._mouse_ids = []
        self._current_page = 0
        self._update_page_controls()
        self._update_all_plots()

    # ------------------------------------------------------------------
    # Animal combo (animal mode)
    # ------------------------------------------------------------------
    def _refresh_animal_combo(self) -> None:
        all_mice_set = {
            mid
            for df, _ in self._data_cache.values()
            for mid in df["mouse_id"].unique()
        }

        def _has_pending(mid: str) -> bool:
            entry = self._manifest.get(mid)
            return entry is not None and any(
                run.sleep_qc is None for run in entry.runs.values()
            )

        # Three groups: reruns awaiting decision, other unreviewed, already reviewed
        rerun_pending = sorted(m for m in all_mice_set if self._has_pending_rerun(m))
        if self._review_mode:
            all_mice = rerun_pending
        else:
            other_pending = sorted(
                m for m in all_mice_set
                if _has_pending(m) and not self._has_pending_rerun(m)
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
            self._has_pending_rerun(self.cmb_animal.itemText(j))
            for j in range(i + 1, n)
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
        """True if this animal has a rerun run with outputs on disk awaiting review."""
        entry = self._manifest.get(mid)
        if entry is None:
            return False
        return any(
            run.source_combo is not None
            and run.sleep_qc is None
            and any(spindle_output_dir(combo, self.project_root).glob(f"{mid}_*.csv"))
            for combo, run in entry.runs.items()
        )

    def _on_next_rerun(self) -> None:
        """Step forward to the next animal with a pending rerun."""
        current = self.cmb_animal.currentIndex()
        for i in range(current + 1, self.cmb_animal.count()):
            if self._has_pending_rerun(self.cmb_animal.itemText(i)):
                self.cmb_animal.setCurrentIndex(i)
                return

    def _advance_to_next_rerun(self) -> None:
        """After resolving a rerun, jump to the next pending one or stay and refresh."""
        current = self.cmb_animal.currentIndex()
        for i in range(current + 1, self.cmb_animal.count()):
            if self._has_pending_rerun(self.cmb_animal.itemText(i)):
                self.cmb_animal.setCurrentIndex(i)  # triggers _on_animal_changed
                return
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
        return self._mouse_ids[start:start + self.MICE_PER_PAGE]

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

    @staticmethod
    def _ensure_x_col(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        if "bin_start_hr" in df.columns:
            return df, "bin_start_hr"
        return df.assign(bin_start_hr=df["bin_start_sec"] / 3600.0), "bin_start_hr"

    def _prepare_plots(self) -> None:
        for p in self._plots.values():
            p.clear()

    def _update_all_plots(self, *_) -> None:
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
                    p.plot(dm[x_col].to_numpy(), dm[metric].to_numpy(),
                           pen=pg.mkPen(color=mouse_colors[mid], width=1.5))

        self._update_legend_group(mice, mouse_colors)

    def _render_animal(self) -> None:
        animal = self.cmb_animal.currentText()

        self._prepare_plots()

        if not animal:
            self._update_legend_animal([])
            return

        drawn_combos = []
        for combo in self._available_combos:
            df = self._get_df(combo)
            if df is None or df.empty:
                continue
            df, x_col = self._ensure_x_col(df)
            adf = df[df["mouse_id"] == animal]
            if adf.empty:
                continue
            color = self._COMBO_COLORS.get(combo, (100, 100, 100))
            run = self._manifest.get_run(animal, combo)
            is_rerun = run is not None and run.source_combo is not None
            pen = pg.mkPen(
                color=color, width=2.0,
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

        # Group mean reference overlay
        ref_combo = self._get_ref_combo()
        if ref_combo is not None:
            self._draw_ref_mean(ref_combo)

        self._update_legend_animal(drawn_combos, ref_combo)

    # ------------------------------------------------------------------
    # Group mean reference overlay
    # ------------------------------------------------------------------
    def _get_ref_combo(self) -> str | None:
        """Return combo with most ok animals; prefer LFC_RSC."""
        ok_counts: dict[str, int] = {}
        for entry in self._manifest:
            for c, run in entry.runs.items():
                if run.sleep_qc == "ok" and c in self._available_combos:
                    ok_counts[c] = ok_counts.get(c, 0) + 1
        if not ok_counts:
            return None
        return "LFC_RSC" if "LFC_RSC" in ok_counts else max(ok_counts, key=ok_counts.__getitem__)

    def _draw_ref_mean(self, combo: str) -> None:
        """Draw group mean reference as a dashed gray line on all plots."""
        df = self._get_df(combo)
        if df is None or df.empty:
            return
        ok_animals = {
            entry.animal_id
            for entry in self._manifest
            for c, run in entry.runs.items()
            if c == combo and run.sleep_qc == "ok"
        }
        if not ok_animals:
            return
        df, x_col = self._ensure_x_col(df)
        sub = df[df["mouse_id"].isin(ok_animals)]
        metrics = [m for m, _ in self.METRIC_ORDER]
        mean_df = sub.groupby(["state", x_col])[metrics].mean().reset_index()

        ref_pen = pg.mkPen(color=(160, 160, 160), width=1.5,
                           style=Qt.PenStyle.DashLine)
        for state in self.STATE_ORDER:
            for metric, _ in self.METRIC_ORDER:
                panel = mean_df[mean_df["state"] == state].sort_values(x_col)
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
        self._manifest = Manifest.load(self.project_root)
        self._update_reruns_badge()
        if not self._manifest.pending_rerun_review():
            self._refresh_animal_combo()
            self._update_all_plots()
            QMessageBox.information(self, "Review Complete", "All reruns have been reviewed.")
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
    def _clear_legend(self) -> None:
        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _build_mouse_color_map(self, mice: list[str]) -> dict:
        n = len(mice)
        cmap = mpl.colormaps["tab10"] if n <= 10 else mpl.colormaps["tab20"]
        return {mid: tuple(int(255 * c) for c in cmap(i)[:3]) for i, mid in enumerate(mice)}

    def _update_legend_group(self, mice: list[str], mouse_colors: dict) -> None:
        self._clear_legend()
        combo = self.cmb_combo.currentText()

        for i, mid in enumerate(mice):
            color = mouse_colors[mid]
            run = self._manifest.get_run(mid, combo) if combo else None
            status = run.sleep_qc if run else None
            rejected_by = run.rejected_by if run else None

            swatch = QFrame()
            swatch.setFixedSize(30, 4)
            swatch.setStyleSheet(f"background-color: rgb({color[0]}, {color[1]}, {color[2]});")

            btn_ok = QPushButton("OK")
            btn_ok.setFixedHeight(22)
            btn_ok.setCheckable(True)
            btn_ok.setChecked(status == "ok")
            btn_ok.clicked.connect(lambda checked, m=mid: self._flag_sleep_qc(m, "ok" if checked else None))

            btn_review = QPushButton("Review")
            btn_review.setFixedHeight(22)
            btn_review.setCheckable(True)
            btn_review.setChecked(status in ("needs_review", "needs_rerun"))
            btn_review.clicked.connect(lambda checked, m=mid: self._flag_sleep_qc(m, "needs_review" if checked else None))

            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(4, 2, 4, 2)
            row_l.setSpacing(4)
            row_l.addWidget(swatch)
            row_l.addWidget(QLabel(str(mid)))
            row_l.addWidget(btn_ok)
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

            bg = self._STATUS_BG.get(status)
            row_w.setObjectName("legendRow")
            row_w.setStyleSheet(
                f"QWidget#legendRow {{ background-color: {bg or 'transparent'};"
                " border-radius: 3px; }"
            )

            self.legend_layout.addWidget(row_w, i // 2, i % 2)

    def _update_legend_animal(self, combos: list[str],
                               ref_combo: str | None = None) -> None:
        self._clear_legend()
        animal = self.cmb_animal.currentText()
        for i, combo in enumerate(combos):
            color = self._COMBO_COLORS.get(combo, (100, 100, 100))
            run = self._manifest.get_run(animal, combo) if animal else None
            status = run.sleep_qc if run else None
            rejected_by = run.rejected_by if run else None
            source_combo = run.source_combo if run else None

            swatch = QFrame()
            swatch.setFixedSize(30, 4)
            swatch.setStyleSheet(f"background-color: rgb({color[0]}, {color[1]}, {color[2]});")

            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(4, 2, 4, 2)
            row_l.setSpacing(4)
            row_l.addWidget(swatch)

            combo_label = QLabel(
                f"{combo}  ← rerun of {source_combo}" if source_combo else combo
            )
            if source_combo:
                combo_label.setStyleSheet("font-style: italic;")
            row_l.addWidget(combo_label)

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
                btn_review.clicked.connect(lambda checked, c=combo: self._flag_animal_review(c, checked))
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

            row_l.addStretch(1)

            bg = self._STATUS_BG.get(status)
            row_w.setObjectName("legendRow")
            row_w.setStyleSheet(
                f"QWidget#legendRow {{ background-color: {bg or 'transparent'};"
                " border-radius: 3px; }"
            )

            self.legend_layout.addWidget(row_w, i // 2, i % 2)

        # Reference line label
        if ref_combo is not None:
            ref_lbl = QLabel(f"─ ─  Group mean ({ref_combo})")
            ref_lbl.setStyleSheet("color: #999;")
            n_rows = (len(combos) + 1) // 2
            self.legend_layout.addWidget(ref_lbl, n_rows, 0, 1, 2)

    # ------------------------------------------------------------------
    # Reset helpers (manually-rejected runs with no cascade history)
    # ------------------------------------------------------------------
    def _reset_sleep_qc_group(self, mid: str, combo: str) -> None:
        self._manifest.reset_sleep_qc(mid, combo)
        self.manifest_changed.emit()
        self._update_reruns_badge()
        mice = self._get_page_mice()
        self._update_legend_group(mice, self._build_mouse_color_map(mice))

    def _reset_sleep_qc_animal(self, animal: str, combo: str) -> None:
        self._manifest.reset_sleep_qc(animal, combo)
        self.manifest_changed.emit()
        self._update_reruns_badge()
        self._update_all_plots()

    # ------------------------------------------------------------------
    # Manifest flagging — the manifest enforces the one-ok invariant
    # ------------------------------------------------------------------
    def _flag_animal_ok(self, combo: str, checked: bool = True) -> None:
        animal = self.cmb_animal.currentText()
        if not animal or self._manifest.get(animal) is None:
            return
        had_pending_rerun = checked and self._has_pending_rerun(animal)
        if not checked:
            self._manifest.reset_sleep_qc(animal, combo)
        else:
            if self._manifest.get_run(animal, combo) is None:
                self._manifest.add_run(animal, combo)
            self._manifest.flag_sleep_qc(animal, combo, "ok")
        self.manifest_changed.emit()
        self._update_reruns_badge()
        if had_pending_rerun:
            self._advance_to_next_rerun()
        else:
            self._update_all_plots()

    def _flag_animal_review(self, combo: str, checked: bool = True) -> None:
        animal = self.cmb_animal.currentText()
        if not animal or self._manifest.get(animal) is None:
            return
        if not checked:
            self._manifest.reset_sleep_qc(animal, combo)
        else:
            if self._manifest.get_run(animal, combo) is None:
                self._manifest.add_run(animal, combo)
            self._manifest.flag_sleep_qc(animal, combo, "needs_review")
        self.manifest_changed.emit()
        self._update_reruns_badge()
        self._update_all_plots()

    def _flag_sleep_qc(self, mid: str, status: str | None) -> None:
        combo = self.cmb_combo.currentText()
        if not combo or self._manifest.get(mid) is None:
            return
        if status is None:
            self._manifest.reset_sleep_qc(mid, combo)
        else:
            if self._manifest.get_run(mid, combo) is None:
                self._manifest.add_run(mid, combo)
            self._manifest.flag_sleep_qc(mid, combo, status)
        self.manifest_changed.emit()
        self._update_reruns_badge()
        mice = self._get_page_mice()
        self._update_legend_group(mice, self._build_mouse_color_map(mice))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vsep(parent: QWidget) -> QFrame:
    f = QFrame(parent)
    f.setFrameShape(QFrame.Shape.VLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f
