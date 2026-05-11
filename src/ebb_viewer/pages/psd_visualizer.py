"""PSD Visualizer page — pick a PSD run/pkl and review per-animal PSDs.

Two review passes are supported:
- Pass 1 ("psds_channel_merged.pkl"): flag each animal OK or needs-drink-mask.
- Pass 2 ("psds_channel_merged_drink.pkl"): verify drink masks worked.

Non-merged per-combo pkls can also be opened for ad-hoc viewing (no flagging).
"""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ebb_viewer.data_stores.psd_store import PSDStore
from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.widgets.psd_graph_widget import PSDGridPage

# Pkl stems treated as "final" merged views eligible for manifest flagging.
_FINAL_VIEW_STEMS = frozenset({"psds_channel_merged", "psds_channel_merged_drink"})
_CHANNEL_NAMES = ["LFC", "RSC", "LSC"]


class PSDVisualizer(QWidget):
    """Sidebar page #7 — pick a PSD pkl and review animals via PSDGridPage."""

    navigate_to = pyqtSignal(str)

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.psd_page: PSDGridPage | None = None
        self._build_ui()
        self._wire()
        self._refresh_run_selector()

    def _build_ui(self):
        self.root = QVBoxLayout(self)

        lbl = QLabel("PSD Visualizer")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        desc = QLabel(
            "Review merged PSDs for each animal. "
            "Mark 'needs drink mask' if sidebands are visible around 52 and 68 Hz (water bottle artifact). "
            "Mark 'ok' otherwise."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")

        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        desc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.root.addWidget(lbl)
        self.root.addWidget(desc)

        folder_gb = QGroupBox("File Selection")
        folder_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        top_form = QFormLayout(folder_gb)

        # Run selector
        run_row = QHBoxLayout()
        self.cmb_run = QComboBox()
        self.cmb_run.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cmb_run.setMinimumWidth(160)
        run_row.addWidget(self.cmb_run, 1)
        top_form.addRow("Run:", run_row)

        # PKL file selector
        row = QHBoxLayout()
        self.cmb_file = QComboBox()
        self.cmb_file.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cmb_file.setMinimumWidth(200)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_browse = QPushButton("Browse…")
        self.btn_plot = QPushButton("Plot PSDs")
        self.btn_plot.setEnabled(False)
        row.addWidget(self.cmb_file, 1)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_browse)
        row.addWidget(self.btn_plot)
        top_form.addRow("PSD File:", row)
        self.root.addWidget(folder_gb, alignment=Qt.AlignmentFlag.AlignTop)

        self._reviewing_lbl = QLabel()
        self._reviewing_lbl.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px 0;")
        self._reviewing_lbl.setVisible(False)
        self.root.addWidget(self._reviewing_lbl)

        # Shown when all animals in a run are reviewed
        self._done_hint = QFrame()
        self._done_hint.setFrameShape(QFrame.Shape.StyledPanel)
        self._done_hint.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QHBoxLayout(self._done_hint)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        self._done_hint_lbl = QLabel("✓ All animals in this run reviewed.")
        self._done_hint_lbl.setWordWrap(True)
        hint_layout.addWidget(self._done_hint_lbl, 1)
        self._btn_go_finalize = QPushButton("→ Finalize")
        self._btn_go_finalize.clicked.connect(lambda: self.navigate_to.emit("finalize"))
        hint_layout.addWidget(self._btn_go_finalize)
        self._done_hint.setVisible(False)
        self.root.addWidget(self._done_hint)

        self._is_final_view = False

    def _wire(self):
        self.cmb_run.currentIndexChanged.connect(self._on_run_changed)
        self.btn_refresh.clicked.connect(self._refresh_run_selector)
        self.btn_browse.clicked.connect(self._on_browse)
        self.btn_plot.clicked.connect(self._on_plot_psds)
        self.cmb_file.currentIndexChanged.connect(self._on_combo_changed)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_run_selector()

    # ----------------------------------------------------------------

    def _current_run_name(self) -> str:
        return self.cmb_run.currentText() or "default"

    def _refresh_run_selector(self):
        """Repopulate run selector from list_runs(), preserving current selection."""
        current = self.cmb_run.currentText()
        runs = psd_params.list_runs(self.project_root)
        self.cmb_run.blockSignals(True)
        self.cmb_run.clear()
        for r in runs:
            self.cmb_run.addItem(r)
        self.cmb_run.blockSignals(False)
        if current in runs:
            self.cmb_run.setCurrentText(current)
        elif runs:
            self.cmb_run.setCurrentIndex(0)
        self._refresh_pkl_list()

    def _on_run_changed(self):
        self._refresh_pkl_list()

    def _refresh_pkl_list(self):
        """Scan psd/<run_name>/ for psds_*.pkl and repopulate the file combo."""
        run_name = self._current_run_name()
        psd_dir = self.project_root / "psd" / run_name
        pkls = sorted(psd_dir.glob("psds_*.pkl")) if psd_dir.is_dir() else []

        current = self.cmb_file.currentData()
        self.cmb_file.blockSignals(True)
        self.cmb_file.clear()
        for p in pkls:
            self.cmb_file.addItem(p.name, str(p))
        self.cmb_file.blockSignals(False)

        # Auto-select priority: psds_channel_merged_drink.pkl > psds_channel_merged.pkl
        merged_drink_idx = self.cmb_file.findText("psds_channel_merged_drink.pkl")
        merged_idx = self.cmb_file.findText("psds_channel_merged.pkl")
        if merged_drink_idx >= 0:
            self.cmb_file.setCurrentIndex(merged_drink_idx)
        elif merged_idx >= 0:
            self.cmb_file.setCurrentIndex(merged_idx)
        elif current:
            idx = self.cmb_file.findData(current)
            self.cmb_file.setCurrentIndex(idx if idx >= 0 else 0)
        elif self.cmb_file.count():
            self.cmb_file.setCurrentIndex(0)

        self._on_combo_changed()

    def _check_done_hint(self):
        if not self._is_final_view:
            self._done_hint.setVisible(False)
            return
        try:
            run_name = self._current_run_name()
            manifest = Manifest.load(self.project_root)
            pending = (
                len(manifest.pending_psd_review(run_name))
                + len(manifest.needs_drink_mask(run_name))
                + len(manifest.pending_drink_verification(run_name))
            )
            complete = pending == 0 and self.cmb_file.count() > 0
            self._done_hint.setVisible(complete)
            if complete:
                self._done_hint_lbl.setText(f"✓ All animals in run '{run_name}' reviewed.")
        except Exception:
            self._done_hint.setVisible(False)

    def _on_combo_changed(self):
        path_str = self.cmb_file.currentData()
        self.btn_plot.setEnabled(bool(path_str and Path(path_str).is_file()))

    def _on_browse(self):
        psd_dir = self.project_root / "psd"
        fp = QFileDialog.getOpenFileName(
            self,
            "Select PSD .pkl File",
            str(psd_dir if psd_dir.is_dir() else self.project_root),
            "Pickle Files (*.pkl);;All Files (*)",
        )[0]
        if not fp:
            return
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

        stem = Path(psd_file).stem
        is_final_view = stem in _FINAL_VIEW_STEMS
        is_drink_review = stem == "psds_channel_merged_drink"
        if is_final_view:
            run_channels = None
        elif stem.startswith("psds_"):
            run_channels = stem[len("psds_") :]
        else:
            run_channels = stem
        run_name = self._current_run_name()

        fname = Path(psd_file).name
        if stem == "psds_channel_merged":
            lbl_text = f"Reviewing: {fname} (Pass 1 — flag original PSDs)  [run: {run_name}]"
        elif is_drink_review:
            lbl_text = f"Reviewing: {fname} (Pass 2 — verify drink masks)  [run: {run_name}]"
        else:
            lbl_text = f"Viewing: {fname}  [run: {run_name}]"
        self._reviewing_lbl.setText(lbl_text)
        self._reviewing_lbl.setVisible(True)

        self.psd_store = PSDStore(psd_file, channel_names=_CHANNEL_NAMES)
        self.psd_page = PSDGridPage(
            self,
            store=self.psd_store,
            channel_names=_CHANNEL_NAMES,
            states=None,  # derived from pkl contents (see PSDGridPage)
            manifest=Manifest.load(self.project_root) if is_final_view else None,
            run_channels=run_channels,
            drink_review=is_drink_review,
            run_name=run_name,
            project_root=self.project_root,
        )
        self._is_final_view = is_final_view
        self._done_hint.setVisible(False)
        self.psd_page.navigate_to.connect(self.navigate_to)
        if is_final_view:
            self.psd_page.manifest_changed.connect(self._check_done_hint)
            self._check_done_hint()
        self.root.addWidget(self.psd_page)
