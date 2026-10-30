# Step 4. Reclassify

Terms are defined in the [glossary](../glossary.md).

## Purpose

SPINDLE flags epochs it thinks are artifacts, and those flags chop real NREM bouts into pieces.
Reclassify repairs this once, up front: it turns suspect NREM epochs into wake and, for animals
where that would over-fragment sleep, asks the EMG whether the change is justified. The result
is stored as `final_state`, the one state column every later step reads.

## Before you run

- Step 3 (Spindle Upload) has downloaded the label CSVs into `spindle_outputs/<COMBO>/`.
- The animal's preprocessed EDF is in `standard/`. It supplies the recording start time for every
  animal, and the EMG channel for animals that need the EMG check. A CSV with no matching EDF is
  skipped with a warning and keeps no `final_state` (it shows "—" in the Reclassified column).
- You prepare no files for this step.

## Inputs

| Input | Location | What it is |
|---|---|---|
| SPINDLE label CSV, one per animal | `spindle_outputs/<COMBO>/*.csv` | One row per 4 s epoch, as downloaded from SleepyRat. See the column definitions under Outputs. |
| Preprocessed EDF, one per animal | `standard/*PROCESSED.edf` | The preprocessed recording. Used for its start time (to find the light period) and, only when the EMG check applies, channel 4 (EMG). |
| Project channel combo | `manifest.json` (`combo`) | Chooses which `spindle_outputs/` folder to read. |

## Settings

None. The only control is **Run reclassification**.

## Fixed values

