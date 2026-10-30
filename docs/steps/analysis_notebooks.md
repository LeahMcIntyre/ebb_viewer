# Analysis notebooks and scripts

Terms are defined in the [glossary](../glossary.md).

These are not part of ebb-viewer. They are the last stage: they turn the sealed PSDs and the reclassified sleep states into
tables, plots and Prism workbooks. Copy one into your own analysis folder, edit its settings, and run it.

## Which one to use

| File | Use it to | Reads |
|---|---|---|
| `psd_analysis.ipynb` or `psd_analysis.py` (with `psd_utils.py` beside it) | Compare group spectra and band power. | `psd/<RUN>/psds_final.pkl` |
| `sleep_by_hour.ipynb` or `sleep_by_hour.py` | Sleep over the day: fraction of time, bout number and bout length by hour, and for the whole recording. | `manifest.json`, `spindle_outputs/<COMBO>/*.csv`, `standard/*.edf` headers |
| `sleep_by_hour_walkthrough.ipynb` | See how the sleep numbers are made, one step at a time, with plots. It runs the same calculation as `sleep_by_hour`, and checks it against the library. | the same |

A notebook and its script give the same output. Use the notebook if you like running cells; use the script (`python
psd_analysis.py`, `python sleep_by_hour.py`) if you prefer a single command.

## Before you run

- **Finish the pipeline.** For PSDs: step 9 (Finalize) has written `psds_final.pkl`. For sleep: Reclassify has run
  (`final_state` in every CSV) and Sleep QC has a decision for every animal (the script warns if not).
- **Use the `ebb-dev` environment.**
- **Make your own copy** of the notebook or script for each analysis, and keep `psd_utils.py` in the same folder as your PSD copy.
- **A groups list** (optional, see below), or you get one group containing everyone.

## Inputs

| Input | What it is |
|---|---|
| `psds_final.pkl` | One per time point. Excluded animals are marked in it, so the notebook can leave them out. Files written on Windows load on macOS and Linux. |
| `manifest.json` (sleep) | The project's combo, and which animals are excluded (with reasons in their notes). |
| State CSVs (sleep) | The `final_state` column, one state per 4 s epoch. |
| EDF headers (sleep) | Only the recording start date and time, read from the file's header. |
| Groups | Typed in the settings, or read from a CSV. |

**Listing groups in a CSV file.** Set `GROUPS_CSV` to the file's path. It replaces `GROUPS`. Animal IDs are the part of the file
name before the first `_`.

One row per animal (recommended), with columns `animal` and `group`. Other columns, such as `sex`, are ignored:

```
animal,group
Mice-1248,WT
Mice-1253,WT
Mice-1251,MUT
Mice-1279,MUT
```

Or one column per group, the group name in the first row:

```
WT,MUT
Mice-1248,Mice-1251
Mice-1253,Mice-1279
```

The two layouts are told apart by the header: if the first row has columns named `animal` and `group` (any capitalisation) it is
read as one row per animal; otherwise as one column per group, so do not name a group "animal" or "group" in that layout.
Spaces around names are ignored and blank cells are skipped. An animal listed in two groups, or a row with an animal but no
group, stops the run with a message naming the line.

---

# PSD analysis (`psd_analysis`)

## Settings

Edit the SETTINGS block of the script, or the Settings cell of the notebook. Lines marked `<<< CHANGE THIS` must be edited;
the rest have lab defaults.

