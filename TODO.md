# TODO

## In progress: UX polish mode (P2)

Done across recent rounds: preprocess Rescan + wording (✓), rerun
multi-combo upload dialog consolidation (✓), preprocess/spindle
"Next →" hint structural part (✓), home per-PSD-run filter dropdown
(✓), spindle_upload page polish (✓), cross-page primary-action
button style (✓), Sleep QC UX bundle (✓), PSD page 4-zone reflow
+ Commutator section + docs pass + Setup compaction (✓), Export Masks
parity + channel selection + sampling-freq control (✓), sidebar
separator + Finalize PSD rename (✓), Drink Mask description rewrite
(✓), spindle write overwrite-dialog parity with preprocess (✓).
See P2 entries below for per-item notes.

**Next on deck:**
- No active P2 item queued. P2 entries below are either DONE,
  deferred, or carry their own scoping notes; pick the next one
  based on which would be the cheapest win in real use.

Skipped this session (pick up here):
`preprocess / spindle write: Route batch_preprocess console output into
the log box` — see entry below for the sketch.

## Post-Sweep Polish (deferred from Phase 5)

### docs: README.md
Repo has no `README.md`. Should cover: project purpose + one-paragraph
domain context (EEG sleep/PSD pipeline), install in editable mode,
`ebb-viewer` entry point, where the docs live (CLAUDE.md, PITFALLS.md,
REVIEW_PROGRESS.md, TODO.md). Keep terse — the deeper docs already
exist.

### release: Tag a release commit (v0.2.0 or similar)
After the README lands and any final smoke tests, tag a release on
`main` (after merging `dev` → `main`). The post-sweep state is
substantially cleaner than the pre-sweep baseline and worth a named
checkpoint.

### consistency: Open-ended naming / error-handling / fs sweep
The per-phase advisor passes already caught the high-value
consistency issues (bare excepts narrowed, `sum(1 for _ in m)` →
`len(m)`, `zip(strict=True)`, magic numbers named, fs hardcoding
documented). A wholesale re-pass would likely surface low-value items.
Skip unless a specific inconsistency becomes painful in real use.

### psd_compute: Commutator mask params should scale with user-set fs
`src/ebb/process/psd_compute.py` hardcodes `_COMMUTATOR_RADIUS_SAMPLES
= 250` (and `_COMMUTATOR_PAD_SAMPLES = 250`) — explicitly tagged "1 s
@ 250 Hz" in the source comments. But the PSD page exposes a Sampling
Frequency SpinBox the user can change, so at any fs ≠ 250 Hz those
constants silently lose their "1 second" semantics. The amplitude
threshold (`_COMMUTATOR_VALUE_UV = 2000`) is fs-independent and stays.
Fix: either (a) recompute the sample counts from the run's fs at the
top of `estimate_psd` / `batch_estimate`, or (b) store the radius/pad
in seconds in the params dict (matching the SD mask's pattern in
`MaskParamsWidget`) and convert in the compute backend. Option (b)
also enables surfacing the params in the UI later if needed. The
broader pattern (sample-count constants silently assuming fs=250 Hz)
was missed in the fs-hardcoding consistency pass — see memory
`feedback_fs_coupled_constants.md`.

---

## P2 — Moderate Value, Moderate Effort

### ~~rerun: Consolidate multi-combo upload dialogs~~
**DONE** — `_UploadDialog` now takes a list of rows and shows one grid
(Combo | SleepyRat project | Remote folder) instead of N sequential
modals. Surfaced and fixed a latent Python-GC + Qt-threading bug along
the way (workers in a loop now go into `self._sr_workers` / `self._sr_threads`
lists so none are destroyed before their event-loop slot fires).
Recorded in `PITFALLS.md` under Worker / threading.

### ~~spindle_upload: Page polish (paths, project picker, primary button)~~
**DONE** — three coordinated cleanups on the Spindle Upload page:
- Dropped the two read-only QLineEdits ("Selected upload folder",
  "Labels output folder") and their hint. Replaced with one compact
  relative-path summary line below the EDF-set combo; full absolute
  paths land in the tooltip. `_current_upload_dir` reads from the
  combo's userData instead of a separate line edit.
