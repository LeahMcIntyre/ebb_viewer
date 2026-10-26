"""Convert sample-level boolean masks into time-stamped intervals for export.

The PSD pipeline computes masks (state, commutator, SD-threshold, drink, ...)
as 1-D boolean arrays at the EDF sampling rate. Downstream tools (Spike2,
MATLAB, R, etc.) prefer interval/event lists keyed by time, not numpy arrays.

This module provides the pure-library primitives that turn masks into
interval rows. Higher-level orchestration (which masks to build for a given
animal, where to write the CSVs) lives in ``ebb_viewer.pipeline.mask_export``.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from ebb.core.arraytools import discretize_bool
from ebb.io.spindle_csv import read_analysis_states

RAWSTATE_TO_NAME: dict[str, str] = {"w": "wake", "n": "nrem", "r": "rem"}


@dataclass(frozen=True, slots=True)
class IntervalRow:
    """A single time-stamped interval. ``end_sample`` is exclusive (Python slice convention)."""

    start_s: float
    end_s: float
    start_sample: int
    end_sample: int
    label: str = ""


def mask_to_intervals(
    mask: npt.NDArray[np.bool_],
    fs: float,
    label: str = "",
) -> list[IntervalRow]:
    """Return contiguous True runs in ``mask`` as ``IntervalRow`` objects.

    Args:
        mask: 1-D boolean array.
        fs: Sampling rate of ``mask`` in Hz.
        label: Optional label attached to every emitted row (e.g. state name).

    Returns:
        List of intervals, one per contiguous True run. Empty list if no Trues.
    """
    if mask.ndim != 1:
        raise ValueError(f"mask must be 1-D, got shape {mask.shape}")
    if mask.size == 0 or not mask.any():
        return []

    pairs = discretize_bool(np.asarray(mask, dtype=bool))
    fs_float = float(fs)
    return [
        IntervalRow(
            start_s=int(s) / fs_float,
            end_s=int(e) / fs_float,
            start_sample=int(s),
            end_sample=int(e),
            label=label,
        )
        for s, e in pairs
    ]


def build_state_intervals(
    state_path: str | Path,
    fs: float = 250,
    winsize: float = 4.0,
    code_to_name: dict[str, str] | None = None,
) -> list[IntervalRow]:
    """Read the reclassified states from a Spindle CSV; one row per contiguous run.

    Uses the ``final_state`` column (``NotReclassifiedError`` if absent; no
    probability filtering — that is a separate, optional step
    applied to ``clean_per_state`` exports).

    Args:
        state_path: Path to the Spindle scoring CSV.
        fs: EDF sampling rate in Hz.
        winsize: Epoch length in seconds (Spindle scoring resolution).
        code_to_name: Map from raw single-letter code to human label. Defaults
            to ``{'w': 'wake', 'n': 'nrem', 'r': 'rem'}``. Unmapped codes are
            kept as-is so unusual scorer outputs (e.g. ``''`` or ``'?'``)
            survive in the export rather than being silently dropped.

    Returns:
        Intervals covering every epoch, labeled by state name. Adjacent epochs
        sharing the same label are merged into a single row. ``end_sample`` is
        exclusive.
    """
    mapping = dict(RAWSTATE_TO_NAME) if code_to_name is None else code_to_name
    raws = read_analysis_states(Path(state_path))
    if not raws:
        return []

    samples_per_epoch = int(round(fs * winsize))
    fs_float = float(fs)

    rows: list[IntervalRow] = []
    run_start = 0
    run_label = raws[0]
    for i in range(1, len(raws)):
        if raws[i] != run_label:
            start_sample = run_start * samples_per_epoch
            end_sample = i * samples_per_epoch
            rows.append(
                IntervalRow(
                    start_s=start_sample / fs_float,
                    end_s=end_sample / fs_float,
                    start_sample=start_sample,
                    end_sample=end_sample,
                    label=mapping.get(run_label, run_label),
                )
            )
            run_start = i
            run_label = raws[i]

    start_sample = run_start * samples_per_epoch
    end_sample = len(raws) * samples_per_epoch
    rows.append(
        IntervalRow(
            start_s=start_sample / fs_float,
            end_s=end_sample / fs_float,
            start_sample=start_sample,
            end_sample=end_sample,
            label=mapping.get(run_label, run_label),
        )
    )
    return rows


def artifact_masks_to_intervals(
    artifact_masks: dict[str, npt.NDArray[np.bool_]],
    fs: float,
) -> list[IntervalRow]:
    """Convert PSD-convention artifact masks (True = OK) to artifact intervals.

    Each input mask is inverted so emitted intervals cover the *artifact* regions
    (the False samples in the original mask). Rows are labeled by the dict key,
    so the caller controls source naming (``"commutator"``, ``"sd_threshold"``,
    ``"drink"``, ...). Output is sorted by start sample, then label, so the same
    inputs always produce a stable CSV.

    Args:
        artifact_masks: Dict mapping source name → 1-D boolean mask. Same
            convention as :func:`ebb.process.psd_compute.estimate_psd`: ``True``
            means the sample is OK, ``False`` means it is in the artifact.
        fs: Sampling rate in Hz.

    Returns:
        Combined intervals across all sources, sorted by ``(start_sample, label)``.
    """
    rows: list[IntervalRow] = []
    for source, mask in artifact_masks.items():
        rows.extend(mask_to_intervals(~np.asarray(mask, dtype=bool), fs, label=source))
    rows.sort(key=lambda r: (r.start_sample, r.label))
    return rows


def clean_per_state_intervals(
    state_masks: dict[str, npt.NDArray[np.bool_]],
    artifact_combined: npt.NDArray[np.bool_],
    fs: float,
) -> list[IntervalRow]:
    """Emit clean intervals per state (state ∩ no-artifact).

    Args:
        state_masks: Dict mapping state name (e.g. ``"wake"``, ``"nrem"``) to
            its 1-D boolean mask. ``True`` means the sample belongs to that
            state.
        artifact_combined: Single 1-D boolean mask, ``True`` where the sample
            is *clean* (i.e. NOT in any artifact). Typically the AND of all
            individual artifact masks (commutator, SD, drink, ...) using PSD's
            "True = OK" convention.
        fs: Sampling rate in Hz.

    Returns:
        Intervals where the state is active AND the sample is clean, one row
        per contiguous run, labeled by state name. Sorted by start sample.
    """
    rows: list[IntervalRow] = []
    clean = np.asarray(artifact_combined, dtype=bool)
    for state, mask in state_masks.items():
        rows.extend(mask_to_intervals(np.asarray(mask, dtype=bool) & clean, fs, label=state))
    rows.sort(key=lambda r: (r.start_sample, r.label))
    return rows


# ---------- writers ----------


def write_intervals_csv(
    path: str | Path,
    rows: list[IntervalRow],
    label_column: str = "label",
) -> None:
    """Write interval rows to a CSV with header.

    The header row is always written (so consumers can rely on column names
    even when there are zero intervals — important for "no artifacts found"
    animals where downstream code shouldn't crash on a missing file).

    Args:
        path: Output CSV path.
        rows: Intervals to write.
        label_column: Name for the per-row label column. Use ``"state"`` for
            state / clean-per-state outputs and ``"source"`` for artifacts.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start_s", "end_s", "start_sample", "end_sample", label_column])
        for r in rows:
            w.writerow([r.start_s, r.end_s, r.start_sample, r.end_sample, r.label])


def write_meta_json(path: str | Path, meta: Mapping[str, Any]) -> None:
    """Write export metadata to a JSON sidecar (atomic via tmp+rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(dict(meta), f, indent=2, default=str)
    tmp.replace(path)


def write_animal_export(
    out_dir: str | Path,
    animal_id: str,
    combo: str,
    state_intervals: list[IntervalRow],
    artifact_intervals: list[IntervalRow],
    clean_intervals: list[IntervalRow],
    meta: Mapping[str, Any],
) -> dict[str, Path]:
    """Write the three CSVs + meta.json for a single animal × combo export.

    Layout::

        <out_dir>/<animal_id>_<combo>_states.csv
        <out_dir>/<animal_id>_<combo>_artifacts.csv
        <out_dir>/<animal_id>_<combo>_clean_per_state.csv
        <out_dir>/<animal_id>_<combo>_meta.json

    Returns:
        Dict of ``kind -> Path`` for the four files written.
    """
    out_dir = Path(out_dir)
    stem = f"{animal_id}_{combo}"
    paths = {
        "states": out_dir / f"{stem}_states.csv",
        "artifacts": out_dir / f"{stem}_artifacts.csv",
        "clean_per_state": out_dir / f"{stem}_clean_per_state.csv",
        "meta": out_dir / f"{stem}_meta.json",
    }
    write_intervals_csv(paths["states"], state_intervals, label_column="state")
    write_intervals_csv(paths["artifacts"], artifact_intervals, label_column="source")
    write_intervals_csv(paths["clean_per_state"], clean_intervals, label_column="state")
    write_meta_json(paths["meta"], meta)
    return paths
