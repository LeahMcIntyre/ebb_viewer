# Handoff

## Goal
Polish the spindle rerun pipeline UX in `ebb_viewer` — specifically the flagging/review
loop from Sleep QC → EDF review → Rerun → re-review.

---

## Current Progress

### Completed (earlier sessions)
- **Sleep QC animal mode** (`pages/sleep_qc_visualizer.py`): per-combo OK/Review buttons with single-ok enforcement.
- **Rerun page** (`pages/rerun.py`): log box, manifest-driven table, upload/download via `SleepyRatWorker`.
- **SleepyRatWorker** (`pages/spindle_upload.py`): `files=` parameter for exact-file upload (used by rerun page); `upload_dir=` for batch glob (used by spindle upload page).
- **Manifest** (`pipeline/manifest.py`):
  - `RunEntry.source_combo` — backward pointer in the rerun chain.
  - `"rejected"` added to `SLEEP_QC_STATUSES`.
  - `Manifest.add_run(animal_id, channels, source_combo=None)` stores backward pointer.
  - `Manifest.pending_rerun_review()` — returns `(entry, combo)` where `source_combo is not None`, `sleep_qc is None`, and spindle outputs exist on disk.
  - `flag_sleep_qc` accepts `"rejected"` and clears `rerun_combo` for non-`needs_rerun` statuses.
- **Home page** (`pages/home.py`):
  - Pipeline summary shows "rerun done ✓" (gray) when original `needs_rerun` combo's rerun has `sleep_qc == "ok"`.
  - `"rejected"` rendered in gray in the Sleep QC column.
  - **"Hide Rejected" toggle button** (defaults on): hides rejected rows from the summary table; label toggles to "Show Rejected" when off.
- **Rerun page filter** (`pages/rerun.py`): hides rows where the rerun combo already has both a spindle EDF and spindle output on disk.
- **Sleep QC page** (`pages/sleep_qc_visualizer.py`):
  - Removed Review Mode entirely (was unused/broken).
  - Animal dropdown: unreviewed animals (any `sleep_qc == None` run) sort to the top.
  - Group mean reference overlay: dashed gray line on all Animal mode plots showing mean of all `sleep_qc == "ok"` animals for the most prevalent combo.
  - **"● N reruns ready for review" badge** in top bar — shown when `pending_rerun_review()` is non-empty; updated on `showEvent` and after accepting a combo.
  - **Reject-all-others on OK**: `_flag_animal_ok` (animal mode) and `_flag_sleep_qc` (group mode) both now reject all other runs for that animal when one combo is accepted as OK.

---

## Key Design Decisions

### Flagging/review flow
```
Sleep QC page
  → flag "needs_review"     → Home page review queue
                               → Open EDF viewer
                               → flag "ok" or "needs_rerun" + target combo

  → flag "ok"               → all other runs for that animal → "rejected"
                               (both group mode and animal mode)

Rerun page
  → writes spindle_edfs/<RERUN_COMBO>/
  → manifest.add_run(..., source_combo=combo)
  → offers SleepyRat upload

Sleep QC page (again)
  → rerun combo appears in animal dropdown (sorted to top)
  → flag "ok" on accepted combo → others "rejected"
```

### Status semantics
| `sleep_qc` | Meaning |
|---|---|
| `None` | Not yet reviewed |
| `"needs_review"` | Flagged for EDF trace inspection (appears in Home queue) |
| `"needs_rerun"` | Flagged for spindle rerun with different channels |
| `"ok"` | Accepted |
| `"rejected"` | Superseded — another combo was accepted instead |

### "rejected" only set via OK
`"rejected"` is never set manually. It's applied automatically to all other runs when
any combo is accepted as OK. The Home page hides rejected rows by default.

### `needs_rerun` original combo never changes
When a rerun is accepted, the original `needs_rerun` combo stays as-is (Home page shows
"rerun done ✓"). Its `rerun_combo` field records what was tried. Only the rerun combo
gets `"ok"` or `"rejected"`.

---

## What Didn't Work
- **Review Mode** in Sleep QC: removed. The EDF trace is needed to pick rerun channels,
  so that decision belongs in the Home page EDF viewer, not Sleep QC.
- **Status column on rerun page**: disk-based `_rerun_step()` felt detached from manifest; reverted.
- **"upload pending" status on Home page**: user decided the Spindle EDF and Spindle Output
  columns already convey this — no extra Sleep QC column state needed.

---

## Next Steps
- Verify end-to-end: write rerun EDF → upload to SleepyRat → download outputs → badge
  appears on Sleep QC page → accept → others rejected → Home table updates.
- Consider whether `_offer_upload` on the rerun page should support a "download only"
  option (EDF already uploaded in a prior session).
- The `needs_review` → Home queue → EDF viewer path is the only way to set `needs_rerun`.
  If users find this roundabout, a direct "Needs Rerun" combo picker in the EDF viewer
  itself (rather than the Home queue row) could be cleaner.

---

## Key Files
- `src/ebb_viewer/pages/rerun.py` — rerun queue page
- `src/ebb_viewer/pages/spindle_upload.py` — batch upload page + `SleepyRatWorker`
- `src/ebb_viewer/pages/sleep_qc_visualizer.py` — Sleep QC page (group + animal modes)
- `src/ebb_viewer/pages/home.py` — pipeline summary + review queue
- `src/ebb/io/sleepyrat.py` — `SleepyRatAPI` (low-level HTTP)
- `src/ebb_viewer/pipeline/manifest.py` — `Manifest` / `ManifestEntry` / `RunEntry`
