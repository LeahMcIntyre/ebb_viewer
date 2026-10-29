"""Tests for ``widgets/sleep_viewer.py``: metrics are computed on one state per second."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ebb.process.sleep_compute import compute_sleep_metrics_per_mouse
from ebb_viewer.widgets.sleep_viewer import metrics_per_second


def _sticky_states(n_epochs: int, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out, cur = [], "w"
    for _ in range(n_epochs):
        if rng.random() < 0.08:
            cur = str(rng.choice(["w", "n", "r"]))
        out.append(cur)
    return np.array(out)


def test_per_second_metrics_equal_the_per_epoch_metrics():
    states = _sticky_states(43200)  # 48 h of 4 s epochs
    per_second = metrics_per_second(states, bin_hours=2)
    per_epoch = compute_sleep_metrics_per_mouse(states, bin_hours=2, sample_rate_hz=0.25)
    keys = ["bin_start_hr", "state"]
    pd.testing.assert_frame_equal(
        per_second.sort_values(keys).reset_index(drop=True),
        per_epoch.sort_values(keys).reset_index(drop=True),
    )


def test_bins_hold_one_second_samples():
    per_second = metrics_per_second(np.array(["w"] * 1800), bin_hours=2)  # 2 h of epochs
    row = per_second[per_second["state"] == "w"].iloc[0]
    assert row["bin_start_sec"] == 0
    assert row["frac_time"] == 1.0
    assert row["mean_bout_sec"] == 7200.0  # one bout, measured in seconds
