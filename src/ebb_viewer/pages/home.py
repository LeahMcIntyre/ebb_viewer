"""Home page — what to do next, per-animal work, and the animal summary.

Top to bottom: a "next step" banner and a compact progress strip (one chip
per step, fed by ``compute_pipeline_status``), a "Needs Attention" zone
grouped by reason (review-EDF / drink-mask; hidden when empty), and a
per-animal status table. Manifest mutations triggered from attention-card
buttons persist via ``Manifest.flag_sleep_qc``'s internal ``save()``.
"""

import contextlib
from pathlib import Path
from typing import Literal, NamedTuple

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ebb.core.naming import parse_animal_id
from ebb.io.spindle_csv import FINAL_COLUMN, has_column
from ebb.process.sleep_flagging import METRIC_BY_KEY
from ebb_viewer.edf_viewer.eeg_viewer import launch_edf_window
from ebb_viewer.pipeline import psd_params as _psd_params
from ebb_viewer.pipeline.manifest import (
    Manifest,
    ManifestEntry,
    psd_path,
    psd_status_label,
    spindle_edf_dir,
    spindle_output_dir,
    swd_review_status,
)
from ebb_viewer.pipeline.naming import drink_mask_rel
from ebb_viewer.pipeline.swd_review import find_swd_file, swd_review_gaps
from ebb_viewer.pipeline.theme import STATUS_COLOR_HEX
from ebb_viewer.widgets.notes_dialog import NotesDialog
from ebb_viewer.widgets.table_helpers import make_cell

# Pipeline stage columns
_COLUMNS = [
    "Animal",
    "Spindle Output",
    "SWD",
    "QC Status",
    "PSD Status",
    "Notes",
]
_COL_ANIMAL = _COLUMNS.index("Animal")
_COL_SPINDLE_OUT = _COLUMNS.index("Spindle Output")
_COL_SWD = _COLUMNS.index("SWD")
_COL_SLEEP_QC = _COLUMNS.index("QC Status")
_COL_PSD_STATUS = _COLUMNS.index("PSD Status")
_COL_NOTES = _COLUMNS.index("Notes")

_STATUS_COLOR = {k: QColor(v) for k, v in STATUS_COLOR_HEX.items()}
_PENDING_COLOR = QColor("#f0f0f0")  # light gray = reached but not yet flagged
_EXISTS_COLOR = QColor("#d4edda")  # green

_SWD_REVIEW_LABEL = {"done": "reviewed ✓", "in_progress": "in progress", "not_started": "to review"}
_SWD_MISSING_COLOR = QColor("#fff3cd")  # amber

_SLEEP_QC_LABEL: dict[str, str] = {
    "needs_review": "Review EDF",
    "excluded": "Excluded",
}


# ---------------------------------------------------------------------------
# Pipeline guide
# ---------------------------------------------------------------------------
StepKind = Literal["done", "attention", "active", "blocked", "off"]


class StepStatus(NamedTuple):
    kind: StepKind
    description: str


_STEP_LABELS = [
    "1. Preprocess",
    "2. Spindle EDFs",
    "3. Spindle Upload",
    "4. Reclassify",
    "4b. SWD Review",
    "5. Sleep QC",
    "6. PSD Computation",
    "7. PSD Review",
    "8. Drink Mask",
    "9. Finalize",
]

_STEP_PAGE_NAMES = [
    "preprocess",
    "spindle_write",
    "spindle_upload",
    "reclassify",
    "swd_review",
    "sleep_qc",
    "psd_compute",
    "psd_review",
    "drink_mask",
    "finalize",
]

# Short chip labels for the progress strip, parallel to _STEP_LABELS.
_STEP_SHORT = [
    "Preprocess",
    "Spindle EDFs",
    "Upload",
    "Reclassify",
    "SWD Review",
    "Sleep QC",
    "PSDs",
    "PSD Review",
    "Drink Mask",
    "Finalize",
]
_SWD_STEP_IDX = _STEP_PAGE_NAMES.index("swd_review")

_GUIDE_ICON = {"done": "✓", "attention": "⚠", "active": "→", "blocked": "○", "off": "–"}
_GUIDE_ICON_COLOR = {
    "done": "#3a7d44",
    "attention": "#b06000",
    "active": "#1a5fa8",
    "blocked": "#999999",
    "off": "#999999",
}
_GUIDE_ROW_HIGHLIGHT = "#eef4fc"

# Attention-zone layout — keep in sync with _make_card_frame.setMaximumHeight
# and _attn_layout.setSpacing.
_ATTN_CARD_HEIGHT_PX = 42
_ATTN_CARD_STRIDE_PX = 48  # card + per-card layout overhead
_ATTN_HEADER_STRIDE_PX = 24  # group header label + spacing


