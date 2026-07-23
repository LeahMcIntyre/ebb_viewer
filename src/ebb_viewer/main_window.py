"""Top-level Qt main window for the ebb_viewer GUI.

Hosts the sidebar navigation (11 pipeline pages + separators), the
``QStackedLayout`` showing the active page, and the periodic poll timer
that refreshes sidebar badges and the currently-visible page every 10 s.

Each page is constructed once at startup with ``project_root`` and added
to the stack. Pages emit ``navigate_to(<page-name>)`` for post-action
routing; the window translates that into a sidebar row change via
``_PAGE_ROWS``.
"""

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ebb_viewer.pages.drink_mask import DrinkMaskPage
from ebb_viewer.pages.export_masks import ExportMasksPage
from ebb_viewer.pages.finalize import FinalizePage
from ebb_viewer.pages.home import HomePage
from ebb_viewer.pages.preprocess import PreprocessPage
from ebb_viewer.pages.psd_visualizer import PSDVisualizer
from ebb_viewer.pages.psds import PSDPage
from ebb_viewer.pages.rerun import RerunPage
from ebb_viewer.pages.sleep_qc_visualizer import SleepQCGridPage
from ebb_viewer.pages.spindle import SpindleWritePage
from ebb_viewer.pages.spindle_upload import SpindleUploadPage
from ebb_viewer.pipeline.manifest import Manifest

# ---------------------------------------------------------------------------
# Sidebar layout — list-row index → (label, stack index) or None for separator.
# Row indices feed _BADGE_ROWS (pending-work counts) and _PAGE_ROWS (navigate_to
# destinations), so reordering here must update both maps below.
# ---------------------------------------------------------------------------
_NAV: list[tuple[str, int] | None] = [
    ("Home", 0),
    None,
    ("1. Preprocess", 1),
    ("2. Spindle EDFs", 2),
    ("3. Spindle Upload", 3),
    None,
    ("4. Sleep QC", 4),
    ("5. Spindle Rerun", 5),
    None,
    ("6. PSD Computation", 6),
    ("7. PSD Visualizer", 7),
    ("8. Drink Mask", 8),
    ("9. Finalize", 9),
    None,
    ("10. Export Masks", 10),
]

# Sidebar rows that carry pending-work badges → manifest method name.
# Row 0: Home — animals flagged for EDF review.
# Row 6: Sleep QC — animals with a downloaded rerun awaiting decision.
# Row 7: Spindle Rerun — animals with rerun queued but EDF not yet written.
# Row 10: PSD Visualizer — PSDs flagged for review (incl. drink verification).
# Row 11: Drink Mask — animals flagged needs_drink_mask.
_BADGE_ROWS: dict[int, str] = {
    0: "needs_review",
    6: "pending_rerun_review",
    7: "needs_rerun_pending",
    10: "pending_psd_review",
    11: "needs_drink_mask",
}

# Page-name keys emitted via navigate_to → sidebar row index.
_PAGE_ROWS: dict[str, int] = {
    "home": 0,
    "preprocess": 2,
    "spindle_write": 3,
    "spindle_upload": 4,
    "sleep_qc": 6,
    "rerun": 7,
    "psd_compute": 9,
    "psd_review": 10,
    "drink_mask": 11,
    "finalize": 12,
}


