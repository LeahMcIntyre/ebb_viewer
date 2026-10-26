# Open items for the documentation

Collected from the decision-log interviews. Tick items off here, and update the matching entry in [decision_log.md](decision_log.md) when you do. The log's entries mark each place with a TODO or **(you)**.

## A. Need your answer or knowledge

- [ ] **Upstream EBB.** What did you keep from EBB (Caudill) and what did you rewrite? Fix the credit lines in `README.txt`. *(log §10)*
- [ ] **Pre-sweep data.** Were any paper datasets processed before the 2026-05-12 cleanup sweep? If so, rerun or note it. *(log §10)*
- [ ] **Reasons for the architecture** marked **(you)**: library/GUI split, manifest. *(log §10)*
- [x] SPINDLE receives the selected EEG channels plus the EMG (always included, per the Spindle EDFs page). Update log §2 "Still to confirm".
- [ ] **Inverse filter.** Source of the coefficients (preamp model and derivation). (It is display-only: stored and exported PSDs are uncorrected. Confirm that is intended for the paper's figures.) *(log §6)*
- [ ] **Bin edges.** How is a bout that spans a 2-hour bin edge counted? *(log §9)*
- [ ] **Gate rule.** Light period (code) or dark hours (PLAN.md)? Where did the 10% tolerance come from? *(log §3)*


## B. Evidence to find or link

- [ ] Artifact-masking notebook (commutator, SD, SPINDLE noise cutoff). *(log §6)*
- [ ] Line-noise notebooks on the `line_noise` branch: confirm they are the final analysis. *(log §6)*
- [ ] Channel-combo comparison slides (older annotations). *(log §2)*
- [ ] Bout-count-by-hour figures in `ebb-research/nrem_reclass_project/bout_count_figures/`: open and choose an example. *(log §3)*
- [ ] **Bout counts before vs. after reclassification** (the central result for the reclassification step). The validation repo's `sleep_by_hour_reclass.ipynb` may already have it. *(log §9)*
- [ ] SWD review: count of changed epochs (validation repo `swd_in_*` notebooks). *(log §4)*
- [ ] Citation or description of the lab's MATLAB SWD detector. *(log §4)*
- [ ] Description or citation of the network that detects drinking events from video (for the methods). *(log §6)*
- [ ] Paste an example of the drink-mask offsets CSV into the user guide (Drink Mask section).
- [ ] Acquisition system documentation for the hardware high-pass. *(log §1)*
- [ ] Check that a *preprocessed* EDF keeps µV. *(log §1)*
- [ ] Optional: rerun a Welch resolution comparison on one dataset (the original runs were lost). *(log §6)*
- [ ] Drink-mask padding: a figure with and without the ±2 s padding, if one exists. *(log §6)*

## C. Decisions to make

- [ ] `psds_final.pkl` naming, or embed project/run/date inside the file. *(log §8)*
- [ ] Mask export: mark or omit excluded animals. *(log §8)*
- [ ] Provenance: write a project summary or run log at Finalize (trim/downsample, combo, SWD, reclassification, PSD params, exclusions, drink masks). Also record SPINDLE scoring date/version. *(log §8, §2)*
- [ ] Drop the "Confirm no SWD" button in favor of empty `.mat` files? *(log §4)*
- [ ] QC thresholds: replace the placeholder wake cutoff (70) and document where REM = 10 came from. *(log §5)*

## D. Code or doc changes (small, ready to do)

- [ ] `manifest.json` already says `combo: LFC_RSC` right after Preprocess, before the user has chosen a combo (it is the default). Make clear whether the user has actually chosen it.
- [ ] **Combo is set implicitly** by writing SPINDLE EDFs (stored in `manifest.json`). Clarify in the UI where the project combo is set and shown, and how to change it. Show the combo on Home.
- [ ] **Home is empty until Preprocess** (animals come from `standard/`). Consider listing raw EDFs on Home or showing a "run Preprocess first" message.

- [ ] Combine is command-line only. Consider a GUI page or a check at Preprocess that warns when short chunks are still in the project folder (Preprocess globs every `*.edf` there).
- [ ] **`ebb-combine edf` needs a lot of memory** on 5 kHz data (about 55 GB for two chunks; it loads each 24 h chunk whole). It completed on a 48 GB Mac only after other programs were closed. Consider changing `combine_edf` to read and write in blocks.
- [ ] Fix the Preprocess page's file-name note: files only need to be named `AnimalID_anything.edf` (tracked in `TODO.md`). Also no cancel button (see `TODO.md`).
- [ ] PSD page: an animal with no annotation file runs without the annotation mask and no warning is shown. Add a readiness warning listing animals with no annotation file when the annotation mask is on.
- [ ] Redraw `pipeline_flow.md` (still shows `needs_rerun`, the Rerun page and multi-combo).

## Done

- [x] `s_prob` removed from the code (commit `c24a2dd`); docs updated.
- [x] `psd_methods.md` corrected: states come from `final_state`, inverse filter/interpolation are display-only, the merged PSD file is gone, `s_prob` removed.
- [x] `TZ` setting and the positional channel convention are in the user guide.

- [x] EDF physical units checked on a raw file: µV, 5000 Hz, range ±8144 µV.
- [x] SWD "mask vs. TS policy" open question removed from `TODO.md`.
