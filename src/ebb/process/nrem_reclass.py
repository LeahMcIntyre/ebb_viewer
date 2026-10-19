"""NREM reclassification of SPINDLE output: gap fill, then an optional EMG gate.

Per file (4-second epochs), starting from SPINDLE's ``rawstate``:

1. **Gap fill** (``gapfill_state``). Only NREM epochs can flip, and they flip to
   Wake when SPINDLE flags the epoch itself as artifact, or when the epoch is
   clean but has an artifact-flagged epoch (of any state) within ``radius``
   epochs both before and after it.
2. **Gate decision.** Count the file's NREM bouts in the light period (a bout
   belongs to the period its first epoch is in) before and after step 1. If the count rises by more than ``FRAGMENTATION_TOL``
   (10%), scattered flips are chopping long bouts, so flips need EMG evidence.
3. **EMG gate** (only where step 2 says so). A flip is kept only if its
   epoch's EMG RMS is above ``median + k * MAD`` of the animal's EMG RMS over
   every epoch SPINDLE calls NREM (artifact-flagged ones included, since that
   flag is what is in question). The gate only cancels flips.
4. ``final_state`` is the gated state where the gate applied, else
   ``gapfill_state``.

An epoch counts as artifact when its noise probability is at or above the
file's ``threshold`` column (else ``DEFAULT_NOISE_THRESHOLD``).

``mad`` here is the plain median absolute deviation, unscaled (no 1.4826).
"""

from __future__ import annotations

import csv
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from ebb.core.naming import parse_animal_id
from ebb.io.edf_header import read_edf_start_datetime
from ebb.io.spindle_csv import (
    NOISE_COLUMNS,
    FINAL_COLUMN,
    RECLASS_COLUMN,
    STATE_COLUMNS,
    resolve_column,
    write_columns,
)

DEFAULT_NOISE_THRESHOLD = 0.5
GAP_RADIUS = 1
FRAGMENTATION_TOL = 0.10
EMG_K = 5.0
EPOCH_SEC = 4
FS = 250
EMG_CHANNEL = 3
# Clock hours that are NOT the light period (20:00 through 05:59).
DARK_HOURS = frozenset({20, 21, 22, 23, 0, 1, 2, 3, 4, 5})

_NREM = "n"
_WAKE = "w"


@dataclass(frozen=True)
class NremReclass:
    """Per-epoch result of reclassifying one SPINDLE file."""

    rawstate: npt.NDArray[np.str_]
    gapfill_state: npt.NDArray[np.str_]
    final_state: npt.NDArray[np.str_]
    gate_applied: bool
    bouts_before: int  # light-period NREM bouts in rawstate
    bouts_after: int  # light-period NREM bouts in gapfill_state


def read_states_and_noise(
    path: str | Path,
) -> tuple[npt.NDArray[np.str_], npt.NDArray[np.float64], float]:
    """(states, noise probabilities, artifact threshold) from a SPINDLE CSV."""
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"empty SPINDLE file: {Path(path).name}")
        try:
            state_idx = header.index(resolve_column(header, STATE_COLUMNS))
            noise_idx = header.index(resolve_column(header, NOISE_COLUMNS))
        except ValueError as e:
            raise ValueError(
                f"{Path(path).name} needs a state column {list(STATE_COLUMNS)} "
                f"and a noise column {list(NOISE_COLUMNS)}"
            ) from e
        thr_idx = header.index("threshold") if "threshold" in header else None

        states: list[str] = []
        noise: list[float] = []
        threshold = DEFAULT_NOISE_THRESHOLD
        found_threshold = False
        for row in reader:
            if not row:
                continue
            states.append(row[state_idx])
            noise.append(float(row[noise_idx]))
            if thr_idx is not None and not found_threshold and row[thr_idx] != "":
                threshold = float(row[thr_idx])
                found_threshold = True
    return np.array(states), np.array(noise), threshold


def gap_fill_flips(
    states: npt.NDArray[np.str_],
    is_artifact: npt.NDArray[np.bool_],
    radius: int = GAP_RADIUS,
) -> npt.NDArray[np.bool_]:
    """NREM epochs that gap fill flips to Wake (True = flip)."""
    n = len(states)
    # padded[i + radius] is epoch i; out-of-range neighbours count as clean.
    padded = np.concatenate([np.zeros(radius, bool), is_artifact, np.zeros(radius, bool)])
    before = np.zeros(n, bool)
    after = np.zeros(n, bool)
    for d in range(1, radius + 1):
        before |= padded[radius - d : radius - d + n]
        after |= padded[radius + d : radius + d + n]
    return (states == _NREM) & (is_artifact | (before & after))


def count_bouts(
    mask: npt.NDArray[np.bool_], start_in: npt.NDArray[np.bool_] | None = None
) -> int:
    """Number of runs of consecutive True values.

    With ``start_in``, only runs whose first epoch is True in ``start_in`` are
    counted, so a bout belongs to the period it starts in even if it runs on
    past the period's end.
    """
    if mask.size == 0:
        return 0
    m = mask.astype(np.int8)
    starts = np.flatnonzero(np.diff(m, prepend=0) == 1)
    return len(starts) if start_in is None else int(start_in[starts].sum())


def needs_emg_gate(bouts_before: int, bouts_after: int, tol: float = FRAGMENTATION_TOL) -> bool:
    """True when gap fill raised the NREM bout count by more than ``tol``."""
    return bouts_after > bouts_before * (1 + tol)


