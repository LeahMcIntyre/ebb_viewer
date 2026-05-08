"""Modeless STFT/PSD viewer for inspecting a window of multi-channel EEG."""

import numpy as np
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas,
)
from matplotlib.backends.backend_qtagg import (
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure
from PyQt6 import QtWidgets
from scipy.signal import stft, welch


class STFTPopup(QtWidgets.QDialog):
    """Stacked per-channel STFT spectrogram or Welch PSD for one EEG window."""

    def __init__(self, parent=None, title="EEG STFT"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)

        self.fig = Figure(constrained_layout=True)
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas)

    def plot_window(self, data, fs, ch_names, start_idx, win_len, nperseg, fmin=0, fmax=120.0):
        """Plot STFT for data[:, start_idx:start_idx+win_len]."""
        nch, n = data.shape
        s0 = int(start_idx)
        s1 = min(s0 + int(win_len), n)
        seg_len = max(0, s1 - s0)

        noverlap = nperseg // 2
        min_len_for_two = nperseg + (nperseg - noverlap)  # = 1.5 * nperseg
        if seg_len < min_len_for_two:
            return

        # First pass: compute magnitudes to pick global color scale
        mags_band = []
        for ch in range(nch):
            f, t, Z = stft(
                data[ch, s0:s1], fs=fs, nperseg=nperseg, noverlap=noverlap, boundary=None
            )
            freq_mask = (f >= fmin) & (f <= fmax)
            # Exclude the US 60 Hz line-noise band from the color scale so
            # power-line bleed doesn't dominate the dynamic range.
            line_mask = (f >= 56.0) & (f <= 64.0)
            scale_mask = freq_mask & (~line_mask)
            band = np.abs(Z[scale_mask, :]) ** 2
            if band.size:
                mags_band.append(band.ravel())
        if not mags_band:
            return
        allvals = np.concatenate(mags_band)
        vmin = np.percentile(allvals, 10)
        vmax = np.percentile(allvals, 90)
        if vmin == vmax:
            vmax = vmin + 1e-9

        # Draw
        self.fig.clear()
        axes = [
            self.fig.add_subplot(nch, 1, i + 1, sharex=(self.fig.axes[0] if i else None))
            for i in range(nch)
        ]
        pcm_ref = None
        for ch, ax in enumerate(axes):
            f, t, Z = stft(
                data[ch, s0:s1], fs=fs, nperseg=nperseg, noverlap=noverlap, boundary=None
            )
            t = t + (s0 / fs)
            mag = np.abs(Z) ** 2
            pcm = ax.pcolormesh(t, f, mag, shading="gouraud", vmin=vmin, vmax=vmax)
            if pcm_ref is None:
                pcm_ref = pcm
            ax.set_ylim(fmin, fmax)
            ax.set_ylabel(str(ch_names[ch]) if ch < len(ch_names) else f"ch {ch}")
        axes[-1].set_xlabel("Time (s)")
        self.fig.colorbar(pcm_ref, ax=axes, label="|STFT|²", fraction=0.03, pad=0.02)
        self.canvas.draw_idle()

    def plot_window_psd(
        self,
        data,
        fs,
        ch_names,
        start_idx,
        win_len,
        nperseg,
        fmin=0.0,
        fmax=120.0,
        detrend="constant",
        scaling="density",
        average="mean",
    ):
        """Plot Welch PSD for data[:, start_idx:start_idx+win_len]."""
        nch, n = data.shape
        s0 = int(start_idx)
        s1 = min(s0 + int(win_len), n)
        seg_len = max(0, s1 - s0)

        if seg_len < int(nperseg):
            return

        self.fig.clear()
        axes = [
            self.fig.add_subplot(nch, 1, i + 1, sharex=(self.fig.axes[0] if i else None))
            for i in range(nch)
        ]

        for ch, ax in enumerate(axes):
            f, Pxx = welch(
                data[ch, s0:s1],
                fs=fs,
                nperseg=nperseg,
                noverlap=nperseg // 2,
                detrend=detrend,
                scaling=scaling,
                average=average,
                axis=0,
            )
            mask = (f >= fmin) & (f <= fmax)
            ax.plot(f[mask], Pxx[mask], linewidth=1.2)
            ax.set_xlim(fmin, fmax)
            ax.set_yscale("log")
            ax.set_ylabel(str(ch_names[ch]) if ch < len(ch_names) else f"ch {ch}")

        axes[-1].set_xlabel("Frequency (Hz)")
        self.fig.suptitle(f"PSD (Welch) — [{s0 / fs:.2f}s, {s1 / fs:.2f}s]", fontsize=12)
        self.canvas.draw_idle()


class STFTBoundsDialog(QtWidgets.QDialog):
    """Modal dialog to set STFT [fmin, fmax] with live validation."""

    def __init__(self, *, fs: int, nperseg: int, fmin: int, fmax: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set STFT Frequency Bounds")
        self.setModal(True)

        nyq = fs // 2
        df = max(1, fs // nperseg)

        self.err = QtWidgets.QLabel("fmin must be strictly less than fmax.")
        self.err.setStyleSheet("color:#b00020;")
        self.err.setVisible(False)

        self.spin_min = QtWidgets.QSpinBox()
        self.spin_min.setRange(0, nyq)
        self.spin_min.setSingleStep(df)
        self.spin_min.setValue(max(0, min(fmin, nyq)))

        self.spin_max = QtWidgets.QSpinBox()
        self.spin_max.setRange(0, nyq)
        self.spin_max.setSingleStep(df)
        self.spin_max.setValue(max(0, min(fmax, nyq)))

        form = QtWidgets.QFormLayout()
        form.addRow("fmin (Hz):", self.spin_min)
        form.addRow("fmax (Hz):", self.spin_max)

        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.err)
        lay.addWidget(self.buttons)

        self.spin_min.valueChanged.connect(self._validate)
        self.spin_max.valueChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        ok = self.spin_min.value() < self.spin_max.value()
        self.err.setVisible(not ok)
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def values(self) -> tuple[int, int]:
        return self.spin_min.value(), self.spin_max.value()
