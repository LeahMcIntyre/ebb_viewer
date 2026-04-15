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

### Completed (previous sessions, branch `refactor/clean-up`)

#### Stage clarity fixes (all stages 1–9)
- Per-file log output (✓/✗ per file) for Preprocess and Spindle Write workers
- Preprocess: confirmation dialog before overwriting existing `standard/` EDFs
- Spindle Write: explicit "folder already exists" dialog
- Stale manifest auto-refresh in SleepQCGridPage `_poll`
- "Build Channel Merged PKL" gated correctly; Step 1/Step 2 labels
- "↺ Reset" toolbar button in PSD Visualizer
- Home: "9. Finalize" step, "Ready to Finalize" attention card
- Research notebook `research/psd_from_edfs.ipynb`

#### Tests — 114 passing

---

### Completed (branch `feature/save_psd_runs` → merged into `feature/psd_compute_hours`)

#### Named PSD runs architecture (all of `project_save_psd_compute_plan.md`)
- Each run lives at `psd/<run_name>/`: `psd_params.json`, `psds_<COMBO>.pkl`, `psds_channel_merged.pkl`, `psds_drink.pkl`, `psds_channel_merged_drink.pkl`, `psds_final.pkl`
- `pipeline/psd_params.py`: `save(root, run_name, params)`, `load(root, run_name)`, `list_runs(root)`, `valid_run_name(name)`, legacy flat-layout migration to `psd/default/`
- `pipeline/manifest.py`: `RunEntry.psd_status` is now `dict[run_name → status]`; all PSD methods gain `run_name` arg; migration shim in `_run_from_dict`; drink_mask cleared on "ok" only if no other run still has `drink_mask_applied`
- `ebb/process/psd_compute.py`: `build_final_pkl(root, manifest, run_name)`, `build_run_final_pkl(root, run_name)`, `rerun_with_drink_masks` gains `run_name`
- `pages/psds.py`: run name field, existing-run warning label, combo table shows per-run PKL status
- All pages (psd_visualizer, drink_mask, finalize) have run selectors

#### Hour window masking in drink mask rerun (bug fix)
- `rerun_with_drink_masks` was not stripping `hw_enabled` or extracting `hour_windows`/`selected_days` from kwargs — `hw_enabled` leaked into `estimators.psd()` as an unknown kwarg
- Fixed to mirror `batch_estimate`: pop `hw_enabled`, extract `hour_windows`/`selected_days`, pass explicitly to `partial(estimate_psd, hour_windows=..., selected_days=..., **kwargs)`

#### Finalize page rewrite (`pages/finalize.py`)
- Old page was broken (referenced non-existent `final_psd_path`, pre-run-name API)
- Rewritten as a **Run Summary** page: scrollable list of per-run cards
- Each card shows: pending counts (or ✓ all reviewed), source PKL (prefers `_drink` variant), `psds_final.pkl` mtime, "Settings…" button, "Finalize" / "Re-finalize" button
- "Settings…" opens `_RunSettingsDialog`: read-only display of all params (general, hour windows, SWD, drink mask animal list from `psds_drink.pkl`, annotation mask)
- Drink mask status reads from `psds_drink.pkl` (not manifest) — manifest `drink_mask` field is cleared once animals are flagged "ok", so the pkl is the only persistent record
- Card labels have `QLabel { border: none; background: transparent; }` to prevent frame border bleed
- Wired into `main_window.py` as stack index 9, sidebar "9. Finalize"

#### PSD Visualizer done-hint
- Replaced "Finalize Run" button with "→ Finalize" navigation button

#### Overwrite guard in PSD Computation (`pages/psds.py`)
- Confirmation dialog when run name already exists in `list_runs()`; default button = Cancel
- On confirmation, clears `psd_status[run_name]` from all manifest entries before computation

#### Sidebar badge cleanup (`main_window.py`)
- Removed PSD Computation badge — no longer meaningful with named runs that can be rerun freely

#### Tests — 201 passing
- 7 new SWD sample-position tests: boundary precision, multiple intervals, adjacent merge, pad_sec, clip at start/end, 1D single-interval shape
- 7 new hour window sample-position tests: inside/outside, boundary precision, non-midnight start, overnight wrap, used_windows coverage, no bleed between windows, selected_days exact positions

---

### Completed (most recent session, branch `feature/psd_compute_hours`)

#### Hint banner fix (`pages/psds.py`, `pages/drink_mask.py`)
- The green "run complete" hint banners on PSD Computation and Drink Mask pages were
  persisting when a new run was started, suggesting the pipeline was done when it wasn't
- Fixed by adding `self._hint_frame.setVisible(False)` at the start of `_run_pipeline_clicked`
  (psds.py) and `_apply_clicked` (drink_mask.py), just before `self._computing = True`
- The PSD Visualizer's done-hint already handled this correctly via `_check_done_hint()`

#### Verified previously flagged issues are resolved
- Home page step 9 logic: already uses `list_runs()` — no flat `psd/psds_final.pkl` reference
- Home page drink mask attention cards: `all_needs_drink_mask()` already iterates all runs correctly

#### Tests — 201 passing (no change)

---

## Current Branch State

**Active branch**: `feature/psd_compute_hours`  
**All 201 tests passing**

