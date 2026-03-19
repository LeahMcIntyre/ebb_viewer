from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QPushButton, QStackedLayout, QVBoxLayout, QWidget, QLabel,
    QListWidget, QListWidgetItem, QFileDialog, QHBoxLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from ebb_viewer.pages.home import HomePage
from ebb_viewer.pages.preprocess import PreprocessPage
from ebb_viewer.pages.spindle import SpindleWritePage
from ebb_viewer.pages.spindle_upload import SpindleUploadPage
from ebb_viewer.pages.rerun import RerunPage
from ebb_viewer.pages.psds import PSDPage
from ebb_viewer.pages.psd_visualizer import PSDVisualizer
from ebb_viewer.pages.sleep_visualizer import SleepMetricsPage
from ebb_viewer.pages.sleep_qc_visualizer import SleepQCGridPage
from ebb_viewer.pipeline.manifest import Manifest

class MainWindow(QMainWindow):
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
        sidebar_layout.addWidget(self.pagelist)
        sidebar_layout.addStretch(1)

        # ----- Pages (stack order must match _ROW_TO_STACK mapping below)
        self.home_page = HomePage(parent=self, project_root=self.project_root)
        self.preprocess_page = PreprocessPage(parent=self, project_root=self.project_root)
        self.spindle_write_page = SpindleWritePage(parent=self, project_root=self.project_root)
        self.spindle_upload_page = SpindleUploadPage(parent=self, project_root=self.project_root)
        self.sleep_combine_page = SleepQCGridPage(parent=self, project_root=self.project_root)
        self.rerun_page = RerunPage(parent=self, project_root=self.project_root)
        self.psd_page = PSDPage(parent=self, project_root=self.project_root)
        self.psd_visualizer_page = PSDVisualizer(parent=self, project_root=self.project_root)

        for w in (self.home_page, self.preprocess_page, self.spindle_write_page,
                  self.spindle_upload_page, self.sleep_combine_page, self.rerun_page,
                  self.psd_page, self.psd_visualizer_page):
            self.stacklayout.addWidget(w)

        # Build sidebar with separators.
        # _ROW_TO_STACK maps list-row index → stack index (None = separator row).
        _NAV = [
            ("Home",               0),
            None,
            ("1. Preprocess",      1),
            ("2. Spindle EDFs",    2),
            ("3. Spindle Upload",  3),
            None,
            ("4. Sleep QC",        4),
            ("5. Spindle Rerun",   5),
            None,
            ("6. PSD Computation", 6),
            ("7. PSD Visualizer",  7),
        ]
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

        # Rows that carry pending-work badges (row index → manifest method name)
        # Home=0: needs_review queue; Sleep QC=6: pending rerun decisions; Rerun=7: needs_rerun
        self._badge_rows: dict[int, str] = {0: "needs_review", 6: "pending_rerun_review", 7: "needs_rerun"}

        # ----- Navigation
        self.pagelist.currentRowChanged.connect(self.display)
        self.pagelist.setCurrentRow(0)  # show home page initially
        self._refresh_badges()

        # Central widget
        wrapper = QWidget()
        wrapper.setLayout(pagelayout)
        self.setCentralWidget(wrapper)


    def display(self, i: int):
        stack_idx = self._row_to_stack.get(i)
        if stack_idx is not None:
            self.stacklayout.setCurrentIndex(stack_idx)
            self._refresh_badges()

    def _refresh_badges(self) -> None:
        """Update sidebar item labels with pending-work counts."""
        try:
            manifest = Manifest.load(self.project_root)
        except Exception:
            return
        counts = {
            "needs_review":        len(manifest.needs_review()),
            "pending_rerun_review": len(manifest.pending_rerun_review()),
            "needs_rerun":         len(manifest.needs_rerun()),
        }
        for row, method in self._badge_rows.items():
            item = self.pagelist.item(row)
            if item is None:
                continue
            base = self._row_base_label[row]
            n = counts[method]
            item.setText(f"{base}  ({n})" if n > 0 else base)
