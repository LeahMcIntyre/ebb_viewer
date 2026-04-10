# Handoff

## Goal
Polish the spindle rerun pipeline UX in `ebb_viewer` — specifically the flagging/review
loop from Sleep QC → EDF review → Rerun → re-review. Also improve manifest reliability,
test coverage, and general UI clarity.

---

## Current Progress

### Completed (earlier sessions)
- **Sleep QC animal mode** (`pages/sleep_qc_visualizer.py`): per-combo OK/Review buttons.
- **Rerun page** (`pages/rerun.py`): log box, manifest-driven table, upload/download via `SleepyRatWorker`.
- **SleepyRatWorker** (`pages/spindle_upload.py`): `files=` parameter for exact-file upload (used by rerun page); `upload_dir=` for batch glob (used by spindle upload page).
- **Home page** (`pages/home.py`): pipeline summary, "rerun done ✓", "Hide Rejected" toggle, collapsible review queue + file tree sections, colored combo badges in summary table.

### Completed (branch `refactor/clean-up`)

#### Manifest one-ok invariant (`pipeline/manifest.py`)
- `RunEntry` gains `prev_sleep_qc` + `rejected_by` for cascade-rejection bookkeeping
- `flag_sleep_qc("ok")` cascade-rejects all sibling runs, saving their prior status; un-okaying restores them
- `reset_sleep_qc` also restores cascade-rejected siblings and clears stale `psd_status`/`drink_mask`
- `build_from_standard` / `add_run` auto-reject new runs when an ok run already exists
- `load()` integrity checks: fix multi-ok animals (warn + auto-fix), clear orphaned `rejected_by` refs
- `flag_psd` raises `ValueError` if `sleep_qc != "ok"`

#### Tests (`tests/ebb_viewer/test_manifest.py`)
- 44 tests covering the full manifest API

### Completed (commits on branch `refactor/sleep_qc`)

#### Manifest additions (`pipeline/manifest.py`)
- `RunEntry.source_combo: str | None` — backward pointer in the rerun chain
- `"rejected"` added to `SLEEP_QC_STATUSES`
- `add_run(animal_id, channels, source_combo=None)` — stamps `source_combo`; handles re-processing after reload
- `pending_rerun_review()` — globs `{entry.animal_id}_*.csv` specifically
- `needs_rerun_pending()` — excludes only when output CSV is on disk (so cancelled uploads re-appear)
- `flag_sleep_qc` handles `"rejected"` cleanly
- `build_from_standard` stamps `source_combo` only from `spindle_outputs/` scan (not `spindle_edfs/`)

#### Home page (`pages/home.py`)
- "Needs Attention" scroll zone with yellow/orange/blue cards
- Attention zone auto-sizes; `navigate_to` signal wired for nav links
- Pipeline Summary table collapsible; `manifest_changed` + `_poll()` wired

#### Sidebar badges (`main_window.py`)
- Immediate refresh via `manifest_changed` signals + 10 s poll timer
- Home → `needs_review()`, Sleep QC → `pending_rerun_review()`, Rerun → `needs_rerun_pending()`

#### Sleep QC page (`pages/sleep_qc_visualizer.py`)
- Review button disabled when `needs_rerun` to prevent silent `rerun_combo` erasure
- `_poll()` skips cache eviction during review mode

#### Rerun page (`pages/rerun.py`)
- Shows items where CSV not yet downloaded; skips EDF re-write if already on disk

#### Tests (`tests/ebb_viewer/test_manifest.py`)
- 77 tests total, all passing

---

### Completed (sessions 3–4, branch `refactor/clean-up`)

#### UX improvements (all 9 original plan items done)

- **Priority 1**: Sidebar pending-work badges
- **Priority 2**: "Needs Attention" action zone on Home page
- **Priority 3**: Decision panel moved above plots in review mode
- **Priority 4** (`sleep_qc_visualizer.py`): Review mode tints page `#f0f4ff`; animal label becomes "Animal (review):"; `"(filtered: N pending)"` label shown next to dropdown
- **Priority 5** (`rerun.py`): After successful `_run_selected`, green hint frame with "→ Sleep QC" button
- **Priority 6** (`rerun.py`): Persistent "Upload Rerun…" button enabled when rerun EDFs exist without CSV
- **Priority 7** (`home.py`): `_SLEEP_QC_LABEL` maps statuses to human-readable labels
- **Priority 8** (`home.py`): "Import new animals" button; `showEvent` auto-runs `build_from_standard`
- **Priority 9** (`home.py`): Editable rerun cells display `✎` with tooltip

#### Drink mask architectural redesign

**Architecture**: PSD Computation page does a clean compute (no drink masks). Drink masks
are only applied from the dedicated "8. Drink Mask" sidebar page, after animals are
explicitly flagged `needs_drink_mask` in the PSD Visualizer.

**PKL architecture**:
- `psds_channel_merged.pkl` — built by `build_final_pkl`, **never modified**
- `psds_drink.pkl` — accumulates drink-mask reruns across sessions; per-animal replace
- `psds_channel_merged_drink.pkl` — regenerated on every drink mask rerun: `psds_channel_merged.pkl` minus drink animals + all of `psds_drink.pkl`

**`rerun_with_drink_masks`** (`psd_compute.py`): validates `source_combo` in `psds_channel_merged.pkl` against manifest ok combo before computing. Stamps `source_combo` on every `psds_drink.pkl` record.

#### Tests
- `tests/ebb_viewer/test_manifest.py` — 79 tests
- `tests/ebb/test_drink_mask_integration.py` — 30 tests

---

### Completed (previous session, branch `refactor/clean-up`)

#### P0/P1/P2 items (from TODO.md)
- PSD Visualizer drink mask banner updated to point to "8. Drink Mask" page
- PSD Visualizer OK/Drink Mask buttons made checkable with correct state sync
- Preprocess: computed Hz label + EDF filename format label
- Home: PSD step gate shows attention when review pending with ok animals
- Home: filter rerun combo dropdown excludes already-ok combos
- Home: drink mask cards + pipeline step 8
- PSD Visualizer: prominent "Reviewing: {filename}" label + is_final_view flag fix
- Preprocess: EDF file count / duration display with live warning