File layout for a named run:
```
psd/
  <run_name>/
    psd_params.json           ← saved on compute
    psds_<COMBO>.pkl          ← per-combo raw results
    psds_channel_merged.pkl   ← built by build_final_pkl (immutable after build)
    psds_drink.pkl            ← drink-mask reruns (accumulates; replace-per-animal)
    psds_channel_merged_drink.pkl  ← merged with drink overrides
    psds_final.pkl            ← written only by Finalize page
```

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

4. Sleep QC page  (sidebar shows "4. Sleep QC (1)")
   → showEvent evicts stale cache, badge appears: "● 1 rerun ready for review →"
   → click badge → review mode, dropdown filtered to pending animals
   → plots: solid line (original), dashed line (rerun), group mean reference
   → legend: [✓ Accept LFC_RSC] [✓ Accept RSC]  [Review]
   → decide → auto-advance or "Review Complete" → exit review mode

5. If "Review" chosen:
   → rerun combo flagged needs_review → Home queue → repeat from step 2
```

## Full PSD + Drink Mask Flow (as implemented)

```
1. PSD Computation page (6. PSD Computation)
   → Enter run name (warning shown if name already exists → confirm overwrites)
   → Select combos, set params, configure hour windows/masking
   → "Run PSD Pipeline" → per-combo psds_<COMBO>.pkl saved to psd/<run_name>/
   → "Build Channel Merged PKL" → psds_channel_merged.pkl

2. PSD Visualizer (7. PSD Visualizer)
   → Select run, auto-selects psds_channel_merged_drink.pkl if present, else psds_channel_merged.pkl
   → Flag buttons: ✓ OK / Drink Mask / ↺ Reset (only for merged PKLs)
   → "Drink Mask" → manifest psd_status[run_name] = "needs_drink_mask"
   → Green hint "→ Finalize" appears when all pending counts = 0

3. Drink Mask page (8. Drink Mask)
   → Select run → loads psd_params.json read-only
   → Table: animals flagged needs_drink_mask + .npy file presence
   → "Apply Drink Masks" → rerun_with_drink_masks (with hour windows applied)
   → Updates psds_drink.pkl + regenerates psds_channel_merged_drink.pkl
   → manifest psd_status[run_name] = "drink_mask_applied"

4. PSD Visualizer Pass 2
   → Review psds_channel_merged_drink.pkl
   → Flag all ok → green "→ Finalize" hint

5. Finalize page (9. Finalize)
   → Per-run cards: pending status, source PKL, psds_final.pkl mtime
   → "Settings…" → read-only view of all params for that run
   → "Finalize" (enabled when pending = 0) → writes psds_final.pkl
```

---

## Key Design Decisions

### Named runs
`psd_status` in `RunEntry` is a `dict[run_name → status]` — each PSD run has
independent review state. `drink_mask` is shared across runs (same .npy file).
`drink_mask` is cleared from manifest when flagged "ok" with no other runs still
at "drink_mask_applied" — use `psds_drink.pkl` existence to detect drink mask
usage in the Finalize settings dialog.

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
button as a copy of `_drink` (or `_merged` if no drink masks were needed).

### `is_final_view` in PSD Visualizer
`is_final_view = stem in {"psds_channel_merged", "psds_channel_merged_drink"}` — these
are the reviewable files that get `manifest` passed in. Other PKLs get `manifest=None`
→ flag buttons hidden (view-only).

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
- **`rerun_with_drink_masks` not handling hour windows**: `hw_enabled` leaked into `estimators.psd()` as unknown kwarg; `hour_windows`/`selected_days` not extracted. Fixed to mirror `batch_estimate`.
- **Drink mask count in Settings dialog reading manifest `drink_mask` field**: field is cleared once animals are flagged "ok", so it always showed "No drink masks on file" for completed runs. Fixed to read `psds_drink.pkl` directly.
- **QLabel border bleed in Finalize run cards**: `QFrame` stylesheet applied border to child `QLabel` widgets. Fixed with `QLabel { border: none; background: transparent; }` in card stylesheet.
- **Linter (`/simplify`) repeatedly strips `offset_path` from `BatchEstimateWorker`**: happens on every `/simplify` run. Restore: `offset_path=None` param in `__init__`, `self.offset_path = offset_path`, `offset_path=self.offset_path` in `batch_estimate` call in `psds.py`.
- **Legend stylesheet extra `}}`**: non-f-string double `}` → Qt parse error. Must be single `}`.
- **`toolbar.addWidget(btn).setVisible(False)` doesn't work**: must store the `QAction` return value and call `setVisible(False)` on that.
- **Hint banners persisting across new runs**: green "run complete" banners on PSD Computation and Drink Mask pages stayed visible when a new run started. Fixed by hiding `_hint_frame` at the top of `_run_pipeline_clicked` / `_apply_clicked`.

---

## Next Steps

The `feature/psd_compute_hours` branch is feature-complete and ready to merge to `dev`.
Only one remaining step before merging:

1. **End-to-end test with real data** — run a full pipeline from scratch with a new run name,
   plus a re-run with an existing name, to confirm the overwrite guard and manifest reset
   work in practice. Also verify the hint banners hide/show correctly across runs.
2. **Merge to `dev`** once testing passes.
