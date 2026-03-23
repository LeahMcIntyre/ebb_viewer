from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QSpinBox, QVBoxLayout, QPushButton,
    QMessageBox, QLabel, QLineEdit, QGroupBox, QSizePolicy, QHBoxLayout, QFrame
)
from PyQt6.QtGui import QFont
from openseize.file_io import edf as edf_io

from ebb_viewer.widgets.trim_to_widget import TrimToWidget
from ebb_viewer.pipeline.manifest import Manifest
from ebb.preprocess.edf import batch, standard


def _fmt_hrs(hours: float) -> str:
    h = int(hours)
    m = int(round((hours - h) * 60))
    return f"{h}h {m:02d}m"


DEFAULT_FS = 5000
DEFAULT_DOWNSAMPLE = 20
DEFAULT_TRIM_TO = [48, 72]  # hours

_SAME_DURATION_THRESHOLD = 1 / 60  # 1 minute — treat as identical


class PreprocessPage(QWidget):
    navigate_to = pyqtSignal(str)

    _STYLE_NORMAL  = "color: #666; font-size: 10px;"
    _STYLE_WARNING = "color: #e67e22; font-size: 10px;"
    _STYLE_ERROR   = "color: #c0392b; font-size: 10px;"

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = project_root
        self.default_target_dir = project_root / "standard"
        self._durations_hrs: list[float] | None = None  # None = not yet scanned
        self._min_duration_hrs: float | None = None
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

        self._scan_label = QLabel("Scanning…")
        self._scan_label.setStyleSheet(self._STYLE_NORMAL + " padding-top: 0px;")

        top_form.addRow("Project:", self.lbl_root)
        top_form.addRow("", self._scan_label)
        top_form.addRow("Target Directory:", self.target_name_edit)

        fmt_lbl = QLabel(
            "ℹ EDF files must be named: "
            "<code>AnimalID_anything_YYYY_MM_DD_HH_MM_SS.edf</code>"
        )
        fmt_lbl.setTextFormat(Qt.TextFormat.RichText)
        fmt_lbl.setStyleSheet("color: #666; font-size: 10px; padding-top: 2px;")
        fmt_lbl.setWordWrap(True)
        top_form.addRow(fmt_lbl)

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

        self._hz_label = QLabel()
        self._hz_label.setStyleSheet("color: #555; font-size: 11px;")

        ds_row = QWidget()
        ds_layout = QHBoxLayout(ds_row)
        ds_layout.setContentsMargins(0, 0, 0, 0)
        ds_layout.setSpacing(8)
        ds_layout.addWidget(self.downsample)
        ds_layout.addWidget(self._hz_label)
        ds_layout.addStretch()

        # placeholder; real values set in _apply_state_to_ui()
        self.trim_to = TrimToWidget(values=DEFAULT_TRIM_TO)

        form.addRow("Original Sampling Frequency", self.fs_original)
        form.addRow("Downsample Factor",           ds_row)
        form.addRow("Trim To (hrs)",               self.trim_to)

        root.addWidget(settings_gb)

        self.btn_run = QPushButton("Run preprocessing")
        root.addWidget(self.btn_run)

        # Post-run hint (hidden until a run succeeds)
        self._hint_frame = QFrame()
        self._hint_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._hint_frame.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QHBoxLayout(self._hint_frame)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        hint_lbl = QLabel("✓ Done. Preprocessed EDFs written to standard/.")
        hint_layout.addWidget(hint_lbl, 1)
        btn_go_spindle = QPushButton("→ Spindle Write")
        btn_go_spindle.clicked.connect(lambda: self.navigate_to.emit("spindle_write"))
        hint_layout.addWidget(btn_go_spindle)
        self._hint_frame.setVisible(False)
        root.addWidget(self._hint_frame)

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
        self.fs_original.valueChanged.connect(self._update_hz_label)
        self.downsample.valueChanged.connect(self._update_hz_label)
        self._update_hz_label()
        self.trim_to.changed.connect(self._update_scan_warning)

    def _update_hz_label(self) -> None:
        fs = self.fs_original.value()
        ds = self.downsample.value()
        hz = fs / ds if ds > 0 else 0
        self._hz_label.setText(f"→ {hz:.0f} Hz output")

    def showEvent(self, event):
        super().showEvent(event)
        if self._durations_hrs is None:  # scan only once per session
            self._scan_edfs()

    def _scan_edfs(self) -> None:
        paths = sorted(self.project_root.glob("*.edf"))
        if not paths:
            self._scan_label.setText("No EDF files found")
            self._scan_label.setStyleSheet(self._STYLE_ERROR)
            self._durations_hrs = []
            self._min_duration_hrs = None
            return

        durations = []
        for p in paths:
            try:
                with edf_io.Reader(p) as reader:
                    secs = reader.header["num_records"] * reader.header["record_duration"]
                durations.append(secs / 3600.0)
            except Exception:
                pass

        self._durations_hrs = durations
        self._min_duration_hrs = min(durations) if durations else None

        n = len(paths)
        if not durations:
            self._scan_label.setText(f"Found {n} file{'s' if n != 1 else ''} · could not read durations")
            self._scan_label.setStyleSheet(self._STYLE_NORMAL)
            return

        min_hrs = self._min_duration_hrs
        max_hrs = max(durations)
        if abs(max_hrs - min_hrs) < _SAME_DURATION_THRESHOLD:
            dur_str = f"all {_fmt_hrs(min_hrs)}"
        else:
            dur_str = f"{_fmt_hrs(min_hrs)} – {_fmt_hrs(max_hrs)}"

        self._scan_label.setText(f"Found {n} file{'s' if n != 1 else ''} · {dur_str}")
        self._update_scan_warning()

    def _update_scan_warning(self) -> None:
        if self._min_duration_hrs is None:
            return
        trim_min = self.trim_to.value()[0]
        if self._min_duration_hrs < trim_min:
            self._scan_label.setStyleSheet(self._STYLE_WARNING)
        else:
            self._scan_label.setStyleSheet(self._STYLE_NORMAL)

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
            Manifest.build_from_standard(self.project_root)
            self._hint_frame.setVisible(True)

        except Exception as e:
            QMessageBox.critical(self, "Preprocess failed", str(e))
