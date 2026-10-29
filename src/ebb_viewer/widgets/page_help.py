"""Optional per-page help: a small "?" button that opens that page's instructions.

The text lives in ``PAGE_HELP`` (one entry per page key) so instructions can be edited without
touching page code. Pages build their title row with ``title_row``.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# How to make an SWD file for an animal with no SWDs (used by the SWD Review and PSD help).
_EMPTY_MAT_HTML = """
<h4>Making an empty SWD file</h4>
<p>The file holds one array named <code>DEL_ts</code> with two columns (start and stop, in
seconds) and no rows. Open a terminal <b>in the project folder</b>, activate the
<code>ebb-dev</code> environment, and run the command below, replacing <code>AM0001</code> with the
animal's ID:</p>
<pre>python -c "import numpy as np; from scipy.io import savemat; savemat('swd/AM0001_DEL_ts.mat', {'DEL_ts': np.empty((0, 2))})"</pre>
<p>This creates <code>swd/AM0001_DEL_ts.mat</code>. Create the <code>swd/</code> folder first if it
doesn't exist, and repeat the command for each animal that needs one.</p>
"""

# page key -> (dialog title, HTML body). Keep each body to: what it does, what it needs, what next.
PAGE_HELP: dict[str, tuple[str, str]] = {
    "reclassify": (
        "Reclassify NREM",
        """
<h4>What it does</h4>
<p>Gap-fills NREM epochs that sit next to (or between) artifact epochs, then applies the EMG gate.
The gate only acts when gap fill would fragment light-period NREM by more than 10%; a flip is
kept only if the epoch's EMG is clearly above the NREM baseline. The result is written to each
spindle CSV as <code>reclass_state</code> and <code>final_state</code>. Originals are kept in
<code>_original</code>.</p>
<h4>Needs</h4>
<p>Spindle outputs downloaded for every animal (Spindle Upload page).</p>
<h4>Good to know</h4>
<ul>
<li>Safe to re-run. Saved SWD review edits are kept and re-applied.</li>
<li>The <b>Gap-fill flips kept / cancelled</b> column shows what the EMG gate decided. If it says
the record is missing, re-run to restore it.</li>
<li>All later analysis reads <code>final_state</code>.</li>
</ul>
<h4>Next</h4>
<p>SWD Review (optional), then Sleep QC.</p>
""",
    ),
    "swd_review": (
        "SWD Review (optional)",
        """
<h4>What it does</h4>
<p>Lets you step through 4 s epochs that overlap a spike-wave discharge and correct their sleep
state. Edits go into <code>swd_reclassification</code> and update <code>final_state</code>.</p>
<h4>Keys in the review window</h4>
<table cellpadding="3">
<tr><td><b>W / N / R</b></td><td>set the selected epoch to Wake / NREM / REM</td></tr>
<tr><td><b>Space</b></td><td>next SWD epoch</td></tr>
<tr><td><b>Shift+Space</b></td><td>previous SWD epoch</td></tr>
<tr><td><b>Left / Right</b></td><td>scroll the trace</td></tr>
</table>
<h4>Needs</h4>
<ul>
<li>Reclassify must have been run first. Re-running it keeps your edits.</li>
<li><b>SWD time-stamp files</b>: one <code>.mat</code> file per animal in the project's
<code>swd/</code> folder, holding the SWD start and stop times in seconds. The file name must start
with the animal ID, for example <code>JK1011_P063_DEL_ts.mat</code> or <code>Mice-1256.mat</code>.
The ID is the text before the first <code>_</code>, after an optional prefix ending in
<code>ts_</code>.</li>
</ul>
<h4>An animal with no SWDs</h4>
<p>Give it an <b>empty <code>.mat</code> file</b> (best practice, because the SWD mask in the PSD
step also looks for a file for every animal). If you really do not want a file, click
<b>Confirm no SWD</b> on that animal's row to override the requirement.</p>
@@EMPTY_MAT@@
<h4>Next</h4>
<p>Sleep QC.</p>
""",
    ),
    "sleep_qc": (
        "Sleep QC",
        """
