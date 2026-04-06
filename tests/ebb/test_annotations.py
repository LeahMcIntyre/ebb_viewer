"""Tests for ebb.masking.annotations.keyword_mask."""

import textwrap
from pathlib import Path

import numpy as np
import pytest

from ebb.masking.annotations import keyword_mask


def write_pinnacle(path: Path, rows: list[tuple[str, float, float]]) -> None:
    """Write a minimal Pinnacle-format annotation file.

    Args:
        path: Destination path.
        rows: List of (label, time_from_start_sec, duration_sec) tuples.
              Times are relative; we place the header + a synthetic start row
              before them so openseize's start=6 parsing works correctly.
    """
    # Pinnacle files have 6 header lines before the column row (start=6)
    header = textwrap.dedent("""\
        Experiment ID\tTest
        Animal ID\tAnimal
        Researcher\tResearcher
        Directory path\t
        \t
        \t
        Number\tStart Time\tEnd Time\tTime From Start\tChannel\tAnnotation
    """)
    # Absolute start timestamp (arbitrary — openseize only uses Time From Start)
    base = "01/01/24 00:00:00.000"
    lines = [header.rstrip("\n")]
    for i, (label, t, dur) in enumerate(rows):
        end_t = t + dur
        lines.append(f"{i}\t{base}\t{base}\t{t:.4f}\tALL\t{label}")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FS = 250  # samples per second


def _n(seconds: float) -> int:
    return int(seconds * FS)


# ---------------------------------------------------------------------------
# Basic matching
# ---------------------------------------------------------------------------


def test_single_keyword_match(tmp_path):
    ann_file = tmp_path / "annots.txt"
    # rows: (label, time_from_start, duration)
    write_pinnacle(ann_file, [
        ("start",  0.0, 0.0),
        ("drink",  2.0, 0.0),
    ])
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_sec=1.0, size=size, fs=FS)

    # Everything before the drink event should be True
    assert np.all(mask[: _n(2)])
    # The drink event window should be False
    assert not np.any(mask[_n(2): _n(3)])
    # After the pad the mask should be True again
    assert np.all(mask[_n(3):])


def test_case_insensitive_matching(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [
        ("start",  0.0, 0.0),
        ("DRINK",  1.0, 0.0),
        ("Drink_End", 5.0, 0.0),
    ])
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_sec=0.5, size=size, fs=FS)
    # "DRINK" at t=1 → masked [1s, 1.5s)
    assert not np.any(mask[_n(1): _n(1) + _n(0.5)])
    # "Drink_End" at t=5 → also matches substring "drink"
    assert not np.any(mask[_n(5): _n(5) + _n(0.5)])


def test_substring_match(tmp_path):
    """Label 'drinking_bout' should match keyword 'drink'."""
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [
        ("start",        0.0, 0.0),
        ("drinking_bout", 2.0, 0.0),
    ])
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_sec=1.0, size=size, fs=FS)
    assert not np.any(mask[_n(2): _n(3)])


def test_no_keyword_match_returns_all_true(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [
        ("start", 0.0, 0.0),
        ("groom", 2.0, 0.5),
    ])
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_sec=1.0, size=size, fs=FS)
    assert np.all(mask)


def test_multiple_keywords_or_logic(tmp_path):
    """Any keyword matching the label should mask the region."""
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [
        ("start", 0.0, 0.0),
        ("drink", 1.0, 0.0),
        ("groom", 3.0, 0.0),
    ])
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink", "groom"], pad_sec=0.5, size=size, fs=FS)
    assert not np.any(mask[_n(1): _n(1) + _n(0.5)])
    assert not np.any(mask[_n(3): _n(3) + _n(0.5)])
    # Gap between events should be unmasked
    assert np.all(mask[_n(1) + _n(0.5): _n(3)])


def test_multiple_events_same_keyword(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [
        ("start", 0.0, 0.0),
        ("drink", 1.0, 0.0),
        ("drink", 4.0, 0.0),
    ])
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_sec=1.0, size=size, fs=FS)
    assert not np.any(mask[_n(1): _n(2)])
    assert not np.any(mask[_n(4): _n(5)])
    assert np.all(mask[_n(2): _n(4)])
    assert np.all(mask[_n(5):])


# ---------------------------------------------------------------------------
# Time-offset adjustment
# ---------------------------------------------------------------------------


def test_times_adjusted_relative_to_first_annotation(tmp_path):
    """Mask positions should be relative to the first annotation's time."""
    ann_file = tmp_path / "annots.txt"
    # First annotation at t=10s acts as t0; drink at t=12s → relative t=2s
    write_pinnacle(ann_file, [
        ("start", 10.0, 0.0),
        ("drink", 12.0, 0.0),
    ])
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_sec=1.0, size=size, fs=FS)
    # Relative time of drink = 12 - 10 = 2s → masked [2s, 3s)
    assert np.all(mask[: _n(2)])
    assert not np.any(mask[_n(2): _n(3)])
    assert np.all(mask[_n(3):])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_keywords_list_returns_all_true(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [
        ("start", 0.0, 0.0),
        ("drink", 1.0, 0.0),
    ])
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=[], pad_sec=1.0, size=size, fs=FS)
    assert np.all(mask)


def test_whitespace_only_keywords_treated_as_empty(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [
        ("start", 0.0, 0.0),
        ("drink", 1.0, 0.0),
    ])
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["  ", "\t"], pad_sec=1.0, size=size, fs=FS)
    assert np.all(mask)


def test_pad_sec_zero_masks_at_least_one_sample(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [
        ("start", 0.0, 0.0),
        ("drink", 1.0, 0.0),
    ])
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_sec=0.0, size=size, fs=FS)
    # pad=0 → min 1 sample masked
    assert mask[_n(1) - 1]   # sample before event: True
    assert not mask[_n(1)]   # event sample: False
    assert mask[_n(1) + 1]   # sample after: True


def test_event_at_end_of_recording_clipped(tmp_path):
    """Pad extending beyond recording length should be clipped, not error."""
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [
        ("start", 0.0, 0.0),
        ("drink", 9.0, 0.0),
    ])
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_sec=5.0, size=size, fs=FS)
    assert not np.any(mask[_n(9):])
    assert len(mask) == size


def test_returns_correct_size(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [("start", 0.0, 0.0)])
    for size in [100, 1000, 5000]:
        mask = keyword_mask(ann_file, keywords=["drink"], pad_sec=1.0, size=size, fs=FS)
        assert len(mask) == size


def test_return_type_is_bool_array(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [("start", 0.0, 0.0)])
    mask = keyword_mask(ann_file, keywords=["drink"], pad_sec=1.0, size=_n(5), fs=FS)
    assert mask.dtype == bool
