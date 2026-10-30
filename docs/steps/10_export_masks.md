# Step 10. Export Masks (optional)

Terms are defined in the [glossary](../glossary.md).

## Purpose

Write each animal's sleep states and artifact masks as time-stamped interval files, **without computing PSDs**. Use it to
take the masks into other software (Spike2, MATLAB, R and so on), or to use the artifact masking outside this pipeline.
The masks are built the same way as in PSD Computation, so an export lines up with what the PSD step analyses.

## Before you run

- Step 4 (Reclassify) has run. The states come from `final_state`.
- Each animal to export has a preprocessed EDF in `standard/` and a state CSV in `spindle_outputs/<COMBO>/`.
- Any mask you turn on has its files, as in step 6: SWD `.mat` files in `swd/`, annotation files in a folder you pick,
  and, for the drink mask, `drink_masks/<ID>.npy` (plus the offsets CSV if you have one).
- A new export name. A name that already exists is refused.

## Inputs

| Input | Location | What it is |
|---|---|---|
| Preprocessed EDF | path in `manifest.json` (`standard/`) | The signal the amplitude masks are computed from. |
| State CSV | `spindle_outputs/<COMBO>/<AnimalID>_*.csv` | `final_state` and `noise_prob`. |
| SWD file (optional) | `swd/` | Used when the SWD mask is on and the animal has a file. |
| Annotation file (optional) | the folder you choose | Used when the annotation mask is on and the animal has a file. |
| Drink-event file (optional) | `drink_masks/<AnimalID>.npy` | Used whenever it exists and the drink mask is on, **whatever the animal's PSD review status**. |
| Offsets file (optional) | the only `.csv` in `drink_masks/` | As in [step 8](08_drink_mask.md). More than one `.csv` makes that animal's export fail. |
| Saved settings (optional) | `psd/<RUN>/psd_params.json` or `exports/<NAME>/export_params.json` | Start from a PSD run's settings, or an earlier export's. |
| Animals | `manifest.json` | Animals that are `ok` **or excluded** in Sleep QC. |

## Settings

Most settings are the same as in [step 6](06_psd_computation.md), with the same labels, meanings, units and defaults:
**States to Export**, **Channels**, **Sampling freq**, and the mask sections (commutator, SD threshold, SPINDLE noise, 60 Hz
notch, SWD, annotation, hour window, drink). **Restore defaults** resets them.

The differences from step 6:

| On-screen label | Meaning here | Default |
|---|---|---|
| Start from: Load from PSD run… | Copy the settings of a PSD run. A red note appears when you later change them. | none (defaults) |
| Start from: Load from saved export… | Copy the settings of an earlier export. | none |
| Animals | Which animals to export. All are ticked by default. **Select all / Select none.** | all `ok` and excluded animals |
| SWD mask: Pad each event | Works here: seconds added each side of every SWD. (Hidden in step 6, where it has no effect.) | 0 s |
| Drink mask: Apply drink mask when available, Pad | Use `drink_masks/<ID>.npy` for animals that have one. | on, 2 s |
| Export name | The folder under `exports/` that receives the files. Letters, digits, `-` and `_`, up to 64 characters. It must not exist yet. | empty |
| Commutator: amplitude limit | A sample is flagged when its absolute amplitude exceeds this, as in step 6. | 2000 µV |

The **Export** button reads "Export N animals" and stays disabled until a name, at least one animal and at least one
state are set.

