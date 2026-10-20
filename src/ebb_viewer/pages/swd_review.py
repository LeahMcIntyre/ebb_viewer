"""SWD Review page — optional per-project review of epochs that overlap SWDs.

Inputs: ``spindle_outputs/<combo>/*.csv`` (after Reclassify) and the SWD interval
``.mat`` files in ``swd/`` (``find_swd_file`` shows the accepted names).
Outputs: ``swd_reclassification`` and an updated ``final_state`` in each reviewed CSV,
and the number of reviewed SWD epochs per animal in the manifest. Only reviewed SWD epochs get a
value, so a partly finished review shows as in progress and resumes where it stopped. Off by default: the checkbox is a
project-level opt-in (``Manifest.swd_review_enabled``).
"""

import re
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

_COLUMNS = ("Animal", "SWD file", "SWD epochs", "Review", "")


# Same rule PSD compute uses to pair SWD files with animals (psd_compute.match_paths): an
# optional "<letters/digits>ts_" prefix, then the animal ID up to the next "_".
_SWD_ANIMAL = re.compile(r"^(?:[A-Za-z0-9]*ts_)?([^_]+)")


def _progress_text(n_reviewed: int, n_swd: int) -> str:
    """"—" (not started), "In progress (k of N)" or "✓ N of N"."""
    if n_swd == 0:
        return "no SWD epochs"
    if n_reviewed == 0:
        return "—"
    if n_reviewed >= n_swd:
        return f"✓ {n_swd} of {n_swd}"
    return f"In progress ({n_reviewed} of {n_swd})"


def find_swd_file(project_root: Path, animal_id: str) -> Path | None:
    """The ``swd/*.mat`` file for ``animal_id`` (first, sorted), or None.

    Matches ``Mice-1256.mat`` and ``JK1011_P063_DEL_ts.mat``, but not another animal whose ID merely starts with the same characters (A1 vs A10).
    """
    swd_dir = Path(project_root) / "swd"
    for mat in sorted(swd_dir.glob("*.mat")) if swd_dir.is_dir() else []:
        m = _SWD_ANIMAL.match(mat.stem)
        if m and m.group(1) == animal_id:
            return mat
    return None


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
        self.lbl_status.setText(f"{len(csvs)} spindle CSV(s) in {manifest.combo}")
        self.table.setRowCount(len(csvs))
        for row, (animal, csv_path) in enumerate(csvs.items()):
            mat = find_swd_file(self.project_root, animal)
            reclassed = has_column(csv_path, RECLASS_COLUMN)
            n_swd = ""
            progress = "—"
            entry = manifest.get(animal)
            if mat is not None and reclassed:
                try:
                    flags = swd_flags_for_file(csv_path, mat)[1]
                    n_swd = str(int(flags.sum()))
                    done = (
                        len(reviewed_epochs(read_state_column(csv_path, SWD_COLUMN), flags))
                        if has_column(csv_path, SWD_COLUMN)
                        else 0
                    )
                    progress = _progress_text(done, int(flags.sum()))
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
            btn = QPushButton("Review…")
            btn.setEnabled(mat is not None and reclassed and entry is not None)
            btn.clicked.connect(lambda _=False, a=animal: self._open_review(a))
            self.table.setCellWidget(row, 4, btn)

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
