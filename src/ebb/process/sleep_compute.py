# processing/sleep_metrics.py
import csv
import re
from collections import Counter
from datetime import datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


def seconds_until_target(t: time, h: int = 6) -> int:

    # Just need to combine with data
    now = datetime.combine(datetime.today(), t)
    target_today = datetime.combine(datetime.today(), time(h, 0))

    if now <= target_today:
        target = target_today
    else:
        target = target_today + timedelta(days=1)

    return int((target - now).total_seconds())


# Used for quick plotting purposes
# TODO: Implement functions for analysis purposes (ex: allows for aggregation across multiple days, offsets time)
def compute_sleep_metrics_per_mouse(
    states,
    mouse_id=None,
    group=None,
    dataset=None,
    bin_hours=2,
    sample_rate_hz=0.25,
):
    """
    states: 1D array of state labels at 1 Hz for one mouse.
    """
    states = np.asarray(states)
    n_samples = len(states)

    bin_size_samples = int(bin_hours * 3600 * sample_rate_hz)
    if bin_size_samples <= 0:
        raise ValueError("bin_hours * 3600 * sample_rate_hz must be >= 1 sample")

    n_bins = int(np.ceil(n_samples / bin_size_samples))
    unique_states = np.unique(states)

    def bouts_for_state(mask, sample_rate_hz):
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

        durations_samples = ends - starts
        durations_sec = durations_samples / sample_rate_hz
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
    state_paths = Path(state_dir).glob("*.csv")

    sleep_dfs = []

    # Iterate through state_paths and get the basic sleep metrics df
    for state_path in state_paths:
        animal = state_path.stem.split("_")[0]
        with open(state_path) as infile:
            reader = csv.reader(infile)
            header = next(reader)
            if "rawstate" not in header:
                raise ValueError(f"'rawstate' column not found in {state_path.name}")
            idx = header.index("rawstate")
            states = [row[idx] for row in reader]
        df_mouse = compute_sleep_metrics_per_mouse(
            states, mouse_id=animal, bin_hours=bin_hours, sample_rate_hz=0.25
        )
        sleep_dfs.append(df_mouse)

    return pd.concat(sleep_dfs, ignore_index=True)


def compute_sleep_bins_df_offset(
    state_dir: str | Path,
    bin_hours: int = 2,
    begin_hr: int = 6,
) -> pd.DataFrame:
    state_paths = Path(state_dir).glob("*.csv")

    sleep_dfs = []

    # Iterate through state_paths and get the basic sleep metrics df
    for state_path in state_paths:
        animal = state_path.stem.split("_")[0]
        s = str(state_path)
        match = re.search(r"_(\d{2})_(\d{2})_(\d{2})_", s)
        if not match:
            raise ValueError(f"Could not parse start time from filename: {state_path.name}")
        hh, mm, ss = map(int, match.groups())
        t = time(hh, mm, ss)

        with open(state_path) as infile:
            reader = csv.reader(infile)
            header = next(reader)
            if "rawstate" not in header:
                raise ValueError(f"'rawstate' column not found in {state_path.name}")
            idx = header.index("rawstate")
            states = [row[idx] for row in reader]
            expanded_states = [state for state in states for _ in range(4)]

        # Start states at next occurance of 6 am and add the end states to the end
        offset = seconds_until_target(t=t, h=begin_hr)
        states_after = expanded_states[offset:]
        states_before = expanded_states[:offset]
        offset_states = states_after + states_before

        df_mouse = compute_sleep_metrics_per_mouse(
            offset_states, mouse_id=animal, bin_hours=bin_hours, sample_rate_hz=1
        )

        df_mouse["bin_start_sec"] = df_mouse["bin_start_sec"] + (3600 * begin_hr)
        df_mouse["bin_start_hr"] = df_mouse["bin_start_hr"] + (begin_hr)

        sleep_dfs.append(df_mouse)

    return pd.concat(sleep_dfs, ignore_index=True)


def compute_spindle_fractions(
    state_dir: str | Path,
    noise_prob_threshold: float = 0.5,
) -> pd.DataFrame:
    """
    Compute per-animal, per-state spindle mask fractions from spindle output CSVs.

    Reads the ``rawstate`` column (``w``/``n``/``r``) to determine sleep state and the
    ``noise_probs`` column to determine whether each epoch is spindle-masked.  An epoch
    is counted as spindle-masked when its noise probability is >= ``noise_prob_threshold``
    (default 0.5).

    Returns a long-form DataFrame with one row per (animal × state) plus a ``Total``
    row per animal.

    Columns: mouse_id, state, clean_count, spindle_count, total_count, fraction
    State order: Wake, NREM, REM, Total.
    """
    STATE_RAW = {"Wake": "w", "NREM": "n", "REM": "r"}
    RAW_VALID = set(STATE_RAW.values())
    STATE_ORDER = ["Wake", "NREM", "REM"]

    rows: list[dict] = []
    for state_path in sorted(Path(state_dir).glob("*.csv")):
        animal = state_path.stem.split("_")[0]
        with open(state_path) as f:
            reader = csv.reader(f)
            header = next(reader)
            if "rawstate" not in header:
                raise ValueError(f"'rawstate' column not found in {state_path.name}")
            if "noise_probs" not in header:
                raise ValueError(f"'noise_probs' column not found in {state_path.name}")
            raw_idx = header.index("rawstate")
            noise_idx = header.index("noise_probs")

            clean_counts = Counter()
            spindle_counts = Counter()
            for row in reader:
                raw = row[raw_idx]
                if raw not in RAW_VALID:
                    continue
                if float(row[noise_idx]) >= noise_prob_threshold:
                    spindle_counts[raw] += 1
                else:
                    clean_counts[raw] += 1

        for state_label in STATE_ORDER:
            raw = STATE_RAW[state_label]
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