def compute_pipeline_status(
    project_root: Path,
    manifest: Manifest,
    *,
    psd_runs: list[str] | None = None,
) -> list[StepStatus]:
    """Derive the 10 pipeline-step statuses driving the home-page guide.

    Pure logic (no Qt). Reads ``manifest`` plus filesystem state under
    ``project_root`` (``standard/``, ``spindle_edfs/``, ``spindle_outputs/``,
    ``psd/``). Returns the steps in pipeline order — preprocess → drink mask (reclassify sits between upload and sleep QC).

    Args:
        psd_runs: Optional pre-computed result of ``psd_params.list_runs``.
            When omitted, scanned here. Threaded by ``HomePage._refresh``
            so a single page refresh doesn't scan ``psd/`` twice.

    Tests live in ``tests/ebb_viewer/test_compute_pipeline_status.py``.
    """
    root = Path(project_root)

    # --- filesystem facts ---
    # Step 1 done: standard dir exists and has at least 1 edf
    standard_dir = root / "standard"
    standard_edfs = list(standard_dir.glob("*.edf")) if standard_dir.is_dir() else []
    step1_done = bool(standard_edfs)

    # Step 2 done: the project combo's spindle_edfs folder has at least 1 edf
    step2_done = any(spindle_edf_dir(manifest.combo, root).glob("*.edf"))

    # Step 3 done: the project combo's spindle_outputs folder has at least 1 csv
    step3_done = any(spindle_output_dir(manifest.combo, root).glob("*.csv"))

    # --- manifest facts ---
    n_review = len(manifest.needs_review())
    n_pending_qc = len(manifest.pending_sleep_qc())
    n_animals = len(manifest)
    n_ok = len(manifest.ready_for_psd())  # ok + excluded
    n_excluded = sum(1 for e in manifest.ready_for_psd() if e.sleep_qc == "excluded")
    n_psd_pending = len(manifest.all_pending_psd_review())
    n_verify = len(manifest.all_pending_drink_verification())

    # --- Step 1: Preprocess ---
    if step1_done:
        n = len(standard_edfs)
        s1 = StepStatus("done", f"{n} EDF{'s' if n != 1 else ''} in standard/")
    else:
        s1 = StepStatus("active", "Start here — run preprocessor on raw EDF files")

    # --- Step 2: Spindle EDFs ---
    if step2_done or step3_done:  # outputs downloaded ⇒ EDFs were written (even if since deleted)
        s2 = StepStatus("done", "Spindle EDFs written")
    elif step1_done:
        s2 = StepStatus("active", "Ready — write spindle EDFs from standard/")
    else:
        s2 = StepStatus("blocked", "Requires step 1")

    # --- Step 3: Upload & Download ---
    if step3_done:
        s3 = StepStatus("done", "Spindle output CSVs downloaded")
    elif step2_done:
        s3 = StepStatus("active", "Ready — upload spindle EDFs to SleepyRat")
    else:
        s3 = StepStatus("blocked", "Requires step 2")

    # --- Step 4: Reclassify ---
    # Ground truth is the CSVs themselves (a final_state column), not the manifest:
    # re-downloading a CSV from SleepyRat drops the column but leaves the manifest flag.
    csvs = list(spindle_output_dir(manifest.combo, root).glob("*.csv"))
    n_csvs = len(csvs)
    n_reclassed = sum(1 for p in csvs if has_column(p, FINAL_COLUMN))
    n_gated = sum(1 for e in manifest if e.reclass_gate_applied)
    n_gate_unknown = sum(
        1
        for p in csvs
        if has_column(p, FINAL_COLUMN)
        and ((e := manifest.get(parse_animal_id(p))) is None or e.reclass_gate_applied is None)
    )
    if not step3_done:
        s_reclass = StepStatus("blocked", "Requires step 3")
    elif n_reclassed == n_csvs:
        note = f"; gate record missing for {n_gate_unknown}" if n_gate_unknown else ""
        s_reclass = StepStatus("done", f"{n_reclassed} reclassified (EMG gate on {n_gated}{note})")
    elif n_reclassed > 0:
        s_reclass = StepStatus(
            "attention", f"{n_csvs - n_reclassed} of {n_csvs} CSVs not reclassified"
        )
    else:
        s_reclass = StepStatus("active", "Ready — reclassify NREM before Sleep QC")

    # --- Step 4b: SWD Review (optional, project opt-in) ---
    if not manifest.swd_review_enabled:
        s_swd = StepStatus("off", "Not enabled (optional)")
    elif s_reclass.kind != "done":
        s_swd = StepStatus("blocked", "Requires Reclassify (step 4)")
    else:
        gaps = swd_review_gaps(root, manifest)
        animals = [e for e in manifest if e.has_spindle]
        n_done = sum(
            1
            for e in animals
            if find_swd_file(root, e.animal_id) and swd_review_status(e) == "done"
        )
        n_started = sum(
            1
            for e in animals
            if find_swd_file(root, e.animal_id) and swd_review_status(e) == "in_progress"
        )
        if not gaps:
            s_swd = StepStatus("done", f"{n_done} animal{'s' if n_done != 1 else ''} reviewed")
        else:
            parts = []
            if gaps.missing:
                parts.append(f"{len(gaps.missing)} without an SWD file")
            if n_done or n_started:
                parts.append(f"{n_done} of {n_done + len(gaps.unfinished)} reviewed")
                if n_started:
                    parts.append(f"{n_started} in progress")
            elif gaps.unfinished:
                parts.append("Ready — review SWD epochs")
            kind = "attention" if (gaps.missing or n_done or n_started) else "active"
            s_swd = StepStatus(kind, ", ".join(parts))

    # --- Step 5: Sleep QC ---
    if step3_done and n_pending_qc == 0 and n_review == 0 and n_ok > 0:
        excluded = f", {n_excluded} excluded" if n_excluded else ""
        s4 = StepStatus(
            "done",
            f"{n_ok - n_excluded} animal{'s' if n_ok - n_excluded != 1 else ''} marked ok{excluded}",
        )
    elif step3_done and (n_review > 0 or n_pending_qc > 0):
        parts = []
        if n_review:
            parts.append(f"{n_review} flagged for EDF review")
        if n_pending_qc:
            parts.append(f"{n_pending_qc} not yet assessed")
        s4 = StepStatus("attention", ", ".join(parts))
    elif step3_done:
        s4 = StepStatus("active", "Ready — review sleep QC for each animal")
    else:
        s4 = StepStatus("blocked", "Requires step 3")

    # --- Step 5: PSD Computation ---
    if psd_runs is None:
        psd_runs = _psd_params.list_runs(root)
    any_psd_pkl = any(psd_path(manifest.combo, root, rn).exists() for rn in psd_runs)
    all_ready_for_psd = n_animals > 0 and n_ok == n_animals

    if psd_runs and any_psd_pkl:
        n_runs = len(psd_runs)
        s5 = StepStatus("done", f"{n_runs} run{'s' if n_runs != 1 else ''} computed — PSDs ready")
    elif all_ready_for_psd:
        excluded = f" ({n_excluded} excluded, still computed)" if n_excluded else " marked ok"
        s5 = StepStatus(
            "active",
            f"Ready — {n_animals} animal{'s' if n_animals != 1 else ''}{excluded}",
        )
    elif n_ok > 0:
        n_not_ready = n_animals - n_ok
        s5 = StepStatus(
            "blocked", f"{n_not_ready} animal{'s' if n_not_ready != 1 else ''} not yet ready"
        )
    else:
        s5 = StepStatus("blocked", "Requires all animals to be marked ok (step 5)")

    # --- Step 6: PSD Review ---
    n_needs_drink = len(manifest.all_needs_drink_mask())
    if n_psd_pending > 0:
        s6 = StepStatus(
            "attention", f"{n_psd_pending} PSD{'s' if n_psd_pending != 1 else ''} to review"
        )
    elif n_verify > 0:
        s6 = StepStatus(
            "attention",
            f"{n_verify} drink-masked PSD{'s' if n_verify != 1 else ''} to verify",
        )
    elif n_needs_drink > 0 and any_psd_pkl:
        s6 = StepStatus(
            "attention",
            f"{n_needs_drink} animal{'s' if n_needs_drink != 1 else ''} need drink mask",
        )
    elif any_psd_pkl and n_psd_pending == 0:
        s6 = StepStatus("done", "All PSDs reviewed")
    elif any_psd_pkl:
        s6 = StepStatus("active", "Ready — open PSD Review page")
    else:
        s6 = StepStatus("blocked", "Requires computed PSDs (step 6)")

    # --- Step 7: Drink Mask ---
    # n_needs_drink already computed above
    n_drink_applied = sum(1 for e in manifest if "drink_mask_applied" in e.psd_status.values())
    if not any_psd_pkl:
        s7 = StepStatus("blocked", "Requires computed PSDs (step 6)")
    elif n_needs_drink > 0:
        s7 = StepStatus(
            "attention",
            f"{n_needs_drink} animal{'s' if n_needs_drink != 1 else ''} need drink mask",
        )
    elif n_drink_applied > 0:
        s7 = StepStatus(
            "done",
            f"{n_drink_applied} drink mask{'s' if n_drink_applied != 1 else ''} applied",
        )
    else:
        s7 = StepStatus("done", "No drink masks needed")

    # --- Step 9: Finalize (seal each computed PSD run into psds_final.pkl) ---
    # Sealing is detected by the file existing; a change made after sealing (a new exclusion,
    # a re-run drink mask) is not detected, so Finalize shows done until re-run. The sleep
    # export is not part of this step.
    computed = [rn for rn in psd_runs if psd_path(manifest.combo, root, rn).exists()]
    n_sealed = sum(1 for rn in computed if (root / "psd" / rn / "psds_final.pkl").exists())
    n_unsealed = len(computed) - n_sealed
    if s4.kind != "done":
        s8 = StepStatus("blocked", "Requires Sleep QC (step 5)")
    elif not any_psd_pkl or s6.kind == "attention" or s7.kind == "attention":
        s8 = StepStatus("blocked", "Requires PSD review and drink masks (steps 7-8)")
    elif n_unsealed == 0:
        s8 = StepStatus("done", f"{n_sealed} run{'s' if n_sealed != 1 else ''} finalized")
    elif n_sealed:
        s8 = StepStatus("attention", f"{n_sealed} of {len(computed)} runs finalized")
    else:
        s8 = StepStatus(
            "active", f"Ready — {n_unsealed} run{'s' if n_unsealed != 1 else ''} to finalize"
        )

    return [s1, s2, s3, s_reclass, s_swd, s4, s5, s6, s7, s8]


