"""The EEG viewer opens EDFs at any sampling rate and scales its rate-dependent defaults."""

from __future__ import annotations

import numpy as np
import pytest

edfio = pytest.importorskip("edfio")

from ebb_viewer.edf_viewer import eeg_viewer  # noqa: E402
from ebb_viewer.edf_viewer.eeg_viewer import EegMainWindow, _load_recording  # noqa: E402


def _write_edf(path, fs: int, seconds: int = 20) -> None:
    rng = np.random.default_rng(0)
    signals = [
        edfio.EdfSignal(
            rng.normal(0, 40, fs * seconds),
            sampling_frequency=fs,
            label=name,
            physical_dimension="uV",
        )
        for name in ("LFC", "RSC", "LSC", "EMG")
    ]
    edfio.Edf(signals).write(path)


@pytest.mark.parametrize("fs", [200, 500, 1000])
def test_loads_an_edf_at_any_rate(tmp_path, fs):
    path = tmp_path / "AM001_a.edf"
    _write_edf(path, fs)
    rec = _load_recording(path)
    assert rec.fs == fs
    assert rec.data.shape == (4, fs * 20)


@pytest.mark.parametrize("fs", [200, 500, 1000])
def test_window_scales_its_defaults_to_the_rate(qapp, tmp_path, fs):
    path = tmp_path / "AM001_a.edf"
    _write_edf(path, fs)
    win = EegMainWindow(_load_recording(path))
    assert win.nperseg == fs // 2  # a 0.5 s STFT window
    assert win.stft_fmax == min(120, fs // 2)  # never above Nyquist
    comm = win.mask_set.get("commutator")
    assert comm.metadata["radius"] == fs and comm.metadata["pad"] == fs  # still 1 s


def test_refuses_a_recording_too_large_to_hold_in_memory(tmp_path, monkeypatch):
    path = tmp_path / "AM001_a.edf"
    _write_edf(path, 500)
    monkeypatch.setattr(eeg_viewer, "_MAX_RECORDING_BYTES", 1000)
    with pytest.raises(ValueError, match="Preprocess"):
        _load_recording(path)
