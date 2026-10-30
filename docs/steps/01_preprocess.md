# Step 1. Preprocess

Terms are defined in the [glossary](../glossary.md).

## Purpose

Turn each raw recording into a trimmed, downsampled copy that every later step uses. The raw files are
never changed. Trimming makes all recordings a whole number of days; downsampling (5000 Hz to 250 Hz by
default) makes the files small enough to work with.

## Before you run

- **One EDF per animal**, directly in the project folder. Subfolders are not searched. If an animal's
  recording was restarted and is in several short files, combine them first with the command-line combine
  step (a separate page, to be written), and move the original chunks out of the folder.
- **Channel order** is LFC, RSC, LSC, EMG, by position. The step does not check names.
- **File names** are `AnimalID_anything.edf`: the animal ID is the part before the first `_`. The animal ID
  must be the same everywhere else the animal appears. **The name must not contain spaces**: the file name
  carries through every later step to SleepyRat, which fails on spaces (see step 3).
- **One project folder per time point**, so animal IDs do not collide.

## Inputs

| Input | Location | What it is |
|---|---|---|
| Raw EDFs, one per animal | `*.edf` in the project folder | Recordings at the original sampling rate, all channels. The page reads each header on opening to show duration and rate. |

## Settings

These are not saved anywhere after the run. Nothing records which values made a given file (see Outputs).

| On-screen label | Meaning | Unit | Default | Allowed range | Change it when | Code name |
|---|---|---|---|---|---|---|
| Original Sampling Frequency | The rate the recordings were acquired at. **Every scanned file's header rate must equal it**, or Run preprocessing stays disabled and a red line names the files that differ. | Hz | 5000 | 250 – 10 000 | Your recordings were not acquired at 5000 Hz. | `fs` |
| Downsample Factor | Keep one sample in this many (after anti-alias filtering). The page shows the output rate. The original rate must divide evenly by it, or Run stays disabled. | – | 20 | 1 – 100 | Leave at 20 (5000 → 250 Hz). | `downsample` |
| Trim To (hrs) | One to four target lengths. Each recording is trimmed to the longest target that is no longer than the recording. Add or remove targets with **+** / **−**. | hours | 48, 72 | 1 – 168 per target, whole numbers | Leave alone for whole days. Other projects can use other lengths. | `trim_to` |