- Replaced the SleepyRat project `QListWidget` (and its enclosing
  group box) with an inline `QComboBox` + Refresh / New buttons in
  one row, matching the EDF-set row above it. Selection is preserved
  across refreshes.
- Promoted the "Upload & Download" button to the shared primary-action
  style; `_update_run_enabled` sets a tooltip reporting the first
  missing input in priority order (EDF set → SleepyRat project →
  remote folder).

### ~~ui: Consistent primary-action button style across pipeline pages~~
**DONE** — added `PRIMARY_BUTTON_QSS` + `apply_primary_button()` (and
a paired `SECONDARY_BUTTON_QSS` + `apply_secondary_button()`) to
`pipeline/theme.py`. Applied across preprocess, spindle (write),
spindle_upload, rerun, psds, drink_mask, and export_masks so every
"Run X" / "Apply X" / "Export" / "Upload & Download" button reads
the same. Finalize keeps its existing minimal bold-only style for
now since its primary button sits inside a per-run section header
where the larger styled button would crowd the layout. Spindle
Rerun's "Select All" picks up the outlined secondary style so it
doesn't read as native-Qt afterthought next to "Run Selected".

### ~~home: Surface per-PSD-run granularity in the Pipeline Summary table~~
**DONE** — "PSD run:" dropdown lives above the Pipeline Summary in the
summary header row. Default "All runs (best)" preserves the prior
best-wins behavior; selecting a specific run filters PSD File / PSD
Status cells to that run only (animals where the chosen run isn't
computed yet now show "—"). Hidden when fewer than 2 runs exist —
"All runs (best)" and a single run would render identically.
Selection is preserved across refreshes; falls back to default if
the selected run is removed from disk. Covered by 7 new tests in
`test_home_page.py`.

### ~~psd: Reflow page around user intent (Setup / What to compute / Filters / Run)~~
**DONE** — both the PSD compute page and the Export Masks page now use
a four-zone framing (Setup / What to Compute / Filters & Masks / Run)
with small blue uppercase section headers (`zone_header_qss` in
`pipeline/theme.py`). The States section is pulled out of
`MaskParamsWidget` via a new `expose_states_externally=True` flag and
rendered alongside channels + sampling-freq in zone 2, so all "what
gets produced" controls cluster together. Zone 3 picks up artifact-vs-
event sub-zone headers via `show_subzone_headers=True`. Setup zone is
collapsible with a one-line summary when collapsed (saves vertical
space once project + run name are set).

Related parity work landed at the same time:
- Commutator mask section added to `MaskParamsWidget` (amplitude
  threshold only; radius/pad stay hardcoded — see fs-scaling TODO).
- Section descriptions + per-parameter tooltips added to every mask
  section (States, Commutator, SD, Spindle Noise, SWD, Annotation,
  Compute Hours).
- Export Masks gained channel selection + sampling-freq control to
  match PSD page. Both controls are page-owned and merged into
  `_current_params` / `_snapshot_widget_values`.
- `NoScrollSpinBox` on `spin_fs` for both pages so a stray scroll
  doesn't change the value mid-config.
- ↻ "Detect fs" button next to each sampling-freq SpinBox, backed by
  `ebb.io.fs_detect.detect_fs_from_standard`.
- Drop the redundant "PSD Output Root" row from PSD setup (derived
  path lives in the Run-name tooltip instead).
- Auto-fit the Spindle Output Combos table to its row count.

Tests landed: 5 for `fs_detect`, 5 for page-level channels/fs
plumbing (incl. `comm_value` survives `_UI_ONLY_KWARGS`). Total +10.

### ~~psd: Unify mask controls UI with Export Masks page~~
**DONE** (Phase 5, Stage B-1 + B-2). PSD page now uses the shared
`MaskParamsWidget` inline with `show_drink_mask=False`. The dialog and
the "Advanced PSD Settings" collapsible are gone; mask params live in
one place across PSD Compute and Export Masks. The widget gained the
dialog's preview features (SWD file count, annotation file availability,
hour-window coverage estimate with per-window badges) and the
state-overlap warning banner.

### ~~preprocess: "Rescan" button + initial-state wording~~
**DONE** — `_scan_label` initial text is now `"(EDF scan pending)"` and
a Rescan button sits inline with it inside Folder Selection. `_scan_edfs`
also clears `_trim_hint_label` on empty/unreadable exit paths so a
healthy→empty rescan doesn't leave stale trim counts.

