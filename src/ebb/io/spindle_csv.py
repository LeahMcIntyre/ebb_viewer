"""Column-name resolution for SPINDLE-scored CSVs.

SleepyRat's output columns changed between versions. The old format stores
the clean per-epoch state (`w`/`n`/`r`) under `rawstate` and the artifact-
coded value under `state`; the new format has only `state`, holding the
same clean values `rawstate` used to. Noise probability moved from
`noise_probs` (old) to `noise_prob` (new). ebb needs to keep reading both,
since old-format files already exist on disk alongside new ones.
"""

import csv
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

# Order matters: `rawstate` must win when both are present (old format),
# since old `state` can hold artifact codes (`1`/`2`/`3`) instead of a
# clean state value.
STATE_COLUMNS = ("rawstate", "state")
NOISE_COLUMNS = ("noise_probs", "noise_prob")


def resolve_column(header: Sequence[str], candidates: Sequence[str]) -> str:
    """Return the first of `candidates` present in `header`.

    Raises:
        ValueError: if none of `candidates` are present in `header`.
    """
    for name in candidates:
        if name in header:
            return name
    raise ValueError(f"None of {list(candidates)} found in CSV header {list(header)}")


RECLASS_COLUMN = "reclass_state"
# The resolved per-epoch state downstream steps read: reclass_state, overridden by
# swd_reclassification where that is non-blank. Not part of STATE_COLUMNS, which is
# the *input* to reclassification (reading final_state there would break re-runs).
FINAL_COLUMN = "final_state"
ORIGINAL_DIRNAME = "_original"


def has_column(csv_path: str | Path, name: str) -> bool:
    """True if the CSV header contains ``name``."""
    with open(csv_path, newline="") as f:
        header = next(csv.reader(f), [])
    return name in header


def write_columns(csv_path: str | Path, columns: Mapping[str, Sequence[str]]) -> None:
    """Add (or replace) columns in a CSV, one value per data row.

    The first time a file is rewritten, the untouched original is copied to
    ``<dir>/_original/`` (never overwritten, so re-runs keep the SleepyRat file).
    Blank rows are dropped. Written atomically via a ``.tmp`` rename.
    """
    path = Path(csv_path)
    with open(path, newline="") as f:
        rows = [r for r in csv.reader(f) if r]
    if not rows:
        raise ValueError(f"empty CSV: {path.name}")
    header, data = rows[0], rows[1:]
    for name, values in columns.items():
        if len(data) != len(values):
            raise ValueError(f"{path.name}: {len(data)} rows but {len(values)} values for {name!r}")

    backup = path.parent / ORIGINAL_DIRNAME / path.name
    if not backup.exists():
        backup.parent.mkdir(exist_ok=True)
        shutil.copy2(path, backup)

    for name, values in columns.items():
        if name in header:
            idx = header.index(name)
            for row, v in zip(data, values, strict=True):
                row[idx] = str(v)
        else:
            header.append(name)
            for row, v in zip(data, values, strict=True):
                row.append(str(v))

    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)
    tmp.replace(path)
