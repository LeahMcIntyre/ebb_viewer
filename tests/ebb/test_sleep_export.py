import csv
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from ebb.io.sleep_export import _average_bins_across_days, export_sleep


def _write_rawstate_csv(path: Path, states: list[str]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rawstate"])
        for s in states:
            w.writerow([s])


def _make_project(tmp_path: Path, states: list[str]) -> tuple[Path, Path]:
    state_dir = tmp_path / "chosen"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()
    _write_rawstate_csv(state_dir / "Animal1_LFC_RSC.csv", states)
    (edf_dir / "Animal1_PREPROCESSED.edf").write_bytes(b"")
    return state_dir, edf_dir


def test_export_sleep_writes_all_tables(tmp_path: Path):
    per_hr = 3600 // 4
    # 26h recording so it spans two 6AM days after rotation.
    states = ["w"] * (13 * per_hr) + ["n"] * (13 * per_hr)
    state_dir, edf_dir = _make_project(tmp_path, states)
    out = tmp_path / "sleep_export"

    fake_start = datetime(2024, 1, 1, 22, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        written = export_sleep(state_dir, edf_dir, out, begin_hr=6)

    for key in ("sleep_bins", "sleep_bins_avg", "sleep_whole_file", "workbook"):
        assert written[key].exists()

    # Workbook has one sheet per table.
    assert pd.ExcelFile(out / "sleep_export.xlsx").sheet_names == [
        "sleep_bins",
        "sleep_bins_avg",
        "sleep_whole_file",
    ]

    # Bins rotate to 6AM and run monotonically across the two days.
    bins = pd.read_csv(out / "sleep_bins.csv")
    assert bins["bin_start_hr"].min() == 6
    assert bins["bin_start_hr"].max() > 24

    # Whole-file fractions are standardized over the whole recording.
    whole = pd.read_csv(out / "sleep_whole_file.csv").set_index("state")
    assert whole.loc["w", "frac_time"] == pytest.approx(0.5)
    assert whole.loc["n", "frac_time"] == pytest.approx(0.5)
    assert whole.loc["w", "n_hours"] == pytest.approx(26.0)


def test_average_folds_matching_hours_across_days(tmp_path: Path):
    # Two synthetic rotated bins at the same clock hour on different days.
    bins = pd.DataFrame(
        {
            "mouse_id": ["A", "A"],
            "state": ["w", "w"],
            "bin_idx": [0, 12],
            "bin_start_hr": [6.0, 30.0],  # 30 % 24 == 6
            "bin_start_sec": [0, 0],
            "frac_time": [0.2, 0.8],
            "n_bouts": [1, 3],
            "mean_bout_sec": [100.0, 300.0],
        }
    )
    avg = _average_bins_across_days(bins)
    row = avg[(avg["state"] == "w") & (avg["hour_of_day"] == 6)].iloc[0]
    assert row["frac_time"] == pytest.approx(0.5)
    assert row["n_bouts"] == pytest.approx(2.0)
    assert row["n_days"] == 2


def test_export_empty_when_no_matching_edf(tmp_path: Path):
    state_dir = tmp_path / "chosen"
    edf_dir = tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()
    _write_rawstate_csv(state_dir / "Animal1_LFC_RSC.csv", ["w"] * 100)
    # No EDF for Animal1 → offset bins empty, but whole-file still populated.
    out = tmp_path / "sleep_export"

    with pytest.warns(UserWarning):
        written = export_sleep(state_dir, edf_dir, out, begin_hr=6)

    assert pd.read_csv(written["sleep_bins"]).empty
    assert not pd.read_csv(written["sleep_whole_file"]).empty
