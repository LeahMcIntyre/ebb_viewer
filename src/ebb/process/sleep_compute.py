"""Sleep-state metrics from SPINDLE-scored CSVs.

Two output families:
- Per-bin metrics (`compute_sleep_metrics_per_mouse`, `compute_sleep_bins_df`,
  `compute_sleep_bins_df_offset`): time-binned fraction-of-time and bout
  statistics per state.
- Per-state spindle masking (`compute_spindle_fractions`): how much of each
  state was masked out by SPINDLE's noise probability.

CSV inputs are SPINDLE outputs with a `rawstate` column (`w`/`n`/`r`), or
`state` in newer SPINDLE outputs; the spindle-fraction function additionally
requires a noise-probability column (`noise_probs`, or `noise_prob` in
newer outputs).

Sample-rate convention: `compute_sleep_metrics_per_mouse` is rate-agnostic —
the caller passes `sample_rate_hz` to match whatever rate `states` arrives at
(0.25 Hz for raw SPINDLE epochs, 1 Hz after upsampling, etc.).
"""

import csv
import warnings
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ebb.core.naming import parse_animal_id
from ebb.io.edf_header import read_edf_start_datetime
from ebb.io.spindle_csv import NOISE_COLUMNS, STATE_COLUMNS, resolve_column

# SPINDLE epoch length in seconds. Used to upsample 0.25 Hz epoch-rate state
# arrays to 1 Hz second-rate when rotating to a fixed clock hour.
DEFAULT_SPINDLE_EPOCH_SEC = 4

_RAW_STATE_TO_NAME = {"w": "Wake", "n": "NREM", "r": "REM"}
_VALID_RAW_STATES = set(_RAW_STATE_TO_NAME)
_STATE_DISPLAY_ORDER = ["Wake", "NREM", "REM"]


