# Glossary

Terms used on more than one step page, each defined once. Step pages link here instead of
redefining them. Terms used on only one step are defined on that step's page.

## Project and files

**Animal ID.** The part of a file name before the first `_` (`CW0DC4_P098_KO_….edf` is animal
`CW0DC4`). Every file is matched to an animal by this ID, and it must match exactly, including capitals.

**Project folder.** The folder you choose when ebb-viewer starts. It holds one time point's
recordings and everything the pipeline writes (`standard/`, `spindle_edfs/`, `spindle_outputs/`,
`psd/`, `manifest.json`). Animals from different time points must not share a project folder, because
their IDs would collide.

**Manifest (`manifest.json`).** The pipeline's record of each animal's progress and decisions, plus
the project-level channel combo. The Home page reads it. Do not edit it by hand.

**Channel combo.** The EEG channels given to SPINDLE, joined by `_` (for example `LFC_RSC`), with the
EMG always included. A project has exactly one combo. It is set when you write the SPINDLE EDFs and
names the `spindle_edfs/<COMBO>/` and `spindle_outputs/<COMBO>/` folders.

**Channel order.** The pipeline finds channels by position, never by name: 1 = LFC (left frontal cortex), 2 = RSC (right somatosensory cortex), 3 = LSC (left somatosensory cortex),
4 = EMG.

**Standard EDF.** A preprocessed recording in `standard/` (`…_PREPROCESSED.edf`): trimmed to whole days
and downsampled to 250 Hz.

## Sleep states

**Epoch.** One 4-second scoring unit. SPINDLE gives one state per epoch, so a 72 h recording has
64 800 epochs and a 48 h recording 43 200.

**State.** Wake (`w`), NREM (`n`) or REM (`r`) for one epoch.

**Bout.** A run of consecutive epochs in the same state. In the sleep-by-bin tables a bout is counted once, in the bin that holds most
of it, with its full length; it is never cut at a bin edge.

**SPINDLE / SleepyRat.** SPINDLE is the sleep-scoring model. SleepyRat is the web service that runs it;
the Spindle Upload step sends recordings there and downloads one label CSV per animal.

**Artifact (SPINDLE).** An epoch that SPINDLE judges to be noise, because its artifact probability
(`noise_prob`) is at or above the file's cutoff. Not the same as the artifact masks in PSD Computation,
which flag samples by amplitude, SD, events and so on.

**Original states.** SPINDLE's own states (`rawstate`, or `state` in the newer format). They are kept
for comparison and are never used for analysis.

**Reclassified states (`reclass_state`).** The states after Reclassify's gap fill and, where needed,
the EMG check.

**`final_state`.** The one state column all analysis reads. After Reclassify it equals `reclass_state`;
SWD review can then override it for epochs it corrected. A CSV without it raises `NotReclassifiedError`.

**EMG gate.** The part of Reclassify that keeps a gap-fill change only if the EMG shows
real muscle activity in that epoch. Applied only to animals where gap fill over-fragments light-period
NREM.

**Light period.** The clock hours 06:00–19:59, taken from the EDF's start time. Reclassify uses it to
count NREM bouts. This is the lab's light schedule and is hardcoded; other schedules are not supported.

**SWD.** Spike-wave discharge. Detected outside ebb-viewer and supplied as one `.mat` file per animal
(start and stop times in seconds).

## Decisions and statuses

**Sleep QC status (`sleep_qc`).** Your decision about an animal's sleep data: `None` (not decided),
`ok`, `needs_review` (look at the recording, then settle it), or `excluded`.

**Flagged.** Marked `needs_review` in Sleep QC, either by you or automatically because a metric passed
its threshold. A flag is a prompt to look, not a decision. Every flagged animal must end `ok` or
`excluded`.

**Excluded.** A final decision to leave an animal out of analysis. It needs a written reason, saved in
the animal's notes. An excluded animal is **not deleted**: it is still computed, kept in the sealed
PSD file, and marked `excluded` with its reason, so you can reverse the decision or leave it out later.

**PSD status (`psd_status`).** Your decision about an animal's PSDs within one PSD run (stored as
`{run name: status}`): `ok`, `needs_drink_mask`, or `drink_mask_applied` (recomputed, waiting to be
verified). Only animals that are `ok` in Sleep QC have one.

**Notes.** Free text per animal. Exclusion reasons are added as `Excluded (<stage>): …` lines, where the
stage is Sleep QC or PSD review.

## PSDs

**PSD.** Power spectral density: power per frequency, for one animal, channel and state group. Units:
µV² per Hz.

**State group.** The set of states pooled into one PSD: Wake, NREM, REM, Sleep (NREM + REM) or All.

**PSD run.** One computation of PSDs under a name (default `default`), saved in `psd/<RUN>/` with its
exact settings. Several runs can sit side by side.

**Mask.** A true/false value per sample saying whether to keep it. A sample is used for a PSD only if
every mask keeps it. Artifact masks (commutator, SD threshold, SPINDLE noise) are built from the signal;
event masks (SWD, annotation, drink, hour window) are built from files or clock time.

**Drink mask.** A mask of drinking events, made from video outside ebb-viewer. Applied only on the Drink
Mask step, to animals whose PSDs show the drinking artifact (sidebands near 52 and 68 Hz).

**Notch filter.** A 60 Hz bandstop filter (57–63 Hz) applied to the signal before the PSD is estimated.
Changes the saved PSD.

**Interpolation (display).** A straight line (in log-log space) drawn across the line-noise gap in the visualizer (56–64 Hz
if the notch was used, 58–62 Hz otherwise). It changes only what you see. Do not confuse it with the
notch, which changes the data.

**Inverse filter.** Correction factors on 0.5–3.5 Hz that compensate for the recording hardware's
low-frequency roll-off. Display-only in the visualizer; the analysis notebook applies it.

**Sealed (`psds_final.pkl`).** The PSD file written by Finalize: a copy of the latest PSD file for the run,
with excluded animals kept and marked. It is the file to use for analysis.
