# Step 6. PSD Computation

Terms are defined in the [glossary](../glossary.md).

## Purpose

Estimate a power spectral density (PSD) for every animal, channel and sleep-state group, using
only the parts of the recording that are free of artifacts. The result is a set of per-animal
spectra that the review, drink-mask and finalize steps work from.

## Before you run

- Step 5 (Sleep QC) has given every animal a decision: `ok` or `excluded`. Excluded animals are
  computed too and are marked at Finalize.
- `standard/*PROCESSED.edf` and `spindle_outputs/<COMBO>/*.csv` exist, and the CSVs have been
  reclassified (step 4). PSDs read `final_state` only.
- Optional files, only for the masks you turn on:
  - SWD mask: one `.mat` per animal in `swd/` (an empty file means "no SWDs"). **Every** animal
    needs one or the run is blocked.
  - Annotation mask: one Pinnacle annotation file per animal (`.txt`, `.csv` or `.tsv`) in a
    folder you choose. Animals without a file are still computed, without this mask.
- The drink mask is **not** applied here. It is added later, on step 8, for flagged animals only.

> **In our lab.** The SWD `.mat` files come from the lab's MATLAB SWD detector. Annotation files
> are exported from Pinnacle, where jerks and jumps were labelled.

## Inputs

| Input | Location | What it is |
|---|---|---|
| Preprocessed EDF, one per animal | `standard/*PROCESSED.edf` | 250 Hz recording. Only the animals that also have a CSV are processed. |
| State CSV, one per animal | `spindle_outputs/<COMBO>/*.csv` | Gives the state of every 4 s epoch (`final_state`) and the SPINDLE artifact probability (`noise_prob`). |
| SWD file, one per animal (optional) | `swd/*.mat` | Start and stop times of SWDs, in seconds. Matched to animals by the ID in the file name. |
| Annotation file, one per animal (optional) | any folder you pick | Pinnacle annotation events. Matched by animal ID. If two files share an ID, the last one found is used. |
| Sleep QC decisions | `manifest.json` (`sleep_qc`) | Decides which animals may run: all must be `ok` or `excluded`. |

## Settings

Everything below is saved with the run in `psd/<RUN>/psd_params.json`. **Restore defaults** resets
States and all mask sections; it does not reset Channels, Sampling freq or Run name.

### What to compute

| On-screen label | Meaning | Unit | Default | Allowed range | Change it when | Saved as |
|---|---|---|---|---|---|---|
| States to Compute: Wake | One PSD from wake epochs | tick | on | – | – | `states` |
| States to Compute: NREM | One PSD from NREM epochs | tick | on | – | – | `states` |
| States to Compute: REM | One PSD from REM epochs | tick | on | – | – | `states` |
| States to Compute: Sleep (NREM+REM) | One PSD over NREM and REM epochs pooled together | tick | off | – | You want a single sleep spectrum | `states` |
| States to Compute: All (Wake+NREM+REM) | One PSD over every epoch pooled together | tick | off | – | You want an all-states spectrum | `states` |
| Channels | Which EEG channels to compute: LFC (0), RSC (1), LSC (2). **A sample flagged on any selected channel is removed from all of them**, so unticking a channel also changes which samples the others keep. | tick | all three | at least one | Rarely | `channels` (indices) |
| Sampling freq (Advanced) | Sampling rate of the EDFs. The run fails if an EDF's rate differs. The ↻ button reads it from the first EDF in `standard/`. | Hz | 250 | 1 – 100 000 | Never for our data | `fs` |
| Run name | Folder under `psd/` that holds the results. Letters, digits, `-` and `_`, up to 64 characters. Re-using a name overwrites that run's files and clears its PSD review decisions (a confirmation is asked). | text | `default` | – | You want to keep several runs side by side | – (folder name) |

### Artifact masks

| On-screen label | Meaning | Unit | Default | Allowed range | Change it when | Saved as |
|---|---|---|---|---|---|---|
| Commutator: amplitude limit | A sample is flagged when its absolute amplitude exceeds this. Catches commutator and movement spikes. | µV | 2000 | 0 – 50 000 | Never without a reason | `comm_value` |
| SD threshold: threshold | A sample is flagged when it is more than this many standard deviations from the window mean. Applied to wake samples only (see What it does). | σ | 5 | 1 – 20 | Never without a reason | `nstd` |
| SD threshold: window | Length of each window in which the mean and SD are estimated. | s | 180 | 1 – 6000 | Never without a reason | `winsize` |
| SD threshold: merge gap | Flagged samples closer together than this are merged into one artifact. | s | 0.5 | 0 – 60 | Never without a reason | `radius` |
| SPINDLE noise: probability | An epoch is dropped when SPINDLE's artifact probability is at or above this. | probability | 0.5 | 0 – 1 | Never without a reason | `noise_thresh` |
| 60 Hz notch filter | Removes power-line noise from the signal that enters the PSD. Applied after the amplitude masks are computed. | tick | on | – | Only to compare without the filter | `apply_notch` |

