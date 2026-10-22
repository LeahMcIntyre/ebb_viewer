# Sleep QC, PSD review and exclusions

How an animal moves from Sleep QC through PSD review to Finalize, and what happens to it if it is
excluded along the way. For how the sleep states themselves are produced, see
`docs/sleep_reclassification.md`. This describes the single-combo line (`dev`).

## 1. The idea

Every animal gets a decision in Sleep QC: **ok** or **excluded**. An excluded animal is
**still computed** (PSDs, sleep tables), because excluding is a judgement about the analysis, not
about the data, and it can be undone. What changes is that it is **not reviewed** (nobody checks
its PSDs for drink artifacts) and it is **marked as excluded in the sealed outputs**, so the
analysis step can drop it and anyone reading a file on its own can see why.

The manifest (`manifest.json`) is the live record. The sealed outputs hold a snapshot taken by
Finalize.

## 2. Statuses

`sleep_qc` (per animal, `ManifestEntry.sleep_qc`):

| Value | Meaning | Set by |
|---|---|---|
| `None` | not assessed yet | default; `reset_sleep_qc` |
| `needs_review` | flagged; waiting for an EDF check | Review button, "Flag for Review" on the Overview, un-excluding |
| `ok` | checked, fine | OK button (Sleep QC grid or EDF viewer) |
| `excluded` | left out of the analysis; **reason required** | Exclude button (Sleep QC grid, EDF viewer, PSD Visualizer) |

`psd_status` (per animal, per PSD run): `None`, `ok`, `needs_drink_mask`, `drink_mask_applied`.

**Invariant:** `psd_status` and `drink_mask` only exist while `sleep_qc == "ok"`. Any change of
`sleep_qc` to something other than `ok` clears them (`Manifest._set_sleep_qc`), and `flag_psd`
raises for a non-ok animal. Always go through the manifest methods
(`flag_sleep_qc`, `exclude_sleep_qc`, `reset_sleep_qc`), not `entry.sleep_qc = ...`.

`READY_STATUSES = {"ok", "excluded"}` means "Sleep QC decided". It gates PSD compute and the
exports. Review queues use `== "ok"` instead (section 4).

## 3. Sleep QC page (`5. Sleep QC`)

The page has two views, switched by **VIEW**:

**Overview** (the default). One boxplot per flagging metric, one dot per animal, with the raw
points. A dashed line marks each threshold and is labelled with its direction and value. Animals
past a threshold are red and labelled; dot outlines show the status (green ok, orange needs
review) and excluded dots are faded. Click a dot, then **Flag for Review**, to set
`needs_review`. The metrics come from `ebb.process.sleep_flagging` and use `final_state`:

| Metric | Default threshold |
|---|---|
| Short (1-2 epoch) NREM bouts per file | above 400 |
| NREM bouts per dark hour (20:00 to 06:00) | above 15 |
| REM % of the file | above 10 |
| NREM % of the file | below 30 |
| Wake % of the file | above 70 |
| Max REM % in any 2-hour bin | at least 35 |

The cutoffs are starting points. The first, second, fourth and sixth come from the
spindle-validation notebook; REM (10) was read from that notebook's REM plot and Wake (70) is a
placeholder. They live in `flag_thresholds` in `manifest.json` (missing keys use the defaults);
there is no editor in the GUI, edit the file.

