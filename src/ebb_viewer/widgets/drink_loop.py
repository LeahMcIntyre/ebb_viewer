"""One-line summary of the review → drink mask → verify loop, shared by its two pages."""

from __future__ import annotations

from ebb_viewer.pipeline.manifest import DrinkLoopCounts

REVIEW_STEP = "review"
MASK_STEP = "mask"
VERIFY_STEP = "verify"


def loop_summary_html(counts: DrinkLoopCounts, active: str | None) -> str:
    """Rich text: ``1 Review PSDs → 2 Add masks → 3 Verify``, each with its count.

    ``active`` is the step the current page is about (``REVIEW_STEP`` / ``MASK_STEP`` /
    ``VERIFY_STEP``); it is shown bold and blue.
    """
    review = f"{counts.unreviewed} left" if counts.unreviewed else f"done ✓ ({counts.ok} ok)"
    if counts.flagged:
        mask = f"{counts.flagged} flagged, {counts.ready} with a mask file"
    else:
        mask = "none needed"
    verify = f"{counts.to_verify} to check" if counts.to_verify else "nothing waiting"
    steps = [
        (REVIEW_STEP, "1 Review PSDs", review),
        (MASK_STEP, "2 Add masks", mask),
        (VERIFY_STEP, "3 Verify", verify),
    ]
    parts = []
    for key, title, detail in steps:
        text = f"{title}: {detail}"
        parts.append(f"<b style='color:#1a5fa8'>{text}</b>" if key == active else text)
    return " &nbsp;→&nbsp; ".join(parts)
