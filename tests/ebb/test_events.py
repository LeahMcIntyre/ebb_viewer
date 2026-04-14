from datetime import datetime, time as dtime
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from ebb.masking import swd, time_of_day_mask, hour_window_mask


def test_swd_empty_mat_returns_all_true(tmp_path: Path):
    p = tmp_path / "swds.mat"
    savemat(p, {"DEL_ts": np.empty((0, 2))})

    n = 1000
    mask = swd(p, n_samples=n, fs=250, label="DEL_ts", pad_sec=0)

    assert mask.dtype == bool
    assert mask.size == n
    assert mask.all()


def test_swd_intervals_become_false(tmp_path: Path):
    p = tmp_path / "swds.mat"
    # one interval: 1.0s to 2.0s
    savemat(p, {"DEL_ts": np.array([[1.0, 2.0]])})

    fs = 250
    n = 2500  # 10 seconds
    mask = swd(p, n_samples=n, fs=fs, label="DEL_ts", pad_sec=0)

    # samples [10, 20) should be False
    assert mask[:250].all()
    assert (~mask[250:500]).all()
    assert mask[500:].all()


# ── time_of_day_mask ─────────────────────────────────────────────────────────

FS = 250  # samples/s

# Helper: recording starts at 2024-01-01 06:00:00 (6 AM)
_START = datetime(2024, 1, 1, 6, 0, 0)


def _n(seconds: float) -> int:
    return int(seconds * FS)


def test_tod_basic_window_shape_and_dtype():
    # 4-hour recording; 08:00–20:00 window
    n = _n(4 * 3600)
    mask = time_of_day_mask(_START, n, FS, dtime(8, 0), dtime(20, 0))
    assert mask.shape == (n,)
    assert mask.dtype == bool


def test_tod_samples_inside_window_are_true():
    # Recording starts 06:00, length 6h → ends 12:00.  Window 08:00–20:00.
    # First 2h (samples 0–1_800_000) = before window → False
    # Last 4h = inside window → True
    n = _n(6 * 3600)
    mask = time_of_day_mask(_START, n, FS, dtime(8, 0), dtime(20, 0))
    two_h = _n(2 * 3600)
    assert not mask[:two_h].any(), "samples before window start should be False"
    assert mask[two_h:].all(), "samples after window start should be True"


def test_tod_samples_outside_window_are_false():
    # Recording starts 06:00, length 1h → ends 07:00.  Window 08:00–20:00.
    n = _n(3600)
    mask = time_of_day_mask(_START, n, FS, dtime(8, 0), dtime(20, 0))
    assert not mask.any(), "all samples before window start should be False"


def test_tod_midnight_wrapping_window():
    # Window 20:00–08:00 (dark phase).  Recording starts 18:00, length 12h → ends 06:00.
    # d=0 window: [20:00 day 0, 08:00 day 1] → samples [2h, 12h) should be True
    # Samples 0–2h (18:00–20:00) → outside window → False
    start = datetime(2024, 1, 1, 18, 0, 0)
    n = _n(12 * 3600)
    mask = time_of_day_mask(start, n, FS, dtime(20, 0), dtime(8, 0))
    two_h = _n(2 * 3600)
    assert not mask[:two_h].any(), "samples before 20:00 should be False"
    assert mask[two_h:].all(), "samples from 20:00 onward should be True"


def test_tod_multi_day_window_repeats():
    # 3-day recording starting at 00:00.  Window 08:00–09:00 (1h per day).
    start = datetime(2024, 1, 1, 0, 0, 0)
    n = _n(3 * 24 * 3600)
    mask = time_of_day_mask(start, n, FS, dtime(8, 0), dtime(9, 0))
    for day in range(3):
        offset_s = day * 24 * 3600
        in_start = _n(offset_s + 8 * 3600)
        in_end = _n(offset_s + 9 * 3600)
        # inside the 1h window
        assert mask[in_start:in_end].all(), f"day {day} window should be True"
        # just before the window
        if in_start > 0:
            assert not mask[in_start - 1], f"sample before day {day} window should be False"


