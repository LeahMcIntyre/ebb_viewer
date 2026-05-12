# Code Cleanup Sweep — Progress Tracker

**Goal:** sweep every source file for correctness, readability, simplification, and documentation. Bottom-up order, leaf modules first.

**Status legend:** `[ ]` not yet · `[~]` reviewed clean (no changes needed) · `[!]` changes pending · `[x]` done

**Active branch convention:** one long-lived `cleanup/<phase>` branch per phase, off `dev`, merged into `dev` when phase completes.

---

## Phase 0 — Foundation

- [x] Run `pytest` and capture baseline — **257 passing on `dev`**, **317 passing post-merge**
- [x] Resolve `stash@{0}` — applied & committed as `05f601e` on `feature/mask_export`
- [x] Merge `feature/mask_export` into `cleanup/phase0-foundation` (no conflicts)
- [x] Add `ruff` config to `pyproject.toml` and to `envs/ebb-dev.yml`
- [x] `ruff check --fix` pass (672 fixes; 1 real bug exposed in `psd_compute.py`)
- [x] `ruff format` pass (71 files reformatted)
- [x] Commit `CLEANUP_PLAN.md` + `REVIEW_PROGRESS.md`
- [x] Merge `cleanup/phase0-foundation` → `dev` (fast-forward)

**Phase 0 complete. ✅** Test count holding at 317.

**Phase 0 leftovers to address during per-phase reviews:** 107 non-auto-fixable ruff issues remain. Notable categories:
- 27 `E702` multiple-statements-on-one-line-semicolon
- 10 `E701` multiple-statements-on-one-line-colon
- 7 `B905` `zip()` without explicit `strict=`
- 5 `F841` unused variables
- 4 `B007` unused loop control variables
- 4 `E402` module imports not at top
- 2 `B006` mutable default args (real bug pattern — flag during phase 1)
- 2 `B028` `warnings.warn` without `stacklevel`
- 1 `B011` `assert False` (use `raise AssertionError`)
- ... plus a handful of SIM simplifications

Run `ruff check src/ tests/ scripts/` at any point to see the remaining list.

---

## Phase 1 — `ebb/` library (well-tested, safer)

### 1a. `ebb/core/` (243 lines)
- [x] `arraytools.py` — fixed empty-input bug in `aggregate1d`; cleaned `else` on while; doc/typing
- [x] `concurrency.py` — deleted dead `is_pickleable`; doc/typing
- [x] `mixins.py` — deleted dead `_fetch_methods`; simplified `__str__`; doc/typing
- [x] `metastores.py` — fixed MetaArray.select metadata bug; guarded MetaMask "metadata" name; misc

### 1b. `ebb/io/` (525 lines)
- [x] `combine.py` — fixed `pair` substring bug + `combine_edf` NaN-pad bug + `combine_swd` boundary clamp; added 2 regression tests
- [x] `sleepyrat.py` — type hints, raise_for_status everywhere, doc; credentials TODO'd
- [x] `utils.py` — **deleted** (between_pro replaced by native openseize 1.3.0 producer start/stop kwargs; verified empirically)
- [x] `__init__.py` — left bare (consistent with rest of project)

### 1c. `ebb/masking/` (614 lines)
- [x] `annotations.py` — fixed `artifact()` `between=(None,b)` bug; doc/typing
- [x] `events.py` — fixed `swd` docstring; cleaned `drinking_mask` truthiness; rewrote `get_offset` with proper error; restructured `time_of_day_mask` to match `hour_window_mask`; misc
- [x] `spindle.py` — clarified mask-intent docstrings (`state` selects, `spindle_noise` excludes); simplified `_expand_spindle_column`; extracted `_PROB_COLUMN`; doc/typing
- [x] `threshold.py` — `zip(strict=True)`; documented chunksize side effect; doc/typing
- [~] `__init__.py` — re-exports only, reviewed clean

