import csv
from pathlib import Path

import numpy as np
import pytest

from ebb.io.spindle_csv import STATE_COLUMNS, NotReclassifiedError
from ebb.masking import spindle_noise, state


# Write test spindle csv with minimal headers
def write_spindle_csv(path: Path, rawstates, *, new_format: bool = False):
    state_col = "state" if new_format else "rawstate"
    noise_col = "noise_prob" if new_format else "noise_probs"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([state_col, noise_col, "final_state"])
        for rs in rawstates:
            w.writerow([rs, "0.0", rs])


@pytest.mark.parametrize("new_format", [False, True])
def test_state_expands_per_window(tmp_path: Path, new_format: bool):
    # 4 spindle windows: wake, nrem, wake
    p = tmp_path / "spindle.csv"
    write_spindle_csv(p, ["w", "n", "w", "r"], new_format=new_format)

    fs = 250
    winsize = 4
    mask = state(p, labels=["w"], fs=fs, winsize=winsize, include=True)

    assert mask.dtype == bool
    assert mask.size == 4 * fs * winsize

    # First window is wake -> True
    assert mask[: fs * winsize].all()
    # Second window is nrem -> False
    assert (~mask[fs * winsize : 2 * fs * winsize]).all()
    # Third window is wake -> True
    assert mask[2 * fs * winsize : 3 * fs * winsize].all()
    # Third window is rem -> False
    assert (~mask[3 * fs * winsize :]).all()


def write_noise_csv(path: Path, noise_probs, *, new_format: bool = False):
    state_col = "state" if new_format else "rawstate"
    noise_col = "noise_prob" if new_format else "noise_probs"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([state_col, noise_col, "final_state"])
        for v in noise_probs:
            w.writerow(["w", str(v), "w"])


@pytest.mark.parametrize("new_format", [False, True])
def test_spindle_noise_threshold(tmp_path: Path, new_format: bool):
    p = tmp_path / "spindle.csv"
    # noise probs per window
    write_noise_csv(p, [0.1, 0.6, 0.49, 0.5], new_format=new_format)

    fs = 250
    winsize = 4

    # default include=False (i.e., noise events become False)
    mask = spindle_noise(p, noise_thresh=0.5, fs=fs, winsize=winsize, include=False)

    # windows with prob >= 0.5 should be False in the returned mask
    # So: 0.1 -> True, 0.6 -> False, 0.49 -> True, 0.5 -> False
    expected_per_window = [True, False, True, False]
    expected = np.repeat(expected_per_window, fs * winsize).astype(bool)

    assert mask.size == expected.size
    assert np.array_equal(mask, expected)


def test_state_prefers_rawstate_over_artifact_coded_state(tmp_path: Path):
    # Old-format file with both columns: `state` carries an artifact code
    # ('1') on an epoch where `rawstate` is clean ('w'). The clean value
    # must win.
    p = tmp_path / "spindle.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state", "rawstate", "noise_probs"])
        w.writerow(["1", "w", "0.0"])

    fs = 250
    winsize = 4
    mask = state(p, labels=["w"], fs=fs, winsize=winsize, include=True, columns=STATE_COLUMNS)
    assert mask.all()


def test_state_defaults_to_final_state_over_original_columns(tmp_path: Path):
    p = tmp_path / "spindle.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rawstate", "final_state"])
        w.writerows([["n", "w"], ["n", "n"]])
    mask = state(p, labels=["w"], fs=1, winsize=1)
    assert mask.tolist() == [True, False]


def test_state_without_final_state_raises_not_reclassified(tmp_path: Path):
    p = tmp_path / "spindle.csv"
    write_spindle_csv(p, ["w"])
    # strip final_state
    p.write_text("rawstate,noise_probs\nw,0.0\n")
    with pytest.raises(NotReclassifiedError, match="Reclassify"):
        state(p, labels=["w"], fs=1, winsize=1)
