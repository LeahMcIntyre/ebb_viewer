import warnings
from datetime import datetime
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from ebb.masking import hour_window_mask, swd, time_of_day_mask
from ebb.masking.events import drinking_mask


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


def test_swd_boundary_sample_precision(tmp_path: Path):
    # Interval 2.0s–4.0s; verify the exact boundary samples.
    p = tmp_path / "swds.mat"
    savemat(p, {"DEL_ts": np.array([[2.0, 4.0]])})
    fs = 250
    n = fs * 10
    mask = swd(p, n_samples=n, fs=fs, label="DEL_ts", pad_sec=0)

    start = int(2.0 * fs)
    end = int(4.0 * fs)

    assert mask[start - 1], "sample just before interval should be True"
    assert not mask[start], "first sample of interval should be False"
    assert not mask[end - 1], "last sample of interval should be False"
    assert mask[end], "first sample after interval should be True"


def test_swd_multiple_intervals(tmp_path: Path):
    # Two separate intervals: 1–2s and 5–6s.
    p = tmp_path / "swds.mat"
    savemat(p, {"DEL_ts": np.array([[1.0, 2.0], [5.0, 6.0]])})
    fs = 250
    n = fs * 10
    mask = swd(p, n_samples=n, fs=fs, label="DEL_ts", pad_sec=0)

    assert mask[:fs].all(), "before first interval should be True"
    assert not mask[fs : 2 * fs].any(), "first interval should be False"
    assert mask[2 * fs : 5 * fs].all(), "between intervals should be True"
    assert not mask[5 * fs : 6 * fs].any(), "second interval should be False"
    assert mask[6 * fs :].all(), "after second interval should be True"


def test_swd_adjacent_intervals_merged(tmp_path: Path):
    # Two touching intervals (end of first == start of second) should merge.
    p = tmp_path / "swds.mat"
    savemat(p, {"DEL_ts": np.array([[1.0, 2.0], [2.0, 3.0]])})
    fs = 250
    n = fs * 10
    mask = swd(p, n_samples=n, fs=fs, label="DEL_ts", pad_sec=0)

    assert not mask[fs : 3 * fs].any(), "merged interval 1–3s should all be False"
    assert mask[3 * fs :].all(), "after merged interval should be True"


def test_swd_pad_sec_extends_interval(tmp_path: Path):
    # Interval 3–4s with pad_sec=1 should mask 2–5s.
    p = tmp_path / "swds.mat"
    savemat(p, {"DEL_ts": np.array([[3.0, 4.0]])})
    fs = 250
    n = fs * 10
    mask = swd(p, n_samples=n, fs=fs, label="DEL_ts", pad_sec=1)

    assert mask[: 2 * fs].all(), "before padded interval should be True"
    assert not mask[2 * fs : 5 * fs].any(), "padded interval 2–5s should be False"
    assert mask[5 * fs :].all(), "after padded interval should be True"


def test_swd_pad_clipped_at_recording_start(tmp_path: Path):
    # Interval at 0.5s with pad_sec=1; pad extends before sample 0 — should clip.
    p = tmp_path / "swds.mat"
    savemat(p, {"DEL_ts": np.array([[0.5, 1.0]])})
    fs = 250
    n = fs * 10
    mask = swd(p, n_samples=n, fs=fs, label="DEL_ts", pad_sec=1)

    assert not mask[0], "sample 0 should be False (pad clipped to start)"
    assert mask[2 * fs :].all(), "after padded end (1.0+1.0=2.0s) should be True"
    assert len(mask) == n


def test_swd_interval_clipped_at_recording_end(tmp_path: Path):
    # Interval 8–12s; recording is only 10s — tail should be clipped.
    p = tmp_path / "swds.mat"
    savemat(p, {"DEL_ts": np.array([[8.0, 12.0]])})
    fs = 250
    n = fs * 10
    mask = swd(p, n_samples=n, fs=fs, label="DEL_ts", pad_sec=0)

    assert mask[: 8 * fs].all(), "before interval should be True"
    assert not mask[8 * fs :].any(), "interval clipped to recording end should be False"
    assert len(mask) == n


def test_swd_1d_single_interval_shape(tmp_path: Path):
    # A single [start, stop] stored as a 1D array (scipy may squeeze it).
    p = tmp_path / "swds.mat"
    savemat(p, {"DEL_ts": np.array([2.0, 4.0])})  # 1D, not (1, 2)
    fs = 250
    n = fs * 10
    mask = swd(p, n_samples=n, fs=fs, label="DEL_ts", pad_sec=0)

    assert not mask[2 * fs : 4 * fs].any(), "1D single interval should be masked False"
    assert mask[: 2 * fs].all()
    assert mask[4 * fs :].all()


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
    assert we0 == datetime(2024, 1, 1, 12, 0), "day 0 should end at window end"
    assert (we0 - ws0).total_seconds() < full_dur, "day 0 should be partial"

    ws3, we3 = windows[3]
    assert ws3 == datetime(2024, 1, 4, 10, 0), "day 3 should start at window start"
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
    assert mask[_n(2 * 3600) : _n(4 * 3600)].all()
    assert mask[_n(10 * 3600) : _n(12 * 3600)].all()
    assert not mask[_n(4 * 3600) : _n(10 * 3600)].any()
    assert not mask[_n(12 * 3600) :].any()


