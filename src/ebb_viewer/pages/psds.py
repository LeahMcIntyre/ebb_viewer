"""PSD compute page — wraps :func:`ebb.process.psd_compute.batch_estimate`.

Drives the initial PSD computation step of the pipeline. Each run writes one
``psd/<run_name>/psds_<combo>.pkl`` for the project's channel combo, consumed by
the visualizer. Only the combo's channels are computed.

The page is structured as:

1. A status card — the combo, its CSVs, how many animals are ready, the run name
   and the output file (all read-only except the run name)
2. States to compute
3. ``MaskParamsWidget`` — shared editor for state-group selection and the
   SWD / annotation / hour-window / artifact mask params (same widget the
   Export Masks page uses, with ``show_drink_mask=False`` since the PSD
   compute step doesn't apply drink masks), event-based masks first
4. Advanced — sampling frequency
5. A bar pinned to the bottom with the Run button, what is blocking it, and
   the post-run hint; the status log sits at the end of the scrolling content

Run params (mask + filter knobs + states) round-trip through
``project/psd/<run_name>/psd_params.json``. Drink masking is intentionally
*not* applied here; the Drink Mask page re-applies it after PSD review.
"""

from __future__ import annotations

import dataclasses
import pickle
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ebb.core.naming import parse_animal_id
from ebb.io.edf_header import detect_fs_from_standard
from ebb.process.psd_compute import batch_estimate
from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.pipeline.theme import apply_primary_button, zone_header_qss
from ebb_viewer.widgets.collapsible_section import CollapsibleSection
from ebb_viewer.widgets.mask_params_widget import MaskParamsWidget
from ebb_viewer.widgets.no_scroll_spinbox import NoScrollSpinBox
from ebb_viewer.widgets.swd_warning import confirm_unfinished_swd_review
from ebb_viewer.widgets.worker_helpers import launch_worker

DEFAULT_FS = 250
CH_LABELS = ["LFC", "RSC", "LSC"]


def combo_channels(combo: str) -> list[int]:
    """Indices into ``CH_LABELS`` of the channels named by a combo like ``"LFC_RSC"``.

    Raises:
        ValueError: if the combo names a channel that is not in ``CH_LABELS``.
    """
    names = combo.split("_")
    unknown = [n for n in names if n not in CH_LABELS]
    if unknown:
        raise ValueError(f"Unknown channel(s) {', '.join(unknown)} in combo {combo!r}")
    return [CH_LABELS.index(n) for n in names]


