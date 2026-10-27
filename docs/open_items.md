# Open items for the documentation

Collected from the decision-log interviews. Tick items off here, and update the matching entry in [decision_log.md](decision_log.md) when you do. The log's entries mark each place with a TODO or **(you)**.

## A. Need your answer or knowledge

- [ ] **Upstream EBB.** What did you keep from EBB (Caudill) and what did you rewrite? Fix the credit lines in `README.txt`. *(log §10)*
- [ ] **Pre-sweep data.** Were any paper datasets processed before the 2026-05-12 cleanup sweep? If so, rerun or note it. *(log §10)*
- [ ] **Reasons for the architecture** marked **(you)**: library/GUI split, manifest. *(log §10)*
- [x] SPINDLE receives the selected EEG channels plus the EMG (always included, per the Spindle EDFs page). Update log §2 "Still to confirm".
- [ ] **Inverse filter.** Source of the coefficients (preamp model and derivation). It is display-only in the visualizer and applied at analysis in `psd_analysis.ipynb`; confirm that is intended.
- [ ] **Bin edges.** How is a bout that spans a 2-hour bin edge counted? *(log §9)*
- [x] **Gate rule.** Light period is right: rho 0.83 vs. 0.58 for dark hours on the 12 annotated animals; 10% is the bucketing threshold of `run_reclassification.py`. Recorded in log §3. The by-hour figures were at k = 3 while the code uses k = 5; k = 5 versions now exist at the end of both notebooks. *(log §3)*


## B. Evidence to find or link

- [ ] Artifact-masking notebook (commutator, SD, SPINDLE noise cutoff). *(log §6)*
- [ ] Line-noise notebooks: copied from the `line_noise` branch to the server (`Pipeline_Research/line_noise`); confirm the folder is there and that they are the final analysis. Push the branch (commit `a815a54` is local only). *(log §6)*
- [x] **Notch order.** Compared late vs. early notch on the Stxbp1 characterization set; the difference figure is from the late run. Result is in log §6 ("The notch runs after the artifact masks").
- [ ] Server folder names: `spindle-validation` and `ebb-research` are linked in the log; check `line_noise` once copied. Still no source for the channel-combo slides, the artifact-masking notebook, the SWD detector citation and the drink-padding figure. *(log §2, §4, §6)*
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

- [ ] Mask export: mark or omit excluded animals. *(log §8)*
- [ ] Provenance: write a project summary or run log at Finalize (trim/downsample, combo, SWD, reclassification, PSD params, exclusions, drink masks). Also record SPINDLE scoring date/version. *(log §8, §2)*
- [ ] Drop the "Confirm no SWD" button in favor of empty `.mat` files? *(log §4)*
- [ ] QC thresholds: replace the placeholder wake cutoff (70) and document where REM = 10 came from. *(log §5)*

## D. Code or doc changes (small, ready to do)

- [ ] The combo is set implicitly by writing SPINDLE EDFs. Home now shows it ("default; set on 2. Spindle EDFs" until then); consider a deliberate way to see and change it.
- [ ] Preprocess page: no cancel button (see `TODO.md`).

## Done

- [x] Added `notebooks/psd_analysis.ipynb` and `notebooks/psd_utils.py` (branch `feature/psd-analysis-notebook`, not merged), modeled on `PSD_Analysis_Example/psd`.

- [x] Deleted the stale slide diagrams (`pipeline_flow_slide.md`, `psd_flow_slide.md`, `storage_schematic_slide.md`). `pipeline_flow.md` now has two flowcharts and the folder layout.

- [x] `pipeline_flow.md` redrawn for the current stages (branch `docs/pipeline-flow`).

- [x] Decided: `psds_final.pkl` keeps its name.
- [x] Decided: no change to `ebb-combine edf` memory use. The guide tells users to close other programs first (about 55 GB free for a two-chunk animal).

- [x] Branch `fix/small-ui-fixes` (not merged): Preprocess file-name note and leftover-chunk warning; PSD readiness warning for animals without an annotation file; Home shows the combo and explains the empty table.

- [x] `s_prob` removed from the code (commit `c24a2dd`); docs updated.
- [x] `psd_methods.md` corrected: states come from `final_state`, inverse filter/interpolation are display-only, the merged PSD file is gone, `s_prob` removed.
- [x] `TZ` setting and the positional channel convention are in the user guide.

- [x] EDF physical units checked on a raw file: µV, 5000 Hz, range ±8144 µV.
- [x] SWD "mask vs. TS policy" open question removed from `TODO.md`.
