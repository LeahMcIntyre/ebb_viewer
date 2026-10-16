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
4. `SleepQCGridPage` — per-animal OK/Review flagging. The Reclassify button recomputes both views (Spindle Mask and Sleep) from NREM-reclassified states (`ebb.process.nrem_reclass`: gap fill, plus an EMG gate on files where gap fill fragments NREM). View-only; nothing is written to disk.
5. `PSDPage` — computes PSDs, writes `psd/<RUN>/psds_<COMBO>.pkl`
6. `PSDVisualizer` — review PSDs, flag drink mask artifacts

### Manifest

`pipeline/manifest.py` is the authoritative pipeline state store. It persists to `project_root/manifest.json` (atomic write via `.tmp` rename).

Key model:
- `Manifest` — ordered dict of `ManifestEntry` objects, one per animal, plus the project-level `combo` (default `LFC_RSC`; stored at the top level of `manifest.json`)
- `ManifestEntry` — `preprocessed_edf` path, `has_spindle`, `sleep_qc`, `psd_status`, `drink_mask`, `notes`. A project has exactly one channel combo, so there is no per-combo run state.

`Manifest.build_from_standard(root)` is the standard constructor on the home page — it loads existing state and syncs new files from disk without overwriting existing flags.

Valid statuses: `sleep_qc` ∈ `{None, "ok", "needs_review"}`; `psd_status` ∈ `{None, "ok", "needs_drink_mask", "drink_mask_applied"}`.

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
