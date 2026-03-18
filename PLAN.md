# Rerun Review Plan

## Goal
After reruns are downloaded from SleepyRat, give the user a clean way to:
1. See how a rerun compares to the original (and all other runs for that animal)
2. See the rerun in context of the group baseline
3. Decide: accept one of the existing runs, or flag for another rerun

---

## Changes

### 1. Manifest (`pipeline/manifest.py`)

- Add `source_combo: str | None = None` to `RunEntry`
  - Backward pointer in the rerun chain (e.g. `LSC_RSC.source_combo = "LFC_RSC"`)
  - Enables `pending_rerun_review()` without scanning all forward pointers
- Add `"rejected"` to `SLEEP_QC_STATUSES`
  - Used when a rerun is abandoned in favour of another combo
  - Only applied to the *rerun* combo that was not chosen, never to the original `"needs_rerun"` run
- Update `Manifest.add_run(animal_id, channels, source_combo=None)` to store `source_combo`
- Add `Manifest.pending_rerun_review()`:
  - Returns `(entry, combo)` pairs where:
    - `run.source_combo is not None`
    - `run.sleep_qc is None`
    - spindle outputs exist on disk for that combo
- Update `flag_sleep_qc` to accept `"rejected"` and clear `rerun_combo` when setting it

### 2. RerunPage (`pages/rerun.py`)

- When calling `manifest.add_run(animal_id, rerun_combo)`, pass `source_combo=combo`
  so the backward pointer is recorded at write time

### 3. Home page (`pages/home.py`)

- No rerun review queue. The existing "Sleep QC Review Queue" remains unchanged:
  only `needs_review` animals with "Open EDF / OK / Needs Rerun" rows.
- Add `"rejected"` display in the pipeline summary table: gray text, no background colour.
- For `needs_rerun` rows where the rerun combo already has `sleep_qc == "ok"`:
  show "rerun done ✓" in gray instead of red "rerun → LSC_RSC", so the table
  doesn't alarm the user after a rerun has been accepted.

### 4. Sleep QC — group reference overlay (`pages/sleep_qc_visualizer.py`)

In **Animal mode**, overlay a dashed reference line on each plot panel showing the
**mean** across all animals that have `sleep_qc == "ok"` in the default combo
(`LFC_RSC`, or whichever combo is most prevalent in `spindle_outputs/`).

- Computed once and cached alongside the existing `_data_cache`
- Drawn as a gray dashed line labeled "Group mean (LFC_RSC)"
- Only shown when Animal mode is active

### 5. Sleep QC — Review Mode (`pages/sleep_qc_visualizer.py`)

Review Mode is where the user both visualises and decides on reruns — no home page
queue involvement.

- Add a **"Review Mode"** toggle button in the top bar
- When active:
  - Auto-switches to Animal mode
  - Filters `cmb_animal` to only animals from `manifest.pending_rerun_review()`
  - Group reference overlay shown automatically
  - Decision buttons appear in the legend for each combo:
    - **"Accept"** — sets `this_combo.sleep_qc = "ok"`; if this combo has a
      `source_combo`, that source's display updates (see home page note above)
    - **"Reject"** — sets `this_combo.sleep_qc = "rejected"` (only valid on rerun
      combos, i.e. those with `source_combo is not None`)
    - **"Rerun Again"** — combo picker + sets `this_combo.sleep_qc = "needs_rerun"`
      with new `rerun_combo`; the new RunEntry is created by the Rerun page when
      the user processes it
  - After accepting or rejecting, refresh the animal list; if no more pending animals,
    show a "All reruns reviewed" message
- When inactive: normal Animal mode behaviour, all animals available, no decision buttons

---

## Rerun chain semantics (summary)

| Scenario | Original combo | Rerun combo |
|---|---|---|
| Accept rerun | stays `"needs_rerun"` (display: "rerun done ✓") | → `"ok"` |
| Accept original / revert | → `"ok"`, `rerun_combo` cleared | → `"rejected"` |
| Rerun again | stays `"needs_rerun"` | → `"needs_rerun"` with new `rerun_combo` |

The `"rejected"` status only ever lands on a run that was *tried as a rerun* and then
abandoned. The original `"needs_rerun"` run is never changed to `"rejected"` — its
status accurately reflects pipeline history, and the queue filters already prevent it
from re-appearing as actionable.

---

## Implementation order

1. ✅ Manifest — `RunEntry.source_combo`, `"rejected"` status, `add_run`, `pending_rerun_review`, `flag_sleep_qc`
2. ✅ RerunPage — pass `source_combo` when calling `add_run`
3. ✅ Home page — `"rejected"` colour in table + "rerun done ✓" display for resolved reruns
4. ✅ Sleep QC — group reference overlay (Animal mode)
5. ✅ Sleep QC — Review Mode toggle + decision buttons in legend