### 1d. `ebb/preprocess/` + `ebb/process/` (1,641 lines)
- [x] `preprocess/edf.py` — fixed reader-close leak; deduped trim logic; resolved exist_ok TODOs; misc
- [x] `process/state_presets.py` — doc/typing; stale ref fix
- [x] `process/sleep_compute.py` — fixed `datetime.today()` race + DST note; parameterized magic 4; raise on short-recording rotation; deduped CSV reading; module docstring
- [~] `process/mask_export.py` — reviewed clean (recently written, well-structured)
- [x] `process/psd_compute.py` — fixed mutable defaults bug + tracemalloc leak; extracted scientific constants + helper for kwarg prep; full docstring rewrites; verified producer re-iteration empirically

### Phase 1 closeout
- [x] All `ebb/` tests pass — **319 passing**
- [ ] Merge `cleanup/phase1-ebb` → `dev`

---

## Phase 2 — `ebb_viewer/` infrastructure

### 2a. `pipeline/` (~1,400 lines, partial test coverage)
- [x] `manifest.py` — fixed 2 correctness bugs (rerun-target sibling restore in `flag_sleep_qc`; psd cleanup in `reset_sleep_qc`); deleted old flat-format migration; simplified `_run_from_dict` to defensive guard; extracted `_aggregate_across_runs` (3-method dedupe); hoisted `psd_params` import; tracked `dirty` in `build_from_standard`; +2 tests, -3 migration tests; SIM102/B007/F841 cleared
- [x] `mask_export.py` — fixed `_coerce_param`/bool flag silent-None bug; enforced one offset CSV per project (raise on >1); 8-tuple → `_BuiltMasks` dataclass; flattened nested `if s_prob`; SIM105 → `contextlib.suppress`; +1 test
- [~] `naming.py` — already cleaned in Phase 1 (re-export shim)
- [x] `psd_params.py` — deleted `_migrate_legacy` (no legacy compat); narrowed `load()` exception; cleaned docstring
- [~] `sleepyrat_config.py` — reviewed clean
- [~] `theme.py` — reviewed clean

### 2b. `widgets/` — DONE
- [~] `worker_helpers.py` — reviewed clean
- [x] `drink_mask_dialog.py` — added module docstring
- [x] `trim_to_widget.py` — dropped stale filename comment, added module + class docstrings
- [x] `tree_view.py` — added module + class docstrings
- [x] `range_dialog.py` — added module docstring
- [x] `sleep_viewer.py` — replaced inline CSV reader with shared `read_rawstate_column`; added module + class + method docstrings
- [x] `output_dialog.py` — added module docstring
- [~] `table_helpers.py` — reviewed clean
- [x] `stft_viewer.py` — added module + class docstrings; commented 56-64 Hz line-noise exclusion
- [x] `psd_graph_widget.py` — fixed log-Y clip-to-wrong-variable bug (silent gaps at zero/neg power); removed debug print; deleted half-implemented `_export_png` + dead toolbar block + stale filename comment; renamed shadowed `act_invfil`; hoisted `(0.5, 110)` to `DEFAULT_XRANGE`; renamed `_drink_review` → `drink_review` for sibling consistency; localized `first_plot`; added module + class docstrings + INVERSE_FILTER doc placeholder

**2b dedupe:** promoted `_read_rawstate_column` → `read_rawstate_column` in `ebb/process/sleep_compute.py`; deleted the duplicate copy in `ebb/process/mask_export.py` (which had a slightly more robust version — kept its `newline=""`, None-check, empty-row skip).

