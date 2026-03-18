# Handoff

## Goal
Polish the spindle rerun pipeline UX in `ebb_viewer` — specifically the flagging/review
loop from Sleep QC → EDF review → Rerun → re-review. Also improve manifest reliability
and test coverage.

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
- `needs_drink_mask` / `needs_drink_mask_rerun` guarded on `sleep_qc == "ok"`
- `build_from_standard` / `add_run` auto-reject new runs when an ok run already exists
- `load()` integrity checks: fix multi-ok animals (warn + auto-fix), clear orphaned `rejected_by` refs
- `flag_psd` raises `ValueError` if `sleep_qc != "ok"`

#### Tests (`tests/ebb_viewer/test_manifest.py`)
- 44 tests covering the full manifest API: save/load round-trip, migration, one-ok invariant, cascade/restore, psd_status clearing, add_run, integrity checks, build_from_standard, all filtered views, validation errors

### Completed (branch `refactor/sleep_qc`)

#### Manifest additions (`pipeline/manifest.py`)
- `RunEntry.source_combo: str | None` — backward pointer in the rerun chain (e.g. `LSC_RSC.source_combo = "LFC_RSC"`)
- `"rejected"` added to `SLEEP_QC_STATUSES`
- `add_run(animal_id, channels, source_combo=None)` — deliberate reruns start with `sleep_qc=None` regardless of existing ok run; stamps `source_combo` retroactively if run exists but wasn't tagged yet
- `pending_rerun_review()` — returns `(entry, combo)` pairs where `source_combo` is set, `sleep_qc is None`, and **this animal's own `*_labels.csv` exists** in the rerun combo's output directory
- `flag_sleep_qc` handles `"rejected"` status cleanly
- Bug fix: `add_run` with `source_combo` on an already-existing run now stamps it

#### Rerun page (`pages/rerun.py`)
- `add_run` now called with `source_combo=combo` so the backward pointer is recorded
- Bug fix: `setRowCount(0)` instead of `setSpan(0,0,1,1)` — properly clears all content and spans on refresh

#### Home page (`pages/home.py`)
- Colored combo badges in the **pipeline summary Channels column** (per-combo hue, white text, lighter shades): blue=`LFC_RSC`, orange=`LFC_LSC`, green=`RSC_LSC`, red=`LFC`, purple=`RSC`, brown=`LSC`
- Review queue rows use plain `[channels]` text (no color)
- Collapsible "Sleep QC Review Queue" and "Project Files" sections (▼/► toggle buttons)
- Review queue scroll area is `stretch=1` (flexible height)

#### Sleep QC page — full review mode redesign (`pages/sleep_qc_visualizer.py`)

**Single entry point:** The orange `"● N reruns ready for review →"` badge is a
**checkable toggle**. Clicking it enters review mode; clicking again exits.

**Review mode behaviour:**
- Forces Animal mode; disables Group button
- On entry AND on `showEvent`: evicts stale cache for pending-rerun combos so newly-downloaded animal files are picked up (fixes bug where rerun line was invisible until app restart)
- Filters `cmb_animal` dropdown to **only animals with pending rerun decisions**
- A **decision panel** appears between the plots and the legend with one row per pending rerun:
  ```
  LSC_RSC  ← rerun of LFC_RSC
  [✓ Accept LSC_RSC]  [↩ Accept LFC_RSC instead]  [Review]
  ```
- Legend in review mode is **read-only colour key** (swatch + label + status text)
- After any decision: reloads manifest, refreshes filtered list, auto-advances to next pending or shows "Review Complete" and exits

**Three decisions:**
| Button | Action | Manifest call |
|---|---|---|
| **✓ Accept rerun** | Accept the rerun; cascade-rejects original | `flag_sleep_qc(animal, rerun_combo, "ok")` |
| **↩ Accept original instead** | Accept the original; cascade-rejects the rerun | `flag_sleep_qc(animal, original_combo, "ok")` |
| **Review** | Send rerun back through Home page review queue | `flag_sleep_qc(animal, rerun_combo, "needs_review")` |

**Other Sleep QC improvements:**
- Group mean reference overlay in animal mode (dashed gray line = mean of all `ok` animals for the most prevalent combo)
- `_has_pending_rerun()` and `_update_decision_panel()` use animal-specific glob (`{animal_id}_*.csv`) instead of `any(iterdir())` — badge and decision panel only show when download is truly complete for that animal

### Bug fixes (this session)
- **Stale cache / rerun line invisible**: `showEvent` now evicts `_data_cache` entries for any pending-rerun combo on every page visit. `_on_review_mode_toggled` does the same. Previously the cache was populated before the download completed and never invalidated, so the rerun line didn't appear until app restart.
- **`pending_rerun_review()` too loose**: was checking `any(iterdir())` — passed even if other animals' files were present but not this animal's. Now globs `{entry.animal_id}_*.csv` specifically.

### Pending commit
All changes are uncommitted. Branch: `refactor/sleep_qc`. Suggested commit:
```bash
git add src/ebb_viewer/pages/sleep_qc_visualizer.py \
        src/ebb_viewer/pages/rerun.py \
        src/ebb_viewer/pages/home.py \
        src/ebb_viewer/pipeline/manifest.py \
        PLAN.md
git commit -m "Redesign rerun review: single entry point, decision panel, no dead ends"
```

