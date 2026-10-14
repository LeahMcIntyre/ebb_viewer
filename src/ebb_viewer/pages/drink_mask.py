"""Drink Mask Rerun page — re-compute PSDs for animals flagged needs_drink_mask.

Workflow:
- During PSD Visualizer Pass 1, the user flags animals with visible drinking
  sidebands as ``needs_drink_mask``.
- The user drops per-animal ``<animal_id>.npy`` mask files in
  ``project_root/drink_masks/`` and (optionally) a single CSV with
  ``Animal,Offset`` columns to align video timestamps to the EEG start.
- This page validates inputs, then runs ``rerun_with_drink_masks`` off-thread
  to regenerate ``psds_drink.pkl`` and ``psds_<combo>_drink.pkl`` for
  the selected PSD run. On success it flags each animal
  ``drink_mask_applied`` in the manifest so Pass 2 review can pick them up.
"""

import csv as _csv
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ebb.process.psd_compute import rerun_with_drink_masks
from ebb.process.state_presets import PRESET_DISPLAY
from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.pipeline.theme import apply_primary_button
from ebb_viewer.widgets.worker_helpers import launch_worker

# Keys present in psd_params.json that are UI/config only and must be stripped
# before forwarding to rerun_with_drink_masks / estimate_psd. List must mirror
# what psds.py writes beyond the raw estimate_psd kwargs. New mask-widget keys
# (drink_pad, use_drink_mask, use_swd_mask, swd_pad, etc.) are NOT written by
# psds.py and therefore don't appear in psd_params.json — no need to strip them
# until/unless psds.py is migrated to the shared MaskParamsWidget.
_UI_ONLY_PARAM_KEYS = frozenset(
    {
        "swd_mode",
        "ann_enabled",
        "ann_dir",
        "ann_keywords",
        "ann_match_mode",
        "ann_pad_before",
        "ann_pad_after",
    }
)

CH_LABELS = ["LFC", "RSC", "LSC"]