### 2c. `edf_viewer/` — DONE (~1,800 lines, **untested**)
- [x] `recording.py` — added module + class docstrings
- [x] `state_legend.py` — added module docstring; renamed unused `a` → `_a` (B007)
- [x] `state_bar.py` — added module docstring
- [x] `masks.py` — dropped stale `# model.py` filename comment; added module docstring; `zip(strict=True)` (B905)
- [x] `file_openers.py` — added module docstring; renamed `dir` → `start_dir` (Python builtin shadowing); hoisted `import csv` to module level
- [x] `masks_dock.py` — fixed ZeroDivisionError in `_state_overlap` for zero-coverage states (e.g. animal with no REM); added module docstring; `state_set: MaskSet | None`
- [x] `mask_builder.py` — extracted `_compute_artifact_masks` + `_wrap_artifact_masks` helpers (deduped ~25 lines between `build_default_masks` and `rebuild_artifact_masks`, killed 2 commented-out `# pro = make_producer` lines); hoisted `_DEFAULT_COMM_META`/`_DEFAULT_SD_META` constants; added module docstring; replaced vestigial TODO with real docstring on `_param_desc`
- [x] `trace_view.py` — fixed annotation teardown crash (now tracks `(pw, item)` pairs); replaced 0.01s magic epsilon with one-sample `1.0/fs`; eliminated `__init__` double `base_y` init + dropped `_apply_y`'s now-unneeded lazy guard; deleted commented-out reset-centers archaeology + dead `# lbl.setAlignment` line; added module/class/method docstrings (sticky-center zoom design now lives in module docstring)
- [x] `eeg_viewer.py` — fixed orphan-window leak in `on_open` (now sets `WA_DeleteOnClose`); fixed SleepPopup accumulation (now created once in `__init__` like STFTPopup); `launch_edf_window` now raises `ValueError` on fs != 250 instead of `print+return None`; extracted `_load_recording` (deduped EDF reading across 3 sites) + `_load_state_df` (narrows bare except, removes inline I/O from `__init__`); hoisted `_QC_STYLES` to class constant; replaced magic `4` with `DEFAULT_SPINDLE_EPOCH_SEC`; rewrote `main()` as a thin wrapper around `launch_edf_window` (no more hardcoded `/media/...` paths); added module + class docstrings; deleted dead toolbar comments. **Also added `ebb-eeg-viewer` console-script entry point in `pyproject.toml`** for standalone viewer launch.

### 2d. `data_stores/` — DONE
- [x] `psd_store.py` — deleted unused `parse_animal_from_path` wrapper; moved `_source_combos` init to `__init__`; moved freq-mismatch validation before `by_animal` mutation; typed `first_freqs` as `np.empty(0)` (was empty list); resolved 2 vague TODOs; added module + class docstrings

### Phase 2 closeout
- [~] Tests for pure-Python helpers — deferred to Phase 5 (no non-trivial pure helpers were extracted in 2c that warrant tests today; `_load_recording`, `_load_state_df`, `_compute_artifact_masks` all wrap external I/O or numerics covered by integration use)
- [x] Merge `cleanup/phase2-viewer-infra` → `dev`

**Phase 2 complete. ✅** 26 source files reviewed end-to-end. 330 tests passing.

---

## Phase 3 — `pages/` (largely untested, riskiest)

