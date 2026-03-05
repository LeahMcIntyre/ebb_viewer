from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QComboBox, QMessageBox,
)

from ebb_viewer.widgets.tree_view import ProjectTree
from ebb_viewer.pipeline.manifest import (
    Manifest, ManifestEntry, RunEntry,
    psd_path, spindle_output_dir,
)

_CHANNEL_COMBOS = ["LFC_RSC", "LFC_LSC", "RSC_LSC", "LFC", "RSC", "LSC"]


# Pipeline stage columns
_COLUMNS = [
    "Animal", "Preprocessed", "Channels",
    "Spindle EDF", "Spindle Output",
    "Sleep QC", "PSD File", "PSD Status",
]

_STATUS_COLOR = {
    "ok":                QColor("#d4edda"),   # green
    "needs_review":      QColor("#fff3cd"),   # yellow
    "needs_rerun":       QColor("#fde8ce"),   # orange
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
        self._open_windows: list = []
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
            "animals and runs not yet in the manifest"
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

        # --- review queue ---
        queue_lbl = QLabel("Review Queue")
        queue_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        root_layout.addWidget(queue_lbl)

        self._queue_container = QWidget()
        self._queue_layout = QVBoxLayout(self._queue_container)
        self._queue_layout.setContentsMargins(0, 2, 0, 4)
        self._queue_layout.setSpacing(3)
        root_layout.addWidget(self._queue_container)

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

        # Build one row per (animal, run) pair
        rows: list[tuple[ManifestEntry, str, RunEntry]] = []
        for entry in manifest:
            if entry.runs:
                for combo, run in entry.runs.items():
                    rows.append((entry, combo, run))
            else:
                # Animal exists but no runs yet — show a placeholder row
                rows.append((entry, "", None))

        self.table.setRowCount(len(rows))
        for row_idx, (entry, combo, run) in enumerate(rows):
            spindle_edf_ok  = bool(combo) and _any_file_for_animal(
                self.project_root, "spindle_edfs", combo, entry.animal_id)
            spindle_out_ok  = bool(combo) and _any_file_for_animal(
                self.project_root, "spindle_outputs", combo, entry.animal_id)
            psd_file_ok     = bool(combo) and psd_path(combo, self.project_root).is_file()

            sleep_qc   = run.sleep_qc   if run else None
            psd_status = run.psd_status if run else None

            # 0: Animal
            self.table.setItem(row_idx, 0, _cell(entry.animal_id))

            # 1: Preprocessed EDF (filename only)
            pre = Path(entry.preprocessed_edf).name if entry.preprocessed_edf else "—"
            self.table.setItem(row_idx, 1, _cell(pre))

            # 2: Channels
            self.table.setItem(row_idx, 2, _cell(combo or "—"))

            # 3: Spindle EDF
            self.table.setItem(row_idx, 3, _cell(
                "✓" if spindle_edf_ok else "—",
                _EXISTS_COLOR if spindle_edf_ok else None,
            ))

            # 4: Spindle Output
            self.table.setItem(row_idx, 4, _cell(
                "✓" if spindle_out_ok else "—",
                _EXISTS_COLOR if spindle_out_ok else None,
            ))

            # 5: Sleep QC
            if sleep_qc is None:
                txt = "pending" if spindle_out_ok else "—"
                bg  = _PENDING_COLOR if spindle_out_ok else None
            else:
                txt = (f"rerun → {run.rerun_combo}"
                       if sleep_qc == "needs_rerun" and run.rerun_combo
                       else sleep_qc)
                bg  = _STATUS_COLOR.get(sleep_qc)
            self.table.setItem(row_idx, 5, _cell(txt, bg))

            # 6: PSD File
            self.table.setItem(row_idx, 6, _cell(
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
            self.table.setItem(row_idx, 7, _cell(txt, bg))

        self.table.resizeRowsToContents()

        # Shrink table height to content so file tree gets the remaining space
        total_h = self.table.horizontalHeader().height()
        for r in range(self.table.rowCount()):
            total_h += self.table.rowHeight(r)
        self.table.setMaximumHeight(total_h + 4)
        self._refresh_review_queue(manifest)

    # ---------------------------------------------------------------
    # Review queue
    # ---------------------------------------------------------------
    def _refresh_review_queue(self, manifest: Manifest) -> None:
        while self._queue_layout.count():
            item = self._queue_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        pairs = manifest.needs_review()
        if not pairs:
            lbl = QLabel("No animals pending review.")
            lbl.setStyleSheet("color: #888;")
            self._queue_layout.addWidget(lbl)
            return

        for entry, channels in pairs:
            self._queue_layout.addWidget(self._make_queue_row(entry, channels))

    def _make_queue_row(self, entry: ManifestEntry, channels: str) -> QWidget:
        edf_name = Path(entry.preprocessed_edf).name if entry.preprocessed_edf else "—"

        row_w = QWidget()
        row_w.setStyleSheet("background-color: #fff3cd; border-radius: 3px;")
        h = QHBoxLayout(row_w)
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(8)

        h.addWidget(QLabel(f"<b>{entry.animal_id}</b>"))

        lbl_ch = QLabel(f"[{channels}]")
        lbl_ch.setStyleSheet("color: #555;")
        h.addWidget(lbl_ch)

        lbl_file = QLabel(edf_name)
        lbl_file.setStyleSheet("color: #888;")
        h.addWidget(lbl_file, stretch=1)

        btn_open = QPushButton("Open EDF")
        btn_open.setFixedHeight(24)
        btn_open.clicked.connect(lambda _, e=entry, ch=channels: self._open_edf_for_animal(e, ch))
        h.addWidget(btn_open)

        btn_ok = QPushButton("✓ OK")
        btn_ok.setFixedHeight(24)
        btn_ok.clicked.connect(
            lambda _, mid=entry.animal_id, ch=channels: self._queue_flag_ok(mid, ch)
        )
        h.addWidget(btn_ok)

        rerun_combo = QComboBox()
        rerun_combo.addItems(_CHANNEL_COMBOS)
        # Pre-select a sensible default (not the current combo)
        others = [c for c in _CHANNEL_COMBOS if c != channels]
        if others:
            rerun_combo.setCurrentText(others[0])
        h.addWidget(rerun_combo)

        btn_rerun = QPushButton("Needs Rerun")
        btn_rerun.setFixedHeight(24)
        btn_rerun.clicked.connect(
            lambda _, mid=entry.animal_id, ch=channels, c=rerun_combo:
                self._queue_flag_rerun(mid, ch, c.currentText())
        )
        h.addWidget(btn_rerun)

        return row_w

    def _queue_flag_ok(self, animal_id: str, channels: str) -> None:
        Manifest.load(self.project_root).flag_sleep_qc(animal_id, channels, "ok")
        self._refresh()

    def _queue_flag_rerun(self, animal_id: str, channels: str, rerun_combo: str) -> None:
        Manifest.load(self.project_root).flag_sleep_qc(
            animal_id, channels, "needs_rerun", rerun_combo=rerun_combo
        )
        self._refresh()

    def _open_edf_for_animal(self, entry: ManifestEntry, channels: str) -> None:
        if not entry.preprocessed_edf:
            QMessageBox.warning(self, "No EDF", f"No preprocessed EDF set for {entry.animal_id}.")
            return
        edf_path = self.project_root / entry.preprocessed_edf
        if not edf_path.is_file():
            QMessageBox.warning(self, "File not found", f"EDF not found:\n{edf_path}")
            return

        csv_path = self._find_spindle_csv(entry.animal_id, channels)
        manifest = Manifest.load(self.project_root)

        from ebb_viewer.edf_viewer.eeg_viewer import launch_edf_window
        try:
            win = launch_edf_window(
                edf_path=edf_path,
                csv_path=csv_path,
                manifest=manifest,
                animal_id=entry.animal_id,
                run_channels=channels,
                initial_dir=str(self.project_root),
            )
            win.resize(1200, 800)
            win.show()
            self._open_windows.append(win)
        except Exception as e:
            QMessageBox.critical(self, "Error opening EDF", f"{type(e).__name__}: {e}")

    def _find_spindle_csv(self, animal_id: str, channels: str) -> Path | None:
        try:
            d = spindle_output_dir(channels, self.project_root)
            hits = sorted(d.glob(f"{animal_id}*labels.csv"))
            return hits[0] if hits else None
        except Exception:
            return None
