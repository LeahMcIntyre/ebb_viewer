import shutil
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QMessageBox,
)

from ebb_viewer.pipeline.manifest import Manifest, merged_psd_path, final_psd_path


class FinalizePage(QWidget):

    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()

    def _poll(self):
        self._refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        hdr = QHBoxLayout()
        lbl = QLabel("Finalize")
        lbl.setStyleSheet("font-weight: bold; font-size: 15px;")
        hdr.addWidget(lbl)
        hdr.addStretch(1)
        root.addLayout(hdr)

        desc = QLabel(
            "Seal the reviewed PSDs into psds_final.pkl. "
            "All animals must be reviewed (OK or drink mask applied) before finalizing."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(desc)

        # Status panel
        status_frame = QFrame()
        status_frame.setFrameShape(QFrame.Shape.StyledPanel)
        status_frame.setStyleSheet("QFrame { background: #f8f9fa; border-radius: 4px; }")
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(4)

        self._lbl_pending = QLabel()
        self._lbl_pending.setWordWrap(True)
        self._lbl_source = QLabel()
        self._lbl_source.setWordWrap(True)
        self._lbl_last_finalized = QLabel()
        self._lbl_last_finalized.setWordWrap(True)
        for lbl in (self._lbl_pending, self._lbl_source, self._lbl_last_finalized):
            status_layout.addWidget(lbl)

        root.addWidget(status_frame)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._btn_finalize = QPushButton("Finalize ▶")
        self._btn_finalize.setStyleSheet("font-weight: bold;")
        self._btn_finalize.setEnabled(False)
        self._btn_finalize.clicked.connect(self._on_finalize)
        btn_row.addWidget(self._btn_finalize)
        root.addLayout(btn_row)

        root.addStretch(1)

    def _refresh(self):
        try:
            manifest = Manifest.load(self.project_root)
        except Exception:
            self._lbl_pending.setText("Could not load manifest.")
            self._lbl_pending.setStyleSheet("color: gray;")
            self._btn_finalize.setEnabled(False)
            return

        pending = (
            len(manifest.pending_psd_review())
            + len(manifest.needs_drink_mask())
            + len(manifest.pending_drink_verification())
        )

        if pending == 0:
            self._lbl_pending.setText("✓ All animals reviewed — ready to finalize.")
            self._lbl_pending.setStyleSheet("color: #1a5c1a; font-weight: bold;")
        else:
            self._lbl_pending.setText(f"⚠ {pending} animal/combo(s) still pending review.")
            self._lbl_pending.setStyleSheet("color: #8a4400;")

        psd_dir = self.project_root / "psd"
        src = psd_dir / "psds_channel_merged_drink.pkl"
        if not src.exists():
            src = psd_dir / "psds_channel_merged.pkl"
        if src.exists():
            self._lbl_source.setText(f"Source: {src.name}")
            self._lbl_source.setStyleSheet("color: #333;")
        else:
            self._lbl_source.setText("Source: no merged PKL found yet")
            self._lbl_source.setStyleSheet("color: gray;")

        dest = final_psd_path(self.project_root)
        if dest.exists():
            ts = datetime.fromtimestamp(dest.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            self._lbl_last_finalized.setText(f"Last finalized: {ts}")
            self._lbl_last_finalized.setStyleSheet("color: #333;")
        else:
            self._lbl_last_finalized.setText("Last finalized: not yet finalized")
            self._lbl_last_finalized.setStyleSheet("color: gray;")

        self._btn_finalize.setEnabled(pending == 0 and src.exists())

    def _on_finalize(self):
        psd_dir = self.project_root / "psd"
        src = psd_dir / "psds_channel_merged_drink.pkl"
        if not src.exists():
            src = psd_dir / "psds_channel_merged.pkl"
        if not src.exists():
            QMessageBox.warning(self, "Finalize", "No merged PKL found to finalize.")
            return
        dest = final_psd_path(self.project_root)
        shutil.copy2(src, dest)
        self._refresh()
        self.manifest_changed.emit()
        QMessageBox.information(self, "Finalize", f"psds_final.pkl written from {src.name}.")
