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

Layout: the left column lists the animals (flagged and already applied) with their
mask-file status, then collapsed sections for the video offset CSV, the run's PSD
parameters and a how-to. The right Run panel has the PSD run, a summary of the rerun, a
readiness checklist, the Apply button, the post-run hint and the log.
"""

import csv as _csv
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ebb.process.psd_compute import rerun_with_drink_masks
from ebb.process.state_presets import PRESET_DISPLAY
from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.pipeline.naming import drink_mask_rel
from ebb_viewer.pipeline.theme import apply_primary_button, zone_header_qss
from ebb_viewer.widgets.collapsible_section import CollapsibleSection
from ebb_viewer.widgets.readiness import Check, blockers, checks_html, first_fix, fix_button_text
from ebb_viewer.widgets.worker_helpers import launch_worker

# Keys in psd_params.json that psds.py adds or reshapes (the swd_mode / ann_* post-processing)
# and that must not reach rerun_with_drink_masks. The mask widget's own keys (use_swd_mask,
# swd_pad, drink_pad, ...) are stripped downstream by ``_UI_ONLY_KWARGS`` in psd_compute.
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

_RUN_PANEL_WIDTH_PX = 380

_HOW_TO = (
    "Provide one <b>.npy</b> file per animal at <b>drink_masks/&lt;AnimalID&gt;.npy</b>: a "
    "<b>1 Hz boolean array</b> where True marks drinking-event samples. (Animal ID is the part "
    "before the first <code>_</code> in the EDF filename, e.g. <code>Mice-1234</code>.)<br><br>"
    "If the video and EEG don't start at the same time, also place a single CSV in "
    "<b>drink_masks/</b> with columns <b>Animal,Offset</b> (Offset in seconds, positive = video "
    "starts later) to align them.<br><br>"
    "PSD parameters are loaded from the selected run (read-only)."
)


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
        self._fix_page: str | None = None

        self._build_ui()
        self._wire()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_run_selector()

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ----- Left column: animals + collapsed details -----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 8, 8, 8)

        hdr = QHBoxLayout()
        lbl = QLabel("Drink Mask Rerun")
        lbl.setStyleSheet("font-weight: bold; font-size: 15px;")
        hdr.addWidget(lbl)
        hdr.addStretch(1)
        self.btn_refresh = QPushButton("Refresh")
        hdr.addWidget(self.btn_refresh)
        root.addLayout(hdr)

        desc = QLabel(
            "Recompute PSDs for animals flagged <b>needs_drink_mask</b> using per-animal "
            "drink-event masks from <b>drink_masks/</b>."
        )
        desc.setTextFormat(Qt.TextFormat.RichText)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(desc)

        zone_animals = QLabel("ANIMALS")
        zone_animals.setStyleSheet(zone_header_qss())
        root.addWidget(zone_animals)

        self._lbl_status = QLabel("No animals need drink masks in this run.")
        self._lbl_status.setStyleSheet("color: gray;")
        root.addWidget(self._lbl_status)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Animal", "Status", "Mask file"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setMinimumHeight(180)
        self._table.setVisible(False)
        root.addWidget(self._table)

        # Offset CSV (collapsed; the subtitle carries its state)
        offset_body = QWidget()
        offset_v = QVBoxLayout(offset_body)
        self._lbl_offset_hint = QLabel("")
        self._lbl_offset_hint.setWordWrap(True)
        self._lbl_offset_hint.setStyleSheet("font-size: 11px;")
        offset_v.addWidget(self._lbl_offset_hint)
        self._sec_offset = CollapsibleSection("Video offset CSV", offset_body, collapsed=True)
        root.addWidget(self._sec_offset)

        # PSD params (collapsed; the Run panel carries the short summary)
        params_body = QWidget()
        params_form = QFormLayout(params_body)
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
        root.addWidget(CollapsibleSection("PSD parameters (from the run)", params_body))

        how_lbl = QLabel(_HOW_TO)
        how_lbl.setTextFormat(Qt.TextFormat.RichText)
        how_lbl.setWordWrap(True)
        how_lbl.setStyleSheet("color: #555; font-size: 12px; padding: 4px;")
        root.addWidget(CollapsibleSection("How drink masks work", how_lbl))
        root.addStretch(1)

        # ----- Right column: Run panel -----
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        panel.setFixedWidth(_RUN_PANEL_WIDTH_PX)
        outer.addWidget(panel)
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(10, 8, 10, 8)
        pv.setSpacing(6)

        zone_run = QLabel("RUN")
        zone_run.setStyleSheet(zone_header_qss())
        pv.addWidget(zone_run)
        run_row = QHBoxLayout()
        run_row.addWidget(QLabel("PSD run:"))
        self.cmb_run = QComboBox()
        self.cmb_run.setMinimumWidth(140)
        run_row.addWidget(self.cmb_run, 1)
        pv.addLayout(run_row)
        self._run_info_lbl = QLabel("")
        self._run_info_lbl.setWordWrap(True)
        self._run_info_lbl.setStyleSheet("font-size: 11px; color: #666;")
        pv.addWidget(self._run_info_lbl)

        zone_will = QLabel("THIS RERUN")
        zone_will.setStyleSheet(zone_header_qss())
        pv.addWidget(zone_will)
        self._summary_lbl = QLabel("")
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setStyleSheet("font-size: 11px;")
        pv.addWidget(self._summary_lbl)

        zone_ready = QLabel("READINESS")
        zone_ready.setStyleSheet(zone_header_qss())
        pv.addWidget(zone_ready)
        self._checks_lbl = QLabel("")
        self._checks_lbl.setWordWrap(True)
        self._checks_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._checks_lbl.setStyleSheet("font-size: 11px;")
        pv.addWidget(self._checks_lbl)
        self.btn_fix = QPushButton("")
        self.btn_fix.clicked.connect(
            lambda: self._fix_page and self.navigate_to.emit(self._fix_page)
        )
        self.btn_fix.setVisible(False)
        pv.addWidget(self.btn_fix)

        # Post-run hint
        self._hint_frame = QFrame()
        self._hint_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._hint_frame.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QVBoxLayout(self._hint_frame)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        # Text set dynamically in _on_done to include the run name + full path.
        self._hint_lbl = QLabel("")
        self._hint_lbl.setWordWrap(True)
        hint_layout.addWidget(self._hint_lbl)
        btn_go_psd = QPushButton("→ PSD Visualizer")
        btn_go_psd.clicked.connect(lambda: self.navigate_to.emit("psd_review"))
        hint_layout.addWidget(btn_go_psd)
        self._hint_frame.setVisible(False)
        pv.addWidget(self._hint_frame)

        self.btn_apply = QPushButton("Apply Drink Masks")
        self.btn_apply.setEnabled(False)
        apply_primary_button(self.btn_apply)
        pv.addWidget(self.btn_apply)

        # Log (hidden until there is output)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(300)
        self.log_box.setMinimumHeight(120)
        self.log_box.setVisible(False)
        pv.addWidget(self.log_box, 1)
        pv.addStretch(1)

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
        self._refresh_offset()
        params = self._refresh_params()
        self._refresh_run_info()
        self._refresh_animals(params)

    def _drink_masks_dir(self) -> Path:
        return self.project_root / "drink_masks"

    def _offset_csvs(self) -> list[Path]:
        d = self._drink_masks_dir()
        return sorted(d.glob("*.csv")) if d.is_dir() else []

    def _detect_offset_csv(self) -> Path | None:
        """Return the unique offset CSV in drink_masks/, or None if 0 or >1 exist.

        Multiple CSVs are an ambiguity error — the readiness checklist blocks Apply and asks
        the user to keep only one. This mirrors the policy enforced by the Export Masks
        pipeline's resolve_paths.
        """
        csvs = self._offset_csvs()
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

    def _refresh_offset(self):
        """Fill the offset section: its subtitle is the state, its body the explanation."""
        csvs = self._offset_csvs()
        if len(csvs) > 1:
            self._sec_offset.set_subtitle(f"{len(csvs)} CSVs — ambiguous")
            self._lbl_offset_hint.setText(
                f"⚠ Multiple CSV files in drink_masks/: {', '.join(c.name for c in csvs)}. "
                "Keep only one so the page knows which offsets to use."
            )
            self._lbl_offset_hint.setStyleSheet("color: #c0392b; font-size: 11px;")
        elif not csvs:
            self._sec_offset.set_subtitle("none · video assumed aligned")
            self._lbl_offset_hint.setText(
                "Optional. Place a CSV with 'Animal' and 'Offset' (seconds) columns in "
                "drink_masks/ to align video timestamps with the EEG."
            )
            self._lbl_offset_hint.setStyleSheet("color: #666; font-size: 11px;")
        else:
            is_valid, msg = self._validate_offset_csv(csvs[0])
            self._sec_offset.set_subtitle(f"{csvs[0].name} · {'valid' if is_valid else 'invalid'}")
            self._lbl_offset_hint.setText(msg)
            self._lbl_offset_hint.setStyleSheet(
                ("color: #1a5c1a;" if is_valid else "color: #c0392b;") + " font-size: 11px;"
            )
        self._sec_offset.set_active(len(csvs) == 1)

    def _refresh_params(self) -> dict | None:
        """Fill the PSD-parameter details and the rerun summary; return the run's params."""
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
            self._summary_lbl.setText("No saved parameters for this run.")
            return None
        for key, lbl in self._param_labels.items():
            lbl.setStyleSheet("")
            if key == "channels":
                names = [CH_LABELS[i] for i in params.get("channels", []) if i < len(CH_LABELS)]
                lbl.setText(", ".join(names) if names else "—")
            else:
                lbl.setText(str(params.get(key, "—")))

        hours_text = None
        if params.get("hw_enabled"):
            windows = params.get("hour_windows") or []
            wins_str = ", ".join(f"{int(w[0])}–{int(w[1])}h" for w in windows) or "?"
            days = params.get("selected_days")
            day_str = "all days" if days is None else f"days {', '.join(str(d) for d in days)}"
            hours_text = f"{wins_str}  ({day_str})"
            self._lbl_compute_hours.setText(hours_text)
            self._lbl_compute_hours.setStyleSheet("color: #1a5c8a; font-weight: bold;")
        else:
            self._lbl_compute_hours.setText("off (all hours included)")
            self._lbl_compute_hours.setStyleSheet("color: gray;")

        states = psd_params.states_from_params(params)
        states_text = ", ".join(PRESET_DISPLAY.get(s, s) for s in states)
        self._lbl_states.setText(states_text)
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

        ann_on = bool(params.get("ann_enabled") and params.get("ann_dir"))
        kw = params.get("ann_keywords") or ""
        if ann_on:
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

        channels = ", ".join(CH_LABELS[i] for i in params.get("channels", []) if i < len(CH_LABELS))
        lines = [
            f"<b>Drink mask pad</b> {params.get('drink_pad', '—')} s · {states_text or 'no states'}",
            f"{params.get('fs', '—')} Hz · {channels or 'no channels'}",
        ]
        if swd_on:
            lines.append(f"• SWD mask on (pad {params.get('swd_pad', '?')} s)")
        if ann_on:
            lines.append(f"• Annotation mask on ({kw or 'no keywords'})")
        if hours_text:
            lines.append(f"• Compute hours {hours_text}")
        lines.append("Other filters as in the run (details on the left).")
        self._summary_lbl.setText("<br>".join(lines))
        return params

    def _refresh_run_info(self):
        run_name = self._current_run_name()
        params_file = self.project_root / "psd" / run_name / "psd_params.json"
        if not params_file.is_file():
            self._run_info_lbl.setText("")
            return
        when = datetime.fromtimestamp(params_file.stat().st_mtime).strftime("%Y-%m-%d")
        combo = Manifest.load(self.project_root).combo
        drink_pkl = self.project_root / "psd" / run_name / f"psds_{combo}_drink.pkl"
        applied = "drink-masked PSDs exist" if drink_pkl.exists() else "no drink-masked PSDs yet"
        self._run_info_lbl.setText(f"Computed {when} · {applied}")

    def _refresh_animals(self, params: dict | None):
        """Fill the animal table and the readiness checklist / Apply button."""
        run_name = self._current_run_name()
        try:
            manifest = Manifest.load(self.project_root)
            flagged = manifest.needs_drink_mask(run_name)
            ready = manifest.needs_drink_mask_rerun(run_name)
            applied = manifest.pending_drink_verification(run_name)
        except Exception:
            flagged, ready, applied = [], [], []

        ready_ids = {e.animal_id for e in ready}
        rows = [(e, "needs mask") for e in flagged] + [(e, "applied") for e in applied]
        self._table.setRowCount(0)
        for entry, status in rows:
            has_file = (self.project_root / drink_mask_rel(entry.animal_id)).is_file()
            missing = status == "needs mask" and entry.animal_id not in ready_ids
            mask_item = QTableWidgetItem("✓ found" if has_file else "✗ missing")
            mask_item.setForeground(QColor("#2a7a2a") if has_file else QColor("#aa2222"))
            items = [QTableWidgetItem(entry.animal_id), QTableWidgetItem(status), mask_item]
            if missing:
                for item in items:
                    item.setBackground(self._AMBER)
            row = self._table.rowCount()
            self._table.insertRow(row)
            for col, item in enumerate(items):
                self._table.setItem(row, col, item)
        self._table.setVisible(bool(rows))

        n_missing = len(flagged) - len(ready)
        if not rows:
            self._lbl_status.setText("No animals need drink masks in this run.")
            self._lbl_status.setStyleSheet("color: gray;")
        else:
            parts = []
            if flagged:
                parts.append(f"{len(flagged)} flagged")
                if ready:
                    parts.append(f"{len(ready)} ready to apply")
                if n_missing:
                    parts.append(f"{n_missing} missing a mask file")
            if applied:
                parts.append(f"{len(applied)} already applied")
            self._lbl_status.setText(" · ".join(parts))
            self._lbl_status.setStyleSheet("color: #8a4400;" if n_missing else "color: #1a5c1a;")

        checks = self._checks(run_name, params, flagged, ready)
        self._checks_lbl.setText(checks_html(checks))
        fix = first_fix(checks)
        self._fix_page = fix.page if fix else None
        self.btn_fix.setVisible(fix is not None)
        if fix:
            self.btn_fix.setText(fix_button_text(fix))
        self.btn_apply.setEnabled(not blockers(checks) and not self._computing)
        self.btn_apply.setText(
            f"Apply Drink Masks ({len(ready)})" if ready else "Apply Drink Masks"
        )

    def _checks(
        self, run_name: str, params: dict | None, flagged: list, ready: list
    ) -> list[Check]:
        """The readiness checklist behind the Apply button."""
        checks = [
            Check(
                params is not None,
                f"PSD run '{run_name}' has saved parameters"
                if params is not None
                else "No PSD run with saved parameters — compute PSDs first",
                page=None if params is not None else "psd_compute",
            )
        ]
        standard_ok = (self.project_root / "standard").is_dir()
        checks.append(
            Check(
                standard_ok,
                "Standard EDFs found" if standard_ok else "Standard folder not found",
                page=None if standard_ok else "preprocess",
            )
        )
        if not flagged:
            checks.append(
                Check(
                    False,
                    "No animals flagged needs_drink_mask in this run",
                    page="psd_review",
                )
            )
        else:
            ready_ids = {e.animal_id for e in ready}
            missing = [e.animal_id for e in flagged if e.animal_id not in ready_ids]
            if not ready:
                checks.append(
                    Check(
                        False,
                        "No mask files yet — place <AnimalID>.npy in drink_masks/ for: "
                        + ", ".join(missing),
                    )
                )
            elif missing:
                checks.append(
                    Check(
                        False,
                        f"{len(missing)} flagged animal{'s' if len(missing) != 1 else ''} "
                        f"without a mask file will be skipped: {', '.join(missing)}",
                        blocking=False,
                    )
                )
            else:
                checks.append(Check(True, "Mask files found for every flagged animal"))

        csvs = self._offset_csvs()
        if len(csvs) > 1:
            checks.append(Check(False, "Several CSVs in drink_masks/ — keep only one offset file"))
        elif csvs:
            valid, _ = self._validate_offset_csv(csvs[0])
            checks.append(
                Check(
                    valid,
                    f"Offset CSV {csvs[0].name} is valid"
                    if valid
                    else f"Offset CSV {csvs[0].name} needs 'Animal' and 'Offset' columns",
                )
            )
        else:
            checks.append(Check(True, "No offset CSV — video assumed aligned with the EEG"))
        return checks

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
        self.log_box.setVisible(True)
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