def test_tod_selected_days_filters_correctly():
    # 3-day recording.  Window 08:00–09:00.  Only day 1 selected.
    start = datetime(2024, 1, 1, 0, 0, 0)
    n = _n(3 * 24 * 3600)
    mask = time_of_day_mask(start, n, FS, dtime(8, 0), dtime(9, 0), selected_days=[1])
    for day in range(3):
        offset_s = day * 24 * 3600
        in_start = _n(offset_s + 8 * 3600)
        in_end = _n(offset_s + 9 * 3600)
        if day == 1:
            assert mask[in_start:in_end].all(), "selected day should be True"
        else:
            assert not mask[in_start:in_end].any(), "unselected day should be False"


def test_tod_no_intervals_returns_all_false():
    # Window entirely in the future relative to recording
    start = datetime(2024, 1, 1, 0, 0, 0)
    n = _n(3600)  # 1-hour recording ending at 01:00
    mask = time_of_day_mask(start, n, FS, dtime(8, 0), dtime(9, 0))
    assert not mask.any()


# ── hour_window_mask ──────────────────────────────────────────────────────────

# 72h recording starting at 10:30, window 10:00–12:00.
# Day 0: 10:30–12:00 (partial start), Days 1–2: full, Day 3: 10:00–10:30 (partial end).
_HW_START = datetime(2024, 1, 1, 10, 30, 0)
_HW_N = _n(72 * 3600)


def test_hw_returns_correct_types():
    mask, windows = hour_window_mask(_HW_START, _HW_N, FS, [(10.0, 12.0)])
    assert mask.shape == (_HW_N,)
    assert mask.dtype == bool
    assert isinstance(windows, list)
    assert all(isinstance(w, tuple) and len(w) == 2 for w in windows)


def test_hw_partial_edge_days():
    _, windows = hour_window_mask(_HW_START, _HW_N, FS, [(10.0, 12.0)])
    assert len(windows) == 4
    full_dur = 120 * 60  # 2 hours in seconds

    ws0, we0 = windows[0]
    assert ws0 == datetime(2024, 1, 1, 10, 30), "day 0 should start at recording start"
    assert we0 == datetime(2024, 1, 1, 12,  0), "day 0 should end at window end"
    assert (we0 - ws0).total_seconds() < full_dur, "day 0 should be partial"

    ws3, we3 = windows[3]
    assert ws3 == datetime(2024, 1, 4, 10,  0), "day 3 should start at window start"
    assert we3 == datetime(2024, 1, 4, 10, 30), "day 3 should end at recording end"
    assert (we3 - ws3).total_seconds() < full_dur, "day 3 should be partial"


def test_hw_full_middle_days():
    _, windows = hour_window_mask(_HW_START, _HW_N, FS, [(10.0, 12.0)])
    full_dur = 120 * 60
    for ws, we in windows[1:3]:
        assert (we - ws).total_seconds() == full_dur, "middle days should be full windows"


def test_hw_mask_samples_correct():
    mask, windows = hour_window_mask(_HW_START, _HW_N, FS, [(10.0, 12.0)])
    expected = sum(int((we - ws).total_seconds() * FS) for ws, we in windows)
    # allow ±1 sample per window for floor/ceil rounding
    assert abs(mask.sum() - expected) <= len(windows)


def test_hw_selected_days_filters():
    _, windows_all = hour_window_mask(_HW_START, _HW_N, FS, [(10.0, 12.0)])
    mask, windows = hour_window_mask(_HW_START, _HW_N, FS, [(10.0, 12.0)], [1, 2])
    assert len(windows) == 2
    assert windows == windows_all[1:3]
    # samples outside days 1 and 2 should be False
    day1_start = _n(int((windows[0][0] - _HW_START).total_seconds()))
    assert not mask[:day1_start].any()


def test_hw_multiple_windows_union():
    # 24h recording starting midnight; windows [2, 4] and [10, 12]
    start = datetime(2024, 1, 1, 0, 0)
    n = _n(24 * 3600)
    mask, windows = hour_window_mask(start, n, FS, [(2.0, 4.0), (10.0, 12.0)])
    assert len(windows) == 2
    assert mask[_n(2 * 3600):_n(4 * 3600)].all()
    assert mask[_n(10 * 3600):_n(12 * 3600)].all()
    assert not mask[_n(4 * 3600):_n(10 * 3600)].any()
    assert not mask[_n(12 * 3600):].any()


def test_hw_no_overlap_returns_empty():
    # 1-hour recording 10:30–11:30; window 12:00–14:00 — no overlap
    n = _n(3600)
    mask, windows = hour_window_mask(_HW_START, n, FS, [(12.0, 14.0)])
    assert not mask.any()
    assert windows == []