def _any_file_for_animal(root: Path, subdir: str, channels: str, animal_id: str) -> bool:
    """True if any file matching animal_id* exists in root/subdir/channels/."""
    d = root / subdir / channels
    return d.is_dir() and any(d.glob(f"{animal_id}*"))


def _needs_attention(
    entry: ManifestEntry, spindle_out_ok: bool, psd_file_ok: bool, psd_status: str | None
) -> bool:
    """True if this animal has outstanding Sleep QC or PSD work. Excluded animals never do."""
    if entry.sleep_qc == "excluded":
        return False
    if entry.sleep_qc == "needs_review" or (entry.sleep_qc is None and spindle_out_ok):
        return True
    return psd_status == "needs_drink_mask" or (psd_file_ok and psd_status is None)


def combo_text(root: Path, combo: str) -> str:
    """Header text naming the project's channel combo, and whether it has been chosen yet.

    The combo is chosen by writing SPINDLE EDFs (page 2); until a ``spindle_edfs/<combo>`` folder
    holds files, ``combo`` is only the default.
    """
    if any(spindle_edf_dir(combo, root).glob("*.edf")):
        return f"Channel combo: {combo}"
    return f"Channel combo: {combo} (default; set on 2. Spindle EDFs)"


def empty_animals_hint(root: Path, n_animals: int) -> str | None:
    """Explain an empty animals table: animals come from ``standard/``, written by Preprocess."""
    if n_animals:
        return None
    n_raw = len(list(root.glob("*.edf")))
    if n_raw:
        return (
            f"No animals yet. Found {n_raw} EDF file{'s' if n_raw != 1 else ''} in the project "
            "folder; animals appear here after 1. Preprocess has run."
        )
    return (
        "No animals yet, and no EDF files in the project folder. Put the raw EDFs there, "
        "then run 1. Preprocess."
    )


