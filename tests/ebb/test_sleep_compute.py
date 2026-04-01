import csv
import math
from pathlib import Path

import pytest

from ebb.process.sleep_compute import compute_spindle_fractions


def write_state_csv(path: Path, states: list[str]) -> None:
    """Write a minimal spindle output CSV with a 'state' column."""
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state", "noise_probs"])
        for s in states:
            w.writerow([s, "0.0"])


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------

def test_single_animal_fractions(tmp_path: Path):
    # 2 clean wake, 1 spindle-wake, 3 clean NREM, 1 spindle-NREM, 0 REM
    write_state_csv(tmp_path / "Animal1_foo.csv", ["w", "w", "1", "n", "n", "n", "2"])
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
    # 4 clean (w, n, r, w), 2 spindle (1, 3)
    write_state_csv(tmp_path / "Animal1_foo.csv", ["w", "n", "r", "w", "1", "3"])
    df = compute_spindle_fractions(tmp_path)

    total = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Total")].iloc[0]
    assert total["spindle_count"] == 2
    assert total["total_count"] == 6
    assert math.isclose(total["fraction"], 2 / 6)


def test_all_spindle_masked(tmp_path: Path):
    write_state_csv(tmp_path / "Animal1_foo.csv", ["1", "2", "3"])
    df = compute_spindle_fractions(tmp_path)

    total = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Total")].iloc[0]
    assert math.isclose(total["fraction"], 1.0)


def test_no_spindle_masked(tmp_path: Path):
    write_state_csv(tmp_path / "Animal1_foo.csv", ["w", "n", "r", "w"])
    df = compute_spindle_fractions(tmp_path)

    total = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Total")].iloc[0]
    assert math.isclose(total["fraction"], 0.0)


# ---------------------------------------------------------------------------
# Multiple animals
# ---------------------------------------------------------------------------

def test_multiple_animals(tmp_path: Path):
    write_state_csv(tmp_path / "Animal1_foo.csv", ["w", "1"])
    write_state_csv(tmp_path / "Animal2_foo.csv", ["n", "2", "2"])
    df = compute_spindle_fractions(tmp_path)

    assert set(df["mouse_id"].unique()) == {"Animal1", "Animal2"}

    a1_total = df[(df["mouse_id"] == "Animal1") & (df["state"] == "Total")].iloc[0]
    assert math.isclose(a1_total["fraction"], 0.5)

    a2_nrem = df[(df["mouse_id"] == "Animal2") & (df["state"] == "NREM")].iloc[0]
    assert math.isclose(a2_nrem["fraction"], 2 / 3)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_directory(tmp_path: Path):
    df = compute_spindle_fractions(tmp_path)
    assert df.empty
    assert list(df.columns) == [
        "mouse_id", "state", "clean_count", "spindle_count", "total_count", "fraction"
    ]


def test_missing_state_column_raises(tmp_path: Path):
    p = tmp_path / "Animal1_foo.csv"
    with p.open("w", newline="") as f:
        csv.writer(f).writerows([["rawstate"], ["w"]])
    with pytest.raises(ValueError, match="'state' column not found"):
        compute_spindle_fractions(tmp_path)


def test_state_column_is_ordered_categorical(tmp_path: Path):
    write_state_csv(tmp_path / "Animal1_foo.csv", ["w", "n", "r"])
    df = compute_spindle_fractions(tmp_path)

    assert hasattr(df["state"].dtype, "ordered") and df["state"].dtype.ordered
    order = list(df[df["mouse_id"] == "Animal1"]["state"])
    assert order == ["Wake", "NREM", "REM", "Total"]
