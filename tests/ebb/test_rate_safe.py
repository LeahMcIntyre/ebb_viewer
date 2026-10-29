"""The fixed 250 Hz sample counts are derived from the sampling rate instead."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from ebb.masking.threshold import commutator_samples
from ebb.process import nrem_reclass


def test_commutator_samples_match_the_lab_values_at_250_hz():
    assert commutator_samples(250) == {"radius": 250, "pad": 250, "min_to_pad": 10}


@pytest.mark.parametrize("fs", [200, 500, 1000])
def test_commutator_samples_scale_with_the_rate(fs):
    got = commutator_samples(fs)
    assert got["radius"] == fs and got["pad"] == fs  # still 1 s
    assert got["min_to_pad"] == round(0.04 * fs)


class _FakeReader:
    """Stands in for ``openseize.file_io.edf.Reader`` (a 1-channel EMG recording)."""

    def __init__(self, emg: np.ndarray, fs: int):
        self._emg = emg
        self.header = SimpleNamespace(samples_per_record=[fs], record_duration=1.0)
        self.channels = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, start, stop):
        return self._emg[None, :]


@pytest.mark.parametrize("fs", [250, 500])
def test_epoch_emg_rms_uses_the_edf_rate_for_epoch_length(monkeypatch, fs):
    per_epoch = fs * nrem_reclass.EPOCH_SEC
    emg = np.concatenate([np.full(per_epoch, 1.0), np.full(per_epoch, 3.0)])
    monkeypatch.setattr(
        "openseize.file_io.edf.Reader", lambda path: _FakeReader(emg, fs), raising=True
    )
    rms = nrem_reclass.epoch_emg_rms("ignored.edf")
    np.testing.assert_allclose(rms, [1.0, 3.0])
