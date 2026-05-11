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
- [ ] `home.py` (886)
- [ ] `preprocess.py` (401)

### 3b. Spindle pipeline
- [ ] `spindle.py` (442)
- [ ] `spindle_upload.py` (670)

### 3c. Sleep QC visualizer (1,535 lines, **2 sessions**)
- [ ] Session 1: read fully, propose structural refactor plan
- [ ] Session 2: execute refactor

### 3d. Rerun + PSDs (1,890 lines combined)
- [ ] `rerun.py` (355)
- [ ] `psds.py` (1,535) **— own session, possibly 2**

### 3e. PSD review + finalize
- [ ] `psd_visualizer.py` (249)
- [ ] `drink_mask.py` (550)
- [ ] `sleep_visualizer.py` (258)
- [ ] `finalize.py` (325)

### 3f. Export Masks
- [ ] `export_masks.py` (642) **— own session**

### 3g. Out-of-tree scripts
- [ ] `scripts/smoke_export.py` (125)

### Phase 3 closeout
- [ ] All tests pass; smoke-test the GUI end-to-end
- [ ] Merge `cleanup/phase3-pages` → `dev`

---

## Phase 4 — Top-level glue
- [ ] `main_window.py` (225)
- [ ] `__main__.py`
- [ ] `_patches.py` (51)
- [ ] All `__init__.py` files

---

## Phase 5 — Cross-cutting
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
