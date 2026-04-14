from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Union, Iterable

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.io import loadmat

def drinking_mask(mask_path: Union[str, Path],
                  offset_sec: Optional[float] = None,
                  fs: int = 250, 
                  pad_sec: int = 2
) -> npt.NDArray[np.bool_]:
    """
    Builds a drinking mask from a 1 Hz .npy file.

    Args:
        mask_path:
            Path to a 1D boolean/int array at 1 Hz (per-second labels).
        offset_sec:
            Optional: The value (in seconds) to pad to the beginning of the mask
        fs: 
            Target sampling rate for the output mask (samples/sec).
        pad_sec: 
            Pad events by this many seconds on each side (at 1 Hz before upsampling).

    Returns:
        A 1-D boolean array where drinking events and padding are False.
    """
    mask_sec = np.asarray(np.load(Path(mask_path)), dtype=bool)  # per-second mask
    
    # Dilate events by pad_sec on each side at 1 Hz
    pad = int(pad_sec)
    # Convolution-based dilation at 1 Hz
    k = np.ones(2 * pad + 1, dtype=int)
    dil = np.convolve(mask_sec.astype(int), k, mode='same') > 0
    mask_sec = dil

    # --- upsample to sample rate ---
    mask_samples = np.repeat(mask_sec, fs)


    # --- apply offset as a right shift (insert False at start, drop tail) ---
    if (offset_sec) and (offset_sec > 0):
        shift = int(round(offset_sec * fs))
        mask_samples = np.pad(mask_samples, (shift, 0), constant_values=False)[:-shift]
    
    return ~mask_samples.astype(bool)

#TODO: Organize this better --> best way to get offset from files?
def get_offset(mask_path, offset_path):
    
    animal = Path(mask_path).stem.split('_')[0]
    offsets = pd.read_csv(offset_path)
    #Get the offset between the mask from video and the eeg recording
    return offsets[offsets['Animal']==animal]['Offset'].values[0]


def swd(path: Union[str, Path], 
        n_samples: int, 
        fs: int = 250, 
        label: str ='DEL_ts', 
        pad_sec: int=0):
    
    """
    Builds a mask from a .mat file containing time stamps of SWDs.

    Args:
        path:
            Path to a .mat file containing the SWDs
        n_samples:
            Number of samples the mask must be (number of samples in .edf file)
        fs: 
            Target sampling rate for the output mask (samples/sec).
        label:
            Label the timestamp matric is save under in .mat file. Defaults to 'DEL_ts'. If 
            label is not in the file, the first object in file will be taken as key. 
        pad_sec: 
            Pad swd events by this many seconds on each side (at 1 Hz before upsampling).

    Returns:
        A 1-D boolean array where drinking events and padding are False.
    """

    path = Path(path)

    # Explicitly manage the file resource
    with path.open("rb") as f:
        data = loadmat(f, squeeze_me=True, struct_as_record=False)


    # pick key
    keys = [k for k in data.keys() if not k.startswith('__')]
    key = label if label in keys else keys[0]

    swds = np.asarray(data[key])

    # --- handle completely empty arrays: no SWDs at all ---
    if swds.size == 0:
        return np.ones(n_samples, dtype=bool)

    # --- normalize shape to (N, 2) of [start_s, stop_s] ---
    if swds.ndim == 1:
        # If it's exactly 2 values, assume a single [start, stop]
        if swds.shape[0] == 2:
            swds = swds[np.newaxis, :]
        else:
            raise ValueError(
                f"Unexpected 1D swd array shape {swds.shape} in {path}; "
                "expected length 2 for [start, stop]."
            )
    elif swds.ndim == 2:
        if swds.shape[1] == 0:
            # (0, 0) or (0, ?) case: no intervals
            return np.ones(n_samples, dtype=bool)
        elif swds.shape[1] >= 2:
            swds = swds[:, 0:2]
        else:
            raise ValueError(
                f"2D swd array has shape {swds.shape} but needs at least 2 columns "
                "for [start, stop]."
            )
    else:
        raise ValueError(
            f"swds has ndim={swds.ndim}, expected 1D or 2D in {path}"
        )

    # now swds is (N, 2) or (0, 2)
    if swds.shape[0] == 0:
        # no intervals -> all True
        return np.ones(n_samples, dtype=bool)
    
    if pad_sec > 0:
        swds = swds + [(-1*pad_sec), pad_sec]


    iv = _seconds_to_intervals(swds, fs, n_samples)
    iv = _normalize_intervals(iv, n_samples)
    swd_mask = _intervals_to_bool_false(iv, n_samples)

    return swd_mask

