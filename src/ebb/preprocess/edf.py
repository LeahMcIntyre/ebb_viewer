"""Per-EDF preprocessing primitives plus a multiprocessing batch driver.

Two single-file ops:
- `standard`: trim the recording to a clean hour boundary (chosen from
  `trim_to`) and downsample, writing `<stem>_PREPROCESSED.edf`.
- `spindle`: copy a channel subset for SPINDLE upload, writing
  `<stem>_SPINDLE.edf`.

Plus `batch`, a generic driver that runs either single-file op across an
input directory using a process pool, and `process_sleepyrat`, a higher-
level helper that uploads, waits for processing, and downloads labels.

Output directories use `exist_ok=True` so re-running with the same target
dir just (re-)writes the contained files. The exception is
`process_sleepyrat`, which uses `exist_ok=False` deliberately — see its
docstring.
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
from ebb.io.sleepyrat import SleepyRatAPI


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


def process_sleepyrat(
    edf_dir: Path,
    project: str,
    folder: str,
    *,
    threshold: float = 0.5,
    outdir: Path | None = None,
    username: str | None = None,
    password: str | None = None,
    base_url: str | None = None,
) -> Path:
    """High-level upload-process-download helper for the GUI.

    Steps:
        1. Log into SleepyRat (uses `SleepyRatAPI` defaults if creds omitted).
        2. Upload all EDFs in `edf_dir` to `project/folder`.
        3. Wait for processing to finish (polled).
        4. Download labels CSV for every submission into `outdir`.

    Args:
        edf_dir: Directory of EDFs to upload.
        project, folder: Remote SleepyRat location.
        threshold: Score threshold passed through to `download_labels`.
        outdir: Local target for label CSVs. Defaults to a sibling
            `<edf_dir.stem>_outputs/` directory.
        username, password, base_url: Override SleepyRatAPI defaults if set.

    Note:
        Unlike `standard`/`spindle`/`batch`, this uses `exist_ok=False` on
        `outdir`. Re-running into an existing dir would mix new label CSVs
        with stale ones — failing fast forces the caller to choose a fresh
        path or delete the old one deliberately.
    """
    outdir = edf_dir.parent / f"{edf_dir.stem}_outputs" if outdir is None else Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)

    api_kwargs = {
        k: v
        for k, v in {"username": username, "password": password, "base_url": base_url}.items()
        if v is not None
    }
    api = SleepyRatAPI(**api_kwargs)

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