A line under the settings reports how many recordings will go to each length ("2 recordings → 72h,
1 recording → 48h") and warns in red about any recording shorter than the smallest target.

## Fixed values

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|
| Files processed | every `*.edf` directly in the project folder | Also files you did not mean to include, and unreadable ones (the scan label counts them as "unreadable", but they are still passed to the run and will make it fail). | `batch`, `glob("*.edf")` |
| Channels | all, in their original order | Nothing is dropped. | – |
| Trim start | sample 0 | Only the end is cut. | `start=0` |
| Trim end | target hours × 3600 × original rate, rounded up to a whole second | Keeps record arithmetic aligned. | `compute_trim_stop_samples` |
| Downsampling | openseize polyphase resampling with a Kaiser low-pass anti-alias filter | With the default factor 20: cutoff 125 Hz, passband edge 112.5 Hz, stopband edge 137.5 Hz, at most 0.1 dB passband loss, at least 40 dB stopband attenuation. | `resampling.downsample` |
| Output record length | 1 s | Rewritten whatever the input used, because some files use other record lengths (for example 10 s). | `record_duration` |
| Signal units | unchanged | The physical range and units in the header are copied as is (µV for our recordings). | – |
| Processing chunk | 3 000 000 samples | Streaming size while reading. Each worker still holds the whole downsampled recording in memory before writing it. | `chunksize` |
| Workers | all available cores, one file per process | Speed only. Memory use grows with the number of files running at once. | `set_cores` |
| Output name | `<stem>_PREPROCESSED.edf`, in `standard/` | The stem is the input file's name without `.edf`, so a combined animal keeps `_COMBINED` in its name. | – |


## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [Trim to whole days: 48 h or 72 h](../decision_log.md#trim-to-whole-days-48-h-or-72-h)
- [Sampling: 5000 Hz acquired, downsampled by 20 to 250 Hz](../decision_log.md#sampling-5000-hz-acquired-downsampled-by-20-to-250-hz)
- [Anti-alias filter: openseize defaults](../decision_log.md#anti-alias-filter-openseize-defaults)
- [Channels: LFC, RSC, LSC, EMG](../decision_log.md#channels-lfc-rsc-lsc-emg)
- [Animal ID is the first `_`-delimited token of the filename](../decision_log.md#animal-id-is-the-first-_-delimited-token-of-the-filename)

## What it does

1. **Scan** (on opening the page, and on **Rescan**): read every EDF header for its duration
   (records × record length) and sampling rate (samples per record ÷ record length). Warn if one animal has
   several EDFs (uncombined restart chunks) or if a file's rate differs from the setting.
2. **Check the settings.** Run is available only if the output rate is a whole number and every file's
   header rate matches Original Sampling Frequency.
3. **Confirm overwrite.** If `standard/` already holds preprocessed EDFs, ask before replacing them.
4. **Per file, in parallel:**
   1. Choose the longest `Trim To` target that fits the recording. If none fits, stop with an error.
   2. Read samples 0 up to the trim end and downsample by the factor.
   3. Copy the header, set the record length to 1 s, the samples per record to the output rate, and the
      record count to the new length in seconds, and write `standard/<stem>_PREPROCESSED.edf`.
5. **Update the manifest** (only if every file succeeded): add an entry for each animal not already in it,
   with the path of its preprocessed EDF. Existing entries and their decisions are never changed. It also
   marks animals that already have SPINDLE files.

## Outputs

### `standard/<stem>_PREPROCESSED.edf`

One per animal. It is an ordinary EDF with:

| Header field | Value |
|---|---|
| Sampling rate | original rate ÷ downsample factor (250 Hz by default) |
| Record length | 1 s |
| Samples per record | the output rate, for every channel |
| Number of records | trimmed length in seconds |
| Channels | the same channels, in the same order, as the input |
| Recording start date and time | copied from the input; later steps use it to place the recording in the day |
| Signal units and physical range | copied from the input |

Size is about hours × 7.2 MB for four channels at 250 Hz (2 bytes per sample), so about 520 MB for 72 h and
350 MB for 48 h, roughly 1/20 of the raw file. The settings used are **not recorded** in the file or
anywhere else; the output rate and length can be read from the header, but the filter and trim choice cannot.

### Recorded in `manifest.json`

| Field | Meaning |
|---|---|
| Entry per animal | `animal_id` (from the file name) and `preprocessed_edf`, the path relative to the project folder. This is what makes an animal appear on Home. Entries are added, never removed or overwritten. |

### On the page

| Item | Meaning |
|---|---|
| Scan line | "Found N files · 48h 00m – 73h 47m" (or "all 72h 00m"), plus "· K unreadable" if some headers could not be read. |
| Trim line | Recordings per target length, red for any that will fail. |
| Red lines | More than one EDF for an animal; files whose rate differs from the setting. |
| Log | "Starting preprocessing on N file(s)…", then "Done: N file(s) written — time". |
| Green box | "Done. Preprocessed EDFs written to standard." with a button to Spindle EDFs. |

## Check your work

- `standard/` has one `_PREPROCESSED.edf` per animal, with the sizes above.
- Home lists every animal, and the count equals the number of raw EDFs.
- The trim line matched what you expected (48 h or 72 h per animal).

## If something goes wrong

- "No EDF files found": the EDFs are not directly in the project folder.
- Red line about more than one EDF for an animal: uncombined restart chunks, or chunks left behind after
  combining. Combine and move the originals out, or they are preprocessed as separate files.
- Red line about a rate not matching: set Original Sampling Frequency to the real rate, or move the odd
  files out of the folder.
- Run is greyed out: the rate does not divide by the factor, or a file's rate does not match.
- A recording is shorter than the smallest `Trim To` target: the run stops with "Recording is X hrs, below
  all trim_to". Files written before that point stay in `standard/`, but the manifest is not updated until a
  later run succeeds or you open Home. Fix the recording (combine its chunks) or lower the smallest target,
  only if your analysis allows it.
- Very long recordings and many files can use a lot of memory, because each worker holds a whole recording.
  Close other programs first.
- There is no cancel button. To stop, close the app and rerun; existing outputs are overwritten after you confirm.

## Used by

Every later step. Spindle EDFs copies channels from these files. Reclassify reads the EMG channel and the
start time. Sleep QC reads the start time. PSD Computation reads the signal. The EDF viewer opens them.

## Known limitations

- **The settings are not saved.** Nothing on disk records which trim, downsample and sampling-rate values a project was preprocessed with.
- **A failed run can leave files behind** in `standard/` without updating the manifest. There is no cancel button.
- **Other output rates.** The EEG viewer, the commutator mask and the Reclassify EMG check read the sampling rate from the EDF, so they
  follow whatever rate Preprocess wrote. PSD Computation and Export Masks have a Sampling freq setting (default 250 Hz) that must equal the
  EDFs' rate, or the run stops. 250 Hz is the lab's rate.
