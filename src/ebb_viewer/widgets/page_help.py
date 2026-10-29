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
