"""Per-EDF preprocessing primitives plus a multiprocessing batch driver.

Two single-file ops:
- `standard`: trim the recording to a clean hour boundary (chosen from
  `trim_to`) and downsample, writing `<stem>_PREPROCESSED.edf`.
- `spindle`: copy a channel subset for SPINDLE upload, writing
  `<stem>_SPINDLE.edf`.

Plus `batch`, a generic driver that runs either single-file op across an
input directory using a process pool.

Output directories use `exist_ok=True` so re-running with the same target
dir just (re-)writes the contained files.
"""

from __future__ import annotations

import copy
import multiprocessing
import time
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

import numpy as np
from openseize.core.producer import producer
from openseize.file_io import edf
from openseize.resampling import resampling

from ebb.core.concurrency import set_cores


def compute_trim_stop_samples(
    n_samples: int,
    fs: float,
    trim_to_hours: Sequence[float],
) -> int:
    """Pick the largest trim_to hour value that is <= the recording length.

    Returns:
        Stop sample index, rounded up to a whole-second boundary.

    Raises:
        ValueError if the recording is shorter than every value in
        `trim_to_hours`.
    """
    trim_samples = np.asarray(trim_to_hours, dtype=float) * 3600.0 * fs
    idx = np.searchsorted(trim_samples, n_samples, side="right") - 1
    if idx < 0:
        hours = n_samples / (3600.0 * fs)
        raise ValueError(f"Recording is {hours:.2f} hrs, below all trim_to={list(trim_to_hours)}")
    # Round up to a whole-second boundary so downstream record-duration
    # arithmetic stays aligned.
    return int(np.ceil(trim_samples[idx] / fs) * fs)


def standard(
    path: str | Path,
    *,
    savedir: str | Path,
    fs: float,
    downsample: int,
    trim_to: Sequence[float] = (48, 72),
    chunksize: int = int(30e5),
    axis: int = -1,
    verbose: bool = True,
) -> Path:
    """Downsample and trim an EDF; write *_PREPROCESSED.edf and return its path."""
    savedir = Path(savedir)
    savedir.mkdir(parents=True, exist_ok=True)

    fp = Path(path)
    with edf.Reader(fp) as reader:
        stop = compute_trim_stop_samples(reader.shape[axis], fs, trim_to)

        pro = producer(reader, chunksize, axis, start=0, stop=stop)
        result = resampling.downsample(pro, downsample, fs, chunksize, axis)
        processed = result.to_array()  # until openseize supports streaming writes

        header = copy.deepcopy(reader.header)
        channels = reader.channels

    fs_out = int(fs / downsample)
    # Normalize to 1-second records regardless of input record_duration.
    # Some EDFs use non-standard record_duration (e.g. 10 s) which causes a
    # reshape mismatch when samples_per_record is divided by downsample but
    # num_records is still computed from fs_out assuming 1-second records.
    header["record_duration"] = 1
    header["samples_per_record"] = [fs_out] * len(header.samples_per_record)
    header["num_records"] = int(processed.shape[axis] / fs_out)
    header["reserved_0"] = ""
    header["digital_min"] = [int(x) for x in header["digital_min"]]
    header["digital_max"] = [int(x) for x in header["digital_max"]]

    out = savedir / f"{fp.stem}_PREPROCESSED{fp.suffix}"
    with edf.Writer(out) as writer:
        writer.write(header, processed, channels, verbose)
    return out


def spindle(
    path: str | Path,
    *,
    savedir: str | Path,
    channels: Sequence[int],
    verbose: bool = True,
) -> Path:
    """Write a reduced-channel EDF for SPINDLE upload; return output path."""
    fp = Path(path)
    savedir = Path(savedir)
    savedir.mkdir(parents=True, exist_ok=True)

    with edf.Reader(fp) as reader:
        data = reader.read(0)
        header = copy.deepcopy(reader.header)

    header["digital_min"] = [int(x) for x in header["digital_min"]]
    header["digital_max"] = [int(x) for x in header["digital_max"]]

    out = savedir / f"{fp.stem}_SPINDLE{fp.suffix}"
    with edf.Writer(out) as writer:
        writer.write(header, data, list(channels), verbose)
    return out


def batch(
    preprocessor: Callable[..., Path],
    dirpath: str | Path,
    *,
    target: str | Path | None = None,
    ncores: int | None = None,
    verbose: bool = True,
    use_multiprocessing: bool = True,
    **kwargs,
) -> list[Path]:
    """Run a preprocessor across all EDFs in a directory; return output paths."""
    dirpath = Path(dirpath)
    if target is None:
        target = dirpath / preprocessor.__name__
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)

    paths = list(dirpath.glob("*.edf"))
    if not paths:
        if verbose:
            print(f"No EDF files found in {dirpath}")
        return []

    workers = set_cores(ncores, len(paths))
    if verbose:
        print(f"Running '{preprocessor.__name__}' on {len(paths)} files using {workers} cores.")

    t0 = time.perf_counter()
    kwargs.pop("savedir", None)

    func = partial(preprocessor, savedir=target, **kwargs)

    if use_multiprocessing and workers > 1:
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(workers) as pool:
            outs = pool.map(func, paths)
    else:
        outs = [func(p) for p in paths]

    elapsed = time.perf_counter() - t0
    if verbose:
        print(f"Saved {len(paths)} files to {target} in {elapsed:.2f}s")

    return outs
