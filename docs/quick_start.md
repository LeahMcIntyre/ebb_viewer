# ebb-viewer quick start

This page gets you from nothing to finished results. It lists only what you **need to do** at each step. For the reasons behind a setting, screenshots, or what to do when something goes wrong, use the [user guide](user_guide.md).

**What ebb-viewer does:** it takes your EEG/EMG recordings, has SleepyRat (SPINDLE) score sleep, corrects the scoring, lets you check each animal's quality, and computes power spectra (PSDs) and sleep-by-hour tables.

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

Work **top to bottom in the sidebar**. **Home** shows where you are: a strip of steps, a table of your animals, and a **Needs Attention** list.

---

## Part 1. One-time setup

You need three things: **conda** (Miniconda is fine), **git**, and access to the GitHub repository (ask Leah to add you). You also need a **SleepyRat** account (https://sleepyrat.ai/).

Follow the click-by-click [Windows setup guide](windows_setup.md). It takes you from nothing to a working install. (This quick start is written for Windows; commands below are typed into **Anaconda Prompt**.)


**Start the app** (every time: open **Anaconda Prompt**, activate the environment, then run it):

```bat
conda activate ebb-dev
```

```bat
ebb-viewer
```

A window opens and asks you to choose a **project folder** (see Part 2).

---

## Part 2. Set up your project (before step 1)

**Four rules.** Most problems come from breaking one of these.

1. **One project folder per time point.** Put the raw `.edf` files for one time point in one new folder, and nothing else in it. (Animals from different time points would collide, because the animal ID is the part of the file name before the first `_`.)
2. **Name files `AnimalID_anything.edf`.** For example `CW0DC4_P098_KO_….edf` is animal `CW0DC4`.
3. **Channel order is fixed:** channel 1 = LFC, 2 = RSC, 3 = LSC, 4 = EMG. The app goes by position and does not check names.
4. **One file per animal, 48 h or 72 h long.** Recordings are trimmed to whole days and anything under 48 h is rejected (the default; the Preprocess page lets you change it).

**If a recording was stopped and restarted** (one animal has several short EDF files), combine them **before you open the app**. Skip this if every recording ran continuously.

Put the SWD `.mat` files in a folder called `swd/` and the annotation `.txt` files in a folder called `annotations/` (both optional), then, with `(ebb-dev)` active:

```bat
ebb-combine swd --dir C:\path\to\project\swd --move-short-files
```

```bat
ebb-combine annotations --dir C:\path\to\project\annotations --move-short-files
```

```bat
ebb-combine edf --dir C:\path\to\project --fs 5000 --move-short-files
```

This keeps the first 24 h of each chunk and joins them into one `…_COMBINED.edf`. The EDF step needs a lot of free memory (about 55 GB for two chunks), so close other programs first. Details: user guide, section 3.

**Open the project:** run `ebb-viewer` and choose your project folder. There is no "new project" button: choosing a folder starts a project, and choosing it again later resumes it. **Home looks empty until step 1 is done. That is normal.**

---

## Part 3. Extra files you may need

Besides the raw EDFs, some steps use extra files that **you prepare**. You only need the ones for the steps you will use:

- **Sleep staging and PSDs only:** nothing beyond the EDFs (plus a groups file if you want one for the notebooks).
- **Add SWD files** if you want SWD review (step 4b) or the SWD mask in step 6.
- **Add annotation files** if you want to mask jerks and jumps in step 6.
- **Add drink-event files and an offsets file** only if the PSD review (step 7) shows the drinking artifact.

Put each file in the project folder (the one you choose when ebb-viewer starts) unless the table says otherwise. **In every file name, the animal ID is the part before the first `_`, and it must match the EDF's animal ID exactly, including capitals** (`CW0DC4`, not `cw0dc4`).

| File | Needed for | Put it in | Name it | Where it comes from |
|---|---|---|---|---|
| **SWD file**, one per animal (`.mat`) | Step 4b (SWD Review) and the SWD mask in step 6 | `swd/` in the project folder | `AnimalID_anything.mat`, for example `CW0DC4_P098_DEL_ts.mat` | The lab's MATLAB SWD detection. An animal with no SWDs still gets a file: an empty one (below). |
| **Annotation file**, one per animal (`.txt`) | The annotation mask in step 6 (jerks and jumps) | Any folder; `annotations/` in the project folder is easiest. You choose the folder on the PSD page. | `AnimalID_anything.txt`, for example `CW0DC4_P098_KO_….txt` | Exported from the Pinnacle recording software, where the events were annotated (labels such as `Jerk - NREM` or `Jump - REM`). |
| **Drink-event file**, one per flagged animal (`.npy`) | Step 8 (Drink Mask) | `drink_masks/` in the project folder | Exactly `AnimalID.npy`, for example `CW0DC4.npy` | Made outside ebb-viewer with the lab's drinking-detection network, run on the recording video (exported from the PVFS file). In our lab, ask Claudia. |
| **Offsets file**, one for the whole project (`.csv`) | Step 8, unless the video and the EEG started at exactly the same moment | `drink_masks/`; it must be the **only** `.csv` there | Any name ending in `.csv`, for example `offsets.csv` | You write it. For each animal, the seconds from the start of the EEG recording to the start of the video, read from the PVFS file. |
| **Groups file** (`.csv`) | The notebooks in step 10 (instead of typing the groups) | Anywhere; next to the notebook is easiest. You type its path into the notebook. | Any name, for example `groups.csv` | You write it from your experiment records. |

**What goes inside**

- **SWD file:** a variable called `DEL_ts` holding one row per SWD, `[start, stop]`, in seconds from the start of the recording. For an animal with no SWDs, make an empty file. Open **Anaconda Prompt**, activate `ebb-dev`, go to the project folder (`cd C:\path\to\project`), and run this with the animal's ID in the name:

```bat
python -c "import numpy as np; from scipy.io import savemat; savemat('swd/CW0DB1_DEL_ts.mat', {'DEL_ts': np.empty((0, 2))})"
```

- **Annotation file:** use it exactly as exported (tab-separated, six lines of header, then a row per event with the columns `Time From Start` and `Annotation`). In step 6 you type keywords that appear in the annotation labels, such as `Jerk, Jump`.
- **Drink-event file:** a list of True/False values, **one value per second of the recording**, with True where the animal was drinking.
- **Offsets file:** two columns, `Animal` and `Offset`, one row per animal. The offset is in seconds, and **positive means the video started after the EEG**. Get these values manually from the PVFS file. For example (made-up numbers):

```
Animal,Offset
CW0DC4,125
CW0DB1,98
```

- **Groups file:** the easiest layout is one row per animal, with the columns `animal` and `group`:

```
animal,group
Mice-1248,WT
Mice-1251,MUT
```

  One column per group (the group name on top, its animals below) also works.

**Restarted recordings:** the SWD and annotation files of an animal whose recording was restarted are combined together with its EDFs (Part 2).

**Files ebb-viewer makes for you** (do not create these): `standard/`, `spindle_edfs/`, `spindle_outputs/`, `psd/`, `exports/`, and `manifest.json`.

---

## Part 4. The steps

Each step has the same three parts: **Do this**, **You're done when**, and **Watch out**.

### Step 1. Preprocess

**Do this**
1. Click **1. Preprocess** in the sidebar.
2. Check the scan line at the top (for example "Found 3 files · 48h 00m – 73h 47m").
3. Leave the settings as they are (5000 Hz in, downsample by 20, trim to 48 or 72 h).
4. Click **Run preprocessing**.

**You're done when** the log says "Done: N file(s) written" and **Home** lists all your animals.

**Watch out:** a red warning that an animal has more than one EDF means restarted recordings were not combined (Part 2). Recordings under 48 h fail.

### Step 2. Spindle EDFs

**Do this**
1. Click **2. Spindle EDFs**.
2. Leave **Ch0 (LFC)** and **Ch1 (RSC)** ticked. The EMG is always included. (Two EEG channels is best.)
3. Click **Run Spindle Preprocessor**.

**You're done when** the green bar says "Done. Spindle EDFs written."

**Watch out:** this step sets the **project's channel combo** (for example `LFC_RSC`). Choose it once, before step 3, and use the same one for every animal.

### Step 3. Spindle Upload

**Do this**
1. Click **3. Spindle Upload**.
2. Under **SleepyRat project**, choose **your own name**. If it is not in the list, click **New…** and enter it. If it is already there, do not create it again.
3. Leave **Remote folder name** as filled in.
4. Click **Upload & Download**.
5. The first time, a browser tab asks you to approve access for ebb. Log in with the appropriate credentials and approve it.
6. **Leave the app open.** It uploads, waits for SleepyRat to score the files, then downloads the results. With many files this often takes **more than an hour**, and that is normal.

**You're done when** the green bar says "Done. Labels downloaded — ready to reclassify."

**Watch out:** it is safe to click **Upload & Download** again if anything goes wrong. Files already uploaded and already downloaded are skipped.

### Step 4. Reclassify

**Do this**
1. Click **4. Reclassify**.
2. Click **Run reclassification**.

**You're done when** every animal has a **✓** in the Reclassified column and the EMG gate column says **applied** or **not needed** for each (either is normal).

**Watch out:** nothing needs your input here. It corrects SPINDLE's scoring where wake artifacts were scored as NREM, and keeps SPINDLE's original scoring. Everything after this step uses the corrected scoring.

### Step 4b. SWD Review (optional)

Do this step only if your project needs it (for example, if SWDs could make sleep look more fragmented in one genotype).

**Do this**
1. Put **one `.mat` file per animal** in `swd/`, named with the animal ID (see Part 3). For an animal with no SWDs, still add an empty `.mat` file (Part 3 has the one-line command).
2. Click **4b. SWD Review** and tick **Review SWD epochs for this project**.
3. Click **Review…** next to an animal. For each epoch that contains an SWD (highlighted in yellow): press **Space** to accept its state and move on, or press **w**, **n** or **r** to change it, then **Space**.
4. Click **Save**. You can save half-way and come back.

**You're done when** each animal shows "✓ N of N".

**Watch out:** a misclassified SWD epoch should get the state the animal was in before and after the SWD.

### Step 5. Sleep QC

**Every animal must end up either OK or Excluded.** PSD computation will not start until they all are. You do this in **two passes: first in the Sleep tab, then on Home.**

**Why animals get flagged.** The Overview marks an animal when a measure of its sleep goes past a threshold. The measures are ones that, in our own past data, made us suspicious of a noisy or misclassified recording: many very short NREM bouts (the sleep looks chopped up), too many NREM bouts per dark hour, too much or too little of one state (REM %, NREM %, wake %), or a big spike of REM in one 2-hour stretch. These are warning signs, **not rules**: a flagged animal may be fine, and an unflagged one may not be, so you still look at every animal.

**Do this**
1. Click **5. Sleep QC**. You start on the **Overview**: one boxplot per sleep measure, one dot per animal. Animals past a threshold are red.
2. Animals past a threshold that have no decision yet are **flagged for review automatically** (a red line lists them). You do not need to flag them yourself.
3. **First pass, the Sleep tab.** Click **Sleep** (top right) and go through **every** animal (use **Group** to see them together or **Animal** to see one at a time). Judge from the by-hour plots, then mark each animal:
   - **OK**: the sleep scoring looks fine.
   - **Review**: something looks off and you want to look at the actual recording.
   - **Exclude**: it is clearly wrong, or the EEG/EMG is very noisy. A written reason is required.
4. **Second pass, Home.** Go to **Home**. **Needs Attention** lists every animal you marked **Review** (and the automatically flagged ones), with the measures that flagged it. A card marked **[EMG gate]** means the EMG gate was used on that animal. For each card, click **Open EDF**, look at the recording, then mark the animal **OK** or **Exclude** (in the viewer's toolbar: **✓ Mark OK** or **Exclude**, or click **✓ OK** on the card if the animal is fine).
5. **Exclude needs a written reason.** Say where the problem is and what you saw, for example "lots of misclassification after hour 20, LSC channel noisy".

**Review is not a final answer.** Every animal you mark Review (or that was flagged automatically) must end as OK or Exclude after you look at it on Home.

**You're done when** every animal is OK or Excluded, nothing is left under **Needs Attention** for review, and the Sleep QC page says "All spindle metrics checked — ready for PSD computation."

**Watch out:** do this review **blind to genotype**. If the first or last time bin looks odd in the default view, switch **Time axis** to *Rotate to 6AM* or *From Start* and look again before deciding. An excluded animal is kept and marked, not deleted.

### Step 6. PSD Computation

**Do this**
1. Click **6. PSD Computation**. Check that every line in **READINESS** has a ✓ (a red ✗ blocks the run; the **Open … →** button takes you to the page that fixes it).
2. Leave the settings as they are.
3. If you use them, turn on the **SWD mask** (choose **Mask out SWDs**; needs a `.mat` for every animal in `swd/`) and the **annotation mask** (tick **Apply annotation mask**, choose the annotation folder, and enter keywords such as `Jerk, Jump`). The files are described in Part 3.
4. Type a **Run name** that says what the run is for (for example `default` or `final_run`).
5. Click **Run PSD Pipeline**.

**You're done when** the green bar says "PSDs computed — ready for PSD review."

**Watch out:** it takes from a few minutes to an hour or more. An animal with no annotation file is still computed, just without the annotation mask, and the READINESS list names these animals in amber.

### Step 7. PSD Visualizer

**Do this**
1. Click **7. PSD Visualizer** and choose your **Run**.
2. Click **Interpolate** and **Inverse Filter** in the toolbar (they only change what you see).
3. For each animal (**Prev** / **Next** or the arrow keys), look at the grid of plots. If you see small peaks near **52 Hz and 68 Hz** (the drinking artifact), press **Drink Mask** (key **D**). Otherwise press **✓ OK** (key **O**).

**You're done when** the page says "All animals in this run reviewed." (animals flagged **Drink Mask** are finished in step 8).

**Watch out:** do not exclude an animal from its PSD alone. Look into it first, and exclude only if you cannot find a solution (a reason is required).

### Step 8. Drink Mask (only if you flagged animals)

**You need** a drink-event file for each flagged animal, `drink_masks/<AnimalID>.npy`, and, unless the video and the EEG started at exactly the same moment, **one** offsets CSV in `drink_masks/` with the columns `Animal` and `Offset` (see Part 3 for what they contain and where they come from). These come from outside ebb-viewer; in our lab, ask Claudia.

**Do this**
1. Click **8. Drink Mask** and choose the same **PSD run**.
2. Check **READINESS**, then click **Apply Drink Masks**.
3. Click **→ PSD Visualizer** and open **Verify drink masks**. For each animal, press **✓ Mask worked** (the 52 and 68 Hz peaks are gone) or **✗ Redo mask** (they are still there).

**You're done when** every animal is OK and nothing is waiting to be verified.

### Step 9. Finalize

**Do this**
1. Click **9. Finalize**.
2. On your run's card, click **Finalize**.

**You're done when** the card shows when `psds_final.pkl` was written. **That file, in `psd/<run name>/`, is the one to use for analysis.** Excluded animals stay in it, marked as excluded.

**Watch out:** Finalize waits until every animal is reviewed. **Settings…** on the card shows the settings the run used; **Export to Excel** writes a workbook for Prism.

### Step 10. Get your tables and plots (notebooks)

Both notebooks are in the `analysis/` folder. **Make a copy for each analysis.** Open them with JupyterLab (`jupyter lab`), edit the **Settings** cell at the top, then choose **Run → Run All Cells**.

**PSD results**: copy `psd_analysis.ipynb` **and `psd_utils.py`** into the same folder, then set:
- `RUNS`: the path to each `psd/<run>/psds_final.pkl` (one entry per time point).
- `GROUPS` (type the animal IDs in each group) **or** `GROUPS_CSV` (the path to a groups file; see Part 3).
- `OUT_DIR` can stay as it is: results go in `psd_analysis/<run name>` next to your project's `psd` folder, one folder per run. The notebook prints the exact folder when it starts and finishes.

**Sleep results**: copy `sleep_by_hour.ipynb` and set `PROJECT_ROOT` (your project folder), `GROUPS` or `GROUPS_CSV`, and **`TZ` (your time zone: the default is `America/Chicago`)**. Results go in `<project>/sleep_analysis/`.

**You're done when** the notebook finishes without errors and the output folder holds your tables, plots and Prism workbooks.

---

## If you get stuck

| What you see | What to do |
|---|---|
| **Home** is empty | Run step 1 (Preprocess). Home lists animals from `standard/`. |
| A page says to run an earlier step first | Go back to that step (the sidebar order is the pipeline order). |
| **Run PSD Pipeline** is greyed out | Read the red ✗ lines in READINESS. Usually an animal has no OK/Exclude decision yet. |
| Upload & Download fails or stops | Click it again. Finished uploads and downloads are skipped. |
| An animal is missing from a list | Check that its `.edf` is directly in the project folder and the file name starts with its ID. |
| You excluded an animal by mistake | In **Sleep QC**, click **Exclude** again on that animal; it goes back to needs-review. |
| A notebook says it cannot find `psd_utils` | Copy `psd_utils.py` into the same folder as the notebook. |
| A notebook says `seaborn` or `jupyter` is missing | Your environment is older than the notebooks. Run `pip install seaborn jupyterlab` with `(ebb-dev)` active. |

**More detail:** the [user guide](user_guide.md) covers every page, every setting and what can go wrong. [psd_methods.md](psd_methods.md) lists the PSD settings and values, and the [decision log](decision_log.md) explains why they were chosen.

---

## Checklist

- [ ] One new folder per time point, with the raw EDFs (`AnimalID_anything.edf`, channels LFC, RSC, LSC, EMG)
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
