"""Tests for ebb.masking.annotations.keyword_mask."""

import textwrap
from pathlib import Path

import numpy as np

from ebb.masking.annotations import keyword_mask


def write_pinnacle(path: Path, rows: list[tuple[str, float, float]]) -> None:
    """Write a minimal Pinnacle-format annotation file."""
    header = textwrap.dedent("""\
        Experiment ID\tTest
        Animal ID\tAnimal
        Researcher\tResearcher
        Directory path\t
        \t
        \t
        Number\tStart Time\tEnd Time\tTime From Start\tChannel\tAnnotation
    """)
    base = "01/01/24 00:00:00.000"
    lines = [header.rstrip("\n")]
    for i, (label, t, dur) in enumerate(rows):
        lines.append(f"{i}\t{base}\t{base}\t{t:.4f}\tALL\t{label}")
    path.write_text("\n".join(lines) + "\n")


FS = 250  # samples per second


def _n(seconds: float) -> int:
    return int(seconds * FS)


# ---------------------------------------------------------------------------
# Basic contains matching (default mode)
# ---------------------------------------------------------------------------


def test_single_keyword_match(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 2.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_after_sec=1.0, size=size, fs=FS)

    assert np.all(mask[: _n(2)])
    assert not np.any(mask[_n(2) : _n(3)])
    assert np.all(mask[_n(3) :])


def test_case_insensitive_matching(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("DRINK", 1.0, 0.0),
            ("Drink_End", 5.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_after_sec=0.5, size=size, fs=FS)
    assert not np.any(mask[_n(1) : _n(1) + _n(0.5)])
    assert not np.any(mask[_n(5) : _n(5) + _n(0.5)])


def test_substring_match(tmp_path):
    """Label 'drinking_bout' should match keyword 'drink' in contains mode."""
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drinking_bout", 2.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_after_sec=1.0, size=size, fs=FS)
    assert not np.any(mask[_n(2) : _n(3)])


def test_no_keyword_match_returns_all_true(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("groom", 2.0, 0.5),
        ],
    )
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_after_sec=1.0, size=size, fs=FS)
    assert np.all(mask)


def test_multiple_keywords_or_logic(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 1.0, 0.0),
            ("groom", 3.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink", "groom"], pad_after_sec=0.5, size=size, fs=FS)
    assert not np.any(mask[_n(1) : _n(1) + _n(0.5)])
    assert not np.any(mask[_n(3) : _n(3) + _n(0.5)])
    assert np.all(mask[_n(1) + _n(0.5) : _n(3)])


def test_multiple_events_same_keyword(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 1.0, 0.0),
            ("drink", 4.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_after_sec=1.0, size=size, fs=FS)
    assert not np.any(mask[_n(1) : _n(2)])
    assert not np.any(mask[_n(4) : _n(5)])
    assert np.all(mask[_n(2) : _n(4)])
    assert np.all(mask[_n(5) :])


# ---------------------------------------------------------------------------
# Exact match mode
# ---------------------------------------------------------------------------


def test_exact_match_hits_full_label(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 2.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(
        ann_file, keywords=["drink"], pad_after_sec=1.0, size=size, fs=FS, match_mode="exact"
    )
    assert not np.any(mask[_n(2) : _n(3)])
    assert np.all(mask[_n(3) :])


def test_exact_match_does_not_match_substring(tmp_path):
    """'drink' should NOT match 'drinking_bout' in exact mode."""
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drinking_bout", 2.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(
        ann_file, keywords=["drink"], pad_after_sec=1.0, size=size, fs=FS, match_mode="exact"
    )
    assert np.all(mask)  # no match → all True


def test_exact_match_case_insensitive(tmp_path):
    """Exact match should still be case-insensitive."""
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("DRINK", 2.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(
        ann_file, keywords=["drink"], pad_after_sec=1.0, size=size, fs=FS, match_mode="exact"
    )
    assert not np.any(mask[_n(2) : _n(3)])


def test_contains_matches_where_exact_does_not(tmp_path):
    """Confirm contains and exact behave differently on the same file."""
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drinking_bout", 2.0, 0.0),
        ],
    )
    size = _n(10)
    contains_mask = keyword_mask(
        ann_file, keywords=["drink"], pad_after_sec=1.0, size=size, fs=FS, match_mode="contains"
    )
    exact_mask = keyword_mask(
        ann_file, keywords=["drink"], pad_after_sec=1.0, size=size, fs=FS, match_mode="exact"
    )
    assert not np.any(contains_mask[_n(2) : _n(3)])  # contains: masked
    assert np.all(exact_mask)  # exact: no match


