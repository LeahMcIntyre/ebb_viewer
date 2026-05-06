import csv
import math
from pathlib import Path

import pytest

from ebb.process.sleep_compute import compute_spindle_fractions


def write_state_csv(path: Path, epochs: list[tuple[str, float]]) -> None:
    """Write a spindle output CSV with rawstate and noise_probs columns.

    Each epoch is (rawstate, noise_prob) where rawstate is one of w/n/r and
    noise_prob is in [0, 1].  An epoch is spindle-masked when noise_prob >= 0.5.
    """
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rawstate", "noise_probs"])
        for raw, prob in epochs:
            w.writerow([raw, str(prob)])


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------


def test_single_animal_fractions(tmp_path: Path):
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