| Setting | Meaning | Default | Change it when |
|---|---|---|---|
| `RUNS` | `{label: path to psds_final.pkl}`. One entry for one time point; add a second (for example `pre` and `post`) to compare time points. The label is only a name for the plots and files. | a placeholder path | Always. |
| `GROUPS` or `GROUPS_CSV` | The experimental groups (see above). Use one of them. | empty: everyone in one group | You have groups. |
| `INTERP_RANGES` | The frequency ranges bridged by interpolation to remove line noise, in Hz. | `[[56, 64], [118, 122]]` | **Only if the PSDs were computed with the notch off:** use `[[58, 62], [118, 122]]`. The script reads each run's `psd_params.json` and warns if they do not match. |
| `OUT_DIR` | Where results go. | `<project>/psd_analysis/<run name>`, next to the project's `psd/` folder; for several runs the folder is named after all of them, joined with `+` | You want them elsewhere. |
| `INCLUDE_EXCLUDED` | Keep animals excluded in Sleep QC or PSD review. | False (they are left out and listed with their reasons) | You want to see them. |
| `APPLY_INVERSE_FILTER` | Correct the 0.5–3.5 Hz bins for the hardware roll-off. Needs 0.5 Hz resolution. | True | Your PSDs are not at 0.5 Hz resolution (then set False). |
| `NORM_BAND` | The band whose power each spectrum is divided by, in Hz. | 1 – 100 | – |
| `BANDS` | `{name: (low, high)}` in Hz. Band power is computed for each. **Each name must contain at least one letter** (for example `Hz`) so Excel formats it correctly. | 1–4, 4–8, 8–12, 12–30, 30–70, 70–100 Hz | You use other bands. |
| `FREQ_RANGE` | Frequencies shown on the spectrum plots. | 0.5 – 110 Hz | – |
| `COLOR_MAP` | `{group: colour}`. | automatic | – |
| `SEX_MAP` | `{animal: "M" or "F"}`. Orders Prism columns males first. | none (alphabetical) | You want that order. |

## Fixed values

| Value | Fixed at | Meaning |
|---|---|---|
| Inverse filter | factors 2.4853, 1.3606, 1.1453, 1.0717, 1.0380, 1.0187, 1.0078 on the bins 0.5 to 3.5 Hz | Same as in the PSD Visualizer, but here it is **applied to the data** used for the tables and plots. |
| Interpolation | straight line in log-log space | Joins the median of the 3 bins either side of each range. |
| Band power | area under the spectrum between the band's edges, trapezoid rule | In µV². The same bin at a shared edge is used by both bands, but each band integrates only between its own edges. |
| Normalised spectrum | the interpolated spectrum divided by its own power in `NORM_BAND` | So its power in that band is 1; unitless (a.u.). Shows shape, not amplitude. |
| Outliers | beyond 1.5 × the interquartile range of the group | Calculated separately for each state, channel and group (and time point). They are outlined and labelled with the animal ID. |
| Animal ID | the file name before the first `_` | – |
| Channels | LFC, RSC, LSC (indices 0, 1, 2) | As computed in step 6. |

## What it does

1. **Load** each `psds_final.pkl`. Leave out excluded animals (unless `INCLUDE_EXCLUDED`) and print each with its reason, which starts with
   the step that excluded it.
2. **Apply the inverse filter** to the 0.5–3.5 Hz bins. The stored PSDs are not changed; this is where the correction first
   enters the numbers.
3. **Assign groups.** Animals in no group are labelled `unassigned` and listed; names in your list that are not in the data are listed too.
4. **Interpolate the line noise** over `INTERP_RANGES`, then **normalise**.
5. **Plot** group mean spectra with standard-error bands (channel by state), a low-frequency view (0.5–20 Hz, linear), the normalised
   spectra, and, with two time points, every group at every time point together. Then one line per animal for each group, to spot
   an animal that differs.
6. **Band power** for the interpolated and the normalised spectra, saved as CSV, and box plots with every animal as a point.
7. **Write the Prism workbooks.**

## Outputs

In `OUT_DIR`. The folder is printed when the run starts and again when it ends.

| File | Contents |
|---|---|
| `figures/spectra_<time>.png`, `spectra_low_<time>.png`, `spectra_normalized_<time>.png` | Group spectra for each time point. |
| `figures/spectra_by_group_and_time.png`, `spectra_normalized_by_group_and_time.png` | With two or more time points only. |
| `figures/by_animal_<group>_<time>.png` | One line per animal. |
| `figures/band_<band>_raw.png`, `band_<band>_normalized.png` | Box plots of band power, one per band. |
| `band_power.csv`, `band_power_normalized.csv` | One row per animal, state and channel (and time point), one column per band. Columns: `animal`, `time`, `state`, `group`, `ch`, `channel`, then the bands. |
| `prism_spectra_<time>.xlsx`, `prism_spectra_normalized_<time>.xlsx` | One sheet per channel and state: frequency down column A, then a block of columns per group, one column per animal. |
| `prism_band_power_<time>.xlsx`, `prism_band_power_normalized_<time>.xlsx` | One sheet per channel and state: a row per band, then a block per group. |

