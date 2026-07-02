"""EEG viewer main window — central trace view + masks dock + QC toolbar.

Used both inside pipeline pages (via `launch_edf_window`) and standalone
(via `main` / the `ebb-eeg-viewer` console script).
"""

import sys
from pathlib import Path

import pandas as pd
from openseize.file_io import edf
from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt

from ebb.io.edf_header import parse_edf_start_datetime
from ebb.masking import get_offset
from ebb.process.sleep_compute import DEFAULT_SPINDLE_EPOCH_SEC
from ebb_viewer.edf_viewer.annotations import (
    DEFAULT_COLUMNS,
    DEFAULT_SPAN_SEC,
    AnnotationFile,
    SwdAnnotation,
    default_header_lines,
    load_annotation_file,
    save_annotation_file,
    sidecar_path,
)
from ebb_viewer.edf_viewer.file_openers import (
    pick_annotations_csv,
    pick_edf_csv,
    pick_mat,
    pick_npy_csv,
)
from ebb_viewer.edf_viewer.mask_builder import (
    build_annotation_mask,
    build_default_masks,
    load_drink_mask,
    load_state_masks,
    load_swd_mask,
    SWD_COLORS,
    rebuild_annotation_mask,
    rebuild_artifact_masks,
    rebuild_drink_mask,
    rebuild_spindle_mask,
)
from ebb_viewer.edf_viewer.masks_dock import MasksDock
from ebb_viewer.edf_viewer.recording import Recording
from ebb_viewer.edf_viewer.trace_view import TraceView
from ebb_viewer.pipeline.naming import CHANNEL_COMBOS, parse_animal_id
from ebb_viewer.qt_platform import force_xcb_on_wayland
from ebb_viewer.widgets.drink_mask_dialog import DrinkMaskDialogue
from ebb_viewer.widgets.sleep_viewer import SleepPopup
from ebb_viewer.widgets.stft_viewer import STFTBoundsDialog, STFTPopup

_CH_NAMES = ("LFC", "RSC", "LSC", "EMG")


def _load_recording(edf_path: Path, csv_path: Path | None = None) -> Recording:
    """Read an EDF + optional state CSV and return a Recording.

    The sampling rate is read from the EDF header and threaded through the
    viewer, so 250 Hz and 500 Hz files are both supported.
    """
    with edf.Reader(str(edf_path)) as reader:
        data = reader.read(start=0)
        fs = int(reader.header.samples_per_record[0])
        start_time = parse_edf_start_datetime(reader.header)
    return Recording(
        data=data,
        fs=fs,
        start_time=start_time,
        ch_names=_CH_NAMES,
        edf_path=edf_path,
        csv_path=csv_path,
    )


def _load_state_df(csv_path: Path) -> pd.DataFrame | None:
    """Load a SPINDLE-scored CSV and drop UI-only columns. Return None on parse error."""
    try:
        df = pd.read_csv(csv_path)
        return df.drop(columns=["state", "threshold"], errors="ignore")
    except (OSError, pd.errors.ParserError):
        return None