<h4>What it does</h4>
<p>Review sleep staging for each animal and mark it OK, Review or Exclude. Excluding requires a
reason, which is saved in the animal's notes.</p>
<h4>Views</h4>
<ul>
<li><b>Overview</b>: boxplots of the flagging metrics. Animals past a threshold are highlighted and
can be flagged from here.</li>
<li><b>Sleep</b>: the by-hour grid with the OK / Review / Exclude buttons.
<b>You must go through this tab to decide every animal.</b></li>
<li><b>Spindle mask</b>: percent of each state (and total) masked as artifact, per animal.</li>
</ul>
<p>Metrics and plots use the reclassified states. <b>Show original</b> switches to the original
SPINDLE states for comparison.</p>
<h4>Reviewing the EDF</h4>
<p>Animals marked Review appear on <b>Home</b>. Use <b>Open EDF</b> on their card to look at the
recording, then mark them OK or Exclude there.</p>
<h4>Next</h4>
<p>PSD, once every animal is decided (OK or Excluded).</p>
""",
    ),
    "home": (
        "Home",
        """
<h4>What it does</h4>
<p>Shows where the project stands and what needs your attention.</p>
<p><b>Animals only appear in the table after Preprocess (step 1) has written their downsampled
EDFs to <code>standard/</code>.</b> Until then Home is empty, apart from a count of the EDFs
it finds in the project folder.</p>
<h4>Reading it, top to bottom</h4>
<ul>
<li><b>Progress strip</b>: one chip per step plus a next-step banner with an <b>Open</b> button.
Click a chip to jump to that page.</li>
<li><b>Animals table</b>: one row per animal with its status in each step. The <b>PSD run</b>
filter picks which run's statuses are shown. Double-click an animal ID to open its EDF in the
EEG viewer; double-click a notes cell to edit the notes.</li>
<li><b>Needs Attention</b>: animals marked Review in Sleep QC (with the metrics that flagged
them) and animals flagged for a drink mask. <b>This is where you review the EDFs of Review
animals</b>: use <b>Open EDF</b>, then <b>OK</b> or <b>Exclude</b>.</li>
</ul>
<h4>Other controls</h4>
<p><b>Import new animals</b> re-scans <code>standard/</code> and never overwrites existing flags.
<b>Refresh</b> reloads the manifest.</p>
""",
    ),
    "preprocess": (
        "Preprocess",
        """
<h4>What it does</h4>
<p>Trims, downsamples and standardizes the raw EDFs into <code>standard/</code>. The raw files
are not changed.</p>
<h4>Where the raw EDFs go</h4>
<p>Put them <b>directly in the project folder</b> (the folder you chose when you opened the
project). Subfolders are not searched.</p>
<h4>Needs</h4>
<ul>
<li>One EDF per animal (combine restarted recordings first). A red warning appears if an animal
has more than one.</li>
<li>File names like <code>AnimalID_anything.edf</code>: the ID is the text before the first
<code>_</code>.</li>
<li>Channel order LFC, RSC, LSC, EMG.</li>
</ul>
<h4>Settings</h4>
<table cellpadding="3">
<tr><td><b>Original sampling frequency</b></td><td>the rate the files were recorded at (default 5000 Hz).
Every file's header is checked against it; Run stays disabled if any differ.</td></tr>
<tr><td><b>Downsample factor</b></td><td>default 20 (5000 to 250 Hz). The original rate must divide
evenly by it. The rest of the pipeline assumes 250 Hz.</td></tr>
<tr><td><b>Trim To (hrs)</b></td><td>each recording is trimmed to the longest target that fits
(default 48, 72). A recording shorter than the smallest target fails. See below.</td></tr>
</table>
<h4>Using Trim To</h4>
<ul>
<li>Each box is one target length in hours. <b>Edit the number</b> in a box to change it.</li>
<li>Click <b>+</b> to add another target (up to four).</li>
<li>Click <b>&minus;</b> to remove the last one. With a single box left, every recording is
trimmed to that one length.</li>
<li>Example with 48 and 72: a 60 h recording trims to 48 h and an 80 h recording to 72 h. The
line under the settings shows how many recordings will go to each length, and warns in red about
any that will fail.</li>
</ul>
<h4>Why 250 Hz</h4>
<p>The pipeline after this step assumes 250 Hz data (the default 5000 Hz divided by 20). Keep the
downsample factor at 20 unless your recordings were acquired at another rate.</p>
<h4>Next</h4>
<p>Spindle Write.</p>
""",
    ),
    "spindle": (
        "Create Spindle EDFs",
        """
