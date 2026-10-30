# Step 7. PSD Visualizer

Terms are defined in the [glossary](../glossary.md).

## Purpose

Look at every animal's PSDs and decide one thing: is the PSD fine (**OK**), or does it show the drinking artifact
and need a drink mask (**Drink Mask**)? The same page is used afterwards to check that a drink mask worked
(the **verify** pass). You can also exclude an animal here, but only as a last resort.

## Before you run

- Step 6 (PSD Computation) has run, so the run has a `psds_<COMBO>.pkl`. The pass buttons stay disabled until
  that file exists.
- Only animals marked `ok` in Sleep QC are reviewed. Excluded animals are shown for reference but are not asked
  for a decision.
- You know what the artifact looks like: **sidebands near 52 Hz and 68 Hz**, either side of the 60 Hz line-noise
  gap, usually in the LFC wake and NREM plots. REM and LSC plots are often smooth.

## Inputs

| Input | Location | What it is |
|---|---|---|
| PSD file for the review pass | `psd/<RUN>/psds_<COMBO>.pkl` | The PSDs from step 6. |
| PSD file for the verify pass | `psd/<RUN>/psds_<COMBO>_drink.pkl` | The same file with the drink-masked animals replaced (step 8). Exists only after step 8 has run. |
| Run settings | `psd/<RUN>/psd_params.json` | Read only for `apply_notch`, to choose the default interpolation range. |
| Manifest | `manifest.json` | Which animals are `ok`, excluded, or already reviewed in this run. |
| Drink-event files (optional) | `drink_masks/<ID>.npy` | Only used to show a hint if one already exists for an animal. |

## Settings

Nothing here changes the PSD files. The toolbar changes only how the plot looks.

**Source**

| On-screen label | Meaning | Default |
|---|---|---|
| Run | Which PSD run to review. | the first run listed, or the one you just computed |
| Review PSDs (N left) | The first pass: every `ok` animal that has no decision yet in this run. | – |
| Verify drink masks (N to check) | The second pass: animals recomputed with a drink mask that wait for your check. Disabled until `psds_<COMBO>_drink.pkl` exists. | opens automatically when every animal has had its first review and some are waiting to be verified |
| Other PSD file | View any `psds_*.pkl` in the run's folder (including `psds_final.pkl`), or **Browse…** for one. View only: no decisions can be recorded. | collapsed |

**Toolbar** (in the grid)

| On-screen label | Meaning | Default |
|---|---|---|
| Log-X | Logarithmic frequency axis. | off |
| Log-Y | Logarithmic power axis. | on |
| Inverse Filter | Multiply the lowest bins by correction factors, to compensate for the recording hardware's low-frequency roll-off (see Fixed values). | **off** |
| Interpolate | Replace the line-noise gap by a straight line in log-log space. | **off** |
| Set X-Range | Choose the frequency range shown. | 0.5 – 110 Hz |
| Set Interp-Range | Choose the frequencies to bridge. | 56 – 64 Hz if the run used the notch filter, otherwise 58 – 62 Hz |
| Reset zoom | Back to 0.5 – 110 Hz. | – |
| 📝 Notes | Edit the animal's notes. A • shows when there is a note. | – |

We use both **Inverse Filter** and **Interpolate** for every animal during review. They start switched off, so
switch them on.

**Decision buttons** (bar above the grid)

| Button | Key | Review pass | Verify pass |
|---|---|---|---|
| ✓ OK / ✓ Mask worked | `O` | The PSD looks fine. Sets `psd_status` to `ok`. | The sidebands are gone. Sets `ok`. |
| Drink Mask / ✗ Redo mask | `D` | Sidebands are visible. Sets `needs_drink_mask`. | The mask did not work. Sends the animal back to step 8 as `needs_drink_mask`. |
| Exclude | none, on purpose | Leave the animal out (a reason is required). Pressing it again sends the animal back to Sleep QC as `needs_review`. | Same. |
| ↺ Reset | – | Clears the animal's decision for this run. Disabled if there is none, or the animal is excluded. | Same. |
| ◄ Prev / Next ► | `←` `→` | Move between animals. | Same. |

The `O`, `D` and arrow keys work anywhere on the page while it is visible, even when the focus is on the sidebar.
**Do not exclude an animal from its PSD alone.** Look into it separately first (for example in the EEG viewer),
and exclude only if you cannot find a fix.

