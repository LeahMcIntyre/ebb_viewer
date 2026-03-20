from pathlib import Path
from typing import Optional, List, Tuple

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QSpinBox, QDoubleSpinBox, QVBoxLayout, QPushButton,
    QMessageBox, QLabel, QHBoxLayout, QGroupBox, QCheckBox, QGridLayout,
    QSizePolicy, QLineEdit, QApplication, QPlainTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog,
)


DEFAULT_FS = 250
DEFAULT_NOISE_THRESH = 0.5
DEFAULT_WINSIZE = 180
DEFAULT_RADIUS = 0.5
DEFAULT_NSTD = 5.0
CH_LABELS = ["LFC", "RSC", "LSC"]


class PSDPage(QWidget):

    manifest_changed = pyqtSignal()

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.standard_folder: Optional[Path] = None
        self._computing = False
        self._pending_drink_rerun: dict = {}

        self._build_ui()
        self._wire()
        self._refresh_standard_folder()
        self._refresh_drink_mask_info()
        self._refresh_combo_table()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_standard_folder()
        self._refresh_drink_mask_info()
        self._refresh_combo_table()

    # ---------------- UI ----------------

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ----- Group 1: Folder Selection -----
        self.folder_gb = QGroupBox("Folder Selection")
        self.folder_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        top_form = QFormLayout(self.folder_gb)

        standard_row = QHBoxLayout()
        self.btn_standard = QPushButton("Browse…")
        self.lbl_standard = QLineEdit("Looking for 'standard' in project root…")
        self.lbl_standard.setReadOnly(True)
        standard_row.addWidget(self.lbl_standard)
        standard_row.addWidget(self.btn_standard)
        top_form.addRow("Preprocessed EDF Folder:", standard_row)

        self.target_name_edit = QLineEdit()
        self.target_name_edit.setReadOnly(True)
        top_form.addRow("PSD Output Root:", self.target_name_edit)

        drink_dir_row = QHBoxLayout()
        self.lbl_drink_dir = QLineEdit("Checking…")
        self.lbl_drink_dir.setReadOnly(True)
        self._lbl_drink_count = QLabel("")
        self._lbl_drink_count.setMinimumWidth(110)
        drink_dir_row.addWidget(self.lbl_drink_dir)
        drink_dir_row.addWidget(self._lbl_drink_count)
        top_form.addRow("Drink Masks Folder:", drink_dir_row)

        self.lbl_offset_csv = QLineEdit("None")
        self.lbl_offset_csv.setReadOnly(True)
        self.lbl_offset_csv.setToolTip(
            "Optional CSV with columns 'Animal' and 'Offset' (seconds) for video-EEG time alignment"
        )
        top_form.addRow("Video Offset CSV:", self.lbl_offset_csv)

        root.addWidget(self.folder_gb)

        # ----- Group 2: Combo Table -----
        self.combo_gb = QGroupBox("Spindle Output Combos")
        combo_v = QVBoxLayout(self.combo_gb)

        btn_row = QHBoxLayout()
        self.btn_refresh_table = QPushButton("Refresh")
        btn_row.addWidget(self.btn_refresh_table)
        btn_row.addStretch(1)
        combo_v.addLayout(btn_row)

        self.combo_table = QTableWidget(0, 4)
        self.combo_table.setHorizontalHeaderLabels(["✓", "Combo", "CSVs", "PKL Status"])
        self.combo_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self.combo_table.setColumnWidth(0, 30)
        self.combo_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.combo_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self.combo_table.setColumnWidth(2, 60)
        self.combo_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.combo_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.combo_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.combo_table.verticalHeader().setVisible(False)
        combo_v.addWidget(self.combo_table)

        root.addWidget(self.combo_gb)

        # ----- Group 3: PSD Settings -----
        self.gb_psd = QGroupBox("PSD Settings")
        self.gb_psd.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        psd_v = QVBoxLayout(self.gb_psd)

        ch_hdr = QHBoxLayout()
        ch_hdr.addWidget(QLabel("Channels:"))
        ch_hdr.addStretch(1)
        self.chk_all = QCheckBox("Select all")
        self.chk_all.setChecked(True)
        ch_hdr.addWidget(self.chk_all)
        psd_v.addLayout(ch_hdr)

        self._channels_container = QWidget()
        self._channels_grid = QGridLayout(self._channels_container)
        self._channels_grid.setContentsMargins(0, 0, 0, 0)
        self._channels_grid.setHorizontalSpacing(12)
        self._channels_grid.setVerticalSpacing(4)
        psd_v.addWidget(self._channels_container)

        self._channel_boxes = []
        cols = 4
        for i, label in enumerate(CH_LABELS):
            cb = QCheckBox(label)
            cb.setChecked(True)
            self._channel_boxes.append(cb)
            r, c = divmod(i, cols)
            self._channels_grid.addWidget(cb, r, c)

        fs_form = QFormLayout()
        fs_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.spin_fs = QSpinBox()
        self.spin_fs.setRange(1, 100_000)
        self.spin_fs.setSuffix(" Hz")
        self.spin_fs.setValue(DEFAULT_FS)
        fs_form.addRow("Sampling freq:", self.spin_fs)
        psd_v.addLayout(fs_form)

        root.addWidget(self.gb_psd)

        # ----- Group 4: Spindle Noise Mask -----
        self.gb_spindle = QGroupBox("Spindle Noise Mask: Applied To All States")
        self.gb_spindle.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        spindle_form = QFormLayout()
        spindle_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.dspin_noise = QDoubleSpinBox()
        self.dspin_noise.setDecimals(2)
        self.dspin_noise.setRange(0.0, 1.0)
        self.dspin_noise.setValue(DEFAULT_NOISE_THRESH)

        spindle_form.addRow("Spindle Noise Threshold:", self.dspin_noise)
        self.gb_spindle.setLayout(spindle_form)
        root.addWidget(self.gb_spindle)

        # ----- Group 5: SD Mask -----
        self.gb_mask = QGroupBox("Standard Deviation Mask: Applied Only To Wake")
        self.gb_mask.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        mask_form = QFormLayout()
        mask_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.spin_window = QSpinBox()
        self.spin_window.setRange(1, 6000)
        self.spin_window.setSuffix(" s")
        self.spin_window.setValue(DEFAULT_WINSIZE)

        self.dspin_radius = QDoubleSpinBox()
        self.dspin_radius.setDecimals(1)
        self.dspin_radius.setRange(0.0, 60.0)
        self.dspin_radius.setSuffix(" s")
        self.dspin_radius.setValue(DEFAULT_RADIUS)

        self.dspin_z = QDoubleSpinBox()
        self.dspin_z.setDecimals(2)
        self.dspin_z.setRange(1.0, 20.0)
        self.dspin_z.setSuffix(" σ")
        self.dspin_z.setValue(DEFAULT_NSTD)

        mask_form.addRow("Window:", self.spin_window)
        mask_form.addRow("Radius:", self.dspin_radius)
        mask_form.addRow("Z-threshold:", self.dspin_z)
        self.gb_mask.setLayout(mask_form)
        root.addWidget(self.gb_mask)

        # ----- Main Action Buttons -----
        btn_row2 = QHBoxLayout()
        self.btn_psd = QPushButton("Compute PSDs")
        self.btn_psd.setEnabled(False)
        btn_row2.addWidget(self.btn_psd)

        self.btn_final = QPushButton("Build Final PKL")
        self.btn_final.setEnabled(False)
        self.btn_final.setToolTip(
            "Consolidate one entry per animal (from their ok combo) into psds_final.pkl"
        )
        btn_row2.addWidget(self.btn_final)
        root.addLayout(btn_row2)

        # ----- Drink Mask Rerun -----
        self.gb_drink_rerun = QGroupBox("Drink Mask Rerun")
        self.gb_drink_rerun.setObjectName("drinkRerunBox")
        drink_v = QVBoxLayout(self.gb_drink_rerun)

        self._lbl_drink_rerun_status = QLabel("No animals pending drink mask rerun.")
        self._lbl_drink_rerun_status.setStyleSheet("color: gray;")
        drink_v.addWidget(self._lbl_drink_rerun_status)

        self._drink_rerun_table = QTableWidget(0, 3)
        self._drink_rerun_table.setHorizontalHeaderLabels(["Animal (Combo)", "Status", "Mask File"])
        self._drink_rerun_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._drink_rerun_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed
        )
        self._drink_rerun_table.setColumnWidth(1, 100)
        self._drink_rerun_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self._drink_rerun_table.setColumnWidth(2, 110)
        self._drink_rerun_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._drink_rerun_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._drink_rerun_table.verticalHeader().setVisible(False)
        self._drink_rerun_table.setMaximumHeight(130)
        self._drink_rerun_table.setVisible(False)
        drink_v.addWidget(self._drink_rerun_table)

        self.btn_drink_mask = QPushButton("Apply Drink Masks")
        self.btn_drink_mask.setEnabled(False)
        drink_v.addWidget(self.btn_drink_mask, alignment=Qt.AlignmentFlag.AlignRight)
        root.addWidget(self.gb_drink_rerun)

        # ----- Log -----
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(300)
        self.log_box.setPlaceholderText("Status messages will appear here...")
        root.addWidget(self.log_box)

        # Styling
        self.folder_gb.setObjectName("folderBox")
        self.combo_gb.setObjectName("comboBox")
        self.gb_psd.setObjectName("psdBox")
        self.gb_spindle.setObjectName("spindleBox")
        self.gb_mask.setObjectName("maskBox")
        self.setStyleSheet("""
        QGroupBox#psdBox, QGroupBox#spindleBox, QGroupBox#maskBox,
        QGroupBox#folderBox, QGroupBox#comboBox, QGroupBox#drinkRerunBox {
            font: 550;
        }
        QGroupBox#psdBox *, QGroupBox#spindleBox *, QGroupBox#maskBox *,
        QGroupBox#folderBox *, QGroupBox#comboBox *, QGroupBox#drinkRerunBox * {
            font: 400;
        }
        """)

    # ------------- Wiring / Signals -------------

    def _wire(self):
        self.chk_all.toggled.connect(self._toggle_all_channels)
        self.btn_standard.clicked.connect(self._choose_standard_folder)
        self.btn_refresh_table.clicked.connect(self._refresh_combo_table)
        self.btn_psd.clicked.connect(self._run_clicked)
        self.btn_drink_mask.clicked.connect(self._run_drink_mask_clicked)
        self.btn_final.clicked.connect(self._build_final_pkl)
        self.combo_table.itemChanged.connect(lambda _: self._validate())

    # ------------- Path / table refresh -------------

    def _refresh_standard_folder(self):
        cand_std = self.project_root / "standard"
        if cand_std.exists() and cand_std.is_dir():
            self.standard_folder = cand_std
            self.lbl_standard.setText(str(cand_std))
        else:
            self.standard_folder = None
            self.lbl_standard.setText(
                f"No 'standard' folder found under {self.project_root}. "
                "Run preprocessing first or browse manually."
            )
        self.target_name_edit.setText(str(self.project_root / "psd"))

    def _drink_masks_dir(self) -> Path:
        return self.project_root / "drink_masks"

    def _detect_offset_csv(self) -> Optional[Path]:
        """Return the first .csv found in drink_masks/, or None."""
        d = self._drink_masks_dir()
        csvs = sorted(d.glob("*.csv")) if d.is_dir() else []
        return csvs[0] if csvs else None

    def _refresh_drink_mask_info(self):
        d = self._drink_masks_dir()
        if d.is_dir():
            n = len(list(d.glob("*.npy")))
            self.lbl_drink_dir.setText(str(d))
            if n:
                self._lbl_drink_count.setText(f"✓ {n} mask{'s' if n != 1 else ''}")
                self._lbl_drink_count.setStyleSheet("color: green;")
            else:
                self._lbl_drink_count.setText("! no .npy files")
                self._lbl_drink_count.setStyleSheet("color: orange;")
        else:
            self.lbl_drink_dir.setText("Not found — place .npy files in project_root/drink_masks/")
            self._lbl_drink_count.setText("")
            self._lbl_drink_count.setStyleSheet("")

        csv = self._detect_offset_csv()
        self.lbl_offset_csv.setText(str(csv.name) if csv else "None")

    def _refresh_combo_table(self):
        spindle_root = self.project_root / "spindle_outputs"
        psd_dir = self.project_root / "psd"

        self.combo_table.blockSignals(True)
        self.combo_table.setRowCount(0)

        if spindle_root.is_dir():
            for combo_dir in sorted(p for p in spindle_root.iterdir() if p.is_dir()):
                combo = combo_dir.name
                csv_count = len(list(combo_dir.glob("*.csv")))
                pkl_path = psd_dir / f"psds_{combo}.pkl"
                pkl_status = "✓ exists" if pkl_path.exists() else "missing"

                row = self.combo_table.rowCount()
                self.combo_table.insertRow(row)

                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                chk_item.setCheckState(
                    Qt.CheckState.Checked if csv_count > 0 else Qt.CheckState.Unchecked
                )
                self.combo_table.setItem(row, 0, chk_item)
                self.combo_table.setItem(row, 1, QTableWidgetItem(combo))
                self.combo_table.setItem(row, 2, QTableWidgetItem(str(csv_count)))

                status_item = QTableWidgetItem(pkl_status)
                if pkl_status.startswith("✓"):
                    status_item.setForeground(QColor("#2a7a2a"))
                self.combo_table.setItem(row, 3, status_item)

        self.combo_table.blockSignals(False)
        self._validate()

    def _checked_combos(self) -> List[str]:
        result = []
        for row in range(self.combo_table.rowCount()):
            chk = self.combo_table.item(row, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                combo_item = self.combo_table.item(row, 1)
                if combo_item:
                    result.append(combo_item.text())
        return result

    # ------------- Actions -------------

    def _run_clicked(self):
        if self.standard_folder is None or not self.standard_folder.exists():
            QMessageBox.critical(
                self,
                "No Standard Folder",
                "Standard EDF folder not set or does not exist.\n\n"
                f"Expected: {self.project_root / 'standard'}",
            )
            return

        combos = self._checked_combos()
        if not combos:
            QMessageBox.warning(
                self, "No Combos Selected",
                "Please check at least one combo in the table."
            )
            return

        spindle_root = self.project_root / "spindle_outputs"
        psd_dir = self.project_root / "psd"
        psd_dir.mkdir(parents=True, exist_ok=True)

        pairs: List[Tuple[Path, Path]] = [
            (spindle_root / combo, psd_dir / f"psds_{combo}.pkl")
            for combo in combos
        ]

        params = {
            "fs": int(self.spin_fs.value()),
            "channels": self.selected_channels(),
            "winsize": int(self.spin_window.value()),
            "radius": float(self.dspin_radius.value()),
            "nstd": float(self.dspin_z.value()),
            "noise_thresh": float(self.dspin_noise.value()),
        }

        drink_dir = self._drink_masks_dir() if self._drink_masks_dir().is_dir() else None
        offset_path = self._detect_offset_csv()

        self._computing = True
        self.btn_psd.setEnabled(False)
        self.btn_drink_mask.setEnabled(False)
        self.btn_final.setEnabled(False)
        self._log(f"Starting PSD computation for {len(combos)} combo(s): {', '.join(combos)}")
        if drink_dir:
            self._log(f"  Drink masks folder: {drink_dir}")

        self.psd_thread = QThread(self)
        self.psd_worker = BatchEstimateWorker(
            eeg_dir=self.standard_folder,
            combo_pairs=pairs,
            params=params,
            drink_dir=drink_dir,
            offset_path=offset_path,
        )
        self.psd_worker.moveToThread(self.psd_thread)
        self.psd_thread.started.connect(self.psd_worker.run)
        self.psd_worker.progress.connect(self._log)
        self.psd_worker.finished.connect(self._on_psd_done)
        self.psd_worker.error.connect(self._on_psd_error)
        self.psd_worker.finished.connect(self.psd_thread.quit)
        self.psd_worker.finished.connect(self.psd_worker.deleteLater)
        self.psd_thread.finished.connect(self.psd_thread.deleteLater)
        self.psd_thread.start()

    def _build_final_pkl(self):
        from ebb.process.psd_compute import build_final_pkl
        from ebb_viewer.pipeline.manifest import Manifest
        try:
            manifest = Manifest.load(self.project_root)
            out = build_final_pkl(self.project_root, manifest)
            self._log(f"Built final PKL: {out}")
            self.manifest_changed.emit()
            self._refresh_combo_table()
        except Exception as e:
            self._log(f"ERROR building final PKL: {e}")
            QMessageBox.critical(self, "Build Final PKL Error", str(e))

    # ---------- Channels API ----------

    def selected_channels(self):
        return [i for i, cb in enumerate(self._channel_boxes) if cb.isChecked()]

    def channel_labels(self):
        return [cb.text() for cb in self._channel_boxes]

    # ---------- Internals ----------

    def _toggle_all_channels(self, checked):
        for cb in self._channel_boxes:
            cb.setChecked(checked)

    def _choose_standard_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Standard EDF Folder", str(self.project_root)
        )
        if not folder:
            return
        self.standard_folder = Path(folder).expanduser().resolve()
        self.lbl_standard.setText(str(self.standard_folder))
        self._validate()

    def _validate(self):
        if self._computing:
            return
        has_standard = (
            self.standard_folder is not None and self.standard_folder.exists()
        )
        has_checked = bool(self._checked_combos())
        self.btn_psd.setEnabled(has_standard and has_checked)

        psd_dir = self.project_root / "psd"
        has_pkl = (
            psd_dir.is_dir()
            and any(p for p in psd_dir.glob("psds_*.pkl") if p.stem != "psds_final")
        )
        self.btn_final.setEnabled(has_pkl)

        self._refresh_drink_rerun_table()

    def _refresh_drink_rerun_table(self):
        from ebb_viewer.pipeline.manifest import Manifest
        try:
            manifest = Manifest.load(self.project_root)
            flagged = manifest.needs_drink_mask()
            ready = manifest.needs_drink_mask_rerun()
        except Exception:
            flagged = []
            ready = []

        if not flagged:
            self._lbl_drink_rerun_status.setText("No animals pending drink mask rerun.")
            self._lbl_drink_rerun_status.setStyleSheet("color: gray;")
            self._drink_rerun_table.setVisible(False)
            self._drink_rerun_table.setRowCount(0)
            self.btn_drink_mask.setEnabled(False)
            self.btn_drink_mask.setText("Apply Drink Masks")
            return

        ready_set = {(e.animal_id, c) for e, c in ready}
        n_ready = len(ready)
        n_missing = len(flagged) - n_ready

        parts = []
        if n_ready:
            parts.append(f"{n_ready} ready")
        if n_missing:
            parts.append(f"{n_missing} missing mask file")
        self._lbl_drink_rerun_status.setText(
            f"{len(flagged)} animal(s) flagged — {', '.join(parts)}"
        )
        self._lbl_drink_rerun_status.setStyleSheet(
            "color: #8a4400;" if n_missing else "color: #1a5c1a;"
        )

        self._drink_rerun_table.blockSignals(True)
        self._drink_rerun_table.setRowCount(0)
        for entry, combo in flagged:
            is_ready = (entry.animal_id, combo) in ready_set
            row = self._drink_rerun_table.rowCount()
            self._drink_rerun_table.insertRow(row)
            self._drink_rerun_table.setItem(row, 0, QTableWidgetItem(f"{entry.animal_id} ({combo})"))
            self._drink_rerun_table.setItem(row, 1, QTableWidgetItem("⚠ needs rerun"))
            mask_item = QTableWidgetItem("✓ found" if is_ready else "✗ missing")
            mask_item.setForeground(QColor("#2a7a2a") if is_ready else QColor("#aa2222"))
            self._drink_rerun_table.setItem(row, 2, mask_item)
        self._drink_rerun_table.blockSignals(False)
        self._drink_rerun_table.setVisible(True)

        self.btn_drink_mask.setEnabled(n_ready > 0 and not self._computing)
        if n_ready:
            self.btn_drink_mask.setText(f"Apply Drink Masks ({n_ready} ready)")
        else:
            self.btn_drink_mask.setText("Apply Drink Masks (place .npy files to enable)")

    def _run_drink_mask_clicked(self):
        from ebb_viewer.pipeline.manifest import Manifest
        manifest = Manifest.load(self.project_root)
        to_rerun = manifest.needs_drink_mask_rerun()
        if not to_rerun:
            return

        # {animal_id: ok_combo} — combo comes from manifest (validated against psds_final.pkl
        # inside rerun_with_drink_masks before any computation starts)
        animal_combos = {entry.animal_id: combo for entry, combo in to_rerun}

        offset_path = self._detect_offset_csv()
        params = {
            "fs":           int(self.spin_fs.value()),
            "winsize":      int(self.spin_window.value()),
            "radius":       float(self.dspin_radius.value()),
            "nstd":         float(self.dspin_z.value()),
            "noise_thresh": float(self.dspin_noise.value()),
        }

        self._computing = True
        self._pending_drink_rerun = animal_combos
        self.btn_psd.setEnabled(False)
        self.btn_final.setEnabled(False)
        self.btn_drink_mask.setEnabled(False)
        self._log(f"Starting drink mask rerun for {len(animal_combos)} animal(s)…")

        self.drink_thread = QThread(self)
        self.drink_worker = DrinkMaskRerunWorker(
            psd_dir=self.project_root / "psd",
            eeg_dir=self.standard_folder,
            spindle_root=self.project_root / "spindle_outputs",
            drink_dir=self._drink_masks_dir(),
            animal_combos=animal_combos,
            offset_path=offset_path,
            params=params,
        )
        self.drink_worker.moveToThread(self.drink_thread)
        self.drink_thread.started.connect(self.drink_worker.run)
        self.drink_worker.progress.connect(self._log)
        self.drink_worker.finished.connect(self._on_drink_mask_done)
        self.drink_worker.error.connect(self._on_drink_mask_error)
        self.drink_worker.finished.connect(self.drink_thread.quit)
        self.drink_worker.finished.connect(self.drink_worker.deleteLater)
        self.drink_thread.finished.connect(self.drink_thread.deleteLater)
        self.drink_thread.start()

    def _on_drink_mask_done(self):
        self._computing = False
        from ebb_viewer.pipeline.manifest import Manifest
        manifest = Manifest.load(self.project_root)
        for animal_id, combo in self._pending_drink_rerun.items():
            try:
                manifest.flag_psd(animal_id, combo, "drink_mask_applied")
            except Exception:
                pass
        manifest.save()
        self._pending_drink_rerun = {}
        self._log("Drink mask rerun complete. psds_drink.pkl and psds_final_drink.pkl updated.")
        self.manifest_changed.emit()
        self._refresh_combo_table()

    def _on_drink_mask_error(self, msg: str):
        self._computing = False
        self._pending_drink_rerun = {}
        self._log(f"ERROR in drink mask rerun: {msg}")
        QMessageBox.critical(self, "Drink Mask Rerun Error", msg)
        self._validate()

    def _on_psd_done(self):
        self._computing = False
        self._log("PSD computation finished.")
        self._refresh_drink_mask_info()
        self._refresh_combo_table()

    def _on_psd_error(self, msg: str):
        self._computing = False
        self._log(f"ERROR in batch_estimate: {msg}")
        QMessageBox.critical(self, "PSD Error", msg)
        self._validate()

    def _log(self, msg: str):
        self.log_box.appendPlainText(msg)
        QApplication.processEvents()


class BatchEstimateWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        eeg_dir: Path,
        combo_pairs: List[Tuple[Path, Path]],
        params: dict,
        drink_dir=None,
        offset_path=None,
        parent=None,
    ):
        super().__init__(parent)
        self.eeg_dir = eeg_dir
        self.combo_pairs = combo_pairs
        self.params = params
        self.drink_dir = drink_dir
        self.offset_path = offset_path

    def run(self):
        from ebb.process.psd_compute import batch_estimate
        try:
            if self.drink_dir and self.drink_dir.is_dir():
                drink_animals = {
                    p.stem.split("_")[0] for p in sorted(self.drink_dir.glob("*.npy"))
                }
                edf_animals = {
                    p.stem.split("_")[0] for p in sorted(self.eeg_dir.glob("*PROCESSED.edf"))
                }
                with_mask = sorted(edf_animals & drink_animals)
                without_mask = sorted(edf_animals - drink_animals)
                self.progress.emit(
                    f"  Drink masks: {len(with_mask)}/{len(edf_animals)} animals covered"
                )
                if with_mask:
                    self.progress.emit(f"    With mask:  {', '.join(with_mask)}")
                if without_mask:
                    self.progress.emit(f"    No mask:    {', '.join(without_mask)}")

            for spindle_dir, savepath in self.combo_pairs:
                self.progress.emit(f"Computing PSDs for combo: {spindle_dir.name}…")
                batch_estimate(
                    eeg_dir=self.eeg_dir,
                    state_dir=spindle_dir,
                    swd_dir=None,
                    drink_dir=self.drink_dir,
                    ncores=None,
                    savepath=savepath,
                    offset_path=self.offset_path,
                    **self.params,
                )
                self.progress.emit(f"  → Saved: {savepath.name}")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


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
                ncores=None,
                **self.params,
            )
            self.progress.emit("  → psds_drink.pkl updated.")
            self.progress.emit("  → psds_final_drink.pkl regenerated.")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
