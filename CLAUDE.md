# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in editable mode (required before running anything)
pip install -e .

# Run the GUI
ebb-viewer

# Run all tests
pytest

# Run a single test file
pytest tests/ebb/test_spindle_masks.py

# Run a single test
pytest tests/ebb/test_spindle_masks.py::test_state_expands_per_window
```

## Architecture

The repo is split into two packages under `src/`:

- **`ebb/`** — pure processing library (no GUI). Contains masking, preprocessing, PSD estimation, and I/O (including the `SleepyRatAPI` HTTP client).
- **`ebb_viewer/`** — Qt6 GUI application that drives the pipeline. Entry point: `ebb_viewer/__main__.py:main` → `MainWindow`.

### GUI structure

`MainWindow` (`main_window.py`) uses a `QStackedLayout` with a sidebar `QListWidget` for navigation. Each sidebar item maps to a page widget. Pages are instantiated once at startup and receive `project_root: Path`.

Pages in pipeline order:
1. `PreprocessPage` — raw EDFs → `standard/`
2. `SpindleWritePage` — `standard/` → `spindle_edfs/<COMBO>/`
3. `SpindleUploadPage` — upload/download via `SleepyRatWorker`
4. `ReclassifyPage` — NREM gap fill + EMG gate (`ebb.process.nrem_reclass`); writes `reclass_state` and `final_state` into each `spindle_outputs/<COMBO>/*.csv` and records the gate decision in the manifest
4b. `SwdReviewPage` — optional (project opt-in): step through epochs that overlap an SWD and fix their states; writes `swd_reclassification` and updates `final_state`
5. `SleepQCGridPage` — opens on an **Overview** of boxplots of the flagging metrics (`ebb.process.sleep_flagging`; thresholds in `Manifest.flag_thresholds`) where animals past a threshold are highlighted and can be flagged, then the by-hour grid with per-animal OK / Review / Exclude buttons. Exclude requires a reason, appended to `notes` (`Manifest.exclude_sleep_qc`). Metrics and plots use the reclassified states (`final_state`); **Show original** switches to the original SPINDLE states.
6. `PSDPage` — computes PSDs, writes `psd/<RUN>/psds_<COMBO>.pkl` (ok **and** excluded animals)
7. `PSDVisualizer` — review PSDs of `ok` animals, flag drink mask artifacts; shows excluded animals with a banner, and has an Exclude button (reason required)
8. `DrinkMaskPage` — re-run PSDs with drink masks for the animals flagged `needs_drink_mask`
9. `FinalizePage` — seals `psds_final.pkl`; keeps excluded animals and marks them (`excluded` / `exclusion_reason`, `excluded_animals.csv`). Sleep analysis is not a page: users copy `notebooks/sleep_by_hour.ipynb` (settings + Run All) or `sleep_by_hour_walkthrough.ipynb` (the same calculation explained step by step); both compute in the open from `final_state` and leave out excluded animals
10. `ExportMasksPage` — exports masks (includes excluded animals, unmarked: a known gap)

How the states are produced and consumed is documented in `docs/sleep_reclassification.md`; how Sleep QC, PSD review, Finalize and exclusions fit together (statuses, queues, what each step does with an excluded animal, known gaps) is in `docs/sleep_qc_and_exclusion.md`. In short: **all analysis reads `final_state`** and raises `NotReclassifiedError` if it is missing; the original states are only for the "original" comparison views (`STATE_COLUMNS`).

### Manifest

`pipeline/manifest.py` is the authoritative pipeline state store. It persists to `project_root/manifest.json` (atomic write via `.tmp` rename).

Key model:
- `Manifest` — ordered dict of `ManifestEntry` objects, one per animal, plus the project-level `combo` (default `LFC_RSC`; stored at the top level of `manifest.json`)
- `ManifestEntry` — `preprocessed_edf` path, `has_spindle`, `sleep_qc`, `flag_reasons` (metrics past threshold when flagged, shown on Home), `reclass_gate_applied`, `swd_reviewed` / `swd_total` / `swd_waived`, `psd_status`, `drink_mask`, `notes`. A project has exactly one channel combo, so there is no per-combo run state.
- The project-level SWD review opt-in is `Manifest.swd_review_enabled` (top level of `manifest.json`, next to `combo`).

`Manifest.build_from_standard(root)` is the standard constructor on the home page — it loads existing state and syncs new files from disk without overwriting existing flags.

Valid statuses: `sleep_qc` ∈ `{None, "ok", "needs_review", "excluded"}`; `psd_status` ∈ `{None, "ok", "needs_drink_mask", "drink_mask_applied"}`.

Exclusion rules (details in `docs/sleep_qc_and_exclusion.md`):
- `"excluded"` needs a reason (`Manifest.exclude_sleep_qc`), appended to `notes` as an `Excluded (<stage>): ...` line (stage = Sleep QC or PSD review).
- `READY_STATUSES = {"ok", "excluded"}` ("Sleep QC decided") gate PSD compute and the exports, so an excluded animal is still computed.
- Only `"ok"` animals are in PSD review: the review queues use `== "ok"`, `psd_status` / `drink_mask` exist only while `sleep_qc == "ok"` (any other status clears them), and `flag_psd` raises for a non-ok animal.
- Finalize snapshots the exclusions into the sealed outputs; the manifest is the live record.

`manifest._entry_from_dict` still reads the pre-single-combo format (marked TEMPORARY) — delete it once existing projects have been re-saved.

### EDF viewer component

`edf_viewer/` is a self-contained EEG viewer used inside pipeline pages (not a standalone page itself). Key files:
- `eeg_viewer.py` — `EegMainWindow`, orchestrates viewer
- `trace_view.py` — pyqtgraph-based scrollable/zoomable trace rendering; antialiasing enabled at module level
- `masks.py` — `Mask` / `MaskSet` / `ParamSpec` dataclasses
- `mask_builder.py` — translates `ParamSpec` → calls into `ebb.masking`
- `masks_dock.py` — bottom dock UI; right-click → parameters dialog → rebuild

### SleepyRat upload/download

`SleepyRatWorker` (in `pages/spindle_upload.py`) is a `QObject` worker that globs `upload_dir=<Path>`, skips files already on the remote, uploads the rest, and downloads label CSVs.

The low-level HTTP calls live in `ebb/io/sleepyrat.py`.

### Constants

- `fs = 250` Hz (hardcoded in multiple places)
- `ch_names = ("LFC", "RSC", "LSC", "EMG")`
- EDF stem format: `AnimalID_..._PREPROCESSED.edf` — animal ID is the first `_`-delimited token
- The project's channel combo string (`Manifest.combo`, e.g. `"LFC_RSC"`) names the `spindle_edfs/`, `spindle_outputs/` and `psd/<RUN>/psds_<COMBO>.pkl` locations

## Working conventions

### No legacy compatibility code
Delete migration shims, deprecated parameter aliases, and back-compat
branches rather than tidy them. This codebase has one user and one
deployment — old saved files can always be re-generated. When you find
"if 'old_key' in params: ..." or similar, delete it.

### Branch off `dev`, never `main`
All feature and cleanup branches branch off `dev` and merge back to
`dev` via `--no-ff` to preserve the work-unit boundary in history.
`main` is the release branch.

### Sweep progress lives in `REVIEW_PROGRESS.md`
The repo is mid-way through a multi-phase code cleanup sweep. State of
record is `REVIEW_PROGRESS.md` at the repo root — read it first when
resuming work. `TODO.md` holds deferred items + product-level ideas.

### Past gotchas live in `PITFALLS.md`
A curated list of patterns that bit before — worker/threading traps,
manifest invariant edges, PSD compute / drink mask pitfalls, Qt
styling quirks. Read the relevant section before touching `pages/`,
`pipeline/manifest.py`, or `ebb/process/psd_compute.py`. Skim it before
running auto-formatters or aggressive simplifications — there are
several seams that linters love to delete.
