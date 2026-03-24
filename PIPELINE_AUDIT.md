# Pipeline Audit: Clarity Issues & Testing Gaps

---

## Pipeline Clarity Issues

### Stage 1–2: Preprocess / Spindle Write

**Per-file silence.** The worker emits 2 messages total (start + done). If `batch()` skips a file because the EDF doesn't match the expected filename format, or a file can't be opened, there's no per-file feedback. The user won't know 3 of 10 animals were silently skipped.

**Re-running onto existing files.** If `standard/` already has preprocessed EDFs and the user re-runs, new EDFs are appended (or may collide depending on naming). No warning shown.

**SpindleWrite: `exist_ok=False` on target dir.** If you try to write a combo whose directory already exists (e.g., you re-ran and it's there from before), the worker raises `FileExistsError` immediately — the error dialog says "Could not create spindle folder" which is confusing since the folder *does* exist, that's the problem. It should either say "folder already exists — delete it first" or use `exist_ok=True` and let it overwrite.

---

### Stage 4: Sleep QC

**Stale manifest.** `SleepQCGridPage.__init__` loads `self._manifest = Manifest.load(project_root)` and holds it. `_poll()` only refreshes the UI from this cached manifest, never reloading from disk. If the RerunPage writes a new run via `manifest.add_run()` (which saves to disk) while Sleep QC is the active page, the cached manifest is now stale. The badge on the sidebar will update (it calls `Manifest.load` independently), but the page itself won't pick up the new run until it's hidden and re-shown.

**`pending_sleep_qc` vs `needs_review` confusion.** Home step 4 shows "N to review, M pending" — "to review" means flagged for EDF viewer inspection, "pending" means never QC'd at all. These are genuinely different but the home page labels are too terse to communicate that distinction.

**Disabled "Review" button with no explanation.** When a run has `sleep_qc == "needs_rerun"`, the Review button is disabled. There's no tooltip or label explaining why. A user will just see a grayed-out button.

---

### Stage 5: Spindle Rerun

**"N reruns resolved" label is misleading.** In `compute_pipeline_status`, step 5 shows `"done"` with "N reruns resolved" when `n_rerun > 0 and n_rerun_pend == 0 and n_rerun_ready == 0`. But `needs_rerun()` returns runs that still have `sleep_qc == "needs_rerun"` — these are the *original* combos, which stay in that state even after the rerun is accepted. So "N reruns resolved" appears while those N original combos permanently show `needs_rerun` in the manifest. The label is accurate but the word "resolved" suggests cleanup that hasn't happened.

**Hint frame only shows if the *last* upload succeeds.** `_offer_upload` loops over combos; `on_finished=lambda: self._hint_frame.setVisible(True)` is wired per-worker. If you have 2 combos and the second upload fails, `_hint_frame` never gets shown. If the first upload succeeds and the second fails, `_hint_frame` shows from the first worker's callback anyway — not a big deal but the timing isn't deterministic.

**"Skipping preprocessing" log message on retry.** On a re-run where the EDF already exists, the log shows "Spindle EDF already exists, skipping preprocessing" before launching the upload. A user who cancelled the upload last time might be confused — did the program do anything? The message should be more reassuring: "EDF already written — skipping to upload."

---

### Stage 6: PSD Computation

**"Build Final PKL" enabled prematurely.** `btn_final` is enabled as soon as *any* per-combo PKL exists. If you've only computed LFC_RSC and 4 of your 10 animals use RSC_LSC (with `sleep_qc == "ok"`), clicking "Build Final PKL" silently skips those 4 animals with a `warnings.warn` that goes to stderr — not the log box, not a dialog. The user gets a merged PKL with fewer animals than expected, with no indication in the UI.

**No per-animal progress.** `batch_estimate` prints per-animal progress to stdout but this is suppressed (`verbose` handling in the worker). The log only shows combo-level start/finish. For large batches this could mean 20 minutes of silence.

**Animals silently skipped when EDF has no matching CSV.** `batch_estimate` filters `eeg_paths` to only animals that have a matching CSV in `state_dir`. If the state CSV is missing for an animal (download failed for one file, different naming convention), that animal is silently excluded. No warning is surfaced in the GUI.

**Two-step flow (Compute → Build Merged) is not visually connected.** After "Compute PSDs" succeeds, the hint frame says "Done. Check merged channel combo pkl file for drink mask." — this doesn't tell the user they still need to click "Build Final PKL". The two buttons sit side-by-side with no visual separation or ordering cue. Step 7 on the home page stays "blocked" until `psds_channel_merged.pkl` exists, but the user has to figure out why by going back to page 6.

---

### Stage 7: PSD Review

**No way to undo a PSD flag via the UI.** If you click "✓ OK" for the wrong animal, there's no "reset" or "undo" button in `PSDGridPage`. `reset_psd_status()` exists on `Manifest` but isn't exposed anywhere. The only workaround is editing `manifest.json` directly.

**Home step 7 doesn't re-check after finalization changes.** If `psds_final.pkl` exists (`final_pkl.exists()`) → step 7 shows "All PSDs reviewed and finalized". But if the user then goes back and re-flags an animal as `needs_drink_mask` (re-opening the PSD Visualizer), `psds_final.pkl` still exists so step 7 still shows "done" even though the data is now stale.

**Home page "Needs Attention" zone never shows a "Ready to Finalize" card.** When all animals are reviewed and `psds_channel_merged.pkl` exists, step 7 in the guide shows "attention: All reviewed — click Finalize to seal." But there's no card in the "Needs Attention" zone pointing to Finalize. Users who rely on the attention zone as their task list won't see this.

---

### Stage 8: Drink Mask

**`_on_done` swallows `flag_psd` errors.** The `try/except Exception: pass` block means if any `flag_psd()` call raises (animal not found, wrong `sleep_qc` status, etc.), it's silently swallowed. The manifest save happens only once at the end, so partial flagging is possible — some animals in `_pending_animal_combos` get flagged, others don't, and the user has no idea.

**Re-building `psds_channel_merged.pkl` invalidates old drink masks.** If you add new animals to the project and rebuild `psds_channel_merged.pkl`, the existing `psds_drink.pkl` records still reference old records by animal ID. The next call to `rerun_with_drink_masks` will regenerate `psds_channel_merged_drink.pkl` with old drink records overlaid on the new base — which is correct if the animal IDs match. But there's no guidance telling the user they need to re-apply drink masks after a rebuild.

---

### Stage 9: Finalize

**Home page has no step 9.** `_STEP_LABELS` / `_STEP_PAGE_NAMES` stop at step 8. The Finalize page is completely invisible from the home guide.

**`psds_final.pkl` exists but is now stale after re-flagging.** If finalized, then an animal is re-flagged as `needs_drink_mask`, `psds_final.pkl` is now outdated. The Finalize page will show the button as disabled (pending > 0), which is correct. But `psds_final.pkl` still exists on disk and home step 7 shows "done." There's no warning that the finalized file is now outdated.

---

## Testing Gaps (Prioritized by Risk)

### High — Silent Data Corruption

**1. `build_final_pkl` with a missing per-combo PKL.**
```python
# Animal AM001 has sleep_qc="ok" for "RSC_LSC"
# but psds_RSC_LSC.pkl doesn't exist
# Expected: warning emitted, AM001 absent from merged PKL, no crash
```
Currently only a `warnings.warn` to stderr — not testable without capturing the warning, and the user has no idea.

**2. `add_run` called on a run that already has `sleep_qc="ok"`.**
`add_run` has this path:
```python
elif source_combo is not None and entry.runs[channels].source_combo is None:
    run.sleep_qc = None   # ← resets an ok run to None
```
If `channels` happens to be the ok combo, this violates the one-ok invariant without triggering the cascade restoration logic. The manifest is now in an inconsistent state (psd_status/drink_mask still set, sleep_qc=None).

**3. `pending_psd_review()` gate disappears when `psds_channel_merged.pkl` is deleted.**
Returns `[]` if the file doesn't exist. If `[]` is returned, the finalize page shows "All reviewed — ready to finalize" (0 pending) even though no review has actually occurred. The finalize button becoming enabled without any real review is dangerous.

**4. `DrinkMaskPage._on_done` partial failure.**
```python
for animal_id, combo in self._pending_animal_combos.items():
    try:
        manifest.flag_psd(animal_id, combo, "drink_mask_applied")
    except Exception:
        pass   # ← silently drops flag for this animal
```
Test: one valid animal, one animal removed from manifest → only the first gets flagged, manifest.save() still runs, no indication of failure.

**5. `rerun_with_drink_masks` after `psds_channel_merged.pkl` is rebuilt.**
`psds_drink.pkl` accumulates records. When `psds_channel_merged.pkl` is rebuilt (new animals added), it regenerates `psds_channel_merged_drink.pkl` by overlaying `psds_drink.pkl` records onto the new base. If an animal was in the old base but removed from the new one, their drink record will be appended to `psds_channel_merged_drink.pkl` even though they're no longer in the project. Test: rebuild merged PKL removing one animal, then re-apply drink masks — verify the removed animal does not appear in the output.

---

### Medium — State Machine Consistency

**6. `needs_rerun_pending()` dead-zone: `needs_rerun` + CSV present + `source_combo=None`.**
```
Scenario: user manually copies CSV into spindle_outputs/COMBO/
  → CSV present → excluded from needs_rerun_pending (CSV check)
  → source_combo=None → excluded from pending_rerun_review
  → Animal is invisible to both queues
```
Test this explicitly. This is the scenario where a user who manually manages files on disk can create an animal that gets permanently lost in the UI.

**7. `batch_estimate` with no matching EDFs produces empty PKL.**
The savepath write runs even when `results` is empty — writes an empty list `[]`. `build_final_pkl` will then open this PKL and find no records for that combo's animals, silently skipping them. Test: `batch_estimate` where no EDF files match state CSV animal IDs → verify savepath contains `[]` or ideally that a warning is emitted.

**8. `needs_rerun_pending()` when `rerun_run.sleep_qc == "rejected"`.**
If the rerun was rejected (original accepted), the `rerun_run.sleep_qc is not None` check excludes it. But the *original* combo still has `sleep_qc == "needs_rerun"`. So it doesn't appear in `needs_rerun_pending()` (correctly excluded) but still shows in `needs_rerun()`. Home step 5 will show "N reruns resolved" but `needs_rerun()` is non-empty. The test should verify the step 5 label in this state.

**9. Home `compute_pipeline_status` step 7 when `final_pkl` exists but `pending_psd_review()` is non-empty.**
```
Scenario: finalized, then user re-flags one animal as needs_drink_mask
  → final_pkl.exists() → True
  → n_psd_pending == 0 (needs_drink_mask is not counted by pending_psd_review)
  → step 7 shows "All PSDs reviewed and finalized" ← incorrect
```
Actually wait — `n_psd_pending = len(manifest.pending_psd_review())`. `pending_psd_review()` only returns runs where `psd_status is None`. After re-flagging to `needs_drink_mask`, `psd_status == "needs_drink_mask"` so it's *not* in `pending_psd_review()`. So step 7 still shows "finalized" even though the data is stale. And the needs_drink_mask count goes up (step 8 shows attention), but step 7 stays green. This is a real misleading state that needs a test to document the behavior.

**10. `flag_sleep_qc("ok")` on a combo that has `psd_status` set, when un-okaying it later.**
`flag_sleep_qc` (un-okaying) clears `psd_status` and `drink_mask` on the run. But does it also clear `psd_status` on the newly restored siblings? The restored siblings had their `sleep_qc` restored from `prev_sleep_qc`, but their `psd_status` is whatever it was before they were cascade-rejected. If a sibling previously had `psd_status="ok"` before being rejected, restoring it would restore `psd_status="ok"` — potentially incorrect since the PSD review should be re-done. Test: sibling with `psd_status` set → ok another combo → un-ok it → verify sibling's `psd_status` state.

---

### Lower Priority — Edge Cases Worth Documenting

**11. `_refresh_combo_table` in PSDPage includes `psds_final.pkl`-filtered combos correctly.**
The filter `p.stem not in {"psds_channel_merged", "psds_channel_merged_drink", "psds_final"}` prevents those from showing as compute targets. Test that all three are excluded.

**12. `manifest.load()` integrity check: orphaned `rejected_by` is cleared.**
This is tested, but the test should also verify that the cleared run is then saveable and re-actionable — i.e., that the animal doesn't end up stuck.

**13. `pending_drink_verification()` + `pending_psd_review()` double-count risk.**
An animal with `psd_status=="drink_mask_applied"` appears in `pending_drink_verification()` but NOT in `pending_psd_review()`. An animal with `psd_status==None` appears in `pending_psd_review()` but NOT `pending_drink_verification()`. The finalize pending count in both `FinalizePage._refresh()` and `_check_finalize_hint()` sums all three queues — these should be mutually exclusive by design. Test that they are.

**14. `SleepQCGridPage` stale manifest — verify `showEvent` reloads.**
The cached `_manifest` should be reloaded in `showEvent`. Read the full `showEvent` / `_refresh_data` to confirm this actually happens — if the manifest is only updated on explicit QC actions (not on `showEvent`), the stale manifest bug is confirmed and needs a fix.

---

## Summary Table

| Area | Risk | Issue |
|---|---|---|
| `add_run` on ok run | **High** | Resets `sleep_qc=None`, breaks invariant |
| `build_final_pkl` missing PKL | **High** | Silent skip, stderr-only warning |
| `pending_psd_review` gate deletion | **High** | `pending==0` without any review |
| `_on_done` swallowed exceptions | **High** | Partial manifest updates undetected |
| Dead-zone: `needs_rerun`+CSV+no source_combo | **High** | Animal invisible to all queues |
| Step 7 "finalized" after re-flagging | **Medium** | False "done" signal on home page |
| Home missing step 9 | **Medium** | Finalize page invisible from guide |
| `batch_estimate` 0-EDF path | **Medium** | Empty PKL silently written |
| No "un-flag PSD" in UI | **Medium** | No recovery from mis-click |
| SleepQC stale manifest | **Medium** | Misses runs added by RerunPage |
| Sibling `psd_status` after un-ok restore | **Low** | Stale PSD status on restored run |
