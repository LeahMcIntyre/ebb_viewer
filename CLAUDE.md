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
4. `SleepQCGridPage` — per-animal, per-combo OK/Review/Rerun flagging
5. `RerunPage` — queue of animals needing reruns; writes new spindle EDFs + upload
6. `PSDPage` — computes PSDs, writes `psd/psds_<COMBO>.pkl`
7. `PSDVisualizer` — review PSDs, flag drink mask artifacts

### Manifest

`pipeline/manifest.py` is the authoritative pipeline state store. It persists to `project_root/manifest.json` (atomic write via `.tmp` rename).

Key model:
- `Manifest` — ordered dict of `ManifestEntry` objects, one per animal
- `ManifestEntry` — holds `preprocessed_edf` path + `runs: dict[str, RunEntry]`
- `RunEntry` — per (animal × channel combo): `sleep_qc`, `rerun_combo`, `psd_status`, `drink_mask`

`Manifest.build_from_standard(root)` is the standard constructor on the home page — it loads existing state and syncs new files from disk without overwriting existing flags.

Valid statuses: `sleep_qc` ∈ `{None, "ok", "needs_review", "needs_rerun"}`; `psd_status` ∈ `{None, "ok", "needs_drink_mask", "drink_mask_applied"}`.

### EDF viewer component

`edf_viewer/` is a self-contained EEG viewer used inside pipeline pages (not a standalone page itself). Key files:
- `eeg_viewer.py` — `EegMainWindow`, orchestrates viewer
- `trace_view.py` — pyqtgraph-based scrollable/zoomable trace rendering; antialiasing enabled at module level
- `masks.py` — `Mask` / `MaskSet` / `ParamSpec` dataclasses
- `mask_builder.py` — translates `ParamSpec` → calls into `ebb.masking`
- `masks_dock.py` — bottom dock UI; right-click → parameters dialog → rebuild

### SleepyRat upload/download

`SleepyRatWorker` (in `pages/spindle_upload.py`) is a `QThread` subclass with two modes:
- `files=<list of Paths>` — upload exactly those files, no remote skip check (used by `RerunPage`)
- `upload_dir=<Path>` — glob directory, skip files already on remote (used by `SpindleUploadPage`)

The low-level HTTP calls live in `ebb/io/sleepyrat.py`.

### Constants

- `fs = 250` Hz (hardcoded in multiple places)
- `ch_names = ("LFC", "RSC", "LSC", "EMG")`
- EDF stem format: `AnimalID_..._PREPROCESSED.edf` — animal ID is the first `_`-delimited token
- Channel combo strings (e.g. `"LFC_RSC"`) are used as directory names and dict keys throughout

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

## Non-obvious design intents

### Sleep QC review mode: ✓ Accept on the *original* combo is intentional
In `pages/sleep_qc_visualizer.py` `_update_legend_animal`, when review
mode is on, every combo in `drawn_combos` (including the non-rerun
original where `run.source_combo is None`) gets a `✓ Accept` button.
This *looks* like a bug because clicking Accept on the original
cascade-rejects the rerun the user just waited for — but it's the
intended affordance. After seeing the rerun's metrics, the user may
decide the original was fine and choose to keep it. Don't gate this
button on `source_combo is not None`.
