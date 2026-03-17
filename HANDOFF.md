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
- **Home page** (`pages/home.py`): pipeline summary, "rerun done ✓", "Hide Rejected" toggle, "● N reruns ready" badge.

### Completed (this session — branch `refactor/clean-up`)

#### Manifest one-ok invariant (`pipeline/manifest.py`)
- `RunEntry` gains `prev_sleep_qc` + `rejected_by` for cascade-rejection bookkeeping
- `flag_sleep_qc("ok")` cascade-rejects all sibling runs, saving their prior status; un-okaying restores them
- `reset_sleep_qc` also restores cascade-rejected siblings and clears stale `psd_status`/`drink_mask`
- Un-ok path in `flag_sleep_qc` clears `psd_status`/`drink_mask`
- `needs_drink_mask` / `needs_drink_mask_rerun` guarded on `sleep_qc == "ok"`
- `build_from_standard` / `add_run` auto-reject new runs when an ok run already exists
- `build_from_standard` step 3 removed (PSD files are per-combo aggregates, not per-animal — was creating ghost runs)
- `load()` integrity checks: fix multi-ok animals (warn + auto-fix), clear orphaned `rejected_by` refs
- Migration bug fixed: `notes` was always dropped on old-format load
- `flag_psd` raises `ValueError` if `sleep_qc != "ok"`
- Code clarity: `_ok_combo()` helper, explicit field names, three-way `elif` in `flag_sleep_qc`, fields grouped in `RunEntry`

#### Sleep QC UI (`pages/sleep_qc_visualizer.py`)
- OK/Review buttons now un-toggle (clicking a checked button calls `reset_sleep_qc`)
- Removed manual cascade-rejection logic from UI (now handled by manifest)
- Cascade-rejected runs show tooltip; manually-rejected runs get a Reset button
- "● N reruns ready for review →" is now a **clickable button** — jumps to animal mode at first pending rerun
- Animal dropdown has three ordered groups: **rerun-pending (bold)** → other unreviewed → reviewed
- **"Next Rerun ►"** button in animal controls steps through only rerun-pending animals; disabled when none remain ahead
- Rerun combos drawn with **dashed line** in plots (solid = original, dashed = rerun)
- Legend label shows provenance in italic: `"LSC_RSC  ← rerun of LFC_RSC"`
- After marking OK on an animal that had a pending rerun, page **auto-advances** to next pending rerun
- `_flag_animal_review` now calls `_update_reruns_badge`
- `_get_ref_combo` optimized to single pass
- Removed old-style `typing` imports

#### Tests (`tests/ebb_viewer/test_manifest.py`)
- 44 new tests covering the full manifest API: save/load round-trip, migration, one-ok invariant, cascade/restore, psd_status clearing, add_run, integrity checks, build_from_standard, all filtered views, validation errors

### Pending commit
The last change (Sleep QC rerun UX) is **staged but not yet committed**. Commit with:
```bash
git add src/ebb_viewer/pages/sleep_qc_visualizer.py
git commit -m "Improve rerun review workflow on Sleep QC page"
```

---

## Key Design Decisions

### One-ok invariant
At most one run per animal may have `sleep_qc == "ok"`. Enforced entirely in the manifest:
- `flag_sleep_qc("ok")` cascade-rejects all siblings, storing their prior status in `prev_sleep_qc` and `rejected_by`
- Un-okaying restores siblings that were cascade-rejected by that run
- Directly-rejected runs (no `rejected_by`) are unaffected by restore; reset explicitly via `reset_sleep_qc`

### Flagging/review flow
```
Sleep QC page
  → flag "needs_review"     → Home page review queue
                               → Open EDF viewer
                               → flag "ok" or "needs_rerun" + target combo

  → flag "ok"               → manifest cascade-rejects all other runs for that animal

Rerun page
  → writes spindle_edfs/<RERUN_COMBO>/
  → manifest.add_run(..., source_combo=combo)
  → offers SleepyRat upload

Sleep QC page (again)
  → rerun badge button → jumps to animal mode at first pending rerun
  → rerun combo shown dashed + "← rerun of LFC_RSC" label
  → flag "ok" on accepted combo → others cascade-rejected → auto-advance
```

### Status semantics
| `sleep_qc` | Meaning |
|---|---|
| `None` | Not yet reviewed |
| `"needs_review"` | Flagged for EDF trace inspection |
| `"needs_rerun"` | Flagged for spindle rerun with different channels |
| `"ok"` | Accepted (at most one per animal) |
| `"rejected"` | Superseded — another combo was accepted |

### PSD status invariant
`psd_status` is only valid when `sleep_qc == "ok"`. It is cleared automatically when a run is un-okayed or reset. `flag_psd` raises if `sleep_qc != "ok"`. `needs_drink_mask` / `needs_drink_mask_rerun` filter views guard on `sleep_qc == "ok"`.

---

## What Didn't Work
- **Review Mode** in Sleep QC: removed (earlier session). EDF trace needed to pick rerun channels — decision belongs in Home page EDF viewer.
- **Status column on rerun page**: disk-based `_rerun_step()` felt detached from manifest; reverted.
- **"upload pending" status on Home page**: Spindle EDF and Spindle Output columns already convey this.
- **`**d` splat in `ManifestEntry` construction**: replaced with explicit field names for clarity.
- **Ghost runs from PSD files in `build_from_standard`**: removed step 3 — PSD files are per-combo aggregates so adding runs for every animal was wrong.

---

## Next Steps
1. **Commit the pending Sleep QC change** (see Pending commit above)
2. **Verify end-to-end**: write rerun EDF → upload → download → badge appears → accept → others cascade-rejected → Home table updates
3. **Debug print in `psd_graph_widget.py:64`**: `print("New PSD Window")` left in, should be removed
4. **`needs_drink_mask()` never called**: the method exists on the manifest but nothing calls it — investigate whether the drink mask widget queries differently, or wire it up
5. **Consider `_offer_upload` "download only" option** on rerun page: for when EDF was already uploaded in a prior session
6. **Consider direct "Needs Rerun" picker in EDF viewer**: the `needs_review` → Home queue → EDF viewer path is the only way to set `needs_rerun`; a direct combo picker in the viewer could be cleaner

---

## Key Files
- `src/ebb_viewer/pages/sleep_qc_visualizer.py` — Sleep QC page (group + animal modes, rerun queue UX)
- `src/ebb_viewer/pages/rerun.py` — rerun queue page
- `src/ebb_viewer/pages/spindle_upload.py` — batch upload page + `SleepyRatWorker`
- `src/ebb_viewer/pages/home.py` — pipeline summary + review queue
- `src/ebb_viewer/pipeline/manifest.py` — `Manifest` / `ManifestEntry` / `RunEntry`
- `src/ebb/io/sleepyrat.py` — `SleepyRatAPI` (low-level HTTP)
- `tests/ebb_viewer/test_manifest.py` — 44 manifest tests

## Environment
- Conda env: `ebb-dev` (`source ~/miniconda3/etc/profile.d/conda.sh && conda activate ebb-dev`)
- Branch: `refactor/clean-up`
- Run tests: `pytest` (65 passing)
