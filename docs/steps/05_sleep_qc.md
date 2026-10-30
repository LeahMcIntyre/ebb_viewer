# Step 5. Sleep QC

Terms are defined in the [glossary](../glossary.md).

## Purpose

Decide, for every animal, whether its sleep data can be trusted. Each animal must end as `ok` or
`excluded` before PSDs can be computed. The page does not change any data. It shows the sleep states
(from `final_state`), highlights animals that look suspicious, and records your decisions in the manifest.

## Before you run

- Step 4 (Reclassify) has run. Without it the page shows the original SPINDLE states, flags nothing
  automatically and says so in an orange line. Run SWD Review (4b) first if your project uses it.
- Every animal has a preprocessed EDF in `standard/`. It supplies the recording start time that the
  dark-period, clock-aligned and rotated views need. An animal without one is left out of those and of
  the flagging metrics, and a warning lists it.
- You prepare no files. Review blind to genotype: file names do not carry it, so the review is blind as
  long as you do not know which ID belongs to which group.

## Inputs

| Input | Location | What it is |
|---|---|---|
| State CSV, one per animal | `spindle_outputs/<COMBO>/*.csv` | `final_state` (the states shown) and `noise_prob` (for the Spindle mask view). The original state column is read for **Show original**. |
| Preprocessed EDF, one per animal | `standard/*PROCESSED.edf` | Only its header is read, for the recording start time. |
| Flagging thresholds | `manifest.json` (`flag_thresholds`) | The six cutoffs below. Missing keys fall back to the defaults. |
| Reclassify record | `manifest.json` (`reclass_gate_applied`) | Marks animals the EMG gate was applied to (`[EMG gate]`, orange ring). |
| SWD review status | `manifest.json`, `swd/` | Only to show an orange "SWD review incomplete" line. It never blocks this page. |

## Settings

The page has three views, switched by the **VIEW** buttons. None of these controls change data on disk.
Your decisions (OK, Review, Exclude) are the only things that write to the manifest.

| On-screen label | Meaning | Default | Change it when |
|---|---|---|---|
| VIEW: Overview | One boxplot per flagging metric, one dot per animal, with threshold lines. Animals past a threshold are red and labelled. | on | – |
| VIEW: Sleep | Per-animal plots of each state over time, with the OK / Review / Exclude buttons. This is where you go through every animal. | off | – |
| VIEW: Spindle mask | Percent of each state that SPINDLE marked as artifact, per animal. A diagnostic only: it has no thresholds and flags nothing. | off | You want to see how much of an animal's data SPINDLE marked as artifact. |
| Show original | Plot SPINDLE's original states instead of `final_state`, in all three views. The flagging metrics follow it. Disabled if no animal is reclassified. | off | Comparing against SPINDLE's own scoring. |
| DISPLAY: Group / Animal | Sleep view only. Group shows 10 animals per page (**◄ Prev**, **Next ►**, **Go to**); Animal shows one at a time (**Animal:** list, **◄ Prev**, **Next ►**). In Animal mode, animals not yet decided are listed first. | Group | – |
| Time axis | Sleep view only. How the x-axis is anchored (see What it does). | Clock-aligned | The first or last bin of an animal looks odd (it may be a partial bin). |
| Median | Sleep view only. Draws the median of all animals as a dashed reference line. | off | You want to compare one animal with the rest. |
| Flag for Review (Overview) | Click an animal's dot, then this button, to mark it `needs_review`. | – | You want to review an animal that is not past a threshold. |
| OK / Review / Exclude (Sleep view, per animal) | Your decision for the animal. See Outputs for what each writes. Pressing a pressed OK or Review resets the animal to undecided; pressing a pressed Exclude sends it to `needs_review`. | none | – |
| 📝 (Sleep view, per animal) | Opens the animal's notes. | – | You want to record why. |

Exclude always asks for a reason. The button stays disabled until you type one, and cancelling changes nothing.

## Fixed values

| Value | Fixed at | Meaning | Code name |
|---|---|---|---|
| Epoch | 4 s | One SPINDLE state. | `EPOCH_SEC` |
| Bin width | 2 h | Width of each point in the Sleep view, and of the bins in the "max REM" metric. | `BIN_HOURS` |
| Short NREM bout | 1 or 2 epochs (≤ 8 s) | A NREM bout this short counts as "short". | `SHORT_BOUT_EPOCHS` |
| Dark period | clock hours 20:00–05:59, from the EDF start time | Used by the "NREM bouts per dark hour" metric. The same hardcoded schedule as the light period in Reclassify. | `DARK_HOURS` |
| Bin anchor hour | 06:00 | Bins in Clock-aligned and Rotate to 6AM are anchored to 06:00 clock boundaries. | `begin_hr=6` |
| Time zone | America/Chicago | Used to place bins and to rotate, so daylight-saving changes are handled. Not a setting on this page. | `_RECORDING_TZ` |
| Spindle-mask artifact cutoff | `noise_prob` ≥ 0.5 | An epoch counts as artifact in the Spindle mask view. Fixed at 0.5, the same cutoff Reclassify uses (current SleepyRat files have no `threshold` column). | `noise_prob_threshold` |
| Animals per page | 10 | Group mode page size. | `MICE_PER_PAGE` |
| Automatic flagging | on, whenever the page loads its data | See What it does. | `auto_flag_for_review` |

