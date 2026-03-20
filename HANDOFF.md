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

### Completed (current session, branch `refactor/clean-up`)

#### Drink mask UX redesign (`pages/psds.py`, `psd_compute.py`, `widgets/psd_graph_widget.py`)

**Display fix**: `lbl_drink_dir` QLineEdit now shows the path only; count moved to a
separate `_lbl_drink_count` QLabel badge (green `✓ N masks` / orange `! no .npy files`).

**Drink Mask Rerun groupbox** replaces the awkward three-button row:
- Main buttons reduced to `[ Compute PSDs ]  [ Build Final PKL ]`
- New "Drink Mask Rerun" QGroupBox always visible below buttons
- Status line: `"N animal(s) flagged — N ready, N missing mask file"` with per-animal table
  showing Animal | Status | Mask File (✓ found / ✗ missing per row)
- Button label is dynamic: `"Apply Drink Masks (N ready)"` or
  `"Apply Drink Masks (place .npy files to enable)"`

**BatchEstimateWorker** pre-flight log: before computing, emits which animals have drink
mask files and which don't.

**PSD Visualizer guidance**: after clicking "Drink Mask" in `psd_graph_widget.py`,
a yellow banner appears below the toolbar: *"Place `drink_masks/<animal_id>.npy`… then
go to PSD Computation → Apply Drink Masks"*. Hidden for all other statuses.

**Removed** `print("New PSD Window")` debug statement from `psd_graph_widget.py`.

#### New drink mask PKL architecture (`psd_compute.py`, `pages/psds.py`)

**Old design** (removed): `rerun_with_drink_masks` rewrote `psds_<COMBO>.pkl` in place.

**New design**:
- `psds_final.pkl` — built by `build_final_pkl`, **never modified** again
- `psds_drink.pkl` — accumulates all drink-mask reruns across sessions; per-animal replace
- `psds_final_drink.pkl` — regenerated on every drink mask rerun as:
  `psds_final.pkl` (base, minus drink animals) + all of `psds_drink.pkl`

**`rerun_with_drink_masks` new signature**:
```python
rerun_with_drink_masks(
    psd_dir, eeg_dir, spindle_root, drink_dir,
    animal_combos: dict[str, str],   # {animal_id: ok_combo}
    offset_path=None, ncores=None, **kwargs
) -> tuple[Path, Path]   # (psds_drink.pkl, psds_final_drink.pkl)
```
Validation step: cross-checks `source_combo` in `psds_final.pkl` against
`animal_combos` — raises `ValueError` with per-animal diff if they disagree.
Groups animals by combo, uses `spindle_outputs/<combo>/` for state CSVs.
Stamps `source_combo` on every record written to `psds_drink.pkl`.

**`DrinkMaskRerunWorker`** simplified: takes `{animal_id: ok_combo}` dict directly,
calls `rerun_with_drink_masks` once (no per-combo loop).

**`_pending_drink_rerun`** is now `{animal_id: combo}` (was `{combo: [animal_ids]}`).

**PSD Visualizer auto-select**: prefers `psds_final_drink.pkl` over `psds_final.pkl`
when both exist.

#### Manifest bug fix: re-flagging `needs_rerun` with existing rerun run (`pipeline/manifest.py`)

**Bug**: When a user clicked "Needs Rerun → LFC" from a yellow card and the LFC run entry
already existed from a previous cycle (with `sleep_qc="ok"` or `"rejected"`),
`needs_rerun_pending()` and `pending_rerun_review()` both skipped it — dead zone.

**Root cause**: `flag_sleep_qc` only un-cascades siblings when `old_status == "ok"`.
Going from `"needs_review"` → `"needs_rerun"` skipped the un-cascade, leaving the
target rerun run's `sleep_qc` as-is (non-None). Both queue methods skip non-None runs.

**Fix** (end of `flag_sleep_qc`): when `status == "needs_rerun"` and the `rerun_combo`
run entry already exists, reset it to `sleep_qc=None`, `source_combo=<channels>`,
clear all cascade and PSD metadata. This re-enters it into the correct queue:
- CSV present → `pending_rerun_review()` catches it → blue card + Sleep QC badge
- CSV absent → `needs_rerun_pending()` catches it → orange card + Rerun queue

#### Bug fix: `rerun_with_drink_masks` path count mismatch (`psd_compute.py`)

State CSVs and drink `.npy` paths were globbed from the full directory rather than
filtered to target animals. When running a subset (1 of N animals), `re_match` got
mismatched counts and raised. Fixed by filtering all three path lists to `animal_ids_set`.

#### Tests
- `tests/ebb_viewer/test_manifest.py` — 79 tests (2 new for re-flag bug)
- `tests/ebb/test_drink_mask_integration.py` — 30 tests (6 new for new PKL architecture)
- Total: **106 passing**

---

## Full Rerun Review Flow (as implemented)

