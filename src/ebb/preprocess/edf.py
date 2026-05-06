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
from ebb.io.sleepyrat import SleepyRatAPI


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
    # TODO: Do I want exist_ok to be True? Best procedure
    savedir = Path(savedir)
    savedir.mkdir(parents=True, exist_ok=True)

    fp = Path(path)
    reader = edf.Reader(fp)

    # Trim data with floor chosen from trim_to
    trim_samples = np.array(trim_to) * 3600 * fs
    idx = np.searchsorted(trim_samples, reader.shape[axis], side="right") - 1
    if idx < 0:
        hrs = reader.shape[axis] / (3600 * fs)
        msg = f"{path.stem} is {hrs} hrs, a value below all trim_to {trim_to}"
        raise ValueError(msg)
    stop = trim_samples[idx]
    # ensure stop is integer multiple of samples per record / downsample
    stop = int(np.ceil(stop / fs) * fs)

    pro = producer(reader, chunksize, axis, start=0, stop=stop)
    result = resampling.downsample(pro, downsample, fs, chunksize, axis)
    processed = result.to_array()  # until openseize supports streaming writes

    header = copy.deepcopy(reader.header)
    m = downsample
    fs_out = int(fs / m)
    # Normalize to 1-second records regardless of input record_duration.
    # Some EDFs use non-standard record_duration (e.g. 10 s) which causes a
    # reshape mismatch when samples_per_record is divided by m but num_records
    # is still computed from fs_out assuming 1-second records.
    header["record_duration"] = 1
    header["samples_per_record"] = [fs_out] * len(header.samples_per_record)
    header["num_records"] = int(processed.shape[axis] / fs_out)
    header["reserved_0"] = ""
    header["digital_min"] = [int(x) for x in header["digital_min"]]
    header["digital_max"] = [int(x) for x in header["digital_max"]]

    out = savedir / f"{fp.stem}_PREPROCESSED{fp.suffix}"
    with edf.Writer(out) as writer:
        writer.write(header, processed, reader.channels, verbose)

    reader.close()
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
    savedir.mkdir(
        parents=True, exist_ok=True
    )  # TODO: Do I want exist_ok to be True? Best procedure

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
    # TODO: Do I want exist_ok to be True? Best procedure
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


# TODO: Make more flexible - check for project/folder existence, how to manage if not all EDFs process in time limit, etc.
# Integrate with the spindle batch process for ease?
def process_sleepyrat(
    edf_dir: Path,
    project: str,
    folder: str,
    *,
    threshold: float = 0.5,
    outdir: Path | None = None,
    username: str = "REDACTED_1",
    password: str = "REDACTED_2",
    base_url: str = "https://sleepyrat.ai/api",
) -> Path:
    """
    High-level helper for the GUI:

    - Logs into SleepyRat
    - Uploads a single EDF to project/folder
    - Waits for processing to finish
    - Downloads that EDF's labels as CSV
    - Saves CSV locally (default: next to the EDF)
    - Returns the local CSV path
    """
    if outdir is None:
        outdir = edf_dir.parent / f"{edf_dir.stem}_outputs"
    else:
        outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)

    api = SleepyRatAPI(username=username, password=password, base_url=base_url)

    # 1. Upload the EDF
    print(f"[SleepyRat] Uploading {edf_dir.name} to {project}/{folder}...")
    api.upload_dir(project, folder, edf_dir)

    # 2. Wait for processing
    print("[SleepyRat] Waiting for processing to finish...")
    ok = api.wait_for_processing(project, folder)
    if not ok:
        raise RuntimeError(f"Processing did not finish within wait limit for {project}/{folder}")

    api.download_labels_all(project, folder, outdir, threshold=threshold)
    print(f"[SleepyRat] Labels downloaded to {outdir}")
