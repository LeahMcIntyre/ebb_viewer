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
- `5. Spindle Rerun` shows count from `needs_rerun_pending()`
- Base labels stored in `_row_base_label`; badge format: `"4. Sleep QC  (2)"`

---

### Completed (this session — branch `refactor/sleep_qc`)

#### Sidebar badge improvements (`main_window.py`, `pages/*.py`)
- `manifest_changed = pyqtSignal()` added to `HomePage`, `RerunPage`, `SleepQCGridPage`
- Emitted after every manifest mutation; connected to `MainWindow._refresh_badges()` for immediate updates
- `QTimer` (10s interval) in `MainWindow._poll()` refreshes badges + calls `_poll()` on the currently-visible page
- `_poll()` added to `HomePage` (full refresh), `RerunPage` (full refresh), `SleepQCGridPage` (lightweight: reloads manifest + evicts stale cache + updates reruns badge only, no plot re-render)

#### Sidebar badge logic fixes
- **`needs_rerun_pending()`** added to `Manifest` — replaces raw `needs_rerun()` for the Spindle Rerun badge
  - Manifest-only check (no filesystem): show if `needs_rerun` AND (rerun run not yet registered OR `sleep_qc is None`)
  - No filesystem check; stale files from previous cycles don't hide items that still need processing
- **Rerun page queue** updated to match: same manifest-only condition, `_rerun_files_exist` helper removed
- **`_run_selected`** already skips writing EDF if it exists on disk — externally placed EDFs are handled

#### Sleep QC legend fixes
- **Review button shows as checked for `needs_rerun` status** (both group and animal mode legends): `status in ("needs_review", "needs_rerun")` instead of `== "needs_review"`
- **Exiting review mode** now calls `_discover_combos()` + `_ensure_all_combos_loaded()` before rendering — fixes bug where rerun combo lines disappeared from the legend after review mode exit

#### Home page — "Needs Attention" zone (`pages/home.py`)
- Old "Sleep QC Review Queue" section replaced by a unified "Needs Attention" scroll zone above the table
- Three card types, all shown:
  - **Yellow** — `needs_review()`: full action buttons (Open EDF, ✓ OK, Rerun as, Needs Rerun)
  - **Orange** — `needs_rerun_pending()`: "Spindle rerun queued" + clickable "→ Spindle Rerun page" link
  - **Blue** — `pending_rerun_review()`: "Rerun ready for review" + clickable "→ Sleep QC page" link
  - Shows **"All caught up ✓"** in green when all three lists are empty
- Navigation links emit `navigate_to = pyqtSignal(str)` from `HomePage`; `MainWindow` connects it to `pagelist.setCurrentRow()`
- **Pipeline Summary table** is now collapsible (toggle "▼ Pipeline Summary"), defaults expanded

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

### `needs_rerun_pending()` — manifest-only, no filesystem
Checks `sleep_qc == "needs_rerun"` AND (rerun run not registered OR `sleep_qc is None`).
No filesystem check — stale EDF/output files from previous rerun cycles don't interfere.
The rerun page's `_run_selected` already skips writing if the EDF is present on disk,
so externally placed EDFs are handled transparently.

---

## What Didn't Work
- **Standalone "Review Reruns" toggle**: removed — badge is the single entry point.
- **"Reject" as standalone decision**: stranded animals — replaced with "Accept Original".
- **Inline combo picker for "Rerun Again"**: routes through Home queue instead.
- **Separate decision panel above plots**: tried twice (below legend, above plots) — reverted to legend each time. The legend is the right home for per-combo decisions.
- **`any(iterdir())` check for download completion**: too loose; replaced with animal-specific glob.
- **Unscoped row stylesheet**: `background-color: {bg}` without selector cascaded into buttons, hiding borders. Fixed with `QWidget#legendRow { ... }`.
- **Filesystem check in `needs_rerun_pending()`**: tried checking for EDF+output existence to filter the badge — caused false exclusions when stale files from previous cycles were present. Reverted to manifest-only check.

---

## Next Steps
1. **Commit** all pending changes on `refactor/sleep_qc`
2. **End-to-end verification**: flag needs_rerun → Needs Attention zone shows orange card → Rerun page shows queue entry → write/upload/download → Sleep QC badge fires → review mode → accept → cascade-rejection → home table "rerun done ✓"
3. **Debug print** in `psd_graph_widget.py:64`: `print("New PSD Window")` — remove it
4. **`needs_drink_mask()` never called**: manifest method exists but nothing in UI calls it
5. **Persistent upload button on Rerun page**: upload is triggered only immediately after Run — add a persistent button to re-trigger upload for when user cancelled or needs download-only
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
- `tests/ebb_viewer/test_manifest.py` — 44 manifest tests

## Environment
- Conda env: `ebb-dev` (`source ~/miniconda3/etc/profile.d/conda.sh && conda activate ebb-dev`)
- Branch: `refactor/sleep_qc`
- Run tests: `pytest` (65 passing)
