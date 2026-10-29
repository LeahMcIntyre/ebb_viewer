"""Reclassify page — NREM gap fill + EMG gate, written into the spindle CSVs.

Inputs: ``spindle_outputs/<combo>/*.csv`` and preprocessed EDFs in ``standard/``.
Outputs: ``reclass_state`` and ``final_state`` columns added to each CSV (the
SleepyRat original is copied once to ``spindle_outputs/<combo>/_original/``), and
whether the EMG gate was applied recorded per animal in the manifest.
"""

from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
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
from ebb.io.spindle_csv import FINAL_COLUMN, RECLASS_COLUMN, has_column
from ebb.process.nrem_reclass import GAP_RADIUS, NremReclass, reclassify_dir_to_csv
from ebb_viewer.pipeline.manifest import Manifest, spindle_output_dir
from ebb_viewer.pipeline.theme import apply_primary_button
from ebb_viewer.widgets.page_help import title_row
from ebb_viewer.widgets.worker_helpers import launch_worker

_COLUMNS = (
    "Animal",
    "Reclassified",
    "EMG gate",
    "Gap-fill flips kept / cancelled",
    "NREM bouts (light) before → after",
)


def gate_label(reclassified: bool, gate: bool | None) -> str:
    """EMG-gate cell text. A reclassified file with no manifest record is "unknown":
    the result in ``final_state`` is right, only the label was lost (re-run restores it)."""
    if gate is not None:
        return "applied" if gate else "not needed"
    return "unknown (re-run to restore)" if reclassified else "—"


def flips_label(entry) -> str:
    """ "kept / cancelled" gap-fill flips from the last run, or "" when not recorded."""
    if entry is None or entry.reclass_flips_kept is None:
        return ""
    return f"{entry.reclass_flips_kept} / {entry.reclass_flips_cancelled}"


class _ReclassWorker(QObject):
    """Runs ``reclassify_dir_to_csv`` off the GUI thread."""

    progress = pyqtSignal(str, object)  # animal_id, NremReclass
    finished = pyqtSignal(dict)  # {animal_id: NremReclass}
    error = pyqtSignal(str)

    def __init__(self, state_dir: Path, edf_dir: Path):
        super().__init__()
        self._state_dir = state_dir
        self._edf_dir = edf_dir

    def run(self) -> None:
        try:
            results = reclassify_dir_to_csv(
                self._state_dir,
                self._edf_dir,
                on_animal=lambda a, r: self.progress.emit(a, r),
            )
        except Exception as e:  # surfaced in a dialog; the thread must not die silently
            self.error.emit(str(e))
            return
        self.finished.emit(results)


