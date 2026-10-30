# Step 2. Spindle EDFs

Terms are defined in the [glossary](../glossary.md).

## Purpose

Write a smaller copy of each preprocessed recording that holds only the channels SPINDLE needs: the EEG
channels you choose, plus the EMG. This step is also where the project's channel combo is set, and every
later step reads that combo.

## Before you run

- Step 1 (Preprocess) has run. Without a `standard/` folder the page says "No standard folder available.
  Run preprocessing first." and Run stays disabled.
- Decide the combo now, for the whole project. Every animal must use the same one, so that sleep is scored
  the same way for all of them. Changing it later means uploading and scoring everything again.
- You prepare no files.

## Inputs

| Input | Location | What it is |
|---|---|---|
| Preprocessed EDFs | `standard/*.edf` | Every `.edf` in `standard/` is processed, not only `*_PREPROCESSED.edf`. |

## Settings

| On-screen label | Meaning | Default | Allowed | Change it when |
|---|---|---|---|---|
| Ch0 — LFC | Include the LFC channel (left frontal cortex). | ticked | – | – |
| Ch1 — RSC | Include the RSC channel (right somatosensory cortex). | ticked | – | – |
| Ch2 — LSC | Include the LSC channel (left somatosensory cortex). | unticked | – | – |
| Ch3 — EMG | Always included. Cannot be unticked. | ticked, locked | – | – |

Tick **exactly 1 or 2** of Ch0–Ch2. With 0 or 3 ticked, Run is disabled and a red line says so.
Two channels is the usual choice, because SPINDLE then has more data to score from; one is for when the
second channel is unusable.

The **Channel Combo** field is read-only. It is the EEG labels joined by `_` in channel order, so Ch0 and
Ch1 give `LFC_RSC`, Ch1 and Ch2 give `RSC_LSC`, and Ch0 alone gives `LFC`. The EMG is not part of the name.
The **Target Directory** is derived from it and cannot be edited.

## Fixed values

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|
| Channels written | the ticked EEG channels, then the EMG (Ch3) | In that order. | `spindle`, `channels` |
| Output name | `<stem>_SPINDLE.edf`, in `spindle_edfs/<COMBO>/` | The stem is the input's name without `.edf`, so `…_PREPROCESSED` stays in it. | – |
| Workers | all available cores, one file per process | Speed only. | `set_cores` |

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [One channel combo per project (e.g. LFC_RSC), not per animal](../decision_log.md#one-channel-combo-per-project-eg-lfc_rsc-not-per-animal)
- [Channels: LFC, RSC, LSC, EMG](../decision_log.md#channels-lfc-rsc-lsc-emg)

## What it does

1. **Check** that `standard/` exists and 1 or 2 EEG channels are ticked.
2. **Warn about changing the combo.** If the project already has SPINDLE files for its current combo and
   you are about to write a different one, a window explains that the new combo will become the project's
   combo, that Home, Reclassify, Sleep QC and the PSD steps will then look for outputs that do not exist yet,
   and that the old files are not deleted. To go back, edit `combo` in `manifest.json` yourself.
3. **Confirm overwrite** if `spindle_edfs/<COMBO>/` already holds `*_SPINDLE.edf` files.
4. **Per file, in parallel:** read the whole recording, keep the selected channels, and write
   `<stem>_SPINDLE.edf` into `spindle_edfs/<COMBO>/`. The header, including the start time, is copied.
5. **Set the combo** (only if every file succeeded): write the combo into `manifest.json`, then mark
   `has_spindle` for animals that now have files in the combo's `spindle_edfs/` or `spindle_outputs/` folder.

## Outputs

### `spindle_edfs/<COMBO>/<stem>_SPINDLE.edf`

One per animal. An EDF with the selected EEG channels and the EMG, otherwise identical to the preprocessed
file. The header lists only the channels written.
A second run with a different combo writes a second folder and leaves the first in place.

### Recorded in `manifest.json`

| Field | Meaning |
|---|---|
| `combo` (project level) | The channel combo, for example `LFC_RSC`. The file starts with the default `LFC_RSC` as soon as a project is opened, so the file alone does not show that you chose it. It becomes your choice when this step finishes. |
| `has_spindle` (per animal) | True once the animal has a file in the combo's `spindle_edfs/` or `spindle_outputs/` folder. |

### On the page

| Item | Meaning |
|---|---|
| Channel Combo, Target Directory | What will be written and where. |
| Green or red status line | "1 EEG channel selected — ready to run" or "2 EEG channels…", or the rule you are breaking. |
| Log | "Starting spindle preprocessing on N file(s)…", then "Done: N file(s) written — time". |
| Green box | "Done. Spindle EDFs written." with a button to Spindle Upload. |

## Check your work

- `spindle_edfs/<COMBO>/` has one `*_SPINDLE.edf` per animal.
- The Channel Combo field shows the combo you intended, and Home shows it next to the title.

## If something goes wrong

- Run is greyed out: 0 or 3 EEG channels are ticked, or `standard/` is missing.
- "No EDF files found in standard folder": `standard/` is empty. Run step 1.
- The run fails partway: the combo is not changed, but files already written stay in the folder.
- Home, Reclassify or Sleep QC cannot find outputs after you wrote a different combo: the project combo
  changed. Upload and download the new combo, or set `combo` in `manifest.json` back.
- There is no cancel button.

## Used by

Step 3 (Spindle Upload) uploads this folder. Every later page reads the combo to find
`spindle_outputs/<COMBO>/`.

## Known limitations

- **Every `.edf` in `standard/` is processed**, not only `*_PREPROCESSED.edf` files.
- **A failed run leaves files behind.** The combo is stored only after every file succeeded, but files already written stay in the folder.