#### PKL file rename + Finalize page
- `psds_final.pkl` → `psds_channel_merged.pkl`, `psds_final_drink.pkl` → `psds_channel_merged_drink.pkl`
- New `psds_final.pkl` = true final written only by Finalize button
- `pages/finalize.py` — NEW standalone Finalize page ("9. Finalize" sidebar item)
- PSD Visualizer: green "→ 9. Finalize" hint when all PSDs reviewed

#### Drink Mask page: navigation hint → PSD Visualizer after completion

#### Tests — 109 passing

---

### Completed (this session, branch `refactor/clean-up`)

#### Stage 1–2 pipeline clarity fixes (from PIPELINE_AUDIT.md)
- Per-file log output (✓/✗ per file) for Preprocess and Spindle Write workers
- Preprocess: confirmation dialog before overwriting existing `standard/` EDFs
- Spindle Write: explicit "folder already exists" dialog instead of confusing `FileExistsError`

#### Stage 4 clarity fixes
- **Stale manifest in SleepQCGridPage** (`sleep_qc_visualizer.py`): `_poll` now detects when `spindle_outputs/` directories have changed and calls `_refresh_combos()` automatically — no hide/show cycle needed
- **Disabled Review button explanation** (`sleep_qc_visualizer.py`): Button text changes from "Review" to "Rerun Queued" when `sleep_qc == "needs_rerun"` (group mode + animal mode legends); tooltip retained for detail

#### Stage 5 clarity fixes
- **"N reruns resolved" misleading** (`home.py`): Changed to "N reruns accepted"
- **"Skipping preprocessing" confusing log** (`rerun.py`): Changed to "EDF already written — skipping to upload."

#### Stage 6 clarity fixes
- **"Build Channel Merged PKL" enabled prematurely** (`psds.py`): `_validate` now loads manifest and gates the button on all animals with `sleep_qc=="ok"` having their per-combo PKL — prevents silent skips
- **Two-step flow not visually connected** (`psds.py`): Step 1 / Step 2 labels with `→` arrow between buttons; hint after "Compute PSDs" now says "click 'Build Channel Merged PKL' to continue"; hint after "Build Channel Merged PKL" shows "→ PSD Visualizer"; button renamed from "Build Final PKL" to "Build Channel Merged PKL"

#### Stage 7 clarity fix
- **No "reset PSD status" in UI** (`psd_graph_widget.py`): Added "↺ Reset" toolbar button; hidden when no manifest; disabled when `psd_status is None`; calls `reset_psd_status()`; removed stale `print()` debug call from `_update_flag_status`

#### Stage 8 clarity fix
- **`_on_done` swallows `flag_psd` errors** (`drink_mask.py`): Failures collected per-animal; logged to log box; `QMessageBox.warning` shown if any failed; manifest always saved with partial successes

#### Stage 9 clarity fix
- **Home page missing step 9** (`home.py`): "9. Finalize" added to `_STEP_LABELS` / `_STEP_PAGE_NAMES`; step 9 logic: `done` when `psds_final.pkl` exists, `attention` when all reviewed and ready to finalize, `blocked` otherwise

#### Tests — 114 passing (5 new step 9 tests)

---

## Full Rerun Review Flow (as implemented)

```
1. Sleep QC page (Group mode)
   → click Review on a suspicious animal → manifest: needs_review

2. Home page — Needs Attention zone  (sidebar shows "Home (1)")
   → yellow card: [Animal] [combo] [Open EDF] [✓ OK] [Rerun as: ▼] [Needs Rerun]
   → Rerun dropdown excludes already-ok combos; shows status of existing runs
   → click Needs Rerun → manifest: needs_rerun + rerun_combo

3. Rerun page  (sidebar shows "5. Spindle Rerun (1)")
   → Run Selected → writes spindle_edfs/<RERUN_COMBO>/ (skips if EDF already exists)
   → manifest.add_run(animal, rerun_combo, source_combo=original_combo)
   → Upload & Download dialog → spindle_outputs/<RERUN_COMBO>/
   → If upload cancelled or fails: item re-appears in queue on next refresh
   NOTE: if EDF + CSV already existed from a prior cycle, flag_sleep_qc now resets the
   existing rerun run entry to sleep_qc=None so the review queues pick it up correctly.

4. Sleep QC page  (sidebar shows "4. Sleep QC (1)")
   → showEvent evicts stale cache, badge appears: "● 1 rerun ready for review →"
   → click badge → review mode, dropdown filtered to pending animals
   → plots: solid line (original), dashed line (rerun), group mean reference
   → legend: [✓ Accept LFC_RSC] [✓ Accept RSC]  [Review]
   → decide → auto-advance or "Review Complete" → exit review mode

5. If "Review" chosen:
   → rerun combo flagged needs_review → Home queue → repeat from step 2
```

## Full Drink Mask Flow (as implemented)

```
1. PSD Computation page (6. PSD Computation)
   → Select combos, set params → Step 1: Compute PSDs (per-combo PKLs)
   → Hint: "✓ PSDs computed — click 'Build Channel Merged PKL' to continue."
   → Step 2: Build Channel Merged PKL → psds_channel_merged.pkl
   → Hint: "✓ Channel merged PKL built — ready for PSD review. → PSD Visualizer"
   → params saved to psd/psd_params.json

2. PSD Visualizer (7. PSD Visualizer)
   → Auto-selects psds_channel_merged_drink.pkl if present, else psds_channel_merged.pkl
   → Bold "Reviewing: {filename}" label shown above plot (Pass 1 / Pass 2 labels)
   → Flag buttons (✓ OK / Drink Mask / ↺ Reset) only active for merged PKLs
   → "Drink Mask" sets psd_status = "needs_drink_mask" in manifest
   → "↺ Reset" clears psd_status back to None (for mis-clicks)
   → Green "→ 9. Finalize" hint appears when all pending review counts = 0

3. Home page — Needs Attention zone
   → Lavender card per flagged animal: "→ Drink Mask page" button

4. Drink Mask page (8. Drink Mask)  (sidebar badge shows count)
   → Loads psd/psd_params.json as read-only
   → Table: animals flagged needs_drink_mask + mask file presence (✓/✗)
   → "Apply Drink Masks (N ready)" — gated on psd_params.json + .npy present
     a. Calls rerun_with_drink_masks: validates source_combo vs psds_channel_merged.pkl
     b. Updates psds_drink.pkl (accumulates across sessions, replace-per-animal)
     c. Regenerates psds_channel_merged_drink.pkl = psds_channel_merged.pkl base + psds_drink.pkl
   → Failures surfaced per-animal in log box + QMessageBox.warning
   → manifest: psd_status = "drink_mask_applied"

5. PSD Visualizer
   → Re-open to review psds_channel_merged_drink.pkl (Pass 2)
   → Flag all ok → green "→ 9. Finalize" hint appears

6. Finalize page (9. Finalize)
   → Shows pending count, source file, last-finalized timestamp
   → "Finalize ▶" button enabled when all pending = 0
   → Click → copies _drink (or _merged) → psds_final.pkl
```

