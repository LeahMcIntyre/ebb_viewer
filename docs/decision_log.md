# Decision log

Why the pipeline works the way it does. Organized by pipeline stage; see
[documentation_plan.md](documentation_plan.md) for the full outline and the
entry template. Parameter values are in [psd_methods.md](psd_methods.md).

Confidence labels: **settled** (deliberate and checked), **inherited** (kept
from the pipeline this was built on, not independently re-evaluated),
**provisional**, **needs discussion**.

Sections for the other stages are not written yet.

---

## 1. Data acquisition and preprocessing

### Trim to whole days: 48 h or 72 h
- **Stage:** Preprocess
- **Chosen:** Trim each recording to the largest of 48 h / 72 h that fits (stop sample rounded up to a whole second). Recordings shorter than 48 h raise an error.
- **Alternatives:** Keep full-length recordings.
- **Why:** Analyses need whole days (multiples of 24 h) for both sleep and PSD. Recordings start at different times of day, so untrimmed files would over-represent some times of day in some animals and not others. 72 h is preferred because it gives more data. 48 h is used when that is all that is available.
- **For other users:** The app lets the trim targets be changed (down to 1 hour). The 48/72 h rule is this project's choice, not a requirement of the software.
- **Evidence:** None needed (design reasoning).
- **Confidence:** settled
- **Affects results?** Yes. State the trim rule and how many animals had 48 h vs. 72 h.
- **Where in code:** `src/ebb/preprocess/edf.py`
- **Revisit if:** A dataset has recordings between 48 and 72 h, or shorter than 48 h, that you would still want to use. Mixing 48 h and 72 h animals in one comparison is worth a sentence in the methods.

### Restarted recordings are combined, 24 h from each chunk
- **Stage:** Before Preprocess (command line: `ebb-combine`)
- **Problem:** Some 3-day recordings stopped early and were restarted, leaving one animal with several short EDFs.
- **Chosen:** Take the first 24 h of each chunk, in start-time order, and concatenate them (and shift the matching SWD and annotation files by 24 h per chunk). 2 chunks give 48 h, 3 give 72 h.
- **Why:** The analysis should cover 24 straight hours per chunk. If a 28 h chunk were combined with a 24 h one in full, some hours of the day would be represented three times in the PSDs and others twice. Taking exactly 24 h from each keeps every hour of the day equally represented.
- **Caveats to state:**
  - Only the first 24 h of each chunk is used, so a 28 h chunk loses 4 h.
  - Chunks shorter than 24 h are not handled; they would shift everything after them off the 24 h grid.
  - The real time gap between chunks is ignored, so clock time within the combined file drifts from true clock time by the restart offset. For `CW0DC4_P096` and `_P098` the second chunk started 22 minutes before the 24 h grid from the first chunk would put it. Sleep-by-hour bins use the first chunk's start time, so this matters for the hourly analysis. Clock drift is not handled. The number of animals combined can be reported.
  - EDFs are ordered by header start time, SWD and annotation files by their `_P###` number. These must agree.
- **Confidence:** settled
- **Affects results?** Yes, for every animal that was restarted. Report how many animals were combined.
- **Memory:** `combine_edf` reads each full 24 h chunk into memory (about 14 GB per chunk at 5 kHz, four channels) and holds the joined data twice. On a 48 GB machine the first attempt was killed (out of memory); after closing other programs it completed. The walkthrough result is exactly 48.0 h. 
- **Where in code:** `src/ebb/io/combine.py` (`ebb-combine edf | swd | annotations`)

### Sampling: 5000 Hz acquired, downsampled by 20 to 250 Hz
- **Stage:** Preprocess
- **Chosen:** 250 Hz.
- **Why:** Inherited. It covers the range of interest (nothing much above 100 Hz) and keeps storage manageable. 5000 Hz is the acquisition rate.
- **Units:** The raw EDF header lists µV for every EEG channel, which matches the 2000 µV commutator threshold.
- **Confidence:** inherited
- **Affects results?** Yes. The maximum analyzable frequency is 125 Hz.
- **Where in code:** `src/ebb/preprocess/edf.py`; `fs = 250` is hard-coded in several places.

### Anti-alias filter: openseize defaults
- **Stage:** Preprocess
- **Chosen:** openseize `resampling.downsample`: Kaiser low-pass, 125 Hz cutoff, 112.5/137.5 Hz pass/stop edges, ≤0.1 dB passband loss, ≥40 dB stopband attenuation.
- **Why:** Inherited. The defaults were accepted without evaluation.
- **Confidence:** inherited
- **Affects results?** Yes (methods should cite the filter).

### Channels: LFC, RSC, LSC, EMG
- **Stage:** Preprocess
- **Chosen:** Four channels, in this order, as in every dataset used so far.
- **Why:** That is the montage of the recordings. Channels are identified by position only: the raw EDF labels are `EEG_1` to `EEG_4`, and by lab convention channel 1 is LFC, 2 is RSC, 3 is LSC and 4 is EMG. Nothing in the pipeline checks or maps the names. It has not been tested with other montages.
- **Confidence:** settled for this lab's datasets; untested otherwise.
- **Risk:** A file with a different channel order would be silently mislabeled. Consider a check at preprocess time, or state the assumption prominently in the user guide.
- **Where in code:** `ch_names` constant.

### Animal ID is the first `_`-delimited token of the filename
- **Stage:** Preprocess and project setup
- **Chosen:** Take the animal ID from the first token of the EDF file name.
- **Why:** It is the lab's naming convention.
- **Known failure:** Putting animals from different time points into the same folder causes mix-ups, since IDs are repeated across time points. **Use one project folder per time point** and state this prominently in the user guide.
- **Confidence:** settled
- **Where in code:** `src/ebb/core/naming.py`

