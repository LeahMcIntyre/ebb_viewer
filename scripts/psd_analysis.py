"""PSD analysis: sealed PSD files of finished ebb-viewer projects -> group spectra, band power, Prism workbooks.

This is the script version of ``notebooks/psd_analysis.ipynb`` (same calculation, same output).

HOW TO RUN
    1. Make a copy of this file for each analysis. Keep ``psd_utils.py`` (it lives in the
       repository's ``notebooks/`` folder) next to your copy, or run the script from where it is.
    2. Edit the block marked "SETTINGS" below. Lines marked  <<< CHANGE THIS  must be edited;
       everything else has a sensible default.
    3. Run it:      python psd_analysis.py
       The script checks your settings first and stops with a plain message if one is wrong.

WHAT YOU GET, in OUT_DIR (default: ``<project>/psd_analysis/<run name>/``, next to the project's ``psd/`` folder)
    figures/   every plot as a PNG
    band_power.csv, band_power_normalized.csv   one row per animal x state x channel (x time), one column per band
    prism_*.xlsx   spectra and band power, one sheet per channel x state, ready to paste into Prism

HOW THE NUMBERS ARE MADE
    1. Each animal's PSD for each state and channel is read from ``psds_final.pkl``. Animals
       excluded in Sleep QC are left out unless INCLUDE_EXCLUDED is True.
    2. The 0.5-3.5 Hz bins are multiplied by correction factors for the recording hardware's
       low-frequency roll-off (the "inverse filter").
    3. Line-noise peaks are bridged by interpolation: 56-64 Hz (the 60 Hz peak and the gap left by
       the 60 Hz notch filter, which is on by default) and 118-122 Hz (the 120 Hz peak).
    4. A *normalized* spectrum is the interpolated spectrum divided by its own power between
       1 and 100 Hz, so it shows the shape of the spectrum independent of overall amplitude.
    5. *Band power* is the area under the spectrum in each band (trapezoid rule), for the
       interpolated and the normalized spectra.
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write the plots to files; never open a window
import matplotlib.pyplot as plt

# psd_utils.py sits next to this script when copied, or in ../notebooks in the repository.
_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "notebooks")]
import psd_utils  # noqa: E402

# =====================================================================================
# SETTINGS  -  EDIT THIS BLOCK. Everything below the next line of "=" is the calculation.
# =====================================================================================

# <<< CHANGE THIS: the sealed PSD file(s) to analyze, {label: path to psds_final.pkl}.
# One entry for one time point, or several (e.g. "pre" and "post") to compare time points.
RUNS = {
    "pre": Path("/path/to/your/project/psd/default/psds_final.pkl"),
    # "post": Path("/path/to/your/other/project/psd/default/psds_final.pkl"),
}

# <<< CHANGE THIS (or leave both empty for one group with everyone): the experimental groups.
# Either list the animals here ...
#     {"group name": [animal IDs]}
GROUPS = {
    # "WT":  ["Mice-1248", "Mice-1253"],
    # "MUT": ["Mice-1251", "Mice-1279"],
}
# ... or read them from a CSV file (this replaces GROUPS). The easiest layout is one row per
# animal, with two columns named "animal" and "group":
#     animal,group
#     Mice-1248,WT
#     Mice-1251,MUT
# One column per group also works: the group name on top, its animal IDs below it:
#     WT,MUT
#     Mice-1248,Mice-1251
#     Mice-1253,Mice-1279
GROUPS_CSV = None  # e.g. Path("/path/to/groups.csv")

# <<< CHECK THIS: the frequencies bridged by interpolation to remove line noise.
# LEAVE AS IS if the PSDs were computed with the 60 Hz notch filter (the default in ebb-viewer):
# 56-64 Hz covers the notch's 57-63 Hz gap. CHANGE to [[58, 62], [118, 122]] only if you turned
# the notch off. 118-122 Hz is for the 120 Hz peak, which the notch does not touch.
# (The script reads each run's psd_params.json and warns you if this does not match.)
INTERP_RANGES = [[56, 64], [118, 122]]

# ----- optional; the defaults are what the lab normally uses -----
# Where the results go. None -> <project>/psd_analysis/<run name>, in the project of the first file
# in RUNS, next to its "psd" folder: one folder per run, so analyses of different runs from the same
# project do not overwrite each other. Or Path("/path/to/results") (created if needed).
OUT_DIR = None
INCLUDE_EXCLUDED = False  # True keeps animals excluded in Sleep QC
APPLY_INVERSE_FILTER = True  # correct 0.5-3.5 Hz for the hardware roll-off
NORM_BAND = (1, 100)  # Hz; spectra are normalized to the power in this band
BANDS = {  # Hz; band power is computed for each of these
    "1-4": (1, 4),
    "4-8": (4, 8),
    "8-12": (8, 12),
    "12-30": (12, 30),
    "30-70": (30, 70),
    "70-100": (70, 100),
}
FREQ_RANGE = (0.5, 110)  # Hz shown on the spectrum plots
COLOR_MAP = None  # e.g. {"WT": "tab:green", "MUT": "tab:blue"}; None = automatic
SEX_MAP = None  # e.g. {"Mice-1248": "M", ...}; orders Prism columns males first

# =====================================================================================
# END OF SETTINGS
# =====================================================================================


def stop(*problems):
    """Print what is wrong with the settings and quit."""
    print("\n" + "=" * 78)
    print("CANNOT RUN YET. Fix the following in the SETTINGS block of this script:\n")
    for problem in problems:
        print(f"  * {problem}")
    print("=" * 78)
    sys.exit(1)


def check_settings():
    """Stop on placeholders and missing files; warn if INTERP_RANGES does not match the runs."""
    problems = []
    if not RUNS:
        problems.append("RUNS is empty. Add at least one {label: path to psds_final.pkl}.")
    for label, path in RUNS.items():
        path = Path(path)
        if "/path/to/" in str(path):
            problems.append(f'RUNS["{label}"] is still the placeholder path. Set it to your psds_final.pkl.')
        elif not path.is_file():
            problems.append(
                f'RUNS["{label}"] = {path} does not exist. '
                "Finalize the project in ebb-viewer first; the file is psd/<run>/psds_final.pkl."
            )
    if GROUPS and GROUPS_CSV:
        problems.append("Both GROUPS and GROUPS_CSV are set. Use one of them.")
    if GROUPS_CSV and not Path(GROUPS_CSV).is_file():
        problems.append(f"GROUPS_CSV = {GROUPS_CSV} does not exist.")
    if problems:
        stop(*problems)

    for label, path in RUNS.items():
        params_file = Path(path).parent / "psd_params.json"
        if not params_file.is_file():
            continue
        try:
            notch = json.loads(params_file.read_text()).get("apply_notch")
        except (json.JSONDecodeError, OSError):
            continue
        covers_notch = any(lo <= 57 and hi >= 63 for lo, hi in INTERP_RANGES)
        if notch is True and not covers_notch:
            print(
                f'WARNING: run "{label}" used the 60 Hz notch (57-63 Hz gap) but INTERP_RANGES '
                f"{INTERP_RANGES} does not cover 57-63 Hz. Use [[56, 64], [118, 122]]."
            )
        if notch is False and covers_notch:
            print(
                f'WARNING: run "{label}" was computed WITHOUT the notch but INTERP_RANGES '
                f"{INTERP_RANGES} is the wide notch range. Use [[58, 62], [118, 122]]."
            )


def main():
    check_settings()
    out_dir = Path(OUT_DIR) if OUT_DIR else psd_utils.default_output_dir(*RUNS.values())
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(exist_ok=True)
    print("=" * 78)
    print("RESULTS WILL BE SAVED IN:\n    ", out_dir.resolve())
    print("=" * 78)
    times = list(RUNS)

    # ----- load -----
    df = psd_utils.load_psd_runs(RUNS, apply_inverse_filter=APPLY_INVERSE_FILTER, include_excluded=INCLUDE_EXCLUDED)
    groups = psd_utils.read_groups_csv(GROUPS_CSV) if GROUPS_CSV else (GROUPS or {"all": sorted(df["animal"].unique())})
    group_order = list(groups)
    df = psd_utils.assign_groups(df, groups)
    df = psd_utils.interpolate_line_noise(df, ranges=INTERP_RANGES)
    print("Line noise interpolated over (Hz):", *INTERP_RANGES)
    df = psd_utils.normalize_spectra(df, band=NORM_BAND)
    color_map = COLOR_MAP or {g: plt.cm.tab10(i) for i, g in enumerate(group_order)}

    counts = df[["animal", "time", "group"]].drop_duplicates().groupby(["time", "group"]).size().unstack(fill_value=0)
    print("\nAnimals per group:\n", counts, sep="")

    # ----- spectra by group -----
    for time in times:
        part = df[df["time"] == time]
        psd_utils.plot_spectra(
            part, "interp_spectra", color_map=color_map, freq_range=FREQ_RANGE,
            title=f"Spectra ({time})", save_path=fig_dir / f"spectra_{time}.png",
        )
        psd_utils.plot_spectra(
            part, "interp_spectra", color_map=color_map, freq_range=(0.5, 20), log_y=False, sharey=False,
            title=f"Spectra, low frequencies ({time})", save_path=fig_dir / f"spectra_low_{time}.png",
        )
        psd_utils.plot_spectra(
            part, "norm_spectra", color_map=color_map, freq_range=(NORM_BAND[0], NORM_BAND[1]),
            title=f"Normalized spectra ({time})", save_path=fig_dir / f"spectra_normalized_{time}.png",
        )
        plt.close("all")

    # ----- comparing time points (only when RUNS has more than one entry) -----
    if len(times) > 1:
        pair_colors = {
            f"{g}_{t}": plt.cm.tab10(i) for i, (g, t) in enumerate((g, t) for g in group_order for t in times)
        }
        psd_utils.plot_spectra(
            df, "interp_spectra", group_col="group_time", color_map=pair_colors, freq_range=FREQ_RANGE,
            title="Spectra by group and time", save_path=fig_dir / "spectra_by_group_and_time.png",
        )
        psd_utils.plot_spectra(
            df, "norm_spectra", group_col="group_time", color_map=pair_colors,
            freq_range=(NORM_BAND[0], NORM_BAND[1]), title="Normalized spectra by group and time",
            save_path=fig_dir / "spectra_normalized_by_group_and_time.png",
        )
        plt.close("all")

    # ----- spectra by animal: spot an animal whose spectrum looks different -----
    for time in times:
        for group in group_order:
            part = df[(df["time"] == time) & (df["group"] == group)]
            if part.empty:
                continue
            psd_utils.plot_spectra_by_animal(
                part, "interp_spectra", freq_range=FREQ_RANGE, title=f"{group} by animal ({time})",
                save_path=fig_dir / f"by_animal_{group}_{time}.png",
            )
            plt.close("all")

    # ----- band power -----
    band_raw = psd_utils.band_power_table(df, "interp_spectra", BANDS)
    band_norm = psd_utils.band_power_table(df, "norm_spectra", BANDS)
    band_raw.to_csv(out_dir / "band_power.csv", index=False)
    band_norm.to_csv(out_dir / "band_power_normalized.csv", index=False)

    multi = len(times) > 1
    box_args = dict(
        x="group", hue="time" if multi else "group", order=group_order,
        hue_order=times if multi else group_order, outlier_groups=["state", "ch", "group", "time"],
    )
    for name, table, ylabel in [("raw", band_raw, r"Power [$\mu V^2$]"), ("normalized", band_norm, "Power [a.u.]")]:
        for band in BANDS:
            psd_utils.boxplot_band_power(
                table, band, ylabel, f"Band {band} Hz ({name})",
                save_path=fig_dir / f"band_{band}_{name}.png", **box_args,
            )
            plt.close("all")

    # ----- export for Prism -----
    for time in times:
        part = df[df["time"] == time]
        for column, name in [("interp_spectra", "spectra"), ("norm_spectra", "spectra_normalized")]:
            psd_utils.export_spectra_prism(part, column, group_order, out_dir / f"prism_{name}_{time}.xlsx", sex_map=SEX_MAP)
        for table, name in [(band_raw, "band_power"), (band_norm, "band_power_normalized")]:
            psd_utils.export_band_power_prism(
                table[table["time"] == time], list(BANDS), group_order,
                out_dir / f"prism_{name}_{time}.xlsx", sex_map=SEX_MAP,
            )

    print("\nWrote:", *sorted(p.name for p in out_dir.glob("*.*")), sep="\n  ")
    print("=" * 78)
    print("ALL RESULTS ARE IN:\n    ", out_dir.resolve())
    print("(tables and workbooks in that folder, plots in its figures/ subfolder)")
    print("=" * 78)


if __name__ == "__main__":
    main()