<h4>What it does</h4>
<p>Writes a small copy of each preprocessed EDF with only the channels SPINDLE needs, in
<code>spindle_edfs/&lt;COMBO&gt;/</code>. EMG is always included.</p>
<h4>This sets the project's channel combo</h4>
<p>Tick exactly 1 or 2 EEG channels (default LFC and RSC, giving <code>LFC_RSC</code>). When the
step finishes, that combo is saved in <code>manifest.json</code> and every later page uses it.</p>
<ul>
<li>Choose it once, before you upload. Every animal must be scored the same way.</li>
<li>Running again with a different combo changes the project combo. To go back, edit
<code>combo</code> in <code>manifest.json</code> yourself.</li>
</ul>
<h4>Next</h4>
<p>Spindle Upload.</p>
""",
    ),
    "spindle_upload": (
        "Spindle Upload",
        """
<h4>What it does</h4>
<p>Uploads the SPINDLE EDFs to SleepyRat for scoring and downloads one label CSV per animal into
<code>spindle_outputs/&lt;COMBO&gt;/</code>. The <b>Upload &amp; Download</b> button does both.</p>
<h4>Needs</h4>
<p>A <b>SleepyRat subscription</b> (SleepyRat was previously called SPINDLE). You sign in to
https://sleepyrat.ai/ with your own account.</p>
<h4>Steps</h4>
<ol>
<li>Pick <b>your own name</b> as the SleepyRat project. Use <b>New</b> only if your name is not in
the list.</li>
<li>Check the remote folder name (filled in for you).</li>
<li>Click <b>Upload &amp; Download</b>.</li>
</ol>
<h4>First time on a new computer</h4>
<p>A browser window opens asking you to log in to SleepyRat. Log in and <b>approve the device</b>;
the app waits. The approval is remembered on that computer.</p>
<h4>Good to know</h4>
<ul>
<li>Scoring can take over an hour for many files. Leave the app open.</li>
<li><b>If anything goes wrong, just run it again.</b> Files already uploaded or downloaded are
skipped, so a re-run only fetches the downloads that are missing.</li>
<li>Epochs are 4 s and scored Wake, NREM or REM.</li>
</ul>
<h4>If you make a new EDF for an animal that was already uploaded</h4>
<p>Files are matched by name, so SleepyRat will skip the new one. <b>Delete the old entry for that
animal in your folder on the SleepyRat website</b> first. An existing label CSV is also never
overwritten, so delete that animal's CSV in <code>spindle_outputs/</code> and run again.</p>
<p><b>Or give the new EDF a different animal ID.</b> SleepyRat then treats it as a separate animal
and nothing needs deleting. Every other file for that animal must use the <b>new ID</b> too (SWD
<code>.mat</code>, annotation, drink mask and so on), because files are paired with an EDF by
exact animal ID.</p>
<h4>Next</h4>
<p>Reclassify.</p>
""",
    ),
    "psds": (
        "PSD Computation",
        """
