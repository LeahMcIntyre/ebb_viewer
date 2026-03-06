from pathlib import Path
from typing import Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QHBoxLayout,
    QPushButton, QComboBox, QSizePolicy, QFileDialog
)
from ebb_viewer.data_stores.psd_store import PSDStore
from ebb_viewer.widgets.psd_graph_widget import PSDGridPage
from ebb_viewer.pipeline.manifest import Manifest


class PSDVisualizer(QWidget):
    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.psd_page: Optional[PSDGridPage] = None
        self._build_ui()
        self._wire()
        self._refresh_pkl_list()

    def _build_ui(self):
        self.root = QVBoxLayout(self)
        folder_gb = QGroupBox("File Selection")
        folder_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        top_form = QFormLayout(folder_gb)

        row = QHBoxLayout()
        self.cmb_file = QComboBox()
        self.cmb_file.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cmb_file.setMinimumWidth(200)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_browse  = QPushButton("Browse…")
        self.btn_plot    = QPushButton("Plot PSDs")
        self.btn_plot.setEnabled(False)

        row.addWidget(self.cmb_file, 1)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_browse)
        row.addWidget(self.btn_plot)
        top_form.addRow("PSD File:", row)
        self.root.addWidget(folder_gb, alignment=Qt.AlignmentFlag.AlignTop)

    def _wire(self):
        self.btn_refresh.clicked.connect(self._refresh_pkl_list)
        self.btn_browse.clicked.connect(self._on_browse)
        self.btn_plot.clicked.connect(self._on_plot_psds)
        self.cmb_file.currentIndexChanged.connect(self._on_combo_changed)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_pkl_list()

    # ----------------------------------------------------------------

    def _refresh_pkl_list(self):
        """Scan project_root/psd/ for psds_*.pkl and repopulate the combo."""
        psd_dir = self.project_root / "psd"
        pkls = sorted(psd_dir.glob("psds_*.pkl")) if psd_dir.is_dir() else []

        current = self.cmb_file.currentData()
        self.cmb_file.blockSignals(True)
        self.cmb_file.clear()
        for p in pkls:
            self.cmb_file.addItem(p.name, str(p))
        self.cmb_file.blockSignals(False)

        # Restore previous selection if still present
        if current:
            idx = self.cmb_file.findData(current)
            self.cmb_file.setCurrentIndex(idx if idx >= 0 else 0)
        elif self.cmb_file.count():
            self.cmb_file.setCurrentIndex(0)

        self._on_combo_changed()

    def _on_combo_changed(self):
        path_str = self.cmb_file.currentData()
        self.btn_plot.setEnabled(bool(path_str and Path(path_str).is_file()))

    def _on_browse(self):
        psd_dir = self.project_root / "psd"
        fp = QFileDialog.getOpenFileName(
            self,
            "Select PSD .pkl File",
            str(psd_dir if psd_dir.is_dir() else self.project_root),
            "Pickle Files (*.pkl);;All Files (*)"
        )[0]
        if not fp:
            return
        # Add to combo if not already present, then select it
        idx = self.cmb_file.findData(fp)
        if idx < 0:
            self.cmb_file.addItem(Path(fp).name, fp)
            idx = self.cmb_file.count() - 1
        self.cmb_file.setCurrentIndex(idx)

    def _on_plot_psds(self):
        if self.psd_page:
            self.psd_page.setParent(None)
            self.psd_page.deleteLater()
            self.psd_page = None

        psd_file = self.cmb_file.currentData()
        if not psd_file or not Path(psd_file).is_file():
            return

        channel_names = ["LFC", "RSC", "LSC"]
        stem = Path(psd_file).stem  # e.g. "psds_LFC_RSC"
        run_channels = stem[len("psds_"):] if stem.startswith("psds_") else stem

        self.psd_store = PSDStore(psd_file, channel_names=channel_names)
        self.psd_page = PSDGridPage(
            self,
            store=self.psd_store,
            channel_names=channel_names,
            states=['wake', 'nrem', 'rem'],
            manifest=Manifest.load(self.project_root),
            run_channels=run_channels,
        )
        self.root.addWidget(self.psd_page)



