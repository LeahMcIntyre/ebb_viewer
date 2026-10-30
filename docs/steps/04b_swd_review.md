# Step 4b. SWD Review (optional)

Terms are defined in the [glossary](../glossary.md).

## Purpose

Spike-wave discharges (SWDs) can make SPINDLE's and Reclassify's state for nearby epochs wrong, which could
produce a false difference between groups in sleep fragmentation. This step lets you step through every
4-second epoch that overlaps an SWD and correct its state where it is wrong. The corrections are saved in
the state CSV and flow into `final_state`, so every later step uses them without knowing the review happened.

## Before you run

- Step 4 (Reclassify) has run. An animal not yet reclassified shows "run Reclassify" and its Review button is
  disabled.
- **One SWD file per animal**, in an `swd/` folder in the project folder (see Inputs). Every animal needs one,
  even an animal with no SWDs, or you must confirm on this page that it has none.
- The review is **optional and off by default**. Nothing on this page changes anything until you tick the
  project-wide box.

> **In our lab.** The SWD files come from the lab's MATLAB SWD detector.

## Inputs

| Input | Location | What it is |
|---|---|---|
| SWD file, one per animal | `swd/*.mat` | The start and stop time of each SWD, in seconds from the start of the recording (this lines up with the preprocessed EDF unless part of the EDF was cut out), stored under the key `DEL_ts` as one `[start, stop]` row per SWD. If `DEL_ts` is not there, the file's first non-meta key is used. An empty array means "no SWDs". |
| State CSV, one per animal | `spindle_outputs/<COMBO>/*.csv` | Must already have `reclass_state` (from step 4). |
| Preprocessed EDF | `standard/` (path from `manifest.json`) | Shown as the trace in the review window. The whole file is loaded into memory. |

**Naming the SWD file.** The animal ID must come first: `CW0DB1_P118_DEL_ts.mat` and `Mice-1256.mat` both
work. The ID is the text before the first `_` (a leading `<letters or digits>ts_` prefix, such as `ts_`, is
skipped). An ID that merely starts the same does not match (`A1` does not match `A10`). If two files match
one animal, the first in sorted order is used. A name beginning `DEL_ts_…` would be read as animal `DEL`.