class ReclassifyPage(QWidget):
    """Sidebar page — reclassify NREM and write ``reclass_state`` into the CSVs."""

    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        # Keep the worker referenced: unparented, it is GC'd before thread.started → run.
        self._thread: QThread | None = None
        self._worker: _ReclassWorker | None = None
        self._bouts: dict[str, tuple[int, int]] = {}  # this session's before/after
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        title = title_row("Reclassify NREM", "reclassify")
        desc = QLabel(
            f"Gap-fills NREM epochs next to artifacts (radius {GAP_RADIUS}) and applies the EMG "
            f"gate where gap fill fragments light-period NREM. The result is added to each "
            f"spindle CSV as '{RECLASS_COLUMN}' and '{FINAL_COLUMN}' columns; the original CSVs are kept in an "
            f"'_original' folder. Safe to re-run; any SWD review you saved is kept and re-applied."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(title)
        root.addWidget(desc)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: gray;")
        root.addWidget(self.lbl_status)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.btn_run = QPushButton("Run reclassification")
        apply_primary_button(self.btn_run)
        self.btn_run.clicked.connect(self._run)
        root.addWidget(self.btn_run)

        swd_row = QHBoxLayout()
        swd_lbl = QLabel(
            "Optional: if you have SWD detections, you can review the epochs that overlap "
            "them before Sleep QC. Skip this to go straight to Sleep QC."
        )
        swd_lbl.setWordWrap(True)
        swd_lbl.setStyleSheet("color: #555; font-size: 12px;")
        swd_row.addWidget(swd_lbl, 1)
        btn_go_swd = QPushButton("SWD review (optional) →")
        btn_go_swd.clicked.connect(lambda: self.navigate_to.emit("swd_review"))
        swd_row.addWidget(btn_go_swd)
        root.addLayout(swd_row)

        btn_go_qc = QPushButton("→ Sleep QC")
        btn_go_qc.clicked.connect(lambda: self.navigate_to.emit("sleep_qc"))
        root.addWidget(btn_go_qc)

    # ---------------- state ----------------
    def _dirs(self) -> tuple[Path, Path]:
        manifest = Manifest.load(self.project_root)
        return spindle_output_dir(manifest.combo, self.project_root), self.project_root / "standard"

    def _refresh(self) -> None:
        manifest = Manifest.load(self.project_root)
        state_dir, _ = self._dirs()
        csvs = {parse_animal_id(p): p for p in sorted(state_dir.glob("*.csv"))}

        n_unknown = sum(
            1
            for a, p in csvs.items()
            if has_column(p, FINAL_COLUMN)
            and ((e := manifest.get(a)) is None or e.reclass_gate_applied is None)
        )
        hint = f"; EMG gate record missing for {n_unknown} (re-run to restore)" if n_unknown else ""
        self.lbl_status.setText(f"{len(csvs)} spindle CSV(s) in {state_dir}{hint}")
        self.btn_run.setEnabled(bool(csvs) and self._thread is None)

        self.table.setRowCount(len(csvs))
        for row, (animal, path) in enumerate(csvs.items()):
            entry = manifest.get(animal)
            done = has_column(path, RECLASS_COLUMN)
            gate = entry.reclass_gate_applied if entry else None
            bouts = self._bouts.get(animal)
            cells = (
                animal,
                "✓" if done else "—",
                gate_label(done, gate),
                flips_label(entry),
                f"{bouts[0]} → {bouts[1]}" if bouts else "",
            )
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))

    def _poll(self) -> None:
        if self._thread is None:
            self._refresh()

    # ---------------- run ----------------
    def _run(self) -> None:
        state_dir, edf_dir = self._dirs()
        # Warn only: re-running changes the states that earlier Sleep QC flags were
        # judged on, but those flags are left as they are.
        flagged = [e.animal_id for e in Manifest.load(self.project_root) if e.sleep_qc]
        if flagged:
            reply = QMessageBox.question(
                self,
                "Sleep QC already started",
                f"{len(flagged)} animal(s) already have Sleep QC flags. Re-running changes the "
                "states they were reviewed on. The flags are not reset. Continue?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        worker = self._worker = _ReclassWorker(state_dir, edf_dir)
        worker.progress.connect(self._on_progress)
        self._thread = QThread(self)
        self.btn_run.setEnabled(False)
        self.lbl_status.setText("Reclassifying…")
        launch_worker(self._thread, worker, on_finished=self._on_finished, on_error=self._on_error)

    def _on_progress(self, animal: str, result: NremReclass) -> None:
        self._bouts[animal] = (result.bouts_before, result.bouts_after)
        self.lbl_status.setText(f"Reclassified {animal}…")

    def _on_finished(self, results: dict) -> None:
        self._thread = self._worker = None
        manifest = Manifest.load(self.project_root)
        manifest.set_reclass_results(
            {a: (r.gate_applied, r.n_flips_kept, r.n_flips_cancelled) for a, r in results.items()}
        )
        self.manifest_changed.emit()
        self._refresh()
        n_gate = sum(r.gate_applied for r in results.values())
        self.lbl_status.setText(f"Done: {len(results)} file(s), EMG gate applied to {n_gate}.")

    def _on_error(self, msg: str) -> None:
        self._thread = self._worker = None
        self._refresh()
        QMessageBox.critical(self, "Reclassification failed", msg)