Units: spectra are µV²/Hz, band power µV², normalised values a.u.

## If something goes wrong

- "CANNOT RUN YET": the script names the setting to fix (a placeholder path, a missing file, both `GROUPS` and `GROUPS_CSV` set).
- "The inverse filter needs 7 frequency bins between 0.5 and 3.5 Hz": the PSDs are not at 0.5 Hz resolution. Set `APPLY_INVERSE_FILTER = False`.
- "Not in any group" lists animals missing from your groups. "In GROUPS but not in the data" lists names that were not found: a misspelled ID, or an excluded animal.
- A warning about `INTERP_RANGES`: the run's notch setting does not match; use the other range.

---

# Sleep by hour (`sleep_by_hour`)

## Settings

| Setting | Meaning | Default | Change it when |
|---|---|---|---|
| `PROJECT_ROOT` | The project folder (the one holding `manifest.json`). | a placeholder | Always. |
| `GROUPS` or `GROUPS_CSV` | As above. **Every animal in the project must be in a group**, or the run stops. | empty: one group "All" | You have groups. |
| `TZ` | The time zone the recordings were made in, used to handle daylight saving when working out where 6 AM falls. `None` ignores daylight saving. | `America/Chicago` | **Check it for your recordings.** |
| `OUT_DIR` | Where results go. | `<PROJECT_ROOT>/sleep_analysis` | – |
| `INCLUDE_EXCLUDED` | Keep animals excluded in Sleep QC (marked in an `excluded` column). | False | – |
| `BIN_HOURS` | Width of each bin in hours. Must divide 24. | 2 | – |
| `BEGIN_HR` | The clock hour that is ZT 0 (lights on). | 6 | Your light schedule differs. |
| `DARK_ONSET_ZT` | Where the grey "lights off" band starts on the plots. | 14 (8 PM) | – |
| `STATE_COLUMN` | The CSV column to read. `final_state` is the reclassified one. | `final_state` | Only to compare with the original scoring. In current SleepyRat files the original column is called `state`, not `rawstate`. |
| `EPOCH_SEC` | Epoch length in seconds. | 4 | Never. |

## Fixed values

| Value | Fixed at | Meaning |
|---|---|---|
| ZT | (clock hour − `BEGIN_HR`) mod 24 | ZT 0 is lights on. |
| Rotation | the recording is rotated so its first `BEGIN_HR`:00 is position 0 | The part before that first 6 AM is moved to the end, so each point keeps its own hour of the day. A recording that never reaches 6 AM is skipped with a message. |
| Per-second states | each 4 s epoch is repeated 4 times | Bins and bouts are counted in seconds. |
| Bins | `BIN_HOURS` wide, counted from the rotated start | The last bin may be shorter. |
| A bout | an unbroken run of one state, found over the **whole recording** | **Each bout is counted once, in the bin that holds most of its seconds (a tie goes to the earlier bin), with its full length.** None is cut at a bin edge, and the bin counts add up to the whole-recording count. Time in state (`frac_time`) is still measured inside each bin. |
| Rotation and bouts | bouts are found before rotating | A run that crosses the 6 AM rotation point stays one bout, and the two ends of the recording are not joined into one. |
| Days | the same hour of the day is averaged across days | `n_days` records how many days went into each average. |
| Animal ID | the file name before the first `_` | – |

## What it does

1. **Load the project:** the animals with a state CSV and a preprocessed EDF, the recording start time from each EDF header, the
   exclusions from the manifest (with reasons from the notes), and the groups. It stops if a CSV lacks `STATE_COLUMN`, an EDF
   is missing, or an animal is in no group, and warns if Sleep QC is undecided for some animals.
2. **Bin each animal:** per bin and state, `frac_time` (fraction of the bin in that state), `n_bouts` (whole bouts counted in the bin) and
   `mean_bout_sec` (their average full length in seconds; empty if there were none).
3. **Fold onto a 24 h day:** average the bins that fall on the same hour of the day across days, and convert to ZT.
4. **Whole recording:** per animal and state, without rotation: fraction of time, number of bouts, mean bout length, `bouts_per_hour` and
   the recording length.