<h4>What it does</h4>
<p>Computes power spectral densities for each animal, per sleep state and channel, with artifacts
masked out. Excluded animals are computed too and stay marked excluded.</p>
<h4>Needs</h4>
<ul>
<li>A Sleep QC decision (OK or Excluded) for every animal.</li>
<li><b>For the SWD mask</b>: one <code>.mat</code> file per animal in the project's
<code>swd/</code> folder (an empty one is fine). The name must start with the animal ID, for
example <code>JK1011_P063_DEL_ts.mat</code>: the ID is the text before the first <code>_</code>,
after an optional prefix ending in <code>ts_</code>. Every animal needs one when the mask is on.</li>
<li><b>For the annotation mask</b>: one annotation file per animal (<code>.txt</code>,
<code>.csv</code> or <code>.tsv</code>) in a single folder that you pick on this page. The animal ID
is the text before the first <code>_</code> in the file name. If two files share an ID, the last
one found is used. An animal with no annotation file is still computed, without the mask (the
checklist warns you).</li>
</ul>
@@EMPTY_MAT@@
<h4>Settings</h4>
<p>The defaults are the ones the lab uses; leave them unless you have a reason. <b>Restore
defaults</b> resets them.</p>
<table cellpadding="3">
<tr><td><b>States</b></td><td>Wake, NREM and REM by default. Sleep (NREM + REM) and All are also
available.</td></tr>
<tr><td><b>Channels</b></td><td>all three EEG channels by default. A sample flagged on any
selected channel is masked on all of them.</td></tr>
<tr><td><b>Commutator</b></td><td>masks samples beyond &plusmn;2000 &micro;V (cable/commutator
artifact), merging events closer than 1 s.</td></tr>
<tr><td><b>SD threshold</b></td><td>masks samples more than 5 standard deviations from the mean in
180 s windows. Applied to Wake only.</td></tr>
<tr><td><b>SPINDLE noise</b></td><td>drops epochs where SPINDLE's noise probability is 0.5 or
higher.</td></tr>
<tr><td><b>60 Hz notch</b></td><td>filters 57&ndash;63 Hz out of the signal after the masks are
computed.</td></tr>
<tr><td><b>SWD mask</b></td><td>choose <b>Mask out SWDs</b>. <b>Pad each event</b> adds seconds on
each side (default 0).</td></tr>
<tr><td><b>Annotation mask</b></td><td>tick it, pick the folder and enter comma-separated keywords.
<b>Contains</b> matches any label containing a keyword (not case-sensitive); <b>Exact</b> needs the
whole label. <b>Pad before / after</b> extend each event.</td></tr>
<tr><td><b>Hour window</b></td><td>rarely used: keeps only certain clock hours, for example to
compute light and dark periods separately.</td></tr>
<tr><td><b>Sampling frequency</b></td><td>250 Hz. Don't change it for this data.</td></tr>
</table>
<p>Drink masks are not applied here; that happens on the Drink Mask page.</p>
<h4>Run name and outputs</h4>
<p><b>Run name</b> names the results folder. Use a name that says what the run is for; several runs
can sit side by side. Results are saved in <code>psd/&lt;run name&gt;/</code>:</p>
<ul>
<li><code>psds_&lt;COMBO&gt;.pkl</code>: the PSDs for every animal (for example
<code>psds_LFC_RSC.pkl</code>).</li>
<li><code>psd_params.json</code>: the exact settings used.</li>
</ul>
<p>Drink Mask and Finalize add <code>psds_&lt;COMBO&gt;_drink.pkl</code> and
<code>psds_final.pkl</code> to the same folder.</p>
<h4>Readiness</h4>
<p>Read the checklist before running. A red mark blocks the run; amber is a warning. The
<b>Open</b> button on a failed check takes you to the page that fixes it.</p>
<h4>Next</h4>
<p>PSD Visualizer.</p>
""",
    ),
    "psd_visualizer": (
        "PSD Visualizer",
        """
