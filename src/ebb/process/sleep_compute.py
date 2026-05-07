"""Sleep-state metrics from SPINDLE-scored CSVs.

Two output families:
- Per-bin metrics (`compute_sleep_metrics_per_mouse`, `compute_sleep_bins_df`,
  `compute_sleep_bins_df_offset`): time-binned fraction-of-time and bout
  statistics per state.
- Per-state spindle masking (`compute_spindle_fractions`): how much of each
  state was masked out by SPINDLE's noise probability.

CSV inputs are SPINDLE outputs with a `rawstate` column (`w`/`n`/`r`); the
spindle-fraction function additionally requires a `noise_probs` column.

Sample-rate convention: `compute_sleep_metrics_per_mouse` is rate-agnostic —
the caller passes `sample_rate_hz` to match whatever rate `states` arrives at
(0.25 Hz for raw SPINDLE epochs, 1 Hz after upsampling, etc.).
"""

import csv
import re
from collections import Counter
from datetime import datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ebb.core.naming import parse_animal_id

# SPINDLE epoch length in seconds. Used to upsample 0.25 Hz epoch-rate state
# arrays to 1 Hz second-rate when rotating to a fixed clock hour.
DEFAULT_SPINDLE_EPOCH_SEC = 4

_RAW_STATE_TO_NAME = {"w": "Wake", "n": "NREM", "r": "REM"}
_VALID_RAW_STATES = set(_RAW_STATE_TO_NAME)
_STATE_DISPLAY_ORDER = ["Wake", "NREM", "REM"]


def seconds_until_target(t: time, h: int = 6) -> int:
    """Seconds from clock time `t` forward to the next occurrence of `h:00`.

    If `t` is at or before `h:00` today, the target is today's `h:00`;
    otherwise the target is tomorrow's `h:00`. Used by
    `compute_sleep_bins_df_offset` to compute the rotation offset that
    aligns each animal's data to the same clock hour.

    Note:
        Uses naive datetime arithmetic. `timedelta(days=1)` is exactly
        86,400 seconds and ignores DST transitions; recordings that cross
        a DST shift will have their bin alignment off by one hour. See
        TODO.md for the timezone-aware follow-up.
    """
    today = datetime.today().date()
    now = datetime.combine(today, t)
    target_today = datetime.combine(today, time(h, 0))
    target = target_today if now <= target_today else target_today + timedelta(days=1)
    return int((target - now).total_seconds())


def _read_rawstate_column(state_path: Path) -> list[str]:
    """Read the `rawstate` column from a SPINDLE-scored CSV (one entry per epoch)."""
    with open(state_path) as infile:
        reader = csv.reader(infile)
        header = next(reader)
        if "rawstate" not in header:
            raise ValueError(f"'rawstate' column not found in {state_path.name}")
        idx = header.index("rawstate")
        return [row[idx] for row in reader]