# ---------------------------------------------------------------------------
# Padding — before and after
# ---------------------------------------------------------------------------


def test_pad_after_only(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 2.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(
        ann_file, keywords=["drink"], pad_before_sec=0.0, pad_after_sec=1.0, size=size, fs=FS
    )
    assert np.all(mask[: _n(2)])
    assert not np.any(mask[_n(2) : _n(3)])
    assert np.all(mask[_n(3) :])


def test_pad_before_only(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 3.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(
        ann_file, keywords=["drink"], pad_before_sec=1.0, pad_after_sec=0.0, size=size, fs=FS
    )
    # Masked: [2s, 3s + 1 sample)
    assert np.all(mask[: _n(2)])
    assert not np.any(mask[_n(2) : _n(3)])
    # Annotation sample itself masked (min 1 after)
    assert not mask[_n(3)]
    assert np.all(mask[_n(3) + 1 :])


def test_pad_before_and_after(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 3.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(
        ann_file, keywords=["drink"], pad_before_sec=1.0, pad_after_sec=2.0, size=size, fs=FS
    )
    # Masked: [2s, 5s)
    assert np.all(mask[: _n(2)])
    assert not np.any(mask[_n(2) : _n(5)])
    assert np.all(mask[_n(5) :])


def test_pad_before_clipped_at_start(tmp_path):
    """pad_before extending before sample 0 should be clipped."""
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 0.5, 0.0),
        ],
    )
    size = _n(10)
    # pad_before would extend to -0.5s → clipped to 0
    mask = keyword_mask(
        ann_file, keywords=["drink"], pad_before_sec=1.0, pad_after_sec=0.0, size=size, fs=FS
    )
    assert not np.any(mask[: _n(0.5) + 1])
    assert np.all(mask[_n(0.5) + 1 :])


# ---------------------------------------------------------------------------
# Time-offset adjustment
# ---------------------------------------------------------------------------


def test_times_adjusted_relative_to_first_annotation(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 10.0, 0.0),
            ("drink", 12.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_after_sec=1.0, size=size, fs=FS)
    assert np.all(mask[: _n(2)])
    assert not np.any(mask[_n(2) : _n(3)])
    assert np.all(mask[_n(3) :])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_keywords_list_returns_all_true(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 1.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=[], pad_after_sec=1.0, size=size, fs=FS)
    assert np.all(mask)


def test_whitespace_only_keywords_treated_as_empty(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 1.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["  ", "\t"], pad_after_sec=1.0, size=size, fs=FS)
    assert np.all(mask)


def test_pad_after_zero_masks_at_least_one_sample(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 1.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_after_sec=0.0, size=size, fs=FS)
    assert mask[_n(1) - 1]  # sample before event: True
    assert not mask[_n(1)]  # event sample: False
    assert mask[_n(1) + 1]  # sample after: True


def test_event_at_end_of_recording_clipped(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(
        ann_file,
        [
            ("start", 0.0, 0.0),
            ("drink", 9.0, 0.0),
        ],
    )
    size = _n(10)
    mask = keyword_mask(ann_file, keywords=["drink"], pad_after_sec=5.0, size=size, fs=FS)
    assert not np.any(mask[_n(9) :])
    assert len(mask) == size


def test_returns_correct_size(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [("start", 0.0, 0.0)])
    for size in [100, 1000, 5000]:
        mask = keyword_mask(ann_file, keywords=["drink"], pad_after_sec=1.0, size=size, fs=FS)
        assert len(mask) == size


def test_return_type_is_bool_array(tmp_path):
    ann_file = tmp_path / "annots.txt"
    write_pinnacle(ann_file, [("start", 0.0, 0.0)])
    mask = keyword_mask(ann_file, keywords=["drink"], pad_after_sec=1.0, size=_n(5), fs=FS)
    assert mask.dtype == bool
