"""PSD compute page — wraps :func:`ebb.process.psd_compute.batch_estimate`.

Drives the initial PSD computation step of the pipeline. Each run produces
one ``psds_<combo>.pkl`` per channel combination plus a merged
``psds_channel_merged.pkl`` consumed by the visualizer.

The page is structured as:

1. Folder selection + run name (PSD-specific)
2. Spindle output combos table (read-only summary)
3. ``MaskParamsWidget`` — shared editor for state-group selection,
   SD/spindle/SWD/annotation/hour-window mask params (same widget the
   Export Masks page uses, with ``show_drink_mask=False`` since the PSD
   compute step doesn't apply drink masks)
4. PSD output settings — channels + sampling frequency
5. Run button + status log + post-run hint

Run params (mask + filter knobs + states) round-trip through
``project/psd/<run_name>/psd_params.json``. Drink masking is intentionally
*not* applied here; the Drink Mask page re-applies it after PSD review.
"""

from __future__ import annotations

import dataclasses
import pickle
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ebb.core.naming import parse_animal_id
from ebb.io.edf_header import detect_fs_from_standard
from ebb.process.psd_compute import batch_estimate, build_final_pkl
from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import Manifest, merged_psd_path
from ebb_viewer.pipeline.theme import apply_primary_button, zone_header_qss
from ebb_viewer.widgets.mask_params_widget import MaskParamsWidget
from ebb_viewer.widgets.no_scroll_spinbox import NoScrollSpinBox
from ebb_viewer.widgets.worker_helpers import launch_worker

DEFAULT_FS = 250
CH_LABELS = ["LFC", "RSC", "LSC"]


