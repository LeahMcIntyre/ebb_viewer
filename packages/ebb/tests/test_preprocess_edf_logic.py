import pytest
from ebb.preprocess.edf import compute_trim_stop_samples

def test_compute_trim_stop_picks_lower_bin():
    fs = 100
    # 66 hours recording
    n = int(66 * 3600 * fs)
    stop = compute_trim_stop_samples(n, fs, trim_to_hours=[60, 80])
    assert stop == int(60 * 3600 * fs)

def test_compute_trim_stop_picks_max_if_longer():
    fs = 100
    # 90 hours recording
    n = int(90 * 3600 * fs)
    stop = compute_trim_stop_samples(n, fs, trim_to_hours=[48, 72])
    assert stop == int(72 * 3600 * fs)

def test_compute_trim_stop_raises_if_too_short():
    fs = 100
    # 10 hours recording
    n = int(10 * 3600 * fs)
    with pytest.raises(ValueError):
        compute_trim_stop_samples(n, fs, trim_to_hours=[48, 72])

def test_compute_trim_stop_zero_length():
    fs = 100
    # 0 hours recording
    n = 0
    with pytest.raises(ValueError):
        compute_trim_stop_samples(n, fs, trim_to_hours=[1, 2, 3])

def test_compute_trim_stop_no_trim_hours():
    fs = 100
    # 50 hours recording
    n = int(50 * 3600 * fs)
    with pytest.raises(ValueError):
        compute_trim_stop_samples(n, fs, trim_to_hours=[])