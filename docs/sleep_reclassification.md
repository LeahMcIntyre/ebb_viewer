# Sleep reclassification and SWD review

How ebb turns SleepyRat's per-epoch sleep states into the `final_state` column that every
analysis step reads, and what the optional SWD review adds. This describes the single-combo
line (`dev`). The older multi-combo / rerun version lives on `dev-multi-combo` and does not have
any of this.

## 1. The idea

SPINDLE (via SleepyRat) scores every 4 s epoch as wake / NREM / REM and flags epochs it thinks are
artifacts. Artifact flags chop long NREM bouts into pieces. Reclassification repairs that, once,
up front, and writes the result into the CSV. Everything downstream (Sleep QC, PSDs, masks,
exports) then reads one resolved column, `final_state`, so the analysis is identical whether or
not a project also did the optional SWD review.

```
raw EDFs → 1 Preprocess → 2 Spindle EDFs → 3 Spindle Upload (SleepyRat labels → CSVs)
        → 4 Reclassify        writes reclass_state + final_state
        → 4b SWD Review       optional, writes swd_reclassification, updates final_state
        → 5 Sleep QC → 6 PSD Computation → 7 PSD Visualizer → 8 Drink Mask → 9 Finalize
                                                              → 10 Export Masks
```

## 2. Columns in `spindle_outputs/<combo>/<animal>_*.csv`

| Column | Written by | Meaning |
|---|---|---|
| `rawstate` (old format) or `state` (new format) | SleepyRat | Original SPINDLE state: `w` / `n` / `r`. In the old format `state` holds artifact codes, so `rawstate` wins when both exist. |
| `noise_probs` / `noise_prob`, `threshold` | SleepyRat | Artifact probability per epoch, and the cutoff (first non-empty `threshold`, else 0.5). |
| `reclass_state` | Reclassify page | State after gap fill and the EMG gate. |
| `swd_reclassification` | SWD Review (optional) | Blank except SWD epochs you reviewed and epochs you edited (see §5). |
| **`final_state`** | Reclassify, then SWD Review | `swd_reclassification` where non-blank, else `reclass_state`. **The only state column analysis reads.** |

The first time ebb rewrites a CSV it copies the untouched SleepyRat file to
`spindle_outputs/<combo>/_original/` (never overwritten). Writes are atomic (`.tmp` rename).
To undo reclassification entirely, copy the files back from `_original/`.

## 3. The reclassification algorithm

Code: `src/ebb/process/nrem_reclass.py`. Per file, in 4 s epochs, starting from the original
states:

1. **Artifact epochs.** An epoch is an artifact when its noise probability is at or above the
   file's threshold.
2. **Gap fill** (`gapfill_state`, radius 1). Only **NREM** epochs can change, and they change to
   **wake**: an NREM epoch flips if it is itself an artifact, or if it is clean but has an
   artifact epoch (of any state) within 1 epoch on **both** sides. Neighbors past the ends of the
   file count as clean.
3. **Gate decision.** Count the file's NREM bouts in the **light period** (clock hours outside
   20:00 to 05:59, from the EDF start time; a bout belongs to the period its first epoch is in)
   before and after gap fill. If the count rose by **more than 10%**, scattered flips are
   chopping long bouts, so the flips need EMG evidence.
4. **EMG gate** (only when step 3 says so). Read the EMG channel (channel 3, 250 Hz) of the
   preprocessed EDF and take its RMS per epoch. A flip is kept only if its epoch's RMS is above
   `median + 5 × MAD` of the animal's EMG RMS over every epoch SPINDLE called NREM (artifact
   epochs included, since that flag is what is in question). `MAD` is the plain, unscaled median
   absolute deviation. The gate only ever **cancels** flips; it never creates new ones.
   If the EDF is shorter than the CSV, the missing epochs have no RMS and their flips are
   cancelled.
5. `reclass_state` is the gated state where the gate applied, else the gap-filled state.

The EMG channel is read only for files where the gate applies, which is the slow part. Most
files never need it.

The manifest records the gate decision per animal in `reclass_gate_applied` (`None` = not run,
`True` / `False` = gate applied / not needed). The CSV is what says whether an animal *is*
reclassified (it has a `final_state` column); the manifest only adds how.