class DrinkMaskPage(QWidget):
    """Sidebar page #8 — drives the drink-mask rerun for a selected PSD run."""

    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)

    # Highlight color for rows whose .npy is missing.
    _AMBER = QColor("#fff3cd")

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._computing = False
        self._pending_animal_ids: list[str] = []
        self._pending_run_name: str = ""

        self._build_ui()
        self._wire()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_run_selector()

    def _build_ui(self):
        root = QVBoxLayout(self)

        hdr = QHBoxLayout()
        lbl = QLabel("Drink Mask Rerun")
        lbl.setStyleSheet("font-weight: bold; font-size: 15px;")
        hdr.addWidget(lbl)
        hdr.addStretch(1)
        self.btn_refresh = QPushButton("Refresh")
        hdr.addWidget(self.btn_refresh)
        root.addLayout(hdr)

        desc = QLabel(
            "Recompute PSDs for animals flagged <b>'needs_drink_mask'</b> using "
            "per-animal drink-event masks. Provide one <b>.npy</b> file per "
            "animal at <b>project_root/drink_masks/&lt;AnimalID&gt;.npy</b> — a "
            "<b>1 Hz boolean array</b> where True marks drinking-event samples. "
            "(Animal ID is the part before the first <code>_</code> in the EDF "
            "filename, e.g. <code>Mice-1234</code>.)<br><br>"
            "If the video and EEG don't start at the same time, also place a "
            "single CSV in <b>drink_masks/</b> with columns <b>Animal,Offset</b> "
            "(Offset in seconds, positive = video starts later) to align them."
            "<br><br>"
            "PSD params are loaded from the selected run (read-only)."
        )
        desc.setTextFormat(Qt.TextFormat.RichText)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(desc)

        # ----- Run selector -----
        run_gb = QGroupBox("Run")
        run_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        run_form = QFormLayout(run_gb)
        self.cmb_run = QComboBox()
        self.cmb_run.setMinimumWidth(180)
        run_form.addRow("PSD Run:", self.cmb_run)
        root.addWidget(run_gb)

        # ----- Group 1: Paths -----
        self.gb_paths = QGroupBox("Paths")
        self.gb_paths.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        paths_form = QFormLayout(self.gb_paths)

        self.lbl_drink_dir = QLineEdit()
        self.lbl_drink_dir.setReadOnly(True)
        paths_form.addRow("Drink Masks Folder:", self.lbl_drink_dir)

        self._lbl_mask_count = QLabel()
        paths_form.addRow("Mask files found:", self._lbl_mask_count)

        self.lbl_offset_csv = QLineEdit("None")
        self.lbl_offset_csv.setReadOnly(True)
        offset_tooltip = (
            "Optional CSV in drink_masks/ with columns:\n"
            "  Animal  — animal ID (the part before the first '_', e.g. 'Mice-1234')\n"
            "  Offset  — seconds the video starts after the EEG recording begins\n"
            "            (positive = video starts later; use 0 if simultaneous)"
        )
        self.lbl_offset_csv.setToolTip(offset_tooltip)

        offset_row_lbl = QLabel("Video Offset CSV:")
        offset_row_lbl.setToolTip(offset_tooltip)
        paths_form.addRow(offset_row_lbl, self.lbl_offset_csv)

        # Text + style filled in by _refresh_paths; start empty.
        self._lbl_offset_hint = QLabel("")
        self._lbl_offset_hint.setWordWrap(True)
        self._lbl_offset_hint.setStyleSheet("font-size: 11px; padding-left: 2px;")

        paths_form.addRow("", self._lbl_offset_hint)
        root.addWidget(self.gb_paths)

        # ----- Group 2: PSD Params (read-only) -----
        self.gb_params = QGroupBox("PSD Parameters (from selected run)")
        self.gb_params.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        params_form = QFormLayout(self.gb_params)

        self._param_labels: dict[str, QLabel] = {}
        for key, display in [
            ("fs", "Sampling freq (Hz)"),
            ("channels", "Channels"),
            ("comm_value", "Commutator threshold (µV)"),
            ("winsize", "SD window (s)"),
            ("radius", "SD radius (s)"),
            ("nstd", "SD z-threshold"),
            ("noise_thresh", "Spindle noise threshold"),
            ("drink_pad", "Drink mask pad (s)"),
        ]:
            lbl_w = QLabel("—")
            self._param_labels[key] = lbl_w
            params_form.addRow(display + ":", lbl_w)

        self._lbl_compute_hours = QLabel("—")
        params_form.addRow("Compute hours:", self._lbl_compute_hours)

        self._lbl_states = QLabel("—")
        params_form.addRow("States:", self._lbl_states)

        self._lbl_swd = QLabel("—")
        self._lbl_swd.setWordWrap(True)
        params_form.addRow("SWD mask:", self._lbl_swd)

        self._lbl_ann = QLabel("—")
        self._lbl_ann.setWordWrap(True)
        params_form.addRow("Annotation mask:", self._lbl_ann)

        root.addWidget(self.gb_params)

        # ----- Group 3: Animals pending drink mask -----
        self.gb_animals = QGroupBox("Animals Pending Drink Mask Rerun")
        animals_v = QVBoxLayout(self.gb_animals)

        self._lbl_status = QLabel("No animals pending drink mask rerun.")
        self._lbl_status.setStyleSheet("color: gray;")
        animals_v.addWidget(self._lbl_status)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Animal", "PSD Status", "Mask"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 130)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(2, 110)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setVisible(False)
        animals_v.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_apply = QPushButton("Apply Drink Masks")
        self.btn_apply.setEnabled(False)
        apply_primary_button(self.btn_apply)
        btn_row.addWidget(self.btn_apply)
        animals_v.addLayout(btn_row)

        root.addWidget(self.gb_animals)

        # ----- Log -----
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(300)
        self.log_box.setPlaceholderText("Status messages will appear here…")
        root.addWidget(self.log_box)

        # Post-run hint
        self._hint_frame = QFrame()
        self._hint_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._hint_frame.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QHBoxLayout(self._hint_frame)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        # Text set dynamically in _on_done to include the run name + full path.
        self._hint_lbl = QLabel("")
        self._hint_lbl.setWordWrap(True)
        hint_layout.addWidget(self._hint_lbl, 1)
        btn_go_psd = QPushButton("→ PSD Visualizer")
        btn_go_psd.clicked.connect(lambda: self.navigate_to.emit("psd_review"))
        hint_layout.addWidget(btn_go_psd)
        self._hint_frame.setVisible(False)
        root.addWidget(self._hint_frame)

        # Styling
        run_gb.setObjectName("runBox")
        self.gb_paths.setObjectName("pathsBox")
        self.gb_params.setObjectName("paramsBox")
        self.gb_animals.setObjectName("animalsBox")
        self.setStyleSheet("""
        QGroupBox#runBox, QGroupBox#pathsBox, QGroupBox#paramsBox, QGroupBox#animalsBox { font: 550; }
        QGroupBox#runBox *, QGroupBox#pathsBox *, QGroupBox#paramsBox *, QGroupBox#animalsBox * { font: 400; }
        """)

    def _wire(self):
        self.btn_refresh.clicked.connect(self._refresh_run_selector)
        self.btn_apply.clicked.connect(self._apply_clicked)
        self.cmb_run.currentIndexChanged.connect(self._on_run_changed)

    # ------------- Run selector -------------

    def _current_run_name(self) -> str:
        return self.cmb_run.currentText() or "default"

    def _refresh_run_selector(self):
        current = self.cmb_run.currentText()
        runs = psd_params.list_runs(self.project_root)
        self.cmb_run.blockSignals(True)
        self.cmb_run.clear()
        for r in runs:
            self.cmb_run.addItem(r)
        self.cmb_run.blockSignals(False)
        if current in runs:
            self.cmb_run.setCurrentText(current)
        elif runs:
            self.cmb_run.setCurrentIndex(0)
        self._refresh()

    def _on_run_changed(self):
        self._refresh()

    # ------------- Data refresh -------------

    def _refresh(self):
        self._refresh_paths()
        self._refresh_params()
        self._refresh_animals()

    def _drink_masks_dir(self) -> Path:
        return self.project_root / "drink_masks"

    def _detect_offset_csv(self) -> Path | None:
        """Return the unique offset CSV in drink_masks/, or None if 0 or >1 exist.

        Multiple CSVs are an ambiguity error — caller surfaces a message
        instructing the user to keep only one. This mirrors the policy
        enforced by the Export Masks pipeline's resolve_paths.
        """
        d = self._drink_masks_dir()
        csvs = sorted(d.glob("*.csv")) if d.is_dir() else []
        return csvs[0] if len(csvs) == 1 else None

    def _validate_offset_csv(self, csv: Path) -> tuple[bool, str]:
        """Inspect the CSV header. Return ``(is_valid, message)`` for display."""
        try:
            with csv.open(newline="") as fh:
                header = next(_csv.reader(fh))
        except Exception:
            return False, "Could not read CSV headers."
        missing = {"Animal", "Offset"} - {c.strip() for c in header}
        if missing:
            return False, (
                f"⚠ CSV is missing required column(s): {', '.join(sorted(missing))}. "
                "Expected: 'Animal' (ID before first '_') and 'Offset' (seconds video starts after EEG)."
            )
        return True, (
            "✓ CSV looks valid. 'Animal' = ID before first '_'; "
            "'Offset' = seconds the video starts after the EEG recording begins."
        )

    def _refresh_paths(self):
        d = self._drink_masks_dir()
        self.lbl_drink_dir.setText(str(d))
        if d.is_dir():
            n = sum(1 for _ in d.glob("*.npy"))
            if n:
                self._lbl_mask_count.setText(f"✓ {n} mask{'s' if n != 1 else ''}")
                self._lbl_mask_count.setStyleSheet("color: green;")
            else:
                self._lbl_mask_count.setText("No .npy files found")
                self._lbl_mask_count.setStyleSheet("color: orange;")
        else:
            self._lbl_mask_count.setText("Folder does not exist")
            self._lbl_mask_count.setStyleSheet("color: gray;")

        csvs = sorted(d.glob("*.csv")) if d.is_dir() else []
        if len(csvs) > 1:
            self.lbl_offset_csv.setText(f"{len(csvs)} CSVs found — ambiguous")
            self._lbl_offset_hint.setText(
                f"⚠ Multiple CSV files in drink_masks/: {', '.join(c.name for c in csvs)}. "
                "Keep only one so the page knows which offsets to use."
            )
            self._lbl_offset_hint.setStyleSheet(
                "color: #c0392b; font-size: 11px; padding-left: 2px;"
            )
            return
        if not csvs:
            self.lbl_offset_csv.setText("None")
            self._lbl_offset_hint.setText(
                "Place a CSV with 'Animal' and 'Offset' (seconds) columns in "
                "drink_masks/ to align video timestamps."
            )
            self._lbl_offset_hint.setStyleSheet(
                "color: #666; font-size: 11px; padding-left: 2px;"
            )
            return

        csv_path = csvs[0]
        self.lbl_offset_csv.setText(csv_path.name)
        is_valid, msg = self._validate_offset_csv(csv_path)
        self._lbl_offset_hint.setText(msg)
        self._lbl_offset_hint.setStyleSheet(
            ("color: #1a5c1a;" if is_valid else "color: #c0392b;")
            + " font-size: 11px; padding-left: 2px;"
        )

    def _refresh_params(self):
        run_name = self._current_run_name()
        params = psd_params.load(self.project_root, run_name)
        if params is None:
            for lbl in self._param_labels.values():
                lbl.setText("— (run Compute PSDs first)")
                lbl.setStyleSheet("color: gray;")
            for lbl in (
                self._lbl_compute_hours,
                self._lbl_states,
                self._lbl_swd,
                self._lbl_ann,
            ):
                lbl.setText("— (run Compute PSDs first)")
                lbl.setStyleSheet("color: gray;")
            return
        for key, lbl in self._param_labels.items():
            lbl.setStyleSheet("")
            if key == "channels":
                names = [CH_LABELS[i] for i in params.get("channels", []) if i < len(CH_LABELS)]
                lbl.setText(", ".join(names) if names else "—")
            else:
                lbl.setText(str(params.get(key, "—")))

        if params.get("hw_enabled"):
            windows = params.get("hour_windows") or []
            wins_str = ", ".join(f"{int(w[0])}–{int(w[1])}h" for w in windows) or "?"
            days = params.get("selected_days")
            day_str = "all days" if days is None else f"days {', '.join(str(d) for d in days)}"
            self._lbl_compute_hours.setText(f"{wins_str}  ({day_str})")
            self._lbl_compute_hours.setStyleSheet("color: #1a5c8a; font-weight: bold;")
        else:
            self._lbl_compute_hours.setText("off (all hours included)")
            self._lbl_compute_hours.setStyleSheet("color: gray;")

        states = psd_params.states_from_params(params)
        self._lbl_states.setText(", ".join(PRESET_DISPLAY.get(s, s) for s in states))
        self._lbl_states.setStyleSheet("color: #1a5c8a;")

        # SWD — accept either widget-shape ("use_swd_mask") or the post-processed
        # form psds.py writes ("swd_mode") so the row works for either source.
        swd_on = bool(params.get("use_swd_mask")) or params.get("swd_mode") == "mask_out"
        if swd_on:
            self._lbl_swd.setText(f"on (pad={params.get('swd_pad', '?')}s)")
            self._lbl_swd.setStyleSheet("color: #1a5c8a; font-weight: bold;")
        else:
            self._lbl_swd.setText("off")
            self._lbl_swd.setStyleSheet("color: gray;")

        if params.get("ann_enabled") and params.get("ann_dir"):
            kw = params.get("ann_keywords") or ""
            mode = params.get("ann_match_mode", "contains")
            pb = params.get("ann_pad_before", 0.0)
            pa = params.get("ann_pad_after", 0.0)
            self._lbl_ann.setText(
                f"on — dir: {params['ann_dir']}\n"
                f"keywords: {kw or '(none)'}  •  match: {mode}  •  pad: −{pb}s / +{pa}s"
            )
            self._lbl_ann.setStyleSheet("color: #1a5c8a; font-weight: bold;")
        else:
            self._lbl_ann.setText("off")
            self._lbl_ann.setStyleSheet("color: gray;")

    def _refresh_animals(self):
        run_name = self._current_run_name()
        try:
            manifest = Manifest.load(self.project_root)
            flagged = manifest.needs_drink_mask(run_name)
            ready = manifest.needs_drink_mask_rerun(run_name)
        except Exception:
            flagged = []
            ready = []

        if not flagged:
            self._lbl_status.setText("No animals pending drink mask rerun.")
            self._lbl_status.setStyleSheet("color: gray;")
            self._table.setVisible(False)
            self._table.setRowCount(0)
            self.btn_apply.setEnabled(False)
            self.btn_apply.setText("Apply Drink Masks")
            return

        ready_set = {e.animal_id for e in ready}
        n_ready = len(ready)
        n_missing = len(flagged) - n_ready

        parts = []
        if n_ready:
            parts.append(f"{n_ready} ready")
        if n_missing:
            parts.append(f"{n_missing} missing mask file")
        self._lbl_status.setText(f"{len(flagged)} animal(s) flagged — {', '.join(parts)}")
        self._lbl_status.setStyleSheet("color: #8a4400;" if n_missing else "color: #1a5c1a;")

        self._table.setRowCount(0)
        for entry in flagged:
            is_ready = entry.animal_id in ready_set
            row = self._table.rowCount()
            self._table.insertRow(row)
            items = [
                QTableWidgetItem(entry.animal_id),
                QTableWidgetItem("needs_drink_mask"),
                QTableWidgetItem("✓ found" if is_ready else "✗ missing"),
            ]
            items[2].setForeground(QColor("#2a7a2a") if is_ready else QColor("#aa2222"))
            if not is_ready:
                for item in items:
                    item.setBackground(self._AMBER)
            for col, item in enumerate(items):
                self._table.setItem(row, col, item)
        self._table.setVisible(True)

        has_params = psd_params.load(self.project_root, run_name) is not None
        self.btn_apply.setEnabled(n_ready > 0 and has_params and not self._computing)
        if not has_params:
            self.btn_apply.setText("Apply Drink Masks (run Compute PSDs first)")
        elif n_ready:
            self.btn_apply.setText(f"Apply Drink Masks ({n_ready} ready)")
        else:
            self.btn_apply.setText("Apply Drink Masks (place .npy files to enable)")

    # ------------- Apply action -------------

    def _apply_clicked(self):
        run_name = self._current_run_name()
        params = psd_params.load(self.project_root, run_name)
        if params is None:
            QMessageBox.critical(
                self,
                "No PSD Params",
                f"psd_params.json not found for run '{run_name}'. Run Compute PSDs first.",
            )
            return

        standard_folder = self.project_root / "standard"
        if not standard_folder.is_dir():
            QMessageBox.critical(self, "No Standard Folder", f"Expected: {standard_folder}")
            return

        manifest = Manifest.load(self.project_root)
        to_rerun = manifest.needs_drink_mask_rerun(run_name)
        if not to_rerun:
            return

        self._pending_animal_ids = [e.animal_id for e in to_rerun]
        self._pending_run_name = run_name

        offset_path = self._detect_offset_csv()
        swd_dir = (self.project_root / "swd") if params.get("swd_mode") == "mask_out" else None

        self._computing = True
        self._hint_frame.setVisible(False)
        self.btn_apply.setEnabled(False)
        self._log(
            f"Starting drink mask rerun for {len(self._pending_animal_ids)} animal(s) in run '{run_name}'…"
        )
        if swd_dir:
            self._log(f"  SWD mask: {swd_dir}")

        self.drink_thread = QThread(self)
        ann_params = None
        if params.get("ann_enabled") and params.get("ann_dir"):
            kw_raw = params.get("ann_keywords", "")
            ann_params = {
                "ann_dir": params["ann_dir"],
                "keywords": [k.strip() for k in kw_raw.split(",") if k.strip()],
                "match_mode": params.get("ann_match_mode", "contains"),
                "pad_before_sec": float(params.get("ann_pad_before", 0.0)),
                "pad_after_sec": float(params.get("ann_pad_after", 0.0)),
            }

        self.drink_worker = DrinkMaskRerunWorker(
            psd_dir=self.project_root / "psd",
            eeg_dir=standard_folder,
            spindle_root=self.project_root / "spindle_outputs",
            drink_dir=self._drink_masks_dir(),
            animal_ids=self._pending_animal_ids,
            combo=manifest.combo,
            offset_path=offset_path,
            params=params,
            run_name=run_name,
            swd_dir=swd_dir,
            ann_params=ann_params,
        )
        self.drink_worker.progress.connect(self._log)
        launch_worker(
            self.drink_thread, self.drink_worker, on_finished=self._on_done, on_error=self._on_error
        )

    def _on_done(self):
        # rerun_with_drink_masks is all-or-nothing: it raises on any per-animal
        # failure and we'd be in _on_error instead. Reaching here means every
        # animal in _pending_animal_ids completed successfully.
        self._computing = False
        manifest = Manifest.load(self.project_root)
        run_name = self._pending_run_name
        failed = []
        for animal_id in self._pending_animal_ids:
            try:
                manifest.flag_psd(animal_id, "drink_mask_applied", run_name)
            except Exception as e:
                failed.append(f"{animal_id}: {e}")
        manifest.save()
        self._pending_animal_ids = []
        if failed:
            msg = "\n".join(failed)
            self._log(f"WARNING: {len(failed)} flag(s) failed:\n{msg}")
            QMessageBox.warning(
                self,
                "Partial Failure",
                f"{len(failed)} animal(s) could not be flagged:\n\n{msg}",
            )
        self._log(
            f"Drink mask rerun complete. psds_drink.pkl and psds_{manifest.combo}_drink.pkl updated."
        )
        self.manifest_changed.emit()
        self._hint_lbl.setText(
            f"✓ Drink masks applied for run '{run_name}'. Review the updated PSDs in "
            f"PSD Visualizer (plot psd/{run_name}/psds_{manifest.combo}_drink.pkl)."
        )
        self._hint_frame.setVisible(True)
        self._refresh()

    def _on_error(self, msg: str):
        self._computing = False
        self._pending_animal_ids = []
        self._log(f"ERROR in drink mask rerun: {msg}")
        QMessageBox.critical(self, "Drink Mask Rerun Error", msg)
        self._refresh()

    def _log(self, msg: str):
        self.log_box.appendPlainText(msg)
        QApplication.processEvents()


