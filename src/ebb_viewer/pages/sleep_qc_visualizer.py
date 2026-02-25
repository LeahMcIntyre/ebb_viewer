from __future__ import annotations

from typing import Optional, Dict, Tuple, List
from pathlib import Path

import numpy as np
import pandas as pd

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QLabel, QPushButton, QSizePolicy,
    QFileDialog, QMessageBox, QSpinBox, QFrame
)

import pyqtgraph as pg
import matplotlib as mpl
from ebb.process.sleep_compute import compute_sleep_bins_df, compute_sleep_bins_df_offset



class SleepQCGridPage(QWidget):
    """
    QC page: 3x3 grid (states x metrics), showing ~10 mice at a time.
    Each panel: x = time (h), y = metric, colored by mouse_id.
    """

    STATE_ORDER = ["w", "n", "r"]
    STATE_DEF = {"w": 'Wake', "n": 'NREM', "r": 'REM'}
    METRIC_ORDER = [
        ("frac_time", "Fraction of time"),
        ("n_bouts", "# bouts"),
        ("mean_bout_sec", "Mean bout duration (s)"),
    ]

    MICE_PER_PAGE = 10

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)

        self._df: Optional[pd.DataFrame] = None
        self._df_offset: Optional[pd.DataFrame] = None
        self._current_dir: Optional[Path] = None
        self._mouse_ids: List[str] = []
        self._current_page: int = 0  # 0-based

        self._plots: Dict[Tuple[str, str], pg.PlotItem] = {}
        self._legend_items: Dict[int, Tuple[pg.GraphicsObject, str]] = {}

        self._build_ui()
        self._wire()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # --- directory chooser row ---
        dir_row = QHBoxLayout()
        self.dir_button = QPushButton("Select spindle outputs directory…")
        self.dir_label = QLabel("No directory selected")
        self.dir_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        dir_row.addWidget(self.dir_button)
        dir_row.addWidget(self.dir_label, stretch=1)
        layout.addLayout(dir_row)

        # --- top controls: group filter + page controls ---
        ctrl_row = QHBoxLayout()

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Optional group filter (or "All groups")
        self.group_combo = QComboBox()
        self.group_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        form.addRow(QLabel("Group filter:"), self.group_combo)

        # Page controls
        page_ctrl = QHBoxLayout()
        self.offset_btn = QPushButton("6 AM Start")
        self.offset_btn.setCheckable(True)   # makes it toggle-able
        self.offset_btn.setChecked(False)    # start as False

        self.prev_button = QPushButton("Prev mice")
        self.next_button = QPushButton("Next mice")

        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.setValue(1)

        self.page_label = QLabel("Page 1 / 1")

        page_ctrl.addWidget(self.offset_btn)
        page_ctrl.addWidget(self.prev_button)
        page_ctrl.addWidget(self.next_button)
        page_ctrl.addWidget(QLabel("Go to:"))
        page_ctrl.addWidget(self.page_spin)
        page_ctrl.addWidget(self.page_label)

        # Put group + page widgets together
        ctrl_row.addLayout(form)
        ctrl_row.addStretch(1)
        ctrl_row.addLayout(page_ctrl)

        layout.addLayout(ctrl_row)

        # --- grid of plots ---
        self.grid = pg.GraphicsLayoutWidget()
        self.grid.setBackground("w")
        self.grid.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Create 3x3 PlotItems and remember them in dict keyed by (state, metric_name)
        self._plots.clear()
        for si, state in enumerate(self.STATE_ORDER):
            for mi, (metric, metric_label) in enumerate(self.METRIC_ORDER):
                p: pg.PlotItem = self.grid.addPlot(row=mi, col=si)
                p.showGrid(x=True, y=True, alpha=0.3)
                if mi == len(self.METRIC_ORDER) - 1:
                    p.setLabel("bottom", "Time (h)")
                else:
                    p.getAxis("bottom").setStyle(showValues=False)

                if si == 0:
                    p.setLabel("left", metric_label)
                #else:
                    # hide values but maybe keep ticks
                    #p.getAxis("left").setStyle(showValues=False)

                # title = metric label
                p.setTitle(f'{self.STATE_DEF[state]}: {metric_label}', size="10pt")
                self._plots[(metric, state)] = p

        layout.addWidget(self.grid, stretch=1)

        # --- legend area ---
        self.legend_container = QWidget()
        self.legend_layout = QHBoxLayout(self.legend_container)
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setSpacing(12)

        layout.addWidget(self.legend_container)

    def _wire(self) -> None:
        self.dir_button.clicked.connect(self._on_choose_directory)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        self.offset_btn.toggled.connect(self._update_all_plots)

        self.prev_button.clicked.connect(self._on_prev_page)
        self.next_button.clicked.connect(self._on_next_page)
        self.page_spin.valueChanged.connect(self._on_page_spin_changed)

    # ------------------------------------------------------------------
    # Directory selection + loading
    # ------------------------------------------------------------------
    def _on_choose_directory(self) -> None:
        spindle_root = self.project_root / "spindle_outputs"
        if spindle_root.exists() and spindle_root.is_dir():
            start_dir = spindle_root
        else:
            start_dir = self.project_root

        dirname = QFileDialog.getExistingDirectory(
            self,
            "Select spindle outputs directory",
            str(start_dir),
        )
        if not dirname:
            return

        self._current_dir = Path(dirname)
        self.dir_label.setText(str(self._current_dir))

        try:
            df = compute_sleep_bins_df(self._current_dir)
            df_offset = compute_sleep_bins_df_offset(self._current_dir)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error loading sleep metrics",
                f"Could not load sleep metrics from:\n{self._current_dir}\n\n{e}",
            )
            self._df = None
            self._df_offset = None

            self._mouse_ids = []
            self._update_group_combo()
            self._update_page_controls()
            self._clear_plots()
            return

        self._df = df
        self._df_offset = df_offset
        self._update_group_combo()
        self._reset_mouse_list()
        self._update_page_controls()
        self._update_all_plots()

    # ------------------------------------------------------------------
    # Group filter / mouse pagination
    # ------------------------------------------------------------------
    def _update_group_combo(self) -> None:
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem("All groups", userData=None)

        df = self._df
        if df is not None and not df.empty and "group" in df.columns:
            for g in sorted(df["group"].dropna().unique()):
                self.group_combo.addItem(str(g), userData=g)

        self.group_combo.blockSignals(False)

    def _current_group_filter(self):
        idx = self.group_combo.currentIndex()
        if idx < 0:
            return None
        return self.group_combo.currentData()

    def _reset_mouse_list(self) -> None:
        df = self._df
        if df is None or df.empty:
            self._mouse_ids = []
            self._current_page = 0
            return

        g = self._current_group_filter()
        if g is None or "group" not in df.columns:
            sub = df
        else:
            sub = df[df["group"] == g]

        self._mouse_ids = sorted(sub["mouse_id"].unique())
        self._current_page = 0

    def _update_page_controls(self) -> None:
        n_mice = len(self._mouse_ids)
        if n_mice == 0:
            self.page_spin.setMaximum(1)
            self.page_spin.setValue(1)
            self.page_label.setText("Page 0 / 0")
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            return

        # Show Mice Per Page amount of mice per group
        n_pages = int(np.ceil(n_mice / self.MICE_PER_PAGE))
        # Ensure current page is in bounds
        self._current_page = max(0, min(self._current_page, n_pages - 1))

        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(n_pages)
        self.page_spin.setValue(self._current_page + 1)  # 1-based for user
        self.page_spin.blockSignals(False)

        self.page_label.setText(f"Page {self._current_page + 1} / {n_pages}")

        self.prev_button.setEnabled(self._current_page > 0)
        self.next_button.setEnabled(self._current_page < n_pages - 1)

    def _get_mice_for_current_page(self) -> List[str]:
        start = self._current_page * self.MICE_PER_PAGE
        end = start + self.MICE_PER_PAGE
        return self._mouse_ids[start:end]

    def _on_group_changed(self) -> None:
        if self._df is None:
            return
        self._reset_mouse_list()
        self._update_page_controls()
        self._update_all_plots()

    def _on_prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._update_page_controls()
            self._update_all_plots()

    def _on_next_page(self) -> None:
        n_mice = len(self._mouse_ids)
        if n_mice == 0:
            return
        n_pages = int(np.ceil(n_mice / self.MICE_PER_PAGE))
        if self._current_page < n_pages - 1:
            self._current_page += 1
            self._update_page_controls()
            self._update_all_plots()

    def _on_page_spin_changed(self, value: int) -> None:
        # spinbox is 1-based; internal page is 0-based
        self._current_page = max(0, value - 1)
        self._update_page_controls()
        self._update_all_plots()

        
    # ------------------------------------------------------------------
    # Plotting
    # ------------------------------------------------------------------
    def _clear_plots(self) -> None:
        for p in self._plots.values():
            p.clear()
        #self.legend_label.setText("Mice on this page:")

    def _update_all_plots(self) -> None:

        if self.offset_btn.isChecked():
            df = self._df_offset
        else:
            df = self._df

        if df is None or df.empty:
            self._clear_plots()
            return

        mice = self._get_mice_for_current_page()
        if not mice:
            self._clear_plots()
            return

        # Filter by group (if any) and mice on this page
        g = self._current_group_filter()
        sub = df.copy()
        if g is not None and "group" in sub.columns:
            sub = sub[sub["group"] == g]
        sub = sub[sub["mouse_id"].isin(mice)]

        if sub.empty:
            self._clear_plots()
            return

        # Ensure we have time column
        if "bin_start_hr" in sub.columns:
            x_col = "bin_start_hr"
        elif "bin_start_sec" in sub.columns:
            sub = sub.assign(bin_start_hr=sub["bin_start_sec"] / 3600.0)
            x_col = "bin_start_hr"
        else:
            raise ValueError("sleep metrics df must have bin_start_hr or bin_start_sec")

        # Clear all plots before drawing
        for p in self._plots.values():
            p.clear()

        """# Update legend label: list mice on this page with their colors
        legend_lines = []
        for mid in mice:
            color = color_from_mouse_id(mid)
            legend_lines.append(f"{mid} (rgb{color})")"""
        mouse_colors = self._build_mouse_color_map(mice)
        self._update_color_legend(mice, mouse_colors)




        # Draw: loop over state x metric; within each panel, draw lines for each mouse
        for state in self.STATE_ORDER:
            for metric, _metric_label in self.METRIC_ORDER:
                p = self._plots.get((metric, state))
                if p is None:
                    continue
                if metric == self.METRIC_ORDER[-1][0]:
                    label = "Time (h)" if self.offset_btn.isChecked() else "Time (h) From EEG Start"
                    p.setLabel("bottom", label)

                #panel_df = sub[(sub["state"] == state) & sub[metric].notna()]
                panel_df = sub[(sub["state"] == state)]

                if panel_df.empty:
                    continue

                
                for mid in mice:
                    df_mouse = panel_df[panel_df["mouse_id"] == mid].copy()
                    if df_mouse.empty:
                        continue
                    df_mouse[metric] = df_mouse[metric].fillna(0)
                    df_mouse = df_mouse.sort_values(x_col)
                    x = df_mouse[x_col].to_numpy()
                    y = df_mouse[metric].to_numpy()

                    color = mouse_colors[mid]
                    pen = pg.mkPen(color=color, width=1.5)
                    p.plot(x, y, pen=pen)

        """# Optional: link x-axes across plots for synchronized zoom/pan
        # (link all plots to the top-left one, for example)
        base_plot = self._plots.get((self.STATE_ORDER[0], self.METRIC_ORDER[0][0]))
        if base_plot is not None:
            for key, p in self._plots.items():
                if p is base_plot:
                    continue
                p.setXLink(base_plot)"""
        



    def _build_mouse_color_map(self, mice: List[str]) -> dict:
        """
        Build a color map for the given list of mice using tab10 or tab20.
        Returns: {mouse_id: (r, g, b)}
        """
        n = len(mice)

        if n <= 10:
            cmap = mpl.colormaps["tab10"]
        else:
            cmap = mpl.colormaps["tab20"]

        color_map = {}
        for i, mid in enumerate(mice):
            rgba = cmap(i)
            rgb = tuple(int(255 * c) for c in rgba[:3])
            color_map[mid] = rgb

        return color_map

    def _update_color_legend(self, mice: List[str], mouse_colors: dict) -> None:        
        """Rebuild color legend for the currently displayed mice."""

        # Clear old legend entries
        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for mid in mice:
            color = mouse_colors[mid]

            # Small colored line box
            swatch = QFrame()
            swatch.setFixedSize(30, 4)
            swatch.setStyleSheet(
                f"background-color: rgb({color[0]}, {color[1]}, {color[2]});"
            )

            label = QLabel(str(mid))

            entry_layout = QHBoxLayout()
            entry_layout.setContentsMargins(0, 0, 0, 0)
            entry_layout.setSpacing(6)
            entry_layout.addWidget(swatch)
            entry_layout.addWidget(label)

            entry_widget = QWidget()
            entry_widget.setLayout(entry_layout)

            self.legend_layout.addWidget(entry_widget)

        self.legend_layout.addStretch(1)