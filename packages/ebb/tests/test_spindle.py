import csv
from pathlib import Path

import numpy as np
import pytest

from ebb.masking import state, spindle_noise


# Write test spindle csv with minimal headers 
def write_spindle_csv(path: Path, rawstates):
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rawstate", "noise_probs"]) 
        for rs in rawstates:
            w.writerow([rs, "0.0"])


def test_state_expands_per_window(tmp_path: Path):
    # 4 spindle windows: wake, nrem, wake
    p = tmp_path / "spindle.csv"
    write_spindle_csv(p, ["w", "n", "w", "r"])

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
    assert mask[2 * fs * winsize :3 * fs * winsize].all()
    # Third window is rem -> False
    assert (~mask[3 * fs * winsize :]).all()


def write_noise_csv(path: Path, noise_probs):
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rawstate", "noise_probs"])
        for v in noise_probs:
            w.writerow(["w", str(v)])


def test_spindle_noise_threshold(tmp_path: Path):
    p = tmp_path / "spindle.csv"
    # noise probs per window
    write_noise_csv(p, [0.1, 0.6, 0.49, 0.5])

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
