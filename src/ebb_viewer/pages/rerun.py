from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QApplication, QDialog,
    QFormLayout, QLineEdit, QDialogButtonBox, QPlainTextEdit,
)

from ebb.preprocess.edf import spindle as spindle_preprocess
from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry, spindle_edf_dir
from ebb_viewer.pipeline import sleepyrat_config
from ebb_viewer.pages.spindle_upload import SleepyRatWorker


# Maps channel combo name → channel indices (EMG index 3 always included)
_COMBO_CHANNELS: dict[str, list[int]] = {
    "LFC_RSC": [0, 1, 3],
    "LFC_LSC": [0, 2, 3],
    "RSC_LSC": [1, 2, 3],
    "LFC":     [0, 3],
    "RSC":     [1, 3],
    "LSC":     [2, 3],
}

_ORANGE = QColor("#fde8ce")
_BLUE   = QColor("#dce8f7")
_GREEN  = QColor("#d4edda")
_RED    = QColor("#f8d7da")
_GRAY   = QColor("#e8e8e8")


def _combo_to_channels(combo: str) -> list[int]:
    if combo in _COMBO_CHANNELS:
        return _COMBO_CHANNELS[combo]
    # Fallback: parse from combo name
    mapping = {"LFC": 0, "RSC": 1, "LSC": 2}
    parts = combo.split("_")
    indices = sorted({mapping[p] for p in parts if p in mapping})
    indices.append(3)  # EMG always
    return indices


def _rerun_step(entry: ManifestEntry, combo: str, project_root: Path) -> tuple[str, QColor]:
    """Return (status_label, color) for where this rerun currently stands."""
    rerun_combo = entry.runs[combo].rerun_combo
    if rerun_combo not in entry.runs:
        return "Write EDF", _ORANGE
    out_dir = project_root / "spindle_outputs" / rerun_combo
    if not out_dir.is_dir() or not any(out_dir.glob(f"{entry.animal_id}*_labels.csv")):
        return "Upload & Download", _BLUE
    return "Sleep QC pending", _GRAY