def light_period_mask(start, n_epochs: int, epoch_sec: int = EPOCH_SEC) -> npt.NDArray[np.bool_]:
    """True for epochs whose clock hour is outside ``DARK_HOURS``."""
    secs = np.arange(n_epochs) * epoch_sec
    first = start.hour * 3600 + start.minute * 60 + start.second
    hours = ((first + secs) // 3600) % 24
    return ~np.isin(hours, list(DARK_HOURS))


def emg_cutoff(rms: npt.NDArray[np.float64], nrem: npt.NDArray[np.bool_], k: float = EMG_K) -> float:
    """``median + k * MAD`` of the EMG RMS over all NREM epochs."""
    vals = rms[nrem]
    vals = vals[~np.isnan(vals)]
    if vals.size == 0:
        return float("inf")
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med)))
    return med + k * mad


def epoch_emg_rms(
    edf_path: str | Path,
    channel: int = EMG_CHANNEL,
    fs: int = FS,
    epoch_sec: int = EPOCH_SEC,
) -> npt.NDArray[np.float64]:
    """RMS of the raw EMG channel within each epoch, for the whole recording."""
    from openseize.file_io import edf

    per_epoch = fs * epoch_sec
    with edf.Reader(str(edf_path)) as reader:
        reader.channels = [channel]
        emg = reader.read(0, None)[0]
    n_epochs = len(emg) // per_epoch
    emg = emg[: n_epochs * per_epoch].reshape(n_epochs, per_epoch)
    return np.sqrt(np.mean(emg.astype(np.float64) ** 2, axis=1))


def reclassify_file(
    csv_path: str | Path,
    edf_path: str | Path,
    *,
    radius: int = GAP_RADIUS,
    k: float = EMG_K,
    rms_fn: Callable[[Path], npt.NDArray[np.float64]] = epoch_emg_rms,
) -> NremReclass:
    """Run the full protocol on one SPINDLE CSV.

    ``edf_path`` supplies the recording start time (for the light period) and,
    only when the gate applies, the EMG channel. ``rms_fn`` is injectable so
    tests don't need a real EDF.
    """
    states, noise, threshold = read_states_and_noise(csv_path)
    n = len(states)
    is_artifact = noise >= threshold

    flips = gap_fill_flips(states, is_artifact, radius)
    gapfill = states.copy()
    gapfill[flips] = _WAKE

    light = light_period_mask(read_edf_start_datetime(Path(edf_path)), n)
    before = count_bouts(states == _NREM, light)
    after = count_bouts(gapfill == _NREM, light)

    final = gapfill
    gate = needs_emg_gate(before, after)
    if gate:
        rms = np.full(n, np.nan)
        got = rms_fn(Path(edf_path))[:n]
        rms[: len(got)] = got
        cutoff = emg_cutoff(rms, states == _NREM, k)
        # NaN RMS (EDF shorter than the CSV) compares False, so those flips are cancelled.
        keep = flips & (rms > cutoff)
        final = states.copy()
        final[keep] = _WAKE

    return NremReclass(
        rawstate=states,
        gapfill_state=gapfill,
        final_state=final,
        gate_applied=gate,
        bouts_before=before,
        bouts_after=after,
    )


def _paired_files(state_dir: str | Path, edf_dir: str | Path):
    """Yield ``(animal, csv_path, edf_path)`` for each CSV with a matching EDF.

    CSVs without a matching preprocessed EDF in ``edf_dir`` are skipped with a
    warning (callers fall back to the raw states for them).
    """
    edf_by_animal = {parse_animal_id(p): p for p in Path(edf_dir).glob("*PROCESSED.edf")}
    for csv_path in sorted(Path(state_dir).glob("*.csv")):
        animal = parse_animal_id(csv_path)
        edf_path = edf_by_animal.get(animal)
        if edf_path is None:
            warnings.warn(
                f"No EDF for animal {animal!r} in {edf_dir}; skipping reclassification "
                f"for {csv_path.name} (raw states kept).",
                stacklevel=3,
            )
            continue
        yield animal, csv_path, edf_path


def reclassify_dir(
    state_dir: str | Path,
    edf_dir: str | Path,
    **kwargs,
) -> dict[str, NremReclass]:
    """``reclassify_file`` for every CSV in ``state_dir``, keyed by animal ID."""
    return {
        animal: reclassify_file(csv_path, edf_path, **kwargs)
        for animal, csv_path, edf_path in _paired_files(state_dir, edf_dir)
    }


def reclassify_dir_to_csv(
    state_dir: str | Path,
    edf_dir: str | Path,
    on_animal: Callable[[str, NremReclass], None] | None = None,
    **kwargs,
) -> dict[str, NremReclass]:
    """Reclassify every CSV in ``state_dir`` and write ``reclass_state`` and ``final_state``.

    ``on_animal`` is called after each file is written (for progress logging).
    """
    out: dict[str, NremReclass] = {}
    for animal, csv_path, edf_path in _paired_files(state_dir, edf_dir):
        result = reclassify_file(csv_path, edf_path, **kwargs)
        write_columns(
            csv_path,
            {RECLASS_COLUMN: result.final_state, FINAL_COLUMN: result.final_state},
        )
        out[animal] = result
        if on_animal is not None:
            on_animal(animal, result)
    return out


__all__ = [
    "NremReclass",
    "count_bouts",
    "emg_cutoff",
    "epoch_emg_rms",
    "gap_fill_flips",
    "light_period_mask",
    "needs_emg_gate",
    "read_states_and_noise",
    "reclassify_dir",
    "reclassify_dir_to_csv",
    "reclassify_file",
]
