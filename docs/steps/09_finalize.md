# Step 9. Finalize

Terms are defined in the [glossary](../glossary.md).

## Purpose

Seal a finished PSD run into one file, `psds_final.pkl`, which is **the file to use for analysis**. Finalize also
records which animals were excluded, inside that file, so anyone who opens it on its own can see who to leave out.
It can also write the PSDs to an Excel workbook for GraphPad Prism.

> **Three things to know before you click.**
> 1. **Finalizing again overwrites `psds_final.pkl` with no confirmation.** The old file is gone.
> 2. **The Excel export is unprocessed.** It contains the stored PSDs only: the inverse filter and the interpolation
>    from step 7 are not applied. Excluded animals are still in the sheets.
> 3. **Exclusions are a snapshot.** They are copied from the manifest when you click Finalize. If you change an
>    exclusion afterwards, click **Re-finalize** to update the file.

## Before you run

- Every animal in the run has been dealt with: reviewed as OK, excluded, or drink-masked and verified (steps 7 and 8).
  The run's card says "✓ All animals reviewed" when it is ready, or what is still pending.
- The run has a PSD file to seal (see Inputs).
- If your project uses SWD review (4b), finish it, or be ready to confirm that you want to continue without.
- You prepare no files.

## Inputs

| Input | Location | What it is |
|---|---|---|
| PSD file to seal | `psd/<RUN>/psds_<COMBO>_drink.pkl` if it exists, otherwise `psds_<COMBO>.pkl` | The drink-masked version is preferred whenever it exists. The card shows which file will be used. |
| Run settings | `psd/<RUN>/psd_params.json` | Shown read-only by **Settings…**. Not copied into the sealed file. |
| Exclusions | `manifest.json` (`sleep_qc == excluded`, `notes`) | Read at the moment you click Finalize. |
| PSD decisions | `manifest.json` (`psd_status[<RUN>]`) | Decides whether the run is ready. |
| Sealed file (for Excel) | `psd/<RUN>/psds_final.pkl` | The input to **Export to Excel**. |

## Settings

There is one card per PSD run (every run with a `psd_params.json`). Nothing on the page is a parameter.

| On-screen label | Meaning |
|---|---|
| Finalize / Re-finalize | Seal this run. Enabled only when nothing in the run is waiting (see What it does) and a PSD file exists. Becomes **Re-finalize** once `psds_final.pkl` exists. |
| Export to Excel | Write the sealed file's PSDs to a `.xlsx`. Enabled only once `psds_final.pkl` exists. Asks where to save; the default is `psd/<RUN>/psds_<RUN>.xlsx`. |
| Settings… | Read-only summary of the run's settings: channels, states, sampling rate, artifact-mask values, hour windows, SWD, drink and annotation masks. |
| Refresh | Rescan the runs and the manifest. |

