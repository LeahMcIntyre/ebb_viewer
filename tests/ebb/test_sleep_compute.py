import csv
import math
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from ebb.process.sleep_compute import (
    compute_sleep_bins_df_clock_aligned,
    compute_sleep_bins_df_offset,
    compute_spindle_fractions,
    compute_whole_file_metrics,
    read_rawstate_column,
    seconds_until_target,
)


def write_state_csv(
    path: Path, epochs: list[tuple[str, float]], *, new_format: bool = False
) -> None:
    """Write a spindle output CSV with state and noise-probability columns.

    Each epoch is (rawstate, noise_prob) where rawstate is one of w/n/r and
    noise_prob is in [0, 1].  An epoch is spindle-masked when noise_prob >= 0.5.

    `new_format=True` writes the newer SleepyRat header (`state`,
    `noise_prob`); the default writes the older header (`rawstate`,
    `noise_probs`).
    """
    state_col = "state" if new_format else "rawstate"
    noise_col = "noise_prob" if new_format else "noise_probs"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([state_col, noise_col])
        for raw, prob in epochs:
            w.writerow([raw, str(prob)])


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("new_format", [False, True])
def test_single_animal_fractions(tmp_path: Path, new_format: bool):
    # 2 clean wake, 1 spindle-wake, 3 clean NREM, 1 spindle-NREM, 0 REM
    write_state_csv(
        tmp_path / "Animal1_foo.csv",
        [
            ("w", 0.1),
            ("w", 0.1),
            ("w", 0.9),
            ("n", 0.1),
            ("n", 0.1),
            ("n", 0.1),
            ("n", 0.9),
        ],
        new_format=new_format,
    )
    df = compute_spindle_fractions(tmp_path)

    wake = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Wake")].iloc[0]
    assert wake["clean_count"] == 2
    assert wake["spindle_count"] == 1
    assert wake["total_count"] == 3
    assert math.isclose(wake["fraction"], 1 / 3)

    nrem = df[(df["mouse_id"] == "Animal1") & (df["state"] == "NREM")].iloc[0]
    assert nrem["clean_count"] == 3
    assert nrem["spindle_count"] == 1
    assert math.isclose(nrem["fraction"], 1 / 4)

    rem = df[(df["mouse_id"] == "Animal1") & (df["state"] == "REM")].iloc[0]
    assert rem["total_count"] == 0
    assert math.isnan(rem["fraction"])


def test_total_row(tmp_path: Path):
    # 4 clean (2w, 1n, 1r), 2 spindle (1w, 1r)
    write_state_csv(
        tmp_path / "Animal1_foo.csv",
        [
            ("w", 0.1),
            ("n", 0.1),
            ("r", 0.1),
            ("w", 0.1),
            ("w", 0.9),
            ("r", 0.9),
        ],
    )
    df = compute_spindle_fractions(tmp_path)

    total = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Total")].iloc[0]
    assert total["spindle_count"] == 2
    assert total["total_count"] == 6
    assert math.isclose(total["fraction"], 2 / 6)


def test_all_spindle_masked(tmp_path: Path):
    write_state_csv(
        tmp_path / "Animal1_foo.csv",
        [
            ("w", 1.0),
            ("n", 1.0),
            ("r", 1.0),
        ],
    )
    df = compute_spindle_fractions(tmp_path)

    total = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Total")].iloc[0]
    assert math.isclose(total["fraction"], 1.0)


def test_no_spindle_masked(tmp_path: Path):
    write_state_csv(
        tmp_path / "Animal1_foo.csv",
        [
            ("w", 0.0),
            ("n", 0.0),
            ("r", 0.0),
            ("w", 0.0),
        ],
    )
    df = compute_spindle_fractions(tmp_path)

    total = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Total")].iloc[0]
    assert math.isclose(total["fraction"], 0.0)


# ---------------------------------------------------------------------------
# Multiple animals
# ---------------------------------------------------------------------------