Constants (`nrem_reclass.py`): `GAP_RADIUS = 1`, `FRAGMENTATION_TOL = 0.10`, `EMG_K = 5.0`,
`EPOCH_SEC = 4`, `EMG_CHANNEL = 3`.

### The Reclassify page (`4. Reclassify`)

`pages/reclassify.py`. Runs `reclassify_dir_to_csv` on `spindle_outputs/<combo>/` with the
EDFs in `standard/`, in a background thread, and shows per animal: reclassified or not, whether
the gate applied, and light-period NREM bouts before → after. It is safe to re-run. If any animal
already has a Sleep QC flag, it asks first, because the flags were judged on the old states; it
never resets them. The home page's "4. Reclassify" row checks the CSV headers (not the manifest),
so a CSV re-downloaded from SleepyRat shows as not reclassified.

## 4. How downstream steps use it

Analysis is **forced** onto `final_state`; there is no silent fallback to the original states.
A CSV without `final_state` raises `NotReclassifiedError` ("run the Reclassify step"):

- `masking.state` (PSD compute, Export Masks), `build_state_intervals`, the sleep metric
  functions in `sleep_compute`, and sleep export all read `final_state`.
- **Sleep QC** opens on the reclassified states. A **Show original** button switches both views
  to the original SPINDLE states for comparison. Animals without `final_state` stay original and
  are counted in a label; if none are reclassified, the page says so and the button is disabled.
  EMG-gated animals are tagged `[EMG gate]` (from the manifest).
- **EDF viewer:** the "R" pill beside the state bar starts lit (reclassified states); click it
  for the original bar.
- **Export Masks** writes `state_column: final_state` into each export's meta file.
- **Scripts** (no GUI, no Reclassify step) can opt out explicitly:
  `estimate_psd(..., state_columns=ebb.io.spindle_csv.STATE_COLUMNS)` (also `batch_estimate`).
  The GUI never passes it. For masks directly: `ebb.masking.state(path, labels, columns=STATE_COLUMNS)`.
- The class-probability filter (`s_prob` / `state_prob`) was removed: SPINDLE's `class_prob_*`
  describe the original call, so it would have dropped reclassified epochs.

`final_state` is deliberately **not** in `STATE_COLUMNS` (the *input* to reclassification).
Reading it there would make a re-run read its own output.

## 5. SWD review (optional, `4b. SWD Review`)

Spike-wave discharges (SWDs) can make the reclassified state of nearby epochs wrong. The review
lets you step through the epochs that overlap an SWD and fix them.

**Opt-in.** A checkbox on the page sets `swd_review_enabled` at the top level of
`manifest.json`. Off means nothing changes and the home guide shows "Not enabled".

**SWD epochs.** SWD intervals come from `swd/*.mat` (`[start_s, stop_s]`, key `DEL_ts`, else the
first key; `ebb.masking.events.swd_intervals`). A 4 s epoch is an SWD epoch if **any part**
overlaps an interval (touching an edge exactly does not count). Files are matched to animals by
`find_swd_file` (`pipeline/swd_review.py`), the same rule PSD compute uses, so `Mice-1256.mat`
and `JK1011_P063_DEL_ts.mat` both work.

**The window** (`edf_viewer/swd_review.py`, opened with **Review…**):

- Shows the trace (10 s view by default) with SWD intervals shaded, the state bar, and the
  selected epoch highlighted.
- `w` / `n` / `r` set the selected epoch's state. `Space` / `Shift+Space` (or the buttons) go to
  the next / previous SWD epoch. Double-click selects any epoch, so neighbors on either side
  of an SWD can be edited too. `←` / `→` scroll.
- An SWD epoch counts as **reviewed** when you edit it, move on from it, or press **Save** while
  it is selected. The epoch the window opens on does not count until then.
- **Save** writes `swd_reclassification` and the recomputed `final_state`. Closing with unsaved
  changes asks first. Reopening resumes at the first unreviewed SWD epoch.