To make an empty file for an animal with no SWDs (run in the `ebb-dev` environment, using the animal's ID):

```bash
python -c "import numpy as np; from scipy.io import savemat; savemat('swd/CW0DB1_DEL_ts.mat', {'DEL_ts': np.empty((0, 2))})"
```

## Settings

| On-screen label | Meaning | Default | Change it when |
|---|---|---|---|
| Review SWD epochs for this project | Project-wide opt-in. Off: the page changes nothing and the table is hidden. | off | Your project reviews SWDs. |
| Review… (per animal) | Opens the review window for the animal. Enabled only if the animal has an SWD file and is reclassified. | – | – |
| Confirm no SWD (per animal) | For an animal with no SWD file: confirms it has none and needs none. Asks first. Becomes **Undo confirmation**. | – | An animal truly has no SWD file and you do not want to make an empty one. |

In the review window:

| Control | What it does |
|---|---|
| `w` / `n` / `r` | Set the selected epoch to Wake / NREM / REM. Setting it to the epoch's reclassified state removes the edit. |
| Space, or **Next SWD epoch →** | Go to the next SWD epoch. Marks the current SWD epoch as reviewed. |
| Shift+Space, or **← Prev SWD epoch** | Go to the previous SWD epoch. |
| Double-click the trace | Select the epoch at that time. Use it to change an epoch that does not contain an SWD (for example a neighbor). |
| ← / → | Scroll the trace. |
| **Save** | Write the review to the CSV. Closing with unsaved changes asks first. |

The trace shows a 10-second window with SWDs shaded, the state bar, and the selected epoch highlighted in yellow.
The keys act on the selected epoch.

## Fixed values

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|
| Epoch | 4 s | An SWD epoch is any 4 s epoch that overlaps an SWD interval by any amount. An interval that only touches an epoch's edge does not count. | `swd_epoch_flags`, `EPOCH_SEC` |
| SWD key | `DEL_ts` | Falls back to the first key in the file. | `swd_intervals` |
| Review window | 10 s of trace | – | `_REVIEW_WIN_SEC` |
| Valid states | `w`, `n`, `r` | – | `VALID_STATES` |
| Intervals ignored | those with stop before start; those past the end of the recording | – | – |

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [Optional epoch-by-epoch review of epochs that overlap an SWD](../decision_log.md#optional-epoch-by-epoch-review-of-epochs-that-overlap-an-swd)
- [SWD times come from the lab's MATLAB detector](../decision_log.md#swd-times-come-from-the-labs-matlab-detector)
- [Every animal needs an SWD file; the preferred answer for "no SWDs" is an empty file](../decision_log.md#every-animal-needs-an-swd-file-the-preferred-answer-for-no-swds-is-an-empty-file)
- [SWD masking in PSDs: no separate policy needed](../decision_log.md#swd-masking-in-psds-no-separate-policy-needed)

## What it does

1. **Find the SWD epochs.** Read the `.mat` intervals and mark every epoch they overlap.
2. **Open on the right epoch.** The window opens on the first SWD epoch not yet reviewed (or the first SWD epoch,
   if all are).
3. **You review.** For each SWD epoch: if its state is right, press Space to move on (this keeps the state and
   counts the epoch as reviewed). If it is wrong, press `w`, `n` or `r`, then Space. A misclassified SWD epoch
   should get the state the animal was in before and after the SWD.
4. **An SWD epoch counts as reviewed** when you edit it, move on from it, or press Save while it is selected. The
   epoch the window opens on does not count until you do one of these.
5. **Save.** Write two columns into the CSV (see Outputs) and record the progress in the manifest. The first
   write copies the untouched SleepyRat file to `_original/`, as Reclassify does.
6. **Re-running Reclassify keeps your work.** Both old columns are still in the CSV at that point, so a saved
   entry equal to the old `reclass_state` is an unedited copy and follows the new `reclass_state`; an entry that
   differs is a real edit and is kept. Then `final_state` is recomputed.

## Outputs

### Added to each reviewed `spindle_outputs/<COMBO>/*.csv`

| Column | Values | Meaning |
|---|---|---|
| `swd_reclassification` | `w` / `n` / `r` / blank | Non-blank only for (a) SWD epochs you reviewed (the state you chose, or the current `reclass_state` if you left it alone) and (b) any epoch you edited, SWD or not. Blank for SWD epochs not yet reviewed. This makes the column the record of review progress. |
| `final_state` | `w` / `n` / `r` | `swd_reclassification` where it is non-blank, otherwise `reclass_state`. All later steps read it. |

### Recorded in `manifest.json`

| Field | Meaning |
|---|---|
| `swd_review_enabled` (project level) | The opt-in box. |
| `swd_reviewed`, `swd_total` (per animal) | Reviewed and total SWD epochs. A cache of the CSV, refreshed whenever the page opens, so Home and the warnings never read CSVs. `swd_total` is empty until known; `0` means an empty SWD file (nothing to review, counted as done). |
| `swd_waived` (per animal) | You confirmed the animal has no SWD file and needs none. |

### On the page

| Column | Meaning |
|---|---|
| SWD file | The matched file name, or "— no SWD file". |
| SWD epochs | Number of epochs overlapping an SWD, or "run Reclassify". |
| Review | "—" (not started), "In progress (k of N)", "✓ N of N", "no SWD epochs", "Needs file or confirmation", or "Confirmed: no SWD needed". |

While the review is on and unfinished (an animal with no file and no confirmation, or not fully reviewed), Sleep QC shows
an orange line, and PSD Computation, Finalize and Export Masks ask you to confirm before running (Cancel is the
default). Nothing is blocked, because unreviewed SWD epochs keep their reclassified state.

## Check your work

- Each animal reads "✓ N of N" (or "no SWD epochs", or "Confirmed: no SWD needed").
- The CSV has a `swd_reclassification` column and an updated `final_state`.
- No orange "SWD review incomplete" line on Sleep QC.

## If something goes wrong

- "Needs file or confirmation": no `.mat` in `swd/` matches the animal's ID. Check the name, or add an empty file.
- Review… is greyed out: the animal is not reclassified, or has no SWD file.
- Unsaved changes when closing ask to Save, Discard or Cancel.
- Reopening resumes where you stopped, as long as you saved.

## Used by

Everything after this step reads `final_state`, so the review needs no further handling. The PSD SWD mask (step 6)
uses the same `.mat` files but is separate: it removes the SWD time from the PSD, and it does not change states.

## Known limitations

- **"Confirm no SWD" does not satisfy the PSD SWD mask.** The confirmation counts only for this review. If you turn on the SWD mask in
  PSD Computation, every animal still needs a `.mat` file, and the run is blocked until it has one. This is why an empty file is recommended.
- **Turning the review off does not undo saved work.** The box only stops the page, the warnings and the gap checks. Edits already saved
  stay in `swd_reclassification` and in `final_state`.
- **SWD times must line up with the preprocessed EDF.** They are seconds from the start of the recording. Preprocess only trims the end,
  so this holds for normal recordings, but a recording that had a piece removed from its start or middle would no longer match.