<h4>What it does</h4>
<p>Review each OK animal's PSDs. Mark <b>OK</b>, flag a <b>Drink Mask</b>, or <b>Exclude</b>.</p>
<h4>What to look for</h4>
<p>A drinking (water bottle) artifact shows as small peaks, or sidebands, around
<b>52 and 68 Hz</b>, on either side of the 60 Hz line-noise gap. If you see them, press Drink
Mask. Otherwise press OK.</p>
<h4>Keys</h4>
<table cellpadding="3">
<tr><td><b>O</b></td><td>OK (in the verify pass: Mask worked)</td></tr>
<tr><td><b>D</b></td><td>Drink Mask (in the verify pass: Redo mask)</td></tr>
<tr><td><b>Left / Right</b></td><td>previous / next animal</td></tr>
</table>
<p>Exclude has no key on purpose.</p>
<h4>Two passes</h4>
<ul>
<li><b>Review PSDs</b>: the first look at every animal.</li>
<li><b>Verify drink masks</b>: check animals recomputed on the Drink Mask page. Good means the
sidebands are gone.</li>
</ul>
<h4>Toolbar</h4>
<p><b>Interpolate</b> and <b>Inverse Filter</b> are display-only: they change what you see, not
the saved PSDs, the sealed file or the Excel export. Turn both on for the review.</p>
<ul>
<li><b>Interpolate</b> draws a straight bridge over the gap the 60 Hz line noise leaves, so it
doesn't dominate the plot. If the run used the notch filter (the default) the range is
<b>56&ndash;64 Hz</b>; for a run without it, <b>58&ndash;62 Hz</b>. <b>Set Interp-Range</b> changes
it.</li>
<li><b>Inverse Filter</b> multiplies the lowest frequencies (0.5&ndash;3.5 Hz) by correction
factors, to make up for the recording hardware's roll-off at low frequencies. The largest factor
(about 2.5x) is at 0.5 Hz and it falls to about 1x by 3.5 Hz.</li>
<li><b>Log-X</b> and <b>Log-Y</b> switch the axes (Log-Y is on by default).
<b>Set X-Range</b> and <b>Reset zoom</b> change the frequency range shown.</li>
</ul>
<h4>Excluding</h4>
<p>Don't exclude an animal from its PSD alone. Look into it separately first (for example in the
EEG viewer). A reason is required.</p>
<h4>Next</h4>
<p>Drink Mask for flagged animals, then Finalize once every animal is reviewed.</p>
""",
    ),
    "drink_mask": (
        "Drink Mask Rerun",
        """
<h4>What it does</h4>
<p>Recomputes the PSDs of animals flagged <b>Drink Mask</b> with drinking events masked out, so
the 52 and 68 Hz sidebands go away. Each event is padded by 2 s each side.</p>
<h4>Needs</h4>
<ul>
<li><b>A drink-event file per flagged animal</b>: <code>drink_masks/&lt;AnimalID&gt;.npy</code>,
one true/false value per second of recording. <b>This is not computed in ebb.</b> It comes from
a neural network that detects drinking from the recording video, so you need the video (exported
from the PVFS file). Animals without a file are skipped.</li>
<li><b>An offsets CSV</b>, if the video and EEG did not start at the same moment. It goes in
<code>drink_masks/</code> with the columns <code>Animal</code> and <code>Offset</code>, one row per
animal. <code>Offset</code> is the time in seconds from the start of the EEG to the start of the
video (positive means the video starts later).</li>
</ul>
<h4>How the offsets CSV is used</h4>
<table cellpadding="3">
<tr><td><b>One CSV</b></td><td>its offsets are applied to each animal's mask.</td></tr>
<tr><td><b>No CSV</b></td><td>no offset is used; the video is assumed to start with the EEG.</td></tr>
<tr><td><b>Two or more CSVs</b></td><td>an error: the page doesn't know which to use, and the run is
blocked until only one is left.</td></tr>
</table>
<p>If the CSV is missing the <code>Animal</code> or <code>Offset</code> column, the page also
reports an error.</p>
<h4>Steps</h4>
<ol>
<li>Choose the <b>PSD run</b> you reviewed. Its settings are rebuilt exactly, plus the drink mask.</li>
<li>Check <b>Readiness</b>.</li>
<li>Click <b>Apply Drink Masks</b>. Only flagged animals are recomputed; originals are never
overwritten.</li>
</ol>
<h4>Next</h4>
<p>Back in the PSD Visualizer, use <b>Verify drink masks</b>.</p>
""",
    ),
    "finalize": (
        "Finalize",
        """