def test_hw_no_overlap_returns_empty():
    # 1-hour recording 10:30–11:30; window 12:00–14:00 — no overlap
    n = _n(3600)
    mask, windows = hour_window_mask(_HW_START, n, FS, [(12.0, 14.0)])
    assert not mask.any()
    assert windows == []


# ── Sample-position correctness ───────────────────────────────────────────────
# These tests verify *which* samples are True/False, not just the count.


def test_hw_samples_inside_window_are_true():
    # 24h recording starting at midnight; window 02:00–04:00.
    # Samples at hour 1 (before), 3 (inside), 5 (after) should be F/T/F.
    start = datetime(2024, 1, 1, 0, 0, 0)
    n = _n(24 * 3600)
    mask, _ = hour_window_mask(start, n, FS, [(2.0, 4.0)])

    assert not mask[_n(1 * 3600)], "1h into recording (before window) should be False"
    assert mask[_n(3 * 3600)], "3h into recording (inside window) should be True"
    assert not mask[_n(5 * 3600)], "5h into recording (after window) should be False"


def test_hw_boundary_sample_precision():
    # Window 02:00–04:00; recording starts at midnight.
    # The first sample of the window (floor(2*3600*FS)) should be True.
    # The sample immediately before it should be False.
    # The last sample before window end (floor(4*3600*FS) - 1) should be True.
    # The sample at floor(4*3600*FS) should be False.
    start = datetime(2024, 1, 1, 0, 0, 0)
    n = _n(24 * 3600)
    mask, _ = hour_window_mask(start, n, FS, [(2.0, 4.0)])

    win_start_sample = int(2 * 3600 * FS)
    win_end_sample = int(4 * 3600 * FS)

    assert mask[win_start_sample], "first sample of window should be True"
    assert not mask[win_start_sample - 1], "sample just before window start should be False"
    assert mask[win_end_sample - 1], "last sample inside window should be True"
    assert not mask[win_end_sample], "first sample after window end should be False"


def test_hw_non_midnight_start_correct_samples():
    # Recording starts 10:30, window 10:00–12:00.
    # Day 0: window is clipped to [10:30, 12:00] → 1.5h of True starting at sample 0.
    # After 12:00, samples should be False until the next day's window.
    n = _n(4 * 3600)  # 4-hour recording (ends 14:30)
    mask, windows = hour_window_mask(_HW_START, n, FS, [(10.0, 12.0)])

    # Sample 0 is 10:30 — inside the day-0 window
    assert mask[0], "sample 0 (10:30) should be inside the clipped window"

    # Sample at 1.5h = 12:00 — just at window end, should be False
    end_sample = int(1.5 * 3600 * FS)
    assert not mask[end_sample], "sample at 12:00 (window end) should be False"

    # Sample at 2h (12:30) — outside any window
    assert not mask[_n(2 * 3600)], "sample at 12:30 should be False"

    # Day-0 window reported as starting at recording start (10:30)
    assert windows[0][0] == _HW_START, "day-0 window should start at recording start"
    assert windows[0][1] == datetime(2024, 1, 1, 12, 0), "day-0 window should end at 12:00"


def test_hw_overnight_window_samples():
    # Window (20, 6) = dark phase.  Recording starts 18:00, runs 24h.
    # Samples 0–2h (18:00–20:00) → False.
    # Samples from 2h onward (20:00–end, wrapping through midnight to 06:00) → True
    # until 06:00 on day 1, then False again.
    start = datetime(2024, 1, 1, 18, 0, 0)
    n = _n(24 * 3600)
    mask, windows = hour_window_mask(start, n, FS, [(20.0, 6.0)])

    assert not mask[_n(1 * 3600)], "18:00+1h = 19:00, before dark phase → False"
    assert mask[_n(3 * 3600)], "18:00+3h = 21:00, inside dark phase → True"
    assert mask[_n(11 * 3600)], "18:00+11h = 05:00, inside dark phase → True"
    assert not mask[_n(13 * 3600)], "18:00+13h = 07:00, after dark phase ends → False"

    # Boundary: 2h in is exactly 20:00 (window start)
    assert mask[_n(2 * 3600)], "sample at 20:00 (window start) should be True"
    assert not mask[_n(2 * 3600) - 1], "sample just before 20:00 should be False"


