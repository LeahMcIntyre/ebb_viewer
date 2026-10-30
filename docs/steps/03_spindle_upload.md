# Step 3. Spindle Upload

Terms are defined in the [glossary](../glossary.md).

## Purpose

Send the SPINDLE EDFs to SleepyRat, wait for SleepyRat to score them, and download one label CSV per animal.
Each CSV gives a state (wake, NREM or REM) and an artifact probability for every 4 s epoch. One button does
the whole job.

## Before you run

- Step 2 (Spindle EDFs) has run. Otherwise the page says "Spindle EDFs need to be created before using this
  page" and the button is disabled.
- You can sign in to SleepyRat (https://sleepyrat.ai/) in a browser, with an account that can create
  projects. The first time, the app opens a browser tab for you to approve access.
- A network connection. The step can take a long time (see What it does), so leave the app open.

> **No spaces, anywhere.** SleepyRat fails if the SleepyRat project name, the remote folder name or the name of
> any EDF file contains a space. The app replaces spaces with `_` in the remote folder name for you, and
> nothing else: it does not rename your EDF files or your SleepyRat project. File names come from your
> raw recordings, so check them before step 1 (a name with a space carries through every later step).

> **In our lab.** The SleepyRat username is `xuelab`, and the password is the lab's standard password. Use
> your own SleepyRat project, named for you, so your files stay separate from other people's. If your name is
> not in the list, create it with **New…**.

## Inputs

| Input | Location | What it is |
|---|---|---|
| SPINDLE EDFs | `spindle_edfs/<COMBO>/*.edf` | The files from step 2. All `.edf` files in the folder are uploaded. |
| Project combo | `manifest.json` (`combo`) | Chooses which folders are used. |
| SleepyRat access token | `~/.config/ebb/sleepyrat.json` | Created the first time you approve access in the browser. Reused until it expires or is revoked. |

## Settings

| On-screen label | Meaning | Default | Change it when |
|---|---|---|---|
| SleepyRat project | The SleepyRat project that holds your files. Pick from the list; **Refresh** reloads it; **New…** creates one (name, then an optional description). | first in the list | Always pick your own. |
| Remote folder name | The folder inside that project for this project's files. Spaces become `_`. A line below says whether the folder already exists ("Existing folder — already-uploaded edf files will be skipped; missing labels will be downloaded") or will be created ("New folder — will be created on upload"). | `<project folder name>_<COMBO>`, for example `Walk_Through_LFC_RSC` | You want a different name, or you need a new folder to re-score (see If something goes wrong). |

The **Upload & Download** button stays disabled until a project and a folder name are set; its tooltip says
what is missing.

## Fixed values

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|
| Epoch length | 4 s | SleepyRat scores 4 s windows. | – |
| State labels | computed by SleepyRat | The state is decided on SleepyRat's side. ebb cannot change the scoring threshold. | `download_labels` |
| Match on name | file name without `.edf`, Unicode-normalised, spaces as `_` | How an uploaded file is recognised as already on SleepyRat, and how a label file is named. | `_norm_stem` |
| Label file name | `<stem>_labels.csv` in `spindle_outputs/<COMBO>/` | The stem is the submission's name without `.edf`. | – |
| Wait between checks | 30 s | How often the app asks SleepyRat whether scoring has finished. | `wait_for_processing` |
| Maximum wait | 10 000 s (about 2 h 47 min) | After this, the run stops with "Processing did not finish within the wait limit." Run again later; finished files download. | `max_wait` |
| Uploads | one at a time | Not parallel. | – |
| Network timeouts | none set | A stalled connection can hang the step. | – |

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [Using SPINDLE for staging](../decision_log.md#using-spindle-for-staging)
- [Epoch length 4 s and the three states](../decision_log.md#epoch-length-4-s-and-the-three-states)

## What it does

1. **Create the remote folder** if the project does not have it yet.
2. **Upload what is missing.** List the files already in the remote folder and compare names. Files whose
   name is already there are skipped ("Skipping N already-uploaded edf file(s)"); the rest are uploaded
   one by one. If the list cannot be fetched, the app treats it as empty and uploads everything.
3. **Wait for scoring**, but only if something was uploaded. Check every 30 s until every file in the remote
   folder has finished (succeeded, failed or cancelled). If nothing was uploaded, this step is skipped.
4. **Download labels.** For every file in the remote folder (not only the ones you just uploaded) that has no
   `<stem>_labels.csv` yet in `spindle_outputs/<COMBO>/`, download its labels. Existing label files are never
   overwritten ("Skipping N already-downloaded file(s)").
5. **Update the manifest:** mark `has_spindle` for animals that now have a file in the combo's folders.

If the output folder already contains files, a window asks before continuing ("New CSVs will be mixed
with existing files").

## Outputs

### `spindle_outputs/<COMBO>/<stem>_labels.csv`

One per animal, exactly as SleepyRat returns it: one row per 4 s epoch, so 64 800 rows for 72 h and 43 200
for 48 h. Columns include:

| Column | Meaning |
|---|---|
| `index` | Epoch number, from 0. |
| `state` | SPINDLE's state for the epoch: `w`, `n` or `r`. |
| `noise_prob` | SPINDLE's probability that the epoch is an artifact. |
| `class_prob_0` – `class_prob_2` | SPINDLE's probabilities for the three states. |

Reclassify later adds columns to these files. Older SleepyRat files also have a `threshold` column (the
artifact cutoff, 0.5) and used `rawstate` and `noise_probs` as column names. Current versions have none of
these, so the artifact cutoff is 0.5 everywhere. The code still reads both formats.

### Recorded in `manifest.json`

| Field | Meaning |
|---|---|
| `has_spindle` (per animal) | True once the animal has a file in the combo's `spindle_edfs/` or `spindle_outputs/` folder. |

### On the page

| Item | Meaning |
|---|---|
| "Spindle EDF set" line | Where files come from and go to. |
| Log | Progress for each stage, including "Checking for existing edf files on SleepyRat…", "Uploading (i/N): name…" and "Downloading N sleep state csv(s)…". Messages about failed scoring are printed to the terminal, not to this log. |
| Citation line | How to cite SleepyRat. |
| Green box | "Done. Labels downloaded — ready to reclassify." with a button to Reclassify. |

## Check your work

- `spindle_outputs/<COMBO>/` has one `*_labels.csv` per animal, each with 64 800 or 43 200 rows.
- Home shows every animal with SPINDLE output.

## If something goes wrong

- "SleepyRat Error" window or an ERROR line: read the message. Running again is safe, because nothing is
  uploaded or downloaded twice.
- "Processing did not finish within the wait limit": SleepyRat is slow. Run again later; files that finished
  will download.
- Your name is missing after you created it: click **Refresh**.
- **Re-scoring an animal after rebuilding its EDF.** Files are matched by name, so SleepyRat skips the new
  file and keeps the old scoring, and an existing label CSV is never overwritten. **You must delete the old
  entry for that animal on the SleepyRat website, in your project's folder, and also delete the animal's
  `_labels.csv` in `spindle_outputs/<COMBO>/`.** Then run again. Deleting only one of the two does not work.
  Alternatively, give the new EDF a different animal ID: SleepyRat then treats it as a separate animal and
  nothing needs deleting, but every other file for that animal (SWD, annotation, drink mask) must use the new
  ID too, because files are paired by exact animal ID. A new remote folder name also avoids the old entry,
  but then every animal is uploaded and scored again. A freshly downloaded CSV counts as not reclassified
  until you run step 4 again.
- A scoring job fails on SleepyRat: the app shows nothing in its log. The failure is printed in the terminal
  the app was started from, and SleepyRat's website shows it. What happens when the app then tries to
  download that file has not been observed; it may stall. If the step appears stuck after the wait ends,
  check the terminal and SleepyRat's site.
- Extra CSVs appear: the download covers every file in the remote folder, so sharing one remote folder between
  projects brings in the other project's labels. Use one remote folder per project.

## Used by

Step 4 (Reclassify) reads these CSVs. Sleep QC, PSD Computation and Export Masks read them through
`final_state` after reclassifying.

## Known limitations

- **Downloads cover the whole remote folder**, not only this project's files. Use one remote folder per project.
- **The list of files already on the remote is trusted.** If the listing fails, everything is uploaded again.
- **A failed scoring job shows only in the terminal** the app was started from, and on SleepyRat's website. The app's log does not show it.
- **Re-scoring needs the old entry deleted on SleepyRat as well** as the local `_labels.csv` (see If something goes wrong).
