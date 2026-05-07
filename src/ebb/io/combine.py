"""
Combine prematurely-stopped EDF files and corresponding SWD timestamp .mat files.

Library functions:
- locate: find EDFs shorter than expected duration
- pair: group related files by token pattern
- combine_edf: combine EDF chunks into a new *_COMBINED.edf
- combine_swd: combine SWD timestamp .mat files into *_COMBINED.mat

CLI:
    ebb-combine edf --dir ... --fs 5000
    ebb-combine swd --dir .../swd_ts/short
"""

from __future__ import annotations

import argparse
import copy
import re
import reprlib
from collections.abc import Sequence
from operator import attrgetter
from pathlib import Path
from re import Pattern

import numpy as np
from openseize.file_io import edf
from scipy.io import loadmat, savemat


# -------------------------
# Core helpers
# -------------------------
def locate(dirpath: str | Path, fs: float, expected_hours: float) -> list[Path]:
    """Return EDF paths whose duration (hours) is less than expected_hours."""
    dirpath = Path(dirpath)
    result: list[Path] = []
    for fp in dirpath.glob("*.edf"):
        with edf.Reader(fp) as reader:
            hours = reader.shape[-1] / (3600.0 * fs)
            if hours < expected_hours:
                result.append(reader.path)
    return result


def pair(paths: Sequence[Path], pattern: str | Pattern[str] = r"[^_]+") -> list[tuple[Path, ...]]:
    """Group files whose stems share the same token captured by `pattern`.

    The token is the regex match (the literal `m.group()`); two files belong
    in the same group iff `pattern` extracts the same token from each stem.
    Substring containment is intentionally avoided so that `"CW1"` does not
    silently group with `"CW10..."`.

    Raises:
        ValueError if `pattern` fails to match any path's stem, or if a
        path's token has no companion in the input.
    """
    pat = re.compile(pattern) if isinstance(pattern, str) else pattern

    result: list[tuple[Path, ...]] = []
    cpaths = list(paths)

    while cpaths:
        path = cpaths.pop(0)
        m = pat.search(path.stem)
        if not m:
            raise ValueError(f"Pattern {pat.pattern!r} did not match: {path.stem}")
        token = m.group()

        matches = [
            other
            for other in cpaths
            if (m2 := pat.search(other.stem)) and m2.group() == token
        ]
        if not matches:
            raise ValueError(f"No match found for token {token!r} from {path.name}")

        for mm in matches:
            cpaths.remove(mm)
        result.append((path, *matches))

    return result


def move_files(new_dir: Path, paths: Sequence[Path], *, exist_ok: bool = False) -> None:
    """Move each file in paths into new_dir."""
    new_dir.mkdir(parents=True, exist_ok=exist_ok)
    for path in paths:
        path.rename(new_dir / path.name)


# -------------------------
# EDF combine
# -------------------------
def combine_edf(
    dirpath: str | Path,
    *,
    fs: float,
    amount_hours: float = 24,
    nominal_hours: float = 72,
    pattern: str | Pattern[str] = r"[^_]+",
    verbose: bool = True,
    move_short_files: bool = False,
    short_dirname: str = "short_files",
    overwrite: bool = False,
) -> list[Path]:
    """Combine EDF files whose duration is less than nominal_hours.

    Returns a list of created combined EDF paths.
    """
    dirpath = Path(dirpath)

    short_files = locate(dirpath, fs, nominal_hours)
    if not short_files:
        if verbose:
            print("No short EDF files found.")
        return []

    path_tuples = pair(short_files, pattern)

    created: list[Path] = []
    samples = int(amount_hours * fs * 3600)

    for tup in path_tuples:
        readers = [edf.Reader(fp) for fp in tup]
        readers = sorted(readers, key=attrgetter("header.start_date"))

        if verbose:
            print("Combining EDFs:\n" + reprlib.repr([r.path.stem for r in readers]))

        # Read up to `samples` from each reader; concatenate. Reading
        # `samples` past a short reader's end would NaN-pad silently
        # (openseize Reader.read pads with `padvalue=nan` by default), so
        # we cap each read at the reader's actual length.
        chunks = []
        for r in readers:
            n = min(samples, r.shape[-1])
            chunks.append(r.read(0, n))
            r.close()
        arr = np.concatenate(chunks, axis=-1)

        header = copy.deepcopy(readers[0].header)
        spr = header.samples_per_record[0]
        if arr.shape[-1] % spr != 0:
            raise ValueError(
                f"Combined sample count ({arr.shape[-1]}) is not a multiple of "
                f"samples_per_record ({spr}); cannot write a valid EDF."
            )
        header["num_records"] = arr.shape[-1] // spr

        out_fp = readers[0].path.with_stem(readers[0].path.stem + "_COMBINED")
        if out_fp.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing file: {out_fp}")

        with edf.Writer(out_fp) as writer:
            writer.write(header, arr, readers[0].channels, verbose=verbose)

        created.append(out_fp)

    if move_short_files:
        move_files(dirpath / short_dirname, short_files, exist_ok=True)

    return created