def test_hw_used_windows_cover_true_samples():
    # The union of used_windows datetimes should account for all True samples.
    start = datetime(2024, 1, 1, 0, 0, 0)
    n = _n(48 * 3600)
    mask, windows = hour_window_mask(start, n, FS, [(6.0, 8.0), (14.0, 16.0)])

    expected_true = sum(int((we - ws).total_seconds() * FS) for ws, we in windows)
    # Allow ±1 sample per window for floor/ceil rounding
    assert abs(int(mask.sum()) - expected_true) <= len(windows), (
        f"True sample count {mask.sum()} should be within {len(windows)} of "
        f"expected {expected_true} from used_windows"
    )


def test_hw_multiple_windows_no_bleed_between():
    # Windows [02:00–04:00] and [10:00–12:00]; samples between them should be False.
    start = datetime(2024, 1, 1, 0, 0, 0)
    n = _n(24 * 3600)
    mask, _ = hour_window_mask(start, n, FS, [(2.0, 4.0), (10.0, 12.0)])

    # Gap between the two windows: 04:00–10:00
    assert not mask[_n(4 * 3600) : _n(10 * 3600)].any(), (
        "samples between windows should all be False"
    )


def test_hw_selected_days_exact_sample_positions():
    # 3-day recording; window [08:00–09:00], only day 2 selected.
    # Days 0 and 1 windows should be entirely False.
    start = datetime(2024, 1, 1, 0, 0, 0)
    n = _n(3 * 24 * 3600)
    mask, _ = hour_window_mask(start, n, FS, [(8.0, 9.0)], selected_days=[2])

    for day in range(3):
        win_s = _n(day * 24 * 3600 + 8 * 3600)
        win_e = _n(day * 24 * 3600 + 9 * 3600)
        if day == 2:
            assert mask[win_s:win_e].all(), "day 2 window should be all True"
        else:
            assert not mask[win_s:win_e].any(), f"day {day} window should be all False"


# ---------------------------------------------------------------------------
# drinking_mask — resize to n_samples
# ---------------------------------------------------------------------------


def _write_drink_npy(tmp_path: Path, n_seconds: int) -> Path:
    """Write a 1Hz boolean .npy of length `n_seconds` with no drinking events."""
    p = tmp_path / "drink.npy"
    np.save(p, np.zeros(n_seconds, dtype=bool))
    return p


def test_drinking_mask_no_n_samples_unchanged(tmp_path: Path):
    """Without n_samples the output is len(.npy) * fs as before."""
    fs = 250
    p = _write_drink_npy(tmp_path, n_seconds=100)
    out = drinking_mask(p, fs=fs, pad_sec=0)
    assert out.size == 100 * fs


def test_drinking_mask_truncates_when_edf_shorter(tmp_path: Path):
    """When n_samples < natural output, tail is sliced off; no warning within tolerance."""
    fs = 250
    p = _write_drink_npy(tmp_path, n_seconds=100)
    target = 100 * fs - fs  # 1s shorter — inside 2s tolerance
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning would fail
        out = drinking_mask(p, fs=fs, pad_sec=0, n_samples=target)
    assert out.size == target


def test_drinking_mask_pads_when_edf_longer(tmp_path: Path):
    """When n_samples > natural output, tail is padded with True (keep)."""
    fs = 250
    p = _write_drink_npy(tmp_path, n_seconds=100)
    target = 100 * fs + fs  # 1s longer — inside 2s tolerance
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = drinking_mask(p, fs=fs, pad_sec=0, n_samples=target)
    assert out.size == target
    assert out[-fs:].all(), "padded tail should be True (keep)"


def test_drinking_mask_warns_when_mismatch_exceeds_tolerance(tmp_path: Path):
    """Mismatches larger than 2s emit a UserWarning but still resize."""
    fs = 250
    p = _write_drink_npy(tmp_path, n_seconds=100)
    target = 100 * fs - 10 * fs  # 10s short
    with pytest.warns(UserWarning, match="size mismatch"):
        out = drinking_mask(p, fs=fs, pad_sec=0, n_samples=target)
    assert out.size == target


def test_drinking_mask_exact_match_no_warning(tmp_path: Path):
    """When sizes already match, no warning and no resize."""
    fs = 250
    p = _write_drink_npy(tmp_path, n_seconds=100)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = drinking_mask(p, fs=fs, pad_sec=0, n_samples=100 * fs)
    assert out.size == 100 * fs


def test_drinking_mask_preserves_leading_offset_pad_when_trimming(tmp_path: Path):
    """Offset's leading 'keep' pad is untouched when resize trims from the tail."""
    fs = 250
    # Make one drink event in the middle so the inverted mask has a real False span.
    arr = np.zeros(100, dtype=bool)
    arr[50] = True
    p = tmp_path / "drink.npy"
    np.save(p, arr)

    offset_sec = 5.0
    target = 100 * fs - fs  # trim 1s from tail
    out = drinking_mask(p, offset_sec=offset_sec, fs=fs, pad_sec=0, n_samples=target)
    assert out.size == target
    # Leading `offset_sec * fs` samples are the offset's "keep" pad → all True.
    assert out[: int(offset_sec * fs)].all()