## Fixed values

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|
| Commutator amplitude limit | the value on the page, 2000 µV by default | As in step 6. | `comm_value` |
| Commutator radius, pad, minimum event | 1 s, 1 s, 0.04 s | As in step 6, converted to samples at the sampling rate. | `commutator_samples` |
| Epoch length | 4 s | – | `epoch_winsize` |
| Same-channel rule | a sample flagged on any selected channel is flagged for all | As in step 6. | – |
| SD mask scope | wake samples only, in the clean-window files | The artifact file lists SD flags wherever they occur; the clean-window file applies them to wake only. | `clean_mask_for_state` |
| Intervals | start inclusive, end exclusive | In seconds from the start of the recording and in samples. | `IntervalRow` |
| Missing mask inputs | skipped quietly | An animal with no SWD file, no annotation file or no drink-event file is exported without that mask; the meta file records the path as empty. | – |
| Failures | per animal | One animal failing does not stop the others. | `export_run` |

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [Mask export is for analysis outside the pipeline](../decision_log.md#mask-export-is-for-analysis-outside-the-pipeline)

## What it does

1. **Name and check.** Refuse an existing name. If SWD review is on and unfinished, ask to continue (Cancel is the default).
2. **Save the settings** to `exports/<NAME>/export_params.json`, so the export can be reproduced with "Load from saved export…".
3. **Per animal, in order:** find the EDF, state CSV, drink file, SWD file and offsets file; build the state masks and the
   artifact masks as in step 6; then write the four files below. A failure is recorded for that animal and the loop moves on.
4. **Show a status table** with one row per animal and a progress bar. **Open exports folder** opens the result.

## Outputs

In `exports/<NAME>/`, for each animal (`<animal>_<combo>_…`):

| File | Contents |
|---|---|
| `…_states.csv` | The sleep states over the whole recording, one row per run of the same state, labelled `wake`, `nrem` or `rem`. Column `state`. |
| `…_artifacts.csv` | The time windows that were masked. One row per run, labelled by its source in column `source`. Sources: `commutator`, `spindle_noise`, `sd_threshold`, `drink`, `swd`, `outside_hour_window`, `annotation`. A source appears only if it was on for that animal. |
| `…_clean_per_state.csv` | The clean windows left for each state: samples that are in the state and in no artifact. Column `state`. |
| `…_meta.json` | The settings and files used (see below). |

Every CSV has the columns `start_s`, `end_s`, `start_sample`, `end_sample` and then the label column. A file with no
intervals still has its header. `exports/<NAME>/export_params.json` holds the settings.

**`…_meta.json` keys**

| Key | Meaning |
|---|---|
| `animal_id`, `combo` | – |
| `fs`, `epoch_winsize_s` | Sampling rate and epoch length used. |
| `n_samples`, `duration_s` | Recording length. |
| `recording_start` | Start date and time from the EDF. |
| `edf_path`, `state_csv_path` | Source files. |
| `state_column` | Always `final_state`. |
| `drink_mask_path`, `offset_csv_path`, `swd_path`, `annotation_path` | The files used, or empty. |
| `params` | The settings, in the same form as `psd_params.json`. |
| `used_hour_windows` | Hour windows after clipping to the recording. |
| `exported_at` | When the export ran. |

**Excluded animals are not marked.** Nothing in the files says an animal was excluded. Check the manifest (Home), and leave
excluded animals out, or untick them in **Animals** before exporting.

## Check your work

- Every animal in the status table reads ok.
- Each animal has the four files, and the `…_artifacts.csv` sources match the masks you turned on.
- For an animal you expected to have a drink, SWD or annotation mask, the corresponding path in `…_meta.json` is not empty.

## If something goes wrong

- Export is greyed out: no name, a name that exists, no state, or no animal selected. The hint beside it says which.
- A row in the status table shows an error: the message names the cause. Usual ones are a missing preprocessed EDF or state CSV,
  no `final_state` (run step 4), a sampling rate that does not match the setting, or several `.csv` files in `drink_masks/`.
- An expected mask is missing from the output: its file was not found for that animal. Check `…_meta.json`.

## Used by

Nothing in ebb-viewer. These files are for other software.

## Known limitations

- **Excluded animals are exported, unmarked.**
- **The drink mask is applied from the file on disk,** whatever the animal's PSD review status, so an animal never flagged for a drink mask
  is still masked if `drink_masks/<ID>.npy` exists.
- **A missing drink offset only warns** (in the terminal) and the mask is applied unshifted. In step 8 the same situation stops the rerun.
- **A negative offset is ignored,** as in step 8.
