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
- `psds_final.pkl` — built by `build_final_pkl`, **never modified**
- `psds_drink.pkl` — accumulates drink-mask reruns across sessions; per-animal replace
- `psds_final_drink.pkl` — regenerated on every drink mask rerun: `psds_final.pkl` minus drink animals + all of `psds_drink.pkl`

**`rerun_with_drink_masks`** (`psd_compute.py`): validates `source_combo` in `psds_final.pkl` against manifest ok combo before computing. Stamps `source_combo` on every `psds_drink.pkl` record.

#### Tests
- `tests/ebb_viewer/test_manifest.py` — 79 tests
- `tests/ebb/test_drink_mask_integration.py` — 30 tests

---

### Completed (this session, branch `refactor/clean-up`)

#### TODO list reviewed and reorganized
- Rewrote `TODO.md` with P0/P1/P2/P3 priority tiers and rationale for each item
- Removed already-resolved items (auto-sync, clean PSD compute, etc.)

#### P0 completed
- **PSD Visualizer drink mask banner** (`psd_graph_widget.py:159`): updated text from
  "go to PSD Computation → Apply Drink Masks" (button no longer exists) to
  "go to **8. Drink Mask** page"

#### P1 completed — all 5 items
- **PSD Visualizer OK/Drink Mask buttons** (`psd_graph_widget.py`): made `setCheckable(True)`; `_update_flag_status()` now calls `setChecked()` inside each if/elif branch so button state and label state are always co-located
- **Preprocess: computed Hz label** (`preprocess.py`): dynamic `"→ 250 Hz output"` label beside downsample spinbox, updates live on either spinbox change
- **Preprocess: EDF filename format label** (`preprocess.py`): info label in Folder Selection group: `"ℹ EDF files must be named: AnimalID_anything_YYYY_MM_DD_HH_MM_SS.edf"`
- **Home: PSD step gate** (`home.py` `compute_pipeline_status`): step 6 now shows "attention" with `"⚠ N animals still need Sleep QC review"` when `n_review > 0` and `n_ok > 0`, instead of "active"
- **Home: filter rerun combo dropdown** (`home.py` `_make_review_card`): excludes already-ok combos; shows status suffix for existing non-ok runs (e.g. `"LFC_RSC (Rerun Queued)"`); uses `currentData()` for actual combo string

#### `/simplify` fixes applied after P1
- `_SLEEP_QC_LABEL` — added `"needs_rerun": "Rerun Queued"` (was missing; raw snake_case showed in dropdown)
- `not in ("ok", "rejected")` — simplified to `not in (None, "rejected")` since `"ok"` already filtered by `ok_combos`
- `standard_dir.glob("*.edf")` — was called twice per refresh; now stored in `standard_edfs` list once
- `setChecked` in `_update_flag_status` — moved inside each if/elif branch (was unconditional before the block)
- Lambda pattern — `lambda _checked=False:` → `lambda checked:` on flag button connects

#### P2 partial — 2 of 6 items completed
- **Home: drink mask cards + pipeline step 8** (`home.py`):
  - Added "8. Drink Mask" to `_STEP_LABELS` / `_STEP_PAGE_NAMES`
  - `compute_pipeline_status` now computes step 8: blocked/attention/done based on `needs_drink_mask` and `drink_mask_applied` counts
  - `_refresh_attention_zone` now includes `manifest.needs_drink_mask()` items
  - New `_make_drink_mask_card` method: lavender `#f0e6ff` card with `"→ Drink Mask page"` nav button
  - "All caught up ✓" now requires no pending drink mask items too
- **PSD Visualizer: prominent file label + flag button gate** (`psd_visualizer.py`):
  - **Bug fix**: `psds_final_drink.pkl` was treated as non-final (`is_final = False`) → manifest was None → flag buttons hidden. Fixed: `is_final = stem in {"psds_final", "psds_final_drink"}`
  - **`run_channels`** correctly set to `None` for both final stems (was `"final_drink"` for `psds_final_drink.pkl`)
  - Bold `"Reviewing: {filename}"` label appears above plot area when "Plot PSDs" is clicked
- **Video offset label** — verified already gone from `PSDPage` UI; removed from TODO

#### P2 partial — preprocess EDF file count / duration display (`preprocess.py`)
- `_scan_edfs()`: globs `*.edf` in project root, reads headers with `edf_io.Reader` context manager, computes min/max durations
- `_scan_label` QLabel in Folder Selection group shows `"Found N files · all 72h 00m"` or `"Found N files · 48h 00m – 72h 00m"` for mixed durations
- Live orange warning when any file is shorter than the current trim_to minimum — updates reactively via `trim_to.changed` signal
- Scan is cached per-session (`_durations_hrs: list | None` sentinel in `__init__`); guarded in `showEvent`
- `_fmt_hrs()` module helper, `_SAME_DURATION_THRESHOLD = 1/60`, `_STYLE_NORMAL/_STYLE_WARNING/_STYLE_ERROR` class constants

#### Tests
- `tests/ebb_viewer/test_compute_pipeline_status.py` — 10 new tests (6 for step 6 PSD gate, 4 for step 8 drink mask)
- **Total: 109 passing**

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
   → Select combos, set params → Compute PSDs
   → Clean compute: no drink masks applied
   → params saved to psd/psd_params.json
   → Each PKL record has {"params": {...}} embedded for provenance

2. Build Final PKL → psds_final.pkl  (one entry per animal from their ok combo)

