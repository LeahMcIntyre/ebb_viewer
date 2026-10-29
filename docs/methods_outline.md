# Methods outline

A bulleted skeleton for the methods section, in pipeline order. Built from
[decision_log.md](decision_log.md), [psd_methods.md](psd_methods.md),
[sleep_reclassification.md](sleep_reclassification.md),
[sleep_qc_and_exclusion.md](sleep_qc_and_exclusion.md) and the `analysis/` notebooks.
Values are as documented there. **[TBD]** marks something to fill in or confirm; the
numbers to report per dataset are collected at the end.

## 1. Recordings and preprocessing

- Acquisition
  - 4 channels: left frontal cortex (LFC), retrosplenial cortex (RSC), left somatosensory cortex (LSC), EMG. Identified by position (`EEG_1`–`EEG_4`).
  - Sampled at 5000 Hz; raw units µV (range ±8144 µV). **[TBD]** acquisition system, preamp model, hardware high-pass cutoff.
  - **[TBD]** animals, ages, genotypes, surgery, housing, light cycle (lights on 6 AM, ZT 0), time zone for clock alignment.
- Restarted recordings (`ebb-combine`)
  - First 24 h of each chunk, in start-time order, concatenated; 2 chunks give 48 h, 3 give 72 h.
  - Caveat: the real gap between chunks is ignored, so clock time drifts from true time by the restart offset.
  - Report how many animals were combined.
- Trim to whole days: largest of 48 h or 72 h that fits (shorter recordings rejected). Report n at each length.
- Downsample 5000 → 250 Hz (factor 20)
  - openseize polyphase resampling, Kaiser low-pass anti-alias filter (125 Hz cutoff, 112.5/137.5 Hz pass/stop edges, ≤0.1 dB passband loss, ≥40 dB stopband attenuation).
  - Max analyzable frequency 125 Hz.
- Output: one 250 Hz EDF per animal.

## 2. Sleep staging (SPINDLE)

- SPINDLE, run through SleepyRat, scores 4 s epochs as wake (w), NREM (n) or REM (r) and gives a per-epoch noise probability.
  - **[TBD]** SPINDLE citation, SleepyRat version and scoring date (not recorded in the project).
- Input: one channel combo for the whole project (LFC + RSC, chosen as best in earlier validation), plus EMG. Same combo for every animal so groups are comparable.
- Validation against hand scoring (`spindle-validation`: 40 files, 8 datasets, 2 raters, 49,025 epochs)
  - Raw SPINDLE agreement 89.4%; after reclassification and EMG gate 90.8%.
  - Limits to state: REM over-called (precision ~33%, recall ~94%); Wake→NREM claims confirmed ~70%; rater B agrees ~6 points less than rater A.
  - **[TBD]** channel-combo comparison (used older annotations; say so).

## 3. State reclassification

- Motivation: SPINDLE labels some wake artifacts as NREM, which chops bouts and inflates bout counts (fragmentation is a primary outcome). Only NREM → Wake changes are made.
- Artifact epoch: noise probability ≥ the file's threshold (default 0.5).
- Gap fill (radius 1): a NREM epoch becomes wake if it is an artifact epoch, or is clean but has an artifact epoch (any state) on both sides within 1 epoch.
- EMG gate, applied per file only when needed
  - Rule: light-period NREM bouts rise by more than 10% after gap fill.
  - Effect: a flip is kept only if the epoch's EMG RMS exceeds the median + 5 × MAD of the animal's EMG RMS over all SPINDLE-NREM epochs. The gate only cancels flips.
  - Choice of k = 5: on 12 annotated animals (5,406 epochs) 100% precision, 70.7% recall. Light period chosen as the window because it best predicted where the gate helps (Spearman ρ 0.83 vs. 0.58 for dark hours).
  - Thresholds chosen in exploration, not by formal optimization.
- Effect on validation: +641 correct epochs from gap fill (+1.3 points agreement; NREM precision 90.1% → 94.1%, recall unchanged); the gate adds 68.
- Original SPINDLE states are kept; the result is a separate `final_state` column that all analysis reads.
- **[TBD]** figure: NREM bout counts per hour, before vs. after reclassification (the central result for this step).
- **[TBD]** check: the reclassification light period is clock 06:00–19:59 (dark 20:00–05:59), while the sleep-by-hour analysis uses lights off at ZT 12 (18:00). Confirm they are meant to differ.

## 4. SWD handling (projects with spike-wave discharges)

- SWD start/stop times from the lab's MATLAB detector. **[TBD]** citation or description.
- Why: SPINDLE can score SWDs in wake or REM as NREM, which could create a genotype-dependent difference in apparent fragmentation.
- Optional review: every epoch overlapping an SWD (any overlap) was stepped through and corrected.
  - Rule: a misclassified SWD epoch is changed to the state the animal was in before and after the SWD.
  - **[TBD]** who reviewed; number of epochs reviewed and changed.
- Animals with no SWDs have an empty SWD file.

## 5. Quality control and exclusion