# -------------------------
# SWD combine
# -------------------------
def combine_swd(
    swd_dir: str | Path,
    *,
    amount_hours: float = 24,
    pattern: str | Pattern[str] = r"final_ts_([^_]+)",
    verbose: bool = True,
    label_preference: str = "final_ts",
    overwrite: bool = False,
) -> list[Path]:
    """Combine SWD timestamp .mat files corresponding to short EDFs.

    Returns a list of created combined MAT paths.
    """
    swd_dir = Path(swd_dir)
    short_files = list(swd_dir.glob("*.mat"))
    if not short_files:
        if verbose:
            print("No .mat files found.")
        return []

    path_tuples = pair(short_files, pattern)
    amount_sec = float(amount_hours) * 3600.0

    def extract_pnum(path: Path) -> int:
        m = re.search(r"_P(\d+)", path.name)
        if not m:
            # If this is too strict for your naming, we can soften it later
            raise ValueError(f"No _P### pattern found in: {path.name}")
        return int(m.group(1))

    created: list[Path] = []

    for tup in path_tuples:
        swd_paths = sorted(tup, key=extract_pnum)

        if verbose:
            print(f"Combining SWD files: {[p.stem for p in swd_paths]}")

        # Resolve label and capture the first file's auxiliary keys before
        # the per-file loop (label is constant across files in a group).
        first_data = loadmat(swd_paths[0], squeeze_me=True, struct_as_record=False)
        first_keys = [k for k in first_data if not k.startswith("__")]
        label = label_preference if label_preference in first_keys else first_keys[0]
        first_data_dict = {k: v for k, v in first_data.items() if not k.startswith("__")}

        combined_swds = []

        for idx, path in enumerate(swd_paths):
            data = loadmat(path, squeeze_me=True, struct_as_record=False)
            keys = [k for k in data if not k.startswith("__")]
            key = label if label in keys else keys[0]

            swds = np.asarray(data[key])

            # normalize to (N, 2)
            if swds.size == 0:
                continue
            if swds.ndim == 1 and swds.shape[0] == 2:
                swds = swds[np.newaxis, :]
            elif swds.ndim == 2 and swds.shape[1] >= 2:
                swds = swds[:, 0:2]
            else:
                raise ValueError(f"Unexpected SWD array shape {swds.shape} in {path}")

            # Keep events that begin within this chunk; clamp any straddling
            # event's stop to the chunk boundary so it doesn't spill into the
            # next file's timespan after shifting.
            swds = swds[swds[:, 0] < amount_sec].copy()
            swds[:, 1] = np.minimum(swds[:, 1], amount_sec)

            swds += idx * amount_sec

            if swds.size:
                combined_swds.append(swds)

        if not combined_swds:
            if verbose:
                print(f"No SWDs found in first {amount_hours}h for {swd_paths}")
            continue

        out_swds = np.vstack(combined_swds)
        out_swds = out_swds[np.argsort(out_swds[:, 0])]

        out_path = swd_paths[0].with_stem(swd_paths[0].stem + "_COMBINED")
        if out_path.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing file: {out_path}")

        out_data = dict(first_data_dict or {})
        out_data[label] = out_swds

        if verbose:
            print(f"Writing combined SWD file to: {out_path}")

        savemat(out_path, out_data)
        created.append(out_path)

    return created


# -------------------------
# CLI
# -------------------------
# Invoke as: python -m ebb.io.combine {edf|swd} ...
# Not registered as a console_script in pyproject.toml.
def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ebb-combine")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_edf = sub.add_parser("edf", help="Combine short EDF restarts")
    p_edf.add_argument("--dir", type=Path, required=True, help="Directory containing EDF files")
    p_edf.add_argument("--fs", type=float, required=True, help="Sampling rate (Hz)")
    p_edf.add_argument("--amount-hours", type=float, default=24)
    p_edf.add_argument("--nominal-hours", type=float, default=72)
    p_edf.add_argument("--pattern", type=str, default=r"[^_]+")
    p_edf.add_argument("--move-short-files", action="store_true")
    p_edf.add_argument("--short-dirname", type=str, default="short_files")
    p_edf.add_argument("--overwrite", action="store_true")
    p_edf.add_argument("--quiet", action="store_true")

    p_swd = sub.add_parser("swd", help="Combine SWD timestamp .mat files")
    p_swd.add_argument("--dir", type=Path, required=True, help="Directory containing .mat files")
    p_swd.add_argument("--amount-hours", type=float, default=24)
    p_swd.add_argument("--pattern", type=str, default=r"final_ts_([^_]+)")
    p_swd.add_argument("--label-preference", type=str, default="final_ts")
    p_swd.add_argument("--overwrite", action="store_true")
    p_swd.add_argument("--quiet", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "edf":
        combine_edf(
            args.dir,
            fs=args.fs,
            amount_hours=args.amount_hours,
            nominal_hours=args.nominal_hours,
            pattern=args.pattern,
            verbose=not args.quiet,
            move_short_files=args.move_short_files,
            short_dirname=args.short_dirname,
            overwrite=args.overwrite,
        )
        return 0

    if args.cmd == "swd":
        combine_swd(
            args.dir,
            amount_hours=args.amount_hours,
            pattern=args.pattern,
            verbose=not args.quiet,
            label_preference=args.label_preference,
            overwrite=args.overwrite,
        )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
