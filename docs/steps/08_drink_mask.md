# Step 8. Drink Mask

Terms are defined in the [glossary](../glossary.md).

## Purpose

Recompute the PSDs of the animals you flagged **Drink Mask** in step 7, this time with their drinking events
removed, so the sidebands near 52 and 68 Hz go away. Only the flagged animals are recomputed. Their new PSDs go in
separate files, and you check them back in step 7 (the verify pass).

## Before you run

- At least one animal in the run is flagged `needs_drink_mask` (step 7).
- **A drink-event file for each flagged animal**, `drink_masks/<AnimalID>.npy`. An animal without one is skipped.
- **An offsets CSV**, only if the video and the EEG did not start at the same moment. With no CSV the page assumes
  they are aligned.
- Do not change the PSD settings. The rerun reads them from the run you pick, and they are read-only here.

> **In our lab.** The drink-event files are made outside ebb-viewer, with the lab's network that detects drinking
> from the recording video (exported from the PVFS file). Ask Claudia. The offsets are read by hand from the PVFS
> file.

## Inputs

| Input | Location | What it is |
|---|---|---|
| Drink-event file, one per flagged animal | `drink_masks/<AnimalID>.npy` | A 1 Hz array: one true/false value per second of the recording, true where the animal was drinking. The name must be exactly the animal ID. |
| Offsets file (optional) | the only `.csv` in `drink_masks/` | Columns `Animal` and `Offset`, one row per animal. Offset is in seconds from the start of the EEG to the start of the video. **Positive means the video started after the EEG.** If it is present, every animal being rerun must have a row. |
| Run settings | `psd/<RUN>/psd_params.json` | Everything the first computation used: states, channels, sampling rate, artifact masks, SWD, annotation, hour windows, notch. |
| Preprocessed EDFs | `standard/*PROCESSED.edf` | The signal. |
| State CSVs | `spindle_outputs/<COMBO>/*.csv` | `final_state`, as in step 6. |
| SWD and annotation files | as in step 6 | Used if the run used those masks. |
| PSD decisions | `manifest.json` (`psd_status[<RUN>]`) | Which animals are flagged. |

Example offsets file (made-up numbers):

```
Animal,Offset
CW0DC4,125
CW0DB1,98
```

## Settings

There is one choice on the page, and the rest is read from the run.

| On-screen label | Meaning | Default | Change it when |
|---|---|---|---|
| PSD run | Which run to add drink masks to. Follows the run chosen in step 7. | the run you were just reviewing | You review several runs. |
| Apply Drink Masks (N) | Start the rerun for the N flagged animals that have a mask file. | – | – |
| Refresh | Rescan the folder and the manifest. | – | You added a file. |

The collapsed **PSD parameters (from the run)** section shows what the rerun will use. It cannot be edited.

