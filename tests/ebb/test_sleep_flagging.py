"""Tests for the Sleep QC flagging metrics (final_state, whole file)."""

import csv
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from ebb.io.spindle_csv import NotReclassifiedError
from ebb.process import sleep_flagging as sf


def _states(spec: str) -> np.ndarray:
    return np.array(list(spec))


def test_bout_lengths_and_starts_match_notebook_toy_case():
    toy = _states("wwnnnwnrrwnw")
    assert list(sf.bout_lengths(toy, "n")) == [3, 1, 1]
    assert list(sf.bout_starts(toy, "n")) == [2, 6, 10]


def test_bout_lengths_runs_touching_both_ends():
    assert list(sf.bout_lengths(_states("nnwnn"), "n")) == [2, 2]
    assert list(sf.bout_lengths(_states("www"), "n")) == []


def test_file_metrics_percentages_and_short_bouts():
    states = _states("wwnnnwnrrwnw")
    m = sf.file_metrics(states, np.zeros(len(states), dtype=bool))
    assert m["nrem_short"] == 2  # the two single-epoch bouts
    assert m["pct_nrem"] == pytest.approx(100 * 5 / 12)
    assert m["pct_rem"] == pytest.approx(100 * 2 / 12)
    assert m["pct_wake"] == pytest.approx(100 * 5 / 12)


def test_dark_bouts_per_hour_counts_bouts_by_start():
    # 900 epochs = 1 dark hour; bouts start at 0 and 3 (dark) and 6 (light)
    states = np.array(list("nwwnwwn") + ["w"] * 893)
    dark = np.zeros(len(states), dtype=bool)
    dark[:900] = True
    dark[6] = False
    m = sf.file_metrics(states, dark)
    # dark hours = 899 epochs * 4 s / 3600
    assert m["dark_bouts_h"] == pytest.approx(2 / (899 * 4 / 3600))


def test_no_dark_epochs_gives_nan_rate():
    m = sf.file_metrics(_states("nwn"), np.zeros(3, dtype=bool))
    assert np.isnan(m["dark_bouts_h"])


def test_max_bin_rem_uses_full_two_hour_bins_only():
    n = sf.BIN_EPOCHS
    states = np.array(["w"] * n + ["r"] * (n // 2) + ["w"] * (n - n // 2) + ["r"] * 10)
    m = sf.file_metrics(states, np.zeros(len(states), dtype=bool))
    assert m["max_bin_rem"] == pytest.approx(50.0)  # trailing partial bin ignored


def test_short_file_has_nan_max_bin_rem():
    m = sf.file_metrics(_states("wnr"), np.zeros(3, dtype=bool))
    assert np.isnan(m["max_bin_rem"])


def test_empty_states_raise():
    with pytest.raises(ValueError):
        sf.file_metrics(np.array([]), np.array([], dtype=bool))


@pytest.mark.parametrize(
    "direction, value, cutoff, expected",
    [
        (sf.ABOVE, 400, 400, False),
        (sf.ABOVE, 401, 400, True),
        (sf.AT_LEAST, 35, 35, True),
        (sf.AT_LEAST, 34.9, 35, False),
        (sf.BELOW, 29.9, 30, True),
        (sf.BELOW, 30, 30, False),
        (sf.ABOVE, float("nan"), 1, False),
    ],
)
def test_past_threshold(direction, value, cutoff, expected):
    assert sf.past_threshold(value, direction, cutoff) is expected


def test_flagged_metrics_defaults_and_overrides():
    m = {"nrem_short": 500, "dark_bouts_h": 10, "pct_rem": 8, "pct_nrem": 25,
         "pct_wake": 60, "max_bin_rem": 20}
    assert sf.flagged_metrics(m) == ["nrem_short", "pct_nrem"]
    assert sf.flagged_metrics({**m, "pct_rem": 16, "pct_wake": 71}) == [
        "nrem_short", "pct_rem", "pct_nrem", "pct_wake"
    ]
    assert sf.flagged_metrics(m, {"nrem_short": 600}) == []  # missing keys never flag


def test_default_thresholds():
    assert sf.default_thresholds() == {
        "nrem_short": 400, "dark_bouts_h": 15, "pct_rem": 10, "pct_nrem": 30,
        "pct_wake": 70, "max_bin_rem": 35,
    }


# --- from files -----------------------------------------------------------


def _write_csv(path: Path, states: str, final: bool = True) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "rawstate"] + (["final_state"] if final else []))
        for i, s in enumerate(states):
            w.writerow([i, s] + ([s] if final else []))


def test_metrics_for_file_reads_final_state_and_edf_start(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, "read_edf_start_datetime", lambda p: datetime(2024, 1, 1, 19, 59, 56))
    csv_path = tmp_path / "A1_labels.csv"
    _write_csv(csv_path, "nwn")
    m = sf.metrics_for_file(csv_path, tmp_path / "A1_PROCESSED.edf")
    # EDF starts at 19:59:56, so epoch 0 is light and epochs 1-2 are dark; bouts start at 0 and 2
    assert m["dark_bouts_h"] == pytest.approx(1 / (2 * 4 / 3600))


def test_metrics_for_file_requires_final_state(tmp_path):
    csv_path = tmp_path / "A1_labels.csv"
    _write_csv(csv_path, "nwn", final=False)
    with pytest.raises(NotReclassifiedError):
        sf.metrics_for_file(csv_path, tmp_path / "A1_PROCESSED.edf")


def test_metrics_table_one_row_per_paired_animal(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, "read_edf_start_datetime", lambda p: datetime(2024, 1, 1, 8, 0, 0))
    states, edfs = tmp_path / "out", tmp_path / "standard"
    states.mkdir()
    edfs.mkdir()
    for animal in ("A1", "A2"):
        _write_csv(states / f"{animal}_labels.csv", "nwnr")
    (edfs / "A1_PROCESSED.edf").touch()  # A2 has no EDF
    with pytest.warns(UserWarning, match="A2"):
        table = sf.metrics_table(states, edfs)
    assert list(table.index) == ["A1"]
    assert list(table.columns) == [m.key for m in sf.METRICS]


def test_metrics_table_uses_supplied_states(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, "read_edf_start_datetime", lambda p: datetime(2024, 1, 1, 8, 0, 0))
    states, edfs = tmp_path / "out", tmp_path / "standard"
    states.mkdir()
    edfs.mkdir()
    _write_csv(states / "A1_labels.csv", "nwnr", final=False)  # no final_state: would raise
    (edfs / "A1_PROCESSED.edf").touch()
    table = sf.metrics_table(states, edfs, {"A1": list("nnnn")})
    assert table.loc["A1", "pct_nrem"] == 100
