---
name: One-ok invariant refactor
description: Context and patterns from the manifest one-ok invariant refactor and related sleep_qc_visualizer changes
type: project
---

The manifest was refactored to enforce "one-ok invariant": at most one run per animal may have sleep_qc == "ok".

Key design decisions:
- `flag_sleep_qc("ok")` cascade-rejects siblings, storing `prev_sleep_qc` and `rejected_by` on each.
- Un-okaying restores only siblings whose `rejected_by == channels` (not manually-rejected siblings).
- `reset_sleep_qc` is the explicit reset path for manually-rejected runs (rejected_by is None).
- `build_from_standard()` and `add_run()` auto-reject new runs when an ok run already exists.
- `flag_psd()` now raises if sleep_qc != "ok" — PSD review is gated on sleep QC passing.
- `sleep_qc_visualizer.py` removed its own cascade-rejection logic; manifest now owns it.
- Rejected runs in the UI show tooltips explaining cascade source; manually-rejected runs get a Reset button.

**Why:** Needed to prevent data from two different spindle runs for the same animal accidentally both going to the PSD stage, which would corrupt the final merged PSD output.

**How to apply:** When reviewing manifest or QC UI code, check that the one-ok invariant is respected. The manifest is the single source of truth for all state mutations — the UI should not apply its own cascade logic.
