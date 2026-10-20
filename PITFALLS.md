# Pitfalls & Past Gotchas

Curated from `HANDOFF.md`'s "What Didn't Work" history — patterns that
bit before and would bite again if reintroduced. Read this when working
on the listed surfaces.

---

## Worker / threading

### `BatchEstimateWorker.offset_path` keeps getting stripped by linters
The `offset_path=None` parameter in `BatchEstimateWorker.__init__`,
`self.offset_path = offset_path`, and `offset_path=self.offset_path` in
the `batch_estimate(...)` call inside `pages/psds.py` are *all* required.
Linters (and human "simplify" passes) repeatedly delete this on the
grounds that `pages/psds.py` never sets `offset_path`. It's a
forward-compatibility seam used by the Drink Mask rerun path — leave
it alone.

### Launching multiple SleepyRatWorkers in a loop — keep ALL refs alive
`SleepyRatWorker` has no Qt parent. If you spawn several in a tight
Python loop and only stash the latest in a single `self._sr_worker`
attribute, the earlier workers get Python-GC'd before
`thread.started → worker.run` can dispatch — only the last worker
actually runs. A single-slot attribute only appears to work when each
iteration is bracketed by a modal `dlg.exec()` that spins the event
loop (the removed Rerun page did this until its per-combo dialogs were
consolidated, and the bug surfaced). **Fix:** append each worker + thread to
`list` attributes on the page so all live workers stay reachable
from Python. Mirror this pattern any time a page may launch >1 worker
in the same call. The threads themselves usually survive because they
have a Qt parent (the page), but the workers don't.

---

## Manifest semantics

### `has_spindle` gates the filtered views
`ManifestEntry.has_spindle` is set by `Manifest.build_from_standard`
when a file for the animal exists in the project combo's
`spindle_edfs/<combo>/` or `spindle_outputs/<combo>/`. Every filtered
view (`pending_sleep_qc`, `ready_for_psd`, ...) requires it, so an
animal with only a preprocessed EDF never shows up as "pending QC".
New code that builds a `ManifestEntry` by hand (tests, importers) must
set it or the entry is invisible to the views.

### PSD status is only valid while `sleep_qc == "ok"`
`flag_sleep_qc` clears `psd_status` and `drink_mask` when an animal
leaves "ok", and `reset_sleep_qc` always clears them. `flag_psd`
refuses to run on a non-ok animal. Go through these methods rather
than assigning `entry.sleep_qc` directly.

### Project combo lives in `manifest.json`
`Manifest.combo` (default `LFC_RSC`) is stored at the top level of
`manifest.json` next to the `animals` dict. Path helpers
(`spindle_edf_dir`, `spindle_output_dir`, `psd_path`) still take the
combo explicitly — callers pass `manifest.combo`. Changing the combo
on an existing project does **not** migrate flags: they belong to
whichever combo was active when they were set.

### TEMPORARY: reading pre-single-combo manifests
`manifest._entry_from_dict` still reads the old
`{animal: {runs: {combo: ...}}}` format (takes the project combo's
run, drops the rest, maps `needs_rerun`/`rejected` to unreviewed).
`build_from_standard` rewrites such a file in the new format. Delete
this branch (and its `test_legacy_*` tests) once existing projects
have been re-saved.

---

## PSD compute / drink mask

### `psds_<combo>.pkl` is immutable after Compute PSDs
Drink-mask reruns must **not** overwrite `psds_<combo>.pkl`. They land in
`psds_drink.pkl` (accumulates, replace-per-animal) and the overlay is
regenerated in `psds_<combo>_drink.pkl`. The Finalize page picks the
`_drink` variant when present, else the bare `psds_<combo>.pkl`.

### `rerun_with_drink_masks` and hour windows
Forgetting to strip `hw_enabled` and explicitly pass `hour_windows` /
`selected_days` to `partial(estimate_psd, ...)` causes `hw_enabled` to
leak into `estimators.psd()` as an unknown kwarg → crash. The function
must mirror `batch_estimate`'s param-prep step exactly.

### Subset reruns with `rerun_with_drink_masks`
Globbing state/drink/SWD paths without filtering to the active animal
set causes a count mismatch when running on a subset (e.g. just the
animals flagged `needs_drink_mask`). Always filter all path lists to
the input `animal_ids_set`.