def _cell(text: str, bg: QColor | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if bg is not None:
        item.setBackground(bg)
    return item


class RerunPage(QWidget):
    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._row_data: list[tuple[ManifestEntry, str]] = []
        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        lbl = QLabel("Spindle Rerun Queue")
        lbl.setStyleSheet("font-weight: bold; font-size: 15px;")
        hdr.addWidget(lbl)
        hdr.addStretch(1)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self._refresh)
        hdr.addWidget(btn_refresh)
        layout.addLayout(hdr)

        desc = QLabel(
            "Files flagged during Sleep QC to be rerun with a different channel combination. "
            "Select rows and click Run to write the new spindle EDFs."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(desc)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Animal", "Standard EDF", "Original Combo", "Rerun Combo", "Status"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.clicked.connect(self.table.selectAll)
        btn_row.addWidget(self.btn_select_all)
        self.btn_run = QPushButton("Run Selected")
        self.btn_run.setStyleSheet("font-weight: bold;")
        self.btn_run.clicked.connect(self._run_selected)
        btn_row.addWidget(self.btn_run)
        layout.addLayout(btn_row)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(500)
        self.log_box.setPlaceholderText("Status messages will appear here…")
        layout.addWidget(self.log_box)

    # ---------------------------------------------------------------- Data

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()

    def _refresh(self):
        manifest = Manifest.load(self.project_root)

        # Show all needs_rerun entries where the rerun hasn't been QC'd yet.
        pairs = [
            (entry, combo)
            for entry, combo in manifest.needs_rerun()
            if (
                entry.runs[combo].rerun_combo not in entry.runs
                or entry.runs[entry.runs[combo].rerun_combo].sleep_qc is None
            )
        ]

        self.table.setRowCount(len(pairs))
        self._row_data = []

        for i, (entry, combo) in enumerate(pairs):
            run = entry.runs[combo]
            rerun_combo = run.rerun_combo or "?"
            edf_name = Path(entry.preprocessed_edf).name if entry.preprocessed_edf else "—"
            status_label, status_color = _rerun_step(entry, combo, self.project_root)

            self.table.setItem(i, 0, _cell(entry.animal_id))
            self.table.setItem(i, 1, _cell(edf_name))
            self.table.setItem(i, 2, _cell(combo, _ORANGE))
            self.table.setItem(i, 3, _cell(rerun_combo, _BLUE))
            self.table.setItem(i, 4, _cell(status_label, status_color))
            self._row_data.append((entry, combo, status_label))

        self.table.resizeRowsToContents()
        self.btn_run.setEnabled(len(pairs) > 0)

        if not pairs:
            self.table.setRowCount(1)
            placeholder = _cell("No files pending rerun.")
            placeholder.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setSpan(0, 0, 1, 5)
            self.table.setItem(0, 0, placeholder)

    # ----------------------------------------------------------------- Log

    def _log(self, msg: str) -> None:
        self.log_box.appendPlainText(msg)
        QApplication.processEvents()

    # -------------------------------------------------------------- Actions

    def _run_selected(self):
        selected_rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not selected_rows:
            QMessageBox.information(self, "No Selection", "Select at least one row to run.")
            return

        manifest = Manifest.load(self.project_root)
        items = [self._row_data[r] for r in selected_rows if r < len(self._row_data)]

        errors: list[str] = []
        # Track which rerun combos were written successfully (for upload step)
        written_combos: set[str] = set()

        for step, (entry, combo, status_label) in enumerate(items):
            run = entry.runs[combo]
            rerun_combo = run.rerun_combo
            row = selected_rows[step]

            if status_label == "Sleep QC pending":
                self._log(f"[{step + 1}/{len(items)}] {entry.animal_id}: outputs ready, go to Sleep QC.")
                continue

            self._log(f"[{step + 1}/{len(items)}] {entry.animal_id} → {rerun_combo}…")

            if not entry.preprocessed_edf:
                msg = f"{entry.animal_id}: no preprocessed EDF set"
                self._log(f"  ERROR: {msg}")
                errors.append(msg)
                self._color_row(row, _RED)
                continue

            edf_path = self.project_root / entry.preprocessed_edf
            if not edf_path.is_file():
                msg = f"{entry.animal_id}: EDF not found at {edf_path}"
                self._log(f"  ERROR: {msg}")
                errors.append(msg)
                self._color_row(row, _RED)
                continue

            try:
                channels = _combo_to_channels(rerun_combo)
                target_dir = spindle_edf_dir(rerun_combo, self.project_root)
                already_written = target_dir.is_dir() and any(target_dir.glob(f"{entry.animal_id}*.edf"))
                if already_written:
                    self._log(f"  Spindle EDF already exists, skipping preprocessing.")
                else:
                    spindle_preprocess(edf_path, savedir=target_dir, channels=channels)
                manifest.add_run(entry.animal_id, rerun_combo)
                written_combos.add((combo, rerun_combo))
                self._color_row(row, _GREEN)
                self._log(f"  Done.")
            except Exception as e:
                msg = f"{entry.animal_id}: {e}"
                self._log(f"  ERROR: {msg}")
                errors.append(msg)
                self._color_row(row, _RED)

        if errors:
            QMessageBox.warning(
                self, "Some files failed",
                "The following errors occurred:\n\n" + "\n".join(errors),
            )

        if written_combos:
            self._refresh()
            self._offer_upload(written_combos)

    def _offer_upload(self, written_combos: set[tuple[str, str]]) -> None:
        """For each unique rerun combo written, offer SleepyRat upload using saved config."""
        from PyQt6.QtCore import QThread
        seen_rerun_combos: set[str] = set()

        for orig_combo, rerun_combo in written_combos:
            if rerun_combo in seen_rerun_combos:
                continue
            seen_rerun_combos.add(rerun_combo)

            saved = sleepyrat_config.get_combo(self.project_root, orig_combo)
            project = saved["project"] if saved else ""
            default_folder = f"{self.project_root.stem}_{rerun_combo}"

            dlg = _UploadDialog(
                self,
                rerun_combo=rerun_combo,
                project=project,
                remote_folder=default_folder,
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                continue

            project_name = dlg.project_edit.text().strip()
            remote_folder = dlg.folder_edit.text().strip()
            upload_dir = spindle_edf_dir(rerun_combo, self.project_root)
            out_dir = self.project_root / "spindle_outputs" / rerun_combo

            self._sr_thread = QThread(self)
            self._sr_worker = SleepyRatWorker(
                project_name, remote_folder, out_dir, upload_dir=upload_dir
            )
            self._sr_worker.moveToThread(self._sr_thread)
            self._sr_thread.started.connect(self._sr_worker.run)
            self._sr_worker.log.connect(self._log)
            self._sr_worker.finished.connect(self._sr_thread.quit)
            self._sr_worker.finished.connect(self._sr_worker.deleteLater)
            self._sr_worker.error.connect(self._sr_thread.quit)
            self._sr_worker.error.connect(self._sr_worker.deleteLater)
            self._sr_thread.finished.connect(self._sr_thread.deleteLater)
            self._sr_worker.finished.connect(
                lambda p=project_name, f=remote_folder, rc=rerun_combo:
                    sleepyrat_config.save_combo(self.project_root, rc, p, f)
            )
            self._sr_worker.error.connect(
                lambda msg: (self._log(f"ERROR: {msg}"),
                             QMessageBox.critical(self, "SleepyRat Error", msg))
            )
            self._sr_thread.start()

    def _color_row(self, row: int, color: QColor) -> None:
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                item.setBackground(color)


class _UploadDialog(QDialog):
    """Confirm SleepyRat upload settings for a rerun combo."""

    def __init__(self, parent, *, rerun_combo: str, project: str, remote_folder: str):
        super().__init__(parent)
        self.setWindowTitle(f"Upload Rerun: {rerun_combo}")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        lbl = QLabel(
            f"Spindle EDFs for <b>{rerun_combo}</b> have been written.<br>"
            "Upload to SleepyRat now?"
        )
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        form = QFormLayout()
        self.project_edit = QLineEdit(project)
        self.folder_edit = QLineEdit(remote_folder)
        form.addRow("SleepyRat project:", self.project_edit)
        form.addRow("Remote folder name:", self.folder_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Upload & Download")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
