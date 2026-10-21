"""Export consolidated sleep metrics for a project's chosen-combo CSVs.

Given a directory of SPINDLE CSVs (one per animal, already narrowed to each
animal's accepted channel combo) plus the preprocessed EDFs, write three
analysis-ready tables as tidy CSVs and as sheets in one workbook:

- ``sleep_bins``     — rotate-to-6AM per-bin metrics, one row per
                       (animal, bin, state); multi-day recordings keep a
                       distinct monotonic ``bin_start_hr`` per day.
- ``sleep_bins_avg`` — the same metrics averaged across days, folded to
                       hour-of-day, one row per (animal, hour_of_day, state).
- ``sleep_whole_file`` — whole-recording metrics standardized by recording
                       length, one row per (animal, state).

With ``excluded`` given, animals excluded in Sleep QC stay in all three tables and are marked
(``excluded`` / ``exclusion_reason`` columns, plus ``excluded_animals.csv``).

Group assignment is intentionally left out — tables are keyed by animal ID
so the caller can join their own grouping downstream.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ebb.io.exclusions import annotate_table, write_excluded_animals
from ebb.process.sleep_compute import (
    compute_sleep_bins_df_offset,
    compute_whole_file_metrics,
)

# Order metric-identifier columns first in every written table.
_BIN_COLUMNS = [
    "mouse_id",
    "state",
    "bin_idx",
    "bin_start_hr",
    "bin_start_sec",
    "frac_time",
    "n_bouts",
    "mean_bout_sec",
]

_METRIC_COLS = ["frac_time", "n_bouts", "mean_bout_sec"]


def _average_bins_across_days(bins: pd.DataFrame) -> pd.DataFrame:
    """Fold the rotate-to-6AM bins to hour-of-day and average across days.

    Each rotated bin's ``bin_start_hr`` grows monotonically (6, 8, …, 30, …)
    so day 2's 6AM bin sits at 30. Taking ``% 24`` collapses matching clock
    hours across days; the mean over that group is the per-hour average.
    """
    if bins.empty:
        return pd.DataFrame(
            columns=["mouse_id", "state", "hour_of_day", *_METRIC_COLS, "n_days"]
        )
    df = bins.copy()
    df["hour_of_day"] = (df["bin_start_hr"] % 24).astype(int)
    grouped = df.groupby(["mouse_id", "state", "hour_of_day"], as_index=False)
    avg = grouped[_METRIC_COLS].mean()
    avg["n_days"] = grouped.size()["size"]
    return avg.sort_values(["mouse_id", "state", "hour_of_day"], ignore_index=True)


def export_sleep(
    state_dir: str | Path,
    edf_dir: str | Path,
    out_dir: str | Path,
    *,
    begin_hr: int = 6,
    tz: ZoneInfo | None = None,
    excluded: dict[str, str] | None = None,
) -> dict[str, Path]:
    """Compute and write the three sleep tables as CSVs plus one workbook.

    Args:
        state_dir: Directory of the chosen-combo SPINDLE CSVs.
        edf_dir: Directory of preprocessed EDFs (for recording start times,
            used by the rotate-to-6AM binning).
        out_dir: Destination directory; created if absent.
        begin_hr: Clock hour bin 0 rotates to (default 6 AM).
        tz: Optional recording timezone so the rotation honors DST.
        excluded: Animal ID -> Sleep QC exclusion reason. Excluded animals stay in every
            table, which gets ``excluded`` / ``exclusion_reason`` columns, and an
            ``excluded_animals.csv`` is written to ``out_dir``. ``None`` adds nothing.

    Returns:
        Mapping of table name → written CSV path, plus ``"workbook"`` → xlsx
        path.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bins = compute_sleep_bins_df_offset(
        state_dir, edf_dir, begin_hr=begin_hr, tz=tz
    )
    if bins.empty:
        # An all-skipped offset compute returns a column-less frame; give it
        # headers so the written CSV is still a valid (empty) table.
        bins = pd.DataFrame(columns=_BIN_COLUMNS)
    else:
        bins = bins[_BIN_COLUMNS].sort_values(
            ["mouse_id", "state", "bin_idx"], ignore_index=True
        )
    bins_avg = _average_bins_across_days(bins)
    whole = compute_whole_file_metrics(state_dir)

    tables = {
        "sleep_bins": bins,
        "sleep_bins_avg": bins_avg,
        "sleep_whole_file": whole,
    }

    if excluded is not None:
        tables = {name: annotate_table(df, excluded) for name, df in tables.items()}
        write_excluded_animals(out_dir, excluded)

    written: dict[str, Path] = {}
    for name, df in tables.items():
        csv_path = out_dir / f"{name}.csv"
        df.to_csv(csv_path, index=False)
        written[name] = csv_path

    workbook = out_dir / "sleep_export.xlsx"
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        for name, df in tables.items():
            df.to_excel(writer, sheet_name=name, index=False)
    written["workbook"] = workbook

    return written
