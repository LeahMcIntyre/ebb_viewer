"""Modeless dialog showing per-state sleep metrics across binned hours.

Reads a SPINDLE scoring CSV and renders a 3x3 grid of plots: rows are metrics
(frac time / # bouts / mean bout duration) and columns are states (Wake/NREM/REM).
"""

from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas,
)
from matplotlib.backends.backend_qtagg import (
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure
from PyQt6 import QtWidgets

from ebb.process.sleep_compute import compute_sleep_metrics_per_mouse, read_rawstate_column


class SleepPopup(QtWidgets.QDialog):
    """3x3 grid plot of per-state sleep metrics across time bins."""

    STATE_ORDER = ["w", "n", "r"]
    STATE_DEF = {"w": "Wake", "n": "NREM", "r": "REM"}
    METRIC_ORDER = [
        ("frac_time", "Fraction of time"),
        ("n_bouts", "# bouts"),
        ("mean_bout_sec", "Mean bout duration (s)"),
    ]

    def __init__(self, parent=None, title="Sleep Data"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)

        self.fig = Figure(constrained_layout=True)
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas)

    def plot_sleep(self, state_path, bin_hours=2):
        """Render metrics for the SPINDLE scoring CSV at ``state_path``."""
        self.fig.clear()
        axarr = [self.fig.add_subplot(3, 3, i + 1) for i in range(9)]

        states = read_rawstate_column(state_path)
        adf = compute_sleep_metrics_per_mouse(states, bin_hours=bin_hours, sample_rate_hz=0.25)

        for j, (metric, metric_label) in enumerate(self.METRIC_ORDER):
            for i, state in enumerate(self.STATE_ORDER):
                ax = axarr[j * 3 + i]
                dm = adf[adf["state"] == state].copy()
                if not dm.empty:
                    dm[metric] = dm[metric].fillna(0)
                    dm = dm.sort_values("bin_start_hr")
                    ax.plot(dm["bin_start_hr"].to_numpy(), dm[metric].to_numpy())
                if j == 0:
                    ax.set_title(self.STATE_DEF[state])
                if i == 0:
                    ax.set_ylabel(metric_label)
                if j == len(self.METRIC_ORDER) - 1:
                    ax.set_xlabel("Time (hours)")
        self.canvas.draw_idle()
