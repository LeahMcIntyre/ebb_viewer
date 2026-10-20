"""SWD Review page — optional per-project review of epochs that overlap SWDs.

Inputs: ``spindle_outputs/<combo>/*.csv`` (after Reclassify) and the SWD interval
``.mat`` files in ``swd/`` (``find_swd_file`` shows the accepted names). With review on, every
animal needs an SWD file (an empty one is fine) or the user's confirmation that it has none.
Outputs: ``swd_reclassification`` and an updated ``final_state`` in each reviewed CSV,
and the number of reviewed SWD epochs per animal in the manifest. Only reviewed SWD epochs get a
value, so a partly finished review shows as in progress and resumes where it stopped. Off by default: the checkbox is a
project-level opt-in (``Manifest.swd_review_enabled``).
"""

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ebb.core.naming import parse_animal_id
from ebb.io.spindle_csv import RECLASS_COLUMN, SWD_COLUMN, has_column, read_state_column
from ebb.process.swd_review import reviewed_epochs, swd_flags_for_file
from ebb_viewer.edf_viewer.swd_review import launch_swd_review
from ebb_viewer.pipeline.manifest import Manifest, spindle_output_dir
from ebb_viewer.pipeline.swd_review import find_swd_file

_COLUMNS = ("Animal", "SWD file", "SWD epochs", "Review", "")


def _progress_text(n_reviewed: int, n_swd: int) -> str:
    """"—" (not started), "In progress (k of N)" or "✓ N of N"."""
    if n_swd == 0:
        return "no SWD epochs"
    if n_reviewed == 0:
        return "—"
    if n_reviewed >= n_swd:
        return f"✓ {n_swd} of {n_swd}"
    return f"In progress ({n_reviewed} of {n_swd})"


