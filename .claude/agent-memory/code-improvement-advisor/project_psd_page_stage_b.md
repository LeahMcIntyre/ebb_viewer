---
name: psds.py Stage B findings
description: Remaining issues in psds.py after Stage A bug fixes — for Stage B review session
type: project
---

Key remaining issues found in Stage B review (2026-05-11):

**Bugs:**
- Empty channels list not validated — user can uncheck all CH_LABELS boxes and `_validate` won't catch it; `selected_channels()` returns `[]`, `batch_estimate` gets `channels=[]`
- `_refresh_ann_status` calls `Manifest.load` on every keystroke in the annotation keyword field (wired via `textChanged`) — disk read per character
- `_windows_overlap` converts to `int()` which truncates floats, but spinboxes are integer `QSpinBox` so this is moot in practice (not a real bug)
- `load_params` sets `ann_dir`/`ann_keywords` before `chk_ann.setChecked(True)`, so the `toggled` signal fires after the body widgets are already populated — `_ann_body.setEnabled(True)` fires correctly via the connected lambda, but `_refresh_ann_status()` is called twice (once in the check, once manually). Not a defect but slightly redundant.

**Performance:**
- `showEvent` triggers 3+ `Manifest.load` calls: `_refresh_combo_table` → `_validate` → `_refresh_swd_status` → `_validate`
- `_validate` loads manifest independently from `_refresh_combo_table` even though both are called together
- `_run_pipeline_clicked` calls `Manifest.load` twice in quick succession (pre-flight at 1273, clear-flags at 1375)

**Cleanup:**
- `BatchEstimateWorker.run` lines 1629-1632: `saved["hw_enabled"]`, `saved["hour_windows"]`, `saved["selected_days"]` are redundant — `{**self.params}` already copies those keys when they're present
- `dspin_radius` on PSDPage uses 1 decimal place; `MaskParamsWidget` uses 2 decimals — inconsistency means a saved value of 0.75 would display as 0.8 on reload
- `_on_run_name_changed` calls `_refresh_combo_table` on every keystroke which calls `Manifest.load`

**Why:** These are the remaining structural/correctness issues after Stage A. Stage B defers MaskingSettingsDialog→MaskParamsWidget unification to Phase 5.

**How to apply:** In Stage B session, address in order: empty-channel bug (P1), manifest reload hotspots (P1/P2), radius precision (P2), redundant saved-dict lines (P2 cleanup).
