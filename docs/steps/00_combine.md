# Step 0. Combine restarted recordings (command line, optional)

Terms are defined in the [glossary](../glossary.md).

This step has no page in ebb-viewer. You run it in a terminal **before you open the app**. Skip it if every recording ran
continuously for its full length.

## Purpose

Sometimes a recording stops early and is restarted, so one animal ends up with several short EDF files (for example
`CW0DC4_P096_….edf` and `CW0DC4_P098_….edf`, each about a day long). The pipeline needs one file per animal. This step joins
the chunks into one `…_COMBINED.edf` per animal, and does the same for the animal's SWD and annotation files so their times
still line up with the combined recording.

## Before you run

- Use the `ebb-dev` environment. The command is `ebb-combine`, installed with the app.
- **Put the files where the commands expect them.** The EDFs in the project folder, the SWD `.mat` files in one folder (for
  example `swd/`), the annotation `.txt` files in another (for example `annotations/`).
- **File names.** The animal ID (the text before the first `_`) must be the same in every chunk of an animal and different
  between animals. The SWD and annotation chunks are ordered by the number after `_P` in the name (`_P096`, then `_P098`); the
  EDF chunks are ordered by the start time in their header. The two orders must agree.
- **Every EDF shorter than the nominal length in the folder needs a companion chunk.** A lone short recording stops the run with
  "No match found for token". If your project mixes full-length recordings of different lengths (for example 48 h and 72 h),
  see `--nominal-hours` below.
- **Each chunk should be at least 24 h long.** A shorter chunk is joined whole, but the SWD and annotation files are still
  shifted by a full 24 h per chunk, so their times no longer match the EDF after the short chunk.
- **Memory.** The EDF step reads a full 24 h of each chunk into memory at once. At 5000 Hz with four channels that is about 14 GB
  per chunk, and the data are held twice while joined, so a two-chunk animal needs about 55 GB free. Close other programs first.
  A three-chunk animal needs more. Allow several minutes, and about 7 GB of disk per two chunks.

## Inputs

| Input | Location | What it is |
|---|---|---|
| EDF chunks | `--dir` of the `edf` command | Every `.edf` shorter than the nominal length, except files whose name ends `_COMBINED`. |
| SWD chunks | `--dir` of the `swd` command | Every `.mat` file there, except `_COMBINED` ones. Each holds one `[start, stop]` row per SWD, in seconds. |
| Annotation chunks | `--dir` of the `annotations` command | Every `.txt` file there, except `_COMBINED` ones. Pinnacle exports: tab-separated, six header lines, then rows with a `Time From Start` column. |

## Settings

Each command is `ebb-combine <edf|swd|annotations> --dir <folder> [options]`. Run `ebb-combine <command> --help` for the full list.

| Option | Applies to | Meaning | Default | Change it when |
|---|---|---|---|---|
| `--dir` | all | The folder holding the files. Required. | – | – |
| `--fs` | edf | The recordings' sampling rate in Hz. Required. It is used to find which files are short, so it must be the files' real rate. | none (5000 for our recordings) | Your recordings were not acquired at 5000 Hz. |
| `--move-short-files` | all | After combining, move the original chunks into a subfolder, so only the combined files remain. Without it the chunks stay in the folder and Preprocess processes them too. | off | Add it. |
| `--short-dirname` | all | Name of that subfolder. | `short_files` | – |
| `--amount-hours` | all | Hours kept from each chunk. Use the same value for all three commands. | 24 | Keep 24: it makes the combined recording whole days, so no hour of the day is counted more than another in the PSDs. |
| `--nominal-hours` | edf | Recordings shorter than this are treated as chunks to combine. | 72 | Full-length recordings in your folder are shorter than 72 h. For a project with both 48 h and 72 h animals, use `--nominal-hours 48` so a lone 48 h recording is not mistaken for a chunk. |
| `--pattern` | all | A regular expression that picks the animal ID out of a file name. | the text before the first `_` | Your animal ID is not the first `_`-separated part. |
| `--overwrite` | all | Replace an existing `_COMBINED` file instead of stopping. | off | You are redoing a combination. |
| `--quiet` | all | Print less. | off | – |
| `--label-preference` | swd | The variable in the `.mat` file that holds the SWD times. If it is not there, the first variable is used. | `final_ts` | Never for our files (they use `DEL_ts`, which is picked as the first variable). |
| `--header-rows`, `--time-col`, `--delimiter` | annotations | The file layout. | 6, `Time From Start`, tab | The annotation export is not Pinnacle's default. |

## Fixed values