## Fixed values

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|
| Drink padding | 2 s each side, whole seconds | Each drinking event is widened by this much on both sides before it is applied. It comes from `drink_pad` in the run's settings, which the PSD Computation page does not expose, so it is 2 s unless the file is edited by hand. A fractional value is cut to whole seconds. | `drink_pad`, `drinking_mask` |
| What is rerun | the same settings as the run, plus the drink mask | States, channels, masks, notch and so on are identical. The drink mask is the only difference. | `rerun_with_drink_masks` |
| Which animals | flagged `needs_drink_mask` **and** with a mask file | Animals already `drink_mask_applied` are not rerun unless step 7 sends them back (Redo mask). | `needs_drink_mask_rerun` |
| Offset direction | only positive offsets are applied | A positive offset shifts the mask later by that many seconds. A negative or zero offset is ignored without a message. | `drinking_mask` |
| Length mismatch | tolerance 2 s | If the file is longer than the recording, the end is cut; if shorter, the missing end is treated as "not drinking". A mismatch of more than 2 s gives a warning (printed to the terminal, not shown in the app). | `_DRINK_MASK_TOLERANCE_SEC` |
| All or nothing | – | If any animal fails, none of the new results are saved and no animal is marked applied. | – |
| Workers | all available cores | Speed only. | `ncores=None` |

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [Drink mask padding: each drinking event dilated ±2 s](../decision_log.md#drink-mask-padding-each-drinking-event-dilated-2-s)
- [Drink artifacts are flagged by eye, not automatically](../decision_log.md#drink-artifacts-are-flagged-by-eye-not-automatically)

## What it does

1. **Check** (the READINESS list): the run has saved settings, `standard/` exists, at least one animal is flagged, at
   least one flagged animal has a mask file (an amber ⚠ names the others, which will be skipped), and the offsets CSV is
   unique and has the right columns.
2. **Rebuild the run** from `psd_params.json`, with drink masks turned on.
3. **For each animal to rerun:** read its `.npy`, widen every drinking event by 2 s each side, expand from 1 Hz to the
   recording's sampling rate, shift by the animal's offset (if a CSV is present), and resize to the recording's
   length. A sample is dropped from the PSD if the drink mask says so, along with every other mask the run uses.
4. **Estimate PSDs** as in step 6, for the same states and channels.
5. **Save** (only if every animal succeeded):
   - `psds_drink.pkl` gets the new records, replacing earlier records of the same animals.
   - `psds_<COMBO>_drink.pkl` is rebuilt as the original `psds_<COMBO>.pkl` with those animals' records swapped for
     the new ones.
   - `psd_params.json` is updated: `use_drink_mask` becomes true.
   - Each rerun animal's `psd_status[<RUN>]` becomes `drink_mask_applied`, and its `drink_mask` link is set.
6. **Go to step 7.** A green bar links to the PSD Visualizer. Use the **Verify drink masks** pass: **Mask worked** marks
   the animal OK; **Redo mask** sends it back here.

## Outputs

### `psd/<RUN>/psds_drink.pkl`

The records (same keys as `psds_<COMBO>.pkl`, see [step 6](06_psd_computation.md)) for every animal that has had a drink
mask applied in this run, with `used_drink` true. When an animal is rerun, its old record here is replaced; other
animals' records are kept. In the visualizer, these animals appear as `<AnimalID>_drink`.

### `psd/<RUN>/psds_<COMBO>_drink.pkl`

A full copy of the run's PSDs: the original records for animals without a drink mask, and the drink-masked records for
the rest. This is the file the verify pass shows, and the file Finalize seals when it exists. `psds_<COMBO>.pkl` itself is
never modified by this step.

### Recorded in `manifest.json` and `psd_params.json`

| Field | Meaning |
|---|---|
| `psd_status[<RUN>]` | `drink_mask_applied` for each rerun animal ("mask applied — verify" on the page). |
| `drink_mask` | The relative path `drink_masks/<AnimalID>.npy`. |
| `use_drink_mask` (in `psd_params.json`) | True once any drink mask has been applied. `drink_pad` is kept as it was. |

### On the page

| Item | Meaning |
|---|---|
| ANIMALS line and table | How many are flagged, ready to apply, missing a mask file, or already applied. Amber rows have no `.npy`. |
| Video offset CSV (collapsed) | "none · video assumed aligned", "N CSVs — ambiguous", or the file name and whether it is valid. |
| THIS RERUN | A summary of the pad, states, channels, SWD, annotation and hour-window settings that will be used. |
| READINESS | ✓ ready, ✗ blocks, ⚠ warns only. |
| Log | Progress, then "Drink mask rerun complete. psds_drink.pkl and psds_<COMBO>_drink.pkl updated." |

## Check your work

- The ANIMALS line shows each flagged animal as "mask applied — verify".
- `psd/<RUN>/` has `psds_drink.pkl` and `psds_<COMBO>_drink.pkl`.
- In step 7's verify pass, the sidebands at 52 and 68 Hz are gone for each recomputed animal.

## If something goes wrong

- "No mask files yet — place `<AnimalID>.npy` in `drink_masks/`": the listed animals have no file, or its name is not
  exactly the animal ID.
- "Several CSVs in `drink_masks/`": keep one offsets file.
- "Offset CSV needs 'Animal' and 'Offset' columns": fix the header.
- The rerun fails with a message naming an animal "not found in offset CSV": a CSV is present but has no row for that
  animal. Add the row; the page checks only the header, not the animals.
- A warning about a size mismatch in the terminal: the `.npy` may belong to a different recording. Check it.
- Apply is greyed out: read the red ✗ lines in READINESS.
- The sidebands are still there after verifying: press **Redo mask** in step 7, check the `.npy` and the offset, and
  apply again.
- **Do not recompute the whole run without thinking.** Re-running step 6 under the same run name rewrites
  `psds_<COMBO>.pkl` and clears the run's decisions, but leaves the old `psds_drink.pkl` and `psds_<COMBO>_drink.pkl`
  in place. Finalize seals `psds_<COMBO>_drink.pkl` when it exists, so it would seal the **old** PSDs for every animal.
  After recomputing a run that had drink masks, apply the drink masks again, or use a new run name.

## Used by

Step 7's verify pass reads `psds_<COMBO>_drink.pkl`. Step 9 (Finalize) seals that file in place of
`psds_<COMBO>.pkl` when it exists.

## Known limitations

- **A negative offset is ignored.** If the video started before the EEG, nothing is shifted and nothing warns you.
- **An animal missing from the offsets CSV stops the whole rerun.** The page checks only the CSV's header, not its animals.
- **The padding cannot be changed on the page.** It is 2 s, from the run's settings.
- **Stale drink files after recomputing a run.** PSD Computation's overwrite warning mentions only the PKL files it rewrites, and Finalize
  does not check whether the drink file is older than the run.