### preprocess / spindle write: Route `batch_preprocess` console output into the log box
Structural part (`✓ Done` hint frame + Next → button) already in place
on both pages. Remaining sub-task: capture `verbose=True` stdout from
`ebb.preprocess.edf.batch(...)` and emit it into each worker's `log`
signal so the GUI log box shows what currently only goes to the terminal
("Running 'standard' on N files using K cores.", "Saved N files to ...").
Sketch: add a small `LineEmittingStream` helper to
`widgets/worker_helpers.py` (file-like, calls `on_line(line)` per
complete line); wrap the `batch_preprocess` call in each worker with
`contextlib.redirect_stdout(stream)`. Only captures parent-process
prints; multiprocessing pool children keep their inherited stdout (fine
for our use). Skipped this session — pick up here when resuming. 

### psd: Make compute → merge two-step flow clearer in UI
~~The "compute per-combo PSDs" and "Build Final PKL" steps are logically distinct but visually run together. Label them as Step 1 / Step 2 with a separator, and show which combos will be included in the merge.~~
**DONE** — Step 1 / Step 2 layout with arrow, dynamic hint frame, and renamed button implemented.

---

## P3 — Larger or Needs More Context

### preprocess / spindle write: Cancel button + skip-existing on restart
Partial parity landed: Spindle Write's overwrite dialog now counts
`*_SPINDLE.edf` in the target and only warns when count > 0, matching
the Preprocess page's existing dialog. The larger Cancel + skip-existing
work below is still open.

Today the Preprocess page (and Spindle Write page) fires a
`multiprocessing.Pool` via `batch_preprocess` with no way to stop
mid-run. The user's only options are "close the window" or "kill the
process" — both kill the pool children too, but leave behind a partial
output file (whichever EDF a worker was mid-write on). The pool then
needs manual cleanup before restart: identify the truncated
`*_PREPROCESSED.edf` by size and delete it. Re-running overwrites
every output (no skip-existing check at
`src/ebb/preprocess/edf.py:99`), so a stopped batch of 20 files
re-does all 20 from scratch.

Two coordinated changes:

1. **Cancel button on Preprocess + Spindle Write pages.** Sits next to
   the Run button while a worker is active. Click sets a cancel flag
   that the worker checks between per-file iterations; on the next
   check the worker terminates the pool gracefully and emits a "Run
   cancelled — N of M files completed" log line. Has to handle the
   "pool worker mid-write" case — probably means the cancel only takes
   effect after the currently-writing file finishes. Document that
   trade-off in the button tooltip.

2. **Skip-existing mode in `batch_preprocess`.** Add a
   `skip_existing: bool = False` kwarg to
   `ebb.preprocess.edf.batch` (and the wrapper called by the spindle
   write page). When True, skip any input whose
   `<stem>_PREPROCESSED.edf` already exists in target. Pages opt in
   via a "Resume from where it stopped" checkbox or a follow-up "Some
   files already processed — skip them?" dialog. Detect the partial
   file (size noticeably below median) and offer to delete it as part
   of the same dialog so the resume doesn't carry a corrupted output
   forward.

Related: real cause of "stalling" on HDD-backed projects is just disk
I/O contention between pool workers. Add an explicit `workers=1`
option for HDD users (multiprocessing actually hurts on a spindle
because of seek thrashing).

### ~~psd / mask_export: per-file fs-mismatch guard~~
**DONE** — `ebb.io.fs_detect.assert_fs_matches(reader, expected_fs, *, path)`
is called inside `estimate_psd` (`psd_compute.py:209`) and
`mask_export._build_masks` (`mask_export.py:253`). A user-set fs that
disagrees with the EDF header now raises `ValueError` with a clear
message instead of silently driving mask windows at the wrong sample
count. Covered by tests in `test_fs_detect.py`,
`test_psd_compute_states.py`, and `test_mask_export_pipeline.py`.