class HomePage(QWidget):
    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)  # page name — see _STEP_PAGE_NAMES

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        # Holds live EDF viewer windows opened from attention cards so they
        # aren't garbage-collected while the user is interacting with them.
        self._open_windows: list[QWidget] = []
        # Snapshot of rows rendered into the summary table. Read by
        # _on_cell_double_clicked so the row index always resolves against
        # what the user actually sees, not a freshly-reloaded manifest.
        self._table_rows: list[ManifestEntry] = []
        self._swd_files: dict[str, Path | None] = {}
        self._swd_review_enabled = False
        self._build_ui()
        self._refresh()

    # ---------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------
    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(6)

        # --- header row ---
        hdr = QHBoxLayout()
        lbl = QLabel("Home")
        lbl.setStyleSheet("font-weight: bold; font-size: 15px;")
        hdr.addWidget(lbl)
        self._combo_lbl = QLabel("")
        self._combo_lbl.setStyleSheet("color: #555; font-size: 11px; padding-left: 12px;")
        hdr.addWidget(self._combo_lbl)
        hdr.addStretch(1)

        self.btn_reveal = QPushButton("Reveal in Finder")
        self.btn_reveal.setToolTip("Open the project folder in the file manager")
        self.btn_reveal.clicked.connect(self._reveal_project)
        hdr.addWidget(self.btn_reveal)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setToolTip("Reload manifest from disk")
        self.btn_refresh.clicked.connect(self._refresh)
        hdr.addWidget(self.btn_refresh)

        self.btn_build = QPushButton("Import new animals")
        self.btn_build.setToolTip(
            "Scan standard/, spindle_edfs/, and spindle_outputs/ to add new "
            "animals not yet in the manifest without changing existing flags"
        )
        self.btn_build.clicked.connect(lambda: self._do_import(show_zero=True))
        hdr.addWidget(self.btn_build)

        root_layout.addLayout(hdr)

        self._import_lbl = QLabel("")
        self._import_lbl.setStyleSheet("color: #3a7d44; font-size: 11px; padding: 1px 0;")
        self._import_lbl.setVisible(False)
        root_layout.addWidget(self._import_lbl)

        # --- next-step banner ---
        self._next_frame = QWidget()
        self._next_frame.setObjectName("nextBanner")
        next_h = QHBoxLayout(self._next_frame)
        next_h.setContentsMargins(10, 6, 10, 6)
        self._next_lbl = QLabel("")
        self._next_lbl.setWordWrap(True)
        next_h.addWidget(self._next_lbl, 1)
        self.btn_next = QPushButton("Open →")
        self.btn_next.setStyleSheet(
            "QPushButton { padding: 3px 12px; font-weight: bold; "
            "color: #1a5fa8; border: 1px solid #1a5fa8; }"
        )
        self._next_page: str | None = None
        self.btn_next.clicked.connect(
            lambda: self._next_page and self.navigate_to.emit(self._next_page)
        )
        next_h.addWidget(self.btn_next)
        root_layout.addWidget(self._next_frame)

        # --- progress strip: one chip per pipeline step ---
        self._strip_container = QWidget()
        self._strip_layout = QHBoxLayout(self._strip_container)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(4)
        root_layout.addWidget(self._strip_container)
        self._build_progress_strip()

        # --- needs attention zone (hidden when nothing needs attention) ---
        self._attn_title = QLabel("Needs Attention")
        self._attn_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        root_layout.addWidget(self._attn_title)

        # Cached height of the rendered attention content. Set by
        # _refresh_attention_zone; read by _update_attn_max_height from
        # both that refresh and resizeEvent.
        self._attn_content_px = 0

        self._attn_container = QWidget()
        self._attn_layout = QVBoxLayout(self._attn_container)
        self._attn_layout.setContentsMargins(0, 2, 0, 4)
        self._attn_layout.setSpacing(3)

        self._attn_scroll = QScrollArea()
        self._attn_scroll.setWidget(self._attn_container)
        self._attn_scroll.setWidgetResizable(True)
        self._attn_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._attn_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        root_layout.addWidget(self._attn_scroll)

        # --- animals table ---
        summary_hdr = QHBoxLayout()

        self._animals_lbl = QLabel("Animals")
        self._animals_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        summary_hdr.addWidget(self._animals_lbl)

        summary_hdr.addStretch(1)

        self.chk_attention_only = QCheckBox("Only animals needing attention")
        self.chk_attention_only.toggled.connect(self._refresh)
        summary_hdr.addWidget(self.chk_attention_only)

        # PSD-run filter — visible only when 2+ runs exist (with 0 or 1 runs,
        # "All runs (best)" and any single run would render identically).
        self._run_filter_lbl = QLabel("PSD run:")
        self._run_filter_lbl.setStyleSheet("color: #555;")
        summary_hdr.addWidget(self._run_filter_lbl)
        self.cmb_run_filter = QComboBox()
        self.cmb_run_filter.setToolTip(
            "Filter the PSD Status column to a specific run. "
            "Default 'All runs (best)' shows the analysis-readiest state across runs."
        )
        self.cmb_run_filter.currentIndexChanged.connect(self._on_run_filter_changed)
        summary_hdr.addWidget(self.cmb_run_filter)
        # Start hidden — visibility is set by _refresh_run_filter.
        self._run_filter_lbl.setVisible(False)
        self.cmb_run_filter.setVisible(False)

        root_layout.addLayout(summary_hdr)

        self._empty_lbl = QLabel("")
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setStyleSheet("color: #8a4400; font-size: 11px; padding: 2px 0;")
        self._empty_lbl.setVisible(False)
        root_layout.addWidget(self._empty_lbl)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        root_layout.addWidget(self.table, 1)

    def _build_progress_strip(self) -> None:
        """One flat chip per ``_STEP_SHORT``; stored for ``_refresh_progress``."""
        self._chips: list[QPushButton] = []
        for i, short in enumerate(_STEP_SHORT):
            chip = QPushButton(short)
            chip.setFlat(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            page_name = _STEP_PAGE_NAMES[i]
            chip.clicked.connect(lambda _, p=page_name: self.navigate_to.emit(p))
            self._strip_layout.addWidget(chip)
            self._chips.append(chip)
        self._strip_layout.addStretch(1)

    def _refresh_progress(self, manifest: Manifest, psd_runs: list[str] | None = None) -> None:
        """Update the next-step banner and the progress-strip chips."""
        statuses = compute_pipeline_status(self.project_root, manifest, psd_runs=psd_runs)
        next_idx: int | None = next(
            (i for i, s in enumerate(statuses) if s.kind in ("active", "attention")),
            None,
        )
        for i, (st, chip, short) in enumerate(zip(statuses, self._chips, _STEP_SHORT, strict=True)):
            chip.setVisible(not (i == _SWD_STEP_IDX and st.kind == "off"))
            color = _GUIDE_ICON_COLOR[st.kind]
            chip.setText(f"{_GUIDE_ICON[st.kind]} {short}")
            chip.setToolTip(f"{_STEP_LABELS[i]}: {st.description}")
            weight = "bold" if i == next_idx else "normal"
            bg = _GUIDE_ROW_HIGHLIGHT if i == next_idx else "transparent"
            chip.setStyleSheet(
                f"QPushButton {{ color: {color}; font-weight: {weight}; background: {bg}; "
                f"border: 1px solid #d0d0d0; border-radius: 10px; padding: 2px 8px; }}"
            )

        if next_idx is None:
            self._next_page = None
            self._next_lbl.setText("<b style='color:#3a7d44'>✓ All pipeline steps complete</b>")
            self._next_frame.setStyleSheet(
                "QWidget#nextBanner { background-color: #e8f4ea; border-radius: 4px; }"
            )
            self.btn_next.setVisible(False)
            return
        st = statuses[next_idx]
        color = _GUIDE_ICON_COLOR[st.kind]
        self._next_page = _STEP_PAGE_NAMES[next_idx]
        self._next_lbl.setText(
            f"<b>Next: {_STEP_LABELS[next_idx]}</b> — "
            f"<span style='color:{color}'>{st.description}</span>"
        )
        self._next_frame.setStyleSheet(
            f"QWidget#nextBanner {{ background-color: {_GUIDE_ROW_HIGHLIGHT}; border-radius: 4px; }}"
        )
        self.btn_next.setText(f"Open {_STEP_SHORT[next_idx]} →")
        self.btn_next.setVisible(True)

    def _reveal_project(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project_root)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_attn_max_height()

    def _update_attn_max_height(self) -> None:
        """Size the attention scroll area to content, capped at 40% of the page."""
        content = self._attn_content_px
        self._attn_title.setVisible(content > 0)
        self._attn_scroll.setVisible(content > 0)
        if content > 0:
            cap = max(120, self.height() * 2 // 5)
            self._attn_scroll.setFixedHeight(min(content + 12, cap))

    # ---------------------------------------------------------------
    # Actions
    # ---------------------------------------------------------------
    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        """Dispatch per-cell double-click actions (edit notes)."""
        # Resolve against the rendered row cache so the index always points
        # to what the user sees, even if the manifest has changed since.
        if row >= len(self._table_rows):
            return
        if col == _COL_NOTES:
            self._edit_notes(self._table_rows[row])

    def _edit_notes(self, entry: ManifestEntry) -> None:
        """Open the notes editor for an animal and persist any change."""
        dlg = NotesDialog(animal_id=entry.animal_id, initial_text=entry.notes, parent=self)
        if not dlg.exec():
            return
        # Fresh load for the mutation — set_notes saves internally.
        manifest = Manifest.load(self.project_root)
        manifest.set_notes(entry.animal_id, dlg.text())
        self._refresh()
        self.manifest_changed.emit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._do_import()

    def _do_import(self, show_zero: bool = False) -> None:
        before = len(Manifest.load(self.project_root))
        after_manifest = Manifest.build_from_standard(self.project_root)
        n_new = len(after_manifest) - before
        self._refresh()
        if n_new > 0:
            self._import_lbl.setText(f"✓ {n_new} new animal{'s' if n_new != 1 else ''} imported")
            self._import_lbl.setVisible(True)
            # Auto-hide so a future navigation doesn't show stale state.
            QTimer.singleShot(3000, lambda: self._import_lbl.setVisible(False))
        elif show_zero:
            self._import_lbl.setText("No new animals found")
            self._import_lbl.setVisible(True)
            QTimer.singleShot(3000, lambda: self._import_lbl.setVisible(False))
        else:
            self._import_lbl.setVisible(False)

    def _poll(self):
        self._refresh()

    def _refresh(self):
        manifest = Manifest.load(self.project_root)

        psd_runs = _psd_params.list_runs(self.project_root)
        self._refresh_run_filter(psd_runs)
        # None → "All runs (best)" (best-wins precedence across runs); a string
        # picks a single run and filters the PSD Status cell to it.
        run_filter: str | None = self.cmb_run_filter.currentData()

        self._swd_review_enabled = manifest.swd_review_enabled
        self._swd_files = {
            e.animal_id: find_swd_file(self.project_root, e.animal_id) for e in manifest
        }
        facts = [
            (entry, *self._row_facts(entry, manifest.combo, psd_runs, run_filter))
            for entry in manifest
        ]
        n_attention = sum(
            1 for e, out_ok, f_ok, st in facts if _needs_attention(e, out_ok, f_ok, st)
        )
        n_excluded = sum(1 for e, *_ in facts if e.sleep_qc == "excluded")
        parts = [f"{len(facts)} animal{'s' if len(facts) != 1 else ''}"]
        if n_attention:
            parts.append(f"{n_attention} need attention")
        if n_excluded:
            parts.append(f"{n_excluded} excluded")
        self._animals_lbl.setText("Animals — " + " · ".join(parts))
        self._combo_lbl.setText(combo_text(self.project_root, manifest.combo))
        hint = empty_animals_hint(self.project_root, len(facts))
        self._empty_lbl.setText(hint or "")
        self._empty_lbl.setVisible(hint is not None)

        if self.chk_attention_only.isChecked():
            facts = [f for f in facts if _needs_attention(*f)]

        # Cache the rendered rows so _on_cell_double_clicked resolves row
        # indices against exactly what the user sees, not a stale fresh-load.
        self._table_rows = [f[0] for f in facts]
        self.table.setRowCount(len(facts))
        for row_idx, (entry, spindle_out_ok, psd_file_ok, psd_status) in enumerate(facts):
            self._build_table_row(
                row_idx,
                entry,
                spindle_out_ok=spindle_out_ok,
                psd_file_ok=psd_file_ok,
                psd_status=psd_status,
            )
        self.table.resizeRowsToContents()
        # The SWD column only matters when SWD files exist or review is on.
        self.table.setColumnHidden(
            _COL_SWD, not (manifest.swd_review_enabled or any(self._swd_files.values()))
        )

        self._refresh_attention_zone(manifest)
        # Reuse psd_runs from above; saves a second scan of project/psd/.
        self._refresh_progress(manifest, psd_runs=psd_runs)

    def _refresh_run_filter(self, psd_runs: list[str]) -> None:
        """Repopulate the PSD-run filter dropdown, preserving the current selection.

        Hidden when fewer than 2 runs exist — "All runs (best)" and a single
        run render identically, so the control would have no effect.
        """
        # Preserve by userData (None for "All runs (best)", run-name otherwise).
        prev = self.cmb_run_filter.currentData()
        self.cmb_run_filter.blockSignals(True)
        self.cmb_run_filter.clear()
        self.cmb_run_filter.addItem("All runs (best)", None)
        for run_name in psd_runs:
            self.cmb_run_filter.addItem(run_name, run_name)
        # Restore selection if still present; otherwise fall back to default.
        if prev is not None and prev in psd_runs:
            idx = self.cmb_run_filter.findData(prev)
            self.cmb_run_filter.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.cmb_run_filter.setCurrentIndex(0)
        self.cmb_run_filter.blockSignals(False)

        show = len(psd_runs) >= 2
        self._run_filter_lbl.setVisible(show)
        self.cmb_run_filter.setVisible(show)

    def _on_run_filter_changed(self) -> None:
        self._refresh()

    def _row_facts(
        self,
        entry: ManifestEntry,
        combo: str,
        psd_runs: list[str],
        run_filter: str | None,
    ) -> tuple[bool, bool, str | None]:
        """Return ``(spindle_out_ok, psd_file_ok, psd_status)`` for one animal.

        With ``run_filter=None`` (the "All runs (best)" default) the PSD file /
        status use best-wins precedence across ``psd_runs``; with a run name
        they reflect that run only, making "this run isn't computed yet" or
        "this run still needs review" visible from Home.
        """
        spindle_out_ok = _any_file_for_animal(
            self.project_root, "spindle_outputs", combo, entry.animal_id
        )
        psd_status_dict = entry.psd_status

        if run_filter is None:
            psd_file_ok = any(psd_path(combo, self.project_root, rn).is_file() for rn in psd_runs)
            # Display the *analysis-readiest* status across PSD runs:
            #   drink_mask_applied > ok > needs_drink_mask
            # The pending-work signal still surfaces via the attention card
            # (Manifest.all_needs_drink_mask) and per-run PSD Review, so the
            # column being "best-wins" doesn't hide outstanding work.
            if any(v == "drink_mask_applied" for v in psd_status_dict.values()):
                psd_status = "drink_mask_applied"
            elif any(v == "ok" for v in psd_status_dict.values()):
                psd_status = "ok"
            elif any(v == "needs_drink_mask" for v in psd_status_dict.values()):
                psd_status = "needs_drink_mask"
            else:
                psd_status = None
        else:
            psd_file_ok = psd_path(combo, self.project_root, run_filter).is_file()
            psd_status = psd_status_dict.get(run_filter)
        return spindle_out_ok, psd_file_ok, psd_status

    def _build_table_row(
        self,
        row_idx: int,
        entry: ManifestEntry,
        *,
        spindle_out_ok: bool,
        psd_file_ok: bool,
        psd_status: str | None,
    ) -> None:
        """Populate one row in the animals table (see ``_row_facts`` for the args)."""
        pre = Path(entry.preprocessed_edf).name if entry.preprocessed_edf else None
        self.table.setItem(row_idx, _COL_ANIMAL, make_cell(entry.animal_id, tooltip=pre))
        self.table.setItem(
            row_idx,
            _COL_SPINDLE_OUT,
            make_cell("✓" if spindle_out_ok else "—", _EXISTS_COLOR if spindle_out_ok else None),
        )
        self.table.setItem(row_idx, _COL_SWD, self._build_swd_cell(entry))
        self.table.setItem(
            row_idx,
            _COL_SLEEP_QC,
            self._build_sleep_qc_cell(entry.sleep_qc, spindle_out_ok, entry.notes),
        )
        self.table.setItem(
            row_idx, _COL_PSD_STATUS, self._build_psd_status_cell(entry, psd_status, psd_file_ok)
        )
        self.table.setItem(
            row_idx,
            _COL_NOTES,
            make_cell("📝" if entry.notes.strip() else "—", tooltip=entry.notes or None),
        )

    def _build_swd_cell(self, entry: ManifestEntry):
        """SWD column: file found (with review progress when review is on) or missing.

        Missing is amber because PSD compute with SWD masking, and SWD review, both
        need a file for every animal; a waived animal is confirmed as having none.
        """
        if self._swd_files.get(entry.animal_id) is None:
            if entry.swd_waived:
                return make_cell("none (waived)")
            return make_cell("missing", _SWD_MISSING_COLOR)
        if not self._swd_review_enabled:
            return make_cell("✓", _EXISTS_COLOR)
        status = swd_review_status(entry)
        return make_cell(_SWD_REVIEW_LABEL[status], _EXISTS_COLOR if status == "done" else None)

    def _build_sleep_qc_cell(self, sleep_qc: str | None, spindle_out_ok: bool, notes: str = ""):
        """Build the QC Status column cell (pending / needs_review / ok / excluded).

        An excluded cell's tooltip is the animal's notes, which hold the reason.
        """
        if sleep_qc is None:
            txt = "pending" if spindle_out_ok else "—"
            bg = _PENDING_COLOR if spindle_out_ok else None
        else:
            txt = _SLEEP_QC_LABEL.get(sleep_qc, sleep_qc)
            bg = _STATUS_COLOR.get(sleep_qc)
            if sleep_qc == "excluded":
                return make_cell(txt, bg, tooltip=notes or None)
        return make_cell(txt, bg)

    def _build_psd_status_cell(
        self,
        entry: ManifestEntry,
        psd_status: str | None,
        psd_file_ok: bool,
    ):
        """Build the PSD Status column cell. See ``_build_table_row`` for
        the best-wins precedence used to collapse the per-run status dict
        down to a single display value."""
        has_drink_mask = (
            psd_status == "needs_drink_mask"
            and (self.project_root / drink_mask_rel(entry.animal_id)).is_file()
        )
        if entry.sleep_qc == "excluded":
            txt, bg = "—", None  # excluded animals are never PSD-reviewed
        elif psd_status == "drink_mask_applied":
            txt, bg = psd_status_label(psd_status), _STATUS_COLOR["drink_mask_applied"]
        elif psd_status == "needs_drink_mask":
            label = psd_status_label(psd_status)
            txt = f"{label} (file ready)" if has_drink_mask else label
            bg = _STATUS_COLOR["needs_drink_mask"]
        elif psd_status == "ok":
            txt, bg = psd_status_label(psd_status), _EXISTS_COLOR
        elif psd_file_ok:
            txt, bg = psd_status_label(None), _PENDING_COLOR
        else:
            txt, bg = "—", None
        return make_cell(txt, bg)

    # ---------------------------------------------------------------
    # Needs Attention zone
    # ---------------------------------------------------------------
    def _refresh_attention_zone(self, manifest: Manifest) -> None:
        while self._attn_layout.count():
            item = self._attn_layout.takeAt(0)
            w = item.widget()
            if w:
                # deleteLater frees the underlying C++ object once Qt has
                # processed pending events; setParent(None) only orphans.
                w.deleteLater()

        reviewing = manifest.needs_review()
        drink_mask = manifest.all_needs_drink_mask()

        self._attn_content_px = 0
        for title, entries, make_card in (
            ("Review EDF", reviewing, self._make_review_card),
            ("Drink mask needed", drink_mask, self._make_drink_mask_card),
        ):
            if not entries:
                continue
            header = QLabel(f"{title} ({len(entries)})")
            header.setStyleSheet("color: #555; font-weight: bold; padding-top: 2px;")
            self._attn_layout.addWidget(header)
            for entry in entries:
                self._attn_layout.addWidget(make_card(entry))
            self._attn_content_px += _ATTN_HEADER_STRIDE_PX + _ATTN_CARD_STRIDE_PX * len(entries)
        self._update_attn_max_height()

    def _make_card_frame(self, bg_color: str) -> "tuple[QWidget, QHBoxLayout]":
        """Create an attention card frame. Returns (widget, layout)."""
        row_w = QWidget()
        row_w.setObjectName("attnRow")
        row_w.setMaximumHeight(_ATTN_CARD_HEIGHT_PX)
        row_w.setStyleSheet(
            f"QWidget#attnRow {{ background-color: {bg_color}; border-radius: 3px; }}"
        )
        h = QHBoxLayout(row_w)
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(8)
        return row_w, h

    def _make_review_card(self, entry: ManifestEntry) -> QWidget:
        row_w, h = self._make_card_frame("#fff3cd")
        h.addWidget(QLabel(f"<b>{entry.animal_id}</b>"))
        lbl_type = QLabel("Review EDF")
        lbl_type.setStyleSheet("color: #7a6000; font-style: italic;")
        h.addWidget(lbl_type)
        reasons = [METRIC_BY_KEY[k] for k in entry.flag_reasons if k in METRIC_BY_KEY]
        if reasons:
            lbl_why = QLabel("Flagged: " + ", ".join(m.short for m in reasons))
            lbl_why.setStyleSheet("color: #b02a2a; font-weight: bold;")
            lbl_why.setToolTip("\n".join(m.label for m in reasons))
            h.addWidget(lbl_why)
        h.addStretch(1)

        btn_open = QPushButton("Open EDF")
        btn_open.setToolTip("View Standard EDF")
        btn_open.setFixedHeight(24)
        btn_open.clicked.connect(lambda _, e=entry: self._open_edf_for_animal(e))
        h.addWidget(btn_open)

        btn_ok = QPushButton("✓ OK")
        btn_ok.setToolTip("Sleep scoring is fine")
        btn_ok.setFixedHeight(24)
        btn_ok.clicked.connect(lambda _, mid=entry.animal_id: self._queue_flag_ok(mid))
        h.addWidget(btn_ok)

        return row_w

    def _make_drink_mask_card(self, entry: ManifestEntry) -> QWidget:
        """Build a one-line attention card linking to the Drink Mask page."""
        accent = "#5a1d6b"
        row_w, h = self._make_card_frame("#f0e6ff")
        h.addWidget(QLabel(f"<b>{entry.animal_id}</b>"))
        lbl_type = QLabel("Drink mask needed")
        lbl_type.setStyleSheet(f"color: {accent}; font-style: italic;")
        h.addWidget(lbl_type)
        h.addStretch(1)
        btn_hint = QPushButton("→ Drink Mask page")
        btn_hint.setStyleSheet(
            f"color: {accent}; border: none; padding: 0; text-decoration: underline;"
        )
        btn_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_hint.setFlat(True)
        btn_hint.clicked.connect(lambda: self.navigate_to.emit("drink_mask"))
        h.addWidget(btn_hint)
        return row_w

    def _queue_flag_ok(self, animal_id: str) -> None:
        # flag_sleep_qc saves the manifest internally; binding the manifest
        # to a name makes the persistence boundary visible to readers.
        manifest = Manifest.load(self.project_root)
        manifest.flag_sleep_qc(animal_id, "ok")
        self._refresh()
        self.manifest_changed.emit()

    def _open_edf_for_animal(self, entry: ManifestEntry) -> None:
        if not entry.preprocessed_edf:
            QMessageBox.warning(self, "No EDF", f"No preprocessed EDF set for {entry.animal_id}.")
            return
        edf_path = self.project_root / entry.preprocessed_edf
        if not edf_path.is_file():
            QMessageBox.warning(self, "File not found", f"EDF not found:\n{edf_path}")
            return

        manifest = Manifest.load(self.project_root)
        csv_path = self._find_spindle_csv(entry.animal_id, manifest.combo)

        try:
            win = launch_edf_window(
                edf_path=edf_path,
                csv_path=csv_path,
                manifest=manifest,
                animal_id=entry.animal_id,
                initial_dir=str(self.project_root),
            )
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Error opening EDF", f"{type(e).__name__}: {e}")
            return
        win.resize(1200, 800)
        win.show()
        # Prune from _open_windows when the user closes the viewer; otherwise
        # the recording arrays stay pinned in memory for the page's lifetime.
        win.destroyed.connect(lambda _, w=win: self._on_window_closed(w))
        self._open_windows.append(win)

    def _on_window_closed(self, win: QWidget) -> None:
        with contextlib.suppress(ValueError):
            self._open_windows.remove(win)

    def _find_spindle_csv(self, animal_id: str, channels: str) -> Path | None:
        """Return the first ``*labels.csv`` for this animal in the combo's folder, or None.

        Returns None on missing directory / unreadable filesystem rather than
        propagating — the EDF viewer renders fine with ``csv_path=None``.
        """
        try:
            d = spindle_output_dir(channels, self.project_root)
            hits = sorted(d.glob(f"{animal_id}*labels.csv"))
        except OSError:
            return None
        return hits[0] if hits else None
