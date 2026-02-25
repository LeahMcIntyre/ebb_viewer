from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QSpinBox, QDoubleSpinBox, QVBoxLayout, QPushButton,
    QMessageBox, QLabel, QHBoxLayout, QGroupBox, QCheckBox, QGridLayout, QFileDialog,
    QSizePolicy, QLineEdit, QApplication, QPlainTextEdit
)



DEFAULT_FS = 250
DEFAULT_NOISE_THRESH = 0.5
DEFAULT_WINSIZE = 180
DEFAULT_RADIUS = 0.5
DEFAULT_NSTD = 5.0
CH_LABELS = ["LFC", "RSC", "LSC"]


class PSDPage(QWidget):

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)

        # These will become Path or None
        self.standard_folder: Optional[Path] = None
        self.spindle_folder: Optional[Path] = None
        self.swd_folder: Optional[Path] = None

        self._build_ui()
        self._wire()
        self._refresh_default_paths()
        self._validate()

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)

        # ----- Group 1: Folder Selection -----
        self.folder_gb = QGroupBox("Folder Selection")
        self.folder_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        top_form = QFormLayout(self.folder_gb)

        # STANDARD FOLDER (preprocessed EDFs)
        standard_row = QHBoxLayout()
        self.btn_standard = QPushButton("Browse…")
        self.lbl_standard = QLineEdit("Looking for 'standard' in project root…")
        self.lbl_standard.setReadOnly(True)
        standard_row.addWidget(self.lbl_standard)
        standard_row.addWidget(self.btn_standard)
        top_form.addRow("Preprocessed EDF Folder:", standard_row)

        # SPINDLE FOLDER (where spindle outputs live — root)
        spindle_row = QHBoxLayout()
        self.btn_spindle = QPushButton("Browse…")
        self.lbl_spindle = QLineEdit("Looking for 'spindle_outputs' in project root…")
        self.lbl_spindle.setReadOnly(True)
        spindle_row.addWidget(self.lbl_spindle)
        spindle_row.addWidget(self.btn_spindle)
        top_form.addRow("Spindle Output Root:", spindle_row)

        # SWD Folder
        swd_row = QHBoxLayout()
        self.btn_swd = QPushButton("Browse…")
        self.lbl_swd = QLineEdit("No SWD folder selected")
        self.lbl_swd.setReadOnly(True)
        swd_row.addWidget(self.lbl_swd)
        swd_row.addWidget(self.btn_swd)
        top_form.addRow("SWD .mat Folder:", swd_row)

        # Target PSD root (read-only: project_root / 'psd')
        self.target_name_edit = QLineEdit()
        self.target_name_edit.setReadOnly(True)
        self.target_name_edit.setStyleSheet(
            "QLineEdit { padding-top: 0px; padding-bottom: 0px; }"
        )
        top_form.addRow("PSD Root:", self.target_name_edit)

        root.addWidget(self.folder_gb)

        # --- Group 2: PSD Settings (Channels + Fs) ---
        self.gb_psd = QGroupBox("PSD Settings")
        self.gb_psd.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        psd_v = QVBoxLayout(self.gb_psd)

        # Channels area
        ch_hdr = QHBoxLayout()
        ch_hdr.addWidget(QLabel("Channels:"))
        ch_hdr.addStretch(1)
        self.chk_all = QCheckBox("Select all")
        self.chk_all.setChecked(True)  # default all selected
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

        # Sampling frequency
        fs_form = QFormLayout()
        fs_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.spin_fs = QSpinBox()
        self.spin_fs.setRange(1, 100_000)
        self.spin_fs.setSuffix(" Hz")
        self.spin_fs.setValue(DEFAULT_FS)
        fs_form.addRow("Sampling freq:", self.spin_fs)
        psd_v.addLayout(fs_form)

        root.addWidget(self.gb_psd)

        # --- Group 3: Artifact Mask ---
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

        # --- Group 3: Artifact Mask ---
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

        # --- Compute button ---
        self.btn_psd = QPushButton("Compute PSDs")
        self.btn_psd.setEnabled(False)
        root.addWidget(self.btn_psd)


        # Log Box 
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(300)
        self.log_box.setPlaceholderText("Status messages will appear here...")
        root.addWidget(self.log_box)

        # Styling
        self.folder_gb.setObjectName("folderBox")
        self.gb_psd.setObjectName("psdBox")
        self.gb_spindle.setObjectName("spindleBox")
        self.gb_mask.setObjectName("maskBox")

        self.setStyleSheet("""
        QGroupBox#psdBox, QGroupBox#spindleBox, QGroupBox#maskBox, QGroupBox#folderBox {
            font: 550;
        }
        QGroupBox#psdBox *, QGroupBox#spindleBox *, QGroupBox#maskBox *, QGroupBox#folderBox * {
            font: 400;
        }
        """)

    # ------------- Wiring / Signals -------------
    def _wire(self):
        self.chk_all.toggled.connect(self._toggle_all_channels)
        self.btn_standard.clicked.connect(self._choose_standard_folder)
        self.btn_spindle.clicked.connect(self._choose_spindle_folder)
        self.btn_swd.clicked.connect(self._choose_swd_folder)
        self.btn_psd.clicked.connect(self._run_clicked)

    # ------------- Path defaults -------------
    def _refresh_default_paths(self):
        """
        Derive standard, spindle_outputs, and PSD root from project_root.
        SWD folder is still user-selected but we can default-probe a common name.
        """
        # Standard EDFs
        cand_std = self.project_root / "standard"
        if cand_std.exists() and cand_std.is_dir():
            self.standard_folder = cand_std
            self.lbl_standard.setText(str(cand_std))
        else:
            self.standard_folder = None
            self.lbl_standard.setText(
                f"No 'standard' folder found under:\n{self.project_root}\n"
                "Run preprocessing first or browse manually."
            )

        # Spindle outputs root
        spindle_root = self.project_root / "spindle_outputs" 
        if spindle_root.exists() and spindle_root.is_dir():
            subdirs = sorted(p for p in spindle_root.iterdir() if p.is_dir())
            if (spindle_root / "LFC_RSC") in subdirs:
                cand_spindle = spindle_root / "LFC_RSC"

                self.spindle_folder = cand_spindle
                self.lbl_spindle.setText(str(cand_spindle))

            elif len(subdirs) > 0:
                cand_spindle = subdirs[0]
                self.spindle_folder = cand_spindle
                self.lbl_spindle.setText(str(cand_spindle))

            else:
                self.spindle_folder = None
                self.lbl_spindle.setText(
                    f"No  folders found under:\n{spindle_root}\n"
                )
                
        else:
            self.spindle_folder = None
            self.lbl_spindle.setText(
                f"No 'spindle_outputs' folder found under:\n{self.project_root}\n"
                "This is optional unless your pipeline expects it."
            )

        if self.swd_folder is None:
            self.lbl_swd.setText("No SWD folder selected")

        # PSD root: always project_root / "psd"
        psd_root = self.project_root / "psd" 
        file_name = f'{self.spindle_folder.stem}.pkl' if self.spindle_folder is not None else "psds.pkl"
        self.target_name_edit.setText(str(psd_root / file_name))

    # ------------- Actions -------------
    def _run_clicked(self):
        # Basic path checks
        if self.standard_folder is None or not self.standard_folder.exists():
            QMessageBox.critical(
                self,
                "No Standard Folder",
                "Standard EDF folder not set or does not exist.\n\n"
                "Expected something like:\n"
                f"{self.project_root / 'standard'}",
            )
            return
        
        """
        if self.swd_folder is None or not self.swd_folder.exists():
            QMessageBox.critical(
                self,
                "No SWD .mat Folder",
                "SWD folder not set or does not exist.\n"
                "Please browse to the folder containing SWD .mat files.",
            )
            return
        """

        if self.spindle_folder is None or not self.spindle_folder.exists():
             QMessageBox.critical(
                 self,
                 "No Spindle Output",
                 "Spindle outputs is not set or does not exist.",
             )
             return

        # PSD root from target line
        psd_root = Path(self.target_name_edit.text().strip() or
                        (self.project_root / "psd"))
        psd_root.mkdir(parents=True, exist_ok=True)
        self.savepath = psd_root / f'psds_{self.spindle_folder.stem}.pkl'

        self.params = {
            "fs": int(self.spin_fs.value()),
            "channels": self.selected_channels(),
            "winsize": int(self.spin_window.value()),
            "radius": float(self.dspin_radius.value()),
            "nstd": float(self.dspin_z.value()),
            "noise_thresh": float(self.dspin_noise.value()),
        }

        # disable buttons while running
        self.btn_psd.setEnabled(False)
        self._log("Starting PSD batch estimate ")

        # create thread + worker
        self.psd_thread = QThread(self)
        self.psd_worker = BatchEstimateWorker(
            eeg_dir=self.standard_folder,
            state_dir=self.spindle_folder,
            swd_dir=self.swd_folder,
            drink_dir=None,
            ncores=None,       
            savepath=self.savepath,
            params=self.params,
        )

        self.psd_worker.moveToThread(self.psd_thread)

        # when thread starts, run worker
        self.psd_thread.started.connect(self.psd_worker.run)

        # hook signals back
        self.psd_worker.finished.connect(self._on_psd_done)
        self.psd_worker.error.connect(self._on_psd_error)

        # cleanup
        self.psd_worker.finished.connect(self.psd_thread.quit)
        self.psd_worker.finished.connect(self.psd_worker.deleteLater)
        self.psd_thread.finished.connect(self.psd_thread.deleteLater)

        self.psd_thread.start()

        
    # ---------- Channels API ----------        
    def selected_channels(self):
        """Return selected channels as indices into the current labels."""
        return [i for i, cb in enumerate(self._channel_boxes) if cb.isChecked()]

    def channel_labels(self):
        return [cb.text() for cb in self._channel_boxes]

    # ---------- Internals ----------
    def _toggle_all_channels(self, checked):
        for cb in self._channel_boxes:
            cb.setChecked(checked)

    def _choose_standard_folder(self):
        parent_dir = str(self.project_root)
        folder = QFileDialog.getExistingDirectory(
            self, "Select Standard EDF Folder", parent_dir
        )
        if not folder:
            return
        folder = Path(folder).expanduser().resolve()
        self.standard_folder = folder
        self.lbl_standard.setText(str(folder))
        self._validate()

    def _choose_spindle_folder(self):
        parent_dir = str(self.project_root/"spindle_outputs")
        folder = QFileDialog.getExistingDirectory(
            self, "Select Spindle Outputs Root", parent_dir
        )
        if not folder:
            return
        folder = Path(folder).expanduser().resolve()
        self.spindle_folder = folder
        self.lbl_spindle.setText(str(folder))
        self._validate()

    def _choose_swd_folder(self):
        parent_dir = str(self.project_root)
        folder = QFileDialog.getExistingDirectory(
            self, "Select SWD .mat Folder", parent_dir
        )
        if not folder:
            return
        folder = Path(folder).expanduser().resolve()
        self.swd_folder = folder
        self.lbl_swd.setText(str(folder))
        self._validate()

    def _validate(self):
        run_enabled = (
            self.standard_folder is not None
            and self.standard_folder.exists()
            and self.spindle_folder is not None
            and self.spindle_folder.exists()
        )
        self.btn_psd.setEnabled(run_enabled)

    def _on_psd_done(self):
        self._log(f"PSD batch_estimate finished. Saved to {self.savepath}.")
        self.btn_psd.setEnabled(True)
        # if you need to refresh UI from saved files, do it here

    def _on_psd_error(self, msg: str):
        self._log(f"ERROR in batch_estimate: {msg}")
        QMessageBox.critical(self, "PSD Error", msg)
        self.btn_psd.setEnabled(True)

    def _log(self, msg: str):
        self.log_box.appendPlainText(msg)
        QApplication.processEvents()



class BatchEstimateWorker(QObject):
    finished = pyqtSignal()        # or pass some results if you have them
    error = pyqtSignal(str)

    def __init__(self, eeg_dir, state_dir, swd_dir, drink_dir, ncores, savepath, params, parent=None):
        super().__init__(parent)
        self.eeg_dir = eeg_dir
        self.state_dir = state_dir
        self.swd_dir = swd_dir
        self.drink_dir = drink_dir
        self.ncores = ncores
        self.savepath = savepath
        self.params = params

    def run(self):
        from ebb.process.psd_compute import batch_estimate
        try:
            batch_estimate(
                eeg_dir=self.eeg_dir,
                state_dir=self.state_dir,
                swd_dir=self.swd_dir,
                drink_dir=self.drink_dir,
                ncores=self.ncores,
                savepath=self.savepath,
                **self.params,
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))