---

## 2. Sleep staging with SPINDLE

### Using SPINDLE for staging
- **Stage:** SPINDLE upload and download
- **Chosen:** SPINDLE (via SleepyRat) scores 4 s epochs as w / n / r.
- **Why:** Inherited. It is validated here against hand scoring: `spindle-validation` repo (server: `/Volumes/labs/PEDI/Xue2a/Members/Leah McIntyre/Pipeline_Research/spindle-validation`), summary in `spindle_validation_project/analysis/SUMMARY.md` (as of 2026-10-13; 40 files, 8 datasets, two raters, 49,025 compared epochs). Overall agreement with the raters: raw SPINDLE 89.4%, after reclassification and the EMG gate 90.8%.
- **Known limits from the validation:** REM may be over-called (precision about 33%, recall about 94%). Agreement from the most recent spindle validation differs from the first round of spindle validation. Wake→NREM transitions are confirmed in about 70% of SPINDLE claims. A few files account for most of the NREM-recall errors. Rater B agrees with SPINDLE about 6 points less than rater A. 
- **Confidence:** inherited, then validated
- **Affects results?** Yes.
- **Where in code:** `src/ebb/io/sleepyrat.py`, `src/ebb_viewer/pages/spindle_upload.py`

### One channel combo per project (e.g. LFC_RSC), not per animal
- **Stage:** Spindle write and project setup
- **Chosen:** The project has a single combo, stored in `manifest.json`, that is used to score every animal.
- **Alternatives:** Let the user pick the best combo per animal (the earlier Rerun page did this).
- **Why:** LFC + RSC performed best in earlier validation. Asking the user to decide per animal was too complicated, and comparing sleep between animals scored with different combos could be unfair.
- **Evidence:** TODO: link the slides with the combo comparison. They used older annotations, so state that.
- **Confidence:** settled
- **Affects results?** Yes.
- **Channels SPINDLE receives:** The EEG channels selected on the Spindle EDFs page plus the EMG, which is always included.
- **Where the combo is set:** Implicitly, on the Spindle EDFs page: writing the files stores it as the project combo. This is unclear to users (open item).

### Epoch length 4 s and the three states
- **Chosen:** Kept SPINDLE's 4 s epochs and w / n / r labels.
- **Confidence:** settled (not evaluated against alternatives)


## 3. State reclassification

Evidence lives on the server in `/Volumes/labs/PEDI/Xue2a/Members/Leah McIntyre/Pipeline_Research/ebb-research` (`nrem_reclass_project/`, `nrem_misclassification_archive/`) and in the `spindle-validation` repo, `/Volumes/labs/PEDI/Xue2a/Members/Leah McIntyre/Pipeline_Research/spindle-validation` (see section 2). Algorithm details: [sleep_reclassification.md](sleep_reclassification.md).

### Why reclassify at all: wake artifacts scored as NREM inflate fragmentation
- **Stage:** Reclassify
- **Problem:** SPINDLE often labels wake artifacts as NREM. Sleep fragmentation is a primary outcome, and spurious NREM calls chop wake and NREM bouts and raise bout counts. SPINDLE also sometimes scores SWDs as NREM. That second problem is **not addressed** by the reclassification (see the optional SWD review, section 4).
- **Scope:** One specific issue is addressed on purpose. The step only turns NREM into Wake, never anything else.
- **Evidence:** Validation repo notebooks 01 and 03 (in the server `spindle-validation` folder under `spindle_validation_project/analysis/`; reclassification adds 641 correct epochs, +1.3 points of agreement; precision for NREM rises from 90.1% to 94.1% while NREM recall is unchanged). Per-animal NREM bout counts by hour, before vs. after reclassification: `/Volumes/labs/PEDI/Xue2a/Members/Leah McIntyre/Pipeline_Research/ebb-research/nrem_reclass_project/bout_count_figures/` (made by `make_bout_count_plots.py`; PNGs in `by_animal/<dataset>/`, datasets PHP_pre, RNA_KO, Stxbp1_characterization). Per-file ranking and hourly change: `nrem_reclass_project/goal2_cross_dataset/reclass_change_by_hour.ipynb` (same `ebb-research` folder). *Not yet opened; confirm these show the fragmentation effect and pick a representative example for the paper.*
- **Confidence:** settled
- **Affects results?** Yes (main one for sleep outcomes).

### Gap fill, radius 1
- **Chosen:** A NREM epoch becomes wake if it is an artifact epoch, or if it is clean and has an artifact epoch (any state) within 1 epoch on both sides.
- **Why:** A NREM epoch sandwiched between two artifact epochs is very likely artifactual too.
- **Alternatives:** Radius 2, tested.
- **Evidence:** `nrem_reclass_project/emg_noise/emg_gap_radius_vs_annotations.ipynb`, `*_gap2.ipynb` (server `ebb-research` folder); validation repo notebook 03 (what-if with radius 2).
- **Confidence:** settled
- **Where in code:** `GAP_RADIUS = 1` in `src/ebb/process/nrem_reclass.py`.