def hour_window_mask(
    recording_start: datetime,
    n_samples: int,
    fs: float,
    hour_windows: List[Tuple[float, float]],
    selected_days: Optional[List[int]] = None,
) -> Tuple[npt.NDArray[np.bool_], List[Tuple[datetime, datetime]]]:
    """Return (bool_mask, used_windows) for samples within any of the given hour windows.

    hour_windows is a list of (hour_start, hour_end) pairs in decimal hours (e.g. 10.0, 12.0).
    Windows must not overlap. When hour_end < hour_start the window wraps midnight
    (e.g. (20.0, 6.0) = dark phase).

    used_windows is a flat list of (actual_start, actual_end) datetime pairs across all
    windows and calendar days, sorted by start time. Partial windows appear naturally:
    their start or end will differ from the requested hours when clipped by the recording
    boundaries.

    Args:
        recording_start: Datetime of the first sample.
        n_samples:       Total number of samples in the recording.
        fs:              Sampling rate in Hz.
        hour_windows:    List of (hour_start, hour_end) pairs.
        selected_days:   0-based calendar-day indices to include; None = all days.

    Returns:
        mask:         1-D boolean array where samples inside any window are True.
        used_windows: List of (actual_start, actual_end) datetimes, sorted by start.
    """
    recording_end = recording_start + timedelta(seconds=n_samples / fs)
    midnight0 = recording_start.replace(hour=0, minute=0, second=0, microsecond=0)

    all_intervals_s: List[Tuple[float, float]] = []
    all_used_windows: List[Tuple[datetime, datetime]] = []

    for hour_start, hour_end in hour_windows:
        wraps = hour_end < hour_start
        d = 0
        while True:
            req_start = midnight0 + timedelta(days=d,         seconds=hour_start * 3600)
            req_end   = midnight0 + timedelta(days=d + wraps, seconds=hour_end   * 3600)
            if req_start >= recording_end:
                break
            if req_end > recording_start:
                if selected_days is None or d in selected_days:
                    actual_start = max(req_start, recording_start)
                    actual_end   = min(req_end,   recording_end)
                    if actual_start < actual_end:
                        all_used_windows.append((actual_start, actual_end))
                        all_intervals_s.append((
                            (actual_start - recording_start).total_seconds(),
                            (actual_end   - recording_start).total_seconds(),
                        ))
            d += 1

    if not all_intervals_s:
        return np.zeros(n_samples, dtype=bool), []

    all_used_windows.sort(key=lambda w: w[0])
    iv = _seconds_to_intervals(np.array(all_intervals_s), fs, n_samples)
    mask = np.zeros(n_samples, dtype=bool)
    for s, e in iv:
        mask[s:e] = True
    return mask, all_used_windows


def time_of_day_mask(
    start_datetime: datetime,
    n_samples: int,
    fs: float,
    tod_start: dtime,
    tod_end: dtime,
    selected_days: Optional[List[int]] = None,
) -> np.ndarray:
    """Return a boolean mask (True = keep) for samples within the given
    time-of-day window.  Wraps midnight when tod_end < tod_start.

    Args:
        start_datetime:
            Datetime of the first sample in the recording.
        n_samples:
            Total number of samples in the recording.
        fs:
            Sampling rate in Hz.
        tod_start:
            Start of the keep window (clock time).
        tod_end:
            End of the keep window (clock time).  If tod_end < tod_start,
            the window wraps midnight (e.g. 20:00–08:00 = dark phase).
        selected_days:
            0-based day indices (relative to the recording start date) to
            include.  None = all days.

    Returns:
        A 1-D boolean array where samples inside the window are True.
    """
    duration_s = n_samples / fs
    wraps = tod_end < tod_start
    intervals = []
    d = 0
    while True:
        day_date = start_datetime.date() + timedelta(days=d)
        earliest = datetime.combine(day_date, tod_start)
        if (earliest - start_datetime).total_seconds() > duration_s:
            break

        if selected_days is None or d in selected_days:
            if not wraps:
                win_start = datetime.combine(day_date, tod_start)
                win_end = datetime.combine(day_date, tod_end)
            else:
                win_start = datetime.combine(day_date, tod_start)
                win_end = datetime.combine(day_date + timedelta(days=1), tod_end)
            intervals.append((
                (win_start - start_datetime).total_seconds(),
                (win_end - start_datetime).total_seconds(),
            ))
        d += 1

    if not intervals:
        return np.zeros(n_samples, dtype=bool)

    iv = _seconds_to_intervals(np.array(intervals), fs, n_samples)
    if iv.size == 0:
        return np.zeros(n_samples, dtype=bool)

    mask = np.zeros(n_samples, dtype=bool)
    for s, e in iv:
        mask[s:e] = True
    return mask


def _normalize_intervals(iv: np.ndarray, n: int) -> np.ndarray:
    """Clip to [0,n], drop empty, sort, and merge touching/overlapping intervals."""
    iv = np.clip(iv, 0, n)
    iv = iv[iv[:, 0] < iv[:, 1]]  # Remove invalid intervals
    if iv.size == 0: return iv

    iv = iv[np.argsort(iv[:, 0])]  # Sort intervals by start time
    merged = [iv[0]]
    
    for s, e in iv[1:]:
        ms, me = merged[-1]
        if s <= me:  # Overlap or touch -> merge
            merged[-1][1] = max(me, e)
        else:
            merged.append([s, e])

    return np.asarray(merged)

def _seconds_to_intervals(spans_s: Iterable[Tuple[float, float]], fs: float, n: int) -> np.ndarray:
    """Convert (start, stop) seconds to clipped, merged sample intervals."""
    arr = np.asarray(spans_s)
    if arr.size == 0: return np.empty((0, 2))
    
    # Convert seconds to sample indices
    a = np.floor(arr[:, 0] * fs).astype(int)
    b = np.ceil(arr[:, 1] * fs).astype(int)
    
    return _normalize_intervals(np.column_stack([a, b]), n)

def _intervals_to_bool_false(intervals: np.ndarray, n: int) -> np.ndarray:
    """Create a boolean mask marking the intervals as False."""
    mask = np.ones(n, dtype=bool)
    if not intervals.size: return mask
    
    diff = np.zeros(n + 1, dtype=int)
    np.add.at(diff, np.clip(intervals[:, 0], 0, n), 1)
    np.add.at(diff, np.clip(intervals[:, 1], 0, n), -1)
    
    covered = np.cumsum(diff[:-1]) > 0
    mask[covered] = False
    return mask
