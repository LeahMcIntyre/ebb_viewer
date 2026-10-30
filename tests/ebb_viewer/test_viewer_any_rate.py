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


# ---------------------------------------------------------------------------
# The viewer's artifact masks match PSD Computation's
# ---------------------------------------------------------------------------


def test_viewer_artifact_masks_match_the_psd_pipeline_on_a_signal_with_a_dc_offset():
    """A channel with a DC offset flags the same samples in the viewer as in step 6.

    The viewer once subtracted each channel's median first, which hid samples that step 6
    (working on the raw signal) removes.
    """
    from datetime import datetime
    from pathlib import Path

    from openseize import producer

    from ebb import masking
    from ebb.masking.threshold import commutator_samples
    from ebb_viewer.edf_viewer.mask_builder import _compute_artifact_masks, _default_comm_meta
    from ebb_viewer.edf_viewer.recording import Recording

    fs = 250
    rng = np.random.default_rng(1)
    data = rng.normal(0, 40, (4, fs * 60))
    data[0] += 1900  # large DC offset on LFC
    data[0, fs * 30 : fs * 30 + 5] += 300  # spikes that cross 2000 uV only in the raw signal
    rec = Recording(
        data=data,
        fs=fs,
        start_time=datetime(2026, 1, 1),
        ch_names=("LFC", "RSC", "LSC", "EMG"),
        edf_path=Path("AM001.edf"),
    )

    comm_meta = _default_comm_meta(fs)
    sd_meta = {"nstd": 5, "winsize": 10, "radius": 0.5, "comm_mask": True}
    comm_viewer, sd_viewer = _compute_artifact_masks(rec, comm_meta, sd_meta)

    pro = producer(data[:3], chunksize=int(30e5), axis=-1)
    comm_psd = masking.commutator_threshold(pro, value=2000, **commutator_samples(fs))[0]
    sd_psd = masking.sd_threshold(
        pro,
        [5],
        winsize=10 * fs,
        radius=0.5 * fs,
        mask_pro=producer(comm_psd, chunksize=int(4.5e4), axis=-1),
    )[0]

    assert not comm_psd.all()  # the spikes are flagged in the raw signal
    np.testing.assert_array_equal(comm_viewer, comm_psd)
    np.testing.assert_array_equal(sd_viewer, sd_psd)