### Flagging thresholds

All six use the reclassified states and the whole recording. An animal is flagged when **any** metric is
past its threshold. NaN never flags. The cutoffs are starting points, not rules: an unflagged animal can
still be bad and a flagged one fine. There is no editor in the GUI; to change a cutoff, edit
`flag_thresholds` in `manifest.json`.

| Metric (key) | How it is computed | Flags when | Default |
|---|---|---|---|
| Short NREM bouts per hour (`nrem_short_h`) | NREM bouts of 1–2 epochs, divided by the recording length in hours | above | 6 |
| NREM bouts per dark hour (`dark_bouts_h`) | NREM bouts that start in the dark period, divided by the hours of dark period in the recording. NaN if the recording has no dark hours. | above | 15 |
| REM % (`pct_rem`) | epochs in REM ÷ all epochs × 100 | above | 10 |
| NREM % (`pct_nrem`) | epochs in NREM ÷ all epochs × 100 | below | 30 |
| Wake % (`pct_wake`) | epochs in wake ÷ all epochs × 100 | above | 70 |
| Max REM % in a 2 h bin (`max_bin_rem`) | The highest REM % over complete 2 h bins counted from the **start of the recording** (not clock-aligned). A final partial bin is ignored. NaN if the recording is shorter than one bin. | at least | 35 |

"Above" means strictly greater, "below" strictly less, "at least" greater than or equal.
The two bout metrics are rates, so 48 h and 72 h recordings are judged on the same scale.

Where the cutoffs came from: the first, second, fourth and sixth come from the spindle-validation
analysis (`file_flagging_metrics.ipynb`). REM = 10 was read from that notebook's REM plot. Wake = 70 is
a value judged reasonable for these recordings. All six are judgement-based starting points, not
validated cutoffs.

## Why these choices

The reasons, the evidence and how settled each choice is are in the [decision log](../decision_log.md):

