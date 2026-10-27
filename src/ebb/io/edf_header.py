"""EDF header read utilities — sampling-frequency detection + start-datetime.

Three small helpers that all extract a single field from an EDF file's header
via openseize. Grouped together so callers have one place to look for
"give me X from this recording" without re-deriving the header-format string
or the ``samples_per_record[0]`` convention each time.

- ``detect_fs_from_standard``: scans ``project_root/standard/`` for the
  first EDF and returns its sampling frequency, so the PSD / Mask Export
  pages can pre-fill the Sampling-freq SpinBox.
- ``assert_fs_matches``: per-file guard called inside ``estimate_psd`` and
  ``mask_export._build_masks`` so a user-supplied fs that disagrees with
  the file's header errors loudly instead of silently driving mask-window
  math at the wrong rate.
- ``read_edf_start_datetime``: parse the ``start_date`` + ``start_time``
  fields into a naive ``datetime``. Callers needing a timezone-aware value
  localize the result themselves.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openseize.file_io import edf

_EDF_TIME_FMT = "%d.%m.%y %H.%M.%S"


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


def header_fs(header) -> float:
    """Sampling frequency (Hz) from an already-loaded EDF header.

    ``samples_per_record[0] / record_duration``: unlike ``detect_fs_from_standard`` this also
    holds for raw recordings whose records are not 1 s long.
    """
    return float(header.samples_per_record[0]) / float(header.record_duration)


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


def parse_edf_start_datetime(header) -> datetime:
    """Return the recording start datetime from an already-loaded EDF header.

    Combines ``start_date`` (``DD.MM.YY``) and ``start_time`` (``HH.MM.SS``)
    into a naive ``datetime``. Use this when you already have a reader open
    (avoids re-opening the file). Callers that need a timezone-aware value
    should attach a ``tzinfo`` themselves (e.g. ``dt.replace(tzinfo=tz)``).
    """
    return datetime.strptime(f"{header.start_date} {header.start_time}", _EDF_TIME_FMT)


def read_edf_start_datetime(path: Path | str) -> datetime:
    """Open ``path`` and return its recording start datetime (naive).

    Convenience wrapper around ``parse_edf_start_datetime`` for callers
    that only need the datetime and don't otherwise read the file.
    """
    with edf.Reader(str(path)) as reader:
        return parse_edf_start_datetime(reader.header)