## Fixed values

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|
| Source preference | `psds_<COMBO>_drink.pkl` over `psds_<COMBO>.pkl` | Chosen by whether the first file exists, not by which is newer (see If something goes wrong). | `build_run_final_pkl` |
| Ready test | no animal needs review, needs a drink mask, or is waiting to be verified | These three counts must all be zero. | `pending_psd_review`, `needs_drink_mask`, `pending_drink_verification` |
| Excluded animals | kept, not removed | Every record of an excluded animal stays in the file and is marked. | `annotate_records` |
| Marker fields | `excluded` (true/false), `exclusion_reason` (text) | Added to **every** record. | – |
| Write method | to a temporary file, then renamed | A failed write cannot leave a half-written `psds_final.pkl`. | – |
| Excel layout | one sheet per channel and state | Column A is the frequency; there is one column per animal, sorted by name; missing values are blank. | `export_psds_to_xlsx` |
| Sheet names | `<channel>_<state>`, for example `LFC_wake`, cut to 31 characters | Excel's limit. | `_SHEET_NAME_MAX` |

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [A sealed `psds_final.pkl` marks "this is the file to use for analysis"](../decision_log.md#a-sealed-psds_finalpkl-marks-this-is-the-file-to-use-for-analysis)
- [Finalize waits until every animal is reviewed](../decision_log.md#finalize-waits-until-every-animal-is-reviewed)
- [There is no channel-merge step](../decision_log.md#there-is-no-channel-merge-step)

## What it does

**Finalize**

1. **Check the SWD review.** If it is on and unfinished (animals with no SWD file and no confirmation, or not fully
   reviewed), ask to continue. Cancel is the default. This check covers all animals, not only this run's.
2. **Read the exclusions** from the manifest: each excluded animal and its reason (the `Excluded (<stage>): …` lines of
   its notes, written as `<stage>: <reason>` and joined with "; ").
3. **Copy the PSD file** (the drink version if it exists), add `excluded` and `exclusion_reason` to every record, and
   write it as `psds_final.pkl`. Clicking again replaces it; there is no confirmation.
4. **Write `excluded_animals.csv`** next to it, with columns `animal` and `reason`. It is always written, with only the
   header when nothing is excluded, so a missing file never has to mean "none excluded".
5. Show a window that names the excluded animals, or says no animals are excluded.

**Export to Excel**

1. Read `psds_final.pkl` and write one sheet per channel and state, in µV²/Hz.
2. If the sealed file marks any excluded animals, add an `excluded_animals` sheet (`animal`, `reason`). The animal columns on
   the other sheets are **not** marked, and excluded animals are still in them.

## Outputs

### `psd/<RUN>/psds_final.pkl`

A pickled list with the same records as the source file (keys listed in [step 6](06_psd_computation.md)), plus:

| Key | Type | Meaning |
|---|---|---|
| `excluded` | bool | True if the animal was excluded (in Sleep QC or in PSD review) when you clicked Finalize. |
| `exclusion_reason` | text | The reason, starting with the stage, for example `Sleep QC: lots of misclassification after hour 30`. Empty if not excluded. |

The exclusions are a snapshot. The manifest is the live record, so run Finalize again after changing an exclusion.

### `psd/<RUN>/excluded_animals.csv`

| Column | Meaning |
|---|---|
| `animal` | Animal ID. |
| `reason` | The reason text, as above. |

### `psd/<RUN>/psds_<RUN>.xlsx` (optional, where you choose)

The sheets described above. The values are the stored PSDs: neither the inverse filter nor the interpolation from step 7 is
applied.

### On the page

| Item | Meaning |
|---|---|
| Status line | "✓ All animals reviewed", or "⚠ 2 need review, 1 need a drink mask, 1 to verify". |
| Excluded line | How many animals are excluded and their IDs. |
| Source line | The PSD file that will be sealed, and whether drink masks are applied. |
| Last written line | When `psds_final.pkl` was last written, or "not yet written". |
| Card colour | Green when ready, grey otherwise. |

## Check your work

- The card shows a recent time for `psds_final.pkl`.
- `excluded_animals.csv` lists exactly the animals you expect, each with a reason.
- The Source line named the file you expected (the drink version, if you used drink masks).
- Home marks Finalize as done.

## If something goes wrong

- Finalize is greyed out: something in the run is still pending. The status line says what.
- "Finalize Failed": the message names the problem, most often that no PSD file exists (compute the run first).
- A change after sealing: Finalize replaces `psds_final.pkl` each time you click it. If the change affects the PSDs
  themselves (masks, settings), compute a new run under a new name and finalize that one instead.
- **The wrong PSDs were sealed.** Finalize picks `psds_<COMBO>_drink.pkl` whenever it exists, without checking its age. If you
  recomputed a run under the same name after applying drink masks, that file is the old one. Apply the drink masks again
  (step 8), or use a new run name, then finalize.
- An exclusion is missing from `psds_final.pkl`: you changed it after sealing. Click Re-finalize.
- Export to Excel is greyed out: the run has no `psds_final.pkl` yet.

## Used by

The PSD analysis notebook reads `psds_final.pkl` and leaves out the animals it marks as excluded. The sleep notebooks do not
use this file; they read `final_state` and the manifest.

## Known limitations

- **There is no confirmation before overwriting `psds_final.pkl`.**
- **The SWD review check covers all animals,** not only the animals in the run being finalized.
- **The Excel export is unprocessed.** The inverse filter and interpolation are not applied, so it differs from the Prism workbooks the PSD analysis notebook writes.
- **Excluded animals are not marked on the Excel sheets,** only listed on the extra sheet.
- **Staleness is not checked.** Finalize seals `psds_<COMBO>_drink.pkl` whenever it exists, whatever its age.