class AnnotationMaskDialog(QtWidgets.QDialog):
    """Dialog for building a mask from annotation keyword matching.

    Shows the unique annotation labels found in the loaded file so the user
    knows what keywords to enter.  A live count updates as the user types.
    """

    def __init__(self, annotations: list[SwdAnnotation], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mask from Annotations")
        self.setMinimumWidth(440)
        self._annotations = annotations

        layout = QtWidgets.QVBoxLayout(self)

        # --- unique labels for reference ---
        unique = sorted({a.label for a in annotations if a.label.strip()})
        ref_lbl = QtWidgets.QLabel("Annotation labels found:")
        layout.addWidget(ref_lbl)
        labels_box = QtWidgets.QPlainTextEdit()
        labels_box.setPlainText("\n".join(unique))
        labels_box.setReadOnly(True)
        labels_box.setFixedHeight(90)
        layout.addWidget(labels_box)

        # --- keyword entry ---
        layout.addWidget(QtWidgets.QLabel("Keywords (comma-separated, case-insensitive):"))
        self._keyword_edit = QtWidgets.QLineEdit()
        self._keyword_edit.setPlaceholderText("e.g.  drink, artifact")
        layout.addWidget(self._keyword_edit)

        # --- match mode ---
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("Match mode:"))
        self._radio_contains = QtWidgets.QRadioButton("Contains")
        self._radio_exact = QtWidgets.QRadioButton("Exact")
        self._radio_contains.setChecked(True)
        self._radio_contains.setToolTip("Match any label that contains the keyword as a substring")
        self._radio_exact.setToolTip("Match only labels that equal the keyword exactly")
        mode_row.addWidget(self._radio_contains)
        mode_row.addWidget(self._radio_exact)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # --- padding ---
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._pad_before_spin = QtWidgets.QDoubleSpinBox()
        self._pad_before_spin.setRange(0.0, 3600.0)
        self._pad_before_spin.setSingleStep(1.0)
        self._pad_before_spin.setDecimals(1)
        self._pad_before_spin.setSuffix(" s")
        self._pad_before_spin.setValue(0.0)
        form.addRow("Pad before:", self._pad_before_spin)

        self._pad_after_spin = QtWidgets.QDoubleSpinBox()
        self._pad_after_spin.setRange(0.0, 3600.0)
        self._pad_after_spin.setSingleStep(1.0)
        self._pad_after_spin.setDecimals(1)
        self._pad_after_spin.setSuffix(" s")
        self._pad_after_spin.setValue(10.0)
        form.addRow("Pad after:", self._pad_after_spin)

        layout.addLayout(form)

        # --- live match count ---
        self._count_lbl = QtWidgets.QLabel()
        self._count_lbl.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(self._count_lbl)

        # --- buttons ---
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._keyword_edit.textChanged.connect(self._update_count)
        self._radio_contains.toggled.connect(self._update_count)
        self._update_count()

    def _update_count(self) -> None:
        keywords = [k.strip().lower() for k in self._keyword_edit.text().split(",") if k.strip()]
        if not keywords:
            self._count_lbl.setText("")
            return
        exact = self._radio_exact.isChecked()
        if exact:
            kw_set = set(keywords)
            n_match = sum(1 for a in self._annotations if a.label.strip().lower() in kw_set)
        else:
            n_match = sum(
                1
                for a in self._annotations
                if any(kw in a.label.strip().lower() for kw in keywords)
            )
        self._count_lbl.setText(f"{n_match} of {len(self._annotations)} annotations match")

    def values(self) -> tuple[list[str], float, float, str]:
        keywords = [k.strip() for k in self._keyword_edit.text().split(",") if k.strip()]
        match_mode = "exact" if self._radio_exact.isChecked() else "contains"
        return keywords, self._pad_before_spin.value(), self._pad_after_spin.value(), match_mode