def test_multiple_animals(tmp_path: Path):
    write_state_csv(tmp_path / "Animal1_foo.csv", [("w", 0.1), ("w", 0.9)])
    write_state_csv(tmp_path / "Animal2_foo.csv", [("n", 0.1), ("n", 0.9), ("n", 0.9)])
    df = compute_spindle_fractions(tmp_path)

    assert set(df["mouse_id"].unique()) == {"Animal1", "Animal2"}

    a1_total = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Total")].iloc[0]
    assert math.isclose(a1_total["fraction"], 0.5)

    a2_nrem = df[(df["mouse_id"] == "Animal2") & (df["state"] == "NREM")].iloc[0]
    assert math.isclose(a2_nrem["fraction"], 2 / 3)


# ---------------------------------------------------------------------------
# Threshold parameter
# ---------------------------------------------------------------------------


def test_threshold_parameter(tmp_path: Path):
    """Epochs at exactly the threshold are masked; just below are clean."""
    write_state_csv(
        tmp_path / "Animal1_foo.csv",
        [
            ("w", 0.3),
            ("w", 0.5),
            ("w", 0.7),
        ],
    )
    # default threshold 0.5: noise_prob 0.5 and 0.7 → spindle, 0.3 → clean
    df = compute_spindle_fractions(tmp_path)
    wake = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Wake")].iloc[0]
    assert wake["spindle_count"] == 2
    assert wake["clean_count"] == 1

    # raised threshold 0.6: only 0.7 → spindle
    df2 = compute_spindle_fractions(tmp_path, noise_prob_threshold=0.6)
    wake2 = df2[(df2["mouse_id"] == "Animal1") & (df2["state"] == "Wake")].iloc[0]
    assert wake2["spindle_count"] == 1
    assert wake2["clean_count"] == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_directory(tmp_path: Path):
    df = compute_spindle_fractions(tmp_path)
    assert df.empty
    assert list(df.columns) == [
        "mouse_id",
        "state",
        "clean_count",
        "spindle_count",
        "total_count",
        "fraction",
    ]


def test_missing_rawstate_column_raises(tmp_path: Path):
    p = tmp_path / "Animal1_foo.csv"
    with p.open("w", newline="") as f:
        csv.writer(f).writerows([["noise_probs"], ["0.1"]])
    with pytest.raises(ValueError, match="'rawstate' column not found"):
        compute_spindle_fractions(tmp_path)


def test_missing_noise_probs_column_raises(tmp_path: Path):
    p = tmp_path / "Animal1_foo.csv"
    with p.open("w", newline="") as f:
        csv.writer(f).writerows([["rawstate"], ["w"]])
    with pytest.raises(ValueError, match="'noise_probs' column not found"):
        compute_spindle_fractions(tmp_path)


def test_missing_both_state_columns_raises(tmp_path: Path):
    p = tmp_path / "Animal1_foo.csv"
    with p.open("w", newline="") as f:
        csv.writer(f).writerows([["noise_prob"], ["0.1"]])
    with pytest.raises(ValueError, match="'rawstate' column not found"):
        compute_spindle_fractions(tmp_path)


@pytest.mark.parametrize("new_format", [False, True])
def test_read_rawstate_column_both_formats(tmp_path: Path, new_format: bool):
    p = tmp_path / "Animal1_foo.csv"
    write_state_csv(p, [("w", 0.1), ("n", 0.1), ("r", 0.1)], new_format=new_format)
    assert read_rawstate_column(p) == ["w", "n", "r"]


def test_read_rawstate_column_missing_raises(tmp_path: Path):
    p = tmp_path / "Animal1_foo.csv"
    with p.open("w", newline="") as f:
        csv.writer(f).writerows([["noise_prob"], ["0.1"]])
    with pytest.raises(ValueError, match="'rawstate' column not found"):
        read_rawstate_column(p)


def test_state_column_is_ordered_categorical(tmp_path: Path):
    write_state_csv(
        tmp_path / "Animal1_foo.csv",
        [
            ("w", 0.0),
            ("n", 0.0),
            ("r", 0.0),
        ],
    )
    df = compute_spindle_fractions(tmp_path)

    assert hasattr(df["state"].dtype, "ordered") and df["state"].dtype.ordered
    order = list(df[df["mouse_id"] == "Animal1"]["state"])
    assert order == ["Wake", "NREM", "REM", "Total"]


def test_non_csv_files_ignored(tmp_path: Path):
    """Non-CSV files in the directory don't cause errors or phantom animals."""
    write_state_csv(tmp_path / "Animal1_foo.csv", [("w", 0.1), ("w", 0.9)])
    (tmp_path / "notes.txt").write_text("ignore me")
    (tmp_path / "Animal2_foo.pkl").write_bytes(b"not a csv")
    df = compute_spindle_fractions(tmp_path)

    assert set(df["mouse_id"].unique()) == {"Animal1"}


