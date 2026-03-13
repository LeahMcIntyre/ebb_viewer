# Handoff

## Goal
Polish the spindle rerun pipeline UX in `ebb_viewer`:
1. Sleep QC review: per-combo OK/Review buttons in animal mode
2. Rerun page: log box, manifest-driven table, upload/download via SleepyRatWorker

## Current Progress

### Completed
- **Sleep QC animal mode** (`pages/sleep_qc_visualizer.py`): per-combo OK/Review buttons with single-ok enforcement; `_flag_animal_ok` resets other combos before setting.
- **Rerun page** (`pages/rerun.py`):
  - Replaced `QProgressDialog` with `QPlainTextEdit` log box + `_log()` method.
  - Table is 4 columns (Animal, Standard EDF, Original Combo, Rerun Combo) — no status column.
  - Filter shows entries where `rerun_combo not in entry.runs` OR `sleep_qc is None` on the rerun combo.
  - Skips preprocessing if spindle EDF already exists.
  - `_run_selected` tracks `written_files: dict[str, list[Path]]` (rerun_combo → EDF paths just written).
  - `_offer_upload(written_combos, written_files)` passes `files=` to worker instead of `upload_dir=`.
- **SleepyRatWorker** (`pages/spindle_upload.py`):
  - Added `files=None` parameter (explicit list of Paths to upload).
  - `run()` branches: `files` → upload exactly those files, no remote check; `upload_dir` → glob + remote skip check.
  - Download skip: checks `<stem>_labels.csv` exists locally before downloading each file.
- **Trace view antialiasing** (`edf_viewer/trace_view.py`): `pg.setConfigOptions(antialias=True)` at module level.

### Key Design Decisions
- **`files` vs `upload_dir`**: rerun page uses `files` (exact EDFs just written, no remote check overhead); spindle_upload page uses `upload_dir` (batch glob with remote skip check for partial-retry).
- **No status column on rerun page**: user wanted manifest-driven approach, not disk-state-based status.
- **Single-ok enforcement**: only one combo per animal can have `sleep_qc == "ok"`.

## What Worked
- Tracking `written_files` per `rerun_combo` in `_run_selected` via `target_dir.glob(f"{entry.animal_id}*.edf")` after write.
- Passing `files=written_files.get(rerun_combo)` to `SleepyRatWorker` — clean, no fragile API call.
- Module-level `pg.setConfigOptions(antialias=True)` in `trace_view.py` ensures consistent rendering regardless of launch path.

## What Didn't Work
- **Status column on rerun page**: disk-based `_rerun_step()` felt detached from manifest; reverted.
- **`_GRAY` / `_rerun_step`**: removed after user decided against the status column approach.
- **`upload_dir=` in `_offer_upload`**: uploading the whole combo directory from rerun page used a fragile `get_submission_names` remote check; replaced with explicit `files=`.

## Next Steps
- Verify `SleepyRatWorker` `files` branch works end-to-end (upload specific EDFs, wait, download labels).
- Verify `upload_dir` batch branch still works correctly from `spindle_upload.py`.
- Check that the `_offer_upload` dialog pre-populates `remote_folder` correctly for reruns (currently defaults to `{project_root.stem}_{rerun_combo}`).
- Consider whether `_offer_upload` should also support a "download only" option for reruns (e.g. EDF already uploaded in a previous session).

## Key Files
- `src/ebb_viewer/pages/rerun.py` — rerun queue page
- `src/ebb_viewer/pages/spindle_upload.py` — batch upload page + `SleepyRatWorker`
- `src/ebb_viewer/pages/sleep_qc_visualizer.py` — sleep QC with per-combo buttons
- `src/ebb/io/sleepyrat.py` — `SleepyRatAPI` (low-level HTTP calls)
- `src/ebb_viewer/pipeline/manifest.py` — `Manifest` / `ManifestEntry` / `RunEntry`
