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

### Completed (earlier session — branch `refactor/clean-up`)

#### Manifest one-ok invariant (`pipeline/manifest.py`)
- `RunEntry` gains `prev_sleep_qc` + `rejected_by` for cascade-rejection bookkeeping
- `flag_sleep_qc("ok")` cascade-rejects all sibling runs, saving their prior status; un-okaying restores them
- `reset_sleep_qc` also restores cascade-rejected siblings and clears stale `psd_status`/`drink_mask`
- `build_from_standard` / `add_run` auto-reject new runs when an ok run already exists
- `load()` integrity checks: fix multi-ok animals (warn + auto-fix), clear orphaned `rejected_by` refs
- `flag_psd` raises `ValueError` if `sleep_qc != "ok"`

#### Tests (`tests/ebb_viewer/test_manifest.py`)
- 44 tests covering the full manifest API

### Completed (branch `refactor/sleep_qc`)

#### Manifest additions (`pipeline/manifest.py`)
- `RunEntry.source_combo: str | None` — backward pointer in the rerun chain
- `"rejected"` added to `SLEEP_QC_STATUSES`
- `add_run(animal_id, channels, source_combo=None)` — stamps `source_combo`; handles re-processing after reload
- `pending_rerun_review()` — globs `{entry.animal_id}_*.csv` specifically (not `any(iterdir())`)
- `flag_sleep_qc` handles `"rejected"` cleanly

#### Rerun page (`pages/rerun.py`)
- `add_run` called with `source_combo=combo`
- Bug fix: `setRowCount(0)` clears all spans on refresh

#### Home page (`pages/home.py`)
- Colored combo badges in the Channels column (per-combo hue, lighter shades, white text)
- Review queue rows use plain `[channels]` text
- Collapsible "Sleep QC Review Queue" and "Project Files" sections
- `_cell()` accepts optional `fg` parameter for foreground color

#### Sleep QC page (`pages/sleep_qc_visualizer.py`)

**Review mode:**
- Orange `"● N reruns ready →"` badge is a checkable toggle — sole entry point
- Forces Animal mode; disables Group button
- `showEvent` and `_on_review_mode_toggled` both evict stale cache for pending-rerun combos
- `_has_pending_rerun()` globs for animal-specific CSV (not `any(iterdir())`)
- Filters animal dropdown to only pending-rerun animals

**Legend in review mode** (decisions live in the legend alongside the colour swatch):
- Every combo row gets `[✓ Accept]` — clicking any one calls `flag_sleep_qc(animal, combo, "ok")` which cascade-rejects all others via the one-ok invariant
- Pending rerun combos additionally show `[Review]` — sends back to Home page review queue
- `_flag_accept_combo(combo)` unified method replaces the old separate accept-rerun / accept-original pair
- `_decision_panel` widget removed entirely — legend handles everything
- Row background colors no longer bleed into buttons: `QWidget#legendRow { ... }` scoped stylesheet

**Other Sleep QC improvements:**
- Group mean reference overlay in animal mode (dashed gray line)
- Bold font for rerun-pending animals in the dropdown

#### Sidebar badges (`main_window.py`)
- `_refresh_badges()` called on every page navigation
- `Home` shows count from `needs_review()`
- `4. Sleep QC` shows count from `pending_rerun_review()`
- `5. Spindle Rerun` shows count from `needs_rerun()`
- Base labels stored in `_row_base_label`; badge format: `"4. Sleep QC  (2)"`

---

## Full Rerun Review Flow (as implemented)

```
1. Sleep QC page (Group mode)
   → click Review on a suspicious animal → manifest: needs_review

2. Home page — Sleep QC Review Queue  (sidebar shows "Home (1)")
   → row: [Animal] [combo] [Open EDF] [✓ OK] [Rerun as: ▼] [Needs Rerun]
   → click Needs Rerun → manifest: needs_rerun + rerun_combo

3. Rerun page  (sidebar shows "5. Spindle Rerun (1)")
   → Run Selected → writes spindle_edfs/<RERUN_COMBO>/
   → manifest.add_run(animal, rerun_combo, source_combo=original_combo)
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

### One-ok invariant
`flag_sleep_qc("ok")` cascade-rejects all siblings. Un-okaying restores them.
Directly-rejected runs require explicit `reset_sleep_qc`.

### Decisions live in the legend
The legend already shows one row per combo with colour swatch. Accept/Review buttons
sit inline with the swatch — no separate decision panel needed. The scoped stylesheet
(`QWidget#legendRow`) prevents button borders from being overridden by row bg colour.

### Rerun chain semantics
| Scenario | Original combo | Rerun combo |
|---|---|---|
| Accept rerun | stays `"needs_rerun"` (Home: "rerun done ✓") | → `"ok"` |
| Accept original | → `"ok"`, rerun_combo cleared | → `"rejected"` (cascade) |
| Review again | unchanged | → `"needs_review"` → Home queue |

### `pending_rerun_review()` check
Globs `{entry.animal_id}_*.csv` in the output directory — badge only fires when
this specific animal's file is actually downloaded, not just any file in the dir.

---

## What Didn't Work
- **Standalone "Review Reruns" toggle**: removed — badge is the single entry point.
- **"Reject" as standalone decision**: stranded animals — replaced with "Accept Original".
- **Inline combo picker for "Rerun Again"**: routes through Home queue instead.
- **Separate decision panel above plots**: tried twice (below legend, above plots) — reverted to legend each time. The legend is the right home for per-combo decisions.
- **`any(iterdir())` check for download completion**: too loose; replaced with animal-specific glob.
- **Unscoped row stylesheet**: `background-color: {bg}` without selector cascaded into buttons, hiding borders. Fixed with `QWidget#legendRow { ... }`.

---

## Next Steps
1. **Commit** all pending changes on `refactor/sleep_qc`
2. **End-to-end verification**: write rerun EDF → upload → download → badge + sidebar count → review mode → both lines visible → accept → cascade-rejection → home table "rerun done ✓"
3. **Debug print** in `psd_graph_widget.py:64`: `print("New PSD Window")` — remove it
4. **`needs_drink_mask()` never called**: manifest method exists but nothing in UI calls it
5. **Persistent upload button on Rerun page**: currently upload is triggered only immediately after Run — add a button to re-trigger for when user cancelled or needs download-only
6. **Remaining UX improvements** from saved plan (see memory: `project_ux_improvement_plan.md`): home page "Needs Attention" zone (priority 2), review mode visual tint (priority 4), post-run nav hints (priority 5), and lower-priority items

---

## Key Files
- `src/ebb_viewer/pages/sleep_qc_visualizer.py` — Sleep QC page (group + animal + review modes)
- `src/ebb_viewer/pages/rerun.py` — rerun queue page
- `src/ebb_viewer/pages/spindle_upload.py` — batch upload page + `SleepyRatWorker`
- `src/ebb_viewer/pages/home.py` — pipeline summary + review queue
- `src/ebb_viewer/pipeline/manifest.py` — `Manifest` / `ManifestEntry` / `RunEntry`
- `src/ebb_viewer/main_window.py` — sidebar + page navigation + badge refresh
- `src/ebb/io/sleepyrat.py` — `SleepyRatAPI` (low-level HTTP)
- `tests/ebb_viewer/test_manifest.py` — 44 manifest tests

## Environment
- Conda env: `ebb-dev` (`source ~/miniconda3/etc/profile.d/conda.sh && conda activate ebb-dev`)
- Branch: `refactor/sleep_qc`
- Run tests: `pytest` (65 passing)
