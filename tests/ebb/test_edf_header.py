"""Tests for ``ebb.io.edf_header``: ``detect_fs_from_standard`` (UI helper),
``assert_fs_matches`` (per-file runtime guard), and ``read_edf_start_datetime``
(header datetime parser).

The success path of ``detect_fs_from_standard`` (open a real EDF, return
its first-channel ``samples_per_record``) is exercised end-to-end by
manual smoke checks on the PSD compute / Mask Export pages. These tests
focus on the fallback paths that the helper needs to handle gracefully
when invoked from the GUI's ↻ button.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from ebb.io.edf_header import (
    assert_fs_matches,
    detect_fs_from_standard,
    read_edf_start_datetime,
)


def test_returns_none_when_no_standard_dir(tmp_path: Path):
    """No ``standard/`` directory under project_root → None."""
    assert detect_fs_from_standard(tmp_path) is None


def test_returns_none_when_standard_has_no_edfs(tmp_path: Path):
    """``standard/`` exists but contains no .edf files → None."""
    (tmp_path / "standard").mkdir()
    (tmp_path / "standard" / "notes.txt").write_text("")
    assert detect_fs_from_standard(tmp_path) is None


def test_returns_none_on_unreadable_edf(tmp_path: Path):
    """``edf.Reader`` raising OSError must surface as None rather than
    propagating — the helper is called from a button click handler where
    a crash would be worse than a silent no-op."""
    std = tmp_path / "standard"
    std.mkdir()
    (std / "fake.edf").write_text("not a real EDF")
    # Patch the reader inside the helper's module so we don't need a valid EDF.
    with patch("ebb.io.edf_header.edf.Reader", side_effect=OSError("bad file")):
        assert detect_fs_from_standard(tmp_path) is None


def test_returns_fs_from_first_edf_when_readable(tmp_path: Path):
    """Happy path: helper opens the first sorted EDF and returns its
    first-channel ``samples_per_record``."""
    std = tmp_path / "standard"
    std.mkdir()
    (std / "AM001.edf").write_text("")
    (std / "AM002.edf").write_text("")

    class _FakeHeader:
        samples_per_record = [500, 500, 500, 500]

    class _FakeReader:
        def __init__(self, _path):
            self.header = _FakeHeader()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    with patch("ebb.io.edf_header.edf.Reader", _FakeReader):
        assert detect_fs_from_standard(tmp_path) == 500


def test_accepts_string_path(tmp_path: Path):
    """The helper accepts a str or Path; both should behave identically."""
    assert detect_fs_from_standard(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# assert_fs_matches
# ---------------------------------------------------------------------------


class _FakeReader:
    """Minimal stand-in: only exposes ``header.samples_per_record``."""

    def __init__(self, fs: int):
        self.header = type("H", (), {"samples_per_record": [fs, fs, fs, fs]})()


def test_assert_fs_matches_passes_when_equal():
    """No raise when reader's fs equals expected_fs."""
    assert_fs_matches(_FakeReader(250), 250)


def test_assert_fs_matches_accepts_float_expected():
    """Floats convert via int() for the comparison."""
    assert_fs_matches(_FakeReader(250), 250.0)


def test_assert_fs_matches_raises_on_mismatch():
    """Mismatch must raise ValueError so a batch run aborts loudly."""
    with pytest.raises(ValueError, match=r"file is 250 Hz but caller passed fs=500"):
        assert_fs_matches(_FakeReader(250), 500)


def test_assert_fs_matches_includes_path_name_in_message():
    """Error message names the offending file so the user can locate it."""
    with pytest.raises(ValueError, match=r"animal-42_PREPROCESSED\.edf"):
        assert_fs_matches(
            _FakeReader(250), 500, path=Path("/tmp/foo/animal-42_PREPROCESSED.edf")
        )


def test_assert_fs_matches_falls_back_to_edf_placeholder_without_path():
    """Without a path, the message uses 'EDF' rather than crashing."""
    with pytest.raises(ValueError, match=r"Sampling-frequency mismatch for EDF"):
        assert_fs_matches(_FakeReader(250), 500)


# ---------------------------------------------------------------------------
# read_edf_start_datetime
# ---------------------------------------------------------------------------


class _FakeHeaderWithDate:
    def __init__(self, start_date: str, start_time: str):
        self.start_date = start_date
        self.start_time = start_time


class _FakeReaderWithDate:
    def __init__(self, start_date: str, start_time: str):
        self.header = _FakeHeaderWithDate(start_date, start_time)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_read_edf_start_datetime_parses_header(tmp_path: Path):
    """Combines start_date (DD.MM.YY) + start_time (HH.MM.SS) into a naive datetime."""

    def reader_factory(_path):
        return _FakeReaderWithDate("08.03.26", "22.30.45")

    with patch("ebb.io.edf_header.edf.Reader", reader_factory):
        dt = read_edf_start_datetime(tmp_path / "fake.edf")

    assert dt == datetime(2026, 3, 8, 22, 30, 45)
    assert dt.tzinfo is None  # helper returns naive; localization is the caller's job
