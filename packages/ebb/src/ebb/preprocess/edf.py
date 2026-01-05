from __future__ import annotations

import copy
import time
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Callable, Iterable, Sequence, Union

import numpy as np
from openseize.file_io import edf
from openseize.resampling import resampling

from ebb.core.concurrency import set_cores 
from ebb.io.utils import between_pro         


def compute_trim_stop_samples(
    n_samples: int,
    fs: float,
    trim_to_hours: Sequence[float],
) -> int:
    """Pick the largest trim_to hour value that is <= the recording length."""
    trim_samples = np.asarray(trim_to_hours, dtype=float) * 3600.0 * fs
    idx = np.searchsorted(trim_samples, n_samples, side="right") - 1
    if idx < 0:
        hours = n_samples / (3600.0 * fs)
        raise ValueError(f"Recording is {hours:.2f} hrs, below all trim_to={list(trim_to_hours)}")
    stop = int(trim_samples[idx])
    return stop


def standard(
    path: Union[str, Path],
    *,
    savedir: Union[str, Path],
    fs: float,
    downsample: int,
    trim_to_hours: Sequence[float] = (48, 72),
    chunksize: int = int(30e5),
    axis: int = -1,
    verbose: bool = True,
) -> Path:
    """Downsample and trim an EDF; write *_PREPROCESSED.edf and return its path."""
    fp = Path(path)
    savedir = Path(savedir)

    #TODO: Do I want exist_ok to be True? Best procedure
    savedir.mkdir(parents=True, exist_ok=True)

    reader = edf.Reader(fp)

    stop = compute_trim_stop_samples(reader.shape[axis], fs, trim_to_hours)
    stop = int(np.ceil(stop / fs) * fs)  # keep multiple-of-1sec (as you had)

    pro = between_pro(reader, 0, stop, chunksize, axis)
    result = resampling.downsample(pro, downsample, fs, chunksize, axis)
    processed = result.to_array()  # until openseize supports streaming writes

    header = copy.deepcopy(reader.header)
    m = downsample
    header["samples_per_record"] = [x // m for x in header.samples_per_record]
    header["num_records"] = int(processed.shape[axis] / (fs / m))
    header["reserved_0"] = ""
    header["digital_min"] = [int(x) for x in header["digital_min"]]
    header["digital_max"] = [int(x) for x in header["digital_max"]]

    out = savedir / f"{fp.stem}_PREPROCESSED{fp.suffix}"
    with edf.Writer(out) as writer:
        writer.write(header, processed, reader.channels, verbose)

    reader.close()
    return out


def spindle(
    path: Union[str, Path],
    *,
    savedir: Union[str, Path],
    channels: Sequence[int],
    verbose: bool = True,
) -> Path:
    """Write a reduced-channel EDF for SPINDLE upload; return output path."""
    fp = Path(path)
    savedir = Path(savedir)
    savedir.mkdir(parents=True, exist_ok=True) #TODO: Do I want exist_ok to be True? Best procedure

    reader = edf.Reader(fp)
    data = reader.read(0)

    header = copy.deepcopy(reader.header)
    header["digital_min"] = [int(x) for x in header["digital_min"]]
    header["digital_max"] = [int(x) for x in header["digital_max"]]

    out = savedir / f"{fp.stem}_SPINDLE{fp.suffix}"
    with edf.Writer(out) as writer:
        writer.write(header, data, list(channels), verbose)

    reader.close()
    return out


def batch(
    preprocessor: Callable[..., Path],
    dirpath: Union[str, Path],
    *,
    target: Union[str, Path, None] = None,
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
    #TODO: Do I want exist_ok to be True? Best procedure
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
        with Pool(workers) as pool:
            outs = pool.map(func, paths)
    else:
        outs = [func(p) for p in paths]

    elapsed = time.perf_counter() - t0
    if verbose:
        print(f"Saved {len(paths)} files to {target} in {elapsed:.2f}s")

    return outs