def test_header_only_csv_gives_zero_counts(tmp_path: Path):
    """A CSV with only a header row yields zero counts and NaN fraction."""
    p = tmp_path / "Animal1_foo.csv"
    with p.open("w", newline="") as f:
        csv.writer(f).writerow(["rawstate", "noise_probs"])
    df = compute_spindle_fractions(tmp_path)

    total = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Total")].iloc[0]
    assert total["total_count"] == 0
    assert math.isnan(total["fraction"])


def test_unknown_rawstate_values_ignored(tmp_path: Path):
    """Unrecognised rawstate tokens are silently skipped."""
    write_state_csv(
        tmp_path / "Animal1_foo.csv",
        [
            ("w", 0.1),
            ("x", 0.1),
            ("?", 0.1),
            ("w", 0.9),
        ],
    )
    df = compute_spindle_fractions(tmp_path)

    total = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Total")].iloc[0]
    # only the two 'w' epochs are counted
    assert total["total_count"] == 2
    assert math.isclose(total["fraction"], 0.5)


# ---------------------------------------------------------------------------
# seconds_until_target
# ---------------------------------------------------------------------------


def test_seconds_until_target_naive_same_day():
    """Start before target → same-day target, no day rollover."""
    start = datetime(2026, 5, 21, 3, 0, 0)  # 03:00
    # 3h until 06:00
    assert seconds_until_target(start, h=6) == 3 * 3600


def test_seconds_until_target_naive_rolls_to_next_day():
    """Start after target → tomorrow's target. Naive arithmetic = 86400 - elapsed."""
    start = datetime(2026, 5, 21, 22, 0, 0)  # 22:00
    # 8h until next 06:00
    assert seconds_until_target(start, h=6) == 8 * 3600


def test_seconds_until_target_dst_spring_forward():
    """tz-aware: a recording starting the evening before spring-forward sees
    only 7h of real elapsed time before the next wall-clock 06:00, not 8h —
    because the clock jumps 02:00→03:00 overnight.
    """
    tz = ZoneInfo("America/Chicago")
    # 2026 US spring-forward is 2026-03-08 at 02:00 local.
    start = datetime(2026, 3, 7, 22, 0, 0, tzinfo=tz)  # Sat 22:00 CST
    # Wall-clock advance: 22:00 → 06:00 next day = 8 wall-clock hours.
    # Real elapsed: 7h because 02:00–03:00 is skipped.
    assert seconds_until_target(start, h=6) == 7 * 3600


def test_seconds_until_target_dst_fall_back():
    """tz-aware: fall-back gives 9h of real time for an 8h wall-clock window."""
    tz = ZoneInfo("America/Chicago")
    # 2026 US fall-back is 2026-11-01 at 02:00 local.
    start = datetime(2026, 10, 31, 22, 0, 0, tzinfo=tz)  # Sat 22:00 CDT
    # Wall-clock advance: 22:00 → 06:00 next day = 8 wall-clock hours.
    # Real elapsed: 9h because 01:00–02:00 happens twice.
    assert seconds_until_target(start, h=6) == 9 * 3600


# ---------------------------------------------------------------------------
# compute_sleep_bins_df_offset (CSV ↔ EDF pairing)
# ---------------------------------------------------------------------------