3. PSD Visualizer (7. PSD Visualizer)
   → Auto-selects psds_final_drink.pkl if present, else psds_final.pkl
   → Bold "Reviewing: {filename}" label shown above plot
   → Flag buttons (✓ OK / Drink Mask) only active for final PKLs — hidden for intermediate per-combo files
   → "Drink Mask" sets psd_status = "needs_drink_mask" in manifest

4. Home page — Needs Attention zone
   → Lavender card per flagged animal: "→ Drink Mask page" button

5. Drink Mask page (8. Drink Mask)  (sidebar badge shows count)
   → Loads psd/psd_params.json as read-only
   → Table: animals flagged needs_drink_mask + mask file presence (✓/✗)
   → "Apply Drink Masks (N ready)" — gated on psd_params.json + .npy present
     a. Calls rerun_with_drink_masks: validates source_combo vs psds_final.pkl
     b. Updates psds_drink.pkl (accumulates across sessions, replace-per-animal)
     c. Regenerates psds_final_drink.pkl = psds_final.pkl base + psds_drink.pkl
   → manifest: psd_status = "drink_mask_applied"

6. PSD Visualizer
   → Re-open to review psds_final_drink.pkl
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
`psds_final.pkl` is immutable after `build_final_pkl`. Drink mask reruns accumulate
in `psds_drink.pkl` (replace-per-animal) and the merge lives in `psds_final_drink.pkl`.

### `is_final` in PSD Visualizer
`is_final = stem in {"psds_final", "psds_final_drink"}` — both are valid files for
manifest flagging. Intermediate per-combo PKLs (`psds_LFC_RSC.pkl` etc.) get
`manifest=None` → flag buttons hidden.

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
- **`rerun_with_drink_masks` overwriting `psds_<COMBO>.pkl` in place**: destructive. Replaced with `psds_drink.pkl` + `psds_final_drink.pkl` architecture.
- **`rerun_with_drink_masks` globbing all state/drink paths without animal filter**: caused count mismatch when running a subset. Fixed by filtering all path lists to `animal_ids_set`.
- **Linter (`/simplify`) repeatedly strips `offset_path` from `BatchEstimateWorker`**: happens on every `/simplify` run. Restore: `offset_path=None` param in `__init__`, `self.offset_path = offset_path`, `offset_path=self.offset_path` in `batch_estimate` call in `psds.py`.
- **Legend stylesheet extra `}}`**: non-f-string double `}` → Qt parse error. Must be single `}`.
- **`psds_final_drink.pkl` treated as non-final**: `is_final = (stem == "psds_final")` missed it → manifest was None → flag buttons hidden. Fixed to `stem in {"psds_final", "psds_final_drink"}`.

---

## Next Steps (see TODO.md for full list)

### P2 — remaining items
1. **home: Evaluate removing double-click rerun combo from pipeline summary table** — the Needs Attention yellow card now handles this; the table double-click may be redundant
2. **preprocess / spindle write: "Next →" navigation hint after completion** — same pattern as Rerun page; add `navigate_to` signal + green hint frame; wire in `main_window.py`
3. **psd: Make compute → merge two-step flow clearer** — label "Step 1: Compute per-combo PSDs" / "Step 2: Build Final PKL" with separator in `psds.py`

### P3 — needs more context
- **spindle_upload: investigate "Upload, Wait & Download" issue** — need to reproduce and document the failure conditions
- **spindle_upload: project names propagate on page shown** — `showEvent` may not trigger `_on_combo_changed`
- **psd: SWD masks** — scientific decision on TS required before implementation

### Additional suggestions (not yet started)
- EDF format validation on import (`build_from_standard`)
- Keyboard shortcuts in PSD Visualizer (O/D/←/→)
- Manifest backup before destructive ops
- Drink Mask page: highlight missing .npy files in orange

---

## Key Files
- `src/ebb_viewer/pages/sleep_qc_visualizer.py` — Sleep QC page (group + animal + review modes)
- `src/ebb_viewer/pages/rerun.py` — rerun queue page
- `src/ebb_viewer/pages/spindle_upload.py` — batch upload page + `SleepyRatWorker`
- `src/ebb_viewer/pages/home.py` — pipeline summary + Needs Attention zone (8 steps, drink mask cards)
- `src/ebb_viewer/pages/psds.py` — PSD Computation page
- `src/ebb_viewer/pages/drink_mask.py` — Drink Mask page
- `src/ebb_viewer/pipeline/psd_params.py` — save/load helpers for psd/psd_params.json
- `src/ebb_viewer/pages/psd_visualizer.py` — PSD Visualizer (prominent file label, final-file gate for flag buttons)
- `src/ebb_viewer/widgets/psd_graph_widget.py` — PSD grid + checkable flag buttons + drink mask banner
- `src/ebb_viewer/pipeline/manifest.py` — `Manifest` / `ManifestEntry` / `RunEntry`
- `src/ebb_viewer/main_window.py` — sidebar + page navigation + badge refresh + poll timer
- `src/ebb/process/psd_compute.py` — `batch_estimate`, `rerun_with_drink_masks`, `build_final_pkl`
- `src/ebb/io/sleepyrat.py` — `SleepyRatAPI` (low-level HTTP)
- `tests/ebb_viewer/test_manifest.py` — 79 manifest tests
- `tests/ebb/test_drink_mask_integration.py` — 30 drink mask integration tests
- `tests/ebb_viewer/test_compute_pipeline_status.py` — 10 pipeline status tests (new this session)

## Environment
- Conda env: `ebb-dev` (`source ~/miniconda3/etc/profile.d/conda.sh && conda activate ebb-dev`)
- Run tests: `QT_QPA_PLATFORM=offscreen pytest` (109 passing)
- Branch: `refactor/clean-up`