5. **Write** the tables, Prism workbooks and plots.

## Outputs

In `OUT_DIR`:

| File | Contents |
|---|---|
| `sleep_bins.csv` | Every bin of every animal: `mouse_id`, `bin_idx`, `bin_start_hr`, `state` (`w`/`n`/`r`), `frac_time`, `n_bouts`, `mean_bout_sec`. |
| `sleep_bins_avg.csv` | The by-hour table: one row per animal, state and hour of the day, averaged across days: the three metrics, `n_days`, `zt`, `group`, `excluded`. |
| `sleep_whole_file.csv` | One row per animal and state: the three metrics, `bouts_per_hour`, `n_hours`, `n_days`, `group`, `excluded`. |
| `prism_sleep_by_hour.xlsx` | One sheet per state and metric (`w_frac_time`, `w_bouts`, `w_mean_bout_sec`, `n_…`, `r_…`): rows are ZT bins, animals blocked by group. |
| `prism_sleep_whole_file.xlsx` | One sheet per metric (`frac_time`, `bouts`, `mean_bout_sec`, `bouts_per_hour`): rows are Wake, NREM, REM, animals blocked by group. |
| `sleep_by_hour.png` | A 3 × 3 grid: group mean ± SEM per ZT bin for time in state, bout number and bout duration, by state. Grey band = lights off. |
| `sleep_whole_file.png` | Box plots of the whole-recording values, every animal shown as a point. |

## If something goes wrong

- "PROJECT_ROOT … has no manifest.json": point it at the folder that holds `manifest.json`.
- "No state CSVs … Has this project been through SPINDLE and Reclassify?": finish steps 3 and 4.
- "These CSVs have no 'final_state' column": run Reclassify.
- "These animals are in the project but in no group": add them to your groups, or leave the groups empty.
- "skipping <animal>: recording ends before it reaches 6:00": that recording never reaches the first 6 AM, so it cannot be rotated.
- "WARNING: Sleep QC not decided for …": some animals are not `ok` or `excluded`; they are analysed, but decide them first.

---

# The walkthrough (`sleep_by_hour_walkthrough.ipynb`)

The same calculation as `sleep_by_hour`, in 15 numbered sections with plots, for one animal first and then every animal: read the
states, upsample to one per second, rotate to 6 AM, score a bin by hand, fold onto a day, assign groups, convert to ZT, lay out one
Prism sheet, write the workbook, plot, and summarise the whole recording. Two sections ("Check against the library") compare its
numbers with the library functions the Sleep QC page uses. Use it to understand or to teach the numbers; use `sleep_by_hour` to
get them.

---

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [No high-pass filter in PSD analysis; an inverse filter compensates low frequencies at review](../decision_log.md#no-high-pass-filter-in-psd-analysis-an-inverse-filter-compensates-low-frequencies-at-review)
- [Groups can be typed or read from a CSV](../decision_log.md#groups-can-be-typed-or-read-from-a-csv)
- [Time bins: 2-hour bins aligned to clock time, starting at 6 AM](../decision_log.md#time-bins-2-hour-bins-aligned-to-clock-time-starting-at-6-am)
- [Metrics: fraction of time in state, bout count, bout duration](../decision_log.md#metrics-fraction-of-time-in-state-bout-count-bout-duration)

## Known limitations

- **`sleep_by_hour` stops when an animal is in no group,** while `psd_analysis` labels it `unassigned` and carries on.
- **`STATE_COLUMN = "rawstate"` does not match current SleepyRat files,** whose original column is `state`. Change it if you compare against the original states.
- **Exclusions come from different places.** The sleep notebook reads the manifest (`sleep_qc == excluded`); the PSD notebook reads the marker
  fields in `psds_final.pkl`, a snapshot from the day you finalized.
- **Timezone.** The script uses `TZ` only to place 6 AM across a daylight-saving change. The Sleep QC page uses a fixed `America/Chicago`.
- **Bout counts changed on 2026-10-30.** Each bout is now counted once, in the bin that holds most of it. Analyses run before that counted a
  bout across a bin edge in both bins, cut at the edge, so their bout numbers and mean bout durations differ.