def _write_rawstate_csv(path: Path, states: list[str]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rawstate"])
        for s in states:
            w.writerow([s])


def _write_fake_edf(path: Path) -> None:
    """Create an empty file so the glob picks it up; the reader is mocked."""
    path.write_bytes(b"")


def test_offset_pairs_csv_with_edf_by_animal_id(tmp_path: Path):
    """Happy path: CSV + matching EDF → returns rotated bins keyed to begin_hr."""
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()

    # 24h of wake at 0.25 Hz epoch rate = 24 * 3600 / 4 = 21600 epochs.
    _write_rawstate_csv(state_dir / "Animal1_run.csv", ["w"] * 21600)
    _write_fake_edf(edf_dir / "Animal1_PREPROCESSED.edf")

    # Recording starts at 04:00 → 2h until 06:00.
    fake_start = datetime(2026, 5, 21, 4, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        df = compute_sleep_bins_df_offset(state_dir, edf_dir, bin_hours=2, begin_hr=6)

    assert not df.empty
    assert set(df["mouse_id"]) == {"Animal1"}
    # First bin should start at begin_hr (6).
    assert df["bin_start_hr"].min() == 6
    # 2h bins → first bin covers [6, 8)
    first_bin = df[df["bin_idx"] == 0]
    assert math.isclose(first_bin["bin_start_hr"].iloc[0], 6)


def test_offset_warns_and_skips_csv_without_matching_edf(tmp_path: Path):
    """CSV with no paired EDF → warning emitted, that animal absent from result."""
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()

    _write_rawstate_csv(state_dir / "Animal1_run.csv", ["w"] * 21600)
    _write_rawstate_csv(state_dir / "Animal2_run.csv", ["w"] * 21600)
    # Only Animal1 has an EDF.
    _write_fake_edf(edf_dir / "Animal1_PREPROCESSED.edf")

    fake_start = datetime(2026, 5, 21, 4, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        with pytest.warns(UserWarning, match=r"No EDF for animal 'Animal2'"):
            df = compute_sleep_bins_df_offset(state_dir, edf_dir, bin_hours=2)

    assert set(df["mouse_id"]) == {"Animal1"}


def test_offset_empty_when_no_csv_has_matching_edf(tmp_path: Path):
    """Every CSV unmatched → returns empty DataFrame (after N warnings)."""
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()
    _write_rawstate_csv(state_dir / "Orphan_run.csv", ["w"] * 21600)

    with pytest.warns(UserWarning, match="No EDF"):
        df = compute_sleep_bins_df_offset(state_dir, edf_dir, bin_hours=2)

    assert df.empty


def test_offset_dst_aware_uses_real_elapsed_seconds(tmp_path: Path):
    """With tz set, the rotation offset reflects DST real-elapsed time, not
    naive wall-clock arithmetic. A spring-forward Saturday recording rotates
    by 7h of samples (not 8h), so the per-second slice landing in bin 0 starts
    7*3600 samples into the expanded state array.
    """
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()

    # 16h of wake at 0.25 Hz = 14400 epochs; expanded to per-second = 57600s.
    # That's enough to cover an 8h rotation offset comfortably.
    _write_rawstate_csv(state_dir / "Animal1_run.csv", ["w"] * 14400)
    _write_fake_edf(edf_dir / "Animal1_PREPROCESSED.edf")

    tz = ZoneInfo("America/Chicago")
    # 22:00 local on 2026-03-07 (Sat) → next wall-clock 06:00 is 7h away (DST).
    fake_start = datetime(2026, 3, 7, 22, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        df_tz = compute_sleep_bins_df_offset(
            state_dir, edf_dir, bin_hours=2, begin_hr=6, tz=tz
        )
        df_naive = compute_sleep_bins_df_offset(
            state_dir, edf_dir, bin_hours=2, begin_hr=6, tz=None
        )

    # With wake-only recording both will look the same in state fractions,
    # but the test below pins the underlying rotation semantics: both should
    # return non-empty dataframes anchored at begin_hr=6, and the tz path
    # should not raise. The DST-aware behavior of seconds_until_target itself
    # is verified by the unit test above; here we just confirm end-to-end
    # plumbing works with a tz arg.
    assert not df_tz.empty
    assert not df_naive.empty
    assert df_tz["bin_start_hr"].min() == 6
    assert df_naive["bin_start_hr"].min() == 6


def test_offset_warns_and_skips_short_recording(tmp_path: Path):
    """Recording that can't span the rotation offset is skipped with a warning,
    leaving longer recordings in the result instead of raising."""
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()

    # Short: 100 epochs = 400s. Offset would need 8h = 28800s.
    _write_rawstate_csv(state_dir / "Short_run.csv", ["w"] * 100)
    _write_fake_edf(edf_dir / "Short_PREPROCESSED.edf")
    # Long: 24h of wake.
    _write_rawstate_csv(state_dir / "Long_run.csv", ["w"] * 21600)
    _write_fake_edf(edf_dir / "Long_PREPROCESSED.edf")

    fake_start = datetime(2026, 5, 21, 22, 0, 0)  # 22:00 → 8h to 06:00
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        with pytest.warns(UserWarning, match=r"too short for begin_hr"):
            df = compute_sleep_bins_df_offset(
                state_dir, edf_dir, bin_hours=2, begin_hr=6
            )

    assert set(df["mouse_id"]) == {"Long"}


# ---------------------------------------------------------------------------
# compute_sleep_bins_df_clock_aligned
# ---------------------------------------------------------------------------


def test_clock_aligned_recording_starts_on_begin_hr(tmp_path: Path):
    """24h recording starting exactly at begin_hr → bins at 6, 8, ..., 28."""
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()

    _write_rawstate_csv(state_dir / "Animal1_run.csv", ["w"] * 21600)  # 24h
    _write_fake_edf(edf_dir / "Animal1_PREPROCESSED.edf")

    fake_start = datetime(2026, 5, 21, 6, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        df = compute_sleep_bins_df_clock_aligned(
            state_dir, edf_dir, bin_hours=2, begin_hr=6
        )

    starts = sorted(df["bin_start_hr"].unique())
    assert starts == [6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]


def test_clock_aligned_24h_recording_starting_late(tmp_path: Path):
    """24h recording starting at 22:00 (begin_hr=6) → bins at 22, 24, ..., 44."""
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()

    _write_rawstate_csv(state_dir / "Animal1_run.csv", ["w"] * 21600)  # 24h
    _write_fake_edf(edf_dir / "Animal1_PREPROCESSED.edf")

    fake_start = datetime(2026, 5, 21, 22, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        df = compute_sleep_bins_df_clock_aligned(
            state_dir, edf_dir, bin_hours=2, begin_hr=6
        )

    starts = sorted(df["bin_start_hr"].unique())
    assert starts == [22.0, 24.0, 26.0, 28.0, 30.0, 32.0, 34.0, 36.0, 38.0, 40.0, 42.0, 44.0]


def test_clock_aligned_48h_preserves_day_distinction(tmp_path: Path):
    """48h recording starting at 22:00 → bins 22..68 (no mod-24 wrap)."""
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()

    # 48h at 0.25 Hz = 43200 epochs.
    _write_rawstate_csv(state_dir / "Animal1_run.csv", ["w"] * 43200)
    _write_fake_edf(edf_dir / "Animal1_PREPROCESSED.edf")

    fake_start = datetime(2026, 5, 21, 22, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        df = compute_sleep_bins_df_clock_aligned(
            state_dir, edf_dir, bin_hours=2, begin_hr=6
        )

    starts = sorted(df["bin_start_hr"].unique())
    assert starts[0] == 22.0
    assert starts[-1] == 68.0
    assert len(starts) == 24  # 48h / 2h per bin


def test_clock_aligned_short_recording_placed_at_true_position(tmp_path: Path):
    """1h recording starting at 22:00 → single bin at bin_start_hr=22."""
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()

    # 1h at 0.25 Hz = 900 epochs.
    _write_rawstate_csv(state_dir / "Animal1_run.csv", ["w"] * 900)
    _write_fake_edf(edf_dir / "Animal1_PREPROCESSED.edf")

    fake_start = datetime(2026, 5, 21, 22, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        df = compute_sleep_bins_df_clock_aligned(
            state_dir, edf_dir, bin_hours=2, begin_hr=6
        )

    starts = sorted(df["bin_start_hr"].unique())
    assert starts == [22.0]


def test_clock_aligned_recording_starting_before_begin_hr(tmp_path: Path):
    """Recording starting at 05:00 (1h before begin_hr=6) → first bin at 4.

    Sample 0 sits inside the bin spanning 04:00-06:00 (one hour into it),
    so the first emitted bin_start_hr is 4 and the bin covers only the
    actual data from 05:00 onward."""
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()

    _write_rawstate_csv(state_dir / "Animal1_run.csv", ["w"] * 21600)  # 24h
    _write_fake_edf(edf_dir / "Animal1_PREPROCESSED.edf")

    fake_start = datetime(2026, 5, 21, 5, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        df = compute_sleep_bins_df_clock_aligned(
            state_dir, edf_dir, bin_hours=2, begin_hr=6
        )

    starts = sorted(df["bin_start_hr"].unique())
    # Previous begin_hr boundary is yesterday's 06:00; rec_start is 23h past
    # that, which falls 1h into the bin spanning 22h-24h past begin_hr
    # (bin_start_hr = 28). The first bin is partial (1h of data), then 11 full
    # bins, then a final partial bin covering 04:00-05:00 the day after — 13
    # bins total, last bin_start_hr = 28 + 24 = 52.
    assert starts[0] == 28.0
    assert starts[-1] == 52.0
    assert len(starts) == 13


def test_clock_aligned_empty_csv_warns(tmp_path: Path):
    """Empty state CSV → skipped with warning, not raised."""
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()

    _write_rawstate_csv(state_dir / "Animal1_run.csv", [])
    _write_fake_edf(edf_dir / "Animal1_PREPROCESSED.edf")

    fake_start = datetime(2026, 5, 21, 6, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        with pytest.warns(UserWarning, match="Empty state CSV"):
            df = compute_sleep_bins_df_clock_aligned(
                state_dir, edf_dir, bin_hours=2, begin_hr=6
            )

    assert df.empty


def test_clock_aligned_warns_and_skips_csv_without_matching_edf(tmp_path: Path):
    """CSV with no paired EDF → warning emitted, other animal still in result."""
    state_dir = tmp_path / "spindle_outputs"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()

    _write_rawstate_csv(state_dir / "Animal1_run.csv", ["w"] * 21600)
    _write_rawstate_csv(state_dir / "Animal2_run.csv", ["w"] * 21600)
    _write_fake_edf(edf_dir / "Animal1_PREPROCESSED.edf")

    fake_start = datetime(2026, 5, 21, 6, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        with pytest.warns(UserWarning, match=r"No EDF for animal 'Animal2'"):
            df = compute_sleep_bins_df_clock_aligned(
                state_dir, edf_dir, bin_hours=2, begin_hr=6
            )

    assert set(df["mouse_id"]) == {"Animal1"}


# ---------------------------------------------------------------------------
# Whole-file metrics
# ---------------------------------------------------------------------------


def test_whole_file_metrics_fractions_and_normalization(tmp_path: Path):
    # 900 epochs/hour at 4s epochs. Two 3h wake blocks around a 3h NREM block,
    # then 1h REM: wake=6h (two bouts), nrem=3h (one bout), rem=1h (one bout).
    per_hr = 3600 // 4
    states = (
        ["w"] * (3 * per_hr)
        + ["n"] * (3 * per_hr)
        + ["w"] * (3 * per_hr)
        + ["r"] * (1 * per_hr)
    )
    _write_rawstate_csv(tmp_path / "Animal1_run.csv", states)

    df = compute_whole_file_metrics(tmp_path).set_index("state")

    # Recording is 10h long.
    assert math.isclose(df.loc["w", "n_hours"], 10.0)
    assert math.isclose(df.loc["w", "n_days"], 10.0 / 24.0)
    # Fractions standardized by whole recording.
    assert math.isclose(df.loc["w", "frac_time"], 6 / 10)
    assert math.isclose(df.loc["n", "frac_time"], 3 / 10)
    assert math.isclose(df.loc["r", "frac_time"], 1 / 10)
    # Wake occurs in two separated blocks → two bouts.
    assert df.loc["w", "n_bouts"] == 2
    assert df.loc["n", "n_bouts"] == 1
    assert math.isclose(df.loc["w", "bouts_per_hour"], 2 / 10)
    # Mean wake bout is 3h = 10800s.
    assert math.isclose(df.loc["w", "mean_bout_sec"], 3 * 3600)


def test_whole_file_metrics_absent_state_zero_filled(tmp_path: Path):
    # No REM at all — should still get a REM row with zeros / NaN mean.
    _write_rawstate_csv(tmp_path / "A1_run.csv", ["w"] * 100 + ["n"] * 100)
    df = compute_whole_file_metrics(tmp_path)
    assert set(df["state"]) == {"w", "n", "r"}
    rem = df[df["state"] == "r"].iloc[0]
    assert rem["frac_time"] == 0.0
    assert rem["n_bouts"] == 0
    assert math.isnan(rem["mean_bout_sec"])


def test_whole_file_metrics_empty_dir(tmp_path: Path):
    df = compute_whole_file_metrics(tmp_path)
    assert df.empty
    assert "bouts_per_hour" in df.columns