---

## Key Design Decisions

### `source_combo` + CSV as the "Rerun page done" signal
- `source_combo=None`, no CSV → Rerun page hasn't acted → orange card / Rerun queue
- `source_combo` set, no CSV → upload triggered but not completed → still orange card
- `source_combo` set, CSV on disk → ready for Sleep QC review → blue card / Sleep QC badge

### Re-flagging `needs_rerun` resets the target run
`flag_sleep_qc("needs_rerun", rerun_combo=X)` unconditionally resets any existing
run entry for X to `sleep_qc=None, source_combo=<original>`.

### Drink mask PKL architecture
`psds_channel_merged.pkl` is immutable after `build_final_pkl`. Drink mask reruns
accumulate in `psds_drink.pkl` (replace-per-animal) and the merge lives in
`psds_channel_merged_drink.pkl`. `psds_final.pkl` is only written by the Finalize
button as a copy of `_drink` (or `_merged` if no drink masks were needed) — it is
never computed directly.

### `is_final_view` in PSD Visualizer
`is_final_view = stem in {"psds_channel_merged", "psds_channel_merged_drink"}` — these
are the reviewable files that get `manifest` passed in. `psds_final.pkl` and per-combo
PKLs (`psds_LFC_RSC.pkl` etc.) get `manifest=None` → flag buttons hidden (view-only).

### One-ok invariant
`flag_sleep_qc("ok")` cascade-rejects all siblings. Un-okaying restores them.

### `_poll()` in Sleep QC — no cache eviction during review mode
The 10 s background poll evicts rerun combo data. Evicting mid-review caused the second
animal's rerun line to disappear. Fix: skip eviction when `self._review_mode` is True.

---

## What Didn't Work
- **Standalone "Review Reruns" toggle**: removed — badge is the single entry point.
- **"Reject" as standalone decision**: stranded animals — replaced with "Accept Original".
- **Inline combo picker for "Rerun Again"**: routes through Home queue instead.
- **Separate decision panel above plots**: tried twice — reverted to legend each time.
- **`any(iterdir())` check for download completion**: too loose; replaced with animal-specific glob.
- **Stamping `source_combo` from `spindle_edfs/` scan**: caused item to disappear when EDF placed manually. Fixed by only stamping from `spindle_outputs/`.
- **Review button interactive for `needs_rerun` status**: called `reset_sleep_qc` and erased `rerun_combo` silently. Fixed by disabling the button.
- **Cache eviction in `_poll()` during review mode**: caused second animal's rerun line to disappear.
- **`needs_rerun_pending()` excluding on `source_combo` alone**: caused vanishing items on cancelled upload. Fixed by gating on CSV presence.
- **`rerun_with_drink_masks` overwriting `psds_<COMBO>.pkl` in place**: destructive. Replaced with `psds_drink.pkl` + `psds_channel_merged_drink.pkl` architecture.
- **`rerun_with_drink_masks` globbing all state/drink paths without animal filter**: caused count mismatch when running a subset. Fixed by filtering all path lists to `animal_ids_set`.
- **Linter (`/simplify`) repeatedly strips `offset_path` from `BatchEstimateWorker`**: happens on every `/simplify` run. Restore: `offset_path=None` param in `__init__`, `self.offset_path = offset_path`, `offset_path=self.offset_path` in `batch_estimate` call in `psds.py`.
- **Legend stylesheet extra `}}`**: non-f-string double `}` → Qt parse error. Must be single `}`.
- **`psds_final_drink.pkl` treated as non-final**: `is_final = (stem == "psds_final")` missed it → manifest was None → flag buttons hidden. Fixed to check both stems (now renamed to `_channel_merged` variants).
- **`toolbar.addWidget(btn).setVisible(False)` doesn't work**: calling `setVisible(False)` on the widget added to a `QToolBar` has no effect — the toolbar wraps it in a `QAction`. Must store the return value of `addWidget()` and call `setVisible(False)` on the `QAction` handle instead.
- **Finalize button starts enabled**: `QPushButton` defaults to enabled; `_update_finalize_button()` must be called at the end of `__init__` (after `_build_tool_bar()`) to set the correct initial state.

---

### Completed (this session, branch `refactor/clean-up`)

#### Test fix
- `test_build_final_pkl_warns_and_skips_when_combo_pkl_missing` — test was using same combo for both animals so the PKL existed and no warning fired. Fixed by giving the second animal a different combo (`RSC_LSC`) with no PKL on disk.

#### Research notebook
- `research/psd_from_edfs.ipynb` — tutorial notebook for computing and analysing PSDs from EDF files. Covers: loading EDF with openseize, Welch's method explainer, basic PSD, artifact masking (commutator + SD threshold), state-specific PSDs (wake/NREM/REM), loading `psds_channel_merged.pkl`, group-level plots (mean ± SEM + spaghetti), and band power summary. Uses `ebb` kernel.

---

### Completed (previous session, branch `refactor/clean-up`)

