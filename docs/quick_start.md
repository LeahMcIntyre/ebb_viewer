# ebb-viewer quick start

This page gets you from nothing to finished
results with the lab defaults. It lists only what you **need to do** at each step. For what a setting means, what a step writes,
or what to do when something goes wrong, open the step page linked at each step. For the whole picture, see the
[overview](overview.md). Terms are in the [glossary](glossary.md).

**What ebb-viewer does:** it takes your EEG/EMG recordings, has SleepyRat (SPINDLE) score sleep, corrects the scoring, lets you
check each animal's quality, and computes power spectra (PSDs) and sleep-by-hour tables.

---

## The whole flow at a glance

| Step | Page in the app | What you do | Takes |
|---|---|---|---|
| 0 | (before the app) | Set up your project folder; combine restarted recordings if you have any | minutes |
| 1 | **1. Preprocess** | Click **Run preprocessing** | minutes |
| 2 | **2. Spindle EDFs** | Choose the channels, click **Run Spindle Preprocessor** | minutes |
| 3 | **3. Spindle Upload** | Pick your name, click **Upload & Download** | **often over an hour** (SleepyRat scores your files) |
| 4 | **4. Reclassify** | Click **Run reclassification** | a minute or two |
| 4b | **4b. SWD Review** | *Optional.* Check epochs that overlap spike-wave discharges | depends on the animal |
| 5 | **5. Sleep QC** | In the Sleep tab mark each animal OK, Review or Exclude; then on Home settle each Review as OK or Exclude | your time |
| 6 | **6. PSD Computation** | Click **Run PSD Pipeline** | a few minutes to an hour |
| 7 | **7. PSD Visualizer** | Mark each animal **OK** or **Drink Mask** | your time |
| 8 | **8. Drink Mask** | *Only if you flagged animals in step 7.* Apply the masks and verify | minutes |
| 9 | **9. Finalize** | Click **Finalize** | seconds |
| 10 | notebooks | Run the PSD and sleep notebooks to get tables and plots | minutes |

Work **top to bottom in the sidebar**. **Home** shows where you are: a strip of steps, a table of your animals, and a **Needs
Attention** list.

---

## Part 1. One-time setup

