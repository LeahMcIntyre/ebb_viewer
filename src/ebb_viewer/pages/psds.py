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

        self._build_ui()
        self._wire()
        self._refresh_standard_folder()
        self._refresh_combo_table()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_standard_folder()
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

        # ----- Buttons -----
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
        QGroupBox#folderBox, QGroupBox#comboBox {
            font: 550;
        }
        QGroupBox#psdBox *, QGroupBox#spindleBox *, QGroupBox#maskBox *,
        QGroupBox#folderBox *, QGroupBox#comboBox * {
            font: 400;
        }
        """)

    # ------------- Wiring / Signals -------------

    def _wire(self):
        self.chk_all.toggled.connect(self._toggle_all_channels)
        self.btn_standard.clicked.connect(self._choose_standard_folder)
        self.btn_refresh_table.clicked.connect(self._refresh_combo_table)
        self.btn_psd.clicked.connect(self._run_clicked)
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

        self._computing = True
        self.btn_psd.setEnabled(False)
        self.btn_final.setEnabled(False)
        self._log(f"Starting PSD computation for {len(combos)} combo(s): {', '.join(combos)}")

        self.psd_thread = QThread(self)
        self.psd_worker = BatchEstimateWorker(
            eeg_dir=self.standard_folder,
            combo_pairs=pairs,
            params=params,
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

    def _on_psd_done(self):
        self._computing = False
        self._log("PSD computation finished.")
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
        parent=None,
    ):
        super().__init__(parent)
        self.eeg_dir = eeg_dir
        self.combo_pairs = combo_pairs
        self.params = params

    def run(self):
        from ebb.process.psd_compute import batch_estimate
        try:
            for spindle_dir, savepath in self.combo_pairs:
                self.progress.emit(f"Computing PSDs for combo: {spindle_dir.name}…")
                batch_estimate(
                    eeg_dir=self.eeg_dir,
                    state_dir=spindle_dir,
                    swd_dir=None,
                    drink_dir=None,
                    ncores=None,
                    savepath=savepath,
                    **self.params,
                )
                self.progress.emit(f"  → Saved: {savepath.name}")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