---

## Full Rerun Review Flow (as implemented)

```
1. Sleep QC page (Group mode)
   → click Review on a suspicious animal
   → manifest: needs_review

2. Home page — Sleep QC Review Queue
   → row appears: [Animal] [combo] [Open EDF] [✓ OK] [Rerun as: ▼] [Needs Rerun]
   → optionally Open EDF to inspect raw traces
   → click Needs Rerun → manifest: needs_rerun + rerun_combo

3. Rerun page
   → table shows animal with original combo → target combo
   → Run Selected → writes spindle_edfs/<RERUN_COMBO>/
   → manifest.add_run(animal, rerun_combo, source_combo=original_combo)
   → Upload & Download dialog → SleepyRatWorker → spindle_outputs/<RERUN_COMBO>/

4. Sleep QC page
   → showEvent reloads manifest, evicts stale cache for rerun combo
   → orange badge appears: "● 1 rerun ready for review →"
   → click badge → enters review mode
   → animal dropdown filtered to pending-rerun animals
   → plots: solid line (original), dashed line (rerun), group mean reference
   → decision panel:
       [✓ Accept rerun]  [↩ Accept original instead]  [Review]
   → decide → auto-advance or "Review Complete" → exit review mode

5. If "Review" chosen:
   → rerun combo flagged needs_review
   → appears in Home page review queue → repeat from step 2
```

---

## Key Design Decisions

### One-ok invariant
At most one run per animal may have `sleep_qc == "ok"`. Enforced entirely in the manifest:
- `flag_sleep_qc("ok")` cascade-rejects all siblings, storing prior status in `prev_sleep_qc` / `rejected_by`
- Un-okaying restores cascade-rejected siblings
- Directly-rejected runs (`rejected_by=None`) require explicit `reset_sleep_qc`

### Rerun chain semantics
| Scenario | Original combo | Rerun combo |
|---|---|---|
| Accept rerun | stays `"needs_rerun"` (Home table: "rerun done ✓") | → `"ok"` |
| Accept original | → `"ok"`, `rerun_combo` cleared | → `"rejected"` (cascade) |
| Review again | unchanged | → `"needs_review"` → Home queue |

### Status semantics
| `sleep_qc` | Meaning |
|---|---|
| `None` | Not yet reviewed |
| `"needs_review"` | Flagged for EDF trace inspection |
| `"needs_rerun"` | Flagged for spindle rerun with different channels |
| `"ok"` | Accepted (at most one per animal) |
| `"rejected"` | Superseded — another combo was accepted (or cascade-rejected) |

### PSD status invariant
`psd_status` is only valid when `sleep_qc == "ok"`. Cleared automatically on un-ok or reset. `flag_psd` raises if `sleep_qc != "ok"`.

---

## What Didn't Work
- **Standalone "Review Reruns" toggle button**: added then removed — the orange badge is a better single entry point.
- **"Reject" as standalone decision**: stranded animals — eliminated in favour of "Accept Original".
- **Inline combo picker for "Rerun Again"**: replaced by routing through the Home page review queue.
- **Review Mode buttons in the legend**: moved to dedicated decision panel above the legend.
- **`any(iterdir())` check for download completion**: too loose — other animals' files triggered it. Replaced with animal-specific glob.
- **Status column on rerun page**: disk-based step detection felt detached from manifest; reverted.
- **Ghost runs from PSD files in `build_from_standard`**: removed — PSD files are per-combo aggregates.

---

## Next Steps
1. **Commit** the pending changes (see Pending commit above)
2. **End-to-end verification**: write rerun EDF → upload → download → badge appears → review mode → both lines visible → accept → cascade-rejection → home table shows "rerun done ✓"
3. **Debug print in `psd_graph_widget.py:64`**: `print("New PSD Window")` left in, should be removed
4. **`needs_drink_mask()` never called**: the method exists on the manifest but nothing in the UI calls it — investigate whether the drink mask widget queries differently, or wire it up
5. **Consider `_offer_upload` "download only" option** on rerun page: for when EDF was already uploaded in a prior session and only download is needed

---

## Key Files
- `src/ebb_viewer/pages/sleep_qc_visualizer.py` — Sleep QC page (group + animal + review modes)
- `src/ebb_viewer/pages/rerun.py` — rerun queue page
- `src/ebb_viewer/pages/spindle_upload.py` — batch upload page + `SleepyRatWorker`
- `src/ebb_viewer/pages/home.py` — pipeline summary + review queue
- `src/ebb_viewer/pipeline/manifest.py` — `Manifest` / `ManifestEntry` / `RunEntry`
- `src/ebb/io/sleepyrat.py` — `SleepyRatAPI` (low-level HTTP)
- `tests/ebb_viewer/test_manifest.py` — 44 manifest tests

## Environment
- Conda env: `ebb-dev` (`source ~/miniconda3/etc/profile.d/conda.sh && conda activate ebb-dev`)
- Branch: `refactor/sleep_qc`
- Run tests: `pytest` (65 passing)