#### Test gaps resolved
- **Gap 3** — regression tests added: step 7 and step 9 correctly show "blocked" when `merged_pkl` is absent even if `psd_status` flags are set in manifest
- **Gap 6** — bug fixed + test added: step 7 was showing "done" when `final_pkl.exists()` but an animal had been re-flagged to `needs_drink_mask`. Fix: `n_needs_drink` computed before step 7; explicit `n_needs_drink > 0` branch fires before the `final_pkl.exists()` check
- **Gap 11** — test added: special PKL names (`psds_channel_merged`, `psds_channel_merged_drink`, `psds_final`) are excluded from `combos_with_pkl`; their presence alone cannot make step 6 show "done"
- **Gap 12** — test added: after `load()` clears orphaned `rejected_by`, the run is actionable (`flag_sleep_qc` works without error)
- **Gap 13** — 2 tests added: `pending_psd_review`, `needs_drink_mask`, `pending_drink_verification` are pairwise disjoint; Finalize pending sum has no double-counting
- **Gap 14** — confirmed by code reading: `showEvent` in `SleepQCGridPage` reloads manifest at line 100; no widget test needed

#### UX clarity fixes (`home.py`, `psds.py`)
- **Step 4 labels**: "N to review" → "N flagged for EDF review", "M pending" → "M not yet assessed"
- **"Ready to Finalize" attention card** (`home.py`): green card appears in Needs Attention zone when `merged_pkl` exists, `final_pkl` absent, all PSDs reviewed, no drink masks pending, at least one ok animal. Navigates to "9. Finalize"
- **CSV pre-flight warning** (`psds.py` `_run_clicked`): before launching `batch_estimate`, logs `⚠ COMBO: no state CSV for ANIMAL — this animal will be skipped` for any ok manifest animal missing a state CSV in `spindle_outputs/<combo>/`
- **Drink mask rebuild guidance** (`psds.py` `_build_final_pkl`): after a successful merge build, if `psds_drink.pkl` exists, logs a note that previously applied drink masks are preserved but may need re-applying if PSD parameters changed

#### P2 items done (by user, outside this session)
- Preprocess and Spindle Write pages: "Next →" navigation hints added post-run

---

### Completed (this session, branch `refactor/spindle_upload` → merged into `refactor/clean-up`)

#### Spindle Upload page — remote folder visibility (`spindle_upload.py`, `sleepyrat.py`)
- `SleepyRatAPI.folder_names(project)` added — returns list of existing folder names for a project
- `remote_folder_edit` changed from `QLineEdit` to editable `QComboBox`; populated with existing remote folders when a project is selected (synchronous call reusing `self._api`)
- Dynamic hint label below the field: "Existing folder — already-uploaded files will be skipped; missing labels will be downloaded." or "New folder — will be created on upload." based on whether current text matches a known folder
- Stale folder list cleared (items cleared, text preserved) on project switch

#### QC toolbar UX (`edf_viewer/eeg_viewer.py`)
- "✓ Mark OK" and "Needs Rerun" `QAction`s made checkable (`setCheckable(True)`)
- `_update_qc_status()` now calls `setChecked` on both actions — button stays visually pressed to match current manifest state, including on initial load
- QC toolbar items pushed to right edge via expanding spacer widget

#### PSD computation page overhaul (`psds.py`)
- **Gate**: `manifest.ready_for_psd()` added to `manifest.py` — returns animals with exactly 1 ok run (any number of total runs). `_validate()` gates "Run PSD Pipeline" on all animals being ready, standard folder existing, and at least one spindle combo with CSVs
- **Single button**: two-step "Compute PSDs" + "Build Channel Merged PKL" replaced with one "Run PSD Pipeline" button; `_on_psd_done()` automatically calls `_build_final_pkl()` after computation
- **Combo table**: checkbox column removed — table is now read-only status display; "Ok Runs" column added (green count from manifest per combo); 4 columns: Combo, CSVs, Ok Runs, PKL Status
- **Channel-merged PKL status line**: below the combo table, "Channel merged PKL: ✓ exists" (green) or "not yet built" (gray); `merged_psd_path` imported at top level
- **Gate label**: explains why button is blocked (e.g. "3 animals not ready — each needs exactly 1 ok run")
- **Summary label**: below the button when gate is met, e.g. "LFC_LSC (5 animals), LFC_RSC (8 animals) → psds_channel_merged.pkl"
- **SWD count warning**: red label when `.mat` file count doesn't match animal count in manifest
- **Imports**: all inline `from ebb_viewer.pipeline...` and `from ebb.process...` imports moved to top of file

#### Home page step 6 gate (`home.py`)
- Step 6 "active" now requires `n_ready_psd == n_animals` (all animals have exactly 1 ok run) instead of `n_ok > 0`
- "attention" shows count of animals not yet ready; "blocked" when no animals have any ok run

#### Sidebar width (`main_window.py`)
- `pagelist.setMinimumHeight(350)` added to make sidebar list taller without expanding to full window height

---

### Completed (latest session, branch `refactor/clean-up`)

#### SWD mask threading through drink mask rerun
- `rerun_with_drink_masks` (`psd_compute.py`) now accepts `swd_dir` parameter; per-combo loop filters `.mat` files to `animals_set` and passes `swd_paths` to `match_paths`
- `DrinkMaskRerunWorker` (`drink_mask.py`) accepts and stores `swd_dir`; passes it to `rerun_with_drink_masks`
- `DrinkMaskPage._apply_clicked` derives `swd_dir = project_root / "swd"` when `params["swd_mode"] == "mask_out"`, logs it, and passes to worker
- SWD mask is now applied consistently in drink mask reruns whenever it was used in the original PSD computation

#### Spindle upload UX fixes (`spindle_upload.py`)
- **Remote folder auto-update on combo switch**: `_on_upload_combo_changed` now updates `remote_folder_edit` when the field contains a previous auto-generated value (starts with `project_root.stem + "_"`), not only when empty — switching combos correctly updates the default remote folder name
- **SleepyRat project list auto-fetch**: added `_projects_fetched` flag; `showEvent` calls `_refresh_projects_clicked()` on first show only — no repeated error dialogs if the server is unreachable

