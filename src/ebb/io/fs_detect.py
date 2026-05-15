"""Helper for detecting EEG sampling frequency from EDF files on disk.

Used by the PSD compute and Mask Export pages so the user can hit a ↻
button next to the Sampling-freq SpinBox and have it filled in from the
first EDF in ``project_root/standard/`` rather than re-typing a value
that's already in the file header.

The auto-detection done here is intentionally narrow — it reads exactly
one EDF, returns whatever its first channel reports, and lets the caller
decide what to do with ``None``. A future change will plumb fs through
to the per-file runtime check inside ``estimate_psd`` /
``mask_export.export_run`` so a mismatched file errors loudly during a
batch run.
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