### Drink-mask discovery by file presence, not manifest state
The Export Masks pipeline and the PSD compute path discover drink
masks by globbing `<project_root>/drink_masks/<animal_id>.npy`, not
by reading the manifest's `drink_mask` field. The manifest field
is cleared once an animal is flagged "ok" with no other PSD run still at
`drink_mask_applied`, so the .npy file is the authoritative record.
Same pattern for SWD, but use `find_swd_file` (`pipeline/swd_review.py`), not a glob:
real projects name files both `Mice-1256.mat` and `JK1011_P063_DEL_ts.mat`, and a
`<animal_id>_*.mat` glob silently misses the first style.

### One drink_masks offset CSV per project
The Export Masks pipeline raises if `drink_masks/` contains more than
one `.csv`. The PSD/Drink Mask UI uses the same convention but
silently picks the first match — flagged in `TODO.md` to unify. Don't
write code that handles "multiple offset CSVs"; the project structure
is intentionally one-per-project.

---

## Sleep states / reclassification

Full description: `docs/sleep_reclassification.md`.

### Never add `final_state` to `STATE_COLUMNS`
`STATE_COLUMNS` (`rawstate`, `state`) is the *input* to reclassification and the "original
states" views. `final_state` is the analysis column (`ANALYSIS_STATE_COLUMNS`). Putting it in
`STATE_COLUMNS` makes a Reclassify re-run read its own output.

### Analysis must not fall back to the original states
`masking.state` and the `sleep_compute` functions default to `final_state` and raise
`NotReclassifiedError`. A silent fallback would mix reclassified and unreclassified animals in
one analysis. Code that deliberately wants the originals (Sleep QC "Show original", the viewer's
original bar, a script) passes the states or `columns=STATE_COLUMNS` explicitly.

### Blank in `swd_reclassification` means "not reviewed"
Only reviewed SWD epochs and edited epochs get a value. Do not fill every SWD epoch on save:
the column is also the progress record, and `final_state` already falls back to
`reclass_state` for blank rows. `refresh_swd_after_reclass` relies on this (an entry equal to
the old `reclass_state` is an unedited copy).

### Keep a reference to unparented workers
`ReclassifyPage` hung forever because its `_ReclassWorker` was garbage-collected before
`thread.started → run`. Store the worker on the page (`self._worker`) as well as the thread.

### Tests: an unmocked `QMessageBox` hangs the run
A page that shows a modal dialog on an error path blocks a headless test forever. Patch
`QMessageBox` (or the confirm helper, e.g. `confirm_unfinished_swd_review`) in tests, and run
viewer test files with a wall-clock cap when something hangs.

### `TraceView` uses `w` / `n` / `r` to jump between state spans
`ReviewTraceView` (the SWD review window) overrides `keyPressEvent` to treat them as "set the
state" instead. The review window's buttons use `NoFocus` so key events stay on the trace.

## Qt UI / styling

### QLabel border bleed inside styled QFrames
A `QFrame` with a `border: 1px solid …` stylesheet applies the border
to child `QLabel` widgets too. Card-style UI fragments need explicit
`QLabel { border: none; background: transparent; }` in the card's
stylesheet to look right.

### `toolbar.addWidget(btn).setVisible(False)` is a no-op
`QToolBar.addWidget` returns a `QAction`, not the widget. Calling
`.setVisible(False)` on the return value hides the *action*, not the
button. To hide the button, store the action: `act = toolbar.addWidget(btn)`
then `act.setVisible(False)`.

### Legend stylesheet brace escaping
A stylesheet inside an f-string that uses `}` for layout boundaries
must escape with `}}`. Outside f-strings, single `}` is correct. A
double `}` in a non-f-string causes Qt to fail-silent-parse and the
sheet stops applying mid-rule.

### `_hint_frame` persistence across runs
The green "run complete" hint frames on PSD Computation and Drink Mask
pages used to stay visible when starting a new run, suggesting the
pipeline was done when it wasn't. Fix: explicit
`self._hint_frame.setVisible(False)` at the top of
`_run_pipeline_clicked` / `_apply_clicked`, just before
`self._computing = True`.

---

## Pyqtgraph / matplotlib

### `pg.PlotWidget(viewBox=...)` and `setBackground`
Setting a background color on a `PlotWidget` constructed with a custom
viewBox needs the call on the widget, not the viewBox. Easy to call
on the wrong target since both accept `setBackground`.

### `legend_lvl` Z-order on overlay plots
When overlaying a reference line on top of per-animal traces, the
reference pen needs higher Z than the traces *and* matching width or
the visual layering reads wrong. `pg.mkPen(width=2.5)` plus
`pi.addItem(ref_line)` *after* the trace loop is the working
ordering.

---

## Lessons that became rules

- **No legacy compat code** — delete migration shims rather than tidy
  them. Codified in `CLAUDE.md`.
- **Branch off `dev`, never `main`** — codified in `CLAUDE.md`.