### EMG gate: cancels gap-fill flips without EMG evidence, applied only when needed
- **Problem it solves:** For some animals SPINDLE's noise flag is too aggressive and marks clean NREM as artifact. Gap fill then relabels that clean NREM as wake, which *adds* false NREM breaks.
- **Chosen:** A flip is kept only if the epoch's EMG RMS exceeds the animal's median + 5 × MAD (computed over all epochs SPINDLE called NREM, including the artifact ones). The gate only cancels flips and never creates new ones.
- **When it applies:** Decided per file by a rule. If the number of light-period NREM bouts after gap fill rises by more than 10% compared with before, the flips are chopping bouts, and the gate is applied. The light period is when the animal moves least, so more bouts there signals that real NREM was relabeled.
- **Why not apply it to every file:** The gate is imperfect for animals with a poor EMG signal.
- **Threshold choice (k = 5, 10% tolerance):** Chosen during the exploration in `nrem_reclass_project/emg_noise/` (server `ebb-research` folder). `k = 5` was picked by sweeping against the annotated Wake/NREM census (`emg_rms_wake_vs_nrem.ipynb`) and checking the real function against human verdicts: 100% precision and 70.7% recall pooled over 5,406 epochs (11 animals), i.e. zero false positives on real NREM at the cost of missing about 3 in 10 real Wake epochs (`EMG_HANDOFF.md` §1.6, §2.1). A looser `k = 3` gave 99.3% / 73.8% (9 false positives). The k sweeps are `emg_rms_gate_k_sweep_vs_annotations.ipynb` (k = 2.5, 3, 4) and `emg_gate_k_sweep_reclass_change_by_hour.ipynb`, with k = 2.5 variants. Note that the per-animal figures in `emg_gap_radius_vs_annotations.ipynb` and the by-hour heatmaps in `emg_gate_reclass_change_by_hour.ipynb` are drawn at **k = 3**, not the shipped k = 5. Both notebooks end with a "Regenerate at the shipped k (k = 5)" section; use those versions for the paper. Pooled over the annotated animals at gap radius 1, k = 5 gives 0 false positives and 62.1% recall (k = 3: 9 false positives, 66.5%); at radius 2, 1 false positive and 70.3% recall (k = 3: 75.1%).
- **Why the gate is judged on the light period (resolved):** `emg_gap_radius_vs_annotations.ipynb` (section "Does the time window matter?") tests which bout-count window best predicts where the gate helps, on the 12 annotated animals (Spearman rho against measured net benefit): dark hours 0.58, whole file 0.59, **light hours 0.83**. Across all 141 animals, dark flags 10 candidates and light 9 (7 in common; light and whole-file give identical sets). That is why the code uses the light period. `nrem_reclass_project/PLAN.md` and `compute_gate_candidate_buckets.py` bucket on dark hours first (the earlier choice) and then add light and whole-file columns for this comparison. The ±10% tolerance is the bucketing threshold of `goal2_cross_dataset/run_reclassification.py`, reused as the gate rule. The validation repo shows the gate adds 68 correct epochs.
- **Figures:** per-animal false negatives/positives and real-Wake/real-NREM outcome bars, gap-fill vs. gate (k = 3), radius 1 vs. 2: `emg_gap_radius_vs_annotations.ipynb`. NREM bout-count delta by hour, gap-fill vs. gap-fill + gate (k = 3, radius 1), for PHP_pre, RNA_KO, Stxbp1_characterization, Stxbp1-vglut2_CKO and Stxbp1-vgat_CKO (star = gate candidate; dark hours shaded): `emg_gate_reclass_change_by_hour.ipynb` (radius 2: `..._gap2.ipynb`). The figures above the k = 3 sections are k = 3; the closing k = 5 section of each notebook redraws them at the shipped k = 5. Candidates come from `results/gate_candidate_buckets.csv` (`compute_gate_candidate_buckets.py`).
- **Confidence:** provisional for the thresholds (chosen in exploration, not by a formal optimization)
- **Affects results?** Yes. State in the methods how many animals were gated, and the rule.
- **Where in code:** `EMG_K`, `FRAGMENTATION_TOL`, `EMG_CHANNEL` in `src/ebb/process/nrem_reclass.py`.
- **Revisit if:** An animal with a bad EMG is gated and the result looks wrong.

### Keep both the original and the reclassified states
- **Chosen:** The reclassified states are written to new columns (`reclass_state`, `final_state`) and the SPINDLE columns are left untouched. All analysis reads `final_state`.
- **Why:** To keep a record of what SPINDLE called and what was changed.
- **Where in code:** `STATE_COLUMNS`, see [sleep_reclassification.md](sleep_reclassification.md) and `PITFALLS.md`.

---

## 4. SWD review

### Optional epoch-by-epoch review of epochs that overlap an SWD
- **Stage:** SWD Review (project opt-in)
- **Problem:** SPINDLE can score SWDs that occur in wake or REM as NREM. If SWD burden differs by genotype, this could create a genotype-specific difference in measured sleep fragmentation that is really misclassification. The reclassification step does not address it (section 3).
- **Chosen:** Step through every epoch that overlaps an SWD in each file (a quick pass) and correct the states of epochs that were misclassified. This makes sure that any fragmentation difference between genotypes is not driven by genotype-dependent misclassification.
- **Rule for corrections:** A misclassified SWD epoch is changed to the state the animal was in before and after the SWD.
- **Why optional:** Only needed for models and projects with SWDs (the `swd_review_enabled` project setting).
- **Evidence:** TODO: a figure or count showing how many NREM epochs overlapped an SWD and were changed. The server `spindle-validation` folder has notebooks `swd_in_short_nrem_bouts.ipynb` and `swd_in_spindle_nrem_disagreements.ipynb` that look relevant. *Not opened yet.*
- **Confidence:** settled
- **Affects results?** Yes. State in the methods that SWD epochs were manually reviewed, by whom, and the correction rule.
- **Where in code:** `src/ebb_viewer/edf_viewer/swd_review.py`, `src/ebb_viewer/pages/swd_review.py`. Results are the `swd_reclassification` column and `final_state`. See [sleep_reclassification.md](sleep_reclassification.md) §5.