```
1. Sleep QC page (Group mode)
   → click Review on a suspicious animal → manifest: needs_review

2. Home page — Needs Attention zone  (sidebar shows "Home (1)")
   → yellow card: [Animal] [combo] [Open EDF] [✓ OK] [Rerun as: ▼] [Needs Rerun]
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
1. PSD Computation page
   → Compute PSDs  (drink masks auto-applied if drink_masks/ folder present;
     pre-flight log shows which animals have mask files)

2. Build Final PKL → psds_final.pkl  (one entry per animal from their ok combo)

3. PSD Visualizer
   → opens psds_final_drink.pkl if present, else psds_final.pkl
   → flag animals: [✓ OK] or [Drink Mask]
   → "Drink Mask" shows guidance banner: place .npy in drink_masks/, go to PSD Computation

4. PSD Computation page — Drink Mask Rerun groupbox
   → table shows flagged animals + mask file status (✓ found / ✗ missing)
   → "Apply Drink Masks (N ready)" — validates combo vs psds_final.pkl, then:
     a. reruns estimate_psd with drink mask for each ready animal
     b. updates psds_drink.pkl (accumulates across sessions, replace-per-animal)
     c. regenerates psds_final_drink.pkl = psds_final.pkl base + all psds_drink.pkl records
   → manifest updated: psd_status = "drink_mask_applied"

5. PSD Visualizer
   → re-open to review psds_final_drink.pkl
```

---

## Key Design Decisions

### `source_combo` + CSV as the "Rerun page done" signal
- `source_combo=None`, no CSV → Rerun page hasn't acted → orange card / Rerun queue
- `source_combo` set, no CSV → upload triggered but not completed → still orange card
- `source_combo` set, CSV on disk → ready for Sleep QC review → blue card / Sleep QC badge

### Re-flagging `needs_rerun` resets the target run
`flag_sleep_qc("needs_rerun", rerun_combo=X)` now unconditionally resets any existing
run entry for X to `sleep_qc=None, source_combo=<original>`. Without this, re-cycling
an animal through the rerun flow left the existing run in a non-None state that both
queue methods skipped.

### Drink mask PKL architecture
`psds_final.pkl` is immutable after `build_final_pkl`. Drink mask reruns accumulate
in `psds_drink.pkl` (replace-per-animal) and the merge lives in `psds_final_drink.pkl`.
The combo used for each animal is stored in `source_combo` on each record.

### Combo validation in `rerun_with_drink_masks`
Cross-checks `source_combo` in `psds_final.pkl` against the manifest ok combo before
any computation. Fails fast with a per-animal diff. Prevents running drink mask rerun
against the wrong spindle outputs.

### One-ok invariant
`flag_sleep_qc("ok")` cascade-rejects all siblings. Un-okaying restores them.
Directly-rejected runs require explicit `reset_sleep_qc`.

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
- **Cache eviction in `_poll()` during review mode**: caused second animal's rerun line to disappear. Fixed by skipping eviction when `_review_mode` is True.
- **`needs_rerun_pending()` excluding on `source_combo` alone**: caused vanishing items on cancelled upload. Fixed by gating on CSV presence.
- **`rerun_with_drink_masks` overwriting `psds_<COMBO>.pkl` in place**: destructive, no accumulation across sessions. Replaced with `psds_drink.pkl` + `psds_final_drink.pkl` architecture.
- **`rerun_with_drink_masks` globbing all state/drink paths without animal filter**: caused `re_match` count mismatch when running a subset. Fixed by filtering all path lists to `animal_ids_set`.

---

## Next Steps
1. **End-to-end verification** of full rerun flow (see flow diagram above)
2. **End-to-end verification** of drink mask flow (see flow diagram above)
3. **Remaining UX improvements** from saved plan (see memory: `project_ux_improvement_plan.md`):
   - Priority 4: Review mode visual tint (`#f0f4ff` background when `_review_mode` is True)
   - Priority 5: Post-run navigation hints on Rerun page
   - Priority 7: Human-readable status labels in home table
   - Priority 8: Rename + auto-run "Sync from filesystem"
   - Priority 9: Discoverable double-click affordance for rerun combo

---

## Key Files
- `src/ebb_viewer/pages/sleep_qc_visualizer.py` — Sleep QC page (group + animal + review modes)
- `src/ebb_viewer/pages/rerun.py` — rerun queue page
- `src/ebb_viewer/pages/spindle_upload.py` — batch upload page + `SleepyRatWorker`
- `src/ebb_viewer/pages/home.py` — pipeline summary + Needs Attention zone
- `src/ebb_viewer/pages/psds.py` — PSD Computation page (batch estimate + drink mask rerun)
- `src/ebb_viewer/pages/psd_visualizer.py` — PSD Visualizer (file picker, auto-selects psds_final_drink.pkl)
- `src/ebb_viewer/widgets/psd_graph_widget.py` — PSD grid + flag buttons + drink mask guidance banner
- `src/ebb_viewer/pipeline/manifest.py` — `Manifest` / `ManifestEntry` / `RunEntry`
- `src/ebb_viewer/main_window.py` — sidebar + page navigation + badge refresh + poll timer
- `src/ebb/process/psd_compute.py` — `batch_estimate`, `rerun_with_drink_masks`, `build_final_pkl`
- `src/ebb/io/sleepyrat.py` — `SleepyRatAPI` (low-level HTTP)
- `tests/ebb_viewer/test_manifest.py` — 79 manifest tests
- `tests/ebb/test_drink_mask_integration.py` — 30 drink mask integration tests

## Environment
- Conda env: `ebb-dev` (`source ~/miniconda3/etc/profile.d/conda.sh && conda activate ebb-dev`)
- Run tests: `QT_QPA_PLATFORM=offscreen pytest` (106 passing)
- Branch: `refactor/clean-up`
