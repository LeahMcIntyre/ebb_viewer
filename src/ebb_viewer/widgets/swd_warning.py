"""Confirm dialog shown before producing results while the SWD review has gaps."""

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox, QWidget

from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.pipeline.swd_review import swd_review_gaps


def confirm_unfinished_swd_review(
    parent: QWidget, project_root: Path, animal_ids: set[str] | None = None
) -> bool:
    """True to continue. Asks only when SWD review is on and there are gaps.

    Gaps are animals with no SWD file (and no confirmation that none is needed) and animals whose
    review is unfinished. Unreviewed SWD epochs keep their ``reclass_state``, so continuing is
    allowed; the dialog just stops a half-reviewed project from being analyzed by accident.
    Cancel is the default.
    """
    gaps = swd_review_gaps(project_root, Manifest.load(project_root), animal_ids)
    if not gaps:
        return True
    sections = []
    if gaps.missing:
        sections.append(
            "No SWD file (add one, even an empty one, or confirm none is needed on the SWD "
            "Review page):\n" + "\n".join(f"  • {a}" for a in gaps.missing)
        )
    if gaps.unfinished:
        sections.append(
            "SWD review not finished:\n" + "\n".join(f"  • {a}" for a in gaps.unfinished)
        )
    reply = QMessageBox.question(
        parent,
        "SWD review incomplete",
        "SWD review is on for this project, but:\n\n"
        + "\n\n".join(sections)
        + "\n\nUnreviewed SWD epochs keep the reclassified state. Continue anyway?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    return reply == QMessageBox.StandardButton.Yes
