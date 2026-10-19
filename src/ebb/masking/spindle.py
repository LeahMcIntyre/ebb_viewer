"""Boolean masks built from a SPINDLE-scored CSV.

SPINDLE writes one row per epoch (epochs are `winsize` seconds long, default
4 s) with a state label and per-class probabilities. These helpers expand
each per-epoch decision to a sample-resolution mask at rate `fs`.

Returned masks follow the project convention: True = keep, False = mask.
"""

import csv
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt

from ebb.io.spindle_csv import (
    ANALYSIS_STATE_COLUMNS,
    NOISE_COLUMNS,
    NotReclassifiedError,
    resolve_column,
)

# SPINDLE encodes class probabilities under columns named `class_prob_{i}`
# where i is the model's output index. The state-letter to index mapping
# below mirrors SPINDLE's training: 0=wake, 1=NREM, 2=REM.
_PROB_COLUMN = {"w": "class_prob_0", "n": "class_prob_1", "r": "class_prob_2"}


def state(
    path: str | Path,
    labels: list[str],
    fs: int = 250,
    winsize: int = 4,
    include: bool = True,
    columns: Sequence[str] = ANALYSIS_STATE_COLUMNS,
) -> npt.NDArray[np.bool_]:
    """Returns a mask **selecting** samples whose epoch is in `labels`.

    With `include=True` (default), True marks samples whose SPINDLE-scored
    epoch state is one of `labels` — i.e. the state(s) you want to keep
    for downstream analysis. Set `include=False` to invert (mask the
    state out instead).

    Args:
        path:
            Path to a SPINDLE-scored CSV.
        labels:
            Epoch states to match, e.g. `["w"]` or `["n", "r"]`.
        fs:
            Sample rate of the EEG data the mask will be applied to.
        winsize:
            SPINDLE epoch length in seconds (default 4).
        include:
            If True (default), matched samples are True (kept); if False,
            matched samples are False.
        columns:
            State column(s) to read. Defaults to the reclassified `final_state`
            (raises `NotReclassifiedError` if absent); pass `STATE_COLUMNS` for
            the original SPINDLE states.

    Returns:
        A 1-D boolean array of length `n_epochs * fs * winsize`.
    """
    return _expand_spindle_column(
        path=path,
        column_candidates=columns,
        fs=fs,
        winsize=winsize,
        value_fn=lambda s: s in labels,
        include=include,
    )


def state_prob(
    path: str | Path,
    label: str,
    fs: int = 250,
    winsize: int = 4,
    sprob: float = 0.9,
) -> npt.NDArray[np.bool_]:
    """Returns a mask **selecting** samples whose epoch is `label` *and* whose
    class probability is at least `sprob`.

    True marks samples in confidently-labeled epochs (the ones you want to
    keep). Use this when you want to be stricter than `state` — e.g. only
    take wake epochs SPINDLE was very confident about.

    Args:
        path: Path to a SPINDLE-scored CSV.
        label: Single state letter to match (`"w"`, `"n"`, or `"r"`).
        fs: Sample rate of the target EEG data.
        winsize: SPINDLE epoch length in seconds.
        sprob: Class-probability threshold an epoch must clear.

    Returns:
        A 1-D boolean mask True where state matches AND probability passes.
    """
    state_mask = state(path, labels=[label], fs=fs, winsize=winsize, include=True)
    prob_mask = _expand_spindle_column(
        path=path,
        column_candidates=(_PROB_COLUMN[label],),
        fs=fs,
        winsize=winsize,
        value_fn=lambda v: float(v) >= sprob,
        include=True,
    )
    return state_mask & prob_mask


def spindle_noise(
    path: str | Path,
    noise_thresh: float = 0.5,
    fs: int = 250,
    winsize: int = 4,
    include: bool = False,
) -> npt.NDArray[np.bool_]:
    """Returns a mask **excluding** noise/artifact epochs.

    With `include=False` (default), True marks samples whose epoch noise
    probability is *below* `noise_thresh` — i.e. clean samples you want
    to keep; False marks noisy/artifact samples to drop. Set
    `include=True` to invert (keep only noise — useful for inspection).

    Args:
        path: Path to a SPINDLE-scored CSV.
        noise_thresh: Probability threshold in [0, 1]. Samples in epochs
            whose noise probability (`noise_probs`, or `noise_prob` in
            newer SPINDLE outputs) is at or above this become False (when
            `include=False`).
        fs: Sample rate of the target EEG data.
        winsize: SPINDLE epoch length in seconds.
        include: If False (default), high-noise samples are masked out;
            if True, they are kept and everything else is masked.

    Returns:
        A 1-D boolean mask.
    """
    return _expand_spindle_column(
        path=path,
        column_candidates=NOISE_COLUMNS,
        fs=fs,
        winsize=winsize,
        value_fn=lambda v: float(v) >= noise_thresh,
        include=include,
    )


def _expand_spindle_column(
    path: str | Path,
    column_candidates: Sequence[str],
    fs: int,
    winsize: int,
    value_fn: Callable[[str], bool],
    include: bool = True,
) -> npt.NDArray[np.bool_]:
    """Read one column of a SPINDLE CSV and expand to a sample-resolution mask.

    Each per-epoch boolean is repeated `fs * winsize` times so the result
    has one element per audio sample over the recording.

    Args:
        column_candidates: Column names to try, in priority order. The
            first one present in the CSV header is used.
    """
    with open(path, newline="") as infile:
        reader = csv.reader(infile)
        header = next(reader)

        try:
            column_name = resolve_column(header, column_candidates)
        except ValueError as e:
            if tuple(column_candidates) == ANALYSIS_STATE_COLUMNS:
                raise NotReclassifiedError(Path(path).name) from e
            raise ValueError(
                f"Spindle file format needs update. Expected one of "
                f"{list(column_candidates)} in the CSV header."
            ) from e

        idx = header.index(column_name)
        values = [row[idx] for row in reader]

    mask = np.array([value_fn(v) for v in values], dtype=bool)
    if not include:
        mask = ~mask
    return np.repeat(mask, fs * winsize)
