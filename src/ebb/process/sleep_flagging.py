"""Annotation-free metrics for flagging problem SPINDLE files.

Computed from the ``final_state`` column (see ``nrem_reclass``) over the whole
recording. Each metric has an optional threshold; a file past it is flagged for
the user to review. Defaults come from the spindle-validation analysis
(``file_flagging_metrics.ipynb``) and are starting points, not validated cutoffs.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pandas as pd

from ebb.core.naming import parse_animal_id
from ebb.io.edf_header import read_edf_start_datetime
from ebb.io.spindle_csv import read_analysis_states
from ebb.process.nrem_reclass import EPOCH_SEC, light_period_mask

BIN_HOURS = 2
BIN_EPOCHS = BIN_HOURS * 3600 // EPOCH_SEC
SHORT_BOUT_EPOCHS = 2  # NREM bouts of 1 or 2 epochs count as "short"

ABOVE = "above"
BELOW = "below"
AT_LEAST = "at least"


@dataclass(frozen=True)
class Metric:
    """One flagging metric: how to label it and where it flags by default."""

    key: str
    label: str
    direction: str | None = None  # ABOVE | BELOW | AT_LEAST; None = never flags
    default: float | None = None  # default threshold; None when direction is None


METRICS: tuple[Metric, ...] = (
    Metric("nrem_short", "Short (1-2 epoch) NREM bouts per file", ABOVE, 400),
    Metric("dark_bouts_h", "NREM bouts per dark hour", ABOVE, 15),
    Metric("pct_rem", "REM % (whole file)"),
    Metric("pct_nrem", "NREM % (whole file)", BELOW, 30),
    Metric("pct_wake", "Wake % (whole file)"),
    Metric("max_bin_rem", f"Max REM % in a {BIN_HOURS}-hour bin", AT_LEAST, 35),
)
METRIC_BY_KEY = {m.key: m for m in METRICS}


def default_thresholds() -> dict[str, float]:
    """``{key: cutoff}`` for every metric that flags."""
    return {m.key: m.default for m in METRICS if m.direction is not None}


def bout_lengths(states: npt.NDArray, state: str) -> npt.NDArray[np.int64]:
    """Length (in epochs) of every run of ``state``."""
    padded = np.r_[False, states == state, False]
    change = np.diff(padded.astype(int))
    return np.flatnonzero(change == -1) - np.flatnonzero(change == 1)


def bout_starts(states: npt.NDArray, state: str) -> npt.NDArray[np.int64]:
    """Index of the first epoch of every run of ``state``."""
    return np.flatnonzero(np.diff(np.r_[False, states == state].astype(int)) == 1)


def file_metrics(states: npt.NDArray, dark: npt.NDArray[np.bool_]) -> dict[str, float]:
    """The flagging metrics for one file.

    Args:
        states: Per-epoch ``"w"``/``"n"``/``"r"`` states.
        dark: Per-epoch dark-period mask, same length as ``states``.

    ``dark_bouts_h`` and ``max_bin_rem`` are NaN when the file has no dark
    hours or is shorter than one full bin.
    """
    states = np.asarray(states)
    n = len(states)
    if n == 0:
        raise ValueError("No epochs")
    nrem_bouts = bout_lengths(states, "n")
    dark_hours = dark.sum() * EPOCH_SEC / 3600
    n_bins = n // BIN_EPOCHS
    rem_bins = [
        100 * np.mean(states[i * BIN_EPOCHS : (i + 1) * BIN_EPOCHS] == "r") for i in range(n_bins)
    ]
    return {
        "nrem_short": int((nrem_bouts <= SHORT_BOUT_EPOCHS).sum()),
        "dark_bouts_h": (
            dark[bout_starts(states, "n")].sum() / dark_hours if dark_hours else float("nan")
        ),
        "pct_rem": 100 * float(np.mean(states == "r")),
        "pct_nrem": 100 * float(np.mean(states == "n")),
        "pct_wake": 100 * float(np.mean(states == "w")),
        "max_bin_rem": max(rem_bins) if rem_bins else float("nan"),
    }


def past_threshold(value: float, direction: str, cutoff: float) -> bool:
    """True when ``value`` is on the flag side of ``cutoff`` (NaN never flags)."""
    if direction == ABOVE:
        return value > cutoff
    if direction == AT_LEAST:
        return value >= cutoff
    if direction == BELOW:
        return value < cutoff
    raise ValueError(f"Unknown direction {direction!r}")


def flagged_metrics(
    metrics: dict[str, float], thresholds: dict[str, float] | None = None
) -> list[str]:
    """Keys of the metrics that put a file past their threshold.

    ``thresholds`` maps metric key to cutoff; metrics missing from it, or with
    no direction, never flag.
    """
    thresholds = default_thresholds() if thresholds is None else thresholds
    return [
        m.key
        for m in METRICS
        if m.direction is not None
        and m.key in thresholds
        and past_threshold(metrics[m.key], m.direction, thresholds[m.key])
    ]


def metrics_for_file(csv_path: str | Path, edf_path: str | Path) -> dict[str, float]:
    """``file_metrics`` from a CSV's ``final_state`` and the EDF's start time.

    Raises:
        NotReclassifiedError: if the CSV lacks ``final_state``.
    """
    states = np.asarray(read_analysis_states(csv_path))
    dark = ~light_period_mask(read_edf_start_datetime(Path(edf_path)), len(states))
    return file_metrics(states, dark)


def metrics_table(state_dir: str | Path, edf_dir: str | Path) -> pd.DataFrame:
    """One row per animal (index ``animal``) with every metric.

    CSVs without a matching preprocessed EDF are skipped with a warning.
    """
    edf_by_animal = {parse_animal_id(p): p for p in Path(edf_dir).glob("*PROCESSED.edf")}
    rows = {}
    for csv_path in sorted(Path(state_dir).glob("*.csv")):
        animal = parse_animal_id(csv_path)
        edf_path = edf_by_animal.get(animal)
        if edf_path is None:
            warnings.warn(f"No EDF for animal {animal!r} in {edf_dir}; skipping {csv_path.name}.")
            continue
        rows[animal] = metrics_for_file(csv_path, edf_path)
    return pd.DataFrame.from_dict(rows, orient="index", columns=[m.key for m in METRICS]).rename_axis(
        "animal"
    )
