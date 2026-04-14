from pathlib import Path
from typing import Optional, List, Tuple
import dataclasses
import pickle

from ebb.process.psd_compute import batch_estimate, build_final_pkl

from PyQt6.QtCore import Qt, QObject, QThread, QTime, pyqtSignal
from ebb_viewer.widgets.worker_helpers import launch_worker
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QSpinBox, QDoubleSpinBox, QVBoxLayout, QPushButton,
    QMessageBox, QLabel, QHBoxLayout, QGroupBox, QCheckBox, QGridLayout,
    QSizePolicy, QLineEdit, QApplication, QPlainTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QFrame, QButtonGroup, QRadioButton,
    QScrollArea, QTimeEdit, QToolButton, QDialog, QDialogButtonBox,
)

from ebb_viewer.pipeline.manifest import Manifest, merged_psd_path
from ebb_viewer.pipeline import psd_params


DEFAULT_FS = 250
DEFAULT_NOISE_THRESH = 0.5
DEFAULT_WINSIZE = 180
DEFAULT_RADIUS = 0.5
DEFAULT_NSTD = 5.0
CH_LABELS = ["LFC", "RSC", "LSC"]


class MaskingSettingsDialog(QDialog):
    """Modal dialog for configuring optional masking/filtering for PSD computation."""

    def __init__(self, parent=None, *, swd_available: bool, swd_status_text: str,
                 project_root: Path):
        super().__init__(parent)
        self.setWindowTitle("Masking & Filtering Settings")
        self.setMinimumWidth(500)
        self._project_root = project_root
        self._swd_available = swd_available
        self._swd_status_text = swd_status_text
        self._ann_dir: Optional[Path] = None
        self._hw_recordings: Optional[List[Tuple]] = None  # cached [(rec_start, n_samples), ...]
        self._build_ui()
        self._wire()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── SWD Mask ──────────────────────────────────────────────────────────
        gb_swd = QGroupBox("SWD Masks")
        swd_v = QVBoxLayout(gb_swd)
        self._swd_grp = QButtonGroup(self)
        self._radio_swd_none = QRadioButton("No SWD mask")
        self._radio_swd_none.setChecked(True)
        self._radio_swd_mask = QRadioButton("Mask out SWDs")
        self._radio_swd_mask.setEnabled(self._swd_available)
        self._swd_grp.addButton(self._radio_swd_none, 0)
        self._swd_grp.addButton(self._radio_swd_mask, 1)
        swd_v.addWidget(self._radio_swd_none)
        swd_v.addWidget(self._radio_swd_mask)
        swd_hint = QLabel(
            "To use SWD masking, place one .mat file of SWD timestamps per animal "
            "in a swd/ folder in the project root (e.g. project/swd/AnimalID_*.mat)."
        )
        swd_hint.setWordWrap(True)
        swd_hint.setStyleSheet("font-size: 10px; color: #777; padding-left: 4px; padding-top: 2px;")
        swd_v.addWidget(swd_hint)
        self._lbl_swd_status = QLabel(self._swd_status_text)
        self._lbl_swd_status.setStyleSheet("font-size: 11px; padding-left: 4px;")
        swd_v.addWidget(self._lbl_swd_status)
        root.addWidget(gb_swd)

        # ── Annotation Mask ───────────────────────────────────────────────────
        gb_ann = QGroupBox("Annotation Mask")
        ann_v = QVBoxLayout(gb_ann)
        self.chk_ann = QCheckBox("Apply annotation mask")
        ann_v.addWidget(self.chk_ann)

        self._ann_body = QWidget()
        self._ann_body.setEnabled(False)
        ann_body_v = QVBoxLayout(self._ann_body)
        ann_body_v.setContentsMargins(0, 4, 0, 0)
        ann_body_v.setSpacing(6)

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
        root.addWidget(gb_ann)

        # ── Compute Hours ─────────────────────────────────────────────────────
        gb_hw = QGroupBox("Compute Hours")
        hw_v = QVBoxLayout(gb_hw)
        self.chk_hour_window = QCheckBox("Restrict to clock-time window")
        hw_v.addWidget(self.chk_hour_window)

        self._hw_body = QWidget()
        self._hw_body.setEnabled(False)
        hw_body_v = QVBoxLayout(self._hw_body)
        hw_body_v.setContentsMargins(0, 4, 0, 0)
        hw_body_v.setSpacing(6)

        # defined-windows list
        self._hw_windows_widget = QWidget()
        self._hw_windows_layout = QVBoxLayout(self._hw_windows_widget)
        self._hw_windows_layout.setContentsMargins(0, 0, 0, 0)
        self._hw_windows_layout.setSpacing(2)
        hw_body_v.addWidget(self._hw_windows_widget)

        # add-row
        add_row = QHBoxLayout()
        self.spin_add_start = QSpinBox()
        self.spin_add_start.setRange(0, 23)
        self.spin_add_start.setSuffix(" h")
        self.spin_add_end = QSpinBox()
        self.spin_add_end.setRange(0, 23)
        self.spin_add_end.setSuffix(" h")
        self.spin_add_end.setValue(1)
        self.btn_add_window = QPushButton("Add")
        self.btn_add_window.setFixedWidth(48)
        add_row.addWidget(self.spin_add_start)
        add_row.addWidget(QLabel("–"))
        add_row.addWidget(self.spin_add_end)
        add_row.addWidget(self.btn_add_window)
        add_row.addStretch()
        hw_body_v.addLayout(add_row)

        wrap_hint = QLabel("If end < start the window wraps midnight (e.g. 20–6 = dark phase).")
        wrap_hint.setWordWrap(True)
        wrap_hint.setStyleSheet("font-size: 10px; color: #777; padding-left: 4px;")
        hw_body_v.addWidget(wrap_hint)

        day_mode_row = QHBoxLayout()
        self._radio_hw_all = QRadioButton("All days")
        self._radio_hw_all.setChecked(True)
        self._radio_hw_sel = QRadioButton("Specific days:")
        self._hw_day_group = QButtonGroup(self)
        self._hw_day_group.addButton(self._radio_hw_all, 0)
        self._hw_day_group.addButton(self._radio_hw_sel, 1)
        self._hw_days_edit = QLineEdit()
        self._hw_days_edit.setPlaceholderText("0,1,2  (0 = recording start date)")
        self._hw_days_edit.setEnabled(False)
        day_mode_row.addWidget(self._radio_hw_all)
        day_mode_row.addWidget(self._radio_hw_sel)
        day_mode_row.addWidget(self._hw_days_edit, 1)
        hw_body_v.addLayout(day_mode_row)

        self._hw_partial_label = QLabel("")
        self._hw_partial_label.setWordWrap(True)
        hw_body_v.addWidget(self._hw_partial_label)

        hw_v.addWidget(self._hw_body)
        root.addWidget(gb_hw)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

    def _wire(self):
        self.chk_ann.toggled.connect(lambda checked: self._ann_body.setEnabled(checked))
        self.chk_ann.toggled.connect(self._refresh_ann_status)
        self.btn_ann_dir.clicked.connect(self._choose_ann_dir)
        self._ann_keyword_edit.textChanged.connect(self._refresh_ann_status)
        self.chk_hour_window.toggled.connect(self._on_hw_toggled)
        self._radio_hw_all.toggled.connect(lambda checked: self._hw_days_edit.setEnabled(not checked))
        self.btn_add_window.clicked.connect(self._on_add_window_clicked)
        self._hw_days_edit.textChanged.connect(self._refresh_hour_window_preview)

    def _on_hw_toggled(self, checked: bool) -> None:
        self._hw_body.setEnabled(checked)
        if checked:
            self._refresh_hour_window_preview()

    def _get_defined_windows(self) -> List[Tuple[float, float]]:
        """Return (hour_start, hour_end) for every row in the windows list."""
        windows = []
        for i in range(self._hw_windows_layout.count()):
            row = self._hw_windows_layout.itemAt(i).widget()
            if row is not None:
                windows.append((row.property("hw_start"), row.property("hw_end")))
        return windows

    def _add_window_row(self, hour_start: float, hour_end: float) -> None:
        row = QWidget()
        row.setProperty("hw_start", hour_start)
        row.setProperty("hw_end",   hour_end)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(QLabel(f"{int(hour_start)} h – {int(hour_end)} h"))
        hl.addStretch()
        status_lbl = QLabel("")
        status_lbl.setStyleSheet("font-size: 10px;")
        row.setProperty("status_label", status_lbl)
        hl.addWidget(status_lbl)
        btn = QPushButton("×")
        btn.setFixedWidth(24)
        btn.clicked.connect(lambda: self._remove_window_row(row))
        hl.addWidget(btn)
        self._hw_windows_layout.addWidget(row)
        self._refresh_hour_window_preview()

    def _remove_window_row(self, row: QWidget) -> None:
        self._hw_windows_layout.removeWidget(row)
        row.deleteLater()
        self._refresh_hour_window_preview()

    def _on_add_window_clicked(self) -> None:
        s = float(self.spin_add_start.value())
        e = float(self.spin_add_end.value())
        if s == e:
            QMessageBox.warning(self, "Invalid Window", "Start and end hour must differ.")
            return
        existing = self._get_defined_windows()
        for ws, we in existing:
            if self._windows_overlap(s, e, ws, we):
                QMessageBox.warning(
                    self, "Overlapping Window",
                    f"This window overlaps the existing window {int(ws)}–{int(we)} h."
                )
                return
        self._add_window_row(s, e)

    @staticmethod
    def _windows_overlap(s1: float, e1: float, s2: float, e2: float) -> bool:
        """Return True if two hour windows share any covered hour-of-day."""
        def covered(s, e):
            s, e = int(s), int(e)
            return set(range(s, 24)) | set(range(0, e)) if e < s else set(range(s, e))
        return bool(covered(s1, e1) & covered(s2, e2))

    def _refresh_hour_window_preview(self) -> None:
        # Clear all row badges first
        for i in range(self._hw_windows_layout.count()):
            row = self._hw_windows_layout.itemAt(i).widget()
            if row is not None:
                lbl = row.property("status_label")
                if lbl is not None:
                    lbl.setText("")

        if not self.chk_hour_window.isChecked():
            self._hw_partial_label.setText("")
            return
        hour_windows = self._get_defined_windows()
        if not hour_windows:
            self._hw_partial_label.setText("")
            return
        if self._hw_recordings is None:
            self._read_edf_headers()
        if not self._hw_recordings:
            self._hw_partial_label.setText("")
            return

        selected_days = None
        if self._radio_hw_sel.isChecked():
            raw = self._hw_days_edit.text().strip()
            try:
                selected_days = [int(x) for x in raw.split(",") if x.strip()]
            except ValueError:
                self._hw_partial_label.setText("")
                return

        from ebb.masking import hour_window_mask
        n_animals = len(self._hw_recordings)

        # Per-window stats: full_count, partial_count, total_seconds
        # Computed by calling hour_window_mask once per window so chunks are unambiguous.
        win_full    = [0] * len(hour_windows)
        win_partial = [0] * len(hour_windows)
        win_secs    = [0.0] * len(hour_windows)

        days_with_windows: set = set()
        total_secs = 0.0

        for idx, (hs, he) in enumerate(hour_windows):
            full_s = ((he - hs) % 24 or 24) * 3600
            for rec_start, n_samples in self._hw_recordings:
                _, used = hour_window_mask(rec_start, n_samples, DEFAULT_FS,
                                           [(hs, he)], selected_days)
                if not used:
                    continue
                animal_clipped = False
                for ws, we in used:
                    days_with_windows.add((ws.date() - rec_start.date()).days)
                    dur_s = (we - ws).total_seconds()
                    win_secs[idx] += dur_s
                    total_secs += dur_s
                    if dur_s < full_s - 30:
                        animal_clipped = True
                if animal_clipped:
                    win_partial[idx] += 1
                else:
                    win_full[idx] += 1

        # Update per-row badges
        rows = [self._hw_windows_layout.itemAt(i).widget()
                for i in range(self._hw_windows_layout.count())]
        rows = [r for r in rows if r is not None]
        for idx, row in enumerate(rows):
            lbl = row.property("status_label")
            if lbl is None:
                continue
            full    = win_full[idx]
            partial = win_partial[idx]
            total   = full + partial
            if total == 0:
                lbl.setText("✗ no data")
                lbl.setStyleSheet("font-size: 10px; color: #c0392b;")
            elif partial > 0:
                lbl.setText(f"⚠ clipped for {partial}/{n_animals} animals")
                lbl.setStyleSheet("font-size: 10px; color: #c77800;")
            else:
                lbl.setText(f"✓ complete for {full}/{n_animals} animals")
                lbl.setStyleSheet("font-size: 10px; color: #2a7a2a;")

        # Summary line
        any_windows = total_secs > 0
        has_partial = any(p > 0 for p in win_partial)
        msgs = []

        if selected_days is not None:
            missing = sorted(d for d in selected_days if d not in days_with_windows)
            if missing:
                days_str = ", ".join(str(d) for d in missing)
                msgs.append(f"⚠ Day{'s' if len(missing) != 1 else ''} {days_str} not found in recording")

        if not any_windows:
            self._hw_partial_label.setText("No windows overlap any recording.")
            self._hw_partial_label.setStyleSheet("color: #c0392b; font-size: 11px;")
        else:
            per_animal_h = (total_secs / n_animals) / 3600
            summary = f"~{per_animal_h:.1f} h / animal"
            if has_partial:
                msgs.insert(0, f"⚠ {summary} (some windows clipped at recording boundary)")
                self._hw_partial_label.setText("\n".join(msgs))
                self._hw_partial_label.setStyleSheet("color: #c77800; font-size: 11px;")
            elif msgs:
                msgs.insert(0, f"✓ {summary}")
                self._hw_partial_label.setText("\n".join(msgs))
                self._hw_partial_label.setStyleSheet("color: #c77800; font-size: 11px;")
            else:
                self._hw_partial_label.setText(f"✓ {summary}")
                self._hw_partial_label.setStyleSheet("color: #2a7a2a; font-size: 11px;")

    def _read_edf_headers(self) -> None:
        """Cache (rec_start, n_samples) for all standard EDFs."""
        standard_dir = self._project_root / "standard"
        if not standard_dir.is_dir():
            return
        edfs = sorted(standard_dir.glob("*PROCESSED.edf"))
        if not edfs:
            return
        import warnings
        from datetime import datetime as _datetime
        from openseize.file_io import edf as edf_io
        recordings = []
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=ResourceWarning)
            for edf_path in edfs:
                try:
                    with edf_io.Reader(str(edf_path)) as r:
                        rec_start = _datetime.strptime(
                            f"{r.header.start_date} {r.header.start_time}", "%d.%m.%y %H.%M.%S"
                        )
                        recordings.append((rec_start, r.shape[-1]))
                except Exception:
                    pass
        self._hw_recordings = recordings

    def _on_accept(self):
        if self.chk_hour_window.isChecked():
            if not self._get_defined_windows():
                QMessageBox.warning(self, "No Windows", "Add at least one hour window.")
                return
            if self._radio_hw_sel.isChecked():
                raw = self._hw_days_edit.text().strip()
                try:
                    [int(x) for x in raw.split(",") if x.strip()]
                except ValueError:
                    QMessageBox.warning(
                        self, "Invalid Days", "Day indices must be comma-separated integers."
                    )
                    return
        self.accept()

    def _choose_ann_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Annotation Directory", str(self._project_root)
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
            return
        manifest = Manifest.load(self._project_root)
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

    def load_params(self, params: dict) -> None:
        if params.get("swd_mode") == "mask_out" and self._swd_available:
            self._radio_swd_mask.setChecked(True)
        else:
            self._radio_swd_none.setChecked(True)
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
        if params.get("hw_enabled"):
            windows = params.get("hour_windows") or (
                [params["hour_window"]] if params.get("hour_window") else []
            )
            for hw in windows:
                self._add_window_row(float(hw[0]), float(hw[1]))
            if params.get("selected_days") is not None:
                self._radio_hw_sel.setChecked(True)
                self._hw_days_edit.setText(",".join(str(d) for d in params["selected_days"]))
            self.chk_hour_window.setChecked(True)

    def get_params(self) -> dict:
        hw_enabled = self.chk_hour_window.isChecked()
        params = {
            "swd_mode": "mask_out" if self._radio_swd_mask.isChecked() else "none",
            "ann_enabled": self.chk_ann.isChecked(),
            "ann_dir": self._ann_dir,
            "ann_keywords": self._ann_keyword_edit.text().strip(),
            "ann_match_mode": "exact" if self._radio_ann_exact.isChecked() else "contains",
            "ann_pad_before": self._ann_pad_before.value(),
            "ann_pad_after": self._ann_pad_after.value(),
            "hw_enabled": hw_enabled,
            "hour_windows": self._get_defined_windows() if hw_enabled else None,
            "selected_days": None,
        }
        if hw_enabled and self._radio_hw_sel.isChecked():
            raw = self._hw_days_edit.text().strip()
            params["selected_days"] = [int(x) for x in raw.split(",") if x.strip()]
        return params


