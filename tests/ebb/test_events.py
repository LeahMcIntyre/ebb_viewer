from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from ebb.masking import swd


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