### SWD times come from the lab's MATLAB detector
- **Chosen:** Each animal has a `.mat` file of SWD start/stop times (seconds) produced by the lab's MATLAB-based detection method. An epoch counts as an SWD epoch if any part of it overlaps an interval.
- **Evidence:** TODO: a citation or description of the detection method for the methods section.

### Every animal needs an SWD file; the preferred answer for "no SWDs" is an empty file
- **Chosen:** If an animal has no SWD file and you don't want one, create an empty `.mat` file. The app also has a "Confirm no SWD" (`swd_waived`) button, but an empty file is better.
- **Why:** The SWD mask in the PSD step also looks for the file, so an empty file keeps that step working, and it records the decision in the data folder, where the project can be reproduced, and not only in the manifest.
- **Possible follow-up:** The docs and UI currently present the waive button as an equal option. Consider making the empty file the documented default, and possibly removing the waive button.

### SWD masking in PSDs: no separate policy needed
- The old open question about whether to mask or include the transition state in PSDs was removed from `TODO.md`. The existing optional SWD mask in PSD compute stays as it is (no padding; masks the intervals supplied).

---

## 5. Quality control and exclusion

Details of the statuses and what each step does with an excluded animal: [sleep_qc_and_exclusion.md](sleep_qc_and_exclusion.md).

### Flagging metrics and thresholds
- **Stage:** Sleep QC (Overview)
- **Chosen:** Six annotation-free metrics computed from `final_state`, with a default threshold each. An animal past a threshold is highlighted so the reviewer can flag it for review:

  | Metric | Threshold | Origin |
  |---|---|---|
  | Short (1–2 epoch) NREM bouts per hour | above 6 | the validation notebook's 400 per file (about 5.6 per hour for a 72 h recording), rounded; per hour so recordings of different lengths compare |
  | NREM bouts per dark hour | above 15 | validation notebook |
  | REM % (whole file) | above 10 | read off the notebook's REM plot |
  | NREM % (whole file) | below 30 | validation notebook |
  | Wake % (whole file) | above 70 | **placeholder** |
  | Max REM % in a 2-hour bin | at least 35 | validation notebook |

