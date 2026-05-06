import time
from pathlib import Path

from openseize.file_io import edf as edf_io
from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ebb.preprocess.edf import batch as batch_preprocess
from ebb.preprocess.edf import standard
from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.widgets.trim_to_widget import TrimToWidget
from ebb_viewer.widgets.worker_helpers import launch_worker


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

    _STYLE_NORMAL = "color: #666; font-size: 10px;"
    _STYLE_WARNING = "color: #e67e22; font-size: 10px;"
    _STYLE_ERROR = "color: #c0392b; font-size: 10px;"

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

        lbl = QLabel("Preprocess EDFs")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        desc = QLabel(
            "Trim, downsample, and standardize raw EDF files. "
            "Processed files are written to the standard/ folder."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")

        root.addWidget(lbl)
        root.addWidget(desc)

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
            "ℹ EDF files must be named: <code>AnimalID_anything_YYYY_MM_DD_HH_MM_SS.edf</code>"
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
        fs_lbl = QLabel("Original Sampling Frequency (Hz):")
        fs_lbl.setToolTip("Original sampling frequency of the EDF files (in Hz)")

        self.downsample = QSpinBox()
        self.downsample.setRange(1, 100)
        self.downsample.setValue(DEFAULT_DOWNSAMPLE)

        ds_lbl = QLabel("Downsample Factor")
        ds_lbl.setToolTip("Factor by which to downsample the EDF files")

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

        trim_lbl = QLabel("Trim To (hrs)")
        trim_lbl.setToolTip(
            "Two fallback trim targets (hours).\n"
            "Each EDF is trimmed to the longest value that is ≤ its duration.\n"
            "Example: targets [48, 72] — a 60h recording trims to 48h; an 80h recording trims to 72h.\n"
            "Recordings shorter than the smaller value will fail."
        )

        self._trim_hint_label = QLabel()
        self._trim_hint_label.setWordWrap(True)
        self._trim_hint_label.setStyleSheet("color: #666; font-size: 10px;")

        form.addRow(fs_lbl, self.fs_original)
        form.addRow(ds_lbl, ds_row)
        form.addRow(trim_lbl, self.trim_to)
        form.addRow("", self._trim_hint_label)

        root.addWidget(settings_gb)

        self.btn_run = QPushButton("Run preprocessing")
        root.addWidget(self.btn_run)

        # ----- Log -----
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(300)
        self.log_box.setPlaceholderText("Status messages will appear here...")
        root.addWidget(self.log_box)

        # Post-run hint (hidden until a run succeeds)
        self._hint_frame = QFrame()
        self._hint_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._hint_frame.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QHBoxLayout(self._hint_frame)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        hint_lbl = QLabel("✓ Done. Preprocessed EDFs written to standard.")
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
        self.trim_to.changed.connect(self._update_trim_hint)

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
            self._scan_label.setText(
                f"Found {n} file{'s' if n != 1 else ''} · could not read durations"
            )
            self._scan_label.setStyleSheet(self._STYLE_NORMAL)
            return

        min_hrs = self._min_duration_hrs
        max_hrs = max(durations)
        if abs(max_hrs - min_hrs) < _SAME_DURATION_THRESHOLD:
            dur_str = f"all {_fmt_hrs(min_hrs)}"
        else:
            dur_str = f"{_fmt_hrs(min_hrs)} – {_fmt_hrs(max_hrs)}"

        self._scan_label.setText(f"Found {n} file{'s' if n != 1 else ''} · {dur_str}")
        self._update_trim_hint()

    def _update_trim_hint(self) -> None:
        trim_vals = sorted(self.trim_to.value())
        trim_min, trim_max = trim_vals[0], trim_vals[1]

        if not self._durations_hrs:
            # No durations known yet — show the rule in plain English
            self._trim_hint_label.setText(
                f"Each EDF trims to the longest target that fits its duration. "
                f"Recordings shorter than {trim_min}h will fail."
            )
            self._trim_hint_label.setStyleSheet("color: #666; font-size: 10px;")
            self._scan_label.setStyleSheet(self._STYLE_NORMAL)
            return

        counts: dict[int, int] = {trim_min: 0, trim_max: 0}
        n_error = 0
        for d in self._durations_hrs:
            if d >= trim_max:
                counts[trim_max] += 1
            elif d >= trim_min:
                counts[trim_min] += 1
            else:
                n_error += 1

        parts = []
        for val in (trim_max, trim_min):
            if counts[val]:
                parts.append(f"{counts[val]} recording{'s' if counts[val] != 1 else ''} → {val}h")

        if n_error:
            self._trim_hint_label.setText(
                (f"{', '.join(parts)} · " if parts else "")
                + f"⚠ {n_error} recording{'s' if n_error != 1 else ''} shorter than {trim_min}h will fail"
            )
            self._trim_hint_label.setStyleSheet("color: #c0392b; font-size: 10px;")
            self._scan_label.setStyleSheet(self._STYLE_WARNING)
        else:
            self._trim_hint_label.setText(", ".join(parts))
            self._trim_hint_label.setStyleSheet("color: #1a5c1a; font-size: 10px;")
            self._scan_label.setStyleSheet(self._STYLE_NORMAL)

    def _log(self, msg: str):
        self.log_box.appendPlainText(msg)
        QApplication.processEvents()

    def _on_preprocess_done(self):
        Manifest.build_from_standard(self.project_root)
        self.btn_run.setEnabled(True)
        self._hint_frame.setVisible(True)

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
            msg = f"Target folder will default to '{self.default_target_dir}'.\nContinue?"
            btn = QMessageBox.question(self, "No Target Folder Selected", msg)
            if btn != QMessageBox.StandardButton.Yes:
                return

            target_dir = self.default_target_dir
            self.target_name_edit.setText(str(target_dir))
            self.target_name_edit.setToolTip(str(target_dir))

        # Pull a snapshot from the UI
        params = {
            "fs": int(self.fs_original.value()),
            "downsample": int(self.downsample.value()),
            "trim_to": list(self.trim_to.value()),
        }

        existing = list(target_dir.glob("*_PREPROCESSED.edf")) if target_dir.is_dir() else []
        if existing:
            btn = QMessageBox.question(
                self,
                "Files Already Exist",
                f"{len(existing)} preprocessed EDF(s) already exist in:\n{target_dir}\n\n"
                "Re-running will overwrite them. Continue?",
            )
            if btn != QMessageBox.StandardButton.Yes:
                return

        self.btn_run.setEnabled(False)
        self._hint_frame.setVisible(False)

        self._preprocess_thread = QThread(self)
        self._preprocess_worker = _PreprocessWorker(
            project_root=self.project_root,
            target_dir=target_dir,
            params=params,
        )
        self._preprocess_worker.log.connect(self._log)
        launch_worker(
            self._preprocess_thread,
            self._preprocess_worker,
            on_finished=self._on_preprocess_done,
            on_error=lambda msg: (
                self.btn_run.setEnabled(True),
                QMessageBox.critical(self, "Preprocess failed", msg),
            ),
        )


class _PreprocessWorker(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, *, project_root, target_dir, params, parent=None):
        super().__init__(parent)
        self.project_root = project_root
        self.target_dir = target_dir
        self.params = params

    def run(self):
        try:
            n = sum(1 for _ in self.project_root.glob("*.edf"))
            if not n:
                self.log.emit("No EDF files found.")
                self.finished.emit()
                return
            self.log.emit(f"Starting preprocessing on {n} file(s)…")
            t0 = time.perf_counter()
            outs = batch_preprocess(
                standard,
                self.project_root,
                target=self.target_dir,
                verbose=True,
                **self.params,
            )
            elapsed = time.perf_counter() - t0
            self.log.emit(f"Done: {len(outs)} file(s) written — {elapsed:.2f}s")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