class PSDPage(QWidget):
    """Sidebar page #6 — drives the PSD compute step of the pipeline.

    Owns: folder selection (standard EDFs + named run output dir), per-combo
    status table, the shared ``MaskParamsWidget`` (states + SD + spindle +
    SWD + annotation + hour-window params), channels + fs settings, and a
    worker thread that runs ``batch_estimate`` per combo and writes one PKL
    + the shared ``psd_params.json`` per run.

    Run state lives in the mask widget (round-trippable to/from the saved
    JSON via ``to_params``/``from_params``) plus the channels + fs
    spinboxes on the page. Initial values are loaded from the most recently
    modified saved run when the page is constructed.
    """

    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.standard_folder: Path | None = None
        self._computing = False
        self._swd_available: bool = False
        self.psd_thread: QThread | None = None
        self.psd_worker: BatchEstimateWorker | None = None

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
        self._refresh_run_name_hint()
        self._maybe_autodetect_fs()

    def _maybe_autodetect_fs(self) -> None:
        """Fill the Sampling Frequency SpinBox from the first EDF in
        standard/ when it's still at the hardcoded default. A user-set or
        saved-params value is never overridden."""
        if self.spin_fs.value() != DEFAULT_FS:
            return
        detected = detect_fs_from_standard(self.project_root)
        if detected is not None:
            self.spin_fs.setValue(detected)

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
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

        # ----- Zone 1: SETUP -----
        # ----- Zone 1: SETUP (collapsible) -----
        # Setup is a "set once and forget" zone — collapse it to a one-line
        # summary once the user has picked a folder + run name. Default
        # expanded so it's discoverable on first visit.
        zone1_row = QHBoxLayout()
        zone1_row.setContentsMargins(0, 0, 0, 0)
        zone1_label = QLabel("1. SETUP")
        zone1_label.setStyleSheet(zone_header_qss())
        zone1_row.addWidget(zone1_label)
        zone1_row.addStretch(1)
        self._setup_summary_lbl = QLabel("")
        self._setup_summary_lbl.setStyleSheet(
            "color: #888; font-size: 11px; font-style: italic; padding-right: 8px;"
        )
        self._setup_summary_lbl.setVisible(False)
        zone1_row.addWidget(self._setup_summary_lbl)
        self._btn_setup_toggle = QPushButton("▼")
        self._btn_setup_toggle.setCheckable(True)
        self._btn_setup_toggle.setChecked(True)
        self._btn_setup_toggle.setFixedSize(28, 22)
        self._btn_setup_toggle.setToolTip("Collapse the Setup section")
        self._btn_setup_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_setup_toggle.clicked.connect(self._on_setup_toggled)
        zone1_row.addWidget(self._btn_setup_toggle)
        root.addLayout(zone1_row)

        # Container wrapping the setup group boxes so we can hide them as
        # a unit on collapse.
        self._setup_container = QWidget()
        setup_v = QVBoxLayout(self._setup_container)
        setup_v.setContentsMargins(0, 0, 0, 0)
        setup_v.setSpacing(4)
        root.addWidget(self._setup_container)

        # Folder Selection
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

        run_name_row = QHBoxLayout()
        self._run_name_edit = QLineEdit("default")
        self._run_name_edit.setPlaceholderText("default")
        self._run_name_edit.setMaximumWidth(200)
        run_name_row.addWidget(self._run_name_edit)
        self._run_name_hint = QLabel("")
        self._run_name_hint.setStyleSheet("font-size: 10px; color: #888;")
        run_name_row.addWidget(self._run_name_hint, 1)
        top_form.addRow("Run name:", run_name_row)

        self._run_name_warn = QLabel("")
        self._run_name_warn.setStyleSheet("font-size: 10px; color: #c77800;")
        self._run_name_warn.setWordWrap(True)
        top_form.addRow("", self._run_name_warn)

        setup_v.addWidget(self.folder_gb)

        # Spindle Output Combos (Setup)
        self.combo_gb = QGroupBox("Spindle Output Combos")
        combo_v = QVBoxLayout(self.combo_gb)

        btn_row = QHBoxLayout()
        self.btn_refresh_table = QPushButton("Refresh")
        btn_row.addWidget(self.btn_refresh_table)
        btn_row.addStretch(1)
        combo_v.addLayout(btn_row)

        self.combo_table = QTableWidget(0, 4)
        self.combo_table.setHorizontalHeaderLabels(["Combo", "CSVs", "Ok Runs", "PKL Status"])
        self.combo_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.combo_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.combo_table.setColumnWidth(1, 60)
        self.combo_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.combo_table.setColumnWidth(2, 70)
        self.combo_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.combo_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.combo_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.combo_table.verticalHeader().setVisible(False)
        # Table height auto-fits its row count (see _autofit_combo_table_height)
        # instead of always reserving ~150 px — most projects have 1–3 combos.
        self.combo_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo_v.addWidget(self.combo_table)

        self._merged_pkl_label = QLabel()
        self._merged_pkl_label.setStyleSheet("font-size: 10px; color: #555; padding-top: 2px;")
        combo_v.addWidget(self._merged_pkl_label)

        setup_v.addWidget(self.combo_gb)

        # Mask widget — built early so its States section can be re-parented
        # into Zone 2 below. expose_states_externally=True keeps state
        # ownership here while letting the page render the visual elsewhere.
        # show_drink_mask=False because PSD initial compute never applies
        # drink masks — those are added later by the Drink Mask page.
        self.mask_widget = MaskParamsWidget(
            project_root=self.project_root,
            swd_available=self._swd_available,
            show_drink_mask=False,
            expose_states_externally=True,
            show_subzone_headers=True,
        )

        # ----- Zone 2: WHAT TO COMPUTE -----
        zone2 = QLabel("2. WHAT TO COMPUTE")
        zone2.setStyleSheet(zone_header_qss())
        root.addWidget(zone2)

        # States section (pulled from the mask widget) — wrapped in a plain
        # QGroupBox so it visually matches the Channels box below it (no
        # collapsible chevron / subtitle here; the box header is enough).
        self.states_gb = QGroupBox("States to Compute")
        self.states_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        states_v = QVBoxLayout(self.states_gb)
        states_v.addWidget(self.mask_widget.states_inner_widget())
        root.addWidget(self.states_gb)

        # "&&" escapes the ampersand so Qt doesn't treat it as an accelerator.
        self.psd_settings_gb = QGroupBox("Channels && Sampling freq")
        self.psd_settings_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        psd_v = QVBoxLayout(self.psd_settings_gb)

        ch_hdr = QHBoxLayout()
        ch_hdr.addWidget(QLabel("Channels:"))
        ch_hdr.addStretch(1)
        self.chk_all = QCheckBox("Select all")
        self.chk_all.setChecked(True)
        ch_hdr.addWidget(self.chk_all)
        psd_v.addLayout(ch_hdr)

        channels_grid = QGridLayout()
        channels_grid.setContentsMargins(0, 0, 0, 0)
        channels_grid.setHorizontalSpacing(12)
        channels_grid.setVerticalSpacing(4)
        psd_v.addLayout(channels_grid)

        self._channel_boxes: list[QCheckBox] = []
        for i, label in enumerate(CH_LABELS):
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.toggled.connect(lambda _checked: self._validate())
            self._channel_boxes.append(cb)
            r, c = divmod(i, 4)
            channels_grid.addWidget(cb, r, c)

        fs_form = QFormLayout()
        fs_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        # NoScrollSpinBox so a stray scroll-wheel inside the page doesn't
        # accidentally change the value.
        self.spin_fs = NoScrollSpinBox()
        self.spin_fs.setRange(1, 100_000)
        self.spin_fs.setSuffix(" Hz")
        self.spin_fs.setValue(DEFAULT_FS)
        # ↻ button reads fs from the first EDF in ``standard/`` and fills
        # in the spinbox. No-op (with a log line) when no EDF is found.
        self.btn_detect_fs = QPushButton("↻")
        self.btn_detect_fs.setFixedSize(24, 22)
        self.btn_detect_fs.setToolTip(
            "Read sampling frequency from the first EDF in standard/"
        )
        self.btn_detect_fs.clicked.connect(self._on_detect_fs_clicked)
        fs_row = QHBoxLayout()
        fs_row.setContentsMargins(0, 0, 0, 0)
        fs_row.addWidget(self.spin_fs)
        fs_row.addWidget(self.btn_detect_fs)
        fs_row.addStretch(1)
        fs_form.addRow("Sampling freq:", fs_row)
        psd_v.addLayout(fs_form)

        root.addWidget(self.psd_settings_gb)

        # ----- Zone 3: FILTERS & MASKS -----
        zone3_row = QHBoxLayout()
        zone3 = QLabel("3. FILTERS & MASKS")
        zone3.setStyleSheet(zone_header_qss())
        zone3_row.addWidget(zone3)
        zone3_row.addStretch(1)
        self.btn_restore_defaults = QPushButton("Restore defaults")
        self.btn_restore_defaults.setToolTip(
            "Reset states, SD, spindle noise, commutator, SWD, annotation, "
            "and hour-window settings to their defaults. Channels and sampling "
            "freq are not affected."
        )
        self.btn_restore_defaults.clicked.connect(self._on_restore_defaults)
        zone3_row.addWidget(self.btn_restore_defaults)
        root.addLayout(zone3_row)

        # The mask widget renders its remaining filter sections (SD,
        # Spindle Noise, SWD, Annotation, Compute Hours) here. States was
        # already pulled into Zone 2 via the expose_states_externally flag.
        root.addWidget(self.mask_widget)

        # ----- Zone 4: RUN -----
        zone4 = QLabel("4. RUN")
        zone4.setStyleSheet(zone_header_qss())
        root.addWidget(zone4)
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(8)
        self.btn_run_pipeline = QPushButton("Run PSD Pipeline")
        self.btn_run_pipeline.setEnabled(False)
        apply_primary_button(self.btn_run_pipeline)
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
        self.states_gb.setObjectName("statesBox")
        self.psd_settings_gb.setObjectName("psdBox")
        self.setStyleSheet("""
        QGroupBox#folderBox, QGroupBox#comboBox, QGroupBox#statesBox, QGroupBox#psdBox {
            font: 550;
        }
        QGroupBox#folderBox *, QGroupBox#comboBox *, QGroupBox#statesBox *, QGroupBox#psdBox * {
            font: 400;
        }
        """)

    def _wire(self) -> None:
        self.chk_all.toggled.connect(self._toggle_all_channels)
        self.btn_standard.clicked.connect(self._choose_standard_folder)
        self.btn_refresh_table.clicked.connect(self._refresh_combo_table)
        self.btn_run_pipeline.clicked.connect(self._run_pipeline_clicked)
        self._run_name_edit.textChanged.connect(self._on_run_name_changed)
        # Re-validate when any mask-widget knob changes (states, ann_dir,
        # ann_keywords, etc. all affect the gate / summary).
        self.mask_widget.changed.connect(self._validate)

    # ------------- Path / table refresh -------------

    def _run_name(self) -> str:
        """Return the current run name, defaulting to 'default'."""
        name = self._run_name_edit.text().strip()
        return name if name else "default"

    def _on_run_name_changed(self) -> None:
        name = self._run_name_edit.text().strip()
        if name and not psd_params.valid_run_name(name):
            self._run_name_warn.setText(
                "Invalid name — use letters, numbers, hyphens, underscores (max 64 chars)."
            )
        else:
            existing = psd_params.list_runs(self.project_root)
            if name in existing:
                self._run_name_warn.setText(
                    f"⚠ Run '{name}' already exists — re-running will overwrite its results."
                )
            else:
                self._run_name_warn.setText("")
        self._refresh_run_name_tooltip()
        self._refresh_combo_table()

    def _refresh_run_name_tooltip(self) -> None:
        """Keep the Run-name tooltip in sync with the derived output path.
        The path used to live on the page as its own row, but it's fully
        derived from project_root + 'psd/<run_name>'; the tooltip is enough
        for discoverability without burning a row of vertical space.
        """
        out = self.project_root / "psd" / (self._run_name() or "default")
        self._run_name_edit.setToolTip(f"PSD output: {out}")
        self._refresh_setup_summary()

    def _on_restore_defaults(self) -> None:
        """Reset the shared mask widget back to its built-in defaults.

        Channels and sampling freq are page-owned and intentionally
        preserved — they're project-detected, not user prefs.
        """
        ret = QMessageBox.question(
            self,
            "Restore defaults?",
            "Reset states, SD, spindle noise, commutator, SWD, annotation, "
            "and hour-window settings to their defaults?\n\n"
            "Channels and sampling frequency are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.mask_widget.from_params({})

    def _on_detect_fs_clicked(self) -> None:
        """Fill the Sampling-freq SpinBox from the first EDF in standard/.
        Silently no-ops (with a log line) when no readable EDF is found —
        the user's existing SpinBox value is preserved.
        """
        detected = detect_fs_from_standard(self.project_root)
        if detected is None:
            self._log("No readable EDF found in standard/; leaving sampling freq unchanged.")
            return
        self.spin_fs.setValue(detected)
        self._log(f"Detected sampling freq: {detected} Hz")

    def _refresh_setup_summary(self) -> None:
        """Update the collapsed-state summary shown next to the SETUP header."""
        self._setup_summary_lbl.setText(
            f"{self.project_root.name} • run: {self._run_name() or 'default'}"
        )

    def _on_setup_toggled(self, checked: bool) -> None:
        """Collapse / expand the Setup zone. The summary label is only
        visible when the body is hidden."""
        self._setup_container.setVisible(checked)
        self._setup_summary_lbl.setVisible(not checked)
        self._btn_setup_toggle.setText("▼" if checked else "▶")
        self._btn_setup_toggle.setToolTip(
            "Collapse the Setup section" if checked else "Expand the Setup section"
        )

    def _refresh_run_name_hint(self) -> None:
        existing = psd_params.list_runs(self.project_root)
        if existing:
            self._run_name_hint.setText("Existing: " + ", ".join(existing))
        else:
            self._run_name_hint.setText("")

    def _refresh_standard_folder(self) -> None:
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
        self._refresh_run_name_tooltip()

    def _refresh_swd_status(self) -> None:
        """Update widget's SWD-available state from the project's swd/ dir."""
        swd_dir = self.project_root / "swd"
        manifest: Manifest | None = None
        if swd_dir.is_dir():
            mat_count = sum(1 for _ in swd_dir.glob("*.mat"))
            self._swd_available = mat_count > 0
            if mat_count > 0:
                manifest = Manifest.load(self.project_root)
        else:
            self._swd_available = False
        # The widget's own ``_refresh_swd_status`` shows the live count text
        # in the SWD section; here we only need to update the
        # ``swd_available`` flag controlling the radio's enabled state.
        self.mask_widget.set_swd_available(self._swd_available)
        self._validate(manifest)

    def _load_saved_params(self) -> None:
        """Load the most recently modified saved run into UI state."""
        runs = psd_params.list_runs(self.project_root)
        run_name = "default"
        if runs:
            psd_dir = self.project_root / "psd"
            run_name = max(runs, key=lambda r: (psd_dir / r / "psd_params.json").stat().st_mtime)
        params = psd_params.load(self.project_root, run_name)
        if params is None:
            return
        self._run_name_edit.setText(run_name)
        self._refresh_run_name_hint()
        # PSD-only knobs (channels + fs) stay on the page.
        if "fs" in params:
            self.spin_fs.setValue(params["fs"])
        if "channels" in params:
            for i, cb in enumerate(self._channel_boxes):
                cb.setChecked(i in params["channels"])
            all_checked = all(cb.isChecked() for cb in self._channel_boxes)
            self.chk_all.blockSignals(True)
            self.chk_all.setChecked(all_checked)
            self.chk_all.blockSignals(False)
        # Everything else (states + mask params) lives in the widget.
        self.mask_widget.from_params(params)

    def _autofit_combo_table_height(self) -> None:
        """Resize the combo table to its content height — header + N rows
        — so the box doesn't reserve ~150 px of empty space when the
        project has only 1–3 combos.
        """
        n = self.combo_table.rowCount()
        header_h = self.combo_table.horizontalHeader().height()
        row_h = sum(self.combo_table.rowHeight(r) for r in range(n))
        # Empty-state minimum: keep one row's worth of space so the
        # placeholder reads as "no combos" rather than vanishing.
        empty_row_h = self.combo_table.verticalHeader().defaultSectionSize()
        body = max(row_h, empty_row_h if n == 0 else 0)
        self.combo_table.setFixedHeight(header_h + body + 4)

    def _refresh_combo_table(self) -> None:
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

        run_name = self._run_name()
        if spindle_root.is_dir():
            for combo_dir in sorted(p for p in spindle_root.iterdir() if p.is_dir()):
                combo = combo_dir.name
                csv_count = len(list(combo_dir.glob("*.csv")))
                ok_count = ok_runs_per_combo.get(combo, 0)
                pkl_path = psd_dir / run_name / f"psds_{combo}.pkl"
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
        self._autofit_combo_table_height()

        merged = merged_psd_path(self.project_root, run_name)
        if merged.exists():
            self._merged_pkl_label.setText("Channel merged PKL: ✓ exists")
            self._merged_pkl_label.setStyleSheet(
                "font-size: 10px; color: #2a7a2a; padding-top: 2px;"
            )
        else:
            self._merged_pkl_label.setText("Channel merged PKL: not yet built")
            self._merged_pkl_label.setStyleSheet("font-size: 10px; color: #555; padding-top: 2px;")

        self._validate(manifest)

    # ------------- Actions -------------

    def _run_pipeline_clicked(self) -> None:
        if self.standard_folder is None or not self.standard_folder.exists():
            QMessageBox.critical(
                self,
                "No Standard Folder",
                "Standard EDF folder not set or does not exist.\n\n"
                f"Expected: {self.project_root / 'standard'}",
            )
            return

        spindle_root = self.project_root / "spindle_outputs"
        combos = (
            sorted(
                sd.name for sd in spindle_root.iterdir() if sd.is_dir() and any(sd.glob("*.csv"))
            )
            if spindle_root.is_dir()
            else []
        )
        if not combos:
            QMessageBox.warning(
                self, "No Combos Found", "No spindle output combos with CSVs found."
            )
            return

        manifest = Manifest.load(self.project_root)

        # Pre-flight: warn about ok animals with no state CSV (they'll be silently skipped)
        for combo in combos:
            csv_animal_ids = {parse_animal_id(p) for p in (spindle_root / combo).glob("*.csv")}
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

        # Pull all mask + filter params from the widget; channels + fs stay
        # on the page. The widget includes a few keys that the underlying
        # estimator doesn't accept (e.g. use_swd_mask, use_drink_mask) —
        # those are stripped by ``_UI_ONLY_KWARGS`` in ``psd_compute``.
        widget_params = self.mask_widget.to_params()

        # Pre-flight: SWD mask — all ok animals must have a .mat file
        swd_dir: Path | None = None
        if widget_params.get("use_swd_mask"):
            swd_dir = self.project_root / "swd"
            swd_animal_ids = {parse_animal_id(p) for p in swd_dir.glob("*.mat")}
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
                    + "\n".join(f"  • {a}" for a in missing_swd)
                    + "\n\nProvide SWD files for all animals before running with SWD masking,"
                    " or switch to 'No SWD mask'.",
                )
                return

        run_name = self._run_name()
        if not psd_params.valid_run_name(run_name):
            QMessageBox.warning(
                self,
                "Invalid Run Name",
                "Run name must contain only letters, numbers, hyphens, "
                "or underscores (max 64 characters).",
            )
            return

        if run_name in psd_params.list_runs(self.project_root):
            reply = QMessageBox.question(
                self,
                "Overwrite Existing Run?",
                f"Run '{run_name}' already exists.\n\n"
                "Re-running will overwrite its PKL files and clear all PSD review "
                "flags for this run in the manifest. This cannot be undone.\n\n"
                "Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        psd_run_dir = self.project_root / "psd" / run_name
        psd_run_dir.mkdir(parents=True, exist_ok=True)
        pairs: list[tuple[Path, Path]] = [
            (spindle_root / combo, psd_run_dir / f"psds_{combo}.pkl") for combo in combos
        ]

        # Compose params for the worker: widget params + page-owned
        # channels + fs.
        params = {
            **widget_params,
            "fs": int(self.spin_fs.value()),
            "channels": self.selected_channels(),
        }

        # Build the separate ann_params dict consumed by batch_estimate.
        # The widget's flat ann_* keys map to the dict shape estimator
        # expects (keywords list, pad_*_sec).
        ann_params: dict | None = None
        if widget_params.get("ann_enabled") and widget_params.get("ann_dir"):
            ann_params = {
                "ann_dir": Path(widget_params["ann_dir"]),
                "keywords": [
                    k.strip()
                    for k in (widget_params.get("ann_keywords") or "").split(",")
                    if k.strip()
                ],
                "match_mode": widget_params.get("ann_match_mode", "contains"),
                "pad_before_sec": float(widget_params.get("ann_pad_before", 0.0)),
                "pad_after_sec": float(widget_params.get("ann_pad_after", 0.0)),
            }

        # Clear stale PSD review flags for this run so the visualizer doesn't
        # show old decisions against freshly computed data. Reuse the manifest
        # loaded above for the pre-flight checks rather than re-reading.
        try:
            for entry in manifest:
                for run in entry.runs.values():
                    run.psd_status.pop(run_name, None)
            manifest.save()
        except (OSError, ValueError) as e:
            self._log(f"⚠ Could not clear stale PSD review flags: {e}")

        self._computing = True
        self._hint_frame.setVisible(False)
        self.btn_run_pipeline.setEnabled(False)
        self._log(f"Running PSD pipeline for {len(combos)} combo(s): {', '.join(combos)}")

        self.psd_thread = QThread(self)
        self.psd_worker = BatchEstimateWorker(
            eeg_dir=self.standard_folder,
            combo_pairs=pairs,
            params=params,
            project_root=self.project_root,
            run_name=run_name,
            swd_dir=swd_dir,
            ann_params=ann_params,
        )
        self.psd_worker.progress.connect(self._log)
        launch_worker(
            self.psd_thread,
            self.psd_worker,
            on_finished=self._on_psd_done,
            on_error=self._on_psd_error,
        )

    def _build_final_pkl(self) -> None:
        try:
            run_name = self._run_name()
            manifest = Manifest.load(self.project_root)
            out = build_final_pkl(self.project_root, manifest, run_name)
            self._log(f"Built channel merged PKL: {out}")
            drink_pkl = self.project_root / "psd" / run_name / "psds_drink.pkl"
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
        except (OSError, ValueError, RuntimeError) as e:
            self._log(f"ERROR building final PKL: {e}")
            QMessageBox.critical(self, "Build Final PKL Error", str(e))

    # ---------- Channels API ----------

    def selected_channels(self) -> list[int]:
        """Return indices of checked channel boxes (in CH_LABELS order)."""
        return [i for i, cb in enumerate(self._channel_boxes) if cb.isChecked()]

    # ---------- Internals ----------

    def _toggle_all_channels(self, checked: bool) -> None:
        for cb in self._channel_boxes:
            cb.setChecked(checked)

    def _choose_standard_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Standard EDF Folder", str(self.project_root)
        )
        if not folder:
            return
        self.standard_folder = Path(folder).expanduser().resolve()
        self.lbl_standard.setText(str(self.standard_folder))
        self._validate()

    def _validate(self, manifest: Manifest | None = None) -> None:
        """Recompute the Run button's enabled state + status labels.

        Args:
            manifest: Optional pre-loaded manifest to avoid a redundant disk
                read when the caller has already loaded one. When ``None``,
                the manifest is loaded here.
        """
        if self._computing:
            self._gate_label.setText("")
            self._summary_label.setText("")
            return
        has_standard = self.standard_folder is not None and self.standard_folder.exists()

        if manifest is None:
            manifest = Manifest.load(self.project_root)
        n_animals = len(manifest)
        n_ready = len(manifest.ready_for_psd())
        all_ready = n_animals > 0 and n_ready == n_animals

        spindle_root = self.project_root / "spindle_outputs"
        has_combos = spindle_root.is_dir() and any(
            sd.is_dir() and any(sd.glob("*.csv")) for sd in spindle_root.iterdir()
        )

        # Annotation mask gate — same shape as the legacy dialog: if
        # annotation masking is enabled, dir + keywords must be valid.
        widget_params = self.mask_widget.to_params()
        ann_ok = True
        if widget_params.get("ann_enabled"):
            ann_dir = widget_params.get("ann_dir")
            ann_keywords = (widget_params.get("ann_keywords") or "").strip()
            if ann_dir is None or not Path(ann_dir).is_dir() or not ann_keywords:
                ann_ok = False

        states_ok = bool(widget_params.get("states"))
        channels_ok = bool(self.selected_channels())

        self.btn_run_pipeline.setEnabled(
            has_standard
            and all_ready
            and has_combos
            and ann_ok
            and states_ok
            and channels_ok
        )

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
            self._gate_label.setText(
                "No spindle output combos found — complete upload/download first"
            )
            self._summary_label.setText("")
        elif not ann_ok:
            ann_dir = widget_params.get("ann_dir")
            if ann_dir is None or not Path(ann_dir).is_dir():
                self._gate_label.setText(
                    "Annotation mask enabled — select a valid annotation directory"
                )
            else:
                self._gate_label.setText("Annotation mask enabled — enter at least one keyword")
            self._summary_label.setText("")
        elif not states_ok:
            self._gate_label.setText("Select at least one state group to compute")
            self._summary_label.setText("")
        elif not channels_ok:
            self._gate_label.setText("Select at least one channel to compute")
            self._summary_label.setText("")
        else:
            self._gate_label.setText("")
            # Build summary: "LFC_RSC (8 animals), LFC_LSC (5 animals) → psds_channel_merged.pkl"
            ok_per_combo: dict[str, int] = {}
            for entry in manifest:
                for combo, run in entry.runs.items():
                    if run.sleep_qc == "ok":
                        ok_per_combo[combo] = ok_per_combo.get(combo, 0) + 1
            parts = [
                f"{c} ({n} animal{'s' if n != 1 else ''})" for c, n in sorted(ok_per_combo.items())
            ]
            self._summary_label.setText(", ".join(parts) + " → psds_channel_merged.pkl")

    def _on_psd_done(self) -> None:
        self._computing = False
        self._log("PSD computation finished.")
        self._refresh_combo_table()
        self._log("Building channel-merged PKL…")
        self._build_final_pkl()

    def _on_psd_error(self, msg: str) -> None:
        self._computing = False
        self._log(f"ERROR in batch_estimate: {msg}")
        QMessageBox.critical(self, "PSD Error", msg)
        self._validate()

    def _log(self, msg: str) -> None:
        """Append a one-line status message to the page's log box."""
        self.log_box.appendPlainText(msg)