**Sleep** (the by-hour grid). The 3 x 3 grid (state x metric) in group or animal mode. Each
animal's legend row has **OK / Review / Exclude** toggles, a notes button, and a short red tag
listing the metrics past a threshold, for example `[short NREM bouts, high REM +2]` (two names
at most; hover for each metric's value and threshold). **Show original** plots the original
SPINDLE states instead of `final_state`; the flagging metrics follow it.

**Reviewing a flagged animal.** Open it in the EDF viewer (the QC toolbar has Mark OK, Needs
Review and Exclude) and decide: **OK** or **Exclude**.

**Excluding** always opens a dialog whose Exclude button stays disabled until a reason is typed;
cancelling changes nothing. The reason is appended to the animal's `notes` as an
`Excluded (<stage>): <reason>` line (`Manifest.exclude_sleep_qc`, which also refuses an empty reason). The stage is `Sleep QC` (grid, legend, EDF viewer) or `PSD review` (PSD Visualizer): it records where the exclusion happened, while the status itself is one and the same, `excluded`. The Home table column is "QC Status" for this reason, and the PSD Status cell of an excluded animal reads "—".
Excluded rows are greyed in the legend and their lines are dimmed in the grid.

**Un-excluding.** Pressing the pressed Exclude button again sends the animal back to
`needs_review` and keeps the note. Pressing OK on an excluded animal in the Sleep QC grid sets
`ok`. Either way it needs a fresh PSD review.

## 4. What each step does with each kind of animal

| Step | ok | excluded |
|---|---|---|
| Sleep QC | decided | decided; reason in `notes` |
| 6 PSD Computation | computed | **computed** |
| 7 PSD Visualizer, pass 1 (queue: ok with no PSD status) | reviewed: OK or Drink Mask | **not queued**; shown with a grey banner (reason), grey curves and a greyed dropdown entry; OK / Drink Mask / Reset disabled; Exclude stays (to un-exclude) |
| 8 Drink Mask (queue: ok and `needs_drink_mask`) | masks applied | **not listed** |
| 7 PSD Visualizer, pass 2 (queue: ok and `drink_mask_applied`) | verified | **not queued** |
| 9 Finalize, PSD | in `psds_final.pkl` | **in `psds_final.pkl`, marked** |
| Sleep analysis (`notebooks/sleep_by_hour.ipynb`, `sleep_by_hour_walkthrough.ipynb`) | analysed | **left out** by default (`INCLUDE_EXCLUDED = True` keeps and marks them) |
| 10 Export Masks | exported | exported, **not marked** (see section 7) |

The review queues (`pending_psd_review`, `needs_drink_mask`, `needs_drink_mask_rerun`,
`pending_drink_verification`) include only `ok` animals. That is why excluding the last
unreviewed animal, even one with a drink mask applied, empties every queue and the Visualizer
shows "All animals reviewed", with the Finalize prompt. The home page, the sidebar badges and the
Finalize counts read the same queues.

## 5. Excluding at the PSD Visualizer

The review bar has an **Exclude** button next to OK and Drink Mask, with the same required-reason
dialog and no keyboard shortcut (OK is `O`, Drink Mask is `D`). Excluding clears the animal's PSD
status and drink-mask link, removes it from the queues, greys its curves and shows the banner.
Pressing the pressed button again returns it to `needs_review`: the animal goes back to Sleep QC
and loses any PSD review progress.

## 6. Finalize marks the exclusions

Finalize keeps excluded animals and records the exclusions **as of the moment it runs**. Re-run
Finalize after changing an exclusion to refresh the markers.

| Output | Marker |
|---|---|
| `psd/<run>/psds_final.pkl` | every record has `excluded` (bool) and `exclusion_reason` |
| `psd/<run>/excluded_animals.csv` | `animal, reason`; always written, header only when nothing is excluded |
| Prism workbook (Export on the Finalize page) | an `excluded_animals` sheet, only when the sealed pkl marks any; the animal columns are unchanged |

The reason is the animal's `Excluded (<stage>):` note lines, each as `<stage>: <reason>`, joined with "; " (`Manifest.excluded_animals()`),
or the whole note if the animal was excluded without one. The Finalize page lists the excluded
animals on each run card and in the result dialogs.

The computed `psds_<combo>.pkl` files are never modified. The analysis step drops the rows where
`excluded` is true.

## 7. Known gaps

- Export Masks (`pipeline/mask_export.default_animals`) uses `ready_for_psd()`, so it includes
  excluded animals, and its meta files do not say so. Its docstring still says "only OK".
- `docs/pipeline_flow.md` and the other flow diagrams still show the old multi-combo pipeline.
- Excluded animals are not marked inside the Drink Mask page, because they are not listed there.

## 8. Code map

| What | Where |
|---|---|
| Statuses, queues, `exclude_sleep_qc`, `excluded_animals`, `flag_thresholds` | `src/ebb_viewer/pipeline/manifest.py` |
| Flagging metrics and default thresholds | `src/ebb/process/sleep_flagging.py` |
| Overview boxplots | `src/ebb_viewer/widgets/sleep_flag_overview.py` |
| Sleep QC page (legend, flag tags, exclude toggle) | `src/ebb_viewer/pages/sleep_qc_visualizer.py` |
| Required-reason dialog | `src/ebb_viewer/widgets/exclude_dialog.py` |
| EDF viewer Exclude action | `src/ebb_viewer/edf_viewer/eeg_viewer.py` |
| PSD review bar, banner, grey curves | `src/ebb_viewer/widgets/psd_graph_widget.py` |
| Markers in the sealed outputs | `src/ebb/io/exclusions.py`, `build_run_final_pkl` in `ebb/process/psd_compute.py`, `ebb/io/psd_export.py` |
| Finalize page | `src/ebb_viewer/pages/finalize.py` |
| Sleep analysis and its exclusion handling | `notebooks/sleep_by_hour*.ipynb` (read `manifest.json`) |
