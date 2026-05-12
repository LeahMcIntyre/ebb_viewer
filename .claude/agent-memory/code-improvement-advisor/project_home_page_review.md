---
name: Home page review findings
description: Confirmed bugs and patterns found in pages/home.py Phase 3 review — open-window leak, stale row index, step-5 false-done, dead _poll method
type: project
---

Review of `src/ebb_viewer/pages/home.py` after Stage A cleanup (Phase 3).

**Confirmed bugs (P1):**
- `_open_windows` list never pruned — closing EDF windows leaks memory; fix by connecting `win.destroyed` to remove the entry.
- `_on_cell_double_clicked` re-derives row list from a fresh manifest load, creating a TOCTOU hazard; fix by caching `self._table_rows` in `_refresh`.
- Step 5 in `compute_pipeline_status` shows "done — N reruns accepted" even when all rerun combos ended up `rejected` rather than `ok`; the condition should verify each rerun combo's `sleep_qc == "ok"`.

**Dead code:**
- `_poll(self)` is a one-line `_refresh()` alias with no callers — remove it.

**Minor patterns:**
- `sum(1 for _ in manifest)` should be `len(manifest)` — `__len__` is implemented.
- `_do_import` does three separate manifest loads; `build_from_standard` returns the manifest so the third load is redundant.
- `_psd_params.list_runs` called 2–3× per refresh cycle; should be computed once and threaded through.
- `any(True for x in ... if cond)` idiom used twice; should be `any(cond for x in ...)`.

**Why:** These came up in a focused Phase 3 review. Stage A already fixed the major readability issues (magic column index, duplicate comments, bare except).
**How to apply:** When reviewing future home.py changes, watch for the window-list leak pattern and the manifest-reload-count pattern elsewhere in pages/.
