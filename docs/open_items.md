# Open items for the documentation

Collected from the decision-log interviews. Tick items off here, and update the matching entry in [decision_log.md](decision_log.md) when you do. The log's entries mark each place with a TODO or **(you)**.

## A. Need your answer or knowledge

- [ ] **Blinding.** How is the QC reviewer blinded to genotype in practice? File names carry genotype tags (e.g. `..._KO_...`). *(log §5)*
- [ ] **Upstream EBB.** What did you keep from EBB (Caudill) and what did you rewrite? Fix the credit lines in `README.txt`. *(log §10)*
- [ ] **Pre-sweep data.** Were any paper datasets processed before the 2026-05-12 cleanup sweep? If so, rerun or note it. *(log §10)*
- [ ] **Reasons for the architecture** marked **(you)**: library/GUI split, manifest. *(log §10)*
- [ ] **Which channels does SPINDLE receive** (EEG pair plus EMG?). *(log §2)*
- [ ] **Inverse filter.** Source of the coefficients (preamp model and derivation). Is it applied only in the review plots or also in stored/exported PSDs? *(log §6)*
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
- [ ] Add a project option to hide genotype in animal names, if blinding is not otherwise handled. *(log §5)*

## D. Code or doc changes (small, ready to do)

- [ ] Remove `s_prob` from the UI and `psd_compute.py`. *(log §6)*
- [ ] Update `psd_methods.md` §4: it says "no other filtering" but the review step has the inverse-filter and interpolation toggles.
- [ ] Update `psd_methods.md` §7 and `CLAUDE.md`: the merged PSD file no longer exists.
- [ ] Redraw `pipeline_flow.md` (still shows `needs_rerun`, the Rerun page and multi-combo).
- [ ] Document the `TZ` setting of the sleep notebooks in the user guide (default `America/Chicago`).
- [ ] State the positional channel convention (1 = LFC, 2 = RSC, 3 = LSC, 4 = EMG) and the one-folder-per-time-point rule in the user guide.

## Done

- [x] EDF physical units checked on a raw file: µV, 5000 Hz, range ±8144 µV.
- [x] SWD "mask vs. TS policy" open question removed from `TODO.md`.