### Event masks

| On-screen label | Meaning | Unit | Default | Allowed range | Change it when | Saved as |
|---|---|---|---|---|---|---|
| SWD mask: No SWD mask / Mask out SWDs | Remove SWD intervals. "Mask out" is unavailable until `swd/` has `.mat` files. | choice | No SWD mask | – | You want SWDs excluded (we do) | `use_swd_mask`, and `swd_mode` (`none` / `mask_out`) |
| Annotation mask: Apply annotation mask | Remove time around annotated events. | tick | off | – | You want jerks and jumps removed (we do) | `ann_enabled` |
| Annotation directory | Folder holding one annotation file per animal. | path | none | existing folder | – | `ann_dir` |
| Keywords | Comma-separated words matched against each event's label. Not case-sensitive. | text | empty | at least one when the mask is on | – | `ann_keywords` |
| Match mode: Contains / Exact | Contains: a label matches if it contains the keyword. Exact: the whole label must equal the keyword. | choice | Contains | – | Labels share a stem that you do not want matched | `ann_match_mode` |
| Pad before | Extra seconds masked before each matching event. | s | 0 | 0 – 3600 | The event's duration was not annotated | `ann_pad_before` |
| Pad after | Extra seconds masked after each matching event. With 0, only one sample (4 ms) is masked. | s | 0 | 0 – 3600 | The event's duration was not annotated | `ann_pad_after` |
| Hour window: Restrict to clock-time window | Keep only samples inside the listed clock-time windows. Use it for separate light and dark PSDs. | tick | off | – | – | `hw_enabled` |
| Windows (start–end hour) | One or more windows of the day. A window whose end is earlier than its start wraps midnight. Windows must not overlap. | hour of day | none | 0 – 23 | – | `hour_windows` |
| Days | All days, or specific 0-based recording-day numbers (comma-separated). | list | all | – | – | `selected_days` |
| Drink mask | Hidden on this page. Saved as off. | – | off | – | – (used on step 8) | `use_drink_mask` (always `false` after this step) |

## Fixed values

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|
| Commutator merge radius | 1 s | Flagged samples closer than this are joined into one event. | `COMMUTATOR_RADIUS_SEC` |
| Commutator pad | 1 s | Events longer than the minimum are extended by this after their end. | `COMMUTATOR_PAD_SEC` |
| Commutator minimum event | 0.04 s | Shorter events (single spikes) are not extended. | `COMMUTATOR_MIN_TO_PAD_SEC` |
| Notch centre and width | 60 Hz ± 3 Hz (stopband 57–63 Hz) | Frequencies removed by the notch. The page says the range "is fixed for now". | `_NOTCH_CENTER_HZ`, `_NOTCH_HALFWIDTH_HZ` |
| Notch filter | 8th-order Butterworth bandstop, run forward and backward (zero phase) | Filter design. | `_NOTCH_ORDER` |
| SPINDLE epoch | 4 s | Length of each state label; each label is repeated 1000 times (4 s × 250 Hz) to cover the samples. | `winsize=4` in `estimate_psd` |
| State source | `final_state` | The only state column read. A CSV without it raises `NotReclassifiedError`. | `ANALYSIS_STATE_COLUMNS` |
| PSD method | Welch, via openseize `estimators.psd` | The page passes no spectral arguments, so openseize defaults apply: 0.5 Hz resolution (2 s, 500-sample segments), Hann window, 50% overlap, constant detrend, density scaling. | – |
| Masked samples | removed, not zeroed | Surviving samples are joined into one stream before Welch, so a 2 s segment can span a removed gap. | – |
| SD mask scope | wake samples only | For the "All" group, only the wake part is SD-masked. NREM-only, REM-only and Sleep spectra do not use it. | `mask &= ~wake_sub_mask \| sd_threshold_mask` |
| Processing order | commutator and SD masks are computed on the unfiltered signal; the notch is applied afterwards | Artifact detection sees true amplitudes; only the values entering the PSD are filtered. | – |
| Workers | all available cores, one animal per process | Speed only. | `ncores=None` |
| Annotation event time | the annotation file's "Time From Start" column, measured from the recording start | An event is masked where its time falls in the recording. | `keyword_mask` |


