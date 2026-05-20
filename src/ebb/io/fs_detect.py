"""Helper for detecting EEG sampling frequency from EDF files on disk.

Used by the PSD compute and Mask Export pages so the user can hit a ↻
button next to the Sampling-freq SpinBox and have it filled in from the
first EDF in ``project_root/standard/`` rather than re-typing a value
that's already in the file header.

The auto-detection done here is intentionally narrow — it reads exactly
one EDF, returns whatever its first channel reports, and lets the caller
decide what to do with ``None``. The companion ``assert_fs_matches``
runs per-file inside ``estimate_psd`` / ``mask_export._build_masks`` so
a user-supplied fs that disagrees with the file's header errors loudly
instead of silently driving mask-window math at the wrong rate.
"""

from __future__ import annotations

from pathlib import Path

from openseize.file_io import edf


def detect_fs_from_standard(project_root: Path | str) -> int | None:
    """Return the sampling frequency of the first ``.edf`` under
    ``project_root/standard/``, or ``None`` if no readable EDF is found.

    Treats the first channel's ``samples_per_record`` as the recording's
    fs — same convention used by ``ebb_viewer.edf_viewer.eeg_viewer`` and
    ``ebb.io.combine``. The project's acquisition standardizes channels
    to a uniform rate so index ``[0]`` is a safe stand-in for "the
    recording's fs".
    """
    std = Path(project_root) / "standard"
    if not std.is_dir():
        return None
    edfs = sorted(std.glob("*.edf"))
    if not edfs:
        return None
    try:
        with edf.Reader(edfs[0]) as reader:
            return int(reader.header.samples_per_record[0])
    except (OSError, ValueError, IndexError):
        return None


def assert_fs_matches(reader, expected_fs: int | float, *, path: Path | None = None) -> None:
    """Raise ``ValueError`` if the EDF reader's fs disagrees with ``expected_fs``.

    Treats ``int(reader.header.samples_per_record[0])`` as the file's fs —
    matches the convention used by ``detect_fs_from_standard`` and assumes
    the preprocess step has normalized ``record_duration`` to 1 second.
    """
    actual = int(reader.header.samples_per_record[0])
    expected = int(expected_fs)
    if actual != expected:
        name = Path(path).name if path is not None else "EDF"
        raise ValueError(
            f"Sampling-frequency mismatch for {name}: file is {actual} Hz "
            f"but caller passed fs={expected}. Update the Sampling Frequency "
            f"setting to match the recording."
        )
