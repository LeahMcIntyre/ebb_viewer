from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
)

from ebb_viewer.widgets.tree_view import ProjectTree
from ebb_viewer.pipeline.manifest import Manifest, psd_path


# Pipeline stage columns
_COLUMNS = [
    "Animal", "Preprocessed", "Channels",
    "Spindle EDF", "Spindle Output",
    "Sleep QC", "PSD File", "PSD Status",
]

_STATUS_COLOR = {
    "ok":                QColor("#d4edda"),   # green
    "needs_review":      QColor("#fff3cd"),   # yellow
    "rerun_channels":    QColor("#fde8ce"),   # orange
    "needs_drink_mask":  QColor("#fde8ce"),   # orange
}
_PENDING_COLOR = QColor("#f0f0f0")            # light gray = reached but not yet flagged
_EXISTS_COLOR  = QColor("#d4edda")            # green


def _cell(text: str, bg: QColor | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if bg is not None:
        item.setBackground(bg)
    return item


def _any_file_for_animal(root: Path, subdir: str, channels: str, animal_id: str) -> bool:
    """True if any file matching animal_id* exists in root/subdir/channels/."""
    d = root / subdir / channels
    return d.is_dir() and any(d.glob(f"{animal_id}*"))


class HomePage(QWidget):
    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._build_ui()
        self._refresh()

    # ---------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------
    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(6)

        # --- header row ---
        hdr = QHBoxLayout()
        lbl = QLabel("Pipeline Summary")
        lbl.setStyleSheet("font-weight: bold; font-size: 15px;")
        hdr.addWidget(lbl)
        hdr.addStretch(1)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setToolTip("Reload manifest from disk")
        self.btn_refresh.clicked.connect(self._refresh)
        hdr.addWidget(self.btn_refresh)

        self.btn_build = QPushButton("Sync from filesystem")
        self.btn_build.setToolTip(
            "Scan standard/, spindle_edfs/, and spindle_outputs/ to add new "
            "animals and infer channel combos for any entries not yet set"
        )
        self.btn_build.clicked.connect(self._build_manifest)
        hdr.addWidget(self.btn_build)

        root_layout.addLayout(hdr)

        # --- summary table ---
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Animal
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)           # Preprocessed EDF
        for col in range(2, len(_COLUMNS)):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        root_layout.addWidget(self.table)

        # --- file tree ---
        file_lbl = QLabel("Project Files")
        file_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        root_layout.addWidget(file_lbl)

        self.edf_tree = ProjectTree()
        self.edf_tree.set_root(root_path=self.project_root)
        root_layout.addWidget(self.edf_tree)

    # ---------------------------------------------------------------
    # Actions
    # ---------------------------------------------------------------
    def _build_manifest(self):
        Manifest.build_from_standard(self.project_root)
        self._refresh()

    def _refresh(self):
        manifest = Manifest.load(self.project_root)
        entries = list(manifest)

        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            ch = entry.spindle_channels

            # Filesystem checks
            spindle_edf_ok  = ch is not None and _any_file_for_animal(
                self.project_root, "spindle_edfs", ch, entry.animal_id)
            spindle_out_ok  = ch is not None and _any_file_for_animal(
                self.project_root, "spindle_outputs", ch, entry.animal_id)
            psd_file_ok     = ch is not None and psd_path(entry, self.project_root).is_file()

            sleep_qc   = entry.sleep_qc
            psd_status = entry.psd_status

            # 0: Animal
            self.table.setItem(row, 0, _cell(entry.animal_id))

            # 1: Preprocessed EDF (filename only to save space)
            pre = Path(entry.preprocessed_edf).name if entry.preprocessed_edf else "—"
            self.table.setItem(row, 1, _cell(pre))

            # 2: Channels
            self.table.setItem(row, 2, _cell(ch or "—"))

            # 3: Spindle EDF
            self.table.setItem(row, 3, _cell(
                "✓" if spindle_edf_ok else "—",
                _EXISTS_COLOR if spindle_edf_ok else None,
            ))

            # 4: Spindle Output
            self.table.setItem(row, 4, _cell(
                "✓" if spindle_out_ok else "—",
                _EXISTS_COLOR if spindle_out_ok else None,
            ))

            # 5: Sleep QC
            if sleep_qc is None:
                txt = "pending" if spindle_out_ok else "—"
                bg  = _PENDING_COLOR if spindle_out_ok else None
            else:
                txt = (f"rerun → {entry.rerun_channels}"
                       if sleep_qc == "rerun_channels" and entry.rerun_channels
                       else sleep_qc)
                bg  = _STATUS_COLOR.get(sleep_qc)
            self.table.setItem(row, 5, _cell(txt, bg))

            # 6: PSD File
            self.table.setItem(row, 6, _cell(
                "✓" if psd_file_ok else "—",
                _EXISTS_COLOR if psd_file_ok else None,
            ))

            # 7: PSD Status
            if psd_status is None:
                txt = "pending" if psd_file_ok else "—"
                bg  = _PENDING_COLOR if psd_file_ok else None
            else:
                txt = psd_status
                bg  = _STATUS_COLOR.get(psd_status)
            self.table.setItem(row, 7, _cell(txt, bg))

        self.table.resizeRowsToContents()

        # Shrink table height to content so file tree gets the remaining space
        total_h = self.table.horizontalHeader().height()
        for r in range(self.table.rowCount()):
            total_h += self.table.rowHeight(r)
        self.table.setMaximumHeight(total_h + 4)
