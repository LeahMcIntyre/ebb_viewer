# ebb-viewer user guide

> **Status: skeleton.** Sections marked **TODO** need a walkthrough of the app with real (or demo) data, screenshots, or an answer from [open_items.md](open_items.md). The reasons behind each setting are in [decision_log.md](decision_log.md).

Each page section has the same shape: **Goal, Before you start, Steps, Check your work, If something goes wrong.**

---

## 0. What this is

ebb-viewer takes continuous EEG/EMG recordings (EDF), stages sleep with SPINDLE, corrects the staging, lets you review the quality of each animal, and computes power spectra (PSDs) and sleep-by-hour tables. It is a GUI over the `ebb` processing library.

- It builds on EBB by Matt Caudill (https://github.com/mscaudill/ebb). **TODO:** final wording of the credit (see open items).
- You need: your recordings as EDF files, a SleepyRat/SPINDLE account, and enough disk space for the copies the pipeline makes. **TODO:** disk estimate per animal.
- **TODO:** one overview figure (the redrawn pipeline flow).

## 1. Install and start

Follow [windows_setup.md](windows_setup.md) (Windows). On macOS or Linux:

```bash
pip install -e .
ebb-viewer
```

Update, verify and troubleshoot: see the same file. **TODO:** macOS/Linux notes.

## 2. Before you click anything

**Read these. Most mix-ups come from here.**

### 2.1 One project folder per time point
The animal ID is the first `_`-delimited part of the file name (`CW0DC4_P098_KO_..._PREPROCESSED.edf` is animal `CW0DC4`). If animals from different time points share a folder, their IDs collide. **Use one project folder per time point.**

### 2.2 Channel order matters
The pipeline identifies channels by position only: **1 = LFC, 2 = RSC, 3 = LSC, 4 = EMG.** It does not check names. Make sure your files follow this order.

### 2.3 Recording length
Recordings are trimmed to the largest whole number of days that fits, 72 h or 48 h. Recordings shorter than 48 h are rejected.

### 2.4 The project folder
```
<project>/
  *.edf                  raw recordings you put here
  standard/              preprocessed EDFs (250 Hz)
  spindle_edfs/<COMBO>/  channel subsets uploaded to SPINDLE
  spindle_outputs/<COMBO>/  SPINDLE results (CSV per animal; reclassification adds columns)
  swd/                   one SWD .mat per animal, if you review SWDs
  drink_masks/           drink-event files and one offsets CSV
  psd/<RUN>/             PSD results, psd_params.json, psds_final.pkl
  sleep_analysis/        outputs of the sleep notebooks
  manifest.json          per-animal status; do not edit by hand
```
**TODO:** replace with a verified tree after a real run.

### 2.5 Concepts
- **Manifest:** the pipeline's record of what each animal has done. The Home page reads it.
- **Channel combo:** one per project (e.g. `LFC_RSC`), used for every animal.
- **States:** `w` wake, `n` NREM, `r` REM, one per 4 s epoch.
- **Original vs. reclassified:** SPINDLE's states are kept. Everything downstream reads `final_state`.
- **Statuses:** Sleep QC is `ok` / `needs_review` / `excluded`. PSD status is `ok` / `needs_drink_mask` / `drink_mask_applied`.

## 3. Quick start

A checklist of the whole run, in order. **TODO:** add typical times per step and a demo dataset.

1. Put raw EDFs in a new project folder; open it in ebb-viewer (Home).
2. Preprocess, then write the SPINDLE EDFs.
3. Upload to SleepyRat, wait, download the CSVs.
4. Reclassify. (Optional: SWD review.)
5. Sleep QC: look at the Overview, review flagged animals, mark each OK or Exclude (with a reason).
6. Compute PSDs; review them; flag drink-mask artifacts.
7. Drink Mask: rerun flagged animals; verify.
8. Finalize.
9. Sleep analysis in the notebook; export masks if needed.

## 4. Page reference

### Home
**Goal:** see the project's state. **TODO:** table columns, how it syncs from disk (`build_from_standard`), what the guide row for each step means.

### 1. Preprocess
**Goal:** raw EDFs to `standard/` at 250 Hz, trimmed to 48 or 72 h.
**Before you start:** Raw files in the project folder, channel order as in 2.2. Input sampling rate is a setting on the page (5000 Hz default).
**Steps / Check:** **TODO** (walkthrough).
Decisions: [log §1](decision_log.md).

### 2. Spindle EDFs
**Goal:** write the channel subset SPINDLE will score, to `spindle_edfs/<COMBO>/`. **TODO.**

### 3. Spindle Upload
**Goal:** upload to SleepyRat, download label CSVs. Files already on the remote are skipped. **TODO:** credentials setup, waiting time, what a failed upload looks like.

### 4. Reclassify
**Goal:** correct NREM epochs that are really wake artifacts.
**What it does:** NREM epochs that are artifacts, or sit between two artifact epochs, become wake. If this raises light-period NREM bouts by more than 10%, an EMG check cancels flips without EMG evidence. Original columns are kept; `reclass_state` and `final_state` are added.
**Check:** the page shows per animal whether the EMG gate applied and the light-period NREM bouts before and after.
Safe to rerun. **TODO:** screenshots. Details: [sleep_reclassification.md](sleep_reclassification.md), [log §3](decision_log.md).

### 4b. SWD Review (optional)
**Goal:** make sure SWDs scored as NREM don't create fake genotype differences in fragmentation.
**Before you start:** Tick the project opt-in. Every animal needs an SWD `.mat` file. For an animal with no SWDs, **create an empty `.mat` file** (preferred) or use "Confirm no SWD".
**Steps:** Open Review. `w`/`n`/`r` set the selected epoch's state; `Space`/`Shift+Space` move to the next/previous SWD epoch. A misclassified SWD epoch should get the state before and after the SWD. Save.
**Check:** the page shows `k of N` reviewed. **TODO:** screenshots. Details: [sleep_reclassification.md](sleep_reclassification.md) §5, [log §4](decision_log.md).

### 5. Sleep QC
**Goal:** decide, per animal, OK / needs review / exclude.
**Steps:** Start on the Overview (boxplots with raw points; dashed threshold lines). Animals past a threshold are highlighted; select and "Flag for Review". Open flagged animals in the viewer. In the by-hour grid, press OK, Review or Exclude. **Exclude needs a written reason.** "Show original" switches to SPINDLE's original states.
**Guidance:** Exclude when the sleep data look wrong and the EEG/EMG looks very noisy or wrong, for example lots of misclassification. Flagged animals should generally be excluded, but use your judgment. Thresholds are screening aids only. Do the review **blind to genotype**. **TODO:** how to hide genotype in practice.
Details: [sleep_qc_and_exclusion.md](sleep_qc_and_exclusion.md), [log §5](decision_log.md).

### 6. PSD Computation
**Goal:** compute PSDs for every animal that has passed Sleep QC (including excluded ones, which are marked later).
**Settings:** state groups (wake, NREM, REM), artifact masks, 60 Hz notch, hour windows. Defaults and the reasons for them: [psd_methods.md](psd_methods.md), [log §6](decision_log.md). **TODO:** which settings you should change and which you should leave; walkthrough.

### 7. PSD Visualizer
**Goal:** review the PSDs of `ok` animals. Flag animals with drink-artifact sidebands as `needs_drink_mask`. You can also exclude an animal here (reason required).
**Toggles:** Interpolate (over the line-noise gap) and Inverse Filter (low-frequency correction) are display options. **TODO:** whether they affect stored PSDs.

### 8. Drink Mask
**Goal:** rerun flagged animals with a drink mask, then verify ("Mask worked" or "Redo mask").
**Before you start:** a drink-event file per animal and one offsets CSV (`Animal,Offset`) in `drink_masks/`. The offset is the time from the recording start to the video start, read from the PVFS file. Events are padded by ±2 s. **TODO:** file formats and an example.

### 9. Finalize
**Goal:** seal `psds_final.pkl`: the file to use for analysis. Excluded animals stay in it, marked `excluded` with a reason, and are listed in `excluded_animals.csv`.
**Before you start:** every animal reviewed and no mask waiting for verification.

### 10. Export Masks
**Goal:** export artifact masks for analysis outside the pipeline. **Note:** excluded animals are currently included, unmarked.

### The EEG viewer
**Goal:** scroll and zoom traces, see the state bar and masks. Keys: `w`/`n`/`r` jump between state spans in the trace view. **TODO:** full shortcut list, masks dock.

## 5. Sleep analysis (notebooks)

Copy `notebooks/sleep_by_hour.ipynb` for each analysis, edit the Settings cell, Run All. Use `sleep_by_hour_walkthrough.ipynb` to see how the numbers are made.
**Settings to check:** `PROJECT_ROOT`, `GROUPS`, `INCLUDE_EXCLUDED`, `BIN_HOURS` (2), `BEGIN_HR` (6 = lights on), `TZ` (**default `America/Chicago`: change it**), `STATE_COLUMN` (`final_state`).
**Outputs** in `<project>/sleep_analysis/`: Prism workbooks, tidy CSVs, PNG plots. Metrics: fraction of time, bout count, bout duration. See [log §9](decision_log.md).

## 6. Common tasks

**TODO** (each as Goal/Steps):
- Add animals to an existing project
- Redo one animal
- Exclude and un-exclude an animal (un-exclude goes back to `needs_review`)
- Redo PSDs with different parameters
- Hand off a finished project

## 7. Troubleshooting

**TODO:** by symptom. Known ones: a page is greyed out or asks to confirm (an earlier step is incomplete); `NotReclassifiedError` (run Reclassify first); a re-downloaded SPINDLE CSV shows as not reclassified (rerun Reclassify); upload skipped everything (files already on the remote); mismatched sampling rate; empty PSD file.

## 8. Reference

**TODO:**
- Output files: `psds_final.pkl`, `excluded_animals.csv`, CSV columns (`rawstate`, `reclass_state`, `swd_reclassification`, `final_state`)
- Glossary (ZT, bout, epoch, SWD, commutator, SPINDLE noise)
- Parameter defaults (copy from [psd_methods.md](psd_methods.md) once it is corrected)