**The column rule.** `swd_reclassification` is non-blank only for (a) reviewed SWD epochs (the
chosen state, or the current `reclass_state` if left alone) and (b) any epoch you edited, SWD or
not. Unreviewed SWD epochs stay blank, so the column doubles as the progress record, and
`final_state` simply falls back to `reclass_state` there.

**Every animal needs an SWD file** (an empty `.mat` is fine and means "nothing to review"), **or
your confirmation that it has none**. Animals without a file show "Needs file or confirmation"
with a **Confirm no SWD** button (`swd_waived` in the manifest; Undo is available).

**Progress and warnings.** The page shows `—` / `In progress (k of N)` / `✓ N of N` from the CSV
column and keeps `swd_reviewed` / `swd_total` in the manifest in step (a cache so the home page
and warnings never read CSVs). While review is on and unfinished (animals missing a file or not
fully reviewed): Sleep QC shows an orange line, and the PSD pipeline, Finalize (sleep export and
finalize) and Export Masks ask for confirmation (Cancel is the default). Nothing is blocked,
because unreviewed epochs keep a valid state.

**Re-running Reclassify keeps your SWD work.** Both old columns are still in the CSV at that
point, so an entry equal to the *old* `reclass_state` is an unedited copy and follows the new
`reclass_state`; an entry that differs is a real edit and is kept. Then `final_state` is
recomputed (`refresh_swd_after_reclass`).

## 6. Manifest fields

| Field | Where | Meaning |
|---|---|---|
| `reclass_gate_applied` | per animal | `None` not run / `True` EMG gate applied / `False` not needed |
| `swd_review_enabled` | top level | project opt-in for SWD review |
| `swd_reviewed`, `swd_total` | per animal | reviewed / total SWD epochs (cache; CSV is the source of truth). `swd_total` is `None` until known; `0` means an empty SWD file |
| `swd_waived` | per animal | user confirmed this animal has no SWD file and needs none |

## 7. Code map

| Area | Files |
|---|---|
| Algorithm, CSV write | `ebb/process/nrem_reclass.py` (`reclassify_file`, `reclassify_dir_to_csv`), `ebb/io/spindle_csv.py` (`write_columns`, column constants, `NotReclassifiedError`, `read_analysis_states`) |
| SWD epochs and columns | `ebb/masking/events.py` (`swd_intervals`), `ebb/process/swd_review.py` (`swd_epoch_flags`, `build_swd_column`, `merge_final_state`, `refresh_swd_after_reclass`, `save_swd_review`) |
| Pages | `pages/reclassify.py`, `pages/swd_review.py`, `pages/sleep_qc_visualizer.py`, `pages/home.py` (pipeline guide) |
| Viewer | `edf_viewer/swd_review.py` (window), `edf_viewer/mask_builder.py` (`state_masks_from_epochs`), `edf_viewer/state_bar.py` (highlight) |
| Shared helpers | `pipeline/swd_review.py` (`find_swd_file`, `swd_review_gaps`), `widgets/swd_warning.py` (confirm dialog), `pipeline/manifest.py` |

## 8. What changed (summary of the refactor)

- The project is single-combo: one `Manifest.combo`, no per-animal runs, no rerun page. The
  multi-combo / rerun version is kept on `dev-multi-combo`.
- New Reclassify step before Sleep QC that persists NREM reclassification into the CSVs; the old
  on-the-fly Sleep QC toggle was replaced by reading `final_state`.
- New optional SWD review (library, review window, page, warnings).
- All analysis reads `final_state`; PSD estimation has a script-only opt-out; `s_prob` removed.
- Export Masks now finds SWD files named `<animal>.mat` (it used to miss them) and asks before
  exporting while SWD review is incomplete.

## 9. Known gaps

- `docs/pipeline_flow.md` and the other flow diagrams still show the multi-combo / rerun
  pipeline and have no Reclassify or SWD step.
- Export Masks skips the SWD mask without saying so when an animal has no SWD file (PSD compute
  refuses to run in that case).
- The review window loads the whole EDF, like the normal viewer; chunked reads would help on
  very long recordings.
- The PSD SWD mask policy question in `TODO.md` ("decide policy on TS") is separate from this
  work; the SWD review only changes state labels, not PSD masking.
