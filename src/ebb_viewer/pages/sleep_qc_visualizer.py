from __future__ import annotations

from typing import Optional, Dict, Tuple, List
from pathlib import Path

import numpy as np
import pandas as pd

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QComboBox, QLabel, QPushButton, QSizePolicy,
    QMessageBox, QSpinBox, QFrame, QScrollArea,
)
from ebb_viewer.pipeline.manifest import Manifest


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
    """

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

        self._available_combos: List[str] = []
        self._data_cache: Dict[str, Tuple[pd.DataFrame, pd.DataFrame]] = {}
        self._mouse_ids: List[str] = []
        self._current_page: int = 0
        self._mode: str = "group"

        self._plots: Dict[Tuple[str, str], pg.PlotItem] = {}

        self._manifest = Manifest.load(project_root)

        self._build_ui()
        self._wire()

    def showEvent(self, event):
        super().showEvent(event)
        self._manifest = Manifest.load(self.project_root)
        self._update_reruns_badge()
        self._refresh_combos()
        if self._mode == "animal":
            self._ensure_all_combos_loaded()
            self._refresh_animal_combo()
            self._update_all_plots()

    def _update_reruns_badge(self) -> None:
        pending = self._manifest.pending_rerun_review()
        if pending:
            n = len(pending)
            self.lbl_reruns_ready.setText(
                f"● {n} rerun{'s' if n != 1 else ''} ready for review"
            )
            self.lbl_reruns_ready.setVisible(True)
        else:
            self.lbl_reruns_ready.setVisible(False)

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

        self.lbl_reruns_ready = QLabel()
        self.lbl_reruns_ready.setStyleSheet("color: #c96a00; font-weight: bold;")
        self.lbl_reruns_ready.setVisible(False)
        top.addWidget(self.lbl_reruns_ready)

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
        ac.addWidget(self.cmb_animal)
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

        self.cmb_animal.currentTextChanged.connect(self._on_animal_changed)
        self.btn_prev_animal.clicked.connect(self._on_prev_animal)
        self.btn_next_animal.clicked.connect(self._on_next_animal)

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------
    def _set_mode(self, mode: str) -> None:
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

    # ------------------------------------------------------------------
    # Combo discovery + loading
    # ------------------------------------------------------------------
    def _discover_combos(self) -> List[str]:
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

        pending = sorted(m for m in all_mice_set if _has_pending(m))
        reviewed = sorted(m for m in all_mice_set if not _has_pending(m))
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

    def _get_page_mice(self) -> List[str]:
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
    def _get_df(self, combo: str) -> Optional[pd.DataFrame]:
        pair = self._data_cache.get(combo)
        if pair is None:
            return None
        return pair[1] if self.btn_offset.isChecked() else pair[0]

    @staticmethod
    def _ensure_x_col(df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
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
            pen = pg.mkPen(color=color, width=2.0)
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
    def _get_ref_combo(self) -> Optional[str]:
        """Return combo with most ok animals; prefer LFC_RSC."""
        ok_counts: dict[str, int] = {}
        for combo in self._available_combos:
            n = sum(
                1 for entry in self._manifest
                for c, run in entry.runs.items()
                if c == combo and run.sleep_qc == "ok"
            )
            if n > 0:
                ok_counts[combo] = n
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

    # ------------------------------------------------------------------
    # Legend
    # ------------------------------------------------------------------
    def _clear_legend(self) -> None:
        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _build_mouse_color_map(self, mice: List[str]) -> dict:
        n = len(mice)
        cmap = mpl.colormaps["tab10"] if n <= 10 else mpl.colormaps["tab20"]
        return {mid: tuple(int(255 * c) for c in cmap(i)[:3]) for i, mid in enumerate(mice)}

    def _update_legend_group(self, mice: List[str], mouse_colors: dict) -> None:
        self._clear_legend()
        combo = self.cmb_combo.currentText()

        for i, mid in enumerate(mice):
            color = mouse_colors[mid]
            run = self._manifest.get_run(mid, combo) if combo else None
            status = run.sleep_qc if run else None

            swatch = QFrame()
            swatch.setFixedSize(30, 4)
            swatch.setStyleSheet(f"background-color: rgb({color[0]}, {color[1]}, {color[2]});")

            btn_ok = QPushButton("OK")
            btn_ok.setFixedHeight(22)
            btn_ok.setCheckable(True)
            btn_ok.setChecked(status == "ok")
            btn_ok.clicked.connect(lambda _, m=mid: self._flag_sleep_qc(m, "ok"))

            btn_review = QPushButton("Review")
            btn_review.setFixedHeight(22)
            btn_review.setCheckable(True)
            btn_review.setChecked(status == "needs_review")
            btn_review.clicked.connect(lambda _, m=mid: self._flag_sleep_qc(m, "needs_review"))

            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(4, 2, 4, 2)
            row_l.setSpacing(4)
            row_l.addWidget(swatch)
            row_l.addWidget(QLabel(str(mid)))
            row_l.addWidget(btn_ok)
            row_l.addWidget(btn_review)

            bg = self._STATUS_BG.get(status)
            if bg:
                row_w.setStyleSheet(f"background-color: {bg}; border-radius: 3px;")

            self.legend_layout.addWidget(row_w, i // 2, i % 2)

    def _update_legend_animal(self, combos: List[str],
                               ref_combo: Optional[str] = None) -> None:
        self._clear_legend()
        animal = self.cmb_animal.currentText()
        for i, combo in enumerate(combos):
            color = self._COMBO_COLORS.get(combo, (100, 100, 100))
            run = self._manifest.get_run(animal, combo) if animal else None
            status = run.sleep_qc if run else None

            swatch = QFrame()
            swatch.setFixedSize(30, 4)
            swatch.setStyleSheet(f"background-color: rgb({color[0]}, {color[1]}, {color[2]});")

            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(4, 2, 4, 2)
            row_l.setSpacing(4)
            row_l.addWidget(swatch)
            row_l.addWidget(QLabel(combo))

            btn_ok = QPushButton("OK")
            btn_ok.setFixedHeight(22)
            btn_ok.setCheckable(True)
            btn_ok.setChecked(status == "ok")
            btn_ok.clicked.connect(lambda _, c=combo: self._flag_animal_ok(c))
            row_l.addWidget(btn_ok)

            btn_review = QPushButton("Review")
            btn_review.setFixedHeight(22)
            btn_review.setCheckable(True)
            btn_review.setChecked(status == "needs_review")
            btn_review.clicked.connect(lambda _, c=combo: self._flag_animal_review(c))
            row_l.addWidget(btn_review)

            row_l.addStretch(1)

            bg = self._STATUS_BG.get(status)
            if bg:
                row_w.setStyleSheet(f"background-color: {bg}; border-radius: 3px;")

            self.legend_layout.addWidget(row_w, i // 2, i % 2)

        # Reference line label
        if ref_combo is not None:
            ref_lbl = QLabel(f"─ ─  Group mean ({ref_combo})")
            ref_lbl.setStyleSheet("color: #999;")
            n_rows = (len(combos) + 1) // 2
            self.legend_layout.addWidget(ref_lbl, n_rows, 0, 1, 2)

    # ------------------------------------------------------------------
    # Manifest flagging (normal mode)
    # ------------------------------------------------------------------
    def _flag_animal_ok(self, combo: str) -> None:
        animal = self.cmb_animal.currentText()
        if not animal or self._manifest.get(animal) is None:
            return
        entry = self._manifest.get(animal)
        for c, run in entry.runs.items():
            if c == combo:
                continue
            if run.sleep_qc != "rejected":
                self._manifest.flag_sleep_qc(animal, c, "rejected")
        if self._manifest.get_run(animal, combo) is None:
            self._manifest.add_run(animal, combo)
        self._manifest.flag_sleep_qc(animal, combo, "ok")
        self._update_reruns_badge()
        self._update_all_plots()

    def _flag_animal_review(self, combo: str) -> None:
        animal = self.cmb_animal.currentText()
        if not animal or self._manifest.get(animal) is None:
            return
        if self._manifest.get_run(animal, combo) is None:
            self._manifest.add_run(animal, combo)
        self._manifest.flag_sleep_qc(animal, combo, "needs_review")
        self._update_all_plots()

    def _flag_sleep_qc(self, mid: str, status: str) -> None:
        combo = self.cmb_combo.currentText()
        if not combo or self._manifest.get(mid) is None:
            return
        if self._manifest.get_run(mid, combo) is None:
            self._manifest.add_run(mid, combo)
        if status == "ok":
            entry = self._manifest.get(mid)
            for c, run in entry.runs.items():
                if c != combo and run.sleep_qc != "rejected":
                    self._manifest.flag_sleep_qc(mid, c, "rejected")
        self._manifest.flag_sleep_qc(mid, combo, status)
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