### 3a. Setup pages
- [x] `home.py` — **Stage A + advisor pass complete.** **Bugs fixed:** B1 `_open_windows` list grew unbounded — never pruned when user closed an EDF viewer, pinning recording arrays in memory; now connects `win.destroyed` to a new `_on_window_closed` slot that removes the entry; B3 step 5 "N reruns accepted" fired even when rerun targets were rejected (not OK'd) — now verifies each `needs_rerun` original's `rerun_combo` target has `sleep_qc == "ok"` before claiming done; B4 `_on_cell_double_clicked` reloaded the manifest independently of `_refresh`'s render, allowing a stale row index if a write landed between — now caches `self._table_rows` in `_refresh` and resolves indices against the cached snapshot; B5 `_do_import` did three manifest loads — now uses `build_from_standard`'s return value + `len(manifest)`; B6 misleading comment in `_make_review_card`'s rerun-combo filter; **PSD-status column precedence switched** from "worst-wins" (`needs_drink_mask` > `drink_mask_applied` > `ok`) to "best-wins" (`drink_mask_applied` > `ok` > `needs_drink_mask`) — user-confirmed change so the column reflects analysis-readiness rather than pending work (which is already surfaced via the attention card + per-run PSD Review). Bare `except Exception` narrowed to `OSError` in `_find_spindle_csv` and to `(OSError, ValueError)` in `_open_edf_for_animal`. Misleading manifest mutation idiom `Manifest.load(...).flag_sleep_qc(...)` split into `m = Manifest.load(...); m.flag_sleep_qc(...)`. **Refactor:** R2 threaded `psd_runs` through `compute_pipeline_status` so a single `_refresh` doesn't scan `project/psd/` twice; R3 named magic layout constants (`_ATTN_CARD_HEIGHT_PX`, `_ATTN_CARD_STRIDE_PX`); R4 collapsed three near-identical attention-card builders (rerun-pending, rerun-ready, drink-mask) into `_make_simple_attention_card`; R5 `_build_pipeline_guide` docstring corrected (8 steps, not 7); R6 duplicate `# --- Step 6: PSD Computation ---` comment removed; R7 `zip(strict=True)` on the statuses↔row-refs zip; `sum(1 for _ in manifest)` → `len(manifest)`; `any(True for x in ...)` → `any(... for x in ...)` at 2 sites. **UX:** UX1 `_import_lbl` "✓ N imported" / "No new animals found" now auto-clears after 3s via `QTimer.singleShot`. **Cleanup:** module docstring; `_open_windows` typed `list[QWidget]`; `_refresh_attention_zone` uses `w.deleteLater()` over `setParent(None)`; magic column index `6` in `_on_cell_double_clicked` replaced with `_COL_SLEEP_QC = _COLUMNS.index("Sleep QC")`; removed stale TODOs (centralize `compute_pipeline_status`, rerun-ready in step 5); inline import of `launch_edf_window` hoisted to module top. **+11 tests** in `tests/ebb_viewer/test_home_page.py` covering smoke construction, B4 PSD-status precedence (5 cases), B3 step-5 done/blocked decision (2 cases), B1 `_open_windows` pruning + safe slot, B4 `_table_rows` cache. **Deferred to Phase 5:** R1 extract `_build_table_row` from 160-line `_refresh`; UX2 visually distinguish "rerun done ✓" rows; UX3 double-click discoverability; B2 step-4 unreachable-active-branch edge case.
- [x] `preprocess.py` — module + class docstrings; removed dead target-dir fallback in `_run_clicked` + stale "Not Relevant Now…" comment; localized `_min_duration_hrs`; narrowed bare-except in `_scan_edfs` and surfaced unreadable-file count in the scan label; extracted `_on_preprocess_error` from inline lambda; +TODO for rescan button + initial-state wording

### 3b. Spindle pipeline
- [x] `spindle.py` — module + class docstrings; declared `_spindle_thread`/`_spindle_worker` in `__init__`; dropped dead target-dir override (read-only field); replaced hard-reject "Folder Already Exists" with confirm-and-proceed (matches SleepyRat output pattern); extracted `_on_spindle_error`; unified validation messages ("1 EEG channel selected — ready to run" / "2 EEG channels…"); per user, shortened lock label to just 🔒 emoji
- [x] `spindle_upload.py` — module + class docstrings; **GUI freeze fix**: extracted `_fetch_folders` and `_refresh_projects_clicked` to off-thread `_ApiFetchWorker` (was blocking the main thread on SleepyRat HTTP calls); extracted `_upload_pending` (~30 lines of dup between files/dir branches); added upload progress count `Uploading (i/N): name…`; safe `_pending_save` consume (try/except around `sleepyrat_config.save_combo`); renamed `Process Spindle` → `Upload & Download`; deleted dead `_download_only_clicked` method; dropped 2 commented-out `# self.btn_run.setEnabled(False)` lines (refer to nonexistent button) + duplicate inline `SleepyRatAPI` import; extracted `_on_remote_folder_changed` from 2-statement tuple-lambda; type-annotated `_get_common_run_context` return

### 3c. Sleep QC visualizer (1,535 lines, **2 sessions**)
- [x] Session 1: read fully + advisor pass (22 findings, triaged)
- [x] Session 2: applied 13 of 22 findings. **Bugs fixed:** B4 `_get_ref_combo` counted ALL runs but docstring said "ok runs" — would draw reference median over `needs_rerun` combos in the wrong direction; B2/U3/C4 (combined) `_on_review_mode_toggled` mutated UI before checking pending count, leaving page in inconsistent half-review state when no reruns existed — split into `_enter_review_mode` / `_exit_review_mode` with pre-check; B3 `_has_pending_rerun` did `glob()` per call in a hot loop — now cached in `_pending_rerun_ids` set populated by new `_refresh_manifest()` helper; B1 `SpindleFractionPlot.set_data` whisker math fragile for `<2` animals per state — added defensive `len(sdf) < 2: continue` guard matching the outlier helper. **Refactor:** R1 collapsed three flagging methods (`_flag_animal_ok`, `_flag_animal_review`, `_flag_sleep_qc`) into shared `_apply_sleep_qc(animal, combo, status, *, after=...)`; R2 collapsed two reset helpers via the new shared path; R4 factored `_jump_to_next_rerun_animal() -> bool` helper used by both `_on_next_rerun` and `_advance_to_next_rerun`; R5 hour-of-day ticks now use union of all drawn combos' x values (was last combo only — could omit ticks when rerun was shorter than original); R6 `_SENTINEL` lifted from module level to `_DEFAULT_ANIMAL` class constant; R7 fixed broken import ordering (sentinel was splitting stdlib/third-party/local). **Cleanup:** C1 deleted dead inline imports of `QFrame` + `QHBoxLayout` in `_make_legend_row_frame` (already at module top); C2 deleted ~10-line commented-out string-literal "code" block in `_make_fraction_comparison_widget` + the now-unused `orig`/`source_fracs` locals that fed it; C3 added module docstring; C7 fixed `addStretch` placement in `_update_legend_animal` (was after buttons → left-aligned; now between label + buttons → right-aligned, matches group legend); idiomatic `max(counts, key=counts.get)` over `counts.__getitem__`; dropped unused `spindle_outliers` local in `_render_group`; `zip(strict=True)` at two B905 sites. **+12 tests** in `tests/ebb_viewer/test_sleep_qc_visualizer.py` covering B4 (counts-only-ok + LFC_RSC tie preference + None when no ok), B2/U3 (zero-pending no UI mutation + happy-path entry), B3 (cache hit, no filesystem probe), R1 (each former call site flags correctly + emits manifest_changed), B1 (single-animal state + empty df). **Deferred to Phase 5:** R3 (legend OK/Review/Reset button extraction, ~60 LOC duplication — same shape as MaskParamsWidget extraction work), B5 (outlier set caching), C5/C6/U1 cosmetic nits

### 3d. Rerun + PSDs (1,890 lines combined)
- [x] `rerun.py` — module + class docstrings; fixed "SleepyRate" → "SleepyRat" typo; extracted `_on_sr_finished`/`_on_sr_error` from inline lambdas; disabled `btn_run` during a run + re-enabled in finish/error/cancel paths (prevents double-trigger); dropped unused `_combo_to_channels` fallback (`_COMBO_CHANNELS` is exhaustive); added inline comment on the multi-worker reassignment in `_offer_upload`; +TODO for consolidating multi-combo upload dialogs
- [~] `psds.py` — **Stage A + A.5 complete** (bug fixes + advisor pass + param-flow tests). Stage B (MaskingSettingsDialog → MaskParamsWidget unification) deferred to its own session. **Stage A bugs fixed:** B1 `ann_pad_after` default was 10.0 in 2 sites where every other site used 0.0 — silently injected unintended padding when loading legacy psd_params.json with annotation enabled; B2 bare `except Exception: pass` swallowed `manifest.save` errors when clearing stale `psd_status` flags — narrowed to `(OSError, ValueError)` + logged; B3 `MaskingSettingsDialog.load_params` only read legacy `swd_mode` — silently ignored widget-style `use_swd_mask`, now accepts both; B4 SWD auto-revert when swd/ becomes unavailable was silent — now logged. **Stage A.5 (advisor pass) bugs fixed:** BUG-1 empty channel selection wasn't gated — `params["channels"] = []` would crash compute (estimate_psd default kicks in on `None` not `[]`); now `_validate` checks `channels_ok` + dedicated gate label + channel checkboxes are now wired to live-update the gate; BUG-2 `_ann_keyword_edit.textChanged` was wired to `_refresh_ann_status` which loads the manifest on every keystroke — disconnected (the directory-choose path still calls it explicitly); BUG-3 `dspin_radius.setDecimals(1)` silently rounded saved values like 0.75 → 0.8 — now 2 decimals + step 0.05 (matches `MaskParamsWidget`); REFACTOR-1 threaded an optional `manifest` parameter through `_validate` and reused from `_refresh_combo_table` + `_refresh_swd_status` (was 4+ disk reads per `showEvent`); REFACTOR-4 reused the pre-flight-loaded manifest for the stale-psd_status clear in `_run_pipeline_clicked`; REFACTOR-2 dropped 4 dead re-assignments in `BatchEstimateWorker.run`'s saved-dict build (already covered by the `**self.params` spread); UX-2 dropped the explicit `_refresh_ann_status` call in `load_params` (signal-driven already fires); CLEANUP-3 deleted unused `channel_labels()`. **Stage A cleanup:** dropped legacy `hour_window` (singular) migration at 2 sites; hoisted inline imports (`warnings`, `datetime`, `openseize.edf_io`) from `_read_edf_headers` to module top; narrowed bare `except Exception` in header reading to `(OSError, ValueError)`; removed `QApplication.processEvents()` from `_log` (worker emits via Qt signals); typed `offset_path: Path | None`. **Added module + PSDPage + BatchEstimateWorker + MaskingSettingsDialog docstrings.** **+14 tests** in `tests/ebb_viewer/test_psds_page.py` covering B1 defaults, B3 dual-key tolerance, hour-window forwarding (with + without hw_enabled), annotation forwarding, full save↔load round-trip via psd_params.json, empty-channels gate (both signal-driven + dedicated label), radius precision round-trip

### 3e. PSD review + finalize
- [x] `psd_visualizer.py` — module + class docstrings; lifted `_FINAL_VIEW_STEMS` and `_CHANNEL_NAMES` to module level; flattened nested-ternary `run_channels` parse
- [x] `drink_mask.py` — module + class docstrings; hoisted 5 inline imports (`psd_params`, `Manifest`, `PRESET_DISPLAY`, `rerun_with_drink_masks`, `csv`); promoted `_AMBER` to class constant; declared `_pending_run_name` in `__init__`; documented `_UI_ONLY_PARAM_KEYS` scope; defensive `animal_combos` loop with assertion (one-ok invariant); fixed `_detect_offset_csv` to return None on multi-CSV (matches Export Masks pipeline policy); extracted `_validate_offset_csv` helper; renamed "Mask File" column → "Mask"; emptied redundant initial offset-hint state; post-run hint now interpolates run_name + full path; `swd_dir`/`ann_params` typed as `Path | None`/`dict | None`; updated 5 tests to monkey-patch at the use site (where `rerun_with_drink_masks` is imported) + replaced "first wins" multi-CSV test with explicit single-CSV + multi-CSV-returns-None tests
- [x] `sleep_visualizer.py` — **deleted** (unused — zero imports anywhere in the codebase; functionality lives in `widgets/sleep_viewer.py`)
- [x] `finalize.py` — module docstring; replaced `__import__("PyQt6.QtCore", ...)` cargo-cult with the already-imported `Qt`; hoisted `import pickle` to module top; tightened dead initial values in card builder

### 3f. Export Masks
- [x] `export_masks.py` — light second-look pass (file was just heavily feature-refactored); collapsed `progress_cb=lambda` to `self.progress.emit` (closure noise); UX: replaced `"export:<name>"` internal-prefix leak by tracking `(source, run_name)` separately — labels now read "Loaded PSD run: 'run_a'" / "Loaded export config: 'my_export'" / "Modified — no longer matches PSD run 'run_a'"; updated 6 tests for the new keyword-arg signature

### 3g. Out-of-tree scripts
- [x] `scripts/smoke_export.py` — renamed `_read_csv_head` → `_read_file_head` (it's also used for `meta.json`); tightened docstring to "text file" rather than "CSV"

### Phase 3 closeout
- [x] All tests pass — **481 passing**, ruff clean on every touched file
- [ ] Smoke-test the GUI end-to-end (user)
- [ ] Merge `cleanup/phase3-pages` → `dev` (after user GUI confirmation)

---

## Phase 4 — Top-level glue
- [ ] `main_window.py` (225)
- [ ] `__main__.py`
- [ ] `_patches.py` (51)
- [ ] All `__init__.py` files

---

## Phase 5 — Cross-cutting
- [ ] **psds.py Stage B** — unify `MaskingSettingsDialog` body with shared `MaskParamsWidget`. Requires porting the dialog's richer hour-window preview (per-window status badges, total-hours-per-animal estimate, day-availability check), SWD status text, and annotation file count to the widget. Own session, advisor required.
- [ ] **sleep_qc_visualizer.py legend extraction** — `_update_legend_group` and `_update_legend_animal` share ~60 LOC of OK/Review/Reset button construction logic. Factor a `_build_flag_buttons(animal, combo, status, run, row_l, *, mode)` helper. Also: outlier-set caching (B5) — `_get_spindle_outlier_animals` recomputed once per render + once per legend rebuild; cache invalidates with `_data_cache`.
- [ ] **home.py `_refresh` row-builder extraction** — `_refresh` is ~160 LOC building 9 cells per row inline. Extract `_build_table_row(row_idx, entry, combo, run, spindle_edf_ok, spindle_out_ok, psd_file_ok)` so the cell-by-cell logic is testable in isolation. Defer also: visually distinguish "rerun done ✓" rows from active rerun rows (UX2); double-click discoverability on Sleep QC column (UX3).
- [ ] Consistency sweep (naming, error handling, fs handling)
- [ ] Audit/consolidate `HANDOFF.md`, `PIPELINE_AUDIT.md`, `PLAN.md`, `TODO.md`
- [ ] README upgrade
- [ ] Final end-to-end smoke test
- [ ] Tag a `v0.2.0` (or similar) release commit

---

## Per-file rubric

1. **Correctness** — off-by-one in sample-index/mask code, float `==`, edge cases (empty/NaN/single), defensive copies of mutable args, race conditions in `QThread` workers, fs hardcoding.
2. **Readability** — methods >40 lines, args >5, nesting >3, magic numbers, single-letter names outside tight scopes.
3. **Documentation** — public class/function docstrings; module summary; comments only for non-obvious *why*.
4. **Simplification** — dead imports/functions, duplication, premature abstractions, defensive checks for impossible cases.
5. **Type hints** — public API only.

## Per-session loop

1. Open this file; pick next batch.
2. Read each file fully.
3. Run `code-improvement-advisor` agent → findings.
4. Discuss findings; decide what to apply.
5. Apply edits; run `pytest`; commit per-batch.
6. Update statuses here; commit tracker update.