## Fixed values

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|
| Inverse filter bins | 0.5, 1.0, 1.5, 2.0, 2.5, 3.0 and 3.5 Hz | Applies to bins from 0.5 to 3.5 Hz inclusive. | `FILTER_RANGE` |
| Inverse filter factors | 2.4853, 1.3606, 1.1453, 1.0717, 1.0380, 1.0187, 1.0078 | Each bin's power is multiplied by the factor in the same position. It needs PSDs at 0.5 Hz resolution (exactly seven bins in that range). | `INVERSE_FILTER` |
| Interpolation method | straight line in log-log space | Joins the median of the 3 bins just below the range to the median of the 3 bins just above it. Meant for small ranges such as line noise. | `specparam.utils.interpolate_spectrum`, `buffer=3` |
| Notch vs. interpolation range | notch 57–63 Hz; interpolation 56–64 Hz | The default range is wider than the notch, to cover its rolloff. | `_NOTCH_INTERP_RANGE` |
| Power axis label | µV²/Hz | – | – |
| Power floor on log axes | 1e-12 | Zero or negative power is raised to this so the plot does not break. | – |
| Pass order | Verify opens first only when no animal is unreviewed, some are waiting, and the drink-masked file exists | – | `default_pass` |

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [No high-pass filter in PSD analysis; an inverse filter compensates low frequencies at review](../decision_log.md#no-high-pass-filter-in-psd-analysis-an-inverse-filter-compensates-low-frequencies-at-review)
- [Drink artifacts are flagged by eye, not automatically](../decision_log.md#drink-artifacts-are-flagged-by-eye-not-automatically)

## What it does

1. **Choose the run and the pass.** The page opens on the pass that is next. The buttons show how many animals
   wait in each pass.
2. **Show one animal at a time.** A grid with one plot per channel (rows: LFC, RSC, LSC) and state (columns). Pick the
   animal from the list, with **Prev / Next**, or the arrow keys. In the verify pass the list holds only the animals
   waiting for verification (fixed when the pass opens, so an animal does not vanish the moment you mark it).
   Tick **Show all animals** to list everyone.
3. **You decide.** Each button writes to the manifest at once.
4. **Helpful prompts.** If a `drink_masks/<ID>.npy` already exists for an animal with no decision, a blue bar offers
   **Flag for drink mask**. After you flag an animal, a yellow bar reminds you to put the drink-event file in
   `drink_masks/` and goes to step 8.
5. **Finish.** When no animal is unreviewed, flagged for a drink mask, or waiting for verification, a green bar says
   "All animals in run '<RUN>' reviewed" with a button to Finalize.

Excluded animals have a grey banner ("EXCLUDED in <stage>" with the reason), grey curves and a greyed list entry. OK
and Drink Mask are disabled for them.

## Outputs

This step writes only to `manifest.json`. The PSD files are never modified.

| Field | Values | Meaning |
|---|---|---|
| `psd_status[<RUN>]` | `ok` / `needs_drink_mask` / `drink_mask_applied` | Your decision for this animal in this run. `drink_mask_applied` is set by step 8, not here. Removed by Reset. |
| `drink_mask` | path or empty | Link to the animal's drink-event file. Set when step 8 applies a mask; cleared when you mark the animal `ok` and no other run still has a mask applied. |
| `sleep_qc` | `excluded` / `needs_review` | Set by Exclude and by pressing it again. The exclusion also adds a line `Excluded (PSD review): <reason>` to `notes` and clears the animal's PSD decisions. |
| `notes` | text | Free text. |

## Check your work

- Every `ok` animal has `OK`, or is flagged for a drink mask, or is waiting for verification. The page's counts read
  "0 left" and "0 to check" when finished.
- Animals flagged for a mask have gone through step 8 and been verified (**Mask worked**).
- Anything excluded here has a specific reason.

## If something goes wrong

- Review PSDs is greyed out: the run has no `psds_<COMBO>.pkl`. Compute it in step 6.
- Verify drink masks is greyed out: step 8 has not been run for this run yet.
- The grid is empty: the run's PSD file has no records for that animal, or the list is empty because no animal is
  waiting in this pass. Tick **Show all animals** in the verify pass.
- The page raises an error when you switch on Inverse Filter: the PSDs were not computed at 0.5 Hz resolution, so the
  seven correction factors do not fit.
- An animal's buttons are greyed: the animal is excluded. Click **Exclude** again to send it back to Sleep QC review.
- Re-running PSD Computation under the same run name clears every decision in that run.

## Used by

Step 8 (Drink Mask) works on the animals flagged here. Step 9 (Finalize) waits until nothing is unreviewed,
flagged or waiting for verification.

## Known limitations

- **Interpolate and Inverse Filter start off** each time the page opens.
- **The inverse filter needs 0.5 Hz resolution.** At any other resolution the seven correction factors do not fit the 0.5–3.5 Hz bins and the page raises an error.
- **Viewing options are display-only.** `psds_<COMBO>.pkl`, `psds_final.pkl` and the Excel export never include them.
