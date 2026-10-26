"""Readiness checklist shared by pages with a Run/Apply button (PSD compute, Drink Mask).

A page builds a list of :class:`Check`, shows ``checks_html(checks)`` in a label, enables its
button only when ``blockers(checks)`` is empty, and offers a button to the page named by
``first_fix(checks)``.
"""

from __future__ import annotations

from dataclasses import dataclass

# Page names (main_window navigation keys) that fix a failing check, with button labels.
FIX_PAGE_LABEL = {
    "preprocess": "Preprocess",
    "sleep_qc": "Sleep QC",
    "spindle_upload": "Spindle Upload",
    "swd_review": "SWD Review",
    "psd_compute": "PSD Computation",
    "psd_review": "PSD Visualizer",
}


@dataclass(frozen=True)
class Check:
    """One line of a readiness checklist."""

    ok: bool
    text: str  # what is true when ok, what to fix when not
    blocking: bool = True  # a failing blocking check disables the action
    page: str | None = None  # page that fixes it, when there is one


def blockers(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.ok and c.blocking]


def first_fix(checks: list[Check]) -> Check | None:
    """The first failing check that names a page to fix it on."""
    return next((c for c in checks if not c.ok and c.page), None)


def fix_button_text(check: Check) -> str:
    return f"Open {FIX_PAGE_LABEL.get(check.page, check.page)} →"


def checks_html(checks: list[Check]) -> str:
    """Rich text, one line per check: ✓ green, ✗ red (blocking), ⚠ amber (warning)."""
    rows = []
    for c in checks:
        if c.ok:
            rows.append(f"<span style='color:#2a7a2a'>✓</span> {c.text}")
        else:
            color, mark = ("#c0392b", "✗") if c.blocking else ("#b06000", "⚠")
            rows.append(f"<span style='color:{color}'>{mark}</span> {c.text}")
    return "<br>".join(rows)