class SwdReviewPage(QWidget):
    """Sidebar page — enable SWD review and open a per-animal review window."""

    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._windows: list = []  # keep open review windows referenced
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        title = QLabel("SWD Review (optional)")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        desc = QLabel(
            "Step through the 4 s epochs that overlap a spike-wave discharge and fix their "
            "sleep state where the reclassification is wrong. Any other epoch can be edited "
            "too. Results go into each CSV as 'swd_reclassification' (blank except SWD "
            "epochs and epochs you changed) and 'final_state' is updated, so every later "
            "step picks them up. Run Reclassify first; re-running it keeps your edits."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(title)
        root.addWidget(desc)

        self.chk_enable = QCheckBox("Review SWD epochs for this project")
        self.chk_enable.toggled.connect(self._on_enable_toggled)
        root.addWidget(self.chk_enable)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: gray;")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        btn_go = QPushButton("→ Sleep QC")
        btn_go.clicked.connect(lambda: self.navigate_to.emit("sleep_qc"))
        root.addWidget(btn_go)

    # ---------------- state ----------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh()

    def _on_enable_toggled(self, checked: bool) -> None:
        manifest = Manifest.load(self.project_root)
        if manifest.swd_review_enabled == checked:
            return
        manifest.set_swd_review_enabled(checked)
        self.manifest_changed.emit()
        self._refresh()

    def _refresh(self) -> None:
        manifest = Manifest.load(self.project_root)
        enabled = manifest.swd_review_enabled
        self.chk_enable.blockSignals(True)
        self.chk_enable.setChecked(enabled)
        self.chk_enable.blockSignals(False)
        self.table.setVisible(enabled)

        csvs = {
            parse_animal_id(p): p
            for p in sorted(spindle_output_dir(manifest.combo, self.project_root).glob("*.csv"))
        }
        if not enabled:
            self.lbl_status.setText("SWD review is off for this project; nothing is changed.")
            self.table.setRowCount(0)
            return
        self.lbl_status.setText(
            f"{len(csvs)} spindle CSV(s) in {manifest.combo}. Every animal needs an SWD file "
            "(an empty one is fine) or your confirmation that it has none."
        )
        self.table.setRowCount(len(csvs))
        synced = False
        for row, (animal, csv_path) in enumerate(csvs.items()):
            mat = find_swd_file(self.project_root, animal)
            reclassed = has_column(csv_path, RECLASS_COLUMN)
            entry = manifest.get(animal)
            n_swd = ""
            progress = "—"
            if mat is None:
                progress = "Confirmed: no SWD needed" if entry and entry.swd_waived else "Needs file or confirmation"
            elif reclassed:
                try:
                    flags = swd_flags_for_file(csv_path, mat)[1]
                    n_swd = str(int(flags.sum()))
                    done = (
                        len(reviewed_epochs(read_state_column(csv_path, SWD_COLUMN), flags))
                        if has_column(csv_path, SWD_COLUMN)
                        else 0
                    )
                    progress = _progress_text(done, int(flags.sum()))
                    if entry is not None and (entry.swd_reviewed, entry.swd_total) != (
                        done,
                        int(flags.sum()),
                    ):
                        # keep the manifest cache (home page, warnings) in step with the CSV
                        entry.swd_reviewed, entry.swd_total = done, int(flags.sum())
                        synced = True
                except (ValueError, OSError) as e:
                    n_swd = f"error: {e}"
            cells = (
                animal,
                mat.name if mat else "— no SWD file",
                n_swd if reclassed else "run Reclassify",
                progress,
            )
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))
            if mat is None:
                waived = bool(entry and entry.swd_waived)
                btn = QPushButton("Undo confirmation" if waived else "Confirm no SWD")
                btn.setEnabled(entry is not None)
                btn.clicked.connect(lambda _=False, a=animal: self._toggle_waived(a))
            else:
                btn = QPushButton("Review…")
                btn.setEnabled(reclassed and entry is not None)
                btn.clicked.connect(lambda _=False, a=animal: self._open_review(a))
            self.table.setCellWidget(row, 4, btn)
        if synced:
            manifest.save()

    def _toggle_waived(self, animal: str) -> None:
        """Confirm that an animal has no SWD file and needs none, or undo that confirmation."""
        manifest = Manifest.load(self.project_root)
        entry = manifest.get(animal)
        if entry is None:
            return
        if not entry.swd_waived:
            reply = QMessageBox.question(
                self,
                "Confirm no SWD file",
                f"{animal} has no SWD file in swd/. Confirm that this animal has no SWDs to "
                "review and does not need one?\n\nIf it does, add a file (an empty one is "
                "fine) instead.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        manifest.set_swd_waived(animal, not entry.swd_waived)
        self.manifest_changed.emit()
        self._refresh()

    # ---------------- review ----------------
    def _open_review(self, animal: str) -> None:
        manifest = Manifest.load(self.project_root)
        entry = manifest.get(animal)
        csv_path = next(
            (
                p
                for p in sorted(spindle_output_dir(manifest.combo, self.project_root).glob("*.csv"))
                if parse_animal_id(p) == animal
            ),
            None,
        )
        mat = find_swd_file(self.project_root, animal)
        if entry is None or csv_path is None or mat is None:
            QMessageBox.warning(self, "SWD review", f"Missing CSV or SWD file for {animal}.")
            return
        try:
            win = launch_swd_review(
                self.project_root / entry.preprocessed_edf,
                csv_path,
                mat,
                animal_id=animal,
                on_saved=self._on_saved,
            )
        except Exception as e:
            QMessageBox.critical(self, "Could not open SWD review", str(e))
            return
        win.resize(1200, 800)
        win.show()
        self._windows.append(win)
        win.destroyed.connect(lambda _=None, w=win: self._windows.remove(w) if w in self._windows else None)

    def _on_saved(self, animal: str, reviewed: int, total: int) -> None:
        Manifest.load(self.project_root).set_swd_progress(animal, reviewed, total)
        self.manifest_changed.emit()
        self._refresh()