### ~~psd / mask_export: auto-detect fs at page open instead of hardcoded 250~~
**DONE** — Both pages now call `detect_fs_from_standard` on `showEvent`
via a small `_maybe_autodetect_fs` helper that only fires when the
SpinBox is still at the `DEFAULT_FS` sentinel. User-set values and
saved-params values are never overridden; the ↻ button continues to
work as the manual refresh path. Related (still open):
`psd_compute: Commutator mask params should scale with user-set fs` —
same family of bug, see memory `feedback_fs_coupled_constants.md`.

### ~~psd: Revisit SD-threshold rule for lumped state groups~~
~~With state-selection presets, a user can pick a lumped group like `all` (wake+nrem+rem) or `sleep` (nrem+rem). Today SD thresholding is applied only when the group is literally named `wake` (see `if 'wake' in combo_state` in `estimate_psd`). For `all`, which contains wake samples, SD probably should apply to the wake portion. For `sleep`, it should stay off. Decide the rule (likely: apply SD when the group's code list includes `"w"`), update `estimate_psd` and tests accordingly.~~
**DONE** — `estimate_psd` builds a `wake_sub_mask` whenever any selected group lumps `'w'` with other states, and restricts SD thresholding to wake samples within those groups (`psd_compute.py:150-258`). Pure `sleep` (no `'w'`) skips SD entirely.

### psd: Clarify REM-in-multiple-groups semantics
~~If a user checks both `rem` and `sleep`, REM epochs feed into two PSDs (a REM-only PSD and a NREM+REM PSD). That's intentional — same epochs, different averages. Decide whether to (a) surface this in the UI with a small hint when overlapping groups are selected, or (b) leave silent.~~
**DONE (hint)** — States group in PSD Computation shows an amber "Overlap: …" banner listing shared epoch codes and the groups they feed. Still open: whether downstream plots/tables should visually distinguish lumped vs. single-state groups.

### psd_visualizer: Stable panel order for custom state groups
~~PSD Visualizer derives panel columns from whatever state names are in the pkl, using canonical-then-alphabetical ordering. If we ever add user-defined group names (beyond the 5 presets), confirm the ordering still makes sense, and consider a persisted user preference.~~
**DONE (behavior verified)** — `gather_states_from_store` (state_presets.py) now owns the canonical-then-alphabetical sort and is covered by tests for mixed-preset + custom-name inputs. Persisted user preference deferred until a UI path actually produces custom group names.

### spindle_upload: Investigate "Upload, Wait & Download" button issue
The button flow appears broken in some cases — needs reproduction and a specific bug report before this can be fixed. Document: what input conditions trigger the failure? Does it hang, crash, or give wrong output? 

### spindle_upload: Project names should propagate on page shown
The remote folder name auto-defaults to `project_root.stem + '_' + combo` on combo selection but may not fire on `showEvent`. Ensure it pre-fills correctly whenever the page is navigated to. Use the SleepyRat manifest to note if there has been a project selected already. 

### psd: SWD masks — decide policy on TS (needs scientific discussion)
Whether to mask out or include the transition state (TS) in PSD computation is a scientific decision that must be made before any implementation. Once policy is settled, add mask support + optional export to `.npy` (consistent with drink mask format).

### general: Run log / settings provenance
`psd/psd_params.json` already tracks PSD params. Consider extending to a `run_log.jsonl` that appends one entry per pipeline action (timestamp, what ran, which animals, params used). Low urgency but valuable for reproducibility and debugging.

### sleepyrat: Move hardcoded credentials out of source (security)
`src/ebb/io/sleepyrat.py` defaults `username`/`password` to real production credentials. Repo is currently private so exposure is limited, but git history is permanent and the password cannot be rotated right now. When rotation becomes possible: rotate the password, then move credentials to env vars (`SLEEPYRAT_USER`, `SLEEPYRAT_PASS`) with a config-file fallback (e.g. `~/.config/ebb/sleepyrat.json`), and delete the in-source defaults. Add a credentials dialog in the GUI for first-run setup.

### combine: Expand `ebb.io.combine` to other data types
Today `combine_edf` and `combine_swd` handle the two specific file types we restart-and-resume. The same per-file shift-and-stack pattern should generalize to drink masks (`.npy`) and any other timestamped data we end up restarting. Sketch a `combine_npy` (or a generic `combine_arrays(loader, writer, ...)`) that mirrors the `combine_swd` semantics: pair files, shift each by `idx * amount_sec`, concatenate, write.

### combine: Accept `.tsv` annotation files in `combine_annotations`
The PSD-compute and mask-export paths now discover annotation files in `.txt`/`.csv`/`.tsv` (openseize's `Pinnacle` reads tab-delimited by default, so `.tsv` parses fine). `ebb.io.combine` still globs only `*.txt` (`combine.py:322`). Extend its glob to include `.csv`/`.tsv` so combined annotations stay in sync with the rest of the pipeline.

### ~~sleep_compute: Pair state CSVs with EDFs and read start times from headers~~
**DONE** — `compute_sleep_bins_df_offset(state_dir, edf_dir, ..., tz=None)`
pairs each CSV with its preprocessed EDF by animal ID and reads
`start_date`/`start_time` from the EDF header via the new
`ebb.io.edf_header.read_edf_start_datetime` helper. CSVs without a
matching EDF emit a `UserWarning` and are skipped; pure CSV-only callers
are gone. Rotation is DST-aware when a `tz` is passed: the Sleep QC
visualizer page passes `ZoneInfo("America/Chicago")`, so a recording
that crosses spring-forward rotates by 7h of real-elapsed samples (not
a naive 8h) into the next `begin_hr:00`. Implementation note:
`seconds_until_target` converts both endpoints via `astimezone(timezone.utc)`
to dodge Python's same-`ZoneInfo` subtraction shortcut, which would otherwise
diff wall-clock fields. Same refactor renamed `ebb.io.fs_detect` →
`ebb.io.edf_header` (now also home to `detect_fs_from_standard`,
`assert_fs_matches`, and `parse_edf_start_datetime`); the three duplicated
`strptime` blocks in `psd_compute`, `mask_export`, and `eeg_viewer` were
deduped at the same time. Covered by 8 new tests in
`test_sleep_compute.py` + 1 in `test_edf_header.py`.

### psd_params: Partition `psd_params.json` into `ui` and `kwargs` sections
The saved psd_params JSON currently mixes UI affordances (`swd_mode`, `ann_enabled`, `time_filter_enabled`, `tod_start`, `tod_end`, `hw_enabled`) with scientific kwargs that get passed to `estimate_psd`. The mix forces `ebb.process.psd_compute._prepare_estimator_kwargs` to maintain a `_UI_ONLY_KWARGS` blacklist and to translate `states` (preset key list) → `labels` (group→codes dict) at every batch call. Cleaner structure: a top-level `{"ui": {...}, "kwargs": {...}}` shape so the kwargs block is exactly what `partial(estimate_psd, ...)` consumes. UI state (toggles + remembered-but-disabled values like "last hour_windows when hw_enabled=False") stays UI-shaped. Migration: read old flat JSON once, save as partitioned. `states→labels` happens once at load. Best tackled during Phase 2 cleanup of `pipeline/psd_params.py` (the GUI side has the right context). Until then the current helper is small, tested, and encapsulated — not urgent.

---

## Carried from `PIPELINE_AUDIT.md`

These were flagged in a pre-sweep audit; verified still applicable
after the Phase 3 + 5 cleanups. Items the audit listed that have since
been addressed (`add_run` ok-protection, `DrinkMaskPage._on_done`
swallowed exceptions, SleepQC stale manifest, home step 9, step 5
"resolved" labelling) were dropped during consolidation.

### psd: `batch_estimate` writes an empty PKL when no EDFs match state CSVs
`batch_estimate` writes `savepath` unconditionally — when no EDFs
match the state CSV animal IDs, the result is a pickled empty list.
Downstream `build_final_pkl` opens the empty PKL and silently skips
that combo. Fix: emit a warning / return early when `paired` is empty,
or assert non-empty before write.

### drink mask: stale records after `psds_channel_merged.pkl` rebuild
`psds_drink.pkl` records persist by animal ID. Rebuilding the merged
PKL (e.g. after dropping an animal) leaves the stale drink record
overlay-able onto a base that no longer contains that animal. Result:
the regenerated `psds_channel_merged_drink.pkl` includes an animal
that's no longer in the project. Fix: filter `psds_drink.pkl` records
against the active manifest animal-set when regenerating the overlay.

### manifest: sibling `psd_status` not cleared on un-ok restore
`flag_sleep_qc` un-okaying a run restores cascade-rejected siblings'
`sleep_qc` from `prev_sleep_qc`. If a sibling had `psd_status` set
before being cascade-rejected, the restore keeps that stale value —
the PSD review should be re-done since the underlying compute might
have changed. Fix: clear `psd_status` and `drink_mask` on every
restored sibling (mirroring what un-okaying does to the run itself).

### Testing gaps (worth writing eventually)
- `_refresh_combo_table` correctly excludes `psds_channel_merged.pkl`,
  `psds_channel_merged_drink.pkl`, and `psds_final.pkl` from compute
  targets.
- Manifest orphaned-`rejected_by` clearing leaves the run saveable +
  re-actionable (not stuck).
- `pending_drink_verification` + `pending_psd_review` are mutually
  exclusive by design — verify they never double-count.
- `needs_rerun_pending()` dead-zone: a `needs_rerun` row with a CSV
  on disk but `source_combo=None` is invisible to all queues. Document
  and add a test.

---

## Windows appearance polish (salvaged from deleted branches)

Two stale remote branches (`feature/windows-polish` @ `226e2c6`,
`refactor/window_compat` @ `603ec01`, both by `yygou`, ~137–147 commits
behind `dev`) were deleted 2026-07-02 after confirming their only
still-relevant content was cosmetic. The `ebbv2.core → ebb.core` import
fix they carried is already in `dev`; their `__main__.py` was a stale
placeholder superseded by dev's current entry point. The ideas below are
worth re-applying *by hand* to current `dev` (do NOT cherry-pick — the
old commits conflict heavily). Only relevant if we still run on Windows.

1. **Windows HiDPI + native font.** In `__main__.py` `main()`, before
   constructing `QApplication`, on `sys.platform == "win32"` set
   `QApplication.setHighDpiScaleFactorRoundingPolicy(PassThrough)`, and
   after constructing it, `app.setFont(QFont("Segoe UI", 9))`. Mirrors
   the existing Wayland/xcb platform guard already in that file.
2. **Higher-contrast status colors.** `pipeline/theme.py`
   `STATUS_COLOR_HEX` — the branch used punchier values that read better
   on Windows: ok `#9fd6ae`, needs_review `#ffe293`, rejected `#d4d4d4`,
   drink_mask_applied `#9fd6ae` (needs_rerun / needs_drink_mask unchanged
   at `#E97B7B`). Sleep QC legend `_STATUS_BG` override used
   needs_rerun `#f9c890`, rejected `#d4d4d4`. Verify against current
   dev colors before applying; treat as a deliberate palette bump.
3. **Global button style (optional).** A global `QPushButton` stylesheet
   (padding/border/hover/pressed/checked) was set in `__main__.py`. Lower
   priority — dev now has `PRIMARY_BUTTON_QSS` / `apply_primary_button()`
   in `pipeline/theme.py`, so reconcile with that rather than adding a
   competing global rule.

## Additional Suggestions

- **EDF format validation on import**: When `build_from_standard` encounters a file that doesn't match `AnimalID_anything_YYYY_MM_DD_HH_MM_SS.edf`, emit a non-blocking warning rather than silently skipping or crashing later.
- **Keyboard shortcuts in PSD Visualizer**: `O` = OK, `D` = Drink Mask, `←`/`→` = prev/next animal. With 60+ animals to review, this saves significant time.
- **Manifest backup before destructive ops**: Auto-save `manifest.json.bak` before cascade-rejects or `reset_sleep_qc` to allow recovery from accidental clicks.
- **Drink Mask page: highlight missing .npy files**: The ✓/✗ in the table is subtle. Show `"Missing mask file"` in orange for animals where the `.npy` hasn't been placed yet.
- **`SleepyRatAPI.wait_for_processing` should use `logging` instead of `print`**: Currently prints poll-status to stdout. Could move to a module-level logger, but doing this well requires deciding on log-level config and how Qt worker threads route log output to the GUI — likely larger than it sounds. Defer until a broader logging story is decided.
- **Clear hint banners on PSD run switch**: When the active PSD run is changed (e.g., switching from one named run to another in the PSD page UI), any state-overlap or compute-status hint banners from the previous run can stick around and mislead. Make the page reset/hide all hint banners as part of the run-switch handler so each run starts visually clean.
