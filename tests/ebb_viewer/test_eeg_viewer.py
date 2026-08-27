import csv
from pathlib import Path

from ebb_viewer.edf_viewer.eeg_viewer import _load_state_df


def test_load_state_df_old_format_drops_state_and_threshold(tmp_path: Path):
    p = tmp_path / "spindle.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "state", "noise_probs", "rawstate", "threshold", "class_prob_0"])
        w.writerow(["0", "1", "0.1", "w", "0.5", "0.99"])

    df = _load_state_df(p)

    assert list(df.columns) == ["index", "noise_probs", "rawstate", "class_prob_0"]
    assert df.iloc[0]["rawstate"] == "w"


def test_load_state_df_new_format_keeps_state(tmp_path: Path):
    p = tmp_path / "spindle.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "noise_prob", "state", "class_prob_0"])
        w.writerow(["0", "0.1", "w", "0.99"])

    df = _load_state_df(p)

    assert list(df.columns) == ["index", "noise_prob", "state", "class_prob_0"]
    assert df.iloc[0]["state"] == "w"


def test_load_state_df_returns_none_on_missing_file(tmp_path: Path):
    assert _load_state_df(tmp_path / "does_not_exist.csv") is None
