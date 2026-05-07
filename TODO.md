# TODO

## P2 — Moderate Value, Moderate Effort

### home: Remove editable channel combo from pipeline summary table (if redundant)
The rerun combo is already settable from the yellow card in Needs Attention. A second editable combo in the pipeline table is a duplicate code path with no extra clarity. Evaluate and remove if nothing is lost.

### preprocess / spindle write: Add "Next →" navigation hint when done
Consistent with the Rerun page pattern. After preprocessing: `"✓ Done. → Go to Spindle Write"`. After spindle write: `"✓ Done. → Go to Spindle Upload"`. Use `navigate_to` signal. Add logs with the outputs that are currently being printed to console. 

### psd: Make compute → merge two-step flow clearer in UI
~~The "compute per-combo PSDs" and "Build Final PKL" steps are logically distinct but visually run together. Label them as Step 1 / Step 2 with a separator, and show which combos will be included in the merge.~~
**DONE** — Step 1 / Step 2 layout with arrow, dynamic hint frame, and renamed button implemented.

---

## P3 — Larger or Needs More Context

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

### sleep_compute: Pair state CSVs with EDFs and read start times from headers
`compute_sleep_bins_df_offset` currently parses recording start time from the `_HH_MM_SS_` chunk of the state CSV's filename. This is brittle (depends on filename convention, ignores date, blows up on differently-named files) and the EDF header already carries the authoritative `start_date` / `start_time`. Refactor to take an `edf_dir` (or the manifest) alongside `state_dir`, pair each state CSV with its EDF by animal ID, and pull the start datetime from the EDF header instead of parsing the filename. While here: make the rotation timezone-aware (`zoneinfo`) so multi-day recordings that cross DST align correctly — currently the naive `timedelta(days=1)` arithmetic silently misaligns bin boundaries by one hour across a DST shift.

### psd_params: Partition `psd_params.json` into `ui` and `kwargs` sections
The saved psd_params JSON currently mixes UI affordances (`swd_mode`, `ann_enabled`, `time_filter_enabled`, `tod_start`, `tod_end`, `hw_enabled`) with scientific kwargs that get passed to `estimate_psd`. The mix forces `ebb.process.psd_compute._prepare_estimator_kwargs` to maintain a `_UI_ONLY_KWARGS` blacklist and to translate `states` (preset key list) → `labels` (group→codes dict) at every batch call. Cleaner structure: a top-level `{"ui": {...}, "kwargs": {...}}` shape so the kwargs block is exactly what `partial(estimate_psd, ...)` consumes. UI state (toggles + remembered-but-disabled values like "last hour_windows when hw_enabled=False") stays UI-shaped. Migration: read old flat JSON once, save as partitioned. `states→labels` happens once at load. Best tackled during Phase 2 cleanup of `pipeline/psd_params.py` (the GUI side has the right context). Until then the current helper is small, tested, and encapsulated — not urgent.

---

## Additional Suggestions

- **EDF format validation on import**: When `build_from_standard` encounters a file that doesn't match `AnimalID_anything_YYYY_MM_DD_HH_MM_SS.edf`, emit a non-blocking warning rather than silently skipping or crashing later.
- **Keyboard shortcuts in PSD Visualizer**: `O` = OK, `D` = Drink Mask, `←`/`→` = prev/next animal. With 60+ animals to review, this saves significant time.
- **Manifest backup before destructive ops**: Auto-save `manifest.json.bak` before cascade-rejects or `reset_sleep_qc` to allow recovery from accidental clicks.
- **Drink Mask page: highlight missing .npy files**: The ✓/✗ in the table is subtle. Show `"Missing mask file"` in orange for animals where the `.npy` hasn't been placed yet.
- **`SleepyRatAPI.wait_for_processing` should use `logging` instead of `print`**: Currently prints poll-status to stdout. Could move to a module-level logger, but doing this well requires deciding on log-level config and how Qt worker threads route log output to the GUI — likely larger than it sounds. Defer until a broader logging story is decided.
- **Clear hint banners on PSD run switch**: When the active PSD run is changed (e.g., switching from one named run to another in the PSD page UI), any state-overlap or compute-status hint banners from the previous run can stick around and mislead. Make the page reset/hide all hint banners as part of the run-switch handler so each run starts visually clean.
