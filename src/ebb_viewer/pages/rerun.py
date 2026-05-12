"""Rerun queue page — re-generate spindle EDFs with a different channel combo.

Animals flagged ``needs_rerun`` in Sleep QC appear here. The user picks rows,
clicks Run, and the page writes new spindle EDFs for the rerun_combo and
offers to upload them to SleepyRat. Rows reappear if upload/download was
cancelled or failed, so the user can re-trigger.
"""

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ebb.preprocess.edf import spindle as spindle_preprocess
from ebb_viewer.pages.spindle_upload import SleepyRatWorker
from ebb_viewer.pipeline import sleepyrat_config
from ebb_viewer.pipeline.manifest import (
    Manifest,
    ManifestEntry,
    spindle_edf_dir,
    spindle_output_dir,
)
from ebb_viewer.widgets.table_helpers import make_cell
from ebb_viewer.widgets.worker_helpers import launch_worker

# Channel indices per channel combo (EMG = index 3 is always included).
_COMBO_CHANNELS: dict[str, list[int]] = {
    "LFC_RSC": [0, 1, 3],
    "LFC_LSC": [0, 2, 3],
    "RSC_LSC": [1, 2, 3],
    "LFC": [0, 3],
    "RSC": [1, 3],
    "LSC": [2, 3],
}

_ORANGE = QColor("#fde8ce")
_BLUE = QColor("#dce8f7")
_GREEN = QColor("#d4edda")
_RED = QColor("#f8d7da")


