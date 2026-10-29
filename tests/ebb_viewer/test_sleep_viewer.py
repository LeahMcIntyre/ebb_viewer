"""Tests for ``widgets/sleep_viewer.py``: the plot bins the recording into 2 hour bins."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ebb_viewer.widgets.sleep_viewer import SleepPopup


def test_plot_sleep_uses_two_hour_bins(qapp, tmp_path):
    n_epochs = 6 * 900  # 6 h of 4 s epochs
    states = np.tile(list("wwnnnnrn"), n_epochs // 8 + 1)[:n_epochs]
    csv = tmp_path / "AM001_labels.csv"
    pd.DataFrame({"state": states, "noise_prob": 0.0, "final_state": states}).to_csv(
        csv, index=False
    )

    popup = SleepPopup()
    popup.plot_sleep(csv)

    wake_fraction_ax = popup.fig.axes[0]  # row 0 (fraction of time), column 0 (Wake)
    hours = wake_fraction_ax.lines[0].get_xdata()
    assert list(hours) == [0, 2, 4]  # three 2 h bins over 6 h
