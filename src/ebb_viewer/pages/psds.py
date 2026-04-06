from pathlib import Path
from typing import Optional, List, Tuple
import dataclasses
import pickle

from ebb.process.psd_compute import batch_estimate, build_final_pkl

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from ebb_viewer.widgets.worker_helpers import launch_worker
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QSpinBox, QDoubleSpinBox, QVBoxLayout, QPushButton,
    QMessageBox, QLabel, QHBoxLayout, QGroupBox, QCheckBox, QGridLayout,
    QSizePolicy, QLineEdit, QApplication, QPlainTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QFrame, QButtonGroup, QRadioButton,
    QToolButton,
)

from ebb_viewer.pipeline.manifest import Manifest, merged_psd_path
from ebb_viewer.pipeline import psd_params


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
        self._ann_dir: Optional[Path] = None
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

        lbl = QLabel("PSD Computation")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        desc = QLabel(
            "Compute power spectral densities from sleep-scored EDF files. "
            "A separate PSD file is produced for each channel combination. "
            "Each animal must have exactly one combination marked 'ok' in Sleep QC — "
            "those ok runs are then merged into a single combined file per combo for downstream analysis."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")

        root.addWidget(lbl)
        root.addWidget(desc)

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
        self.combo_table.setHorizontalHeaderLabels(["Combo", "CSVs", "Ok Runs", "PKL Status"])
        self.combo_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.combo_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed
        )
        self.combo_table.setColumnWidth(1, 60)
        self.combo_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self.combo_table.setColumnWidth(2, 70)
        self.combo_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.combo_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.combo_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.combo_table.verticalHeader().setVisible(False)
        combo_v.addWidget(self.combo_table)

        self._merged_pkl_label = QLabel()
        self._merged_pkl_label.setStyleSheet("font-size: 10px; color: #555; padding-top: 2px;")
        combo_v.addWidget(self._merged_pkl_label)

        root.addWidget(self.combo_gb)

        # ----- Group 3: SWD Masks -----
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

        swd_hint = QLabel(
            "To use SWD masking, place one .mat file of SWD timestamps per animal in a swd/ folder "
            "in the project root (e.g. project/swd/AnimalID_*.mat)."
        )
        swd_hint.setWordWrap(True)
        swd_hint.setStyleSheet("font-size: 10px; color: #777; padding-left: 4px; padding-top: 2px;")
        swd_v.addWidget(swd_hint)

        self._lbl_swd_status = QLabel("")
        self._lbl_swd_status.setStyleSheet("font-size: 11px; padding-left: 4px;")
        swd_v.addWidget(self._lbl_swd_status)

        root.addWidget(self.gb_swd)

        # ----- Group 4: Annotation Mask -----
        self.gb_ann = QGroupBox("Annotation Mask")
        self.gb_ann.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        ann_v = QVBoxLayout(self.gb_ann)

        self.chk_ann = QCheckBox("Apply annotation mask")
        ann_v.addWidget(self.chk_ann)

        # Body — everything inside is enabled/disabled as a unit via setEnabled
        self._ann_body = QWidget()
        ann_body_v = QVBoxLayout(self._ann_body)
        ann_body_v.setContentsMargins(0, 4, 0, 0)
        ann_body_v.setSpacing(6)
        self._ann_body.setEnabled(False)

        # Directory picker
        ann_dir_form = QFormLayout()
        ann_dir_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        ann_dir_row = QHBoxLayout()
        self.lbl_ann_dir = QLineEdit()
        self.lbl_ann_dir.setReadOnly(True)
        self.lbl_ann_dir.setPlaceholderText("No directory selected")
        self.btn_ann_dir = QPushButton("Browse…")
        ann_dir_row.addWidget(self.lbl_ann_dir)
        ann_dir_row.addWidget(self.btn_ann_dir)
        ann_dir_form.addRow("Annotation directory:", ann_dir_row)
        ann_body_v.addLayout(ann_dir_form)

        self._lbl_ann_status = QLabel("")
        self._lbl_ann_status.setStyleSheet("font-size: 11px; padding-left: 4px;")
        ann_body_v.addWidget(self._lbl_ann_status)

        # Keywords
        ann_kw_form = QFormLayout()
        ann_kw_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._ann_keyword_edit = QLineEdit()
        self._ann_keyword_edit.setPlaceholderText("e.g.  drink, artifact")
        ann_kw_form.addRow("Keywords:", self._ann_keyword_edit)
        ann_body_v.addLayout(ann_kw_form)

        kw_hint = QLabel("Comma-separated, case-insensitive. Annotations whose labels match will be masked.")
        kw_hint.setWordWrap(True)
        kw_hint.setStyleSheet("font-size: 10px; color: #777; padding-left: 4px;")
        ann_body_v.addWidget(kw_hint)

        # Match mode
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Match mode:"))
        self._radio_ann_contains = QRadioButton("Contains")
        self._radio_ann_exact = QRadioButton("Exact")
        self._radio_ann_contains.setChecked(True)
        self._radio_ann_contains.setToolTip("Match any label containing the keyword as a substring")
        self._radio_ann_exact.setToolTip("Match only labels that equal the keyword exactly")
        self._ann_mode_group = QButtonGroup(self)
        self._ann_mode_group.addButton(self._radio_ann_contains, 0)
        self._ann_mode_group.addButton(self._radio_ann_exact, 1)
        mode_row.addWidget(self._radio_ann_contains)
        mode_row.addWidget(self._radio_ann_exact)
        mode_row.addStretch()
        ann_body_v.addLayout(mode_row)

        # Padding
        pad_form = QFormLayout()
        pad_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._ann_pad_before = QDoubleSpinBox()
        self._ann_pad_before.setRange(0.0, 3600.0)
        self._ann_pad_before.setSingleStep(1.0)
        self._ann_pad_before.setDecimals(1)
        self._ann_pad_before.setSuffix(" s")
        self._ann_pad_before.setValue(0.0)
        self._ann_pad_after = QDoubleSpinBox()
        self._ann_pad_after.setRange(0.0, 3600.0)
        self._ann_pad_after.setSingleStep(1.0)
        self._ann_pad_after.setDecimals(1)
        self._ann_pad_after.setSuffix(" s")
        self._ann_pad_after.setValue(10.0)
        pad_form.addRow("Pad before:", self._ann_pad_before)
        pad_form.addRow("Pad after:", self._ann_pad_after)
        ann_body_v.addLayout(pad_form)

        ann_v.addWidget(self._ann_body)
        root.addWidget(self.gb_ann)

        # ----- Collapsible: Advanced PSD Settings -----
        self._btn_adv = QToolButton()
        self._btn_adv.setText("Advanced PSD Settings")
        self._btn_adv.setCheckable(True)
        self._btn_adv.setChecked(False)
        self._btn_adv.setArrowType(Qt.ArrowType.RightArrow)
        self._btn_adv.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._btn_adv.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn_adv.setStyleSheet(
            "QToolButton { border: 1px solid #ccc; border-radius: 3px;"
            " padding: 3px 6px; background: #f5f5f5; color: #444; font-size: 11px; }"
            "QToolButton:checked { background: #eaeaea; }"
            "QToolButton:hover { background: #ebebeb; }"
        )
        root.addWidget(self._btn_adv)

        self._adv_container = QWidget()
        adv_v = QVBoxLayout(self._adv_container)
        adv_v.setContentsMargins(0, 0, 0, 0)
        adv_v.setSpacing(4)
        self._adv_container.setVisible(False)

        # ----- Group 4: PSD Settings -----
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

        adv_v.addWidget(self.gb_psd)

        # ----- Group 5: Spindle Noise Mask -----
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
        adv_v.addWidget(self.gb_spindle)

        # ----- Group 6: SD Mask -----
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
        adv_v.addWidget(self.gb_mask)
        root.addWidget(self._adv_container)

        # ----- Main Action Button -----
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(8)
        self.btn_run_pipeline = QPushButton("Run PSD Pipeline")
        self.btn_run_pipeline.setEnabled(False)
        self._gate_label = QLabel("")
        self._gate_label.setStyleSheet("color: #888; font-size: 10px;")
        btn_row2.addWidget(self.btn_run_pipeline)
        btn_row2.addWidget(self._gate_label, 1)
        root.addLayout(btn_row2)

        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet("color: #555; font-size: 10px;")
        self._summary_label.setWordWrap(True)
        root.addWidget(self._summary_label)

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
        self.gb_ann.setObjectName("annBox")
        self.setStyleSheet("""
        QGroupBox#psdBox, QGroupBox#spindleBox, QGroupBox#maskBox,
        QGroupBox#folderBox, QGroupBox#comboBox, QGroupBox#swdBox, QGroupBox#annBox {
            font: 550;
        }
        QGroupBox#psdBox *, QGroupBox#spindleBox *, QGroupBox#maskBox *,
        QGroupBox#folderBox *, QGroupBox#comboBox *, QGroupBox#swdBox *,
        QGroupBox#annBox * {
            font: 400;
        }
        """)

    # ------------- Wiring / Signals -------------

    def _wire(self):
        self.chk_all.toggled.connect(self._toggle_all_channels)
        self.btn_standard.clicked.connect(self._choose_standard_folder)
        self.btn_refresh_table.clicked.connect(self._refresh_combo_table)
        self.btn_run_pipeline.clicked.connect(self._run_pipeline_clicked)
        self._swd_btn_group.buttonToggled.connect(lambda *_: self._validate())
        self._btn_adv.clicked.connect(self._toggle_advanced)
        self.chk_ann.toggled.connect(self._on_ann_toggled)
        self.btn_ann_dir.clicked.connect(self._choose_ann_dir)
        self._ann_keyword_edit.textChanged.connect(self._validate)

    def _toggle_advanced(self, checked: bool):
        self._adv_container.setVisible(checked)
        self._btn_adv.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )

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


    def _on_ann_toggled(self, checked: bool) -> None:
        self._ann_body.setEnabled(checked)
        self._validate()

    def _choose_ann_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Annotation Directory", str(self.project_root)
        )
        if not path:
            return
        self._ann_dir = Path(path)
        self.lbl_ann_dir.setText(str(self._ann_dir))
        self._refresh_ann_status()

    def _refresh_ann_status(self) -> None:
        if not self.chk_ann.isChecked() or self._ann_dir is None:
            self._lbl_ann_status.setText("")
            return
        if not self._ann_dir.is_dir():
            self._lbl_ann_status.setText("Directory not found")
            self._lbl_ann_status.setStyleSheet("font-size: 11px; padding-left: 4px; color: #c0392b;")
            self._validate()
            return
        manifest = Manifest.load(self.project_root)
        animal_ids = [e.animal_id for e in manifest]
        n_animals = len(animal_ids)
        n_found = sum(
            1 for aid in animal_ids
            if any(self._ann_dir.glob(f"{aid}*.txt")) or any(self._ann_dir.glob(f"{aid}*.csv"))
        )
        if n_animals == 0:
            self._lbl_ann_status.setText("No animals in manifest")
            self._lbl_ann_status.setStyleSheet("font-size: 11px; padding-left: 4px; color: #888;")
        elif n_found == n_animals:
            self._lbl_ann_status.setText(f"✓ {n_found} of {n_animals} animals have annotation files")
            self._lbl_ann_status.setStyleSheet("font-size: 11px; padding-left: 4px; color: #2a7a2a;")
        elif n_found == 0:
            self._lbl_ann_status.setText(f"No annotation files found for any of the {n_animals} animals")
            self._lbl_ann_status.setStyleSheet("font-size: 11px; padding-left: 4px; color: #c0392b;")
        else:
            self._lbl_ann_status.setText(f"⚠ {n_found} of {n_animals} animals have annotation files")
            self._lbl_ann_status.setStyleSheet("font-size: 11px; padding-left: 4px; color: #c77800;")
        self._validate()

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
                n_animals = sum(1 for _ in Manifest.load(self.project_root))
                if n_animals > 0 and mat_count != n_animals:
                    self._lbl_swd_status.setText(
                        f"⚠ {mat_count} .mat {'file' if mat_count == 1 else 'files'} in swd/ "
                        f"(expected {n_animals})"
                    )
                    self._lbl_swd_status.setStyleSheet("font-size: 11px; padding-left: 4px; color: #c0392b;")
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
        if params.get("ann_dir"):
            p = Path(params["ann_dir"])
            if p.is_dir():
                self._ann_dir = p
                self.lbl_ann_dir.setText(str(p))
        if params.get("ann_keywords"):
            self._ann_keyword_edit.setText(params["ann_keywords"])
        if params.get("ann_match_mode") == "exact":
            self._radio_ann_exact.setChecked(True)
        if "ann_pad_before" in params:
            self._ann_pad_before.setValue(params["ann_pad_before"])
        if "ann_pad_after" in params:
            self._ann_pad_after.setValue(params["ann_pad_after"])
        if params.get("ann_enabled"):
            self.chk_ann.setChecked(True)
            self._refresh_ann_status()

    def _refresh_combo_table(self):

        spindle_root = self.project_root / "spindle_outputs"
        psd_dir = self.project_root / "psd"
        manifest = Manifest.load(self.project_root)

        # Count ok runs per combo across all animals
        ok_runs_per_combo: dict[str, int] = {}
        for entry in manifest:
            for combo, run in entry.runs.items():
                if run.sleep_qc == "ok":
                    ok_runs_per_combo[combo] = ok_runs_per_combo.get(combo, 0) + 1

        self.combo_table.blockSignals(True)
        self.combo_table.setRowCount(0)

        if spindle_root.is_dir():
            for combo_dir in sorted(p for p in spindle_root.iterdir() if p.is_dir()):
                combo = combo_dir.name
                csv_count = len(list(combo_dir.glob("*.csv")))
                ok_count = ok_runs_per_combo.get(combo, 0)
                pkl_path = psd_dir / f"psds_{combo}.pkl"
                pkl_status = "✓ exists" if pkl_path.exists() else "missing"

                row = self.combo_table.rowCount()
                self.combo_table.insertRow(row)

                self.combo_table.setItem(row, 0, QTableWidgetItem(combo))
                self.combo_table.setItem(row, 1, QTableWidgetItem(str(csv_count)))

                ok_item = QTableWidgetItem(str(ok_count) if ok_count else "—")
                if ok_count > 0:
                    ok_item.setForeground(QColor("#2a7a2a"))
                self.combo_table.setItem(row, 2, ok_item)

                status_item = QTableWidgetItem(pkl_status)
                if pkl_status.startswith("✓"):
                    status_item.setForeground(QColor("#2a7a2a"))
                self.combo_table.setItem(row, 3, status_item)

        self.combo_table.blockSignals(False)

        merged = merged_psd_path(self.project_root)
        if merged.exists():
            self._merged_pkl_label.setText("Channel merged PKL: ✓ exists")
            self._merged_pkl_label.setStyleSheet("font-size: 10px; color: #2a7a2a; padding-top: 2px;")
        else:
            self._merged_pkl_label.setText("Channel merged PKL: not yet built")
            self._merged_pkl_label.setStyleSheet("font-size: 10px; color: #555; padding-top: 2px;")

        self._validate()

    # ------------- Actions -------------

    def _run_pipeline_clicked(self):
        if self.standard_folder is None or not self.standard_folder.exists():
            QMessageBox.critical(
                self,
                "No Standard Folder",
                "Standard EDF folder not set or does not exist.\n\n"
                f"Expected: {self.project_root / 'standard'}",
            )
            return

        spindle_root = self.project_root / "spindle_outputs"
        combos = sorted(
            sd.name for sd in spindle_root.iterdir()
            if sd.is_dir() and any(sd.glob("*.csv"))
        ) if spindle_root.is_dir() else []

        if not combos:
            QMessageBox.warning(self, "No Combos Found",
                                "No spindle output combos with CSVs found.")
            return


        manifest = Manifest.load(self.project_root)

        # Pre-flight: warn about ok animals with no state CSV (they'll be silently skipped)
        for combo in combos:
            csv_animal_ids = {
                p.stem.split("_")[0]
                for p in (spindle_root / combo).glob("*.csv")
            }
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

        ann_params = None
        if self.chk_ann.isChecked() and self._ann_dir is not None:
            ann_params = {
                "ann_dir": self._ann_dir,
                "keywords": [k.strip() for k in self._ann_keyword_edit.text().split(",") if k.strip()],
                "match_mode": "exact" if self._radio_ann_exact.isChecked() else "contains",
                "pad_before_sec": self._ann_pad_before.value(),
                "pad_after_sec": self._ann_pad_after.value(),
            }

        self._computing = True
        self.btn_run_pipeline.setEnabled(False)
        self._log(f"Running PSD pipeline for {len(combos)} combo(s): {', '.join(combos)}")

        self.psd_thread = QThread(self)
        self.psd_worker = BatchEstimateWorker(
            eeg_dir=self.standard_folder,
            combo_pairs=pairs,
            params=params,
            project_root=self.project_root,
            swd_dir=swd_dir,
            ann_params=ann_params,
        )
        self.psd_worker.progress.connect(self._log)
        launch_worker(self.psd_thread, self.psd_worker,
                      on_finished=self._on_psd_done,
                      on_error=self._on_psd_error)

    def _build_final_pkl(self):


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
            self._gate_label.setText("")
            self._summary_label.setText("")
            return
        has_standard = self.standard_folder is not None and self.standard_folder.exists()


        manifest = Manifest.load(self.project_root)
        n_animals = sum(1 for _ in manifest)
        n_ready = len(manifest.ready_for_psd())
        all_ready = n_animals > 0 and n_ready == n_animals

        spindle_root = self.project_root / "spindle_outputs"
        has_combos = spindle_root.is_dir() and any(
            sd.is_dir() and any(sd.glob("*.csv"))
            for sd in spindle_root.iterdir()
        )

        # Annotation mask gate
        ann_ok = True
        if self.chk_ann.isChecked():
            if self._ann_dir is None or not self._ann_dir.is_dir():
                ann_ok = False
            elif not self._ann_keyword_edit.text().strip():
                ann_ok = False

        self.btn_run_pipeline.setEnabled(has_standard and all_ready and has_combos and ann_ok)

        if not has_standard:
            self._gate_label.setText("Standard folder not found — run preprocessing first")
            self._summary_label.setText("")
        elif not all_ready:
            n_not_ready = n_animals - n_ready
            if n_animals == 0:
                self._gate_label.setText("No animals in manifest")
            else:
                self._gate_label.setText(
                    f"{n_not_ready} animal{'s' if n_not_ready != 1 else ''} "
                    "not ready — each needs exactly 1 ok run"
                )
            self._summary_label.setText("")
        elif not has_combos:
            self._gate_label.setText("No spindle output combos found — complete upload/download first")
            self._summary_label.setText("")
        elif not ann_ok:
            if self._ann_dir is None or not self._ann_dir.is_dir():
                self._gate_label.setText("Annotation mask enabled — select a valid annotation directory")
            else:
                self._gate_label.setText("Annotation mask enabled — enter at least one keyword")
            self._summary_label.setText("")
        else:
            self._gate_label.setText("")
            # Build summary: "LFC_RSC (8 animals), LFC_LSC (5 animals) → psds_channel_merged.pkl"
            ok_per_combo: dict[str, int] = {}
            for entry in manifest:
                for combo, run in entry.runs.items():
                    if run.sleep_qc == "ok":
                        ok_per_combo[combo] = ok_per_combo.get(combo, 0) + 1
            parts = [f"{c} ({n} animal{'s' if n != 1 else ''})" for c, n in sorted(ok_per_combo.items())]
            self._summary_label.setText(
                ", ".join(parts) + " → psds_channel_merged.pkl"
            )

    def _on_psd_done(self):
        self._computing = False
        self._log("PSD computation finished.")
        self._refresh_combo_table()
        self._log("Building channel-merged PKL…")
        self._build_final_pkl()

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
        ann_params: Optional[dict] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.eeg_dir = eeg_dir
        self.combo_pairs = combo_pairs
        self.params = params
        self.project_root = Path(project_root)
        self.offset_path = offset_path
        self.swd_dir = swd_dir
        self.ann_params = ann_params

    def run(self):


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
                    ann_params=self.ann_params,
                    **self.params,
                )
                records = [{**dataclasses.asdict(r), "params": self.params} for r in results]
                with open(savepath, "wb") as f:
                    pickle.dump(records, f)
                self.progress.emit(f"  → Saved: {savepath.name}")

            swd_mode = "mask_out" if self.swd_dir is not None else "none"
            saved = {**self.params, "swd_mode": swd_mode}
            if self.ann_params is not None:
                saved.update({
                    "ann_enabled": True,
                    "ann_dir": str(self.ann_params["ann_dir"]),
                    "ann_keywords": ", ".join(self.ann_params["keywords"]),
                    "ann_match_mode": self.ann_params["match_mode"],
                    "ann_pad_before": self.ann_params["pad_before_sec"],
                    "ann_pad_after": self.ann_params["pad_after_sec"],
                })
            else:
                saved["ann_enabled"] = False
            psd_params.save(self.project_root, saved)
            self.progress.emit("  → Saved PSD params to psd/psd_params.json")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
