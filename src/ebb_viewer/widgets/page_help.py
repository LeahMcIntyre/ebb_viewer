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
<p>Reclassify must have been run first. Re-running Reclassify keeps your edits.</p>
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
<h4>Needs</h4>
<ul>
<li>One EDF per animal directly in the project folder (combine restarted recordings first).</li>
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
(default 48, 72). A recording shorter than the smallest target fails.</td></tr>
</table>
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
<h4>Steps</h4>
<ol>
<li>Pick <b>your own name</b> as the SleepyRat project. Use <b>New</b> only if your name is not in
the list.</li>
<li>Check the remote folder name (filled in for you).</li>
<li>Click <b>Upload &amp; Download</b>. The first time, a browser tab asks you to approve access.</li>
</ol>
<h4>Good to know</h4>
<ul>
<li>Scoring can take over an hour for many files. Leave the app open.</li>
<li>Safe to run again: files already uploaded or downloaded are skipped.</li>
<li>Epochs are 4 s and scored Wake, NREM or REM.</li>
</ul>
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
<li>For the SWD mask: a <code>.mat</code> file per animal in <code>swd/</code> (an empty one is
fine).</li>
<li>For the annotation mask: the annotation files in one folder.</li>
</ul>
<h4>Settings</h4>
<p>The defaults are the ones the lab uses; leave them unless you have a reason. <b>Restore
defaults</b> resets them. States default to Wake, NREM and REM, and channels to all three EEG
channels. Sampling frequency is 250 Hz (the refresh button reads it from the first EDF in
<code>standard/</code>).</p>
<ul>
<li><b>SWD mask</b>: choose <b>Mask out SWDs</b>; <b>Pad each event</b> adds seconds either side.</li>
<li><b>Annotation mask</b>: tick it, pick the directory and enter comma-separated keywords.
<b>Contains</b> matches any label containing a keyword; <b>Exact</b> needs the whole label.</li>
<li><b>Run name</b>: the folder under <code>psd/</code> for the results. Use a name that says what
the run is for; several runs can sit side by side.</li>
</ul>
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
the saved PSDs. Turn both on for the review.</p>
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
<li>A drink-event file per flagged animal: <code>drink_masks/&lt;AnimalID&gt;.npy</code>, one
true/false value per second of recording. These are made outside this pipeline. Animals without
one are skipped.</li>
<li>If the video and EEG did not start together: one CSV in <code>drink_masks/</code> with columns
<code>Animal</code> and <code>Offset</code> (seconds from the EEG start to the video start). Keep
only one CSV there.</li>
</ul>
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
<ol>
<li>Optionally load settings from a PSD run or an earlier export, or <b>Restore defaults</b>.</li>
<li>Set what to export: states, channels, sampling frequency and the masks.</li>
<li>Pick the animals, name the export, and click <b>Export</b>.</li>
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
</table>
<h4>Other controls</h4>
<ul>
<li>The seconds-per-view box sets how much time is shown. Each channel has its own zoom slider;
the reset button returns them to 1x.</li>
<li><b>File</b> menu: load an SWD mask, a drink mask or annotations. <b>Ctrl+S</b> plots the STFT.</li>
<li>The toolbar on the right marks the animal <b>OK</b>, <b>Needs Review</b> or <b>Exclude</b> (a
reason is required to exclude).</li>
</ul>
""",
    ),
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
