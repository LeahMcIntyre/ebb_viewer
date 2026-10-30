"""Preprocess page — trim, downsample, and standardize raw EDFs.

Inputs: ``.edf`` files in the project root with names matching
``AnimalID_anything.edf`` (the animal ID is the text before the first ``_``).
Outputs: trimmed + downsampled copies written to ``standard/``.

Trim policy: each EDF is trimmed to the longest target hour count that
fits its duration. Recordings shorter than the smallest target fail.
"""

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

from ebb.core.naming import parse_animal_id
from ebb.io.edf_header import header_fs
from ebb.preprocess.edf import batch as batch_preprocess
from ebb.preprocess.edf import standard
from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.pipeline.theme import apply_primary_button
from ebb_viewer.widgets.page_help import title_row
from ebb_viewer.widgets.trim_to_widget import TrimToWidget
from ebb_viewer.widgets.worker_helpers import launch_worker


def fs_mismatches(file_fs: dict[str, float], expected_fs: float) -> dict[str, float]:
    """``{file name: rate}`` for each scanned file whose header rate is not ``expected_fs``."""
    return {name: fs for name, fs in file_fs.items() if abs(fs - expected_fs) > 1e-6}


def _fmt_hrs(hours: float) -> str:
    h = int(hours)
    m = int(round((hours - h) * 60))
    return f"{h}h {m:02d}m"


DEFAULT_FS = 5000
DEFAULT_DOWNSAMPLE = 20
DEFAULT_TRIM_TO = [48, 72]  # hours

_SAME_DURATION_THRESHOLD = 1 / 60  # 1 minute — treat as identical


def duplicate_animal_edfs(paths: list[Path]) -> dict[str, list[str]]:
    """``{animal_id: [file names]}`` for animals that have more than one EDF in ``paths``.

    One animal with several EDFs in the project folder means a restarted recording whose chunks
    have not been combined yet (``ebb-combine edf``), or chunks left behind after combining.
    """
    by_animal: dict[str, list[str]] = {}
    for p in sorted(paths):
        by_animal.setdefault(parse_animal_id(p), []).append(p.name)
    return {a: names for a, names in by_animal.items() if len(names) > 1}


