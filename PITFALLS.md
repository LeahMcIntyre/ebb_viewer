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

### Cache eviction in `_poll()` during review mode
The 10-second background poll in `SleepQCGridPage._poll` evicts cached
combo data for combos in `pending_rerun_review()`. Evicting *mid-review*
caused the second animal's rerun trace to disappear when navigating to
it (cache was cleared before the next plot built). Fix lives in
`_poll`: skip eviction when `self._review_mode` is True.

### `needs_rerun_pending()` gating on `source_combo` alone
Early version excluded a run from the pending queue as soon as
`source_combo` was set. Caused vanishing items when the user cancelled
an upload between Rerun page and Sleep QC: the EDF write set
`source_combo`, the cancel meant no CSV, but the queue thought the
animal was already past that stage. Fixed by gating on **CSV presence
on disk**, not on `source_combo`.

### Cancelled-upload race in Rerun page
If the upload dialog is cancelled, the spindle_outputs CSV never lands,
but the manifest is already half-set (`source_combo` stamped on the
new run). The animal should re-appear in the rerun queue on next
refresh — verified by the CSV-presence gate above. Don't try to "undo"
the half-state at the manifest level.

### Launching multiple SleepyRatWorkers in a loop — keep ALL refs alive
`SleepyRatWorker` has no Qt parent. If you spawn several in a tight
Python loop and only stash the latest in a single `self._sr_worker`
attribute, the earlier workers get Python-GC'd before
`thread.started → worker.run` can dispatch — only the last worker
actually runs. The original Rerun-page code looked like a single-slot
attribute but worked because each iteration was bracketed by a
modal `dlg.exec()` that spun the event loop. When the per-combo
dialog was consolidated into one bulk dialog, the modal break went
away and the bug surfaced. **Fix:** append each worker + thread to
`list` attributes on the page so all live workers stay reachable
from Python. Mirror this pattern any time a page may launch >1 worker
in the same call. The threads themselves usually survive because they
have a Qt parent (the page), but the workers don't.

---

## Manifest semantics

### One-ok invariant
`flag_sleep_qc("ok")` cascade-rejects every sibling run for that
animal. Un-okaying restores them via the `prev_sleep_qc` /
`rejected_by` bookkeeping on each rejected sibling. **Never** poke at
`sleep_qc` fields directly — always go through `flag_sleep_qc` so the
cascade stays consistent. The integrity check in `Manifest.load`
catches multi-ok states and auto-fixes them (with a warning), so
violations are loud, but the right thing is to not write them at all.

### `source_combo` is forward state, not history
`source_combo` is the backward pointer from a rerun row to the row
that triggered it. It's used to filter `pending_rerun_review`. Don't
treat its presence as "this animal's rerun is done" — that's gated
separately on CSV presence + manifest status.

### `add_run` on an existing ok run
`add_run` was originally happy to reset `sleep_qc` to None on an
already-ok run when re-stamping `source_combo`. That violates the
invariant silently. Current code guards against this — keep the
`if run.sleep_qc != "ok"` check around the reset.

### Stamping `source_combo` from `spindle_edfs/`
Earlier `build_from_standard` stamped `source_combo` from both
`spindle_edfs/` and `spindle_outputs/` scans. The `spindle_edfs/` scan
caused an item to disappear from the rerun queue the moment a user
manually placed an EDF in that directory — *before* it had a CSV.
Fixed by scanning only `spindle_outputs/`.

---

## PSD compute / drink mask

### `psds_channel_merged.pkl` is immutable after `build_final_pkl`
Drink-mask reruns must **not** overwrite the per-combo PKLs or the
channel-merged PKL. They land in `psds_drink.pkl` (accumulates,
replace-per-animal) and the overlay is regenerated in
`psds_channel_merged_drink.pkl`. The Finalize page picks the `_drink`
variant when present, else the bare `_merged`.

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
by reading the manifest's `run.drink_mask` field. The manifest field
is cleared once an animal is flagged "ok" with no other run still at
`drink_mask_applied`, so the .npy file is the authoritative record.
Same pattern for SWD: glob `swd/<animal_id>_*.mat`.

### One drink_masks offset CSV per project
The Export Masks pipeline raises if `drink_masks/` contains more than
one `.csv`. The PSD/Drink Mask UI uses the same convention but
silently picks the first match — flagged in `TODO.md` to unify. Don't
write code that handles "multiple offset CSVs"; the project structure
is intentionally one-per-project.

---

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
- **Review-mode Accept on the original combo is intentional** — flagged
  by the code-improvement advisor twice during the sweep as a bug;
  it's not. Codified in `CLAUDE.md`.
