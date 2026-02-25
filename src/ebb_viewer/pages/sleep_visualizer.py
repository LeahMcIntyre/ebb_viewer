from __future__ import annotations

from typing import Optional, List
from pathlib import Path

import numpy as np
import pandas as pd

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QLabel, QPushButton, QSizePolicy,
    QFileDialog, QMessageBox
)

import pyqtgraph as pg

from ebb.process.sleep_compute import compute_sleep_bins_df

import hashlib
def color_from_mouse_id(mouse_id):
    h = hashlib.md5(str(mouse_id).encode()).hexdigest()
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return (r, g, b)

class SleepMetricsPage(QWidget):
    """
    Page to visualize sleep metrics (frac_time, n_bouts, mean_bout_sec)
    over time, with a user-selected spindle outputs directory.
    """

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._df: Optional[pd.DataFrame] = None
        self._current_dir: Optional[Path] = None
        self._building_controls = False
        self._legend = None

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

        # --- control panel ---
        controls = QWidget(self)
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.mouse_combo = QComboBox()
        self.mouse_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        form.addRow(QLabel("Mouse:"), self.mouse_combo)

        self.group_combo = QComboBox()
        self.group_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        form.addRow(QLabel("Group:"), self.group_combo)

        self.state_combo = QComboBox()
        form.addRow(QLabel("State:"), self.state_combo)

        self.metric_combo = QComboBox()
        self.metric_combo.addItem("Fraction time", userData="frac_time")
        self.metric_combo.addItem("# Bouts", userData="n_bouts")
        self.metric_combo.addItem("Mean bout duration (sec)", userData="mean_bout_sec")
        form.addRow(QLabel("Metric:"), self.metric_combo)

        """self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItem("Individual mice", userData="individual")
        self.view_mode_combo.addItem("Group mean ± SEM", userData="group_mean")
        form.addRow(QLabel("View:"), self.view_mode_combo)"""

        controls_layout.addLayout(form)

        self.refresh_button = QPushButton("Refresh")
        controls_layout.addWidget(self.refresh_button, alignment=Qt.AlignmentFlag.AlignBottom)

        layout.addWidget(controls)

        # --- plot ---
        self.plot = pg.PlotWidget()
        self.plot.setBackground("w")
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setLabel("bottom", "Time", units="h")
        self.plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout.addWidget(self.plot, stretch=1)

    def _wire(self) -> None:
        self.dir_button.clicked.connect(self._on_choose_directory)

        self.mouse_combo.currentIndexChanged.connect(self.update_plot)
        self.group_combo.currentIndexChanged.connect(self.update_plot)
        self.state_combo.currentIndexChanged.connect(self.update_plot)
        self.metric_combo.currentIndexChanged.connect(self.update_plot)
        #self.view_mode_combo.currentIndexChanged.connect(self.update_plot)
        self.refresh_button.clicked.connect(self.update_plot)

    # ------------------------------------------------------------------
    # Directory selection + loading
    # ------------------------------------------------------------------
    def _on_choose_directory(self) -> None:
        spindle_root = self.project_root / "spindle_outputs" 
        if spindle_root.exists() and spindle_root.is_dir():
            start_dir = spindle_root
        else:
            start_dir = self.project_root

        start_dir = str(start_dir)
        dirname = QFileDialog.getExistingDirectory(
            self,
            "Select spindle outputs directory",
            start_dir,
        )
        if not dirname:
            return

        self._current_dir = Path(dirname)
        self.dir_label.setText(str(self._current_dir))


        try:
            df = compute_sleep_bins_df(self._current_dir)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error loading sleep metrics",
                f"Could not load sleep metrics from:\n{self._current_dir}\n\n{e}",
            )
            self._df = None
            self._clear_controls_and_plot()
            return

        self._df = df
        self._populate_controls_from_df()
        self.update_plot()

    # ------------------------------------------------------------------
    # Controls / plotting
    # ------------------------------------------------------------------
    def _clear_controls_and_plot(self) -> None:
        self.mouse_combo.clear()
        self.group_combo.clear()
        self.state_combo.clear()
        self.plot.clear()

    def _populate_controls_from_df(self) -> None:
        df = self._df
        if df is None or df.empty:
            self._clear_controls_and_plot()
            return

        self._building_controls = True

        # Mouse
        self.mouse_combo.clear()
        self.mouse_combo.addItem("All mice", userData=None)
        for mid in sorted(df["mouse_id"].unique()):
            self.mouse_combo.addItem(str(mid), userData=mid)

        # Group
        self.group_combo.clear()
        self.group_combo.addItem("All groups", userData=None)
        if "group" in df.columns:
            for g in sorted(df["group"].dropna().unique()):
                self.group_combo.addItem(str(g), userData=g)

        # State
        self.state_combo.clear()
        for s in sorted(df["state"].unique()):
            self.state_combo.addItem(str(s))

        self._building_controls = False

    def update_plot(self) -> None:
        if self._building_controls:
            return

        df = self._df
        if df is None or df.empty:
            self.plot.clear()
            return

        metric = self.metric_combo.currentData()
        state = self.state_combo.currentText()
        #view_mode = self.view_mode_combo.currentData()
        selected_mouse = self.mouse_combo.currentData()
        selected_group = self.group_combo.currentData()

        sub = df.copy()
        if state:
            sub = sub[sub["state"] == state]
        if selected_group is not None and "group" in sub.columns:
            sub = sub[sub["group"] == selected_group]
        if selected_mouse is not None:
            sub = sub[sub["mouse_id"] == selected_mouse]

        if sub.empty or metric not in sub.columns:
            self.plot.clear()
            return

        self.plot.clear()

        # x-axis
        if "bin_start_hr" in sub.columns:
            x_col = "bin_start_hr"
        elif "bin_start_sec" in sub.columns:
            sub = sub.assign(bin_start_hr=sub["bin_start_sec"] / 3600.0)
            x_col = "bin_start_hr"
        else:
            raise ValueError("sleep metrics df must have bin_start_hr or bin_start_sec")

        # y-label
        if metric == "frac_time":
            self.plot.setLabel("left", "Fraction of time")
        elif metric == "n_bouts":
            self.plot.setLabel("left", "Number of bouts")
        elif metric == "mean_bout_sec":
            self.plot.setLabel("left", "Mean bout duration", units="s")
        else:
            self.plot.setLabel("left", metric)

        self.plot.addLegend(offset=(10, 10))

        for mid, df_mouse in sub.groupby("mouse_id"):
            df_mouse = df_mouse.sort_values(x_col)
            x = df_mouse[x_col].to_numpy()
            y = df_mouse[metric].to_numpy()

            color = color_from_mouse_id(mid)
            pen = pg.mkPen(color=color, width=2)
            self.plot.plot(x, y, pen=pen, name=str(mid))

        
        self.plot.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=True)