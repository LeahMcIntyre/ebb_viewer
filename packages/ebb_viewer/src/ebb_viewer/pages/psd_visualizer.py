from pathlib import Path
from typing import Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QFileDialog
)
from ebb_viewer.data_stores.psd_store import PSDStore
from ebb_viewer.widgets.psd_graph_widget import PSDGridPage


class PSDVisualizer(QWidget):
    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.psd_page: Optional[PSDGridPage] = None
        self._build_ui()
        self._wire()

    def _build_ui(self):
        self.root = QVBoxLayout(self)
        folder_gb = QGroupBox("File Selection")
        folder_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        top_form = QFormLayout(folder_gb)

        # Standard Folder Selection
        row = QHBoxLayout()
        #row.addStretch(1)
        self.btn_select = QPushButton("Select PSD File")
        self.btn_plot = QPushButton("Plot PSDs")
        self.btn_plot.setEnabled(False)
        self.lbl_file= QLineEdit("No psd .pkl file selected")
        self.lbl_file.setReadOnly(True)

        #self.lbl_standard.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.lbl_file); row.addWidget(self.btn_select); row.addWidget(self.btn_plot)
        top_form.addRow("PSD File:", row)
        self.root.addWidget(folder_gb, alignment=Qt.AlignmentFlag.AlignTop)
    
    def _wire(self):
        self.btn_select.clicked.connect(self._on_select_file)
        self.btn_plot.clicked.connect(self._on_plot_psds)

    def _on_select_file(self):
        parent_dir = self.project_root / "psd" or  self.project_root or ""
        fp = QFileDialog.getOpenFileName(
            self,
            "Select PSD .pkl File",
            str(parent_dir),
            "Pickle Files (*.pkl);;All Files (*)"
        )[0]

        if fp is not None:
            self.lbl_file.setText(str(fp))
            self.btn_plot.setEnabled(True)

    def _on_plot_psds(self):
        if self.psd_page:
            self.psd_page.setParent(None)
            self.psd_page.deleteLater()
            self.psd_page = None

        psd_file = self.lbl_file.text()
        if not psd_file or not Path(psd_file).is_file():
            return

        channel_names = ["LFC", "RSC", "LSC"]
        self.psd_store = PSDStore(
            psd_file,
            channel_names=channel_names
            )
        self.psd_page = PSDGridPage(self, store=self.psd_store,
                                    channel_names=channel_names,
                                    states=['wake', 'nrem', 'rem'])
        self.root.addWidget(self.psd_page)