def seconds_until_target(start: datetime, h: int = 6) -> int:
    """Real-elapsed seconds from ``start`` forward to the next wall-clock ``h:00``.

    If ``start`` is at or before ``h:00`` on its calendar date, the target is
    that same day's ``h:00``; otherwise the target is the next day's ``h:00``.

    When ``start`` carries a ``tzinfo``, the diff is computed in UTC so the
    returned seconds reflect actual elapsed real time — recordings that cross
    a DST transition resolve to 7h/9h rather than a naive 8h across the
    22:00 → 06:00 window. Naive ``start`` falls back to wall-clock arithmetic.

    Implementation note: when both endpoints share the same ZoneInfo instance,
    Python's ``-`` operator skips UTC normalization and diffs the wall-clock
    fields. ``astimezone(timezone.utc)`` forces the normalization.
    """
    target_today = start.replace(hour=h, minute=0, second=0, microsecond=0)
    if start <= target_today:
        target = target_today
    else:
        next_date = (start + timedelta(days=1)).date()
        target = datetime.combine(next_date, time(h, 0), tzinfo=start.tzinfo)
    if start.tzinfo is not None:
        return int(
            (target.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds()
        )
    return int((target - start).total_seconds())


def read_rawstate_column(state_path: Path) -> list[str]:
    """Read the per-epoch state column from a SPINDLE-scored CSV.

    Reads ``rawstate`` if present, else ``state`` (newer SPINDLE outputs
    store the same clean `w`/`n`/`r` values under `state` instead).

    Raises:
        ValueError: if the file is empty or has neither column.
    """
    with open(state_path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"'rawstate' column not found in {state_path.name}")
        try:
            idx = header.index(resolve_column(header, STATE_COLUMNS))
        except ValueError:
            raise ValueError(f"'rawstate' column not found in {state_path.name}") from None
        return [row[idx] for row in reader if row]


def _bouts_for_state(mask, sample_rate_hz):
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
            n_bouts, mean_bout_sec = _bouts_for_state(mask, sample_rate_hz)

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
        states = read_rawstate_column(state_path)
        df_mouse = compute_sleep_metrics_per_mouse(
            states, mouse_id=animal, bin_hours=bin_hours, sample_rate_hz=0.25
        )
        sleep_dfs.append(df_mouse)
    return pd.concat(sleep_dfs, ignore_index=True)


def compute_sleep_bins_df_offset(
    state_dir: str | Path,
    edf_dir: str | Path,
    bin_hours: int = 2,
    begin_hr: int = 6,
    spindle_epoch_sec: int = DEFAULT_SPINDLE_EPOCH_SEC,
    tz: ZoneInfo | None = None,
) -> pd.DataFrame:
    """Like `compute_sleep_bins_df`, but rotates each animal's state array so
    that bin 0 starts at `begin_hr:00` clock time.

    Each CSV is paired with its preprocessed EDF in ``edf_dir`` by animal ID
    (the first ``_``-delimited token of the filename stem). The recording
    start datetime is read from the EDF header — the CSV filename is no
    longer parsed for time.

    Each state array is upsampled from SPINDLE epoch rate to per-second by
    repeating each epoch ``spindle_epoch_sec`` times, then rotated so that
    the slice covering ``[begin_hr:00, ...]`` comes first.

    Args:
        state_dir: Directory of SPINDLE CSVs.
        edf_dir: Directory of preprocessed EDFs (typically ``project_root/standard/``).
            CSVs without a matching EDF are skipped with a warning.
        bin_hours: Bin width in hours.
        begin_hr: Clock hour (0-23) at which bin 0 should start.
        spindle_epoch_sec: SPINDLE epoch length in seconds.
        tz: Optional timezone. When given, the EDF header datetime is
            localized so that the next-`begin_hr` rotation honors DST
            transitions (a recording that crosses spring-forward rotates by
            23h of real time, not a naive 24h). ``None`` keeps the legacy
            naive arithmetic.

    Recordings shorter than the rotation offset (i.e. that don't reach the
    next ``begin_hr`` boundary) cannot be rotated and are skipped with a
    ``UserWarning``. Use ``compute_sleep_bins_df_clock_aligned`` to include
    those animals at their true circadian position.
    """
    edf_by_animal = {parse_animal_id(p): p for p in Path(edf_dir).glob("*PROCESSED.edf")}

    sleep_dfs = []
    for state_path in Path(state_dir).glob("*.csv"):
        animal = parse_animal_id(state_path)
        edf_path = edf_by_animal.get(animal)
        if edf_path is None:
            warnings.warn(
                f"No EDF for animal {animal!r} in {edf_dir}; skipping rotation/metrics "
                f"for {state_path.name}.",
                stacklevel=2,
            )
            continue

        rec_start = read_edf_start_datetime(edf_path)
        if tz is not None:
            rec_start = rec_start.replace(tzinfo=tz)

        states = read_rawstate_column(state_path)
        # SPINDLE epoch-rate (0.25 Hz) → per-second by repeating each epoch
        # spindle_epoch_sec times.
        expanded_states = [s for s in states for _ in range(spindle_epoch_sec)]

        offset = seconds_until_target(rec_start, h=begin_hr)
        if offset >= len(expanded_states):
            warnings.warn(
                f"Recording for {animal!r} is too short for begin_hr={begin_hr} "
                f"rotation: offset={offset}s but recording is only "
                f"{len(expanded_states)}s long; skipping (use the clock-aligned "
                f"variant to include this animal).",
                stacklevel=2,
            )
            continue
        offset_states = expanded_states[offset:] + expanded_states[:offset]

        df_mouse = compute_sleep_metrics_per_mouse(
            offset_states, mouse_id=animal, bin_hours=bin_hours, sample_rate_hz=1
        )
        df_mouse["bin_start_sec"] = df_mouse["bin_start_sec"] + (3600 * begin_hr)
        df_mouse["bin_start_hr"] = df_mouse["bin_start_hr"] + begin_hr

        sleep_dfs.append(df_mouse)

    if not sleep_dfs:
        return pd.DataFrame()
    return pd.concat(sleep_dfs, ignore_index=True)


def _bin_states_clock_aligned(
    states,
    mouse_id,
    bin_hours: int,
    rec_start_offset_secs: int,
    begin_hr: int,
    sample_rate_hz: float = 1.0,
) -> pd.DataFrame:
    # Bin states by clock time, anchored to begin_hr boundaries.
    #
    # rec_start_offset_secs is the seconds from the most recent begin_hr
    # boundary at-or-before rec_start to rec_start itself (in [0, 86400)).
    # The recording's sample 0 lands somewhere inside the bin whose left
    # edge is ``(rec_start_offset_secs // bin_size_secs) * bin_size_secs``
    # seconds past that boundary. The first emitted bin is partial whenever
    # rec_start is not on a bin edge. Subsequent bins are full; the final
    # bin may also be partial. bin_start_hr increases monotonically — no
    # mod-24 wrap — so multi-day recordings get distinct positions per day.
    states = np.asarray(states)
    n_samples = len(states)
    if n_samples == 0:
        return pd.DataFrame()

    bin_size_secs = bin_hours * 3600
    bin_size_samples = int(round(bin_size_secs * sample_rate_hz))
    if bin_size_samples <= 0:
        raise ValueError("bin_hours * 3600 * sample_rate_hz must be >= 1 sample")

    first_bin_circadian_start = (rec_start_offset_secs // bin_size_secs) * bin_size_secs
    first_sample_offset_in_bin = int(
        round((rec_start_offset_secs - first_bin_circadian_start) * sample_rate_hz)
    )
    samples_in_first_bin = bin_size_samples - first_sample_offset_in_bin

    unique_states = np.unique(states)
    rows = []
    bin_idx = 0
    sample_pos = 0
    current_circadian_start = first_bin_circadian_start
    while sample_pos < n_samples:
        chunk = samples_in_first_bin if bin_idx == 0 else bin_size_samples
        end_pos = min(sample_pos + chunk, n_samples)

        bin_states = states[sample_pos:end_pos]
        bin_len = len(bin_states)
        if bin_len > 0:
            for state in unique_states:
                mask = bin_states == state
                time_in_state = mask.sum()
                frac_time = time_in_state / bin_len
                n_bouts, mean_bout_sec = _bouts_for_state(mask, sample_rate_hz)
                rows.append(
                    {
                        "mouse_id": mouse_id,
                        "group": None,
                        "dataset": None,
                        "bin_idx": bin_idx,
                        "bin_start_sec": current_circadian_start + 3600 * begin_hr,
                        "bin_start_hr": current_circadian_start / 3600 + begin_hr,
                        "state": state,
                        "frac_time": frac_time,
                        "n_bouts": n_bouts,
                        "mean_bout_sec": mean_bout_sec,
                    }
                )

        sample_pos = end_pos
        bin_idx += 1
        current_circadian_start += bin_size_secs

    return pd.DataFrame(rows)


def compute_sleep_bins_df_clock_aligned(
    state_dir: str | Path,
    edf_dir: str | Path,
    bin_hours: int = 2,
    begin_hr: int = 6,
    spindle_epoch_sec: int = DEFAULT_SPINDLE_EPOCH_SEC,
    tz: ZoneInfo | None = None,
) -> pd.DataFrame:
    """Per-animal sleep bins, placed at their true circadian position.

    Like ``compute_sleep_bins_df_offset`` but instead of rotating each
    recording so bin 0 lands at ``begin_hr:00``, bins are anchored to
    ``begin_hr``-aligned clock boundaries and each recording contributes
    data to whichever bins its wall-clock samples cover. ``bin_start_hr``
    grows monotonically across the recording (e.g. a 48 h recording
    starting at 22:00 with ``begin_hr=6`` yields bins at 22, 24, …, 70 —
    no mod-24 wrap, so day 1 night and day 2 night land at distinct x
    positions). Short recordings that the rotation variant would reject
    instead appear at the partial bin matching their wall-clock window.
    """
    edf_by_animal = {parse_animal_id(p): p for p in Path(edf_dir).glob("*PROCESSED.edf")}

    sleep_dfs = []
    for state_path in Path(state_dir).glob("*.csv"):
        animal = parse_animal_id(state_path)
        edf_path = edf_by_animal.get(animal)
        if edf_path is None:
            warnings.warn(
                f"No EDF for animal {animal!r} in {edf_dir}; skipping rotation/metrics "
                f"for {state_path.name}.",
                stacklevel=2,
            )
            continue

        rec_start = read_edf_start_datetime(edf_path)
        if tz is not None:
            rec_start = rec_start.replace(tzinfo=tz)

        states = read_rawstate_column(state_path)
        expanded_states = [s for s in states for _ in range(spindle_epoch_sec)]
        if not expanded_states:
            warnings.warn(
                f"Empty state CSV for animal {animal!r}; skipping.",
                stacklevel=2,
            )
            continue

        tod_secs = rec_start.hour * 3600 + rec_start.minute * 60 + rec_start.second
        rec_start_offset_secs = (tod_secs - begin_hr * 3600) % (24 * 3600)

        df_mouse = _bin_states_clock_aligned(
            expanded_states,
            mouse_id=animal,
            bin_hours=bin_hours,
            rec_start_offset_secs=rec_start_offset_secs,
            begin_hr=begin_hr,
            sample_rate_hz=1.0,
        )
        sleep_dfs.append(df_mouse)

    if not sleep_dfs:
        return pd.DataFrame()
    return pd.concat(sleep_dfs, ignore_index=True)


def compute_whole_file_metrics(
    state_dir: str | Path,
    spindle_epoch_sec: int = DEFAULT_SPINDLE_EPOCH_SEC,
) -> pd.DataFrame:
    """Per-animal, per-state metrics computed over each whole recording.

    Unlike the binned functions, this collapses each recording to a single
    row per (animal, state), standardized by recording length so animals
    with different-duration recordings are comparable:

    - ``frac_time``: fraction of the whole recording spent in the state
      (already duration-independent).
    - ``n_bouts``: total contiguous runs of the state across the recording.
    - ``mean_bout_sec``: mean bout duration in seconds.
    - ``bouts_per_hour``: ``n_bouts`` normalized by recording length in hours.
    - ``n_hours`` / ``n_days``: recording length, so any other per-time
      normalization is a downstream division.

    States are read from the SPINDLE ``rawstate`` column at epoch rate; no
    EDF pairing or clock alignment is needed. Every animal gets one row per
    ``w``/``n``/``r`` state even if a state never occurs (zero-filled).

    Args:
        state_dir: Directory of SPINDLE CSVs (typically the gathered
            ok-combo CSVs assembled for export).
        spindle_epoch_sec: SPINDLE epoch length in seconds, used to convert
            epoch counts to real time.
    """
    sample_rate_hz = 1.0 / spindle_epoch_sec
    rows: list[dict] = []
    for state_path in sorted(Path(state_dir).glob("*.csv")):
        animal = parse_animal_id(state_path)
        states = np.asarray(read_rawstate_column(state_path))
        n_epochs = len(states)
        n_hours = n_epochs * spindle_epoch_sec / 3600.0
        for raw in _RAW_STATE_TO_NAME:
            mask = states == raw
            time_in_state = int(mask.sum())
            frac_time = time_in_state / n_epochs if n_epochs else float("nan")
            n_bouts, mean_bout_sec = _bouts_for_state(mask, sample_rate_hz)
            rows.append(
                {
                    "mouse_id": animal,
                    "state": raw,
                    "frac_time": frac_time,
                    "n_bouts": n_bouts,
                    "mean_bout_sec": mean_bout_sec,
                    "bouts_per_hour": n_bouts / n_hours if n_hours else float("nan"),
                    "n_hours": n_hours,
                    "n_days": n_hours / 24.0,
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=[
                "mouse_id",
                "state",
                "frac_time",
                "n_bouts",
                "mean_bout_sec",
                "bouts_per_hour",
                "n_hours",
                "n_days",
            ]
        )
    return pd.DataFrame(rows)


def compute_spindle_fractions(
    state_dir: str | Path,
    noise_prob_threshold: float = 0.5,
) -> pd.DataFrame:
    """Per-animal, per-state spindle mask fractions from SPINDLE output CSVs.

    Reads the `rawstate` (or `state`, in newer outputs) column (`w`/`n`/`r`)
    to determine sleep state and the `noise_probs` (or `noise_prob`) column
    to determine whether each epoch is spindle-masked. An epoch is counted
    as spindle-masked when its noise probability is >= `noise_prob_threshold`.

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
            try:
                raw_idx = header.index(resolve_column(header, STATE_COLUMNS))
            except ValueError:
                raise ValueError(f"'rawstate' column not found in {state_path.name}") from None
            try:
                noise_idx = header.index(resolve_column(header, NOISE_COLUMNS))
            except ValueError:
                raise ValueError(f"'noise_probs' column not found in {state_path.name}") from None

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
