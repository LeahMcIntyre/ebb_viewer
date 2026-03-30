from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPlainTextEdit, QMessageBox, QApplication,
    QLineEdit, QSizePolicy, QFrame,
)

from ebb_viewer.widgets.worker_helpers import launch_worker

# Keys stored in psd_params.json that are UI/config only and must not be
# forwarded to computation functions (rerun_with_drink_masks, estimate_psd).
_UI_ONLY_PARAM_KEYS = frozenset({"swd_mode"})

CH_LABELS = ["LFC", "RSC", "LSC"]


class DrinkMaskPage(QWidget):

    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._computing = False
        self._pending_animal_combos: dict = {}

        self._build_ui()
        self._wire()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)

        hdr = QHBoxLayout()
        lbl = QLabel("Drink Mask Rerun")
        lbl.setStyleSheet("font-weight: bold; font-size: 15px;")
        hdr.addWidget(lbl)
        hdr.addStretch(1)
        self.btn_refresh = QPushButton("Refresh")
        hdr.addWidget(self.btn_refresh)
        root.addLayout(hdr)

        desc = QLabel(
            "Recompute PSDs for animals flagged 'needs_drink_mask' using their .npy mask files. "
            "PSD params are loaded from the last Compute PSDs run (read-only)."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(desc)

        # ----- Group 1: Paths -----
        self.gb_paths = QGroupBox("Paths")
        self.gb_paths.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        paths_form = QFormLayout(self.gb_paths)

        self.lbl_drink_dir = QLineEdit()
        self.lbl_drink_dir.setReadOnly(True)
        paths_form.addRow("Drink Masks Folder:", self.lbl_drink_dir)

        self._lbl_mask_count = QLabel()
        paths_form.addRow("Mask files found:", self._lbl_mask_count)

        self.lbl_offset_csv = QLineEdit("None")
        self.lbl_offset_csv.setReadOnly(True)
        paths_form.addRow("Video Offset CSV:", self.lbl_offset_csv)

        root.addWidget(self.gb_paths)

        # ----- Group 2: PSD Params (read-only) -----
        self.gb_params = QGroupBox("PSD Parameters (from last compute run)")
        self.gb_params.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        params_form = QFormLayout(self.gb_params)

        self._param_labels: dict[str, QLabel] = {}
        for key, display in [
            ("fs", "Sampling freq (Hz)"),
            ("channels", "Channels"),
            ("winsize", "SD window (s)"),
            ("radius", "SD radius (s)"),
            ("nstd", "SD z-threshold"),
            ("noise_thresh", "Spindle noise threshold"),
        ]:
            lbl = QLabel("—")
            self._param_labels[key] = lbl
            params_form.addRow(display + ":", lbl)

        root.addWidget(self.gb_params)

        # ----- Group 3: Animals pending drink mask -----
        self.gb_animals = QGroupBox("Animals Pending Drink Mask Rerun")
        animals_v = QVBoxLayout(self.gb_animals)

        self._lbl_status = QLabel("No animals pending drink mask rerun.")
        self._lbl_status.setStyleSheet("color: gray;")
        animals_v.addWidget(self._lbl_status)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Animal (Combo)", "PSD Status", "Mask File"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 130)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(2, 110)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setVisible(False)
        animals_v.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_apply = QPushButton("Apply Drink Masks")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setStyleSheet("font-weight: bold;")
        btn_row.addWidget(self.btn_apply)
        animals_v.addLayout(btn_row)

        root.addWidget(self.gb_animals)

        # ----- Log -----
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(300)
        self.log_box.setPlaceholderText("Status messages will appear here…")
        root.addWidget(self.log_box)

        # Post-run hint (hidden until a run succeeds)
        self._hint_frame = QFrame()
        self._hint_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._hint_frame.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QHBoxLayout(self._hint_frame)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        hint_lbl = QLabel("✓ Drink masks applied. Review the updated PSDs in PSD Visualizer.")
        hint_lbl.setWordWrap(True)
        hint_layout.addWidget(hint_lbl, 1)
        btn_go_psd = QPushButton("→ PSD Visualizer")
        btn_go_psd.clicked.connect(lambda: self.navigate_to.emit("psd_review"))
        hint_layout.addWidget(btn_go_psd)
        self._hint_frame.setVisible(False)
        root.addWidget(self._hint_frame)

        # Styling
        self.gb_paths.setObjectName("pathsBox")
        self.gb_params.setObjectName("paramsBox")
        self.gb_animals.setObjectName("animalsBox")
        self.setStyleSheet("""
        QGroupBox#pathsBox, QGroupBox#paramsBox, QGroupBox#animalsBox { font: 550; }
        QGroupBox#pathsBox *, QGroupBox#paramsBox *, QGroupBox#animalsBox * { font: 400; }
        """)

    def _wire(self):
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_apply.clicked.connect(self._apply_clicked)

    # ------------- Data refresh -------------

    def _refresh(self):
        self._refresh_paths()
        self._refresh_params()
        self._refresh_animals()

    def _drink_masks_dir(self) -> Path:
        return self.project_root / "drink_masks"

    def _detect_offset_csv(self) -> Optional[Path]:
        d = self._drink_masks_dir()
        csvs = sorted(d.glob("*.csv")) if d.is_dir() else []
        return csvs[0] if csvs else None

    def _refresh_paths(self):
        d = self._drink_masks_dir()
        self.lbl_drink_dir.setText(str(d))
        if d.is_dir():
            n = sum(1 for _ in d.glob("*.npy"))
            if n:
                self._lbl_mask_count.setText(f"✓ {n} mask{'s' if n != 1 else ''}")
                self._lbl_mask_count.setStyleSheet("color: green;")
            else:
                self._lbl_mask_count.setText("No .npy files found")
                self._lbl_mask_count.setStyleSheet("color: orange;")
        else:
            self._lbl_mask_count.setText("Folder does not exist")
            self._lbl_mask_count.setStyleSheet("color: gray;")

        csv = self._detect_offset_csv()
        self.lbl_offset_csv.setText(str(csv.name) if csv else "None")

    def _refresh_params(self):
        from ebb_viewer.pipeline import psd_params
        params = psd_params.load(self.project_root)
        if params is None:
            for lbl in self._param_labels.values():
                lbl.setText("— (run Compute PSDs first)")
                lbl.setStyleSheet("color: gray;")
            return
        for key, lbl in self._param_labels.items():
            lbl.setStyleSheet("")
            if key == "channels":
                names = [CH_LABELS[i] for i in params.get("channels", []) if i < len(CH_LABELS)]
                lbl.setText(", ".join(names) if names else "—")
            else:
                lbl.setText(str(params.get(key, "—")))

    def _refresh_animals(self):
        from ebb_viewer.pipeline.manifest import Manifest
        try:
            manifest = Manifest.load(self.project_root)
            flagged = manifest.needs_drink_mask()
            ready = manifest.needs_drink_mask_rerun()
        except Exception:
            flagged = []
            ready = []

        if not flagged:
            self._lbl_status.setText("No animals pending drink mask rerun.")
            self._lbl_status.setStyleSheet("color: gray;")
            self._table.setVisible(False)
            self._table.setRowCount(0)
            self.btn_apply.setEnabled(False)
            self.btn_apply.setText("Apply Drink Masks")
            return

        ready_set = {(e.animal_id, c) for e, c in ready}
        n_ready = len(ready)
        n_missing = len(flagged) - n_ready

        parts = []
        if n_ready:
            parts.append(f"{n_ready} ready")
        if n_missing:
            parts.append(f"{n_missing} missing mask file")
        self._lbl_status.setText(f"{len(flagged)} animal(s) flagged — {', '.join(parts)}")
        self._lbl_status.setStyleSheet(
            "color: #8a4400;" if n_missing else "color: #1a5c1a;"
        )

        _AMBER = QColor("#fff3cd")
        self._table.setRowCount(0)
        for entry, combo in flagged:
            is_ready = (entry.animal_id, combo) in ready_set
            row = self._table.rowCount()
            self._table.insertRow(row)
            items = [
                QTableWidgetItem(f"{entry.animal_id} ({combo})"),
                QTableWidgetItem("needs_drink_mask"),
                QTableWidgetItem("✓ found" if is_ready else "✗ missing"),
            ]
            items[2].setForeground(QColor("#2a7a2a") if is_ready else QColor("#aa2222"))
            if not is_ready:
                for item in items:
                    item.setBackground(_AMBER)
            for col, item in enumerate(items):
                self._table.setItem(row, col, item)
        self._table.setVisible(True)

        has_params = (self.project_root / "psd" / "psd_params.json").exists()
        self.btn_apply.setEnabled(n_ready > 0 and has_params and not self._computing)
        if not has_params:
            self.btn_apply.setText("Apply Drink Masks (run Compute PSDs first)")
        elif n_ready:
            self.btn_apply.setText(f"Apply Drink Masks ({n_ready} ready)")
        else:
            self.btn_apply.setText("Apply Drink Masks (place .npy files to enable)")

    # ------------- Apply action -------------

    def _apply_clicked(self):
        from ebb_viewer.pipeline.manifest import Manifest
        from ebb_viewer.pipeline import psd_params

        params = psd_params.load(self.project_root)
        if params is None:
            QMessageBox.critical(self, "No PSD Params",
                                 "psd_params.json not found. Run Compute PSDs first.")
            return

        standard_folder = self.project_root / "standard"
        if not standard_folder.is_dir():
            QMessageBox.critical(self, "No Standard Folder",
                                 f"Expected: {standard_folder}")
            return

        manifest = Manifest.load(self.project_root)
        to_rerun = manifest.needs_drink_mask_rerun()
        if not to_rerun:
            return

        animal_combos = {entry.animal_id: combo for entry, combo in to_rerun}
        self._pending_animal_combos = animal_combos

        offset_path = self._detect_offset_csv()
        swd_dir = (self.project_root / "swd") if params.get("swd_mode") == "mask_out" else None

        self._computing = True
        self.btn_apply.setEnabled(False)
        self._log(f"Starting drink mask rerun for {len(animal_combos)} animal(s)…")
        if swd_dir:
            self._log(f"  SWD mask: {swd_dir}")

        self.drink_thread = QThread(self)
        self.drink_worker = DrinkMaskRerunWorker(
            psd_dir=self.project_root / "psd",
            eeg_dir=standard_folder,
            spindle_root=self.project_root / "spindle_outputs",
            drink_dir=self._drink_masks_dir(),
            animal_combos=animal_combos,
            offset_path=offset_path,
            params=params,
            swd_dir=swd_dir,
        )
        self.drink_worker.progress.connect(self._log)
        launch_worker(self.drink_thread, self.drink_worker,
                      on_finished=self._on_done,
                      on_error=self._on_error)

    def _on_done(self):
        self._computing = False
        from ebb_viewer.pipeline.manifest import Manifest
        manifest = Manifest.load(self.project_root)
        failed = []
        for animal_id, combo in self._pending_animal_combos.items():
            try:
                manifest.flag_psd(animal_id, combo, "drink_mask_applied")
            except Exception as e:
                failed.append(f"{animal_id} ({combo}): {e}")
        manifest.save()
        self._pending_animal_combos = {}
        if failed:
            msg = "\n".join(failed)
            self._log(f"WARNING: {len(failed)} flag(s) failed:\n{msg}")
            QMessageBox.warning(
                self, "Partial Failure",
                f"{len(failed)} animal(s) could not be flagged:\n\n{msg}",
            )
        self._log("Drink mask rerun complete. psds_drink.pkl and psds_channel_merged_drink.pkl updated.")
        self.manifest_changed.emit()
        self._hint_frame.setVisible(True)
        self._refresh()

    def _on_error(self, msg: str):
        self._computing = False
        self._pending_animal_combos = {}
        self._log(f"ERROR in drink mask rerun: {msg}")
        QMessageBox.critical(self, "Drink Mask Rerun Error", msg)
        self._refresh()

    def _log(self, msg: str):
        self.log_box.appendPlainText(msg)
        QApplication.processEvents()


class DrinkMaskRerunWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        psd_dir: Path,
        eeg_dir: Path,
        spindle_root: Path,
        drink_dir: Path,
        animal_combos: dict,
        offset_path,
        params: dict,
        swd_dir: Path = None,
        parent=None,
    ):
        super().__init__(parent)
        self.psd_dir = Path(psd_dir)
        self.eeg_dir = Path(eeg_dir)
        self.spindle_root = Path(spindle_root)
        self.drink_dir = Path(drink_dir)
        self.animal_combos = animal_combos   # {animal_id: ok_combo}
        self.offset_path = offset_path
        self.params = params
        self.swd_dir = Path(swd_dir) if swd_dir else None

    def run(self):
        from ebb.process.psd_compute import rerun_with_drink_masks
        try:
            rerun_with_drink_masks(
                psd_dir=self.psd_dir,
                eeg_dir=self.eeg_dir,
                spindle_root=self.spindle_root,
                drink_dir=self.drink_dir,
                animal_combos=self.animal_combos,
                offset_path=self.offset_path,
                swd_dir=self.swd_dir,
                ncores=None,
                **{k: v for k, v in self.params.items() if k not in _UI_ONLY_PARAM_KEYS},
            )
            self.progress.emit("  → psds_drink.pkl updated.")
            self.progress.emit("  → psds_channel_merged_drink.pkl regenerated.")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
