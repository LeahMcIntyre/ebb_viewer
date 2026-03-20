# TODO

## P1 — High Value, Low Effort

### psd_visualizer: OK / Drink Mask buttons should reflect current status
Buttons don't visually stay in a "checked" state after flagging. Call `_update_flag_status()` immediately after each flag action; use `setCheckable(True)` / `setChecked()` to reflect the current animal's status.

### preprocess: Show computed output Hz from downsample factor
Add a dynamic label next to the downsample spinbox: e.g. `"5000 Hz ÷ 20 = 250 Hz"`. Update on value-change signal.

### preprocess: Make EDF filename format requirement visible
Wrong filenames give cryptic errors deep in the pipeline. Add a tooltip or info label:
> `"Files must be named: AnimalID_anything_YYYY_MM_DD_HH_MM_SS.edf"`

### home: Gate PSD step on all animals having ≥1 "ok" sleep QC entry
Running PSDs before all sleep QC is resolved produces an incomplete `psds_final.pkl`. The Needs Attention zone / pipeline steps should show a warning (e.g. `"⚠ 3 animals still need Sleep QC"`) instead of a PSD action card until the condition is met. Also consider a warning banner on the PSD Computation page itself.

### home: Filter rerun combo dropdown to exclude already-ok combos
Currently only excludes the current combo. Also exclude any combo where `sleep_qc == "ok"` for that animal — no point re-running a passing combo. Consider showing existing status next to each option (e.g. `"LFC_RSC (needs_review)"`).

---

## P2 — Moderate Value, Moderate Effort

### home: Add drink mask cards to Needs Attention zone
Animals with `psd_status = "needs_drink_mask"` should appear as cards with a "→ Drink Mask" action button. Without this, users rely solely on the sidebar badge.

### home: Add drink mask step to pipeline steps summary
Step 8 (Drink Mask) is not represented in the pipeline summary. Show how many animals are flagged `needs_drink_mask` vs `drink_mask_applied`.

### home: Remove editable channel combo from pipeline summary table (if redundant)
The rerun combo is already settable from the yellow card in Needs Attention. A second editable combo in the pipeline table is a duplicate code path with no extra clarity. Evaluate and remove if nothing is lost.

### psd_visualizer: Make which file is being reviewed more prominent
The file picker dropdown isn't prominent enough. Add a bold label near the top: `"Reviewing: psds_final_drink.pkl"`. Also: if the loaded file is not a "final" PKL (`psds_final.pkl` / `psds_final_drink.pkl`), disable or hide the OK / Drink Mask flag buttons — intermediate per-combo files aren't flaggable in the manifest flow.

### preprocess: Display EDF file count and total length
Scan the raw EDF directory on page load and show `"Found 12 files · ~45 hours"` so users confirm the right folder before starting a long job.

### preprocess / spindle write: Add "Next →" navigation hint when done
Consistent with the Rerun page pattern. After preprocessing: `"✓ Done. → Go to Spindle Write"`. After spindle write: `"✓ Done. → Go to Spindle Upload"`. Use `navigate_to` signal.

### psd: Make compute → merge two-step flow clearer in UI
The "compute per-combo PSDs" and "Build Final PKL" steps are logically distinct but visually run together. Label them as Step 1 / Step 2 with a separator, and show which combos will be included in the merge.

### psd: Confirm "video offset" label is gone
The `offset_path` parameter exists in `BatchEstimateWorker` but no UI widget was found for it in `PSDPage`. Verify there is no stale label or field referencing it; remove if found.

---

## P3 — Larger or Needs More Context

### spindle_upload: Investigate "Upload, Wait & Download" button issue
The button flow appears broken in some cases — needs reproduction and a specific bug report before this can be fixed. Document: what input conditions trigger the failure? Does it hang, crash, or give wrong output?

### spindle_upload: Project names should propagate on page shown
The remote folder name auto-defaults to `project_root.stem + '_' + combo` on combo selection but may not fire on `showEvent`. Ensure it pre-fills correctly whenever the page is navigated to.

### psd: SWD masks — decide policy on TS (needs scientific discussion)
Whether to mask out or include the transition state (TS) in PSD computation is a scientific decision that must be made before any implementation. Once policy is settled, add mask support + optional export to `.npy` (consistent with drink mask format).

### general: Run log / settings provenance
`psd/psd_params.json` already tracks PSD params. Consider extending to a `run_log.jsonl` that appends one entry per pipeline action (timestamp, what ran, which animals, params used). Low urgency but valuable for reproducibility and debugging.

---

## Additional Suggestions

- **EDF format validation on import**: When `build_from_standard` encounters a file that doesn't match `AnimalID_anything_YYYY_MM_DD_HH_MM_SS.edf`, emit a non-blocking warning rather than silently skipping or crashing later.
- **Keyboard shortcuts in PSD Visualizer**: `O` = OK, `D` = Drink Mask, `←`/`→` = prev/next animal. With 60+ animals to review, this saves significant time.
- **Manifest backup before destructive ops**: Auto-save `manifest.json.bak` before cascade-rejects or `reset_sleep_qc` to allow recovery from accidental clicks.
- **Drink Mask page: highlight missing .npy files**: The ✓/✗ in the table is subtle. Show `"Missing mask file"` in orange for animals where the `.npy` hasn't been placed yet.