class PreprocessPage(QWidget):
    """Sidebar page #1 — preprocess raw EDFs into standard/."""

    navigate_to = pyqtSignal(str)

    _STYLE_NORMAL = "color: #666; font-size: 10px;"
    _STYLE_WARNING = "color: #e67e22; font-size: 10px;"
    _STYLE_ERROR = "color: #c0392b; font-size: 10px;"

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = project_root
        self.default_target_dir = project_root / "standard"
        self._durations_hrs: list[float] | None = None  # None = not yet scanned
        self._file_fs: dict[str, float] = {}  # header rate per scanned file
        self._is_running = False
        self._build_ui()
        self._wire()

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)

        lbl = title_row("Preprocess EDFs", "preprocess")
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

        self._scan_label = QLabel("(EDF scan pending)")
        self._scan_label.setStyleSheet(self._STYLE_NORMAL + " padding-top: 0px;")

        self.btn_rescan = QPushButton("Rescan")
        self.btn_rescan.setToolTip("Re-scan the project folder for EDF files")
        self.btn_rescan.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        scan_row = QWidget()
        scan_row_l = QHBoxLayout(scan_row)
        scan_row_l.setContentsMargins(0, 0, 0, 0)
        scan_row_l.setSpacing(8)
        scan_row_l.addWidget(self._scan_label, 1)
        scan_row_l.addWidget(self.btn_rescan)

        top_form.addRow("Project:", self.lbl_root)
        top_form.addRow("", scan_row)

        self._chunk_label = QLabel("")
        self._chunk_label.setWordWrap(True)
        self._chunk_label.setStyleSheet("color: #c0392b; font-size: 10px;")
        self._chunk_label.setVisible(False)
        top_form.addRow("", self._chunk_label)

        self._fs_label = QLabel("")
        self._fs_label.setWordWrap(True)
        self._fs_label.setStyleSheet("color: #c0392b; font-size: 10px;")
        self._fs_label.setVisible(False)
        top_form.addRow("", self._fs_label)
        top_form.addRow("Target Directory:", self.target_name_edit)

        fmt_lbl = QLabel(
            "ℹ EDF files must be named: <code>AnimalID_anything.edf</code> (the animal ID is the text before the first <code>_</code>)"
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

        self.trim_to = TrimToWidget(values=DEFAULT_TRIM_TO)

        trim_lbl = QLabel("Trim To (hrs)")
        trim_lbl.setToolTip(
            "1–4 fallback trim targets (hours).\n"
            "Each EDF is trimmed to the longest target that is ≤ its duration.\n"
            "Example with [48, 72]: a 60h recording trims to 48h; an 80h recording trims to 72h.\n"
            "Add or remove targets with [+] / [−]. "
            "Recordings shorter than the smallest target will fail."
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
        apply_primary_button(self.btn_run)
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
        self.btn_rescan.clicked.connect(self._scan_edfs)
        self.fs_original.valueChanged.connect(self._update_hz_label)
        self.downsample.valueChanged.connect(self._update_hz_label)
        self._update_hz_label()
        self.trim_to.changed.connect(self._update_trim_hint)

    def _update_hz_label(self) -> None:
        fs = self.fs_original.value()
        ds = self.downsample.value()
        hz = fs / ds if ds > 0 else 0.0
        if ds > 0 and hz.is_integer():
            self._hz_label.setText(f"→ {int(hz)} Hz output")
            self._hz_label.setStyleSheet("color: #555; font-size: 11px;")
        else:
            self._hz_label.setText(f"→ {hz:g} Hz output  ⚠ must be a whole number")
            self._hz_label.setStyleSheet("color: #c0392b; font-size: 11px;")
        self._update_fs_warning()
        self._sync_run_button()

    def _update_fs_warning(self) -> None:
        """Flag scanned files whose header rate differs from the entered original frequency."""
        bad = fs_mismatches(self._file_fs, self.fs_original.value())
        if not bad:
            self._fs_label.setVisible(False)
            self._fs_label.setText("")
            return
        shown = ", ".join(f"{n} ({fs:g} Hz)" for n, fs in list(bad.items())[:4])
        more = f" and {len(bad) - 4} more" if len(bad) > 4 else ""
        self._fs_label.setText(
            f"⚠ {len(bad)} of {len(self._file_fs)} file(s) are not at "
            f"{self.fs_original.value()} Hz: {shown}{more}. Fix the Original Sampling "
            "Frequency, or move the odd files out of this folder, before running."
        )
        self._fs_label.setVisible(True)

    def _sync_run_button(self) -> None:
        fs = self.fs_original.value()
        ds = self.downsample.value()
        valid = ds > 0 and (fs / ds).is_integer()
        rates_ok = not fs_mismatches(self._file_fs, fs)
        self.btn_run.setEnabled(valid and rates_ok and not self._is_running)

    def showEvent(self, event):
        super().showEvent(event)
        if self._durations_hrs is None:  # scan only once per session
            self._scan_edfs()

    def _scan_edfs(self) -> None:
        paths = sorted(self.project_root.glob("*.edf"))
        self._show_chunk_warning(paths)
        if not paths:
            self._file_fs = {}
            self._update_fs_warning()
            self._scan_label.setText("No EDF files found")
            self._scan_label.setStyleSheet(self._STYLE_ERROR)
            self._durations_hrs = []
            self._trim_hint_label.setText("")
            return

        durations: list[float] = []
        self._file_fs = {}
        n_skipped = 0
        for p in paths:
            try:
                with edf_io.Reader(p) as reader:
                    secs = reader.header["num_records"] * reader.header["record_duration"]
                    self._file_fs[p.name] = header_fs(reader.header)
                durations.append(secs / 3600.0)
            except (OSError, KeyError, ValueError):
                # Unreadable header / wrong format / corrupt file — count and
                # surface in the scan label so the user knows files were skipped.
                n_skipped += 1

        self._durations_hrs = durations
        self._update_fs_warning()
        self._sync_run_button()

        n = len(paths)
        if not durations:
            self._scan_label.setText(
                f"Found {n} file{'s' if n != 1 else ''} · could not read any durations"
            )
            self._scan_label.setStyleSheet(self._STYLE_ERROR)
            self._trim_hint_label.setText("")
            return

        min_hrs = min(durations)
        max_hrs = max(durations)
        if abs(max_hrs - min_hrs) < _SAME_DURATION_THRESHOLD:
            dur_str = f"all {_fmt_hrs(min_hrs)}"
        else:
            dur_str = f"{_fmt_hrs(min_hrs)} – {_fmt_hrs(max_hrs)}"

        skip_str = f" · {n_skipped} unreadable" if n_skipped else ""
        self._scan_label.setText(
            f"Found {n} file{'s' if n != 1 else ''} · {dur_str}{skip_str}"
        )
        self._update_trim_hint()

    def _show_chunk_warning(self, paths: list[Path]) -> None:
        """Warn when one animal has several EDFs in the folder (uncombined restart chunks)."""
        dupes = duplicate_animal_edfs(paths)
        if not dupes:
            self._chunk_label.setVisible(False)
            self._chunk_label.setText("")
            return
        shown = ", ".join(sorted(dupes)[:6]) + ("…" if len(dupes) > 6 else "")
        self._chunk_label.setText(
            f"⚠ {len(dupes)} animal{'s have' if len(dupes) != 1 else ' has'} more than one EDF "
            f"in this folder ({shown}). If these are restarted recordings, combine them first "
            "with ebb-combine (see the user guide) and move the original chunks out of the "
            "folder, or they will be preprocessed as separate files."
        )
        self._chunk_label.setVisible(True)

    def _update_trim_hint(self) -> None:
        trim_vals = sorted(self.trim_to.value())
        if not trim_vals:
            # TrimToWidget enforces min_count >= 1, so this is defensive.
            return
        trim_min = trim_vals[0]

        if not self._durations_hrs:
            # No durations known yet — show the rule in plain English
            self._trim_hint_label.setText(
                f"Each EDF trims to the longest target that fits its duration. "
                f"Recordings shorter than {trim_min}h will fail."
            )
            self._trim_hint_label.setStyleSheet("color: #666; font-size: 10px;")
            self._scan_label.setStyleSheet(self._STYLE_NORMAL)
            return

        # Bucket each recording into the largest target ≤ its duration; any
        # recording below trim_min is unprocessable.
        counts: dict[int, int] = {v: 0 for v in trim_vals}
        n_error = 0
        for d in self._durations_hrs:
            bucket = next((v for v in reversed(trim_vals) if d >= v), None)
            if bucket is None:
                n_error += 1
            else:
                counts[bucket] += 1

        parts = [
            f"{counts[v]} recording{'s' if counts[v] != 1 else ''} → {v}h"
            for v in reversed(trim_vals)
            if counts[v]
        ]

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
        self._is_running = False
        self._sync_run_button()
        self._hint_frame.setVisible(True)

    def _on_preprocess_error(self, msg: str) -> None:
        self._is_running = False
        self._sync_run_button()
        QMessageBox.critical(self, "Preprocess failed", msg)

    def _run_clicked(self):
        # Target dir is always project_root/standard — the UI just displays it.
        target_dir = self.default_target_dir

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

        self._is_running = True
        self._sync_run_button()
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
            on_error=self._on_preprocess_error,
        )


class _PreprocessWorker(QObject):
    """Off-thread worker that drives `batch_preprocess` and reports progress via log/finished/error signals."""

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
