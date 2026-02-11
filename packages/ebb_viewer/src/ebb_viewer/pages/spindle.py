from PyQt6.QtWidgets import (
    QVBoxLayout, QGroupBox, QGridLayout, QLabel, QCheckBox,
    QPushButton, QHBoxLayout, QSpacerItem, QSizePolicy,
    QMessageBox, QFormLayout, QLineEdit, QWidget
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt
from pathlib import Path
from typing import Optional

from ebb.preprocess.edf import batch, spindle


class SpindleWritePage(QWidget):
    CH_LABELS = {
        "Ch0": "LFC",
        "Ch1": "RSC",
        "Ch2": "LSC",
        "Ch3": "EMG (always included)",
    }

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = project_root
        self.standard_folder = project_root / "standard"
        if self.standard_folder.exists(): self.standard_folder = None  # will be set when project_paths is available


        # Standard folder is derived from AppState.project_paths.standard_dir
        self._validate()  # make sure initial channels are valid

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)

        # ----- Folder selection group -----
        folder_gb = QGroupBox("Folder Selection")
        folder_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        folder_gb.setObjectName("folderBox")

        top_form = QFormLayout(folder_gb)



        # Standard folder (read-only, driven by project)
        self.lbl_standard = QLineEdit("No standard folder selected")
        self.lbl_standard.setReadOnly(True)
        top_form.addRow("Standard EDF Folder:", self.lbl_standard)

        # Spindle root label (readonly)
        self.lbl_spindle_root = QLabel("Spindle root: (no project)")
        self.lbl_spindle_root.setStyleSheet("color: #666;")
        top_form.addRow("Spindle Root:", self.lbl_spindle_root)

        # Channel combo name (read-only, derived from selected EEG channels)
        self.combo_name_edit = QLineEdit("")
        self.combo_name_edit.setReadOnly(True)
        top_form.addRow("Channel Combo:", self.combo_name_edit)

        # Target spindle EDF folder (editable, prefilled from ProjectPaths)
        self.target_name_edit = QLineEdit()
        self.target_name_edit.setStyleSheet(
            "QLineEdit { padding-top: 0px; padding-bottom: 0px; }"
        )
        top_form.addRow("Target Directory:", self.target_name_edit)

        # ----- Channel selection group -----
        gb = QGroupBox("Channel Selection")
        gb.setObjectName("channelBox")
        gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.setStyleSheet("""
        QGroupBox#folderBox, QGroupBox#channelBox {
            font: 550;
        }
        QGroupBox#folderBox *, QGroupBox#channelBox * {
            font: 400;
        }
        """)

        grid = QGridLayout(gb)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        self.lbl_rule = QLabel(
            "Select either <b>exactly 1</b> or <b>exactly 2</b> of the first three channels."
        )
        self.lbl_rule.setTextFormat(Qt.TextFormat.RichText)
        grid.addWidget(self.lbl_rule, 0, 0, 1, 3)

        self.cb_ch0 = QCheckBox(f"Ch0 — {self.CH_LABELS['Ch0']}")
        self.cb_ch0.setChecked(True)
        self.cb_ch1 = QCheckBox(f"Ch1 — {self.CH_LABELS['Ch1']}")
        self.cb_ch1.setChecked(True)
        self.cb_ch2 = QCheckBox(f"Ch2 — {self.CH_LABELS['Ch2']}")
        grid.addWidget(self.cb_ch0, 1, 0)
        grid.addWidget(self.cb_ch1, 1, 1)
        grid.addWidget(self.cb_ch2, 1, 2)

        grid.addItem(
            QSpacerItem(0, 6, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum),
            2, 0, 1, 3
        )

        self.cb_ch3 = QCheckBox(f"Ch3 — {self.CH_LABELS['Ch3']}")
        self.cb_ch3.setChecked(True)
        self.cb_ch3.setEnabled(False)
        self.cb_ch3.setToolTip("This channel is required and will always be processed.")

        self.lbl_lock = QLabel("🔒 Always included — no selection required")
        f = QFont()
        f.setPointSize(f.pointSize() - 1)
        self.lbl_lock.setFont(f)
        self.lbl_lock.setStyleSheet("color: #666;")

        lock_row = QHBoxLayout()
        lock_row.addWidget(self.cb_ch3)
        lock_row.addWidget(self.lbl_lock)
        lock_row.addStretch(1)
        grid.addLayout(lock_row, 3, 0, 1, 3)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: #b00020;")
        grid.addWidget(self.lbl_status, 4, 0, 1, 3)

        # ----- Actions -----
        actions = QHBoxLayout()
        self.btn_apply = QPushButton("Run Spindle Preprocessor")
        self.btn_apply.setEnabled(False)
        actions.addWidget(self.btn_apply)

        root.addWidget(folder_gb)
        root.addWidget(gb)
        root.addLayout(actions)

    # ------------ Wiring / Signals ------------
    def _wire(self):
        # Channels drive validation + combo/target updates
        self.cb_ch0.toggled.connect(self._validate)
        self.cb_ch1.toggled.connect(self._validate)
        self.cb_ch2.toggled.connect(self._validate)
        self.btn_apply.clicked.connect(self._run_spindle_btn)

    # ------------ React to project changes ------------
    def _on_project_changed(self, p: Optional[Path]) -> None:
        """When project changes, point standard_folder to paths.standard_dir."""
        paths: Optional[ProjectPaths] = getattr(self.state, "project_paths", None)

        if paths is not None:
            std = paths.standard_dir
            self.standard_folder = std
            if std.exists():
                self.lbl_standard.setText(str(std))
            else:
                # Folder might not exist yet (e.g. preprocess not run)
                self.lbl_standard.setText(f"{std} (does not exist yet)")
        else:
            self.standard_folder = None
            self.lbl_standard.setText("No standard folder selected")

        self._update_target_path()
        self._validate()

    # ------------ Actions ------------
    def _run_spindle_btn(self):
        channels = self._selected_indices()

        paths: Optional[ProjectPaths] = getattr(self.state, "project_paths", None)
        if paths is None:
            QMessageBox.critical(
                self,
                "No Project",
                "Please choose a project folder first."
            )
            return

        if self.standard_folder is None:
            QMessageBox.critical(
                self,
                "No Standard EDF Folder",
                "Standard folder is not set. Run preprocessing first."
            )
            return

        if not self.standard_folder.exists():
            QMessageBox.critical(
                self,
                "Standard Folder Missing",
                f"Standard folder does not exist:\n{self.standard_folder}"
            )
            return

        # Derive combo name from selected EEG channels (Ch0–Ch2)
        eeg_labels = self._current_eeg_labels()
        if not eeg_labels:
            QMessageBox.critical(
                self,
                "No Channels Selected",
                "Please select at least one EEG channel."
            )
            return

        combo_name = paths.combo_to_str(eeg_labels)  # e.g. "LFC_RSC"
        # Default target dir based on our canonical structure
        default_target = paths.spindle_dir_for_combo(combo_name)

        # Allow user to override target path if they really want
        target_text = self.target_name_edit.text().strip()
        target_dir = Path(target_text) if target_text else default_target

        # If the user cleared the field, confirm using default
        if not target_text:
            msg = (
                "No target folder specified.\n\n"
                f"Use default spindle folder for this combo?\n\n{default_target}"
            )
            btn = QMessageBox.question(
                self,
                "No Target Folder Selected",
                msg
            )
            if btn != QMessageBox.StandardButton.Yes:
                return
            self.target_name_edit.setText(str(default_target))
            self.target_name_edit.setToolTip(str(default_target))
            target_dir = default_target

        # --- NEW: ensure directories exist ---
        spindle_root = paths.spindle_root
        try:
            spindle_root.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Folder Error",
                f"Could not create spindle root folder:\n{spindle_root}\n\n{e}",
            )
            return
        """
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Folder Error",
                f"Could not create target folder:\n{target_dir}\n\n{e}",
            )
            return"""

        try:
            preprocess_folder_spindle(
                standard_dir=self.standard_folder,
                target=target_dir,
                channels=channels
            )
            QMessageBox.information(
                self,
                "Spindle Preprocessing",
                f"Finished preprocessing files for spindle.\n"
                f"Output folder:\n{target_dir}",
            )

        except Exception as e:
            QMessageBox.critical(self, "Spindle Preprocess failed", str(e))

    # ------------ Validation ------------
    def _validate(self):
        n = len(self._selected_indices())

        if n == 2:
            # 1 EEG + EMG
            self.lbl_status.setText("1 selected. You can apply.")
            self.lbl_status.setStyleSheet("color: #0a7f2e;")
            self._update_target_path()

        elif n == 3:
            # 2 EEG + EMG
            self.lbl_status.setText("Perfect - Two selected. You can apply.")
            self.lbl_status.setStyleSheet("color: #0a7f2e;")
            self._update_target_path()

        else:
            msg = (
                "Select 1 or 2 channels from Ch0–Ch2."
                if n < 2
                else "Maximum is 2 channels from Ch0–2."
            )
            self.lbl_status.setText(msg)
            self.lbl_status.setStyleSheet("color: #b00020;")
            self.btn_apply.setEnabled(False)

        run_enabled = (n == 2) or (n == 3)
        if self.standard_folder is None:
            run_enabled = False
        self.btn_apply.setEnabled(run_enabled)

    # ------------ Helpers ------------
    def _selected_indices(self):
        """Return selected channel indices including EMG (3)."""
        sel = []
        if self.cb_ch0.isChecked():
            sel.append(0)
        if self.cb_ch1.isChecked():
            sel.append(1)
        if self.cb_ch2.isChecked():
            sel.append(2)
        sel.append(3)  # ch3 always (EMG)
        return sel

    def _current_eeg_labels(self):
        """Return labels for selected EEG channels (Ch0–Ch2), e.g. ['LFC','RSC']."""
        labels = []
        if self.cb_ch0.isChecked():
            labels.append(self.CH_LABELS["Ch0"])
        if self.cb_ch1.isChecked():
            labels.append(self.CH_LABELS["Ch1"])
        if self.cb_ch2.isChecked():
            labels.append(self.CH_LABELS["Ch2"])
        return labels

    def _update_target_path(self):
        """
        Update suggested combo name and target folder whenever project,
        standard folder, or channel selection changes.
        """
        paths: Optional[ProjectPaths] = getattr(self.state, "project_paths", None)

        if paths is None or self.standard_folder is None:
            self.combo_name_edit.setText("")
            self.combo_name_edit.setToolTip("")
            self.target_name_edit.setText("")
            self.target_name_edit.setToolTip("")
            return

        eeg_labels = self._current_eeg_labels()
        if not eeg_labels:
            self.combo_name_edit.setText("")
            self.target_name_edit.setText("")
            return

        combo_name = paths.combo_to_str(eeg_labels)  # e.g. "LFC_RSC"
        target = paths.spindle_dir_for_combo(combo_name)

        self.combo_name_edit.setText(combo_name)
        self.combo_name_edit.setToolTip(combo_name)
        self.target_name_edit.setText(str(target))
        self.target_name_edit.setToolTip(str(target))