You need **conda** (Miniconda is fine), **git**, access to the code repository, and a **SleepyRat** account
(https://sleepyrat.ai/). Follow the click-by-click [Windows setup guide](windows_setup.md), which takes you from nothing to a working
install.

**Start the app** (every time: open **Anaconda Prompt**, activate the environment, then run it):

```bat
conda activate ebb-dev
```

```bat
ebb-viewer
```

A window opens and asks you to choose a **project folder** (Part 2).

---

## Part 2. Set up your project (before step 1)

**Five rules.** Most problems come from breaking one of these.

1. **One project folder per time point.** Put the raw `.edf` files for one time point in one new folder, and nothing else in it.
   (Animals from different time points would collide, because the animal ID is the part of the file name before the first `_`.)
2. **Name files `AnimalID_anything.edf`,** for example `CW0DC4_P098_KO_….edf` is animal `CW0DC4`. **No spaces in any file or folder
   name:** SleepyRat fails on them.
3. **Channel order is fixed:** channel 1 = LFC, 2 = RSC, 3 = LSC, 4 = EMG. The app goes by position and does not check names.
4. **One file per animal.** If a recording was stopped and restarted, see Combine below.
5. **Use the same animal ID in every file of an animal** (SWD, annotation, drink files), spelled and capitalised the same way.

**Combining restarted recordings (optional).** If a recording was stopped and restarted, so one animal has several short EDF files, combine them
with `ebb-combine` before you open the app. See [Combine](steps/00_combine.md). Skip this if every recording ran continuously.

**Open the project:** run `ebb-viewer` and choose your project folder. There is no "new project" button: choosing a folder starts a
project, and choosing it again later resumes it. **Home looks empty until step 1 is done. That is normal.**

---

## Part 3. Extra files you may need

Besides the raw EDFs, some steps use extra files that **you prepare**. You only need the ones for the steps you will use:

| File | Needed for | Put it in | Name it |
|---|---|---|---|
| **SWD file**, one per animal (`.mat`) | Step 4b (SWD Review) and the SWD mask in step 6 | `swd/` in the project folder | `AnimalID_anything.mat` |
| **Annotation file**, one per animal (`.txt`) | The annotation mask in step 6 (jerks and jumps) | any folder; you choose it on the PSD page | `AnimalID_anything.txt` |
| **Drink-event file**, one per flagged animal (`.npy`) | Step 8 (Drink Mask) | `drink_masks/` | exactly `AnimalID.npy` |
| **Offsets file**, one for the project (`.csv`) | Step 8, unless the video and EEG started together | `drink_masks/`, the **only** `.csv` there | any name ending `.csv` |
| **Groups file** (`.csv`) | The notebooks in step 10 | anywhere; you type its path into the notebook | any name |

Sleep staging and PSDs alone need nothing beyond the EDFs. The animal ID in each name must match the EDF's exactly, including capitals.

> **In our lab.** SWD files come from the lab's MATLAB SWD detector. Annotation files are exported from Pinnacle. Drink-event files come from
> the lab's drinking-detection network (ask Claudia), and the offsets are read by hand from the PVFS file.

What goes inside each file (formats, an example offsets file, how to make an empty SWD file for an animal with no SWDs) is on the
step pages: [SWD Review](steps/04b_swd_review.md), [PSD Computation](steps/06_psd_computation.md), [Drink Mask](steps/08_drink_mask.md)
and the [analysis notebooks](steps/analysis_notebooks.md) (groups file). The app creates `standard/`, `spindle_edfs/`,
`spindle_outputs/`, `psd/`, `exports/` and `manifest.json` for you; do not create them.

---

## Part 4. The steps

Each step has the same three parts: **Do this**, **You're done when**, and **Watch out**. Each links to its full page.

### Step 1. Preprocess — [full page](steps/01_preprocess.md)

**Do this**
1. Click **1. Preprocess** in the sidebar.
2. Check the scan line at the top (for example "Found 3 files · 48h 00m – 73h 47m").
3. Leave the settings as they are (5000 Hz in, downsample by 20).
4. Click **Run preprocessing**.

**You're done when** the log says "Done: N file(s) written" and **Home** lists all your animals.

**Watch out:** a red warning that an animal has more than one EDF means restarted recordings were not combined (Part 2). A red warning that
a file's rate does not match means the original sampling rate setting is wrong for it.

### Step 2. Spindle EDFs — [full page](steps/02_spindle_edfs.md)

**Do this**
1. Click **2. Spindle EDFs**.
2. Leave **Ch0 (LFC)** and **Ch1 (RSC)** ticked. The EMG is always included.
3. Click **Run Spindle Preprocessor**.

**You're done when** the green bar says "Done. Spindle EDFs written."

**Watch out:** this step sets the **project's channel combo** (for example `LFC_RSC`). Choose it once, before step 3, and use the same one for
every animal. Writing a different combo later switches the project to it and a window warns you first.

### Step 3. Spindle Upload — [full page](steps/03_spindle_upload.md)

**Do this**
1. Click **3. Spindle Upload**.
2. Under **SleepyRat project**, choose **your own name**. If it is not in the list, click **New…** and enter it. If it is already there, do
   not create it again.
3. Leave **Remote folder name** as filled in.
4. Click **Upload & Download**.
5. The first time, a browser tab asks you to approve access for ebb. Log in and approve it.
6. **Leave the app open.** It uploads, waits for SleepyRat to score the files, then downloads the results. With many files this often takes
   **more than an hour**, and that is normal.

> **In our lab.** The SleepyRat username is `xuelab`; the password is the lab's standard password.

**You're done when** the green bar says "Done. Labels downloaded — ready to reclassify."

**Watch out:** SleepyRat **fails if any file, folder or project name has a space**. It is safe to click **Upload & Download** again if anything
goes wrong: files already uploaded and downloaded are skipped. To score an animal again after rebuilding its EDF, you must also delete its
old entry on the SleepyRat website (see the full page).

### Step 4. Reclassify — [full page](steps/04_reclassify.md)

**Do this**
1. Click **4. Reclassify**.
2. Click **Run reclassification**.

**You're done when** every animal has a **✓** in the Reclassified column and the EMG gate column says **applied** or **not needed** for each
(either is normal).

**Watch out:** nothing needs your input here. It corrects SPINDLE's scoring where wake artifacts were scored as NREM, and keeps SPINDLE's
original scoring. Everything after this step uses the corrected scoring.

### Step 4b. SWD Review (optional) — [full page](steps/04b_swd_review.md)

Do this step only if your project needs it (for example, if SWDs could make sleep look more fragmented in one genotype).

**Do this**
1. Put **one `.mat` file per animal** in `swd/`, named with the animal ID. For an animal with no SWDs, add an empty `.mat` file (the page has the
   one-line command) or use **Confirm no SWD** on the review page.
2. Click **4b. SWD Review** and tick **Review SWD epochs for this project**.
3. Click **Review…** next to an animal. For each epoch that contains an SWD (highlighted in yellow): press **Space** to accept its state and move
   on, or press **w**, **n** or **r** to change it, then **Space**.
4. Click **Save**. You can save half-way and come back.

**You're done when** each animal shows "✓ N of N".

**Watch out:** a misclassified SWD epoch should get the state the animal was in before and after the SWD. If you will use the SWD mask in step 6,
every animal still needs a `.mat` file; **Confirm no SWD** does not count for that.

### Step 5. Sleep QC — [full page](steps/05_sleep_qc.md)

**Every animal must end up either OK or Excluded.** PSD computation will not start until they all are. You do this in **two passes: first in the
Sleep tab, then on Home.**

**Why animals get flagged.** The Overview marks an animal when a measure of its sleep goes past a threshold: many very short NREM bouts, too many
NREM bouts per dark hour, too much or too little of one state (REM %, NREM %, wake %), or a big spike of REM in one 2-hour stretch. These are
warning signs, **not rules**: a flagged animal may be fine, and an unflagged one may not be, so you still look at every animal.

**Do this**
1. Click **5. Sleep QC**. You start on the **Overview**: one boxplot per measure, one dot per animal. Animals past a threshold are red.
2. Animals past a threshold that have no decision yet are **flagged for review automatically** (a red line lists them).
3. **First pass, the Sleep tab.** Click **Sleep** (top right) and go through **every** animal (**Group** shows them together, **Animal** one at a
   time). Judge from the by-hour plots, then mark each animal:
   - **OK**: the sleep scoring looks fine.
   - **Review**: something looks off and you want to look at the actual recording.
   - **Exclude**: it is clearly wrong, or the EEG/EMG is very noisy. A written reason is required.
4. **Second pass, Home.** **Needs Attention** lists every animal marked **Review** (and the automatically flagged ones), with the measures that
   flagged it. A card marked **[EMG gate]** means the EMG gate was used on that animal. For each card, click **Open EDF**, look at the recording,
   then mark the animal **OK** or **Exclude** (in the viewer's toolbar, or click **✓ OK** on the card if the animal is fine).
5. **Exclude needs a written reason.** Say where the problem is and what you saw, for example "lots of misclassification after hour 20, LSC channel
   noisy".

**Review is not a final answer.** Every animal marked Review (or flagged automatically) must end as OK or Exclude.

**You're done when** every animal is OK or Excluded, nothing is left under **Needs Attention** for review, and the page says "All spindle metrics
checked — ready for PSD computation."

**Watch out:** review **blind to genotype**. If the first or last time bin looks odd in the default view, switch **Time axis** to *Rotate to 6AM* or
*From Start* before deciding. An excluded animal is kept and marked, not deleted. Changing an animal away from OK clears its PSD review progress.

### Step 6. PSD Computation — [full page](steps/06_psd_computation.md)

**Do this**
1. Click **6. PSD Computation**. Check that every line in **READINESS** has a ✓ (a red ✗ blocks the run; the **Open … →** button takes you to
   the page that fixes it).
2. Leave the settings as they are.
3. In our lab we use both masks: turn on the **SWD mask** (choose **Mask out SWDs**; needs a `.mat` for every animal in `swd/`) and the
   **annotation mask** (tick **Apply annotation mask**, choose the annotation folder, and enter keywords such as `Jerk, Jump`).
4. Type a **Run name** that says what the run is for (for example `default` or `final_run`).
5. Click **Run PSD Pipeline**.

**You're done when** the green bar says "PSDs computed — ready for PSD review."

**Watch out:** it takes from a few minutes to an hour or more. An animal with no annotation file is still computed, just without the annotation
mask, and READINESS names these animals in amber. Re-running a run name that already has drink masks leaves the old drink files in place (see
[Drink Mask](steps/08_drink_mask.md)).

### Step 7. PSD Visualizer — [full page](steps/07_psd_visualizer.md)

**Do this**
1. Click **7. PSD Visualizer** and choose your **Run**.
2. Click **Interpolate** and **Inverse Filter** in the toolbar. They start switched off and only change what you see.
3. For each animal (**Prev** / **Next** or the arrow keys), look at the grid of plots. If you see small peaks near **52 Hz and 68 Hz** (the drinking
   artifact), press **Drink Mask** (key **D**). Otherwise press **✓ OK** (key **O**).

**You're done when** the page says "All animals in this run reviewed." (animals flagged **Drink Mask** are finished in step 8).

**Watch out:** do not exclude an animal from its PSD alone. Look into it first, and exclude only if you cannot find a solution (a reason is required).

### Step 8. Drink Mask (only if you flagged animals) — [full page](steps/08_drink_mask.md)

**You need** a drink-event file for each flagged animal, `drink_masks/<AnimalID>.npy`, and, unless the video and the EEG started at exactly the same
moment, **one** offsets CSV in `drink_masks/` with the columns `Animal` and `Offset`.

**Do this**
1. Click **8. Drink Mask** and choose the same **PSD run**.
2. Check **READINESS**, then click **Apply Drink Masks**.
3. Click **→ PSD Visualizer** and open **Verify drink masks**. For each animal, press **✓ Mask worked** (the 52 and 68 Hz peaks are gone) or
   **✗ Redo mask** (they are still there).

**You're done when** every animal is OK and nothing is waiting to be verified.

**Watch out:** if an offsets CSV is present, it needs a row for every animal being rerun.

### Step 9. Finalize — [full page](steps/09_finalize.md)

**Do this**
1. Click **9. Finalize**.
2. On your run's card, click **Finalize**.

**You're done when** the card shows when `psds_final.pkl` was written. **That file, in `psd/<run name>/`, is the one to use for analysis.** Excluded
animals stay in it, marked as excluded.

**Watch out:** Finalize waits until every animal is reviewed. Finalizing again **overwrites the file without asking**, and the exclusions in it are a
snapshot from the day you clicked, so click **Re-finalize** after changing one. **Export to Excel** writes the stored PSDs for Prism, without the
inverse filter or interpolation.

### Step 10. Get your tables and plots (notebooks) — [full page](steps/analysis_notebooks.md)

Both notebooks are in the `analysis/` folder, and each has a script version that gives the same output. **Make a copy for each analysis.** Open a
notebook with JupyterLab (`jupyter lab`), edit the **Settings** cell at the top, then choose **Run → Run All Cells**.

**PSD results**: copy `psd_analysis.ipynb` **and `psd_utils.py`** into the same folder, then set:
- `RUNS`: the path to each `psd/<run>/psds_final.pkl` (one entry per time point).
- `GROUPS` (the animal IDs in each group) **or** `GROUPS_CSV` (the path to a groups file).
- `OUT_DIR` can stay as it is: results go in `psd_analysis/<run name>` next to your project's `psd` folder. The notebook prints the exact folder when
  it starts and finishes.

**Sleep results**: copy `sleep_by_hour.ipynb` and set `PROJECT_ROOT` (your project folder), `GROUPS` or `GROUPS_CSV`, and **`TZ` (your time zone: the
default is `America/Chicago`)**. Results go in `<project>/sleep_analysis/`.

**You're done when** the notebook finishes without errors and the output folder holds your tables, plots and Prism workbooks.

---

## If you get stuck

| What you see | What to do |
|---|---|
| **Home** is empty | Run step 1 (Preprocess). Home lists animals from `standard/`. |
| A page says to run an earlier step first | Go back to that step (the sidebar order is the pipeline order). |
| **Run PSD Pipeline** is greyed out | Read the red ✗ lines in READINESS. Usually an animal has no OK/Exclude decision yet. |
| **Run preprocessing** is greyed out | The original rate does not divide by the downsample factor, or a file's rate does not match the setting. |
| Upload & Download fails or stops | Click it again; finished uploads and downloads are skipped. Check that no file or folder name has a space. |
| An animal is missing from a list | Check that its `.edf` is directly in the project folder and the file name starts with its ID. |
| You excluded an animal by mistake | In **Sleep QC**, click **Exclude** again on that animal; it goes back to needs-review. |
| The EEG viewer is blank, glitchy or crashes when it opens a recording | The viewer draws with OpenGL by default. Turn that off, then start the app again: in Anaconda Prompt run `set EBB_VIEWER_USE_OPENGL=0` and then `ebb-viewer`. It is slower on long recordings but works without OpenGL. |
| The EEG viewer says a file needs too much memory | The viewer loads the whole recording; a raw 5000 Hz file is too large. Open the preprocessed file from `standard/`. |
| A notebook says it cannot find `psd_utils` | Copy `psd_utils.py` into the same folder as the notebook. |
| A notebook says `seaborn` or `jupyter` is missing | Your environment is older than the notebooks. Run `pip install seaborn jupyterlab` with `(ebb-dev)` active. |

**More detail:** the [overview](overview.md) shows every step's inputs and outputs, and each step page above covers every setting and what can go wrong.

---

## Checklist

- [ ] One new folder per time point, with the raw EDFs (`AnimalID_anything.edf`, no spaces, channels LFC, RSC, LSC, EMG)
- [ ] Restarted recordings combined (if any)
- [ ] Extra files in place for the steps you will use (Part 3): SWD files, annotation files, drink-event files and offsets file, groups file
- [ ] 1. Preprocess
- [ ] 2. Spindle EDFs (project combo set)
- [ ] 3. Spindle Upload (labels downloaded)
- [ ] 4. Reclassify
- [ ] 4b. SWD Review (if your project uses it)
- [ ] 5. Sleep QC: Sleep tab (OK / Review / Exclude), then Home (each Review settled): **every animal OK or Excluded**
- [ ] 6. PSD Computation
- [ ] 7. PSD Visualizer: every animal reviewed
- [ ] 8. Drink Mask: applied and verified (if any animal was flagged)
- [ ] 9. Finalize → `psds_final.pkl`
- [ ] 10. Notebooks run, results saved