def compute_sleep_metrics_per_mouse(
    states,
    mouse_id=None,
    group=None,
    dataset=None,
    bin_hours=2,
    sample_rate_hz=0.25,
):
    """Per-bin fraction-of-time + bout statistics for one mouse's state array.

    Args:
        states: 1-D array of state labels for one mouse. Sample rate is
            controlled by `sample_rate_hz`, not assumed.
        mouse_id, group, dataset: Optional identifying metadata copied to
            every output row.
        bin_hours: Bin width in hours.
        sample_rate_hz: Sampling rate of `states`. SPINDLE epoch-rate is
            0.25 Hz; pass 1.0 if you've already upsampled to per-second.

    Returns:
        Long-form DataFrame with one row per (bin × state).
    """
    states = np.asarray(states)
    n_samples = len(states)

    bin_size_samples = int(bin_hours * 3600 * sample_rate_hz)
    if bin_size_samples <= 0:
        raise ValueError("bin_hours * 3600 * sample_rate_hz must be >= 1 sample")

    n_bins = int(np.ceil(n_samples / bin_size_samples))
    unique_states = np.unique(states)

    def bouts_for_state(mask, sample_rate_hz):
        # Run-length encoding via diff. The mask[0]/mask[-1] guards handle
        # bouts that touch the bin's left/right edge (no preceding/following
        # transition to detect via diff).
        if mask.size == 0:
            return 0, np.nan

        x = mask.astype(int)
        dx = np.diff(x)
        starts = np.where(dx == 1)[0] + 1
        ends = np.where(dx == -1)[0] + 1

        if mask[0]:
            starts = np.r_[0, starts]
        if mask[-1]:
            ends = np.r_[ends, mask.size]

        if len(starts) == 0:
            return 0, np.nan

        durations_sec = (ends - starts) / sample_rate_hz
        return len(durations_sec), durations_sec.mean()

    rows = []
    for bin_idx in range(n_bins):
        start = bin_idx * bin_size_samples
        end = min((bin_idx + 1) * bin_size_samples, n_samples)
        bin_states = states[start:end]
        bin_len = len(bin_states)
        if bin_len == 0:
            continue

        for state in unique_states:
            mask = bin_states == state
            time_in_state = mask.sum()
            frac_time = time_in_state / bin_len
            n_bouts, mean_bout_sec = bouts_for_state(mask, sample_rate_hz)

            rows.append(
                {
                    "mouse_id": mouse_id,
                    "group": group,
                    "dataset": dataset,
                    "bin_idx": bin_idx,
                    "bin_start_sec": start / sample_rate_hz,
                    "bin_start_hr": start / (3600 * sample_rate_hz),
                    "state": state,
                    "frac_time": frac_time,
                    "n_bouts": n_bouts,
                    "mean_bout_sec": mean_bout_sec,
                }
            )

    return pd.DataFrame(rows)


def compute_sleep_bins_df(
    state_dir: str | Path,
    bin_hours: int = 2,
) -> pd.DataFrame:
    """Aggregate per-bin metrics across every SPINDLE CSV in `state_dir`.

    Each CSV's states are kept at the SPINDLE epoch rate (0.25 Hz).
    """
    sleep_dfs = []
    for state_path in Path(state_dir).glob("*.csv"):
        animal = parse_animal_id(state_path)
        states = _read_rawstate_column(state_path)
        df_mouse = compute_sleep_metrics_per_mouse(
            states, mouse_id=animal, bin_hours=bin_hours, sample_rate_hz=0.25
        )
        sleep_dfs.append(df_mouse)
    return pd.concat(sleep_dfs, ignore_index=True)


def compute_sleep_bins_df_offset(
    state_dir: str | Path,
    bin_hours: int = 2,
    begin_hr: int = 6,
    spindle_epoch_sec: int = DEFAULT_SPINDLE_EPOCH_SEC,
) -> pd.DataFrame:
    """Like `compute_sleep_bins_df`, but rotates each animal's state array so
    that bin 0 starts at `begin_hr:00` clock time.

    The recording start time is parsed from `_HH_MM_SS_` in the filename
    (project EDF-stem convention). Each state array is upsampled from
    SPINDLE epoch rate to per-second by repeating each epoch
    `spindle_epoch_sec` times, then rotated so that the slice covering
    `[begin_hr:00, ...]` comes first.

    Args:
        state_dir: Directory of SPINDLE CSVs.
        bin_hours: Bin width in hours.
        begin_hr: Clock hour (0-23) at which bin 0 should start.
        spindle_epoch_sec: SPINDLE epoch length in seconds.

    Raises:
        ValueError: if a CSV's filename doesn't include the `_HH_MM_SS_`
            pattern, or if the recording is too short to contain the rotation
            offset (rotation would silently no-op).
    """
    # TODO: parse start time from the paired EDF header instead of regex'ing
    # the filename. See TODO.md "sleep_compute: Pair state CSVs with EDFs".
    sleep_dfs = []
    for state_path in Path(state_dir).glob("*.csv"):
        animal = parse_animal_id(state_path)
        match = re.search(r"_(\d{2})_(\d{2})_(\d{2})_", str(state_path))
        if not match:
            raise ValueError(f"Could not parse start time from filename: {state_path.name}")
        hh, mm, ss = map(int, match.groups())
        t = time(hh, mm, ss)

        states = _read_rawstate_column(state_path)
        # SPINDLE epoch-rate (0.25 Hz) → per-second by repeating each epoch
        # spindle_epoch_sec times.
        expanded_states = [s for s in states for _ in range(spindle_epoch_sec)]

        offset = seconds_until_target(t=t, h=begin_hr)
        if offset >= len(expanded_states):
            raise ValueError(
                f"Recording for {animal} is too short for begin_hr={begin_hr} rotation: "
                f"offset={offset}s but recording is only {len(expanded_states)}s long. "
                f"Drop the animal or pick a closer begin_hr."
            )
        offset_states = expanded_states[offset:] + expanded_states[:offset]

        df_mouse = compute_sleep_metrics_per_mouse(
            offset_states, mouse_id=animal, bin_hours=bin_hours, sample_rate_hz=1
        )
        df_mouse["bin_start_sec"] = df_mouse["bin_start_sec"] + (3600 * begin_hr)
        df_mouse["bin_start_hr"] = df_mouse["bin_start_hr"] + begin_hr

        sleep_dfs.append(df_mouse)

    return pd.concat(sleep_dfs, ignore_index=True)