class EegMainWindow(QtWidgets.QMainWindow):
    """Main EEG viewer window. Trace view + masks dock + optional QC toolbar."""

    _QC_STYLES: dict[str, str] = {
        "ok": "color: green; font-weight: bold;",
        "needs_review": "color: #b8860b; font-weight: bold;",
        "needs_rerun": "color: darkorange; font-weight: bold;",
    }

    def __init__(
        self,
        recording: Recording,
        initial_dir: str = "",
        manifest=None,
        animal_id: str | None = None,
        run_channels: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.rec = recording
        self.initial_dir = initial_dir
        self.manifest = manifest
        self.animal_id = animal_id
        self.run_channels = run_channels  # channel combo for the spindle run being reviewed

        self.mask_set = build_default_masks(recording)
        self.state_set = None
        self.state_df = None
        self._annotations: list[SwdAnnotation] = []
        self._annotation_file: AnnotationFile | None = None
        self._annotation_path = None
        self._last_annotation_label = "SWD"

        # STFT state
        self.stft_fmin = 0
        self.stft_fmax = 120
        self.nperseg = int(recording.fs * 0.5)  # 0.5 s window, fs-independent

        # Popups created once and reused so repeated menu clicks don't accumulate
        # hidden dialogs parented to self.
        self._stft_popup = STFTPopup(self, title="EEG STFT")
        self._stft_popup.resize(1200, 800)
        self._sleep_popup = SleepPopup(parent=self)
        self._sleep_popup.resize(1000, 800)

        self.setWindowTitle("EEG Viewer")
        self.resize(1200, 800)

        # central trace view
        self.trace_view = TraceView(
            data=recording.data,
            fs=recording.fs,
            start_time=recording.start_time,
            ch_names=recording.ch_names,
        )
        self.setCentralWidget(self.trace_view)
        self.trace_view.set_masks(self.mask_set)

        if recording.csv_path is not None:
            self.state_set = load_state_masks(recording.csv_path, int(recording.fs))
            self.trace_view.set_state_masks(self.state_set)
            self.state_df = _load_state_df(recording.csv_path)

        # actions/toolbars/menus
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        if (
            self.manifest is not None
            and self.animal_id is not None
            and self.run_channels is not None
        ):
            self._build_qc_toolbar()
        self._build_docks()

        self.trace_view.timeDoubleClicked.connect(self.on_time_double_clicked)
        self.trace_view.annotationDragCreated.connect(self.on_annotation_dragged)

    # ---------- actions ----------

    def _build_actions(self):
        self.act_open = QtGui.QAction("&Open…", self)
        self.act_open.setShortcut("Ctrl+O")
        self.act_open.triggered.connect(self.on_open)

        self.act_quit = QtGui.QAction("&Quit", self)
        self.act_quit.setShortcut("Ctrl+Q")
        self.act_quit.triggered.connect(self.close)

        self.act_info = QtGui.QAction("Session Information", self)
        self.act_info.triggered.connect(self.on_view_session_info)

        self.act_load_swd = QtGui.QAction("Load SWD mask (.mat)", self)
        self.act_load_swd.triggered.connect(self.on_load_swd)

        self.act_load_drink = QtGui.QAction("Load Drink mask (.npy)", self)
        self.act_load_drink.triggered.connect(self.on_load_drink)

        self.act_stft = QtGui.QAction("Plot STFT", self)
        self.act_stft.setShortcut("Ctrl+S")
        self.act_stft.triggered.connect(self.on_show_stft)

        self.act_stft_bounds = QtGui.QAction("STFT Bounds…", self)
        self.act_stft_bounds.triggered.connect(self.on_stft_bounds)

        self.act_plot_sleep = QtGui.QAction("Plot Sleep Data", self)
        self.act_plot_sleep.triggered.connect(self.on_plot_sleep)

        self.act_load_annotations = QtGui.QAction("Load Annotations…", self)
        self.act_load_annotations.triggered.connect(self.on_load_annotations)

        self.act_load_annotation_dir = QtGui.QAction("Load Annotation Directory…", self)
        self.act_load_annotation_dir.triggered.connect(self.on_load_annotation_dir)

        self.act_mask_annotations = QtGui.QAction("Mask from Annotations…", self)
        self.act_mask_annotations.setEnabled(False)
        self.act_mask_annotations.triggered.connect(self.on_mask_from_annotations)

        self.act_save_annotations = QtGui.QAction("Save Annotations…", self)
        self.act_save_annotations.setEnabled(False)
        self.act_save_annotations.triggered.connect(self.on_save_annotations)

        self.act_add_annotation = QtGui.QAction("Add Annotation", self)
        self.act_add_annotation.setShortcut("A")
        self.act_add_annotation.triggered.connect(self.on_add_annotation)

        self.act_rename_annotation = QtGui.QAction("Rename Annotation", self)
        # F2 (the conventional rename key) rather than "R", which would shadow
        # the trace view's r/Shift+R REM-epoch navigation.
        self.act_rename_annotation.setShortcut("F2")
        self.act_rename_annotation.triggered.connect(self.on_rename_annotation)

        self.act_delete_annotation = QtGui.QAction("Delete Annotation", self)
        self.act_delete_annotation.setShortcut(QtGui.QKeySequence.StandardKey.Delete)
        self.act_delete_annotation.setEnabled(False)
        self.act_delete_annotation.triggered.connect(self.on_delete_annotation)

        self.act_next_annotation = QtGui.QAction("Next Annotation", self)
        self.act_next_annotation.setShortcut("]")
        self.act_next_annotation.triggered.connect(self.trace_view.jump_to_next_annotation)

        self.act_prev_annotation = QtGui.QAction("Previous Annotation", self)
        self.act_prev_annotation.setShortcut("[")
        self.act_prev_annotation.triggered.connect(self.trace_view.jump_to_prev_annotation)

    # ---------- menus / toolbars / docks ----------

    def _build_menus(self):
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_load_swd)
        m_file.addAction(self.act_load_drink)
        m_file.addAction(self.act_load_annotations)
        m_file.addAction(self.act_load_annotation_dir)
        m_file.addAction(self.act_mask_annotations)
        m_file.addAction(self.act_save_annotations)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)
        m_file.addAction(self.act_info)

        m_view = mb.addMenu("&View")
        m_view.addAction(self.act_plot_sleep)
        m_view.addSeparator()
        m_view.addAction(self.act_prev_annotation)
        m_view.addAction(self.act_next_annotation)
        m_view.addAction(self.act_add_annotation)
        m_view.addAction(self.act_rename_annotation)
        m_view.addAction(self.act_delete_annotation)

        m_tools = mb.addMenu("&Tools")
        m_tools.addAction(self.act_stft)
        m_tools.addAction(self.act_stft_bounds)

    def _build_toolbars(self):
        nav_tb = self.addToolBar("Navigation")
        nav_tb.setObjectName("NavigationToolbar")
        nav_tb.addAction(self.act_open)
        nav_tb.addAction(self.act_load_swd)
        nav_tb.addAction(self.act_load_drink)

        tools_tb = self.addToolBar("Tools")
        tools_tb.setObjectName("ToolsToolbar")
        tools_tb.addAction(self.act_stft)

    def on_show_stft(self):
        self._stft_popup.plot_window(
            data=self.rec.data,
            fs=self.rec.fs,
            ch_names=self.rec.ch_names,
            start_idx=self.trace_view.start,
            win_len=self.trace_view.win,
            nperseg=self.nperseg,
            fmin=self.stft_fmin,
            fmax=self.stft_fmax,
        )
        self._stft_popup.resize(1000, 800)
        self._stft_popup.show()
        self._stft_popup.raise_()

    def on_stft_bounds(self):
        dlg = STFTBoundsDialog(
            fs=int(self.rec.fs),
            nperseg=self.nperseg,
            fmin=self.stft_fmin,
            fmax=self.stft_fmax,
            parent=self,
        )
        if dlg.exec():
            self.stft_fmin, self.stft_fmax = dlg.values()

    def on_plot_sleep(self):
        if not self.rec.csv_path:
            return
        self._sleep_popup.plot_sleep(self.rec.csv_path)
        self._sleep_popup.show()
        self._sleep_popup.raise_()

    def _navigate_mask(self, mask, forward: bool) -> None:
        span = (
            mask.next_span_after(self.trace_view.center_sample)
            if forward
            else mask.prev_span_before(self.trace_view.center_sample)
        )
        if span is not None:
            self.trace_view.jump_to_sample(span[0])

    def _build_docks(self):
        self.masks_dock = MasksDock(
            refresh_overlays=self.trace_view.refresh_overlays,
            navigate_mask=self._navigate_mask,
            on_mask_rebuild=self._on_mask_rebuild,
            parent=self,
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.masks_dock)

        self.masks_dock.rebuild(self.mask_set, self.state_set)

    def _build_qc_toolbar(self):
        qc_tb = self.addToolBar("QC")
        qc_tb.setObjectName("QCToolbar")
        qc_tb.setMovable(False)

        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        qc_tb.addWidget(spacer)

        self._qc_status_label = QtWidgets.QLabel()
        self._qc_status_label.setMinimumWidth(130)
        qc_tb.addWidget(self._qc_status_label)
        qc_tb.addSeparator()

        self._act_ok = QtGui.QAction("✓ Mark OK", self)
        self._act_ok.setCheckable(True)
        self._act_ok.triggered.connect(self._flag_qc_ok)
        qc_tb.addAction(self._act_ok)

        qc_tb.addSeparator()

        # Rerun combo: pick a different combo from the current run_channels
        self._rerun_combo = QtWidgets.QComboBox()
        self._rerun_combo.addItems(CHANNEL_COMBOS)
        run = self.manifest.get_run(self.animal_id, self.run_channels)
        if run and run.rerun_combo and run.rerun_combo in CHANNEL_COMBOS:
            self._rerun_combo.setCurrentText(run.rerun_combo)
        else:
            others = [c for c in CHANNEL_COMBOS if c != self.run_channels]
            if others:
                self._rerun_combo.setCurrentText(others[0])
        qc_tb.addWidget(self._rerun_combo)

        self._act_rerun = QtGui.QAction("Needs Rerun", self)
        self._act_rerun.setCheckable(True)
        self._act_rerun.triggered.connect(self._flag_qc_rerun)
        qc_tb.addAction(self._act_rerun)

        self._update_qc_status()

    def _flag_qc_ok(self) -> None:
        self.manifest.flag_sleep_qc(self.animal_id, self.run_channels, "ok")
        self._update_qc_status()

    def _flag_qc_rerun(self) -> None:
        rerun_combo = self._rerun_combo.currentText()
        self.manifest.flag_sleep_qc(
            self.animal_id, self.run_channels, "needs_rerun", rerun_combo=rerun_combo
        )
        self._update_qc_status()

    def _update_qc_status(self) -> None:
        run = self.manifest.get_run(self.animal_id, self.run_channels)
        status = run.sleep_qc if run else None
        txt = (status or "unflagged").replace("_", " ")
        self._qc_status_label.setText(f"QC [{self.run_channels}]: {txt}")
        self._qc_status_label.setStyleSheet(self._QC_STYLES.get(status, ""))
        self._act_ok.setChecked(status == "ok")
        self._act_rerun.setChecked(status == "needs_rerun")

    def _on_mask_rebuild(self, mask) -> None:
        name = mask.name
        if name in ("commutator", "sd"):
            comm_meta = self.mask_set.get("commutator").metadata
            sd_meta = self.mask_set.get("sd").metadata
            new_c, new_sd = rebuild_artifact_masks(self.rec, comm_meta, sd_meta)
            self.mask_set.add(new_c)
            self.mask_set.add(new_sd)
        elif name == "spindle_noise" and self.rec.csv_path:
            new_sp = rebuild_spindle_mask(self.rec.csv_path, int(self.rec.fs), mask.metadata)
            self.mask_set.add(new_sp)
        elif name == "drink" and self.rec.drink_path:
            new_drink = rebuild_drink_mask(self.rec.drink_path, self.rec.fs, mask.metadata)
            self.mask_set.add(new_drink)
        elif name == "annotation" and self._annotation_path:
            _, n_samples = self.rec.data.shape
            new_ann = rebuild_annotation_mask(
                self._annotation_path,
                n_samples=n_samples,
                fs=self.rec.fs,
                meta=mask.metadata,
            )
            self.mask_set.add(new_ann)

        self.trace_view.refresh_overlays()
        self.masks_dock.rebuild(self.mask_set, self.state_set)

    # ---------- behavior ----------

    def on_load_swd(self):
        mat_path = pick_mat(self, self.initial_dir)
        if mat_path is None:
            return

        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Name SWD Mask",
            "Mask name:",
            text=self._unique_swd_name(mat_path.stem),
        )
        if not ok:
            return
        name = name.strip() or self._unique_swd_name(mat_path.stem)
        if name in self.mask_set.masks:
            name = self._unique_swd_name(name)

        swd_idx = getattr(self, "_swd_load_count", 0)
        color = SWD_COLORS[swd_idx % len(SWD_COLORS)]

        try:
            _, n_samples = self.rec.data.shape
            self.mask_set.add(
                load_swd_mask(
                    mat_path,
                    fs=self.rec.fs,
                    n_samples=n_samples,
                    name=name,
                    color=color,
                )
            )
            self._swd_load_count = swd_idx + 1
            self.trace_view.refresh_overlays()
            self.masks_dock.rebuild(self.mask_set, self.state_set)
            self.rec.swd_path = mat_path
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load Error", f"{type(e).__name__}: {e}")

    def _unique_swd_name(self, base: str) -> str:
        """Return a mask name based on ``base`` not already in the mask set."""
        if base not in self.mask_set.masks:
            return base
        i = 2
        while f"{base} ({i})" in self.mask_set.masks:
            i += 1
        return f"{base} ({i})"

    def on_load_drink(self):
        drink_path, offset_path = pick_npy_csv(self, self.initial_dir)
        if drink_path is None:
            return

        offset = 0.0
        try:
            if offset_path is not None:
                offset = get_offset(drink_path, offset_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load Error", f"{type(e).__name__}: {e}")
            return

        dlg = DrinkMaskDialogue(
            drink_path=drink_path,
            offset_val=offset,
            pad=0,
            parent=self,
        )
        if dlg.exec():
            pad_sec, offset = dlg.values()
            try:
                self.mask_set.add(
                    load_drink_mask(drink_path, fs=self.rec.fs, offset_sec=offset, pad_sec=pad_sec)
                )
                self.trace_view.refresh_overlays()
                self.masks_dock.rebuild(self.mask_set, self.state_set)
                self.rec.drink_path = drink_path
                self.rec.video_offset = offset
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Load Error", f"{type(e).__name__}: {e}")

    def _load_annotation_file(self, csv_path: Path) -> None:
        """Load a single annotation file and enable masking + editing."""
        annfile = load_annotation_file(csv_path)
        self.trace_view.set_annotations(annfile.annotations)
        self._annotation_file = annfile
        self._annotations = annfile.annotations
        self._annotation_path = csv_path
        self.act_mask_annotations.setEnabled(True)
        self.act_save_annotations.setEnabled(True)
        self.act_delete_annotation.setEnabled(bool(annfile.annotations))

    def _ensure_annotation_file(self) -> AnnotationFile:
        """Return the active annotation file, creating an empty one if needed.

        Lets the user add annotations to a recording that has no annotation
        file loaded. The new file shares ``self._annotations`` so add/delete
        and drag edits all flow into the same list that save reads.
        """
        if self._annotation_file is None:
            animal_id = self.animal_id or parse_animal_id(self.rec.edf_path)
            self._annotation_file = AnnotationFile(
                path=None,
                header_lines=default_header_lines(animal_id=animal_id),
                columns=list(DEFAULT_COLUMNS),
                delimiter="\t",
                start_clock=self.rec.start_time,
                annotations=self._annotations,
            )
        return self._annotation_file

    def _append_annotation(self, label: str, start_sec: float, end_sec: float) -> SwdAnnotation:
        """Create, store, and draw a new span; enable save/delete actions."""
        self._ensure_annotation_file()  # so a from-scratch set is saveable
        number = max((a.number for a in self._annotations), default=-1) + 1
        ann = SwdAnnotation(
            number=number,
            label=label.strip(),
            start_sec=start_sec,
            end_sec=end_sec,
            channel="ALL",
        )
        self._annotations.append(ann)
        self.trace_view.set_annotations(self._annotations)
        self.act_save_annotations.setEnabled(True)
        self.act_delete_annotation.setEnabled(True)
        return ann

    def on_add_annotation(self):
        """Create a default-width annotation span at the playhead."""
        label, ok = QtWidgets.QInputDialog.getText(
            self, "Add Annotation", "Label:", text=self._last_annotation_label
        )
        if not ok:
            return
        self._last_annotation_label = label.strip()
        t = self.trace_view.center_sample / self.rec.fs
        ann = self._append_annotation(self._last_annotation_label, t, t + DEFAULT_SPAN_SEC)
        self.trace_view.jump_to_sample(int(ann.start_sec * self.rec.fs))

    def on_annotation_dragged(self, start_sec: float, end_sec: float):
        """Create a span from a right-click drag, reusing the last-used label."""
        self._append_annotation(self._last_annotation_label, start_sec, end_sec)

    def on_rename_annotation(self):
        """Relabel the annotation under the playhead; remember the new label."""
        self._rename_annotation(self.trace_view.annotation_at_center())

    def _rename_annotation(self, ann: SwdAnnotation | None) -> None:
        """Prompt to relabel ``ann`` (no-op if ``None``); remember the label."""
        if ann is None:
            return
        label, ok = QtWidgets.QInputDialog.getText(
            self, "Rename Annotation", "Label:", text=ann.label
        )
        if not ok:
            return
        ann.label = label.strip()
        self._last_annotation_label = ann.label
        self.trace_view.set_annotations(self._annotations)

    def on_delete_annotation(self):
        """Delete the annotation under the playhead after confirmation."""
        ann = self.trace_view.annotation_at_center()
        if ann is None:
            return
        resp = QtWidgets.QMessageBox.question(
            self,
            "Delete Annotation",
            f"Delete '{ann.label}' ({ann.start_sec:.2f}–{ann.end_sec:.2f} s)?",
        )
        if resp != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._annotations.remove(ann)
        self.trace_view.set_annotations(self._annotations)
        self.act_delete_annotation.setEnabled(bool(self._annotations))

    def on_save_annotations(self):
        """Write the edited annotation spans to a sidecar file."""
        annfile = self._ensure_annotation_file()
        if self._annotation_path is not None:
            default = sidecar_path(self._annotation_path)
        else:
            edf = self.rec.edf_path
            default = edf.with_name(f"{edf.stem}_annotations.csv")
        out, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Edited Annotations",
            str(default),
            "Annotation files (*.csv *.txt *.tsv);;All files (*)",
        )
        if not out:
            return
        try:
            written = save_annotation_file(annfile, out)
            QtWidgets.QMessageBox.information(
                self, "Annotations Saved", f"Saved {len(self._annotations)} annotations to:\n{written}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save Error", f"{type(e).__name__}: {e}")

    def on_load_annotations(self):
        csv_path = pick_annotations_csv(self, self.initial_dir)
        if csv_path is None:
            return
        try:
            self._load_annotation_file(csv_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load Error", f"{type(e).__name__}: {e}")

    def on_load_annotation_dir(self):
        """Select an annotation directory; auto-match the file for the current animal."""
        dir_path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Annotation Directory", self.initial_dir
        )
        if not dir_path:
            return
        animal_id = self.animal_id or parse_animal_id(self.rec.edf_path)
        matches = (
            sorted(Path(dir_path).glob(f"{animal_id}*.txt"))
            + sorted(Path(dir_path).glob(f"{animal_id}*.csv"))
            + sorted(Path(dir_path).glob(f"{animal_id}*.tsv"))
        )
        if not matches:
            QtWidgets.QMessageBox.warning(
                self,
                "No Annotation File Found",
                f"No annotation file starting with '{animal_id}' found in:\n{dir_path}",
            )
            return
        try:
            self._load_annotation_file(matches[0])
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load Error", f"{type(e).__name__}: {e}")

    def on_mask_from_annotations(self):
        dlg = AnnotationMaskDialog(self._annotations, parent=self)
        if not dlg.exec():
            return
        keywords, pad_before_sec, pad_after_sec, match_mode = dlg.values()
        if not keywords:
            QtWidgets.QMessageBox.warning(self, "No keywords", "Enter at least one keyword.")
            return
        try:
            _, n_samples = self.rec.data.shape
            mask = build_annotation_mask(
                self._annotation_path,
                keywords=keywords,
                pad_before_sec=pad_before_sec,
                pad_after_sec=pad_after_sec,
                match_mode=match_mode,
                n_samples=n_samples,
                fs=self.rec.fs,
            )
            self.mask_set.add(mask)
            self.trace_view.refresh_overlays()
            self.masks_dock.rebuild(self.mask_set, self.state_set)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Mask Error", f"{type(e).__name__}: {e}")

    def on_open(self):
        edf_path, csv_path = pick_edf_csv(self, self.initial_dir)
        if not edf_path:
            return

        try:
            rec = _load_recording(edf_path, csv_path)
        except Exception as e:  # noqa: BLE001 — surface any load failure as a dialog
            QtWidgets.QMessageBox.critical(self, "Load Error", f"{type(e).__name__}: {e}")
            return

        # Open as a separate, independent window. WA_DeleteOnClose ensures the
        # window is freed when the user closes it instead of lingering as a
        # hidden child of self.
        win = EegMainWindow(rec, initial_dir=self.initial_dir)
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.resize(self.width(), self.height())
        win.show()

    def on_time_double_clicked(self, t_sec: float):
        # A double-click landing inside an annotation span renames it.
        ann = self.trace_view.annotation_at_time(t_sec)
        if ann is not None:
            self._rename_annotation(ann)
            return
        if self.state_df is None:
            return
        epoch_samples = int(DEFAULT_SPINDLE_EPOCH_SEC * self.rec.fs)
        row = int(t_sec * self.rec.fs) // epoch_samples
        row = max(0, min(row, len(self.state_df) - 1))
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("Spindle Epoch")
        msg.setText(self.state_df.iloc[row].to_string())
        msg.exec()

    def on_view_session_info(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Session Information")
        text = QtWidgets.QPlainTextEdit(str(self.rec), dlg)
        text.setReadOnly(True)
        text.setMinimumWidth(1200)
        text.setFont(QtGui.QFont("Monospace"))
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(text)
        dlg.exec()


def launch_edf_window(
    edf_path: Path,
    csv_path: Path | None = None,
    manifest=None,
    animal_id: str | None = None,
    run_channels: str | None = None,
    initial_dir: str = "",
) -> EegMainWindow:
    """Load an EDF file and return a configured (not yet shown) EegMainWindow.

    The EDF's sampling rate is read from its header; 250 Hz and 500 Hz files
    are both supported.
    """
    rec = _load_recording(edf_path, csv_path)
    win = EegMainWindow(
        rec,
        initial_dir=initial_dir,
        manifest=manifest,
        animal_id=animal_id,
        run_channels=run_channels,
    )
    win.setWindowTitle(f"{edf_path.stem} — EEG Viewer")
    return win


def main():
    """Standalone launcher: pick an EDF (and optional state CSV), open the viewer.

    Usage: ``ebb-eeg-viewer [initial_dir]``
    """
    force_xcb_on_wayland()  # must precede QApplication; see qt_platform
    app = QtWidgets.QApplication(sys.argv)
    initial_dir = sys.argv[1] if len(sys.argv) > 1 else ""

    edf_path, csv_path = pick_edf_csv(None, initial_dir)
    if not edf_path:
        return

    try:
        win = launch_edf_window(edf_path, csv_path=csv_path, initial_dir=initial_dir)
    except Exception as e:  # noqa: BLE001 — surface any load failure as a dialog
        QtWidgets.QMessageBox.critical(None, "Load Error", f"{type(e).__name__}: {e}")
        return

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