Built into the code (`nrem_reclass.py`) and not editable on the page. They are listed because they define the
result.

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|
| Artifact cutoff | 0.5. Older SleepyRat files carry a `threshold` column (also 0.5) and its first non-empty value is used if present; current files have none | An epoch is an artifact when its `noise_prob` is at or above this. | `DEFAULT_NOISE_THRESHOLD` |
| Gap-fill radius | 1 epoch (4 s) | How far on each side of a clean NREM epoch to look for an artifact. | `GAP_RADIUS` |
| Over-fragmentation tolerance | 10% | The EMG check is applied only when gap fill raises the light-period NREM bout count by more than this. | `FRAGMENTATION_TOL` |
| EMG strictness (k) | 5 | A change is kept only if the epoch's EMG RMS is above median + k × MAD. Larger k keeps fewer changes. | `EMG_K` |
| Light period | clock hours 06:00–19:59 | Hours used to count NREM bouts for the check. Taken from the EDF start time, so a different light cycle is not handled. | `DARK_HOURS` (20:00–05:59 excluded) |
| Epoch length | 4 s | SPINDLE's scoring unit. | `EPOCH_SEC` |
| EMG channel | channel 4; the sampling rate is read from the EDF | Where the EMG is read from. The epoch length in samples follows the recording's own rate. | `EMG_CHANNEL`, `header_fs` |

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [Why reclassify at all: wake artifacts scored as NREM inflate fragmentation](../decision_log.md#why-reclassify-at-all-wake-artifacts-scored-as-nrem-inflate-fragmentation)
- [Gap fill, radius 1](../decision_log.md#gap-fill-radius-1)
- [EMG gate: cancels gap-fill flips without EMG evidence, applied only when needed](../decision_log.md#emg-gate-cancels-gap-fill-flips-without-emg-evidence-applied-only-when-needed)
- [Keep both the original and the reclassified states](../decision_log.md#keep-both-the-original-and-the-reclassified-states)

How well the step agrees with human scoring, and what it does to bout counts, is in the first entry.

## What it does

For each animal, working in 4 s epochs, starting from the original state (`rawstate`, or `state`
in the new SleepyRat format):

1. **Mark artifacts.** An epoch is an artifact if `noise_prob` ≥ the cutoff.
2. **Gap fill.** An NREM epoch becomes wake if it is itself an artifact, or if it is clean but
   an artifact lies one epoch before **and** one epoch after it (the neighbours can be any state).
   Neighbours past the ends of the file count as clean. Wake and REM epochs never change, and
   nothing becomes REM or NREM.
3. **Decide whether the EMG check is needed.** Count NREM bouts in the light period before and
   after step 2. A bout belongs to the period its first epoch is in. If the count rose by more
   than 10%, gap fill is breaking long bouts apart and the check applies. Most animals do not need it.
4. **EMG check (only when step 3 says so).** Compute the EMG RMS of every epoch. Find the cutoff
   `median + 5 × MAD` of the RMS over every epoch SPINDLE originally called NREM, artifact-flagged
   ones included. MAD is the plain, unscaled median absolute deviation. Keep a step-2 change only
   if that epoch's RMS is above the cutoff; otherwise the epoch stays NREM. The check can only
   cancel changes. If the EDF is shorter than the CSV, the missing epochs cannot be checked and
   their changes are cancelled.
5. **Save.** Write the result to the CSV and record the decision in the manifest.

Safe to re-run. A saved SWD review (step 4b) is kept and re-applied over the new states.

## Outputs

### Added to each `spindle_outputs/<COMBO>/*.csv`

| Column | Values | Meaning |
|---|---|---|
| `reclass_state` | `w` / `n` / `r` | State after gap fill and, where it applied, the EMG check. Written equal to `final_state` at this step. |
| `final_state` | `w` / `n` / `r` | The state all later steps read. After this step it equals `reclass_state`; SWD review (4b) can later override it for epochs it corrected. |
| `emg_gate` | `kept`, `cancelled`, blank | For each epoch gap fill changed in an animal where the EMG check applied: `kept` if the EMG supported the change, `cancelled` if not. Blank on every other epoch, and on **every** epoch of an animal where the check was not needed. Documentation only; nothing reads it. |

Columns that were already there are not changed. The ones this step reads:

| Column | Meaning |
|---|---|
| `rawstate` (old format) or `state` (new format) | SPINDLE's original state per epoch. When both exist, `rawstate` wins because old-format `state` holds artifact codes. |
| `noise_probs` (old) or `noise_prob` (new) | SPINDLE's probability that the epoch is an artifact. |
| `threshold` | Older files only: the artifact cutoff for the file (0.5). Current SleepyRat files do not have it. |

The first time a CSV is rewritten, the untouched SleepyRat file is copied to
`spindle_outputs/<COMBO>/_original/<name>.csv`. That copy is never overwritten, so to undo
reclassification, copy the files back.

### Recorded in `manifest.json` (per animal)

| Field | Values | Meaning |
|---|---|---|
| `reclass_gate_applied` | `null` / `true` / `false` | `null`: not run yet. `true`: the EMG check applied. `false`: it was not needed. (The page and Home call this "EMG gate".) |
| `reclass_flips_kept` | integer or `null` | Epochs gap fill changed to wake that stand in `final_state`. |
| `reclass_flips_cancelled` | integer or `null` | Epochs the EMG check put back. Always 0 when the check did not apply. |

### On the page

| Column | Meaning |
|---|---|
| Reclassified | ✓ if the CSV has `reclass_state`; — if not. Read from the file, so a re-downloaded CSV shows —. |
| EMG gate | `applied`, `not needed`, `unknown (re-run to restore)` (CSV is reclassified but the manifest has no record; the result is fine), or —. |
| Gap-fill flips kept / cancelled | The two manifest counts, from the last run. |
| NREM bouts (light) before → after | Light-period NREM bouts before and after gap fill. Shown only for animals run in the current session. |

## Check your work

- Every animal has ✓ under Reclassified. The status line reads "Done: N file(s), EMG gate applied to K".
- An animal with `applied` has a non-zero cancelled count. An animal with `not needed` shows 0 cancelled.
- The bout count after gap fill is not far above the count before (within 10%) for animals marked `not needed`.

## If something goes wrong

- Reclassified shows — for an animal: it has no matching `*PROCESSED.edf` in `standard/`.
- "Sleep QC already started" prompt on run: earlier Sleep QC decisions were made on the old states. Continuing does not reset them.
- A later step raises `NotReclassifiedError`: the CSV has no `final_state`. Run this step. A freshly re-downloaded CSV needs it again.

## Used by

Everything after this step reads `final_state`: SWD review, Sleep QC (with **Show original** for
comparison), PSD computation, Export Masks, and the sleep notebooks. Scripts can opt out only by
passing the original-state columns explicitly.

## Known limitations

- **Only the clock-hour light cycle is handled.** The light period for the bout-count check is taken from the EDF start time as
  06:00–19:59, so a different light cycle is not supported.
- **`reclass_state` and `final_state` are identical after this step.** They differ only after SWD review.
- **The EMG check does not always undo the extra bouts.** Of the 9 research animals (out of 141) that the rule gates, the check removed at least 90% of the light-period increase in 5, part of it in 1 and none of it in 3. See the decision log.
- **The 10% tolerance is not optimized.** About a tenth of the animals (17 of 141) would be treated differently at a tolerance anywhere from 5% to 20%.
- **Only NREM becomes wake.** Nothing else is corrected: SPINDLE's over-called REM (about a third of its REM calls match the raters), NREM called wake, and SWDs scored as NREM (see step 4b).