<h4>What it does</h4>
<p>Seals each PSD run into one file, <code>psd/&lt;run&gt;/psds_final.pkl</code>. This is the file
to use for analysis.</p>
<h4>Needs</h4>
<p>Every animal in the run reviewed (OK, Excluded, or drink mask verified). The run's card says
what is still pending.</p>
<h4>Controls</h4>
<ul>
<li><b>Settings</b>: the exact settings that run used.</li>
<li><b>Finalize</b>: writes <code>psds_final.pkl</code>. Clicking it again replaces the file.</li>
<li><b>Export to Excel</b>: one sheet per channel and state, for Prism.</li>
</ul>
<h4>Excluded animals</h4>
<p>They are kept and marked (<code>excluded</code> and <code>exclusion_reason</code>), and listed
in <code>excluded_animals.csv</code>. Leave them out when you analyze.</p>
<h4>Changing something afterwards</h4>
<p>If masks or settings change the PSDs, run a new PSD run under a new name and finalize that.</p>
""",
    ),
    "export_masks": (
        "Export Masks",
        """
<h4>What it does</h4>
<p>Exports artifact masks and sleep states as time-stamped CSV files, without computing PSDs.
Files go in <code>exports/&lt;name&gt;/</code>.</p>
<h4>Steps</h4>
<p>Work down the page:</p>
<ol>
<li><b>What to export</b>: pick the animals, the states, the channels and the sampling frequency.</li>
<li><b>Masks</b>: set the artifact and event masks. Optionally start from a PSD run's settings
(<b>Load from PSD run</b>) or an earlier export, or <b>Restore defaults</b>.</li>
<li><b>Name &amp; run</b>: type an export name (it becomes the folder name) and click
<b>Export</b>. The button stays disabled until an animal is selected and the name is valid.</li>
</ol>
<h4>Output, per animal</h4>
<ul>
<li><code>_states.csv</code>: sleep states as intervals.</li>
<li><code>_artifacts.csv</code>: masked windows and the source of each.</li>
<li><code>_clean_per_state.csv</code>: clean windows left per state.</li>
<li><code>_meta.json</code>: the settings used.</li>
</ul>
<p>Times are seconds from the start of the recording.</p>
<h4>Excluded animals</h4>
<p>They are not marked in the export. Deselect them in the Animals list, or leave them out when
you use the files.</p>
""",
    ),
    "eeg_viewer": (
        "EEG viewer",
        """