class BatchEstimateWorker(QObject):
    """Worker that drives ``batch_estimate`` per (combo, savepath) pair.

    Lives on a ``QThread`` started via ``launch_worker``. For each combo,
    calls ``batch_estimate`` with ``drink_dir=None`` (drink masking is
    applied later by the Drink Mask page) and ``savepath=None``, then
    writes the PKL manually with ``params`` embedded in each record.
    After the last combo completes, writes ``psd/<run_name>/psd_params.json``
    so the run is fully reproducible from disk.
    """

    progress = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        eeg_dir: Path,
        combo_pairs: list[tuple[Path, Path]],
        params: dict,
        project_root: Path,
        run_name: str = "default",
        offset_path: Path | None = None,
        swd_dir: Path | None = None,
        ann_params: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.eeg_dir = eeg_dir
        self.combo_pairs = combo_pairs
        self.params = params
        self.project_root = Path(project_root)
        self.run_name = run_name
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

            # self.params already carries hw_enabled / hour_windows /
            # selected_days when set (see _run_pipeline_clicked), so the
            # spread below covers them — only swd_mode and ann_* need to
            # be added on top.
            swd_mode = "mask_out" if self.swd_dir is not None else "none"
            saved = {**self.params, "swd_mode": swd_mode}
            if self.ann_params is not None:
                saved.update(
                    {
                        "ann_enabled": True,
                        "ann_dir": str(self.ann_params["ann_dir"]),
                        "ann_keywords": ", ".join(self.ann_params["keywords"]),
                        "ann_match_mode": self.ann_params["match_mode"],
                        "ann_pad_before": self.ann_params["pad_before_sec"],
                        "ann_pad_after": self.ann_params["pad_after_sec"],
                    }
                )
            else:
                saved["ann_enabled"] = False
            psd_params.save(self.project_root, self.run_name, saved)
            self.progress.emit(f"  → Saved PSD params to psd/{self.run_name}/psd_params.json")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