class PSDPage(QWidget):

    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.standard_folder: Optional[Path] = None
        self._computing = False
        self._masking_params: dict = {}
        self._swd_available: bool = False
        self._swd_status_text: str = ""

        self._build_ui()
        self._wire()
        self._update_masking_summary()
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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 8, 8, 8)

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

        self.combo_table.setMaximumHeight(150)
        self.combo_table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum
        )

        combo_v.addWidget(self.combo_table)

        self._merged_pkl_label = QLabel()
        self._merged_pkl_label.setStyleSheet("font-size: 10px; color: #555; padding-top: 2px;")
        combo_v.addWidget(self._merged_pkl_label)

        root.addWidget(self.combo_gb)

        # ----- Masking & Filtering summary bar -----
        masking_bar = QFrame()
        masking_bar.setFrameShape(QFrame.Shape.StyledPanel)
        masking_bar.setStyleSheet(
            "QFrame { background: #f7f7f7; border: 1px solid #d0d0d0; border-radius: 3px; }"
        )
        masking_bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        bar_layout = QHBoxLayout(masking_bar)
        bar_layout.setContentsMargins(10, 6, 6, 6)

        lbl_masking_hdr = QLabel("Masking & Filtering:")
        lbl_masking_hdr.setStyleSheet("font-size: 11px; color: #444;")
        bar_layout.addWidget(lbl_masking_hdr)

        self._masking_summary_lbl = QLabel()
        self._masking_summary_lbl.setStyleSheet("font-size: 11px;")
        bar_layout.addWidget(self._masking_summary_lbl, 1)

        self._btn_configure_masking = QPushButton("Configure…")
        self._btn_configure_masking.setFixedWidth(90)
        bar_layout.addWidget(self._btn_configure_masking)

        root.addWidget(masking_bar)

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
        self.log_box.setMinimumHeight(140)
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
        self.btn_run_pipeline.clicked.connect(self._run_pipeline_clicked)
        self._btn_adv.clicked.connect(self._toggle_advanced)
        self._btn_configure_masking.clicked.connect(self._open_masking_dialog)

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


    def _refresh_swd_status(self):
        swd_dir = self.project_root / "swd"
        if not swd_dir.is_dir():
            self._swd_available = False
            self._swd_status_text = "swd/ not found in project root"
        else:
            mat_count = sum(1 for _ in swd_dir.glob("*.mat"))
            if mat_count == 0:
                self._swd_available = False
                self._swd_status_text = "swd/ found — no .mat files"
            else:
                n_animals = sum(1 for _ in Manifest.load(self.project_root))
                if n_animals > 0 and mat_count != n_animals:
                    self._swd_status_text = (
                        f"⚠ {mat_count} .mat {'file' if mat_count == 1 else 'files'} in swd/ "
                        f"(expected {n_animals})"
                    )
                else:
                    self._swd_status_text = (
                        f"✓ {mat_count} .mat {'file' if mat_count == 1 else 'files'} in swd/"
                    )
                self._swd_available = True
        # If SWD mask was selected but is no longer available, fall back to none
        if not self._swd_available and self._masking_params.get("swd_mode") == "mask_out":
            self._masking_params["swd_mode"] = "none"
            self._update_masking_summary()
        self._validate()

    def _open_masking_dialog(self):
        dlg = MaskingSettingsDialog(
            self,
            swd_available=self._swd_available,
            swd_status_text=self._swd_status_text,
            project_root=self.project_root,
        )
        dlg.load_params(self._masking_params)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._masking_params = dlg.get_params()
            self._update_masking_summary()
            self._validate()

    def _update_masking_summary(self):
        p = self._masking_params
        parts = []

        if p.get("swd_mode") == "mask_out":
            parts.append('<span style="color:#1a6b1a">SWD: masked ✓</span>')
        else:
            parts.append('<span style="color:#888">SWD: off</span>')

        if p.get("ann_enabled"):
            kw = p.get("ann_keywords", "")
            short = (kw[:14] + "…") if len(kw) > 14 else kw
            parts.append(f'<span style="color:#1a6b1a">Annotation: &quot;{short}&quot; ✓</span>')
        else:
            parts.append('<span style="color:#888">Annotation: off</span>')

        if p.get("hw_enabled"):
            windows = p.get("hour_windows") or []
            wins_str = ", ".join(f"{int(w[0])}–{int(w[1])}h" for w in windows) or "?"
            parts.append(f'<span style="color:#1a5c8a">Hours: {wins_str} ✓</span>')
        else:
            parts.append('<span style="color:#888">Hours: off</span>')

        self._masking_summary_lbl.setText("  ·  ".join(parts))

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
        self._masking_params = {
            "swd_mode": params.get("swd_mode", "none"),
            "ann_enabled": bool(params.get("ann_enabled", False)),
            "ann_dir": Path(params["ann_dir"]) if params.get("ann_dir") else None,
            "ann_keywords": params.get("ann_keywords", ""),
            "ann_match_mode": params.get("ann_match_mode", "contains"),
            "ann_pad_before": params.get("ann_pad_before", 0.0),
            "ann_pad_after": params.get("ann_pad_after", 10.0),
            "hw_enabled": bool(params.get("hw_enabled", False)),
            "hour_windows": params.get("hour_windows") or (
                [params["hour_window"]] if params.get("hour_window") else None
            ),
            "selected_days": params.get("selected_days"),
        }
        self._update_masking_summary()

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
        if self._masking_params.get("swd_mode") == "mask_out":
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

        mp = self._masking_params
        ann_params = None
        if mp.get("ann_enabled") and mp.get("ann_dir") is not None:
            ann_dir = mp["ann_dir"]
            ann_params = {
                "ann_dir": ann_dir,
                "keywords": [k.strip() for k in mp.get("ann_keywords", "").split(",") if k.strip()],
                "match_mode": mp.get("ann_match_mode", "contains"),
                "pad_before_sec": mp.get("ann_pad_before", 0.0),
                "pad_after_sec": mp.get("ann_pad_after", 10.0),
            }

        if mp.get("hw_enabled"):
            params["hour_windows"]  = mp.get("hour_windows")
            params["selected_days"] = mp.get("selected_days")
            params["hw_enabled"] = True
        else:
            params["hw_enabled"] = False

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
        if self._masking_params.get("ann_enabled"):
            ann_dir = self._masking_params.get("ann_dir")
            if ann_dir is None or not Path(ann_dir).is_dir():
                ann_ok = False
            elif not self._masking_params.get("ann_keywords", "").strip():
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
            ann_dir = self._masking_params.get("ann_dir")
            if ann_dir is None or not Path(ann_dir).is_dir():
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
            saved["hw_enabled"] = self.params.get("hw_enabled", False)
            if self.params.get("hw_enabled"):
                saved["hour_windows"]  = self.params.get("hour_windows")
                saved["selected_days"] = self.params.get("selected_days")
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
