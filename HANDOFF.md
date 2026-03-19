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

### Completed (commit `642d358` — branch `refactor/sleep_qc`)

#### Manifest additions (`pipeline/manifest.py`)
- `RunEntry.source_combo: str | None` — backward pointer in the rerun chain
- `"rejected"` added to `SLEEP_QC_STATUSES`
- `add_run(animal_id, channels, source_combo=None)` — stamps `source_combo`; handles re-processing after reload
- `pending_rerun_review()` — globs `{entry.animal_id}_*.csv` specifically
- `needs_rerun_pending()` — manifest-only badge/queue view (no filesystem)
- `flag_sleep_qc` handles `"rejected"` cleanly

#### Home page (`pages/home.py`)
- "Needs Attention" scroll zone replaces the old review queue
  - Yellow cards — `needs_review()`: Open EDF / ✓ OK / Rerun as / Needs Rerun
  - Orange cards — `needs_rerun_pending()`: "Spindle rerun queued" + clickable nav link
  - Blue cards — `pending_rerun_review()`: "Rerun ready for review" + clickable nav link
  - "All caught up ✓" when all three lists empty
- `navigate_to = pyqtSignal(str)` — nav links navigate the sidebar
- Pipeline Summary table collapsible
- `manifest_changed` + `_poll()` signals wired

#### Sidebar badges (`main_window.py`)
- Immediate refresh via `manifest_changed` signals from all three pages
- 10 s poll timer refreshes badges + visible page's `_poll()`
- Home → `needs_review()`, Sleep QC → `pending_rerun_review()`, Rerun → `needs_rerun_pending()`

#### Sleep QC page (`pages/sleep_qc_visualizer.py`)
- Review button disabled (not interactive) when status is `needs_rerun` — prevents accidental
  `reset_sleep_qc` that would erase the `rerun_combo` assignment
