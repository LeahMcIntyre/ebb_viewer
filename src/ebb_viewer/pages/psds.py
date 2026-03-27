from pathlib import Path
from typing import Optional, List, Tuple
import dataclasses
import pickle

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from ebb_viewer.widgets.worker_helpers import launch_worker
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QSpinBox, QDoubleSpinBox, QVBoxLayout, QPushButton,
    QMessageBox, QLabel, QHBoxLayout, QGroupBox, QCheckBox, QGridLayout,
    QSizePolicy, QLineEdit, QApplication, QPlainTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QFrame, QButtonGroup, QRadioButton,
)


DEFAULT_FS = 250
DEFAULT_NOISE_THRESH = 0.5
DEFAULT_WINSIZE = 180
DEFAULT_RADIUS = 0.5
DEFAULT_NSTD = 5.0
CH_LABELS = ["LFC", "RSC", "LSC"]


class PSDPage(QWidget):

    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.standard_folder: Optional[Path] = None
        self._computing = False

        self._build_ui()
        self._wire()
        self._refresh_standard_folder()
        self._refresh_combo_table()
        self._refresh_swd_status()
        self._load_saved_params()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_standard_folder()
        self._refresh_combo_table()
        self._refresh_swd_status()

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

        # ----- Group 6: SWD Masks -----
        self.gb_swd = QGroupBox("SWD Masks")
        self.gb_swd.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        swd_v = QVBoxLayout(self.gb_swd)

        self._swd_btn_group = QButtonGroup(self)
        self._radio_swd_none = QRadioButton("No SWD mask")
        self._radio_swd_none.setChecked(True)
        self._radio_swd_mask = QRadioButton("Mask out SWDs")
        self._swd_btn_group.addButton(self._radio_swd_none, 0)
        self._swd_btn_group.addButton(self._radio_swd_mask, 1)
        swd_v.addWidget(self._radio_swd_none)
        swd_v.addWidget(self._radio_swd_mask)

        self._lbl_swd_status = QLabel("")
        self._lbl_swd_status.setStyleSheet("font-size: 11px; padding-left: 4px;")
        swd_v.addWidget(self._lbl_swd_status)

        root.addWidget(self.gb_swd)

        # ----- Main Action Buttons (Step 1 → Step 2) -----
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(8)

        col1 = QVBoxLayout()
        col1.setSpacing(2)
        lbl_step1 = QLabel("Step 1")
        lbl_step1.setStyleSheet("color: #888; font-size: 10px;")
        self.btn_psd = QPushButton("Compute PSDs")
        self.btn_psd.setEnabled(False)
        col1.addWidget(lbl_step1)
        col1.addWidget(self.btn_psd)
        btn_row2.addLayout(col1)

        arrow_lbl = QLabel("→")
        arrow_lbl.setStyleSheet("color: #aaa; font-size: 16px;")
        arrow_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_row2.addWidget(arrow_lbl)

        col2 = QVBoxLayout()
        col2.setSpacing(2)
        lbl_step2 = QLabel("Step 2")
        lbl_step2.setStyleSheet("color: #888; font-size: 10px;")
        self.btn_final = QPushButton("Build Channel Merged PKL")
        self.btn_final.setEnabled(False)
        self.btn_final.setToolTip(
            "Consolidate one entry per animal (from their ok combo) into psds_channel_merged.pkl"
        )
        col2.addWidget(lbl_step2)
        col2.addWidget(self.btn_final)
        btn_row2.addLayout(col2)

        btn_row2.addStretch(1)
        root.addLayout(btn_row2)

        # ----- Log -----
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(300)
        self.log_box.setPlaceholderText("Status messages will appear here...")
        root.addWidget(self.log_box)

        # Hint frame — updated dynamically after each step
        self._hint_frame = QFrame()
        self._hint_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._hint_frame.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QHBoxLayout(self._hint_frame)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        self._hint_lbl = QLabel()
        hint_layout.addWidget(self._hint_lbl, 1)
        self._hint_btn_viz = QPushButton("→ PSD Visualizer")
        self._hint_btn_viz.clicked.connect(lambda: self.navigate_to.emit("psd_review"))
        self._hint_btn_viz.setVisible(False)
        hint_layout.addWidget(self._hint_btn_viz)
        self._hint_frame.setVisible(False)
        root.addWidget(self._hint_frame)

        # Styling
        self.folder_gb.setObjectName("folderBox")
        self.combo_gb.setObjectName("comboBox")
        self.gb_psd.setObjectName("psdBox")
        self.gb_spindle.setObjectName("spindleBox")
        self.gb_mask.setObjectName("maskBox")
        self.gb_swd.setObjectName("swdBox")
        self.setStyleSheet("""
        QGroupBox#psdBox, QGroupBox#spindleBox, QGroupBox#maskBox,
        QGroupBox#folderBox, QGroupBox#comboBox, QGroupBox#swdBox {
            font: 550;
        }
        QGroupBox#psdBox *, QGroupBox#spindleBox *, QGroupBox#maskBox *,
        QGroupBox#folderBox *, QGroupBox#comboBox *, QGroupBox#swdBox * {
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
        self._swd_btn_group.buttonToggled.connect(lambda *_: self._validate())

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


    def _refresh_swd_status(self):
        swd_dir = self.project_root / "swd"
        if not swd_dir.is_dir():
            self._lbl_swd_status.setText("swd/ not found in project root")
            self._lbl_swd_status.setStyleSheet("font-size: 11px; padding-left: 4px; color: #888;")
            self._radio_swd_mask.setEnabled(False)
        else:
            mat_count = sum(1 for _ in swd_dir.glob("*.mat"))
            if mat_count == 0:
                self._lbl_swd_status.setText("swd/ found — no .mat files")
                self._lbl_swd_status.setStyleSheet("font-size: 11px; padding-left: 4px; color: #c77800;")
                self._radio_swd_mask.setEnabled(False)
            else:
                self._lbl_swd_status.setText(
                    f"✓ {mat_count} .mat {'file' if mat_count == 1 else 'files'} in swd/"
                )
                self._lbl_swd_status.setStyleSheet("font-size: 11px; padding-left: 4px; color: #2a7a2a;")
                self._radio_swd_mask.setEnabled(True)
        # If mask mode was selected but is no longer available, fall back to none
        if not self._radio_swd_mask.isEnabled() and self._radio_swd_mask.isChecked():
            self._radio_swd_none.setChecked(True)
        self._validate()

    def _load_saved_params(self):
        from ebb_viewer.pipeline import psd_params
        params = psd_params.load(self.project_root)
        if params is None:
            return
        if "fs" in params:
            self.spin_fs.setValue(params["fs"])
        if "winsize" in params:
            self.spin_window.setValue(params["winsize"])
        if "radius" in params:
            self.dspin_radius.setValue(params["radius"])
        if "nstd" in params:
            self.dspin_z.setValue(params["nstd"])
        if "noise_thresh" in params:
            self.dspin_noise.setValue(params["noise_thresh"])
        if "channels" in params:
            for i, cb in enumerate(self._channel_boxes):
                cb.setChecked(i in params["channels"])
            all_checked = all(cb.isChecked() for cb in self._channel_boxes)
            self.chk_all.blockSignals(True)
            self.chk_all.setChecked(all_checked)
            self.chk_all.blockSignals(False)
        if params.get("swd_mode") == "mask_out" and self._radio_swd_mask.isEnabled():
            self._radio_swd_mask.setChecked(True)

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

        # Pre-flight: warn about ok animals with no state CSV (they'll be silently skipped)
        from ebb_viewer.pipeline.manifest import Manifest
        manifest = Manifest.load(self.project_root)
        for combo in combos:
            csv_animal_ids = {
                p.stem.split("_")[0]
                for p in (spindle_root / combo).glob("*.csv")
            } if (spindle_root / combo).is_dir() else set()
            ok_animals = [
                entry.animal_id
                for entry in manifest
                if any(c == combo and r.sleep_qc == "ok" for c, r in entry.runs.items())
            ]
            missing = [a for a in ok_animals if a not in csv_animal_ids]
            if missing:
                self._log(
                    f"⚠ {combo}: no state CSV for {', '.join(missing)}"
                    f" — {'this animal' if len(missing) == 1 else 'these animals'} will be skipped"
                )

        # Pre-flight: SWD mask — all ok animals must have a .mat file
        swd_dir: Optional[Path] = None
        if self._radio_swd_mask.isChecked():
            swd_dir = self.project_root / "swd"
            swd_animal_ids = {p.stem.split("_")[0] for p in swd_dir.glob("*.mat")}
            all_ok_animals = {
                entry.animal_id
                for entry in manifest
                if any(r.sleep_qc == "ok" for r in entry.runs.values())
            }
            missing_swd = sorted(all_ok_animals - swd_animal_ids)
            if missing_swd:
                QMessageBox.warning(
                    self,
                    "Missing SWD Files",
                    "The following animals have no SWD .mat file in swd/:\n\n"
                    + "\n".join(f"  \u2022 {a}" for a in missing_swd)
                    + "\n\nProvide SWD files for all animals before running with SWD masking,"
                    " or switch to 'No SWD mask'.",
                )
                return

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
            project_root=self.project_root,
            swd_dir=swd_dir,
        )
        self.psd_worker.progress.connect(self._log)
        launch_worker(self.psd_thread, self.psd_worker,
                      on_finished=self._on_psd_done,
                      on_error=self._on_psd_error)

    def _build_final_pkl(self):
        from ebb.process.psd_compute import build_final_pkl
        from ebb_viewer.pipeline.manifest import Manifest
        try:
            manifest = Manifest.load(self.project_root)
            out = build_final_pkl(self.project_root, manifest)
            self._log(f"Built channel merged PKL: {out}")
            drink_pkl = self.project_root / "psd" / "psds_drink.pkl"
            if drink_pkl.exists():
                self._log(
                    "Note: previously applied drink masks are preserved in psds_drink.pkl."
                    " If PSD parameters changed since the last drink mask run,"
                    " re-apply them on the Drink Mask page."
                )
            self.manifest_changed.emit()
            self._hint_lbl.setText("✓ Channel merged PKL built — ready for PSD review.")
            self._hint_btn_viz.setVisible(True)
            self._hint_frame.setVisible(True)
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

        # Build Channel Merged PKL is only ready when every animal with
        # sleep_qc=="ok" has a per-combo PKL — prevents silent skips.
        from ebb_viewer.pipeline.manifest import Manifest
        psd_dir = self.project_root / "psd"
        manifest = Manifest.load(self.project_root)
        ok_combos = [
            combo
            for entry in manifest
            for combo, run in entry.runs.items()
            if run.sleep_qc == "ok"
        ]
        all_pkls_present = bool(ok_combos) and all(
            (psd_dir / f"psds_{combo}.pkl").exists() for combo in ok_combos
        )
        self.btn_final.setEnabled(all_pkls_present)

    def _on_psd_done(self):
        self._computing = False
        self._log("PSD computation finished.")
        self._refresh_combo_table()
        self._hint_lbl.setText("✓ PSDs computed — click 'Build Channel Merged PKL' to continue.")
        self._hint_btn_viz.setVisible(False)
        self._hint_frame.setVisible(True)

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
        project_root: Path,
        offset_path=None,
        swd_dir: Optional[Path] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.eeg_dir = eeg_dir
        self.combo_pairs = combo_pairs
        self.params = params
        self.project_root = Path(project_root)
        self.offset_path = offset_path
        self.swd_dir = swd_dir

    def run(self):
        from ebb.process.psd_compute import batch_estimate
        from ebb_viewer.pipeline import psd_params
        try:
            for spindle_dir, savepath in self.combo_pairs:
                self.progress.emit(f"Computing PSDs for combo: {spindle_dir.name}…")
                results = batch_estimate(
                    eeg_dir=self.eeg_dir,
                    state_dir=spindle_dir,
                    swd_dir=self.swd_dir,
                    drink_dir=None,
                    ncores=None,
                    savepath=None,
                    offset_path=self.offset_path,
                    progress_fn=self.progress.emit,
                    **self.params,
                )
                records = [{**dataclasses.asdict(r), "params": self.params} for r in results]
                with open(savepath, "wb") as f:
                    pickle.dump(records, f)
                self.progress.emit(f"  → Saved: {savepath.name}")

            swd_mode = "mask_out" if self.swd_dir is not None else "none"
            psd_params.save(self.project_root, {**self.params, "swd_mode": swd_mode})
            self.progress.emit("  → Saved PSD params to psd/psd_params.json")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