- **Why:** Chosen from `spindle_validation_project/analysis/file_flagging_metrics.ipynb` in the server `spindle-validation` folder (`/Volumes/labs/PEDI/Xue2a/Members/Leah McIntyre/Pipeline_Research/spindle-validation`) and related notebooks in that folder (for example `file_metric_correlations.ipynb`, `file_qc_ranking.ipynb`).
- **Caveat (in the code's own words):** The cutoffs are "starting points, not validated cutoffs". The wake cutoff is a placeholder and the REM cutoff was read off a plot. If the thresholds are described in the paper, say they are screening aids for the reviewer and that the decision to exclude is made by inspecting the data.
- **Confidence:** provisional
- **Affects results?** Indirectly: they only prompt a review. The exclusion decision is the reviewer's.
- **Where in code:** `src/ebb/process/sleep_flagging.py`; project-level overrides in `flag_thresholds` in `manifest.json`.

### Exclusion criteria: noisy or wrong-looking data, by judgment
- **Chosen:** Exclude an animal when the sleep data do not look right and something about the EEG or EMG looks very noisy or wrong, for example when the review shows a lot of misclassification. Animals past a threshold should generally be excluded, but the user uses their own judgment.
- **Reason required:** Every exclusion needs a written reason, appended to the animal's notes.
- **Confidence:** settled as a policy. There are no fixed numeric criteria, so a reviewer's judgment is part of the method.
- **Affects results?** Yes. The methods should report the number of animals excluded, at which stage, and the reasons.

### Animals past a threshold are flagged for review automatically
- **Chosen:** When Sleep QC loads its metrics (from the reclassified states), every animal that has no status yet and is past any threshold is set to `needs_review`, with the metrics as the reasons. Animals already flagged, OK or excluded are never changed, so repeating it is harmless. A red line on the page names them.
- **Why:** Any animal past a threshold should be looked at, so the reviewer should not have to find and flag it by hand. The thresholds are still screening aids; the decision to exclude is the reviewer's.
- **Not done without reclassified states:** the metrics would be SPINDLE's original ones.
- **Where in code:** `Manifest.auto_flag_for_review`, `_auto_flag_for_review` in `pages/sleep_qc_visualizer.py`.
- **Confidence:** settled

### The Needs Attention card shows when the EMG gate was applied
- **Chosen:** A flagged animal's card on Home carries `[EMG gate]` (amber, in brackets) when `reclass_gate_applied` is true, the same tag the Sleep QC legend uses. The gate changes how an animal's states were corrected, which matters when reviewing it.
- **Where in code:** `_make_review_card` in `pages/home.py`.

### Reviewer is blind to genotype
- **Chosen:** The person doing the QC review is blind to genotype.
- **Why:** So that exclusions cannot be influenced by the expected result.
- **How:** File names generally do not carry genotype, and the review screens show animal IDs, so the review is blind as long as the reviewer does not know which IDs belong to which group. (Some files in the walkthrough do include a tag such as `KO` in the name; if a project's files do, rename them or have someone else assign IDs.)
- **Confidence:** settled

### Excluded animals are kept and marked, not dropped
- **Chosen:** Excluded animals are still processed (including PSD compute). Finalize marks them (`excluded` / `exclusion_reason`, `excluded_animals.csv`) and the analysis notebooks leave them out.
- **Why:** For flexibility and completeness: compute everything, so the data can be looked at later or still be thrown out.
- **Known gaps:** The mask export includes excluded animals unmarked. See the known gaps in [sleep_qc_and_exclusion.md](sleep_qc_and_exclusion.md).
- **Confidence:** settled

---

## 6. PSD estimation

### Welch settings: 0.5 Hz resolution, Hann window, 50% overlap, constant detrend
- **Stage:** PSD estimation
- **Chosen:** 0.5 Hz frequency resolution (2 s segments at 250 Hz), Hann window, 50% overlap, constant detrend, density scaling.
- **Alternatives:** Other frequency resolutions were tried.
- **Why:** Inherited from the existing pipeline (openseize defaults; the app passes no spectral arguments). Other resolutions were tried informally and showed no difference in the results.
- **Evidence:** None retained. The comparison runs were lost. **Do not cite a figure for this.** If a reviewer asks, rerun a resolution comparison on one dataset and keep it.
- **Confidence:** inherited
- **Affects results?** Yes, so it goes in the methods.
- **Where in code:** openseize `spectra.estimators.psd` defaults, called from `src/ebb/process/psd_compute.py`.
- **Revisit if:** A reviewer questions the resolution, or the analysis needs finer low-frequency detail.

### 60 Hz notch: 8th-order Butterworth bandstop, 57–63 Hz, zero-phase
- **Stage:** PSD estimation (filtering)
- **Chosen:** Bandstop 57–63 Hz, order 8, forward–backward filtering. Optional, on by default.
- **Alternatives:** A narrower notch at 60 Hz alone. An order-4 filter was also compared.
- **Why:** A notch at 60 Hz alone did not remove much of the line noise. Some spectra had very large line noise, especially the PHP dataset. The wider stopband lets the PSD be interpolated over 56–64 Hz, and that range is enough to bridge the gap.
- **Evidence:** Server folder `/Volumes/labs/PEDI/Xue2a/Members/Leah McIntyre/Pipeline_Research/line_noise`, copied from the `line_noise` git branch. The branch is local (commit `a815a54` is not on `origin`). Notebooks `psd_raw_vs_order8_vs_order4.ipynb`, `psd_raw_vs_notch_php_pre.ipynb`, `psd_raw_vs_notch_php_pre_order4.ipynb`, `psd_raw_vs_notch_php_pre_order4_redo.ipynb` (PHP_pre, halfwidths 2, 3 and 4 Hz, order 8 vs. 4) and `psd_compute_notch.py`; the cached PSDs are in `notch_trials/`. Stxbp1 characterization comparison (24 animals, WT vs. MUT, raw vs. notch, interpolated): `stxbp1_notch_compare/stxbp1_char_notch_filter_compare.ipynb`. These use the research module, which notches **before** the masks and sweeps the halfwidth. The shipped pipeline notches after the masks (next entry). Merged into `dev` via `feature/notch_filter` (commits 46304da, f1bf247, d74dbd0, e4383fa). *To confirm: that these are the final analysis.*
- **Confidence:** settled
- **Affects results?** Yes.
- **Where in code:** `src/ebb/process/psd_compute.py`. Interpolation range in `psd_graph_widget.py` (`_NOTCH_INTERP_RANGE = [56, 64]`, versus `[58, 62]` when the run was not notch-filtered).
- **Revisit if:** A dataset has line noise outside 57–63 Hz, or a different hardware setup changes the noise profile.

### The notch runs after the artifact masks are computed
- **Stage:** PSD estimation (filtering and masking order)
- **Chosen:** Compute the commutator and SD masks on the unfiltered signal, then filter only the values that go into the PSD.
- **Alternatives:** Filter first, then compute the masks.
- **Why:** The artifact masking had already been analyzed and its parameters set. Filtering first could change how the masks behave in ways that hadn't been studied. Running the notch afterward leaves the mask behavior as validated.
- **Evidence:** Commit 46304da ("applied after artifact masks"); a815a54. The comparison of the two orders is in `/Volumes/labs/PEDI/Xue2a/Members/Leah McIntyre/Pipeline_Research/line_noise`: `compute_stxbp1_char_notch_late_psds.py` (uses `batch_estimate_late_notch` in `psd_compute_notch.py`; output `psd/jerk_jump_swd_notch_57_63_late/psds_LFC_RSC.pkl`) and the "Late Compute" source in `stxbp1_notch_compare/stxbp1_char_notch_filter_compare.ipynb`. **Result (2026-10-26, Stxbp1 characterization, 24 animals, 216 animal/state/channel spectra, interpolated):** The notch-minus-raw difference figure is from the late run (WT dip about −0.21 µV²/Hz, MUT about −0.13; about −2.4% and −2.1% at the dip). Late and early agree inside 56–64 Hz (mean difference 0.1% or less). Outside the notch the late run matches the raw (no-notch) spectra almost exactly (mean |difference| 0.0015 µV²/Hz below 55 Hz), whereas the early run shifts them slightly (0.0129; wake spectra about 0.11% on average, NREM about 0.01%, REM unchanged), because filtering first changes the SD mask. Late versus early differs by 1.5% at most outside the notch. So the order matters little for the reported PSDs; the late order leaves the validated mask behavior alone, as intended.
- **Confidence:** settled
- **Affects results?** Yes.
- **Where in code:** `src/ebb/process/psd_compute.py`
- **Revisit if:** The mask parameters are re-tuned.

### No high-pass filter in PSD analysis; an inverse filter compensates low frequencies at review
- **Stage:** PSD estimation and review
- **Chosen:** No high-pass or detrending beyond Welch's constant detrend. High-pass filtering is applied automatically by the recording system. An inverse filter (coefficients on 0.5–3.5 Hz) corrects the low frequencies it attenuates.
- **Why:** The hardware high-pass already removes slow drift at acquisition. The inverse filter restores the amplitude it rolls off at the lowest frequencies.
- **Evidence:** *Missing. The source of the coefficients is undocumented* (there is a TODO in `psd_graph_widget.py`). Needs the preamp model and the derivation.
- **Confidence:** needs discussion until the coefficients are documented
- **Affects results?** Yes, if reported PSDs include the correction.
- **Where in code:** `INVERSE_FILTER` and `FILTER_RANGE` in `src/ebb_viewer/widgets/psd_graph_widget.py`.
- **Scope (confirmed from the code):** In the PSD review plot, the inverse filter and the interpolation are toggles applied to a copy of the data at display time. The stored PSD files, `psds_final.pkl` and the Excel export contain the **uncorrected** PSDs. The correction is applied **in the analysis**: `analysis/psd_analysis.ipynb` (via `psd_utils.records_to_df`) multiplies the 0.5–3.5 Hz bins by the same factors before anything is plotted or summarized, and interpolates the line noise before computing band power. The `INTERP_RANGES` setting defaults to 56–64 Hz and 118–122 Hz, which is right for runs that used the 60 Hz notch filter (the default); it must be changed to 58–62 Hz and 118–122 Hz for runs computed without the notch. The setting is explicit in the Settings cell, with a comment, and the notebook prints the ranges it used. The notch only covers 60 Hz, so 120 Hz keeps the narrower range.

### Masked samples are removed, not zeroed
- **Stage:** PSD estimation
- **Chosen:** Drop masked samples and stream the remainder to Welch, so a 2 s segment can span a removed gap.
- **Why:** Inherited from the existing behavior.
- **Evidence:** None.
- **Confidence:** inherited
- **Affects results?** Yes (small, unmeasured). State it in the methods.
- **Where in code:** `src/ebb/process/psd_compute.py`
- **Revisit if:** A reviewer asks about discontinuities, or if masking removes a large fraction of an animal's data. `*_out_frac` shows the fractions.

### State groups: wake, nrem, rem by default; sleep and all also offered
- **Stage:** PSD estimation
- **Chosen:** Wake, NREM and REM are the groups used. Sleep (n + r) and all (w + n + r) are available in the app.
- **Why:** The extra groups are there for flexibility for other users. Our analyses use wake, NREM and REM only.
- **Confidence:** settled for the three states. Settled that the others are unused here.
- **Affects results?** Methods should state only the three states used.
- **Where in code:** `src/ebb/process/state_presets.py`
- **Open questions:** See `TODO.md` on REM appearing in multiple groups, and the SD-threshold rule for lumped groups.

### SPINDLE confidence filter (`s_prob`): never evaluated, removed
- **Stage:** PSD estimation
- **Chosen:** No class-probability filter. The `s_prob` option was exploratory and was never evaluated, so it was removed (commit `c24a2dd`, 2026-10-19).
- **Why:** Not evaluated, and not wanted as an option.
- **Confidence:** settled
- **Affects results?** No. It was off in every analysis.

### Commutator mask: |x| > 2000 µV, 1 s merge, 1 s pad after events longer than 10 samples
- **Stage:** PSD estimation (artifact masking)
- **Chosen:** Flag samples above 2000 µV. Merge flagged samples closer than 1 s, and extend events longer than 10 samples by 1 s after their end.
- **Why:** All three values were inherited. 2000 µV is high enough that it catches only artifacts, and it catches all of the commutator artifacts. The merge and pad values were kept because they seemed sufficient.
- **Evidence:** TODO: link the artifact-masking notebook.
- **Confidence:** inherited (the threshold also checked in the notebook; *to confirm*)
- **Affects results?** Yes.
- **Where in code:** `src/ebb/masking/threshold.py`. The merge radius, pad and minimum length are hard-coded.
- **Revisit if:** A recording system has a different amplitude range. The hard-coded values don't scale with a different sampling rate (see `TODO.md`).

### SD threshold: 5 SD, 180 s windows, 0.5 s merge, wake only
- **Stage:** PSD estimation (artifact masking)
- **Chosen:** In each 180 s window, z-score each channel (commutator-masked samples excluded from the mean and SD) and flag samples with |z| > 5. Merge flags within 0.5 s. Apply to wake samples only.
- **Alternatives:** Applying the SD mask to NREM and REM as well.
- **Why:** 5 SD caught enough artifact in wake. The 180 s window was inherited and made theoretical sense. Applied to NREM it masked out too much, including real features such as sleep spindles, so it is applied only to wake.
- **Evidence:** TODO: link the artifact-masking notebook (the NREM over-masking and the 5 SD choice).
- **Confidence:** settled for 5 SD and wake only. The 180 s window is inherited.
- **Affects results?** Yes. It is the main reason wake and sleep PSDs are treated differently.
- **Where in code:** `src/ebb/masking/threshold.py`, `src/ebb/process/psd_compute.py`
- **Open questions:** `TODO.md` has the rule for lumped groups (sleep, all), where SD applies only to the wake portion.

### SPINDLE noise cutoff: epochs with noise probability ≥ 0.5 are dropped
- **Stage:** PSD estimation (artifact masking)
- **Chosen:** 0.5
- **Why:** It is SleepyRat's default and worked well in use. It was also tested in the artifact-masking notebook and gave the best balance of how much it masks.
- **Evidence:** TODO: same notebook.
- **Confidence:** settled
- **Affects results?** Yes.
- **Where in code:** `src/ebb/masking/spindle.py`

### Drink mask padding: each drinking event dilated ±2 s
- **Stage:** Drink-mask rerun
- **Chosen:** Dilate each drinking event by 2 s on either side, upsample to 250 Hz, and shift by the per-animal video→EEG offset.
- **Why:** The event timing from the video is not precise, and the padding caught more of the artifact.
- **Evidence:** TODO: a figure showing the artifact with and without padding, if there is one.
- **Confidence:** settled (*to confirm that it was checked against the artifact*)
- **Affects results?** Yes, for animals rerun with the drink mask.
- **Where in code:** `src/ebb/masking/events.py`
- **Where the events come from:** The drink-event files (1 Hz `.npy`) are made outside this pipeline, with the lab's network that detects drinking events from the video exported from the PVFS file. **TODO:** cite or describe that network for the methods.
- **Offsets:** The per-animal offset is the time from the start of the recording to the start of the video, read from the animal's PVFS file and saved in the offsets CSV (`Animal,Offset`).

### Drink artifacts are flagged by eye, not automatically
- **Stage:** PSD review
- **Chosen:** The reviewer flags `needs_drink_mask` in the PSD visualizer by looking at the spectrum.
- **Alternatives:** An automatic detector. This was never considered.
- **Why:** The artifact shows up as sidebands in the spectrum, which are easy to recognize by eye, so manual flagging seemed appropriate.
- **Evidence:** None. It was a judgment call and not a comparison.
- **Confidence:** provisional (no automatic alternative was ever tried)
- **Affects results?** Yes: which animals get the drink mask depends on reviewer judgment. Say so in the methods, and record who reviewed.
- **Where in code:** `src/ebb_viewer/pages/psd_visualizer.py`, `drink_mask.py`
- **Revisit if:** There are enough animals that manual flagging becomes inconsistent, or a reviewer asks for a reproducible criterion.

---

## 8. Finalization and export

### A sealed `psds_final.pkl` marks "this is the file to use for analysis"
- **Stage:** Finalize
- **Chosen:** Finalize copies the latest PSD file (the drink-mask version when there is one) to `psds_final.pkl` under `psd/<run_name>/`. It also marks excluded animals in the sealed file (`excluded` / `exclusion_reason`, plus `excluded_animals.csv`).
- **Why:** The sealing step dates from when a project could have several channel combos. It now has a different value: it tells the user which file to analyze. Drink-mask reruns write to separate files and never overwrite the originals.
- **Naming (decided):** The file stays named `psds_final.pkl`. It already sits in `psd/<run_name>/`, and the notebooks and `psd_export.py` look for that name. Project, run and date are not embedded in the file.
- **Confidence:** settled
- **Where in code:** `seal` function in `src/ebb/process/psd_compute.py` (around line 710), `src/ebb_viewer/pages/finalize.py`.

### Finalize waits until every animal is reviewed
- **Chosen:** Finalize stays unavailable while any animal is unreviewed, flagged, or waiting for drink-mask verification.
- **Why:** So the user can tell when they are done and what is still left to do.
- **Confidence:** settled

### Channel merge step: no longer exists in the code
- **You said:** The merge step helps when there are drink masks, but you were not sure.
- **What the code shows:** There is no `psds_channel_merged.pkl` anywhere in `src/` any more. The drink-mask rerun is overlaid as `psds_<combo>_drink.pkl`, and Finalize takes that version if present. [psd_methods.md](psd_methods.md) §7 still describes the merged file and is out of date.
- **Action:** Update `psd_methods.md` §7 and the `CLAUDE.md` line on `psd/<RUN>/psds_<COMBO>.pkl` to describe the files that are actually written.

### Mask export is for analysis outside the pipeline
- **Stage:** Export Masks
- **Chosen:** Export the artifact masks so that someone can analyze the data elsewhere with the same exclusions applied.
- **Known gap:** Excluded animals are exported unmarked. For the intended use, mark them or leave them out; this is not decided.
- **Where in code:** `src/ebb/process/mask_export.py`, `src/ebb_viewer/pages/export_masks.py`.

### What you would need to reproduce a result from raw data
There is no run log (see `TODO.md`, "Run log / settings provenance"). Today someone would need:
1. The trim (48 h or 72 h) and the downsampling step.
2. The SPINDLE channel combo used.
3. Whether SWD review was done and the SWD files.
4. The reclassification step, including which animals the EMG gate was applied to (`reclass_gate_applied` in the manifest).
5. The PSD parameters (`psd_params.json`).
6. Which animals were excluded and why (the manifest and `excluded_animals.csv`).
7. Which animals needed drink masks, and the drink masks and offsets CSV (`drink_masks/`).

Most of it lives in `manifest.json`, `psd_params.json` and the project folders. Two things are not recorded anywhere: the trim and downsampling choices per file, and the SPINDLE scoring date or version. A run log or a "project summary" file written at Finalize could capture all seven items in one place. This list is also the checklist for the methods section.

- **Confidence:** needs discussion (a design decision on provenance)

---

## 9. Sleep-by-hour analysis

### A notebook, not a GUI page
- **Stage:** Sleep analysis (after Finalize)
- **Chosen:** Two notebooks in `analysis/` (each also as a script): `sleep_by_hour.ipynb` (copy it, edit the Settings cell, Run All) and `sleep_by_hour_walkthrough.ipynb` (the same calculation explained step by step).
- **Why:** A notebook is more reusable. The user can see how the numbers are computed, and can get and save the plots and tables. The quick-run notebook is for running your own data (copy and go); the walkthrough is for someone who wants to understand how the data are used and aligned.
- **Output:** `<project>/sleep_analysis/` with Prism-ready workbooks (`prism_sleep_by_hour.xlsx`, `prism_sleep_whole_file.xlsx`), tidy CSVs and PNG plots.
- **Confidence:** settled

### Groups can be typed or read from a CSV
- **Stage:** Analysis notebooks (PSD analysis, sleep by hour, walkthrough)
- **Chosen:** Besides a typed `GROUPS` dictionary, each notebook accepts `GROUPS_CSV`, the path to a CSV in either of two layouts: one row per animal (`animal`, `group` columns), or one column per group with the animal IDs below the group name. The layout is detected from the header.
- **Recommended layout:** One row per animal. Each animal appears once, so a duplicate assignment is easy to see (and is an error), and the file can be sorted and filtered. The one-column-per-group layout is accepted because it is quick to type and matches Prism's layout.
- **Where in code:** `read_groups_csv` in `analysis/psd_utils.py`. The two sleep notebooks are self-contained, so each carries an identical copy; a test checks that the copies match.
- **Confidence:** settled

### Time bins: 2-hour bins aligned to clock time, starting at 6 AM
- **Chosen:** Rotate each recording so its first 6 AM (lights on, ZT 0) is position 0 and cut it into 2-hour bins. Lights off is ZT 12. All of these are settings (`BIN_HOURS = 2`, `BEGIN_HR = 6`, `DARK_ONSET_ZT = 12`).
- **Why:** Clock-aligned bins are how similar analyses are done in the literature. Each recording starts at a different time of day, so the start times (read from the EDF header) are needed to align files to each other. They have not caused problems.
- **Time zone:** The notebook's default is `America/Chicago`, to handle daylight saving changes inside a recording. This is a lab-specific default, so it is a setting that someone else must change. State it in the user guide.
- **Confidence:** settled
- **Affects results?** Yes (bin width and ZT alignment go in the methods).
- **Still to confirm:** How a bout that spans a bin boundary is counted. I haven't checked the notebook for this.

### Metrics: fraction of time in state, bout count, bout duration
- **Chosen:** For each state (wake, NREM, REM) and bin: `frac_time` (fraction of the bin), `n_bouts` (unbroken runs) and mean bout duration. Plus one number per animal and state for the whole file.
- **Priority:** Bout count was the main outcome of interest. It has not yet been looked at after reclassification, which is the point of the whole reclassification step (section 3), so that comparison is the next important figure.
- **Input states:** `final_state` (the reclassified states). `STATE_COLUMN = "rawstate"` gives the original SPINDLE scoring for comparison, and excluded animals are left out unless `INCLUDE_EXCLUDED = True`.
- **Confidence:** settled for the metrics

---

## 10. Software and architecture choices

Most of this section is drafted from the code, `CLAUDE.md`, `PITFALLS.md` and `REVIEW_PROGRESS.md`. Items marked **(you)** need your reasons.

### Processing library and GUI are separate packages
- **Chosen:** `ebb` is a pure processing library with no GUI. `ebb_viewer` is the Qt6 application that drives it.
- **Why:** The processing can be used from scripts and notebooks without the GUI (for example `scripts/run_psd_estimation.py` and the sleep notebooks). **(you)** to confirm this was the reason.
- **Where:** `src/ebb/`, `src/ebb_viewer/`

### The manifest is the single record of pipeline state
- **Chosen:** `manifest.json` holds each animal's status (Sleep QC, PSD, exclusion and notes, SWD progress, gate decision) plus the project's channel combo and settings. It is written atomically (temp file, then rename).
- **Rules that protect it:** Statuses change only through manifest methods; PSD status exists only while Sleep QC is `ok`; an exclusion needs a reason; `Manifest.build_from_standard` syncs new files from disk without overwriting existing flags. See `PITFALLS.md`.
- **Why:** One place to see what each animal still needs, and a way for the pages to coordinate. **(you)**

### One channel combo per project
- Described in section 2. The change from per-animal combos to one project combo is why older docs and migration code mention "combos" and "Rerun".

### Relationship to upstream EBB
- **Chosen:** The project began as a refactor of EBB by Matt Caudill (https://github.com/mscaudill/ebb) with additions.
- **What was added here:** Thresholding and masking additions, SPINDLE integration, reclassification, SWD review, QC and exclusion, the GUI. **(you)** to describe precisely what was kept and what was rewritten.
- **Action:** `README.txt` still says "NEED TO CREDIT/COMMUNICATE WITH ORIGINAL AUTHOR" and "NEED TO FIX". Settle that before the paper and before sharing the code, and cite EBB in the methods.

### Working conventions
- **No legacy compatibility code:** Delete migration shims and old-format readers instead of tidying them, because there is one user and one deployment and old files can be regenerated. (The one remaining exception is marked TEMPORARY in `manifest.py`.)
- **Branching:** Feature branches come off `dev` and merge back with `--no-ff`; `main` is the release branch.
- **Cleanup sweep:** A five-phase code review ended 2026-05-12. About 25 real bugs were fixed, mostly in the PSD and Sleep QC pages, and the test suite grew from 257 to 511 tests (`REVIEW_PROGRESS.md`). Results from before the sweep may have been computed with the old behavior. **(you)** if any dataset in the paper was processed before the sweep, rerun it or say so.

### Testing
- **Current:** Automated tests (`pytest`) cover masking, preprocessing, PSD computation, reclassification, exclusions and GUI pieces, plus a notebook test.
- **Gaps:** See `TODO.md` ("Testing gaps"). There is no end-to-end test on real data; the validation repo is the real-data check for the staging and reclassification.

---

## Open items

Moved to [open_items.md](open_items.md), grouped by what is needed (your answer, evidence to find, decisions, small changes).