- Exiting review mode re-discovers combos + reloads all data before rendering
- `_poll()` skips cache eviction during review mode — prevents the 10 s timer from
  evicting rerun combo data mid-review (caused second animal's rerun line to disappear)

#### Rerun page queue / `needs_rerun_pending()` alignment
- Both now exclude runs where `rerun_run.source_combo is not None`
  (once `add_run` stamps `source_combo`, the orange card clears and the blue card takes over)
- Queue filter guards: only show if rerun run doesn't exist OR (`sleep_qc is None` AND `source_combo is None`)

#### `build_from_standard` (`pipeline/manifest.py`)
- Stamps `source_combo` only when scanning `spindle_outputs/` (CSV present = rerun processed)
- Does NOT stamp `source_combo` from `spindle_edfs/` alone — EDF present without CSV means
  upload has not happened yet; the Rerun page must still act and will stamp via `add_run()`

#### Tests (`tests/ebb_viewer/test_manifest.py`)
- 70 tests total (was 44 → 70 across this session and prior session)
- New: `build_from_standard` source_combo stamping (3 tests)
- New: `needs_rerun_pending` source_combo exclusion (2 tests)
- New: EDF-only placement must NOT stamp source_combo (1 test, with `needs_rerun_pending` assertion)

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
   → manifest.add_run(animal, rerun_combo, source_combo=original_combo)  ← stamps source_combo
   → Upload & Download dialog → spindle_outputs/<RERUN_COMBO>/

4. Sleep QC page  (sidebar shows "4. Sleep QC (1)")
   → showEvent evicts stale cache, badge appears: "● 1 rerun ready for review →"
   → click badge → review mode, dropdown filtered to pending animals
   → plots: solid line (original), dashed line (rerun), group mean reference
   → legend: [✓ Accept LFC_RSC] [✓ Accept RSC]  [Review]
   → decide → auto-advance or "Review Complete" → exit review mode

5. If "Review" chosen:
   → rerun combo flagged needs_review → Home queue → repeat from step 2
```

---

## Key Design Decisions

### `source_combo` as the "Rerun page done" signal
`source_combo` being set on a rerun run means the Rerun page has registered it
(called `add_run`) and the upload/download process has been triggered. This is the
handoff point from the orange card to the blue card:
- `source_combo=None` → Rerun page still needs to act → orange card / Rerun queue
- `source_combo` set, no CSV → waiting for download → neither card (transition state)
- `source_combo` set, CSV on disk → ready for Sleep QC review → blue card / Sleep QC badge

### When `build_from_standard` stamps `source_combo`
Only when scanning `spindle_outputs/` (CSV present). A file in `spindle_edfs/` alone
does NOT trigger `source_combo` stamping — the EDF is ready but the upload hasn't
happened. The Rerun page stamps `source_combo` via `add_run()`.

### One-ok invariant
`flag_sleep_qc("ok")` cascade-rejects all siblings. Un-okaying restores them.
Directly-rejected runs require explicit `reset_sleep_qc`.

### Review button on `needs_rerun` runs
Disabled (non-interactive, tooltip explains). Clicking "Review" to uncheck a
`needs_rerun` run previously called `reset_sleep_qc` which silently erased
the `rerun_combo` assignment. Fix: disable the button; manage rerun targets from the
Home page's double-click affordance on the Sleep QC column.

### `_poll()` in Sleep QC — no cache eviction during review mode
The background poll (10 s) evicts rerun combo data so new downloads are picked up.
But during review mode the user is actively navigating between animals using that data.
Evicting mid-review caused the second animal's rerun line to disappear. Fix: skip
eviction in `_poll()` when `self._review_mode` is True. Cache is fully refreshed
on review mode exit.

### `pending_rerun_review()` filesystem check
The only filtered view that checks the filesystem (for the CSV). Badge fires only
when the specific animal's CSV is downloaded, not just any file in the dir.

### `needs_rerun_pending()` — manifest-only, no filesystem
Excludes runs where rerun_run is reviewed (sleep_qc not None) OR already registered
as a rerun (source_combo not None). The Rerun page queue uses the same logic.

---

## What Didn't Work
- **Standalone "Review Reruns" toggle**: removed — badge is the single entry point.
- **"Reject" as standalone decision**: stranded animals — replaced with "Accept Original".
- **Inline combo picker for "Rerun Again"**: routes through Home queue instead.
- **Separate decision panel above plots**: tried twice (below legend, above plots) — reverted to legend each time.
- **`any(iterdir())` check for download completion**: too loose; replaced with animal-specific glob.
- **Filesystem check in `needs_rerun_pending()`**: caused false exclusions from stale files. Reverted to manifest-only check.
- **Stamping `source_combo` from `spindle_edfs/` scan**: caused the "needs rerun" item to disappear from the attention zone when user placed only the EDF manually. Fixed by only stamping from `spindle_outputs/`.
- **Review button interactive for `needs_rerun` status**: unchecking it called `reset_sleep_qc` and erased the rerun target combo silently. Fixed by disabling the button for `needs_rerun` runs.
- **Cache eviction in `_poll()` during review mode**: the 10 s timer evicted rerun combo data causing the second animal's rerun line to disappear mid-review. Fixed by skipping eviction when `_review_mode` is True.
- **`needs_rerun_pending()` not checking `source_combo`**: when user had LSC output pre-placed and synced, then flagged LFC_LSC for rerun, the Rerun page would run (stamp `source_combo`) but both the orange card AND blue card showed simultaneously. Fixed by excluding runs where `rerun_run.source_combo is not None`.

---

## Next Steps
1. **Commit** all pending changes on `refactor/sleep_qc` (4 files modified, ~147 lines)
2. **End-to-end verification** of full rerun flow (see flow diagram above)
3. **Debug print** in `psd_graph_widget.py:64`: `print("New PSD Window")` — remove it
4. **`needs_drink_mask()` never called**: manifest method exists but nothing in UI calls it
5. **Persistent upload button on Rerun page**: upload only triggered immediately after Run —
   add a persistent button to re-trigger for cancelled uploads or download-only re-runs
6. **Remaining UX improvements** from saved plan (see memory: `project_ux_improvement_plan.md`):
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
- `src/ebb_viewer/pipeline/manifest.py` — `Manifest` / `ManifestEntry` / `RunEntry`
- `src/ebb_viewer/main_window.py` — sidebar + page navigation + badge refresh + poll timer
- `src/ebb/io/sleepyrat.py` — `SleepyRatAPI` (low-level HTTP)
- `tests/ebb_viewer/test_manifest.py` — 70 manifest tests

## Environment
- Conda env: `ebb-dev` (`source ~/miniconda3/etc/profile.d/conda.sh && conda activate ebb-dev`)
- Branch: `refactor/sleep_qc`
- Run tests: `pytest` (70 passing)
