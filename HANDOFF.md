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

### Completed (latest session, branch `refactor/clean-up`)

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

## Next Steps

### P3 items (from TODO.md)
- **spindle_upload: "Upload, Wait & Download" button issue** — needs reproduction steps before fixing
- **spindle_upload: Project names propagate on showEvent** — `_on_combo_changed` may not fire on `showEvent`; investigable by reading the code
- **psd: SWD masks** — scientific decision on TS required
- **general: Run log / settings provenance** — `run_log.jsonl` append per action

### Remaining audit clarity items
- Per-animal progress in batch PSD compute — currently silent for large batches; nice-to-have
- Hint frame timing on multi-combo rerun upload — minor, low priority
- Stale `psds_final.pkl` warning — step 7 now correctly shows "attention" when re-flagged, but the file on disk isn't explicitly marked stale

### Additional suggestions (from TODO.md)
- EDF format validation on import (`build_from_standard`)
- Keyboard shortcuts in PSD Visualizer (O/D/←/→)
- Manifest backup before destructive ops
- Drink Mask page: highlight missing .npy files in orange

### Testing gaps status (from PIPELINE_AUDIT.md)

**All high/medium gaps resolved.** Only one open:
- **Gap 4** — `DrinkMaskPage._on_done` partial failure: error is now surfaced in UI, but no automated test exists (widget-level, harder to test).

---

## Key Files
- `src/ebb_viewer/pages/sleep_qc_visualizer.py` — Sleep QC page (group + animal + review modes)
- `src/ebb_viewer/pages/rerun.py` — rerun queue page
- `src/ebb_viewer/pages/spindle_upload.py` — batch upload page + `SleepyRatWorker`
- `src/ebb_viewer/pages/home.py` — pipeline summary + Needs Attention zone (9 steps)
- `src/ebb_viewer/pages/psds.py` — PSD Computation page (Step 1 / Step 2 flow + CSV pre-flight)
- `src/ebb_viewer/pages/drink_mask.py` — Drink Mask page (error surfacing in `_on_done`)
- `src/ebb_viewer/pages/finalize.py` — Finalize page (9. Finalize sidebar item)
- `src/ebb_viewer/pages/psd_visualizer.py` — PSD Visualizer (↺ Reset button, final-file gate)
- `src/ebb_viewer/widgets/psd_graph_widget.py` — PSD grid + flag buttons (OK / Drink Mask / ↺ Reset)
- `src/ebb_viewer/pipeline/manifest.py` — `Manifest` / `ManifestEntry` / `RunEntry`
- `src/ebb_viewer/main_window.py` — sidebar + page navigation + badge refresh + poll timer
- `src/ebb/process/psd_compute.py` — `batch_estimate`, `rerun_with_drink_masks`, `build_final_pkl`
- `tests/ebb_viewer/test_manifest.py` — 84 manifest tests
- `tests/ebb/test_drink_mask_integration.py` — 30 drink mask integration tests
- `tests/ebb_viewer/test_compute_pipeline_status.py` — 21 pipeline status tests (steps 6–9)
- `research/psd_from_edfs.ipynb` — tutorial notebook: load EDF → mask artifacts → state PSDs → group plots from merged PKL

## Environment
- Conda env: `ebb-dev` (`source ~/miniconda3/etc/profile.d/conda.sh && conda activate ebb-dev`)
- Jupyter kernel: `ebb` (registered in `~/.local/share/jupyter/kernels/ebb`)
- Run tests: `QT_QPA_PLATFORM=offscreen python -m pytest` (129 passing, 13 warnings)
- Branch: `refactor/clean-up`