class DrinkMaskRerunWorker(QObject):
    """Off-thread driver for `rerun_with_drink_masks`; emits progress/finished/error."""

    progress = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        psd_dir: Path,
        eeg_dir: Path,
        spindle_root: Path,
        drink_dir: Path,
        animal_ids: list[str],
        combo: str,
        offset_path,
        params: dict,
        run_name: str = "default",
        swd_dir: Path | None = None,
        ann_params: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.psd_dir = Path(psd_dir)
        self.eeg_dir = Path(eeg_dir)
        self.spindle_root = Path(spindle_root)
        self.drink_dir = Path(drink_dir)
        self.animal_ids = animal_ids
        self.combo = combo
        self.offset_path = offset_path
        self.params = params
        self.run_name = run_name
        self.swd_dir = Path(swd_dir) if swd_dir else None
        self.ann_params = ann_params

    def run(self):
        try:
            rerun_with_drink_masks(
                psd_dir=self.psd_dir,
                eeg_dir=self.eeg_dir,
                spindle_root=self.spindle_root,
                drink_dir=self.drink_dir,
                animal_ids=self.animal_ids,
                combo=self.combo,
                offset_path=self.offset_path,
                swd_dir=self.swd_dir,
                ncores=None,
                ann_params=self.ann_params,
                run_name=self.run_name,
                **{k: v for k, v in self.params.items() if k not in _UI_ONLY_PARAM_KEYS},
            )
            self.progress.emit("  → psds_drink.pkl updated.")
            self.progress.emit(f"  → psds_{self.combo}_drink.pkl regenerated.")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
