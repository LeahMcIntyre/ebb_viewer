"""SWD epoch review: which 4 s epochs overlap an SWD, and the ``swd_reclassification`` column.

``swd_reclassification`` is blank except for (a) every epoch that overlaps an SWD
(the user's chosen state, or the current ``reclass_state`` if left alone) and
(b) any epoch the user edited, including non-SWD neighbors. ``final_state`` is then
``swd_reclassification`` where non-blank, else ``reclass_state``, so every
downstream step picks the review up without knowing it happened.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt

from ebb.io.spindle_csv import (
    FINAL_COLUMN,
    RECLASS_COLUMN,
    SWD_COLUMN,
    read_state_column,
    write_columns,
)
from ebb.masking.events import swd_intervals

EPOCH_SEC = 4
VALID_STATES = frozenset({"w", "n", "r"})


def swd_epoch_flags(
    intervals: npt.ArrayLike, n_epochs: int, epoch_sec: float = EPOCH_SEC
) -> npt.NDArray[np.bool_]:
    """True for every epoch that overlaps any ``[start_s, stop_s]`` interval.

    Overlap is strict at the edges: an interval ending exactly where an epoch
    starts (or starting where it ends) does not touch that epoch.
    """
    flags = np.zeros(n_epochs, dtype=bool)
    for start, stop in np.asarray(intervals, dtype=float).reshape(-1, 2):
        if stop < start:
            continue
        first = max(int(math.floor(start / epoch_sec)), 0)
        last = min(int(math.ceil(stop / epoch_sec)) - 1, n_epochs - 1)
        if last >= first:
            flags[first : last + 1] = True
    return flags


def build_swd_column(
    reclass_state: Sequence[str],
    flags: npt.ArrayLike,
    edits: Mapping[int, str],
) -> list[str]:
    """The ``swd_reclassification`` column (see module docstring).

    An edit on a non-SWD epoch that equals ``reclass_state`` is a no-op and
    leaves the row blank.
    """
    flags = np.asarray(flags, dtype=bool)
    n = len(reclass_state)
    if len(flags) != n:
        raise ValueError(f"{len(flags)} SWD flags for {n} epochs")
    out = [reclass_state[i] if flags[i] else "" for i in range(n)]
    for i, state in edits.items():
        if not 0 <= i < n:
            raise ValueError(f"edit for epoch {i} but the file has {n} epochs")
        if state not in VALID_STATES:
            raise ValueError(f"invalid state {state!r} for epoch {i}; expected one of w/n/r")
        if flags[i] or state != reclass_state[i]:
            out[i] = state
    return out


def merge_final_state(reclass_state: Sequence[str], swd_column: Sequence[str]) -> list[str]:
    """``swd_reclassification`` where non-blank, else ``reclass_state``."""
    if len(reclass_state) != len(swd_column):
        raise ValueError(f"{len(reclass_state)} reclass rows vs {len(swd_column)} SWD rows")
    return [s if s != "" else r for r, s in zip(reclass_state, swd_column, strict=True)]


def existing_edits(reclass_state: Sequence[str], swd_column: Sequence[str]) -> dict[int, str]:
    """User edits already saved: non-blank entries that differ from ``reclass_state``."""
    return {
        i: s
        for i, (r, s) in enumerate(zip(reclass_state, swd_column, strict=True))
        if s != "" and s != r
    }


def refresh_swd_after_reclass(
    old_reclass: Sequence[str], old_swd: Sequence[str], new_reclass: Sequence[str]
) -> list[str]:
    """Re-apply saved SWD review after Reclassify is re-run.

    Both old columns are still in the CSV at that point, so an entry equal to the
    OLD ``reclass_state`` is an unedited copy and follows the new ``reclass_state``;
    an entry that differs is a real edit and is kept.
    """
    if not (len(old_reclass) == len(old_swd) == len(new_reclass)):
        raise ValueError("reclass_state / swd_reclassification lengths differ")
    return [
        "" if s == "" else (new if s == old else s)
        for old, s, new in zip(old_reclass, old_swd, new_reclass, strict=True)
    ]


def swd_flags_for_file(csv_path: str | Path, mat_path: str | Path, label: str = "DEL_ts"):
    """``(reclass_state, flags)`` for one animal: its states and which epochs overlap an SWD."""
    reclass = read_state_column(csv_path, RECLASS_COLUMN)
    flags = swd_epoch_flags(swd_intervals(mat_path, label), len(reclass))
    return reclass, flags


def save_swd_review(
    csv_path: str | Path,
    mat_path: str | Path,
    edits: Mapping[int, str],
    label: str = "DEL_ts",
) -> tuple[int, int]:
    """Write ``swd_reclassification`` and the recomputed ``final_state`` into the CSV.

    Returns ``(n_swd_epochs, n_edited)``. The first write backs up the original
    CSV to ``_original/`` (``write_columns``).
    """
    reclass, flags = swd_flags_for_file(csv_path, mat_path, label)
    column = build_swd_column(reclass, flags, edits)
    write_columns(
        csv_path,
        {SWD_COLUMN: column, FINAL_COLUMN: merge_final_state(reclass, column)},
    )
    return int(flags.sum()), len(existing_edits(reclass, column))