class RerunPage(QWidget):
    """Sidebar page #5 — drives the rerun queue for `needs_rerun` animals."""

    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._row_data: list[tuple[ManifestEntry, str]] = []
        # Active SleepyRat workers + threads. We keep references so neither is
        # Python-garbage-collected before its event-loop slot fires; otherwise
        # only the last worker in a parallel launch loop would actually run.
        self._sr_threads: list[QThread] = []
        self._sr_workers: list[SleepyRatWorker] = []
        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        lbl = QLabel("Spindle Rerun Queue")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        hdr.addWidget(lbl)
        hdr.addStretch(1)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self._refresh)
        hdr.addWidget(btn_refresh)
        layout.addLayout(hdr)

        desc = QLabel(
            "Animals flagged during Sleep QC for reprocessing with a different channel combination. "
            "Select rows and click Run to generate new spindle EDFs and re-submit them to Spindle."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(desc)

        # Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Animal", "Standard EDF", "Original Combo", "Rerun Combo"]
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

        # Post-run hint (hidden until a run succeeds)
        self._hint_frame = QFrame()
        self._hint_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._hint_frame.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QHBoxLayout(self._hint_frame)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        hint_lbl = QLabel(
            "✓ Spindle EDFs written, uploaded to SleepyRat, and downloaded. "
            "Go to Sleep QC to review the new results."
        )
        hint_lbl.setWordWrap(True)
        hint_layout.addWidget(hint_lbl, 1)
        btn_go_qc = QPushButton("→ Sleep QC")
        btn_go_qc.clicked.connect(lambda: self.navigate_to.emit("sleep_qc"))
        hint_layout.addWidget(btn_go_qc)
        self._hint_frame.setVisible(False)
        layout.addWidget(self._hint_frame)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(500)
        self.log_box.setPlaceholderText("Status messages will appear here…")
        layout.addWidget(self.log_box)

    # ---------------------------------------------------------------- Data

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()

    def _poll(self):
        self._refresh()

    def _refresh(self):
        self.table.setRowCount(0)  # clears all spans and content from previous render
        manifest = Manifest.load(self.project_root)

        # Show entries where the rerun output CSV hasn't been downloaded yet.
        # Exclude only when the rerun run has been reviewed (sleep_qc set) OR the
        # output CSV is already on disk (pending_rerun_review / blue card takes over).
        # This means items re-appear here if the upload dialog was cancelled or the
        # download failed — the user can run again to re-trigger the upload.
        pairs = []
        for entry, combo in manifest.needs_rerun():
            rerun_combo = entry.runs[combo].rerun_combo
            if rerun_combo not in entry.runs:
                pairs.append((entry, combo))
                continue
            rerun_run = entry.runs[rerun_combo]
            if rerun_run.sleep_qc is not None:
                continue  # already reviewed
            csv_present = any(
                spindle_output_dir(rerun_combo, self.project_root).glob(f"{entry.animal_id}_*.csv")
            )
            if not csv_present:
                pairs.append((entry, combo))

        self.table.setRowCount(len(pairs))
        self._row_data = []

        for i, (entry, combo) in enumerate(pairs):
            run = entry.runs[combo]
            rerun_combo = run.rerun_combo or "?"
            edf_name = Path(entry.preprocessed_edf).name if entry.preprocessed_edf else "—"

            self.table.setItem(i, 0, make_cell(entry.animal_id))
            self.table.setItem(i, 1, make_cell(edf_name))
            self.table.setItem(i, 2, make_cell(combo, _ORANGE))
            self.table.setItem(i, 3, make_cell(rerun_combo, _BLUE))
            self._row_data.append((entry, combo))

        self.table.resizeRowsToContents()
        self.btn_run.setEnabled(len(pairs) > 0)

        if not pairs:
            self.table.setRowCount(1)
            placeholder = make_cell("No files pending rerun.")
            placeholder.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setSpan(0, 0, 1, 4)
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

        # Disable the run button while spindle EDF writes are in flight.
        # Re-enabled in `_offer_upload` (after dialogs) or in the error path.
        self.btn_run.setEnabled(False)
        manifest = Manifest.load(self.project_root)
        items = [self._row_data[r] for r in selected_rows if r < len(self._row_data)]

        errors: list[str] = []
        written_combos: set[tuple[str, str]] = set()
        written_files: dict[str, list[Path]] = {}  # rerun_combo → list of EDF paths written

        for step, (entry, combo) in enumerate(items):
            run = entry.runs[combo]
            rerun_combo = run.rerun_combo
            row = selected_rows[step]

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
                channels = _COMBO_CHANNELS[rerun_combo]
                target_dir = spindle_edf_dir(rerun_combo, self.project_root)
                already_written = target_dir.is_dir() and any(
                    target_dir.glob(f"{entry.animal_id}*.edf")
                )
                if already_written:
                    self._log("  EDF already written — skipping to upload.")
                else:
                    spindle_preprocess(edf_path, savedir=target_dir, channels=channels)
                manifest.add_run(entry.animal_id, rerun_combo, source_combo=combo)
                written_combos.add((combo, rerun_combo))
                written_files.setdefault(rerun_combo, []).extend(
                    target_dir.glob(f"{entry.animal_id}*.edf")
                )
                self._color_row(row, _GREEN)
                self._log("  Done.")
            except Exception as e:
                msg = f"{entry.animal_id}: {e}"
                self._log(f"  ERROR: {msg}")
                errors.append(msg)
                self._color_row(row, _RED)

        if errors:
            QMessageBox.warning(
                self,
                "Some files failed",
                "The following errors occurred:\n\n" + "\n".join(errors),
            )

        if written_combos:
            self._refresh()
            self.manifest_changed.emit()
            self._offer_upload(written_combos, written_files)
        else:
            # Nothing to upload — re-enable for the user to retry.
            self.btn_run.setEnabled(True)

    def _on_sr_finished(self) -> None:
        self._hint_frame.setVisible(True)
        self.btn_run.setEnabled(True)

    def _on_sr_error(self, msg: str) -> None:
        self._log(f"ERROR: {msg}")
        self.btn_run.setEnabled(True)
        QMessageBox.critical(self, "SleepyRat Error", msg)

    def _offer_upload(
        self, written_combos: set[tuple[str, str]], written_files: dict[str, list[Path]]
    ) -> None:
        """Show one dialog with a row per rerun combo; launch all accepted uploads in parallel.

        Workers and threads are appended to ``self._sr_workers`` / ``self._sr_threads`` so
        Python doesn't garbage-collect earlier ones before their event-loop slots fire.
        ``SleepyRatWorker`` has no Qt parent, so overwriting a single attribute slot would
        destroy the earlier worker before ``thread.started → worker.run`` could dispatch.
        """
        # Build per-rerun-combo defaults, deduplicated and ordered.
        rows: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for orig_combo, rerun_combo in sorted(written_combos):
            if rerun_combo in seen:
                continue
            seen.add(rerun_combo)
            saved = sleepyrat_config.get_combo(self.project_root, orig_combo)
            project = saved["project"] if saved else ""
            folder = f"{self.project_root.stem}_{rerun_combo}"
            rows.append((rerun_combo, project, folder))

        if not rows:
            self.btn_run.setEnabled(True)
            return

        dlg = _UploadDialog(self, rows=rows)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.btn_run.setEnabled(True)
            return

        # Reset refs from any previous run — prior workers have finished by the
        # time the user is initiating a new rerun batch.
        self._sr_workers = []
        self._sr_threads = []

        for rerun_combo, project_name, remote_folder in dlg.entries():
            out_dir = self.project_root / "spindle_outputs" / rerun_combo

            thread = QThread(self)
            worker = SleepyRatWorker(
                project_name,
                remote_folder,
                out_dir,
                files=written_files.get(rerun_combo),
            )
            worker.log.connect(self._log)
            worker.finished.connect(
                lambda p=project_name, f=remote_folder, rc=rerun_combo: sleepyrat_config.save_combo(
                    self.project_root, rc, p, f
                )
            )
            self._sr_threads.append(thread)
            self._sr_workers.append(worker)
            launch_worker(
                thread,
                worker,
                on_finished=self._on_sr_finished,
                on_error=self._on_sr_error,
            )

    def _color_row(self, row: int, color: QColor) -> None:
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                item.setBackground(color)


class _UploadDialog(QDialog):
    """Confirm SleepyRat upload settings for one or more rerun combos.

    Shows a grid with one row per rerun combo. Editable project and folder
    fields per row. ``entries()`` returns the user-confirmed values after
    accept.
    """

    def __init__(self, parent, *, rows: list[tuple[str, str, str]]):
        super().__init__(parent)
        n = len(rows)
        self.setWindowTitle("Upload Reruns" if n != 1 else f"Upload Rerun: {rows[0][0]}")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)

        if n == 1:
            header = (
                f"Spindle EDFs for <b>{rows[0][0]}</b> have been written.<br>"
                "Confirm upload destination:"
            )
        else:
            header = (
                f"Spindle EDFs for <b>{n}</b> rerun combos have been written.<br>"
                "Confirm upload destinations:"
            )
        lbl = QLabel(header)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        for col, text in enumerate(("Combo", "SleepyRat project", "Remote folder")):
            hdr = QLabel(f"<b>{text}</b>")
            hdr.setTextFormat(Qt.TextFormat.RichText)
            grid.addWidget(hdr, 0, col)

        # column stretches: combo fixed, project + folder share remaining space
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        self._rows: list[tuple[str, QLineEdit, QLineEdit]] = []
        for i, (rerun_combo, project, folder) in enumerate(rows, start=1):
            combo_lbl = QLabel(rerun_combo)
            combo_lbl.setStyleSheet("font-family: monospace;")
            project_edit = QLineEdit(project)
            folder_edit = QLineEdit(folder)
            grid.addWidget(combo_lbl, i, 0)
            grid.addWidget(project_edit, i, 1)
            grid.addWidget(folder_edit, i, 2)
            self._rows.append((rerun_combo, project_edit, folder_edit))

        layout.addLayout(grid)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Upload All" if n != 1 else "Upload & Download"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def entries(self) -> list[tuple[str, str, str]]:
        """Return [(rerun_combo, project, remote_folder), ...] as edited by the user."""
        return [
            (combo, p.text().strip(), f.text().strip()) for combo, p, f in self._rows
        ]