The amplitude limit (2000 µV), the SD settings (5 σ, 180 s, 0.5 s) and the SPINDLE noise cutoff (0.5) are explained,
with their evidence, in the last three entries listed below.

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [Welch settings: 0.5 Hz resolution, Hann window, 50% overlap, constant detrend](../decision_log.md#welch-settings-05-hz-resolution-hann-window-50-overlap-constant-detrend)
- [60 Hz notch: 8th-order Butterworth bandstop, 57–63 Hz, zero-phase](../decision_log.md#60-hz-notch-8th-order-butterworth-bandstop-5763-hz-zero-phase)
- [The notch runs after the artifact masks are computed](../decision_log.md#the-notch-runs-after-the-artifact-masks-are-computed)
- [No high-pass filter in PSD analysis; an inverse filter compensates low frequencies at review](../decision_log.md#no-high-pass-filter-in-psd-analysis-an-inverse-filter-compensates-low-frequencies-at-review)
- [Masked samples are removed, not zeroed](../decision_log.md#masked-samples-are-removed-not-zeroed)
- [State groups: wake, nrem, rem by default; sleep and all also offered](../decision_log.md#state-groups-wake-nrem-rem-by-default-sleep-and-all-also-offered)
- [SPINDLE confidence filter (`s_prob`): never evaluated, removed](../decision_log.md#spindle-confidence-filter-s_prob-never-evaluated-removed)
- [Commutator mask: |x| > 2000 µV, 1 s merge, 1 s pad after events longer than 10 samples](../decision_log.md#commutator-mask-x--2000-µv-1-s-merge-1-s-pad-after-events-longer-than-10-samples)
- [SD threshold: 5 SD, 180 s windows, 0.5 s merge, wake only](../decision_log.md#sd-threshold-5-sd-180-s-windows-05-s-merge-wake-only)
- [SPINDLE noise cutoff: epochs with noise probability ≥ 0.5 are dropped](../decision_log.md#spindle-noise-cutoff-epochs-with-noise-probability--05-are-dropped)

## What it does

For each animal, in parallel:

1. **Read the states.** Each 4 s epoch's `final_state` label is expanded to one label per sample.
   Each selected state group (Wake = `w`, NREM = `n`, REM = `r`, Sleep = `n`+`r`, All = `w`+`n`+`r`) becomes a sample mask.
2. **Commutator mask.** Flag samples above the amplitude limit on any selected channel; join flags
   closer than 1 s; extend events longer than 0.04 s by 1 s.
3. **SD mask.** Cut the recording into windows. In each window, find each channel's mean and SD
   leaving out the commutator-flagged samples, flag samples more than `nstd` SDs away, and join flags
   closer than the merge gap. A sample flagged on any channel is flagged for all.
4. **SPINDLE noise mask.** Drop epochs whose artifact probability is at or above the cutoff.
5. **Notch.** Unless switched off, filter the signal around 60 Hz.
6. **Event masks, if on.** SWD intervals (no padding), annotation events matching the keywords
   (with their padding), and samples outside the hour windows.
7. **Combine.** A sample is kept only if every mask keeps it (commutator, SPINDLE noise, SWD,
   annotation, hour window). The SD mask is added per group as described under Fixed values.
8. **Estimate.** For each state group, keep the surviving samples, run Welch per channel, and store
   the result. A group with no surviving samples (for example an animal with no REM) is skipped
   without a message to the user.
9. **Save.** Write all records to `psds_<COMBO>.pkl`, then `psd_params.json`. Clear this run's PSD
   review decisions in the manifest first, so old decisions are not shown against new data.

## Outputs

### `psd/<RUN>/psds_<COMBO>.pkl`

A pickled list with one record (a dict) per animal and state group.

| Key | Type | Meaning |
|---|---|---|
| `path` | path | The animal's preprocessed EDF. The animal ID is the first `_`-delimited part of its name. |
| `channels` | list of int | Channel indices computed (0 = LFC, 1 = RSC, 2 = LSC). |
| `behavior` | tuple | `("threshold", "<group>")`, for example `("threshold", "wake")`. The group is one of `wake`, `nrem`, `rem`, `sleep`, `all`. |
| `freqs` | array | Frequency of each bin, in Hz. 0.5 Hz spacing. |
| `psd` | array | Power at each frequency, in µV²/Hz. Shape: `(channels, frequencies)`, one row per channel in the order of `channels`. |
| `n_estimates` | int | Number of Welch segments averaged. A low number means little clean data for that state. |
| `comm_out_frac` | float | Fraction of this state's samples removed by the commutator mask. |
| `sd_out_frac` | float | Fraction removed by the SD mask. 0 for groups without wake (SD not used). For "All", the fraction of the wake part. |
| `spindle_out_frac` | float | Fraction removed by the SPINDLE noise mask. |
| `swd_out_frac` | float | Fraction removed by the SWD mask. 0 if the mask was off. |
| `ann_out_frac` | float | Fraction removed by the annotation mask. 0 if off or the animal had no file. |
| `used_swd`, `used_drink`, `used_ann` | bool | Whether that mask was **configured** for this record. They do not say it removed anything; check the `*_out_frac`. |
| `used_windows` | list of (start, end) | ISO date-times of each hour window actually used, clipped to the recording. Empty if no hour window. |

An `*_out_frac` is `NaN` when the state has no samples at all.

### `psd/<RUN>/psd_params.json`

The exact settings of the run. Keys are those in the Saved as column above, plus:

| Key | Meaning |
|---|---|
| `fs` | Sampling frequency used. |
| `channels` | Channel indices computed. |
| `swd_mode` | `mask_out` or `none`. Same information as `use_swd_mask`; both are written. |
| `ann_enabled`, `ann_dir`, `ann_keywords`, `ann_match_mode`, `ann_pad_before`, `ann_pad_after` | Annotation settings. If the annotation mask was on, the keywords are saved as one comma-separated string. |
| `use_drink_mask` | `false` here. Step 8 changes it. |

Later steps rebuild the run from this file, so do not edit it by hand.

### Recorded in `manifest.json`

The step clears the run's `psd_status` entries. `psd_status` is stored per run: `{run name: status}`.

### On the page

| Item | Meaning |
|---|---|
| THIS RUN | One-line summary of states, channels, sampling rate and each mask that is on. Read it before running. |
| READINESS | ✓ ready, ✗ blocks the run, ⚠ warning only. Checks: standard EDFs exist; every animal has an `ok`/`excluded` Sleep QC decision; state CSVs exist; SWD files exist for every animal (when the SWD mask is on); SWD review finished (warning); annotation directory and keyword set (when on); annotation files exist for every animal (warning); a state and a channel selected. |
| Log | One line per animal as it finishes, then "Saved". Warns about animals with no state CSV (skipped) and lists excluded animals ("computed anyway"). |

## Check your work

- `psd/<RUN>/` holds `psd_params.json` and `psds_<COMBO>.pkl`.
- The log ends with "PSD computation finished" and the green bar says "PSDs computed — ready for PSD review".
- Every animal you expect is in the log. An `ok` animal with no state CSV is skipped with a warning.

## If something goes wrong

- Run PSD Pipeline is greyed out: read the red ✗ lines in READINESS. Each has an **Open …** button to the page that fixes it.
- An EDF's sampling rate differs from the setting: the run fails for that file. Set Sampling freq to match, or check preprocessing.
- `NotReclassifiedError`: a CSV has no `final_state`. Run step 4.
- An animal is missing a PSD for one state: that animal has no surviving samples in that state. This is silent, so check `n_estimates` and which groups appear.
- **Re-running a run that already has drink masks.** Computing under an existing run name rewrites `psds_<COMBO>.pkl` and clears the run's decisions, but leaves the old `psds_drink.pkl` and `psds_<COMBO>_drink.pkl`. Finalize seals `psds_<COMBO>_drink.pkl` when it exists, so it would seal the old PSDs for every animal. Apply the drink masks again after recomputing (step 8), or use a new run name. The log says previously applied drink masks "are preserved"; that refers to the old files, not to up-to-date PSDs.

## Used by

Step 7 (PSD Visualizer) reads `psds_<COMBO>.pkl`. Step 8 (Drink Mask) rebuilds this run from
`psd_params.json`. Step 9 (Finalize) seals the result as `psds_final.pkl`.

## Known limitations

- **A state with no surviving samples is skipped silently.** No record and no message is produced for that animal and state, so check
  `n_estimates` and which groups appear.
- **Re-running a run that has drink masks leaves the old drink files** (see If something goes wrong).
- **The notch and the interpolation use different ranges.** The notch removes 57–63 Hz. The PSD Visualizer's interpolation bridges
  56–64 Hz with the notch on and 58–62 Hz without.
- **Hour windows are whole hours (0–23)** on the page, though the code accepts decimal hours.
- **`psd_params.json` saves `swd_pad: 0`**; SWDs are always masked without padding here.