| Value | Fixed at | Meaning |
|---|---|---|
| What is kept | the first `--amount-hours` of every chunk | Anything after that in a chunk is dropped, from the EDF, the SWD times and the annotation rows alike. |
| Joined recording | continuous | The chunks are placed end to end. **The gap between one chunk's 24 h and the next chunk's start is not corrected**, so clock time within the combined file drifts from true clock time after each join (22 minutes for `CW0DC4` in the walkthrough). |
| Header | the first chunk's | Including the recording start date and time. Only the record count is rewritten. |
| Channels | all, in their original order | – |
| Output name | the first chunk's name plus `_COMBINED` | `<first chunk>_COMBINED.edf`, `.mat` or `.txt`, in the same folder as the first chunk. |
| SWD events | those that start within the kept hours | An event that straddles the cut keeps its start and has its end clamped to the cut. Times are then shifted by `chunk number × amount-hours`. |
| Annotation rows | those with a time before the kept hours | Times are shifted the same way. The other columns, including the wall-clock `Start Time` and `End Time`, are left as they were. |
| Files with no companion | SWD and annotation files are left alone | An animal that never restarted keeps its file. (An EDF with no companion stops the run instead.) |

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [Restarted recordings are combined, 24 h from each chunk](../decision_log.md#restarted-recordings-are-combined-24-h-from-each-chunk)

## What it does

For each animal with more than one chunk:

1. **Group** the chunks by animal ID.
2. **Order** them: EDFs by start time in the header, SWD and annotation files by the `_P###` number.
3. **Keep** the first 24 h of each chunk and **join** them. The SWD times and annotation times are shifted by 24 h per chunk.
4. **Write** the `_COMBINED` file. If one already exists the command stops unless you gave `--overwrite`.
5. **Move** the original chunks to `short_files/` if you gave `--move-short-files`.

Re-running skips files whose names already end `_COMBINED`.

## The commands

Run these from a terminal with the `ebb-dev` environment active. The three can be run in any order; skip the SWD and annotation
commands if you have none.

```bash
ebb-combine swd --dir /path/to/project/swd --move-short-files
```

```bash
ebb-combine annotations --dir /path/to/project/annotations --move-short-files
```

```bash
ebb-combine edf --dir /path/to/project --fs 5000 --move-short-files
```

The SWD and annotation commands take seconds. The EDF command reads and writes many gigabytes and can take several minutes.

## Outputs

| File | Contents |
|---|---|
| `<first chunk>_COMBINED.edf` | The joined recording: 48 h for two chunks, 72 h for three (at 24 h each). Same channels and start time as the first chunk. |
| `<first chunk>_COMBINED.mat` | The joined SWD times, under the same variable name as the input, sorted by start time. If no event falls in the kept hours, an empty file is written. |
| `<first chunk>_COMBINED.txt` | The joined annotation rows with shifted times, and the first chunk's header lines. If no row falls in the kept hours, **no file is written**. |
| `short_files/` | The original chunks, if you used `--move-short-files`. |

Nothing is recorded in `manifest.json`. The next step, Preprocess, simply finds the `_COMBINED` EDF among the files.

## Check your work

- Each restarted animal has one `…_COMBINED.edf` (and `.mat`, `.txt`) and the chunks are in `short_files/`.
- The project folder holds one EDF per animal.
- The combined EDF is 48 h or 72 h. In the walkthrough, `CW0DC4_P096_…_COMBINED.edf` has 172 800 one-second records, exactly 48.0 h
  (about 6.9 GB).

## If something goes wrong

- "No match found for token …": a short EDF has no companion. Move it out of the folder, or check the file names, or set
  `--nominal-hours` lower.
- "Pattern … did not match": the file name has no part the pattern can pick out.
- "Refusing to overwrite existing file": rerun with `--overwrite` to replace a previous `_COMBINED` file.
- "No `_P###` pattern found in …": an SWD or annotation chunk's name lacks `_P` and a number.
- The process is killed or the computer slows to a crawl: out of memory. Close other programs and run again.
- SWD times look wrong after combining: check that the `_P###` order of the SWD files matches the start order of the EDFs.

## Used by

Step 1 (Preprocess) processes the combined EDF like any other. The SWD and annotation files are used from steps 4b and 6 onward,
under the animal ID at the start of the combined name.

## Known limitations

- **A chunk shorter than 24 h is joined whole** in the EDF, but its SWD and annotation times are still shifted by a full 24 h,
  so they no longer match the EDF after that chunk.
- **Clock time drifts after each join.** The gap between one chunk's kept hours and the next chunk's start is not corrected. This
  affects the clock-aligned Sleep QC axes and the dark-period metrics for the data after each join.
- **No annotation file is written** when no annotation row falls in the kept hours. With `--move-short-files` the chunks are
  still moved, so the animal ends up with no annotation file.
- **SWD files with a `ts_` prefix.** ebb-viewer accepts SWD names that start `…ts_` before the animal ID, but `ebb-combine swd`
  groups files by the text before the first `_`, so such files are grouped under the wrong token. Rename them or pass `--pattern`.