class MainWindow(QMainWindow):
    """Main application window — sidebar + stacked page area + poll timer."""

    def __init__(self, project_root: Path, parent=None):
        super().__init__(parent)
        self.project_root = project_root

        self.setWindowTitle("EEG Project Runner")
        self.resize(1000, 600)

        # ----- Layouts
        pagelayout = QHBoxLayout()
        pagelayout.setContentsMargins(6, 6, 6, 6)
        pagelayout.setSpacing(8)

        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(0, 0, 6, 0)
        sidebar_layout.setSpacing(6)
        sidebar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.stacklayout = QStackedLayout()
        self.stacklayout.setContentsMargins(0, 0, 0, 0)

        pagelayout.addLayout(sidebar_layout)
        pagelayout.addLayout(self.stacklayout, 1)

        # ----- Sidebar
        self.lbl_project = QLabel(f"Project: {self.project_root}")
        self.lbl_project.setObjectName("projectPathLabel")
        self.lbl_project.setWordWrap(True)
        self.lbl_project.setStyleSheet("#projectPathLabel { color: gray; font-size: 11px; }")
        sidebar_layout.addWidget(self.lbl_project)

        self.pagelist = QListWidget()
        self.pagelist.setFixedWidth(160)
        self.pagelist.setMinimumHeight(350)
        sidebar_layout.addWidget(self.pagelist)
        sidebar_layout.addStretch(1)

        # ----- Pages (stack order must match _NAV's stack indices)
        self.home_page = HomePage(parent=self, project_root=self.project_root)
        self.preprocess_page = PreprocessPage(parent=self, project_root=self.project_root)
        self.spindle_write_page = SpindleWritePage(parent=self, project_root=self.project_root)
        self.spindle_upload_page = SpindleUploadPage(parent=self, project_root=self.project_root)
        self.sleep_qc_page = SleepQCGridPage(parent=self, project_root=self.project_root)
        self.rerun_page = RerunPage(parent=self, project_root=self.project_root)
        self.psd_page = PSDPage(parent=self, project_root=self.project_root)
        self.psd_visualizer_page = PSDVisualizer(parent=self, project_root=self.project_root)
        self.drink_mask_page = DrinkMaskPage(parent=self, project_root=self.project_root)
        self.finalize_page = FinalizePage(parent=self, project_root=self.project_root)
        self.export_masks_page = ExportMasksPage(project_root=self.project_root, parent=self)

        # Pages in stack order. Index matches _NAV's stack-index column.
        pages_in_stack_order = (
            self.home_page,
            self.preprocess_page,
            self.spindle_write_page,
            self.spindle_upload_page,
            self.sleep_qc_page,
            self.rerun_page,
            self.psd_page,
            self.psd_visualizer_page,
            self.drink_mask_page,
            self.finalize_page,
            self.export_masks_page,
        )
        for w in pages_in_stack_order:
            self.stacklayout.addWidget(w)

        # Build the sidebar list (rows + separators) from _NAV.
        self._row_to_stack: dict[int, int] = {}
        self._row_base_label: dict[int, str] = {}
        for row, entry in enumerate(_NAV):
            if entry is None:
                sep = QListWidgetItem("─────────────")
                sep.setFlags(Qt.ItemFlag.NoItemFlags)
                sep.setForeground(QColor("#bbbbbb"))
                self.pagelist.addItem(sep)
            else:
                label, stack_idx = entry
                self.pagelist.addItem(label)
                self._row_to_stack[row] = stack_idx
                self._row_base_label[row] = label

        # Pages that emit manifest_changed → refresh sidebar badges.
        for page in (
            self.home_page,
            self.sleep_qc_page,
            self.rerun_page,
            self.psd_page,
            self.drink_mask_page,
        ):
            page.manifest_changed.connect(self._refresh_badges)

        # Pages that emit navigate_to(name) → move sidebar selection.
        for page in (
            self.home_page,
            self.preprocess_page,
            self.spindle_write_page,
            self.spindle_upload_page,
            self.sleep_qc_page,
            self.rerun_page,
            self.psd_page,
            self.psd_visualizer_page,
            self.drink_mask_page,
            self.finalize_page,
        ):
            page.navigate_to.connect(self._navigate_to)

        # Periodic poll: refresh badges + currently-visible page every 30 s.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(30_000)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

        # ----- Navigation
        self.pagelist.currentRowChanged.connect(self.display)
        self.pagelist.setCurrentRow(0)  # show home page initially
        self._refresh_badges()

        # Central widget
        wrapper = QWidget()
        wrapper.setLayout(pagelayout)
        self.setCentralWidget(wrapper)

    def display(self, i: int) -> None:
        stack_idx = self._row_to_stack.get(i)
        if stack_idx is not None:
            self.stacklayout.setCurrentIndex(stack_idx)
            self._refresh_badges()

    def _navigate_to(self, name: str) -> None:
        """Move sidebar selection to the row mapped from ``name``."""
        row = _PAGE_ROWS.get(name)
        if row is not None:
            self.pagelist.setCurrentRow(row)

    def _poll(self) -> None:
        """Called every 10 s: refresh badges and the currently-visible page."""
        self._refresh_badges()
        page = self.stacklayout.currentWidget()
        if page is not None and hasattr(page, "_poll"):
            page._poll()

    def _refresh_badges(self) -> None:
        """Update sidebar item labels with pending-work counts."""
        try:
            manifest = Manifest.load(self.project_root)
        except (OSError, ValueError):
            return

        counts = {
            "needs_review": len(manifest.needs_review()),
            "pending_rerun_review": len(manifest.pending_rerun_review()),
            "needs_rerun_pending": len(manifest.needs_rerun_pending()),
            "pending_psd_review": len(manifest.all_pending_psd_review())
            + len(manifest.all_pending_drink_verification()),
            "needs_drink_mask": len(manifest.all_needs_drink_mask()),
        }
        for row, method in _BADGE_ROWS.items():
            item = self.pagelist.item(row)
            if item is None:
                continue
            base = self._row_base_label[row]
            n = counts[method]
            item.setText(f"{base}  ({n})" if n > 0 else base)
