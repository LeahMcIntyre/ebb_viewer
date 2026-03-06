from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QSpinBox, QVBoxLayout, QPushButton,
    QMessageBox, QLabel, QLineEdit, QGroupBox, QSizePolicy
)
from PyQt6.QtGui import QFont

from ebb_viewer.widgets.trim_to_widget import TrimToWidget
from ebb.preprocess.edf import batch, standard

DEFAULT_FS = 5000
DEFAULT_DOWNSAMPLE = 20
DEFAULT_TRIM_TO = [48, 72]  # hours


class PreprocessPage(QWidget):
    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = project_root
        self.default_target_dir = project_root / "standard"
        self._build_ui()
        self._wire()

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)

        # Folder Selection Box
        folder_gb = QGroupBox("Folder Selection")
        folder_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        top_form = QFormLayout(folder_gb)

        self.lbl_root = QLineEdit(str(self.project_root))
        self.lbl_root.setToolTip(str(self.project_root))
        self.lbl_root.setReadOnly(True)

        self.target_name_edit = QLineEdit(str(self.default_target_dir))
        self.target_name_edit.setToolTip(str(self.default_target_dir))
        self.target_name_edit.setStyleSheet("QLineEdit { padding-top: 0px; padding-bottom: 0px; }")
        self.target_name_edit.setReadOnly(True)

        top_form.addRow("Project:", self.lbl_root)
        top_form.addRow("Target Directory:", self.target_name_edit)

        root.addWidget(folder_gb)

        # Form Layout for Settings
        settings_gb = QGroupBox("Preprocessing Settings")
        settings_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        form = QFormLayout(settings_gb)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        # Settings widgets
        self.fs_original = QSpinBox()
        self.fs_original.setRange(250, 10000)
        self.fs_original.setValue(DEFAULT_FS)

        self.downsample = QSpinBox()
        self.downsample.setRange(1, 100)
        self.downsample.setValue(DEFAULT_DOWNSAMPLE)

        # placeholder; real values set in _apply_state_to_ui()
        self.trim_to = TrimToWidget(values=DEFAULT_TRIM_TO)

        form.addRow("Original Sampling Frequency", self.fs_original)
        form.addRow("Downsample Factor",           self.downsample)
        form.addRow("Trim To (hrs)",               self.trim_to)

        root.addWidget(settings_gb)

        self.btn_run = QPushButton("Run preprocessing")
        root.addWidget(self.btn_run)
        root.addStretch()

        # ----------- Set Style Sheets -----------
        folder_gb.setObjectName("folderBox")
        settings_gb.setObjectName("settingsBox")

        self.setStyleSheet("""
        QGroupBox#folderBox, QGroupBox#settingsBox {
            font: 550;
        }
        QGroupBox#folderBox *, QGroupBox#settingsBox * {
            font: 400;
        }
        """)

    # ------------- Wiring / Signals -------------
    def _wire(self):
        self.btn_run.clicked.connect(self._run_clicked)



    # Run Preprocessing
    def _run_clicked(self):
    

        # Read the current target directory text (Not Relevant Now Because I force default)
        target_text = self.target_name_edit.text().strip()
        if target_text:
            target_dir = Path(target_text)
        else:
            target_dir = self.default_target_dir

        # Validate: if the parent of target_dir doesn't exist, warn & fall back
        if not target_dir.parent.is_dir():
            msg = (
                f"Target folder will default to '{self.default_target_dir}'.\n"
                "Continue?"
            )
            btn = QMessageBox.question(
                self,
                "No Target Folder Selected",
                msg
            )
            if btn != QMessageBox.StandardButton.Yes:
                return

            target_dir = self.default_target_dir
            self.target_name_edit.setText(str(target_dir))
            self.target_name_edit.setToolTip(str(target_dir))

        # Pull a snapshot from the UI
        params = {
            "fs":         int(self.fs_original.value()),
            "downsample": int(self.downsample.value()),
            "trim_to":    list(self.trim_to.value()),
        }

        try:
            batch(
                preprocessor=standard,
                dirpath=self.project_root,
                target=target_dir,
                **params,
            )
            QMessageBox.information(
                self,
                "Preprocess",
                "Finished preprocessing files."
            )

        except Exception as e:
            QMessageBox.critical(self, "Preprocess failed", str(e))