- [Flagging metrics and thresholds](../decision_log.md#flagging-metrics-and-thresholds)
- [Exclusion criteria: noisy or wrong-looking data, by judgment](../decision_log.md#exclusion-criteria-noisy-or-wrong-looking-data-by-judgment)
- [Animals past a threshold are flagged for review automatically](../decision_log.md#animals-past-a-threshold-are-flagged-for-review-automatically)
- [The Needs Attention card shows when the EMG gate was applied](../decision_log.md#the-needs-attention-card-shows-when-the-emg-gate-was-applied)
- [Reviewer is blind to genotype](../decision_log.md#reviewer-is-blind-to-genotype)
- [Excluded animals are kept and marked, not dropped](../decision_log.md#excluded-animals-are-kept-and-marked-not-dropped)

## What it does

1. **Load.** Compute, from each CSV, the three Sleep-view tables (one per time axis) and the six flagging
   metrics. Use `final_state` when the CSV has it; an animal without it stays on the original states and is
   counted as "not reclassified". The result is cached until the CSV folder changes.
2. **Flag automatically.** After loading, any animal with **no decision yet** that is past a threshold is
   set to `needs_review`, with the metrics as its reasons. Animals already `needs_review`, `ok` or
   `excluded` are never changed. Nothing is flagged if Reclassify has not been run. It runs again only
   when the page next reloads its data (the CSV folder changed, or the app was restarted), so an animal
   you reset to undecided is flagged again then if it is still past a threshold.
3. **Overview.** Draw one boxplot per metric with every animal's point, the threshold as a dashed line, and
   past-threshold animals in red. Dot outlines show the status (green `ok`, orange `needs_review`);
   excluded dots are faded.
4. **Sleep view.** For each state (Wake, NREM, REM) and each 2 h bin, plot three things: **Fraction of
   time** (epochs in that state ÷ epochs in the bin), **# bouts** (whole bouts of that state, found over the
   whole recording and each counted once, in the bin that holds most of it, so none is cut at a bin edge) and **Mean bout duration (s)** (NaN if the bin has
   no bouts). The time axis sets where the bins sit:

   | Time axis | x-axis | Notes |
   |---|---|---|
   | Clock-aligned | Hours of clock time, increasing across the recording (for a 48 h recording starting at 22:00: 22, 24, … 70). No wrap at 24. | Bins sit at their true clock position, so the first and last bins are often shorter than 2 h and can look odd. |
   | Rotate to 6AM | Hours from the first 06:00 after the recording starts, labelled by clock hour. | The recording is rotated: the data before that first 06:00 wraps around to the end. A recording that never reaches the next 06:00 is skipped, and a warning appears when you select this axis. |
   | From Start | Hours since the first sample. | Bin 0 starts at sample 0. |

5. **Spindle mask view.** For each animal, the percent of Wake, NREM, REM and all epochs with
   `noise_prob` ≥ 0.5, counted under the states currently shown.
6. **Decide.** Each button writes to the manifest immediately (see Outputs). Review the Overview first, then
   go through **every** animal in the Sleep view: the Overview only highlights outliers.
7. **Settle reviews on Home.** An animal marked Review waits on Home under Needs Attention. Open its EDF
   there (or from the viewer's toolbar), look at the recording, and press OK or Exclude. Review is not a
   final answer: every such animal must end `ok` or `excluded`.

What to look for when deciding: sleep that is too fragmented, fractions of time in each state that are far
from the other animals, a large misclassification in one stretch of the recording, or a very noisy channel.
When you exclude, write a reason someone else could act on: where in the recording the problem is, which
channel, and whether the sleep scoring itself is wrong. An excluded animal is not deleted (see
[glossary](../glossary.md)).

## Outputs

This step writes only to `manifest.json`. There are no new files.

| Field | Values | Meaning |
|---|---|---|
| `sleep_qc` | `null` / `ok` / `needs_review` / `excluded` | Your decision. `ok` and `excluded` together are "decided", and PSD Computation needs every animal decided. |
| `flag_reasons` | list of metric keys | The metrics past their threshold when the animal was flagged (for example `["pct_rem", "max_bin_rem"]`). Shown on Home. Kept only while `sleep_qc` is `needs_review`; cleared by any other status. Pressing Review by hand records the metrics currently past a threshold, which can be none. |
| `notes` | text | Free text. An exclusion adds a line `Excluded (Sleep QC): <reason>`. The line stays if you later un-exclude. |
| `flag_thresholds` (project level) | metric key → cutoff | The cutoffs in force. Written back with the manifest. |

**Side effect.** Changing an animal's status to anything other than `ok` (including resetting it, flagging
it for review or excluding it) clears its PSD review progress in every run: `psd_status` and the drink-mask
link. An animal that was `ok` and already reviewed loses that review.

**On the page**

| Item | Meaning |
|---|---|
| Red line under the title | "Flagged for review automatically (past a threshold)" and the animals still waiting. |
| "EMG gate on N of M reclassified files" | How many animals the Reclassify EMG gate was applied to. The same animals get an `[EMG gate]` tag in the Sleep legend and an orange ring in the Spindle mask view. |
| "Not reclassified (run the Reclassify step)…" | No `final_state` anywhere. Everything shown is original SPINDLE states and nothing is flagged. |
| Blue box on Overview | "N of M animals still need a decision." Disappears when all are decided. |
| Orange "SWD review incomplete" | SWD review is on and unfinished. Informational. |
| Yellow box | "N animals flagged for review." Button goes to Home. |
| Green box | "All spindle metrics checked" (with the excluded count). Button goes to PSD Computation. |
| Red tag beside an animal | The metrics past a threshold (two names at most, then `+N`). Hover for each metric's value and threshold. |

## Check your work

- Every animal is `ok` or `excluded`: the green box appears and Home shows no review cards.
- Each excluded animal has a specific reason in its notes (visible on Home).
- For animals auto-flagged and settled, you opened the recording and are not relying on the Overview alone.

## If something goes wrong

- Everything is greyed or empty: no CSVs in `spindle_outputs/<COMBO>/`. Finish step 3.
- "Not reclassified": run step 4. "No sleep metrics yet. Run Reclassify first." appears on the Overview.
- A "Missing preprocessed EDFs" window lists animals with a CSV but no EDF in `standard/`. They are left out
  of the Clock-aligned and Rotate axes and of the flagging metrics. Re-run Preprocess for them.
- Animals vanish when you pick Rotate to 6AM: their recordings do not reach the next 06:00. Use Clock-aligned.
- The first or last bin looks wrong: it is probably a partial bin. Check the animal with Rotate to 6AM or From Start.
- An excluded animal should be included again: press Exclude again (it goes to `needs_review`), then OK. It needs a
  fresh PSD review.

## Used by

PSD Computation requires every animal to be `ok` or `excluded`. The PSD Visualizer and Drink Mask review only `ok`
animals. Finalize keeps excluded animals and marks them with their reasons. The sleep notebooks leave excluded animals
out by default. Details of that flow are in the step pages for those steps.

## Known limitations

- **"Max REM % in a 2 h bin" counts bins from the start of the recording**, while the Sleep view's default axis is clock-aligned, so the
  two can disagree about which bin holds the peak.
- **The time zone is fixed** at America/Chicago and cannot be changed on this page.
- **Pressing a pressed OK or Review resets the animal to undecided** and clears its PSD review progress.