def compute_spindle_fractions(
    state_dir: str | Path,
    noise_prob_threshold: float = 0.5,
) -> pd.DataFrame:
    """Per-animal, per-state spindle mask fractions from SPINDLE output CSVs.

    Reads the `rawstate` column (`w`/`n`/`r`) to determine sleep state and
    the `noise_probs` column to determine whether each epoch is spindle-
    masked. An epoch is counted as spindle-masked when its noise probability
    is >= `noise_prob_threshold`.

    Returns:
        Long-form DataFrame with one row per (animal × state) plus a "Total"
        row per animal. Columns: mouse_id, state, clean_count, spindle_count,
        total_count, fraction. State order: Wake, NREM, REM, Total.
    """
    rows: list[dict] = []
    for state_path in sorted(Path(state_dir).glob("*.csv")):
        animal = parse_animal_id(state_path)
        with open(state_path) as f:
            reader = csv.reader(f)
            header = next(reader)
            if "rawstate" not in header:
                raise ValueError(f"'rawstate' column not found in {state_path.name}")
            if "noise_probs" not in header:
                raise ValueError(f"'noise_probs' column not found in {state_path.name}")
            raw_idx = header.index("rawstate")
            noise_idx = header.index("noise_probs")

            clean_counts: Counter = Counter()
            spindle_counts: Counter = Counter()
            for row in reader:
                raw = row[raw_idx]
                if raw not in _VALID_RAW_STATES:
                    continue
                if float(row[noise_idx]) >= noise_prob_threshold:
                    spindle_counts[raw] += 1
                else:
                    clean_counts[raw] += 1

        for state_label in _STATE_DISPLAY_ORDER:
            raw = next(k for k, v in _RAW_STATE_TO_NAME.items() if v == state_label)
            clean = clean_counts[raw]
            spindle = spindle_counts[raw]
            total = clean + spindle
            rows.append(
                {
                    "mouse_id": animal,
                    "state": state_label,
                    "clean_count": clean,
                    "spindle_count": spindle,
                    "total_count": total,
                    "fraction": spindle / total if total > 0 else float("nan"),
                }
            )

        total_spindle = sum(spindle_counts.values())
        total_clean = sum(clean_counts.values())
        total_all = total_clean + total_spindle
        rows.append(
            {
                "mouse_id": animal,
                "state": "Total",
                "clean_count": total_clean,
                "spindle_count": total_spindle,
                "total_count": total_all,
                "fraction": total_spindle / total_all if total_all > 0 else float("nan"),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=["mouse_id", "state", "clean_count", "spindle_count", "total_count", "fraction"]
        )

    df = pd.DataFrame(rows)
    state_cat = pd.CategoricalDtype(["Wake", "NREM", "REM", "Total"], ordered=True)
    df["state"] = df["state"].astype(state_cat)
    return df
