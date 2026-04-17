# TODO

## P2 — Moderate Value, Moderate Effort

### home: Remove editable channel combo from pipeline summary table (if redundant)
The rerun combo is already settable from the yellow card in Needs Attention. A second editable combo in the pipeline table is a duplicate code path with no extra clarity. Evaluate and remove if nothing is lost.

### preprocess / spindle write: Add "Next →" navigation hint when done
Consistent with the Rerun page pattern. After preprocessing: `"✓ Done. → Go to Spindle Write"`. After spindle write: `"✓ Done. → Go to Spindle Upload"`. Use `navigate_to` signal. Add logs with the outputs that are currently being printed to console. 

### psd: Make compute → merge two-step flow clearer in UI
~~The "compute per-combo PSDs" and "Build Final PKL" steps are logically distinct but visually run together. Label them as Step 1 / Step 2 with a separator, and show which combos will be included in the merge.~~
**DONE** — Step 1 / Step 2 layout with arrow, dynamic hint frame, and renamed button implemented.

---

## P3 — Larger or Needs More Context

### psd: Revisit SD-threshold rule for lumped state groups
With state-selection presets, a user can pick a lumped group like `all` (wake+nrem+rem) or `sleep` (nrem+rem). Today SD thresholding is applied only when the group is literally named `wake` (see `if 'wake' in combo_state` in `estimate_psd`). For `all`, which contains wake samples, SD probably should apply to the wake portion. For `sleep`, it should stay off. Decide the rule (likely: apply SD when the group's code list includes `"w"`), update `estimate_psd` and tests accordingly.

### psd: Clarify REM-in-multiple-groups semantics
If a user checks both `rem` and `sleep`, REM epochs feed into two PSDs (a REM-only PSD and a NREM+REM PSD). That's intentional — same epochs, different averages. Decide whether to (a) surface this in the UI with a small hint when overlapping groups are selected, or (b) leave silent. Also think about whether downstream plots/tables should visually distinguish "lumped" groups from single-state groups.

### psd_visualizer: Stable panel order for custom state groups
PSD Visualizer derives panel columns from whatever state names are in the pkl, using canonical-then-alphabetical ordering. If we ever add user-defined group names (beyond the 5 presets), confirm the ordering still makes sense, and consider a persisted user preference.

### spindle_upload: Investigate "Upload, Wait & Download" button issue
The button flow appears broken in some cases — needs reproduction and a specific bug report before this can be fixed. Document: what input conditions trigger the failure? Does it hang, crash, or give wrong output? 

### spindle_upload: Project names should propagate on page shown
The remote folder name auto-defaults to `project_root.stem + '_' + combo` on combo selection but may not fire on `showEvent`. Ensure it pre-fills correctly whenever the page is navigated to. Use the SleepyRat manifest to note if there has been a project selected already. 

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
