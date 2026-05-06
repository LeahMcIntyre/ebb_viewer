from pathlib import Path

import numpy as np
import pytest
from scipy.io import loadmat, savemat

from ebb.io.combine import combine_swd, pair


def test_pair_groups_by_token(tmp_path: Path):
    # token = "CW0DA2" (everything before first underscore)
    p1 = tmp_path / "CW0DA2_P096_part1.edf"
    p2 = tmp_path / "CW0DA2_P096_part2.edf"
    p3 = tmp_path / "CW0DA2_P096_part3.edf"
    q1 = tmp_path / "OTHER_P001_part1.edf"
    q2 = tmp_path / "OTHER_P001_part2.edf"

    # files do not need to exist for pair(); it uses stem strings
    paths = [p1, p2, p3, q1, q2]

    groups = pair(paths, pattern=r"[^_]+")  # default behavior

    # Convert to sorted lists of stems for stable comparisons
    grouped_stems = [sorted([p.stem for p in g]) for g in groups]

    assert sorted(grouped_stems) == sorted(
        [
            sorted([p1.stem, p2.stem, p3.stem]),
            sorted([q1.stem, q2.stem]),
        ]
    )


def test_pair_raises_if_no_match(tmp_path: Path):
    # Only one file with token "LONE" -> should raise
    lone = tmp_path / "LONE_P999_part1.edf"
    other = tmp_path / "DIFF_P001_part1.edf"

    with pytest.raises(ValueError, match="No match found"):
        pair([lone, other], pattern=r"[^_]+")


def test_pair_does_not_match_token_prefix(tmp_path: Path):
    # Regression: previously `pair` used substring containment (`token in
    # other.stem`), which silently grouped "CW1" with "CW10..." files.
    # Now match must be exact on the regex token.
    a1 = tmp_path / "CW1_P001_part1.edf"
    a2 = tmp_path / "CW1_P001_part2.edf"
    b1 = tmp_path / "CW10_P002_part1.edf"
    b2 = tmp_path / "CW10_P002_part2.edf"

    groups = pair([a1, a2, b1, b2], pattern=r"[^_]+")

    grouped_stems = sorted(sorted(p.stem for p in g) for g in groups)
    assert grouped_stems == sorted(
        [
            sorted([a1.stem, a2.stem]),
            sorted([b1.stem, b2.stem]),
        ]
    )


def test_combine_swd_shifts_and_stacks_intervals(tmp_path: Path):
    # Names must satisfy:
    # - pair() token pattern default: r"final_ts_([^_]+)" -> token "ANIMAL"
    # - extract_pnum requires "_P###" somewhere in name
    p1 = tmp_path / "final_ts_ANIMAL_P001.mat"
    p2 = tmp_path / "final_ts_ANIMAL_P002.mat"

    # intervals in seconds
    swds1 = np.array([[10.0, 20.0], [100.0, 110.0]])
    swds2 = np.array([[5.0, 7.0], [200.0, 205.0]])

    savemat(p1, {"final_ts": swds1})
    savemat(p2, {"final_ts": swds2})

    # amount_hours=1 -> amount_sec=3600; second file should be shifted by +3600
    created = combine_swd(
        tmp_path,
        amount_hours=1,
        pattern=r"final_ts_([^_]+)",
        verbose=False,
        label_preference="final_ts",
        overwrite=False,
    )

    assert len(created) == 1
    out_path = created[0]
    assert out_path.exists()
    assert out_path.stem.endswith("_COMBINED")

    out = loadmat(out_path, squeeze_me=True, struct_as_record=False)
    out_swds = np.asarray(out["final_ts"])

    expected = np.vstack(
        [
            swds1,
            swds2 + 3600.0,  # shifted by one chunk
        ]
    )

    # combine_swd sorts by start time; expected is already sorted
    assert out_swds.shape == expected.shape
    assert np.allclose(out_swds, expected)


def test_combine_swd_truncates_events_straddling_boundary(tmp_path: Path):
    # Regression: events whose start is within [0, amount_sec) but whose stop
    # exceeds amount_sec must have their stop clamped to the boundary so
    # they do not overlap the next file's timespan after shifting.
    p1 = tmp_path / "final_ts_ANIMAL_P001.mat"
    p2 = tmp_path / "final_ts_ANIMAL_P002.mat"

    # second event starts before boundary (3500) but ends after (3700)
    swds1 = np.array([[10.0, 20.0], [3500.0, 3700.0]])
    swds2 = np.array([[5.0, 7.0]])

    savemat(p1, {"final_ts": swds1})
    savemat(p2, {"final_ts": swds2})

    created = combine_swd(
        tmp_path,
        amount_hours=1,  # amount_sec = 3600
        pattern=r"final_ts_([^_]+)",
        verbose=False,
        label_preference="final_ts",
        overwrite=False,
    )

    out = loadmat(created[0], squeeze_me=True, struct_as_record=False)
    out_swds = np.asarray(out["final_ts"])

    expected = np.array(
        [
            [10.0, 20.0],
            [3500.0, 3600.0],  # straddling event clamped at 3600
            [3605.0, 3607.0],  # second file's event shifted by +3600
        ]
    )

    assert out_swds.shape == expected.shape
    assert np.allclose(out_swds, expected)
