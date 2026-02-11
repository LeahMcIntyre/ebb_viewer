from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QPushButton, QStackedLayout, QVBoxLayout, QWidget, QLabel,
    QListWidget, QFileDialog, QHBoxLayout
)
from PyQt6.QtCore import Qt

from ebb_viewer.pages.home import HomePage
from ebb_viewer.pages.preprocess import PreprocessPage
from ebb_viewer.pages.spindle import SpindleWritePage
from ebb_viewer.pages.spindle_upload import SpindleUploadPage
from ebb_viewer.pages.psd import PSDPage
from ebb_viewer.pages.psd_visualizer import PSDVisualizer
from ebb_viewer.app.app_state import AppState

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
        self.pagelist.addItems(["Home", "Preprocess", "Spindle EDFs", "Spindle Upload", "PSD Computation", "PSD Visualizer"])
        self.pagelist.setFixedWidth(140)
        sidebar_layout.addWidget(self.pagelist)
        sidebar_layout.addStretch(1)

        # ----- Pages 
        self.home_page = HomePage(parent=self, project_root=self.project_root)
        self.preprocess_page = PreprocessPage(parent=self, project_root=self.project_root)
        self.spindle_write_page = SpindleWritePage(parent=self, project_root=self.project_root)
        self.spindle_upload_page = SpindleUploadPage(parent=self, project_root=self.project_root)
        self.psd_page = PSDPage(parent=self, project_root=self.project_root)
        self.psd_visualizer_page = PSDVisualizer(parent=self, project_root=self.project_root)

        for w in (self.home_page, self.preprocess_page, self.spindle_write_page,self.spindle_upload_page, self.psd_page, self.psd_visualizer_page):
            self.stacklayout.addWidget(w)


        # ----- Navigation
        self.pagelist.currentRowChanged.connect(self.display)
        self.pagelist.setCurrentRow(0) # show home page initially

        # Central widget
        wrapper = QWidget()
        wrapper.setLayout(pagelayout)
        self.setCentralWidget(wrapper)


    def display(self, i: int):
        self.stacklayout.setCurrentIndex(i)