class PSDPage(QWidget):
    """Sidebar page #6 — drives the PSD compute step of the pipeline.

    Owns: the run name, the status card for the project combo, the shared
    ``MaskParamsWidget`` (states + SWD + annotation + hour-window + artifact
    params), the sampling frequency, and a worker thread that runs
    ``batch_estimate`` for the combo and writes one PKL + ``psd_params.json``
    per run. The channels computed are the combo's (``selected_channels``).

    Run state lives in the mask widget (round-trippable to/from the saved
    JSON via ``to_params``/``from_params``) plus the sampling-frequency
    spinbox. Initial values are loaded from the most recently modified saved
    run when the page is constructed.
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
        self._refresh_status()
        self._refresh_swd_status()
        self._load_saved_params()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_standard_folder()
        self._refresh_status()
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
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll, 1)

        content = QWidget()
        self._scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 8, 8, 8)

        lbl = QLabel("PSD Computation")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        desc = QLabel(
            "Compute power spectral densities for the project's channel combination from the "
            "sleep-scored EDF files. Every animal needs a Sleep QC decision (ok or excluded); "
            "excluded animals are computed too and stay marked excluded."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(lbl)
        root.addWidget(desc)

        # ----- Status card: combo, animals, run name, output -----
        status_card = QFrame()
        status_card.setFrameShape(QFrame.Shape.StyledPanel)
        status_v = QVBoxLayout(status_card)
        status_v.setContentsMargins(10, 8, 10, 8)
        status_v.setSpacing(4)

        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        status_v.addWidget(self._status_lbl)

        run_name_row = QHBoxLayout()
        run_name_row.addWidget(QLabel("Run name:"))
        self._run_name_edit = QLineEdit("default")
        self._run_name_edit.setPlaceholderText("default")
        self._run_name_edit.setMaximumWidth(200)
        run_name_row.addWidget(self._run_name_edit)
        self._run_name_hint = QLabel("")
        self._run_name_hint.setStyleSheet("font-size: 10px; color: #888;")
        run_name_row.addWidget(self._run_name_hint, 1)
        status_v.addLayout(run_name_row)

        self._run_name_warn = QLabel("")
        self._run_name_warn.setStyleSheet("font-size: 10px; color: #c77800;")
        self._run_name_warn.setWordWrap(True)
        status_v.addWidget(self._run_name_warn)

        self._output_lbl = QLabel("")
        self._output_lbl.setStyleSheet("font-size: 11px;")
        status_v.addWidget(self._output_lbl)
        root.addWidget(status_card)

        # Mask widget — built early so its States section can be re-parented
        # into the "What to compute" box below. expose_states_externally=True
        # keeps state ownership here while letting the page render the visual
        # elsewhere. show_drink_mask=False because PSD initial compute never
        # applies drink masks — those are added later by the Drink Mask page.
        self.mask_widget = MaskParamsWidget(
            project_root=self.project_root,
            swd_available=self._swd_available,
            show_drink_mask=False,
            expose_states_externally=True,
            show_subzone_headers=True,
            event_masks_first=True,
        )

        # ----- What to compute -----
        zone_states = QLabel("WHAT TO COMPUTE")
        zone_states.setStyleSheet(zone_header_qss())
        root.addWidget(zone_states)

        self.states_gb = QGroupBox("States to Compute")
        self.states_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        states_v = QVBoxLayout(self.states_gb)
        states_v.addWidget(self.mask_widget.states_inner_widget())
        root.addWidget(self.states_gb)

        # ----- Filters & masks -----
        masks_row = QHBoxLayout()
        zone_masks = QLabel("FILTERS & MASKS")
        zone_masks.setStyleSheet(zone_header_qss())
        masks_row.addWidget(zone_masks)
        masks_row.addStretch(1)
        self.btn_restore_defaults = QPushButton("Restore defaults")
        self.btn_restore_defaults.setToolTip(
            "Reset states, SD, spindle noise, commutator, SWD, annotation, "
            "and hour-window settings to their defaults. Sampling freq is not affected."
        )
        self.btn_restore_defaults.clicked.connect(self._on_restore_defaults)
        masks_row.addWidget(self.btn_restore_defaults)
        root.addLayout(masks_row)

        # The mask widget renders the mask sections here (States was already
        # pulled into the box above via expose_states_externally).
        root.addWidget(self.mask_widget)

        # ----- Advanced: sampling frequency -----
        adv_body = QWidget()
        adv_h = QHBoxLayout(adv_body)
        adv_h.addWidget(QLabel("Sampling freq:"))
        # NoScrollSpinBox so a stray scroll-wheel inside the page doesn't
        # accidentally change the value.
        self.spin_fs = NoScrollSpinBox()
        self.spin_fs.setRange(1, 100_000)
        self.spin_fs.setSuffix(" Hz")
        self.spin_fs.setValue(DEFAULT_FS)
        adv_h.addWidget(self.spin_fs)
        # ↻ reads fs from the first EDF in ``standard/``. No-op (with a log
        # line) when no EDF is found.
        self.btn_detect_fs = QPushButton("↻")
        self.btn_detect_fs.setFixedSize(24, 22)
        self.btn_detect_fs.setToolTip("Read sampling frequency from the first EDF in standard/")
        self.btn_detect_fs.clicked.connect(self._on_detect_fs_clicked)
        adv_h.addWidget(self.btn_detect_fs)
        adv_h.addStretch(1)
        root.addWidget(CollapsibleSection("Advanced", adv_body, collapsed=True))

        # ----- Log -----
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(300)
        self.log_box.setMinimumHeight(140)
        self.log_box.setPlaceholderText("Status messages will appear here...")
        root.addWidget(self.log_box)
        root.addStretch(1)

        # ----- Run bar, pinned below the scroll area -----
        run_bar = QFrame()
        run_bar.setFrameShape(QFrame.Shape.StyledPanel)
        bar_v = QVBoxLayout(run_bar)
        bar_v.setContentsMargins(10, 6, 10, 6)
        bar_v.setSpacing(4)

        # Hint frame — shown after a successful run
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
        bar_v.addWidget(self._hint_frame)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_run_pipeline = QPushButton("Run PSD Pipeline")
        self.btn_run_pipeline.setEnabled(False)
        apply_primary_button(self.btn_run_pipeline)
        btn_row.addWidget(self.btn_run_pipeline)
        msg_v = QVBoxLayout()
        msg_v.setSpacing(0)
        self._gate_label = QLabel("")
        self._gate_label.setStyleSheet("color: #b06000; font-size: 11px;")
        self._gate_label.setWordWrap(True)
        msg_v.addWidget(self._gate_label)
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet("color: #555; font-size: 11px;")
        self._summary_label.setWordWrap(True)
        msg_v.addWidget(self._summary_label)
        btn_row.addLayout(msg_v, 1)
        bar_v.addLayout(btn_row)
        outer.addWidget(run_bar)

        # Styling
        self.states_gb.setObjectName("statesBox")
        self.setStyleSheet("""
        QGroupBox#statesBox { font: 550; }
        QGroupBox#statesBox * { font: 400; }
        """)

    def _wire(self) -> None:
        self.btn_run_pipeline.clicked.connect(self._run_pipeline_clicked)
        self._run_name_edit.textChanged.connect(self._on_run_name_changed)
        # Re-validate when any mask-widget knob changes (states, ann_dir,
        # ann_keywords, etc. all affect the gate / summary).
        self.mask_widget.changed.connect(self._validate)

    # ------------- Path / status refresh -------------

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
        self._refresh_status()

    def _on_restore_defaults(self) -> None:
        """Reset the shared mask widget back to its built-in defaults.

        Sampling freq is page-owned and intentionally preserved — it is
        project-detected, not a user pref.
        """
        ret = QMessageBox.question(
            self,
            "Restore defaults?",
            "Reset states, SD, spindle noise, commutator, SWD, annotation, "
            "and hour-window settings to their defaults?\n\n"
            "Sampling frequency is not affected.",
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

    def _refresh_run_name_hint(self) -> None:
        existing = psd_params.list_runs(self.project_root)
        if existing:
            self._run_name_hint.setText("Existing: " + ", ".join(existing))
        else:
            self._run_name_hint.setText("")

    def _refresh_standard_folder(self) -> None:
        cand_std = self.project_root / "standard"
        self.standard_folder = cand_std if cand_std.is_dir() else None

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
        if "fs" in params:
            self.spin_fs.setValue(params["fs"])
        # Everything else (states + mask params) lives in the widget.
        self.mask_widget.from_params(params)

    def _refresh_status(self) -> None:
        """Update the status card: combo, CSV count, ready animals, output file."""
        manifest = Manifest.load(self.project_root)
        combo = manifest.combo
        ready = manifest.ready_for_psd()
        n_excluded = sum(1 for e in ready if e.sleep_qc == "excluded")

        combo_dir = self.project_root / "spindle_outputs" / combo
        csv_count = len(list(combo_dir.glob("*.csv"))) if combo_dir.is_dir() else 0
        try:
            channels = ", ".join(CH_LABELS[i] for i in combo_channels(combo))
        except ValueError:
            channels = "unknown channels"
        excluded = f" ({n_excluded} excluded)" if n_excluded else ""
        self._status_lbl.setText(
            f"<b>{combo}</b> · channels {channels} · {csv_count} state CSV"
            f"{'s' if csv_count != 1 else ''} · "
            f"{len(ready)} of {len(manifest)} animals ready{excluded}"
        )

        run_name = self._run_name()
        pkl_path = self.project_root / "psd" / run_name / f"psds_{combo}.pkl"
        if pkl_path.exists():
            self._output_lbl.setText(f"Output: psd/{run_name}/{pkl_path.name} — ✓ already computed")
            self._output_lbl.setStyleSheet("font-size: 11px; color: #2a7a2a;")
        else:
            self._output_lbl.setText(f"Output: psd/{run_name}/{pkl_path.name} — not computed yet")
            self._output_lbl.setStyleSheet("font-size: 11px; color: #666;")

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
        manifest = Manifest.load(self.project_root)
        combo = manifest.combo
        if not any((spindle_root / combo).glob("*.csv")):
            QMessageBox.warning(
                self, "No Spindle Output", f"No spindle CSVs found in spindle_outputs/{combo}/."
            )
            return

        # Pre-flight: warn about ok animals with no state CSV (they'll be silently skipped)
        csv_animal_ids = {parse_animal_id(p) for p in (spindle_root / combo).glob("*.csv")}
        missing = [
            e.animal_id for e in manifest.ready_for_psd() if e.animal_id not in csv_animal_ids
        ]
        if missing:
            self._log(
                f"⚠ {combo}: no state CSV for {', '.join(missing)}"
                f" — {'this animal' if len(missing) == 1 else 'these animals'} will be skipped"
            )

        excluded_ids = [e.animal_id for e in manifest.ready_for_psd() if e.sleep_qc == "excluded"]
        if excluded_ids:
            self._log(
                f"{combo}: {', '.join(excluded_ids)} excluded — computed anyway, "
                "marked excluded in the manifest only"
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
            all_ok_animals = {entry.animal_id for entry in manifest.ready_for_psd()}
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

        if not confirm_unfinished_swd_review(
            self, self.project_root, {e.animal_id for e in manifest.ready_for_psd()}
        ):
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
            (spindle_root / combo, psd_run_dir / f"psds_{combo}.pkl")
        ]

        # Compose params for the worker: widget params + the combo's
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
                entry.psd_status.pop(run_name, None)
            manifest.save()
        except (OSError, ValueError) as e:
            self._log(f"⚠ Could not clear stale PSD review flags: {e}")

        self._computing = True
        self._hint_frame.setVisible(False)
        self.btn_run_pipeline.setEnabled(False)
        self._log(f"Running PSD pipeline for combo: {combo}")
        self._scroll.ensureWidgetVisible(self.log_box)

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

    # ---------- Channels API ----------

    def selected_channels(self) -> list[int]:
        """Indices (into ``CH_LABELS``) of the project combo's channels.

        Raises:
            ValueError: if the combo names an unknown channel.
        """
        return combo_channels(Manifest.load(self.project_root).combo)

    # ---------- Internals ----------

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
        has_combos = any((spindle_root / manifest.combo).glob("*.csv"))

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
        try:
            combo_channels(manifest.combo)
            channels_ok = True
        except ValueError:
            channels_ok = False

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
                    "not ready — each needs sleep QC marked ok or excluded"
                )
            self._summary_label.setText("")
        elif not has_combos:
            self._gate_label.setText(
                f"No spindle output found for {manifest.combo} — complete upload/download first"
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
            self._gate_label.setText(
                f"Unknown channel in combo {manifest.combo!r} — expected names from "
                f"{', '.join(CH_LABELS)}"
            )
            self._summary_label.setText("")
        else:
            self._gate_label.setText("")
            # Build summary: "LFC_RSC (8 animals) → psds_LFC_RSC.pkl"
            n_excluded = sum(1 for e in manifest.ready_for_psd() if e.sleep_qc == "excluded")
            excluded = f", {n_excluded} excluded" if n_excluded else ""
            self._summary_label.setText(
                f"{manifest.combo} ({n_ready} animal{'s' if n_ready != 1 else ''}{excluded})"
                f" → psds_{manifest.combo}.pkl"
            )

    def _on_psd_done(self) -> None:
        self._computing = False
        self._log("PSD computation finished.")
        run_name = self._run_name()
        drink_pkl = self.project_root / "psd" / run_name / "psds_drink.pkl"
        if drink_pkl.exists():
            self._log(
                "Note: previously applied drink masks are preserved in psds_drink.pkl."
                " If PSD parameters changed since the last drink mask run,"
                " re-apply them on the Drink Mask page."
            )
        self.manifest_changed.emit()
        self._hint_lbl.setText("✓ PSDs computed — ready for PSD review.")
        self._hint_btn_viz.setVisible(True)
        self._hint_frame.setVisible(True)
        self._refresh_status()

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