#### Per-animal progress in `batch_estimate` (`psd_compute.py`)
- Added `progress_fn: Optional[callable] = None` parameter
- Sequential path (workers=1): calls `progress_fn(f"  [{i+1}/{n}] {filename}…")` before each file
- Parallel path (workers>1): uses `pool.imap` (via `_star_call`) to call `progress_fn(f"  [{i+1}/{n}] done")` as each worker finishes
- `BatchEstimateWorker` passes `progress_fn=self.progress.emit` so per-file progress appears in the Qt log box
- 3 tests added: sequential calls per-file with counter + filename; parallel calls per-file; `None` default doesn't raise

#### Preprocess and Spindle Write workers now use `ebb.preprocess.edf.batch`
- `_PreprocessWorker.run()` (`preprocess.py`) replaced manual `for` loop with `batch_preprocess(standard, ...)` — uses `Pool` for true parallelism
- `_SpindleWriteWorker.run()` (`spindle.py`) replaced manual `for` loop with `batch_preprocess(spindle, ...)` — same

#### Fork-in-multithread fix — `get_context("spawn")` everywhere
- All `Pool` usages now use `multiprocessing.get_context("spawn")` instead of the default fork Pool: `edf.batch`, `batch_estimate` (imap path), `rerun_with_drink_masks` (starmap path)
- Eliminates `DeprecationWarning: This process is multi-threaded, use of fork() may lead to deadlocks` when running from Qt
- `_star_call(fn_args)` added at module level in `psd_compute.py` — unpacks `(fn, args)` tuple for `pool.imap` (lambdas aren't picklable with spawn)
- 6 tests added: `_star_call` correctness (2); `batch_estimate` uses spawn in parallel, not in sequential (2); `edf.batch` uses spawn in parallel, not in sequential (2)

#### Tests — 138 passing

---

### Completed (this session, branch `refactor/sleep_qc_addition`)

#### Spindle Mask Fraction view in Sleep QC (`sleep_qc_visualizer.py`, `sleep_compute.py`)

**Motivation:** Identify outlier animals based on how much of their sleep is flagged as spindle-masked, without leaving the Sleep QC page.

**New function** `compute_spindle_fractions(state_dir)` in `ebb/process/sleep_compute.py`:
- Reads the `state` column (not `rawstate`) from each spindle output CSV
- `w/n/r` = clean epochs; `1/2/3` = spindle-masked Wake/NREM/REM epochs
- Returns long-form DataFrame: `mouse_id, state, clean_count, spindle_count, total_count, fraction`
- Includes a `Total` row per animal (sum across all states)
- State order: Wake → NREM → REM → Total (ordered categorical)
- Uses `collections.Counter` for epoch counting

**New widget** `SpindleFractionPlot` at the bottom of `sleep_qc_visualizer.py`:
- Box-and-strip chart: IQR box + median + whiskers + jittered scatter per state
- Outliers (IQR × 1.5) labeled with `mouse_id` in red
- Current/highlighted animal shown as a larger blue dot
- Clicking any dot selects it → action strip appears below the chart
- Action strip shows: `Selected: {animal}` label + `Flag for Review` button + `×` dismiss
- `Flag for Review` button shows disabled with explanatory text if the animal is already `needs_review` or `needs_rerun` (rerun status is protected — cannot be overwritten)
- `review_requested` signal → parent flags the animal in the manifest for the current combo

**Integration in `SleepQCGridPage`**:
- `_data_cache` extended from 2-tuple to 3-tuple `(df, df_offset, df_frac)` per combo
- **Sleep / Spindle Mask toggle** right-aligned in the top bar (replaces earlier embedded position); the two buttons act as a mutually exclusive pair
- When Spindle Mask is active: grid hidden, `SpindleFractionPlot` shown; `Highlight:` animal dropdown stays active for cross-referencing; combo selector always enabled
- When returning to Sleep view: `_set_mode(self._mode)` restores the correct controls (no duplicated visibility logic)
- `_on_frac_animal_selected`: updates highlight + reads manifest status for strip button state
- `_on_frac_review_requested`: hard guard against overwriting `needs_rerun`; calls existing `_flag_sleep_qc`
- Strip cleared on combo change and on entering Spindle Mask view

**Key bugs fixed during development:**
- `_refresh_animal_combo` unpacked `(df, _)` from cache; changed to `(df, *_)` for 3-tuples
- `set_data` was resetting the strip on every highlight update (triggered by dot click → signal chain); fixed by removing the reset from `set_data` and calling `clear_selection()` only on explicit resets
- `_btn_review` stayed disabled after flagging one animal; fixed by resetting button state at the start of `_on_dot_clicked`

**Simplify cleanup applied:**
- Manual counting loop → `Counter`
- `mids == current_animal` vectorized comparison instead of list comprehension
- `QFont` created once outside outlier label loop
- `_dismiss` delegates to `clear_selection()` (was duplicating 3 lines)
- `_set_spindle_mask_mode(False)` branch calls `_set_mode(self._mode)` instead of duplicating visibility logic

---

### Completed (sessions, branch `refactor/sleep_qc_addition`)

#### Spindle Mask view — UI polish (`sleep_qc_visualizer.py`)

**Layout and defaults:**
- Spindle Mask widget moved to appear *above* the sleep plot grid in the layout
- "Spindle Mask" button now comes first in the top bar and is **selected by default** (sleep grid hidden on load)
- "Sleep" button comes second; starts unchecked

**Sleep-specific controls hidden in Spindle Mask mode:**
- Group, Animal, and 6AM Start buttons (plus their separators) wrapped in `_sleep_mode_controls` container widget
- Container hidden when Spindle Mask is active, shown when switching to Sleep — top bar is visually clean in spindle mode
- `_sleep_mode_controls` starts hidden to match the default spindle-selected state

**Outlier highlighting in sleep plots:**
- `_get_spindle_outlier_animals(combo) -> set` — runs same IQR × 1.5 rule per state as `SpindleFractionPlot`; requires ≥ 4 animals in a state; returns union across all states
- Group mode: outlier animals' lines drawn at width 2.5 (vs 1.5 for normal)
- Animal mode: if current animal is an outlier for a combo, its line drawn at width 3.5 (vs 2.0)
- Legend tag: outlier animals get `[spindle outlier]` appended inline in the QLabel using HTML `<span>` (red, 9px, italic) — buttons not pushed over

**X-axis fix — 6AM Start mode:**
- `enableAutoSIPrefix(False)` added to the left axis of `SpindleFractionPlot` — prevents pyqtgraph showing values as 400–500 with "× 0.001" label
- `_apply_hour_of_day_ticks`: filters to only multiples of 6 (`int(x) % 6 == 0`) — ticks at 6, 12, 18, 0 instead of every 2-hour bin
- `_prepare_plots` now calls `setTicks(None)` on bottom axes when clearing — restores auto ticks when switching back from offset mode

#### Sleep QC visualizer — further UX changes (`sleep_qc_visualizer.py`)

**Alpha-based highlighting (group mode):**
- Outlier dimming replaced line-width changes: when a user clicks an animal name in the legend, that animal goes to alpha=255, all others dim to alpha=80
- `self._highlighted_animal: str | None` — set via clickable flat QPushButton in legend (bold+underlined when checked); cleared on combo change and `showEvent`
- If no highlight is set, all lines are at full alpha (no automatic outlier dimming on load)
- Outlier tag (`[spindle outlier]`) is a separate `QLabel` next to the button, not part of the button text — prevents OK/Review buttons from shifting right
- `row_l.addStretch(1)` between label area and OK/Review buttons anchors buttons regardless of outlier tag presence

**Group median reference line:**
- `_draw_ref_median(combo)` — median over **all** animals in the combo (not ok-only), dark gray pen (80,80,80), width 2.5, dashed
- `_get_ref_combo()` still picks the reference combo by most-ok-animals count (prefers LFC_RSC)
- **Group mode**: toggled by "Median" button (`self._show_ref_median`, off by default) in `_sleep_mode_controls`
- **Animal/Review mode**: always shown
- Legend label: `"─ ─  Group median, all animals ({ref_combo})"`

**Spindle mask mode first-load fix:**
- `showEvent` calls `_set_spindle_mask_mode(True)` when `btn_spindle.isChecked()` — this was the only way to correctly set visibility, label ("Highlight:"), group controls hidden state, and legend on first show
- `_set_spindle_mask_mode(True)` now also calls `_render_group()` to populate the legend
- `_legend_scroll` hidden in spindle mask mode (legend has no plots to reference)
- `_legend_scroll.setFixedHeight(160)` (was 140)
- `self._highlighted_animal` reset in `showEvent` so stale highlight from a prior visit doesn't persist with no visual indicator

#### `compute_spindle_fractions` redesign (`ebb/process/sleep_compute.py`)

Changed from reading the `state` column (`w/n/r/1/2/3`) to reading `rawstate` + `noise_probs`:
- `rawstate` (always `w/n/r`) determines sleep state
- `noise_probs >= noise_prob_threshold` (default 0.5) determines artifact status
- `noise_prob_threshold: float = 0.5` parameter added — explicit, configurable, consistent with SleepyRat's own threshold
- Raises `ValueError` if `rawstate` **or** `noise_probs` column is missing

**Tests updated** (`tests/ebb/test_sleep_compute.py` — 13 tests):
- `write_state_csv` helper rewritten: now accepts `list[tuple[str, float]]` (rawstate, noise_prob) pairs
- Added `test_threshold_parameter` — boundary at threshold (≥ masks, < is clean), raising threshold reduces count
- Added `test_missing_noise_probs_column_raises`
- Renamed `test_missing_state_column_raises` → `test_missing_rawstate_column_raises`

#### Pre-existing test failures fixed (both were on the base branch)

**`test_drink_mask_integration.py` (4 tests):** `batch_estimate` is imported directly in `psds.py` (`from ebb.process.psd_compute import batch_estimate`), so patching `psd_mod.batch_estimate` had no effect. Fixed all three helpers to patch `ebb_viewer.pages.psds.batch_estimate` instead.

**`test_compute_pipeline_status.py` (4 tests):** Step 6 logic was redesigned — "attention" state removed, replaced by "blocked" when not all animals are `ready_for_psd`. Tests updated:
- Description assertion updated to match new wording
- "attention" → "blocked" for needs_review scenario
- `test_step6_active_when_review_animals_are_rejected` fixed to use a realistic manifest state (A002 with LFC_RSC=ok + LSC_RSC=cascade-rejected) rather than an artificial solo-rejected run that can't occur in practice

**Tests — 151 passing (0 failing)**

#### Annotation mask — `ebb/masking/annotations.py` + EEG viewer

**New function `keyword_mask`** (`ebb/masking/annotations.py`):
- `keyword_mask(path, keywords, pad_sec, size, fs, **kwargs)`
- Reads a Pinnacle annotation file via openseize (same as existing `artifact()`)
- Matches annotations by **case-insensitive substring** (not exact label match like `artifact`)
- Masks `[t, t + pad_sec)` from each matching annotation's start; `pad_sec` is the primary duration control since many annotations only mark event onset
- Times adjusted relative to first annotation, consistent with `artifact()`
- Suitable for use in PSD computation pipeline (takes a file path, returns a bool array)

**`mask_builder.py`:**
- `build_annotation_mask(annotation_path, keywords, pad_sec, n_samples, fs) → Mask`
- `rebuild_annotation_mask(annotation_path, n_samples, fs, meta) → Mask`
- Mask name: `"annotation"`, color: purple `(150, 0, 200, 60)`
- Metadata: `keywords` (comma-separated string) + `pad_sec` (float) → right-click Parameters dialog works for re-editing
- `_annotation_param_specs()`: pad_sec has ParamSpec(min=0, max=3600, units="s"); keywords has desc only (QLineEdit in dialog)

**`eeg_viewer.py`:**
- `self._annotations: list[tuple[float, str]]` and `self._annotation_path` stored on load
- `act_mask_annotations` — disabled until annotations loaded; enabled by `on_load_annotations`
- `AnnotationMaskDialog`: shows unique annotation labels found (read-only preview), keyword QLineEdit, padding QDoubleSpinBox, live "X of Y annotations match" counter (updates on every keystroke)
- `on_mask_from_annotations()`: calls `build_annotation_mask`, adds to `mask_set`, rebuilds dock
- `_on_mask_rebuild()`: handles `name == "annotation"` — calls `rebuild_annotation_mask`
- Menu item under File: "Mask from Annotations…" (below "Load Annotations…")

**What didn't work / key decisions:**
- Initially considered making `keyword_mask` take an already-parsed `list[tuple[float, str]]` — rejected in favour of taking a file path so the function is usable for PSD computation without requiring the viewer's annotation loading infrastructure
- The dialog shows already-loaded annotations (from `self._annotations`) for the live preview, while the actual mask computation reads the file path via openseize — these can differ slightly if openseize's Pinnacle reader parses times differently from `load_annotations`'s custom CSV parser; acceptable for now

---

## Next Steps

### Annotation mask — follow-on work
- Consider exposing `keyword_mask` as a step in the PSD computation pipeline (similar to drink mask): add an "Annotation Mask" page or integrate into the Drink Mask page
- Tests for `keyword_mask` in `tests/ebb/test_annotations.py` — currently untested
- The `pad_sec=0` edge case: currently `max(1, int(0 * fs))` = 1 sample minimum; decide if this is the right behaviour or if 0 should truly mask nothing

### P3 items (from TODO.md)
- **spindle_upload: "Upload, Wait & Download" button issue** — needs reproduction steps before fixing
- **general: Run log / settings provenance** — `run_log.jsonl` append per action
- **psds.py: improve merge log** — log per-combo animal counts after build

### Remaining audit clarity items
- Hint frame timing on multi-combo rerun upload — minor, low priority
- Stale `psds_final.pkl` warning — step 7 shows "attention" when re-flagged, but file on disk isn't explicitly marked stale

### Additional suggestions (from TODO.md)
- EDF format validation on import (`build_from_standard`)
- Keyboard shortcuts in PSD Visualizer (O/D/←/→)
- Manifest backup before destructive ops
- Drink Mask page: highlight missing .npy files in orange

### Testing gaps
- **Gap 4** — `DrinkMaskPage._on_done` partial failure: surfaced in UI, no automated test (widget-level)
- **`keyword_mask`** — no tests yet

---

## Key Files
- `src/ebb_viewer/pages/sleep_qc_visualizer.py` — Sleep QC page (group + animal + review modes + spindle fraction view)
- `src/ebb_viewer/pages/rerun.py` — rerun queue page
- `src/ebb_viewer/pages/spindle_upload.py` — batch upload page + `SleepyRatWorker`
- `src/ebb_viewer/pages/home.py` — pipeline summary + Needs Attention zone (9 steps)
- `src/ebb_viewer/pages/psds.py` — PSD Computation page
- `src/ebb_viewer/pages/drink_mask.py` — Drink Mask page; SWD dir threaded through worker
- `src/ebb_viewer/pages/finalize.py` — Finalize page
- `src/ebb_viewer/pages/psd_visualizer.py` — PSD Visualizer
- `src/ebb_viewer/pages/preprocess.py` — Preprocess page
- `src/ebb_viewer/pages/spindle.py` — Spindle Write page
- `src/ebb_viewer/widgets/psd_graph_widget.py` — PSD grid + flag buttons
- `src/ebb_viewer/pipeline/manifest.py` — `Manifest` / `ManifestEntry` / `RunEntry`
- `src/ebb_viewer/main_window.py` — sidebar + page navigation + badge refresh + poll timer
- `src/ebb_viewer/edf_viewer/eeg_viewer.py` — EEG viewer; `AnnotationMaskDialog`; annotation mask wiring
- `src/ebb_viewer/edf_viewer/mask_builder.py` — mask build/rebuild functions incl. `build_annotation_mask`, `rebuild_annotation_mask`
- `src/ebb/masking/annotations.py` — `artifact()` + new `keyword_mask()`
- `src/ebb/process/psd_compute.py` — `batch_estimate`, `rerun_with_drink_masks`, `build_final_pkl`, `_star_call`
- `src/ebb/process/sleep_compute.py` — `compute_spindle_fractions` (rawstate + noise_probs)
- `src/ebb/preprocess/edf.py` — `batch` (spawn context)
- `tests/ebb_viewer/test_manifest.py` — 84 manifest tests
- `tests/ebb/test_drink_mask_integration.py` — drink mask + batch_estimate tests (patching fixed)
- `tests/ebb/test_sleep_compute.py` — 13 tests for `compute_spindle_fractions`
- `tests/ebb/test_preprocess_batch.py` — 4 batch preprocess tests
- `tests/ebb_viewer/test_compute_pipeline_status.py` — pipeline status tests (step 6 logic updated)
- `research/psd_from_edfs.ipynb` — tutorial notebook

---

### Completed (this session, branch `refactor/window_compat`)

#### Annotation editing with duration in EEG viewer

**New file `edf_viewer/annotations_dock.py`:**
- `EventEditDialog(QDialog)` — t0/t1 QDoubleSpinBox, label QLineEdit, red Delete button
- `AnnotationsDock(QDockWidget)` — table with Start/End/Label columns; signals: `annotation_edited`, `annotation_deleted`, `annotation_selected`; `_rebuilding` guard to suppress spurious selection signals; `rebuild()` sorts by t0; `select_annotation()` uses `==` fallback (PyQt6 does NOT preserve object identity through QVariant round-trips — `is` always fails)

**`edf_viewer/trace_view.py`:**
- `EventViewBox(TimeClickViewBox)` — right-drag creates a preview `LinearRegionItem`; `regionCreated = pyqtSignal(float, float)` emitted on release if drag > 1e-4 s
- `_annotations` changed from `list[tuple[float, str]]` to `list[dict]` with `{t0, t1, label}`
- `set_annotations` draws `LinearRegionItem` fills for non-zero-duration events + `InfiniteLine` with label on ALL channels; all items have `setAcceptedMouseButtons(NoButton)` to not absorb clicks
- `add_annotation`, `edit_annotation`, `delete_annotation`, `annotations` property
- `jump_to_next/prev_annotation` emits `annotation_jumped(ev)` after jumping
- Right-click-in-trace code was stripped entirely (multiple approaches failed against pyqtgraph event routing on all platforms)

**`edf_viewer/file_openers.py`:**
- `load_annotations` updated to return `(list[dict], base_dt, header_lines)` — parses full Pinnacle format (Start Time/End Time → duration) or simple format (t1 = t0)
- `save_annotations(path, annotations, base_dt, header_lines)` — writes Pinnacle TXT
- `pick_save_annotations_path(parent, source_path)` — default `{stem}_edited.txt`

**`edf_viewer/eeg_viewer.py`:**
- `AnnotationsDock` instantiated, added to right dock area, hidden until first annotation load
- `_on_event_region_created`, `_on_annotation_edited`, `_on_annotation_deleted`, `_on_annotation_selected`, `_on_annotation_jumped` handlers
- `[`/`]` shortcuts jump AND select the corresponding dock row
- `act_save_annotations` in File menu

**What didn't work:**
- Right-click-in-trace (pyqtgraph `mouseClickEvent`, `mouseDoubleClickEvent`, viewport event filter, custom `PlotWidget` subclass) — all failed; editing is dock-only

#### Windows/macOS rendering fixes (branch `refactor/window_compat`)

**`edf_viewer/mask_builder.py`:** all mask alphas increased from 60 → 80 (compositing appears more washed-out on Windows)

**`sleep_qc_visualizer.py` — legend row backgrounds:**
- Previous attempts (QWidget→QFrame, stylesheet `background-color`, QPalette+autoFillBackground, `setParent(None)` vs `deleteLater()`, `legend_container.update()`) all failed on Windows
- **Working fix:** `_LegendRow(QFrame)` subclass overrides `paintEvent` to call `QPainter.fillRect` directly — bypasses the style engine entirely, guaranteed to paint on every repaint

**`sleep_qc_visualizer.py` — button checked state:**
- `_LEGEND_BTN_STYLE` added as class constant: `background-color: transparent` + explicit `:checked { background-color: rgba(0,0,0,0.18); font-weight: bold; }` — applied to all OK/Review legend buttons
- On Windows/macOS, checkable QPushButton shows no visual difference without explicit `:checked` styling

**What didn't work for legend backgrounds (do not retry):**
- `QFrame#legendRow { background-color: ... }` stylesheet — ignored after dynamic rebuild on Windows
- `QPalette + setAutoFillBackground(True)` — initial render works, but not after legend rebuild
- `hide()` + `deleteLater()` + `legend_container.update()` — did not trigger repaints of newly-added widgets
- `setParent(None)` — same problem

---

## Next Steps

### Windows compat — remaining items to check
- Confirm `_LegendRow` fix works (legend colors update after clicking OK/Review on Windows)
- Check any other pages for similar dynamic-widget repaint issues

### Annotation mask follow-on
- Tests for `keyword_mask` in `tests/ebb/test_annotations.py` — currently untested
- Consider integrating into PSD pipeline (Drink Mask page or separate page)

### P3 items (from TODO.md)
- **spindle_upload: "Upload, Wait & Download" button issue** — needs reproduction steps
- **general: Run log / settings provenance** — `run_log.jsonl` append per action
- **psds.py: improve merge log** — log per-combo animal counts after build

### Testing gaps
- **Gap 4** — `DrinkMaskPage._on_done` partial failure: surfaced in UI, no automated test
- **`keyword_mask`** — no tests yet

---

## Key Files
- `src/ebb_viewer/pages/sleep_qc_visualizer.py` — Sleep QC page (group + animal + review modes + spindle fraction view + `_LegendRow`)
- `src/ebb_viewer/pages/rerun.py` — rerun queue page
- `src/ebb_viewer/pages/spindle_upload.py` — batch upload page + `SleepyRatWorker`
- `src/ebb_viewer/pages/home.py` — pipeline summary + Needs Attention zone (9 steps)
- `src/ebb_viewer/pages/psds.py` — PSD Computation page
- `src/ebb_viewer/pages/drink_mask.py` — Drink Mask page
- `src/ebb_viewer/pages/finalize.py` — Finalize page
- `src/ebb_viewer/pages/psd_visualizer.py` — PSD Visualizer
- `src/ebb_viewer/pipeline/manifest.py` — `Manifest` / `ManifestEntry` / `RunEntry`
- `src/ebb_viewer/main_window.py` — sidebar + page navigation + badge refresh
- `src/ebb_viewer/edf_viewer/eeg_viewer.py` — EEG viewer; annotation dock wiring; annotation mask
- `src/ebb_viewer/edf_viewer/annotations_dock.py` — `AnnotationsDock` + `EventEditDialog`
- `src/ebb_viewer/edf_viewer/trace_view.py` — trace rendering; `EventViewBox`; annotation display
- `src/ebb_viewer/edf_viewer/file_openers.py` — load/save annotations (Pinnacle TXT format)
- `src/ebb_viewer/edf_viewer/mask_builder.py` — mask build/rebuild functions
- `src/ebb/masking/annotations.py` — `artifact()` + `keyword_mask()`
- `src/ebb/process/psd_compute.py` — `batch_estimate`, `rerun_with_drink_masks`, `build_final_pkl`
- `src/ebb/process/sleep_compute.py` — `compute_spindle_fractions` (rawstate + noise_probs)
- `tests/ebb_viewer/test_manifest.py` — 84 manifest tests
- `tests/ebb/test_drink_mask_integration.py` — drink mask + batch_estimate tests
- `tests/ebb/test_sleep_compute.py` — 13 tests
- `research/psd_from_edfs.ipynb` — tutorial notebook

## Environment
- Conda env: `ebb-dev` (`source ~/miniconda3/etc/profile.d/conda.sh && conda activate ebb-dev`)
- Jupyter kernel: `ebb` (registered in `~/.local/share/jupyter/kernels/ebb`)
- Run tests: `QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH="$CONDA_PREFIX/lib" python -m pytest` (151 passing)
- Active branch: `refactor/window_compat`; base: `refactor/sleep_qc_addition` → `refactor/clean-up`