<h4>Moving around</h4>
<table cellpadding="3">
<tr><td><b>Left / Right</b></td><td>scroll half a window</td></tr>
<tr><td><b>W / N / R</b></td><td>jump to the next Wake / NREM / REM span</td></tr>
<tr><td><b>Shift+W / N / R</b></td><td>jump to the previous one</td></tr>
<tr><td><b>1 to 9</b></td><td>jump to the next span of the 1st to 9th mask</td></tr>
<tr><td><b>Shift+1 to 9</b></td><td>jump to the previous span</td></tr>
<tr><td><b>]</b> and <b>[</b></td><td>next / previous annotation</td></tr>
<tr><td><b>Ctrl+S</b></td><td>plot the STFT (spectrogram) of the current view (Plots menu)</td></tr>
<tr><td><b>Ctrl+O</b></td><td>open an EDF</td></tr>
<tr><td><b>Ctrl+Q</b></td><td>close the viewer</td></tr>
<tr><td><b>F1</b></td><td>open this help (or click the <b>?</b> at the bottom right)</td></tr>
</table>
<h4>The sleep-state bar</h4>
<p>The colored bar above the traces shows the sleep state of every 4 s epoch in the time currently
on screen, lined up with the traces below it. The legend on its left gives the colors: Wake,
NREM and REM. It needs the animal's SPINDLE CSV. When the CSV has been reclassified the bar shows
the reclassified states (<code>final_state</code>) and the <b>R</b> badge is lit; click it to see
SPINDLE's original states instead.</p>
<h4>Plots &gt; Plot Sleep Data</h4>
<p>Opens a window that summarizes this animal's whole recording in a 3 by 3 grid. The columns are
Wake, NREM and REM; the rows are the fraction of time spent in the state, the number of bouts,
and the mean bout duration in seconds. Each point is a 2 hour bin and the x-axis is hours from
the start of the recording. The calculation is done on one state per second (each 4 s epoch
counts as four 1 s samples), the same way as the by-hour sleep analysis notebooks. It uses the
reclassified states when the CSV has them and the original states otherwise. It needs a state
CSV.</p>
<h4>Mouse</h4>
<ul>
<li><b>Double-click a trace</b> to see that epoch's row from the SPINDLE CSV (state, noise
probability and the other columns), when a CSV is loaded.</li>
<li><b>Right-click a mask</b> in the Masks panel to edit its parameters and rebuild it. The
arrows next to a mask jump to its previous / next span.</li>
<li>The <b>R</b> badge above the state bar toggles between the reclassified states (lit) and the
original SPINDLE states. It only changes the display.</li>
</ul>
<h4>Other controls</h4>
<ul>
<li>The time readouts show the position as seconds from the start and as clock time.</li>
<li>The seconds-per-view box sets how much time is shown. Each channel has its own zoom slider;
the reset button returns them to 1x.</li>
<li>Menus: <b>File</b> (open an EDF, session information, quit), <b>Masks</b> (load an SWD
mask, a drink mask or annotations), <b>Plots</b> (sleep data, STFT and its bounds), <b>Go</b>
(previous / next annotation) and <b>Help</b>. The toolbar at the top repeats the most-used ones:
Open, the two mask loaders, Plot Sleep Data and Plot STFT.</li>
<li>The toolbar on the right marks the animal <b>OK</b>, <b>Needs Review</b> or <b>Exclude</b> (a
reason is required to exclude).</li>
</ul>
""",
    ),
}


PAGE_HELP = {
    key: (title, html.replace("@@EMPTY_MAT@@", _EMPTY_MAT_HTML))
    for key, (title, html) in PAGE_HELP.items()
}


class HelpDialog(QDialog):
    def __init__(self, title: str, html: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Help: {title}")
        self.resize(520, 480)
        lay = QVBoxLayout(self)
        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setHtml(html)
        lay.addWidget(body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class HelpButton(QToolButton):
    """Small "?" that opens the help for ``page_key``."""

    def __init__(self, page_key: str, parent: QWidget | None = None):
        super().__init__(parent)
        if page_key not in PAGE_HELP:
            raise KeyError(f"No help text for page {page_key!r}")
        self.page_key = page_key
        self.setText("?")
        self.setToolTip("Instructions for this page")
        self.setFixedSize(22, 22)
        self.clicked.connect(self.show_help)

    def show_help(self) -> None:
        title, html = PAGE_HELP[self.page_key]
        HelpDialog(title, html, self.window()).exec()


def title_row(text: str, page_key: str, *, size: int = 14) -> QWidget:
    """Bold page title with a Help button at the right."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    label = QLabel(text)
    label.setStyleSheet(f"font-weight: bold; font-size: {size}px;")
    lay.addWidget(label)
    lay.addStretch(1)
    lay.addWidget(HelpButton(page_key))
    return row
