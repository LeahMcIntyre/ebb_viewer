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
    n = int(90 * 3600 * fs)
    stop = compute_trim_stop_samples(n, fs, trim_to_hours=[48, 72])
    assert stop == int(72 * 3600 * fs)

def test_compute_trim_stop_raises_if_too_short():
    fs = 100
    n = int(10 * 3600 * fs)
    with pytest.raises(ValueError):
        compute_trim_stop_samples(n, fs, trim_to_hours=[48, 72])