- Screening metrics from the reclassified states, computed per animal
  - Short (1–2 epoch) NREM bouts per hour (> 6), NREM bouts per dark hour (> 15), REM % (> 10), NREM % (< 30), Wake % (> 70), max REM % in a 2 h bin (≥ 35).
  - Cutoffs are screening aids, not validated criteria. Animals past any cutoff are flagged for review automatically.
  - **[TBD]** the wake cutoff is a placeholder, and REM = 10 was read from a plot.
- Review: each flagged animal inspected in the EEG/EMG viewer. The reviewer was blind to genotype.
- Exclusion: by judgment when EEG/EMG was very noisy or states looked wrong (e.g. heavy misclassification). A written reason is recorded for each.
- Excluded animals are computed but left out of the sleep and PSD analyses.
- **[TBD]** reviewer(s).

## 6. PSD estimation

- Inputs: 250 Hz EDF, `final_state`, noise probabilities, optional SWD and drink masks.
- State groups: wake, NREM, REM. A PSD per animal, channel and state.
- Artifact masks (boolean at 250 Hz; a sample flagged on any channel is masked on all)
  - Commutator: |x| > 2000 µV; events closer than 1 s merged; events > 10 samples extended 1 s after.
  - SD threshold: 180 s windows, per-channel z-score (commutator samples excluded from mean/SD), |z| > 5 flagged, flags within 0.5 s merged. **Wake only**, since it over-masked real NREM features such as spindles.
  - SPINDLE noise: epochs with noise probability ≥ 0.5 dropped.
  - SWD: intervals from the SWD files masked, no padding.
  - Drink (animals that needed it; see section 7): each event ±2 s, shifted by the per-animal video-to-EEG offset.
- Line-noise notch: 8th-order Butterworth bandstop 57–63 Hz, zero-phase, applied after the masks are computed so artifact detection sees unfiltered amplitudes.
  - Late vs. early order changed spectra by ≤1.5% outside the notch (Stxbp1 characterization set, 24 animals).
- Welch (openseize defaults): 0.5 Hz resolution (2 s segments), Hann window, 50% overlap, constant detrend, density scaling. Masked samples are removed (not zeroed) and the remainder streamed to Welch, so a segment can span a removed gap.
  - Units µV²/Hz.
- Report the fraction of each state's samples removed by each mask.

## 7. PSD review and drink-mask rerun

- Each PSD of an included animal was reviewed by eye; sidebands from drinking mark it `needs_drink_mask`.
- Drink events come from the lab's video-based detection network. **[TBD]** citation or description; offsets read from the PVFS file.
- Flagged animals were recomputed with identical parameters plus the drink mask, then checked by eye ("mask worked" or redo).
- Report how many animals needed the drink mask, and who reviewed.
- Animals could also be excluded at this stage (with a reason).

## 8. PSD analysis (`analysis/psd_analysis`)

- Low-frequency correction: 0.5–3.5 Hz bins multiplied by factors that undo the hardware roll-off. **[TBD]** source of the coefficients.
- Line-noise peaks bridged by interpolation: 56–64 Hz and 118–122 Hz.
- Normalized spectra: interpolated spectrum ÷ its own power from 1–100 Hz.
- Band power: trapezoid-rule area under the spectrum in 1–4, 4–8, 8–12, 12–30, 30–70 and 70–100 Hz, for raw and normalized spectra.
- **[TBD]** statistics (tests, corrections, software), which are not in the repo.

## 9. Sleep architecture analysis (`analysis/sleep_by_hour`)

- Computed from `final_state`.
- Each recording rotated so its first 6 AM (ZT 0) is position 0, then cut into 2 h bins (time zone `America/Chicago` for daylight saving).
- Per state and bin: fraction of time, number of bouts (unbroken runs), mean bout duration; plus whole-file values.
- **[TBD]** how bouts spanning a bin edge are counted.
- **[TBD]** statistics.

## 10. Software and reproducibility

- ebb: a refactor of EBB (Caudill, https://github.com/mscaudill/ebb), with SPINDLE integration, reclassification, SWD review, QC and a Qt GUI. **[TBD]** credit and what was kept.
- Dependencies: openseize (resampling, Welch), SleepyRat/SPINDLE; Python and package versions **[TBD]**.
- Project state in `manifest.json`; PSD parameters in `psd_params.json`. **[TBD]** data and code availability.
- Note: a run log is not written yet, so the trim choices and SPINDLE version are not recorded in the project.

## Numbers to report for each dataset

- Animals recorded, animals per group, 48 h vs. 72 h, animals combined from restarts.
- Animals EMG-gated, with the rule.
- Animals excluded, stage and reasons.
- Animals needing a drink mask.
- SWD epochs reviewed and changed (if applicable).
- Whether the dataset was processed before the 2026-05-12 cleanup sweep, or before reclassification (the PSD artifact examples in the log were).

## Gaps to close before drafting prose

- The **[TBD]** items above (most already tracked in [open_items.md](open_items.md)).
- Evidence still to link: artifact-masking notebook, drink-padding figure, bout counts before vs. after reclassification, SWD review counts.
- Statistics are the largest gap: nothing in the repo documents the tests used.
