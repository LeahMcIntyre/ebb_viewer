"""Home page — pipeline dashboard, attention zone, and animal/run summary.

Hosts the top-level pipeline-step guide (8 steps fed by
``compute_pipeline_status``), a "Needs Attention" zone surfacing per-animal
work (review-EDF / rerun-pending / rerun-ready / drink-mask), a per-run
summary table, and the project file tree. Manifest mutations triggered from
attention-card buttons persist via ``Manifest.flag_sleep_qc``'s internal
``save()``.
"""

import contextlib
from pathlib import Path
from typing import Literal, NamedTuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ebb_viewer.edf_viewer.eeg_viewer import launch_edf_window
from ebb_viewer.pipeline import psd_params as _psd_params
from ebb_viewer.pipeline.manifest import (
    Manifest,
    ManifestEntry,
    RunEntry,
    merged_psd_path,
    psd_path,
    spindle_edf_dir,
    spindle_output_dir,
)
from ebb_viewer.pipeline.naming import CHANNEL_COMBOS, drink_mask_rel
from ebb_viewer.pipeline.theme import COMBO_BADGE_HEX, STATUS_COLOR_HEX
from ebb_viewer.widgets.notes_dialog import NotesDialog
from ebb_viewer.widgets.table_helpers import make_cell
from ebb_viewer.widgets.tree_view import ProjectTree

# Pipeline stage columns
_COLUMNS = [
    "Animal",
    "Runs",
    "Preprocessed",
    "Channels",
    "Spindle EDF",
    "Spindle Output",
    "Sleep QC",
    "PSD File",
    "PSD Status",
    "Notes",
]
_COL_SLEEP_QC = _COLUMNS.index("Sleep QC")
_COL_NOTES = _COLUMNS.index("Notes")

_MULTIRUN_COLOR = QColor("#dce8f7")  # light blue = animal has multiple runs

_STATUS_COLOR = {k: QColor(v) for k, v in STATUS_COLOR_HEX.items()}
_RERUN_DONE_COLOR = QColor("#c8c8c8")  # gray = rerun resolved
_PENDING_COLOR = QColor("#f0f0f0")  # light gray = reached but not yet flagged
_EXISTS_COLOR = QColor("#d4edda")  # green

# Combo badge colours for the Channels column
_COMBO_BG: dict[str, QColor] = {k: QColor(v) for k, v in COMBO_BADGE_HEX.items()}
_COMBO_FG = QColor("#ffffff")

_SLEEP_QC_LABEL: dict[str, str] = {
    "needs_review": "Review EDF",
    "needs_rerun": "Rerun Queued",
}


# ---------------------------------------------------------------------------
# Pipeline guide
# ---------------------------------------------------------------------------
StepKind = Literal["done", "attention", "active", "blocked"]


class StepStatus(NamedTuple):
    kind: StepKind
    description: str


_STEP_LABELS = [
    "1. Preprocess",
    "2. Spindle EDFs",
    "3. Spindle Upload",
    "4. Sleep QC",
    "5. Spindle Rerun",
    "6. PSD Computation",
    "7. PSD Review",
    "8. Drink Mask",
]

_STEP_PAGE_NAMES = [
    "preprocess",
    "spindle_write",
    "spindle_upload",
    "sleep_qc",
    "rerun",
    "psd_compute",
    "psd_review",
    "drink_mask",
]

_GUIDE_ICON = {"done": "✓", "attention": "⚠", "active": "→", "blocked": "○"}
_GUIDE_ICON_COLOR = {
    "done": "#3a7d44",
    "attention": "#b06000",
    "active": "#1a5fa8",
    "blocked": "#999999",
}
_GUIDE_ROW_HIGHLIGHT = "#eef4fc"

# Attention-zone layout — keep in sync with _make_card_frame.setMaximumHeight
# and _attn_layout.setSpacing.
_ATTN_CARD_HEIGHT_PX = 42
_ATTN_CARD_STRIDE_PX = 48  # card + per-card layout overhead


def compute_pipeline_status(
    project_root: Path,
    manifest: Manifest,
    *,
    psd_runs: list[str] | None = None,
) -> list[StepStatus]:
    """Derive the 8 pipeline-step statuses driving the home-page guide.

    Pure logic (no Qt). Reads ``manifest`` plus filesystem state under
    ``project_root`` (``standard/``, ``spindle_edfs/``, ``spindle_outputs/``,
    ``psd/``). Returns the steps in pipeline order — preprocess → drink mask.

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

    # Step 2 done: spindle edfs dir exist and contains at least 1 dir with at least 1 edf
    spindle_edfs_dir = root / "spindle_edfs"
    step2_done = spindle_edfs_dir.is_dir() and any(
        sd.is_dir() and any(sd.glob("*.edf"))
        for sd in spindle_edfs_dir.iterdir()
    )

    # Step 3 done: spindle outputs dir exists and contains at least 1 dir with at least 1 csv
    spindle_outputs_dir = root / "spindle_outputs"
    step3_done = spindle_outputs_dir.is_dir() and any(
        sd.is_dir() and any(sd.glob("*.csv"))
        for sd in spindle_outputs_dir.iterdir()
    )

    # --- manifest facts ---
    n_review = len(manifest.needs_review())
    n_pending_qc = len(manifest.pending_sleep_qc())
    n_ok = sum(1 for e in manifest if any(r.sleep_qc == "ok" for r in e.runs.values()))
    n_rerun = len(manifest.needs_rerun())
    n_animals = len(manifest)
    n_ready_psd = len(manifest.ready_for_psd())
    n_rerun_pend = len(manifest.needs_rerun_pending())
    n_rerun_ready = len(manifest.pending_rerun_review())
    n_psd_pending = len(manifest.all_pending_psd_review())

    # --- Step 1: Preprocess ---
    if step1_done:
        n = len(standard_edfs)
        s1 = StepStatus("done", f"{n} EDF{'s' if n != 1 else ''} in standard/")
    else:
        s1 = StepStatus("active", "Start here — run preprocessor on raw EDF files")

    # --- Step 2: Spindle EDFs ---
    if step2_done:
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

    # --- Step 4: Sleep QC ---
    if step3_done and n_pending_qc == 0 and n_review == 0 and n_ok > 0:
        s4 = StepStatus("done", f"{n_ok} animal{'s' if n_ok != 1 else ''} marked ok")
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

    # --- Step 5: Spindle Rerun ---
    qc_complete = step3_done and n_pending_qc == 0 and n_ok > 0
    if n_rerun_pend > 0 or n_rerun_ready > 0:
        parts = []
        if n_rerun_pend:
            parts.append(f"{n_rerun_pend} upload pending")
        if n_rerun_ready:
            parts.append(f"{n_rerun_ready} ready to review")
        s5 = StepStatus("attention", ", ".join(parts))
    elif n_rerun > 0 and n_rerun_pend == 0 and n_rerun_ready == 0:
        # "needs_rerun" rows hang around even after the rerun target was
        # decided — verify the target combo's sleep_qc is actually "ok",
        # not "rejected", before claiming the rerun was accepted.
        rerun_resolved_ok = all(
            (target := entry.runs.get(run.rerun_combo)) is not None
            and target.sleep_qc == "ok"
            for entry, combo in manifest.needs_rerun()
            for run in [entry.runs[combo]]
            if run.rerun_combo
        )
        if rerun_resolved_ok:
            s5 = StepStatus("done", f"{n_rerun} rerun{'s' if n_rerun != 1 else ''} accepted")
        else:
            s5 = StepStatus("blocked", "Requires step 4 completion")
    elif qc_complete and n_review == 0:
        s5 = StepStatus("done", "No reruns needed")
    else:
        s5 = StepStatus("blocked", "Requires step 4 completion")

    # --- Step 6: PSD Computation ---
    if psd_runs is None:
        psd_runs = _psd_params.list_runs(root)
    any_merged_pkl = (
        any(merged_psd_path(root, rn).exists() for rn in psd_runs) if psd_runs else False
    )
    all_ready_for_psd = n_animals > 0 and n_ready_psd == n_animals

    if psd_runs and any_merged_pkl:
        n_runs = len(psd_runs)
        s6 = StepStatus(
            "done", f"{n_runs} run{'s' if n_runs != 1 else ''} computed — channel merged PKL ready"
        )
    elif all_ready_for_psd:
        s6 = StepStatus(
            "active",
            f"Ready — {n_animals} animal{'s' if n_animals != 1 else ''} each have exactly 1 ok run",
        )
    elif n_ok > 0:
        n_not_ready = n_animals - n_ready_psd
        s6 = StepStatus(
            "blocked", f"{n_not_ready} animal{'s' if n_not_ready != 1 else ''} not yet ready"
        )
    else:
        s6 = StepStatus("blocked", "Requires all animals to have exactly 1 ok run (step 4)")

    # --- Step 7: PSD Review ---
    n_needs_drink = len(manifest.all_needs_drink_mask())
    if n_psd_pending > 0:
        s7 = StepStatus(
            "attention", f"{n_psd_pending} PSD{'s' if n_psd_pending != 1 else ''} to review"
        )
    elif n_needs_drink > 0 and any_merged_pkl:
        s7 = StepStatus(
            "attention",
            f"{n_needs_drink} animal{'s' if n_needs_drink != 1 else ''} need drink mask",
        )
    elif any_merged_pkl and n_psd_pending == 0:
        s7 = StepStatus("done", "All PSDs reviewed")
    elif any_merged_pkl:
        s7 = StepStatus("active", "Ready — open PSD Review page")
    else:
        s7 = StepStatus("blocked", "Requires channel merged PKL (step 6)")

    # --- Step 8: Drink Mask ---
    # n_needs_drink already computed above
    n_drink_applied = sum(
        1
        for e in manifest
        for r in e.runs.values()
        if "drink_mask_applied" in r.psd_status.values()
    )
    if not any_merged_pkl:
        s8 = StepStatus("blocked", "Requires channel merged PKL (step 6)")
    elif n_needs_drink > 0:
        s8 = StepStatus(
            "attention",
            f"{n_needs_drink} animal{'s' if n_needs_drink != 1 else ''} need drink mask",
        )
    elif n_drink_applied > 0:
        s8 = StepStatus(
            "done",
            f"{n_drink_applied} drink mask{'s' if n_drink_applied != 1 else ''} applied",
        )
    else:
        s8 = StepStatus("done", "No drink masks needed")

    return [s1, s2, s3, s4, s5, s6, s7, s8]


def _any_file_for_animal(root: Path, subdir: str, channels: str, animal_id: str) -> bool:
    """True if any file matching animal_id* exists in root/subdir/channels/."""
    d = root / subdir / channels
    return d.is_dir() and any(d.glob(f"{animal_id}*"))


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
        self._table_rows: list[tuple[ManifestEntry, str, RunEntry | None]] = []
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
        hdr.addStretch(1)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setToolTip("Reload manifest from disk")
        self.btn_refresh.clicked.connect(self._refresh)
        hdr.addWidget(self.btn_refresh)

        self.btn_build = QPushButton("Import new animals")
        self.btn_build.setToolTip(
            "Scan standard/, spindle_edfs/, and spindle_outputs/ to add new "
            "animals and runs not yet in the manifest without changing existing flags"
        )
        self.btn_build.clicked.connect(lambda: self._do_import(show_zero=True))
        hdr.addWidget(self.btn_build)

        root_layout.addLayout(hdr)

        self._import_lbl = QLabel("")
        self._import_lbl.setStyleSheet("color: #3a7d44; font-size: 11px; padding: 1px 0;")
        self._import_lbl.setVisible(False)
        root_layout.addWidget(self._import_lbl)

        # --- pipeline steps guide (collapsible) ---
        self.btn_guide_toggle = QPushButton("▼  Pipeline Steps")
        self.btn_guide_toggle.setCheckable(True)
        self.btn_guide_toggle.setChecked(True)
        self.btn_guide_toggle.setStyleSheet(
            "font-weight: bold; font-size: 13px; text-align: left; border: none; padding: 0;"
        )
        self.btn_guide_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guide_toggle.toggled.connect(self._toggle_guide)
        root_layout.addWidget(self.btn_guide_toggle)

        self._guide_container = QWidget()
        self._guide_vbox = QVBoxLayout(self._guide_container)
        self._guide_vbox.setContentsMargins(4, 2, 4, 4)
        self._guide_vbox.setSpacing(1)
        root_layout.addWidget(self._guide_container)

        # --- needs attention zone ---
        lbl_attn = QLabel("Needs Attention")
        lbl_attn.setStyleSheet("font-weight: bold; font-size: 13px;")
        root_layout.addWidget(lbl_attn)

        # Cached count of currently-rendered attention cards. Set by
        # _refresh_attention_zone; read by _update_attn_max_height from
        # both that refresh and resizeEvent.
        self._attn_card_count = 0

        self._attn_container = QWidget()
        self._attn_layout = QVBoxLayout(self._attn_container)
        self._attn_layout.setContentsMargins(0, 2, 0, 4)
        self._attn_layout.setSpacing(3)

        self._attn_scroll = QScrollArea()
        self._attn_scroll.setWidget(self._attn_container)
        self._attn_scroll.setWidgetResizable(True)
        self._attn_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._attn_scroll.setMinimumHeight(160)
        self._attn_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root_layout.addWidget(self._attn_scroll, 1)

        # --- pipeline summary table (collapsible) ---
        summary_hdr = QHBoxLayout()

        self.btn_table_toggle = QPushButton("▼  Pipeline Summary")
        self.btn_table_toggle.setCheckable(True)
        self.btn_table_toggle.setChecked(True)
        self.btn_table_toggle.setStyleSheet(
            "font-weight: bold; font-size: 13px; text-align: left; border: none; padding: 0;"
        )
        self.btn_table_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_table_toggle.toggled.connect(self._toggle_table)
        summary_hdr.addWidget(self.btn_table_toggle)

        summary_hdr.addStretch(1)

        # PSD-run filter — visible only when 2+ runs exist (with 0 or 1 runs,
        # "All runs (best)" and any single run would render identically).
        self._run_filter_lbl = QLabel("PSD run:")
        self._run_filter_lbl.setStyleSheet("color: #555;")
        summary_hdr.addWidget(self._run_filter_lbl)
        self.cmb_run_filter = QComboBox()
        self.cmb_run_filter.setToolTip(
            "Filter PSD File / PSD Status columns to a specific run. "
            "Default 'All runs (best)' shows the analysis-readiest state across runs."
        )
        self.cmb_run_filter.currentIndexChanged.connect(self._on_run_filter_changed)
        summary_hdr.addWidget(self.cmb_run_filter)
        # Start hidden — visibility is set by _refresh_run_filter.
        self._run_filter_lbl.setVisible(False)
        self.cmb_run_filter.setVisible(False)

        self.btn_hide_rejected = QPushButton("Hide Rejected")
        self.btn_hide_rejected.setCheckable(True)
        self.btn_hide_rejected.setChecked(True)
        self.btn_hide_rejected.setToolTip("Toggle visibility of rejected runs in the table")
        self.btn_hide_rejected.toggled.connect(self._refresh)
        summary_hdr.addWidget(self.btn_hide_rejected)

        root_layout.addLayout(summary_hdr)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Animal
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Runs
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Preprocessed EDF
        for col in range(3, len(_COLUMNS)):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        root_layout.addWidget(self.table)

        # --- file tree ---
        self.btn_files_toggle = QPushButton("▼  Project Files")
        self.btn_files_toggle.setCheckable(True)
        self.btn_files_toggle.setChecked(True)
        self.btn_files_toggle.setStyleSheet(
            "font-weight: bold; font-size: 13px; text-align: left; border: none; padding: 0;"
        )
        self.btn_files_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_files_toggle.toggled.connect(self._toggle_file_tree)
        root_layout.addWidget(self.btn_files_toggle)

        self.edf_tree = ProjectTree()
        self.edf_tree.set_root(root_path=self.project_root)
        root_layout.addWidget(self.edf_tree, stretch=2)

        root_layout.addStretch(1)

        self._build_pipeline_guide()

    def _build_pipeline_guide(self) -> None:
        """Build one step row per ``_STEP_LABELS`` and store the (icon_lbl,
        name_lbl, desc_lbl, btn) refs for ``_refresh_pipeline_guide``."""
        self._guide_row_refs: list[tuple[QLabel, QLabel, QLabel, QPushButton]] = []
        for i, label in enumerate(_STEP_LABELS):
            row_w = QWidget()
            row_h = QHBoxLayout(row_w)
            row_h.setContentsMargins(4, 2, 4, 2)
            row_h.setSpacing(8)

            icon_lbl = QLabel("○")
            icon_lbl.setFixedWidth(14)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row_h.addWidget(icon_lbl)

            name_lbl = QLabel(label)
            name_lbl.setFixedWidth(150)
            row_h.addWidget(name_lbl)

            desc_lbl = QLabel("")
            desc_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row_h.addWidget(desc_lbl)

            btn = QPushButton("Open →")
            btn.setFixedHeight(22)
            page_name = _STEP_PAGE_NAMES[i]
            btn.clicked.connect(lambda _, p=page_name: self.navigate_to.emit(p))
            row_h.addWidget(btn)

            self._guide_vbox.addWidget(row_w)
            self._guide_row_refs.append((icon_lbl, name_lbl, desc_lbl, btn))

    def _toggle_guide(self, checked: bool) -> None:
        self.btn_guide_toggle.setText("▼  Pipeline Steps" if checked else "►  Pipeline Steps")
        self._guide_container.setVisible(checked)

    def _refresh_pipeline_guide(
        self, manifest: Manifest, psd_runs: list[str] | None = None
    ) -> None:
        statuses = compute_pipeline_status(
            self.project_root, manifest, psd_runs=psd_runs
        )
        next_idx: int | None = next(
            (i for i, s in enumerate(statuses) if s.kind in ("active", "attention")),
            None,
        )
        for i, (st, (icon_lbl, name_lbl, desc_lbl, btn)) in enumerate(
            zip(statuses, self._guide_row_refs, strict=True)
        ):
            color = _GUIDE_ICON_COLOR[st.kind]
            icon_lbl.setText(_GUIDE_ICON[st.kind])
            icon_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
            desc_lbl.setText(st.description)
            desc_lbl.setStyleSheet(f"color: {color};")

            is_next = i == next_idx
            name_lbl.setStyleSheet("font-weight: bold;" if is_next else "")
            row_w = icon_lbl.parent()
            row_w.setStyleSheet(
                f"background-color: {_GUIDE_ROW_HIGHLIGHT}; border-radius: 3px;" if is_next else ""
            )
            if st.kind == "blocked":
                btn.setStyleSheet("QPushButton { padding: 2px 8px; color: #aaaaaa; }")
            elif is_next:
                btn.setStyleSheet(
                    "QPushButton { padding: 2px 8px; font-weight: bold; "
                    "color: #1a5fa8; border: 1px solid #1a5fa8; }"
                )
            else:
                btn.setStyleSheet("QPushButton { padding: 2px 8px; }")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_attn_max_height()

    def _update_attn_max_height(self) -> None:
        """Size the attention scroll area to content, capped at half the page."""
        n = self._attn_card_count
        if n == 0:
            self._attn_scroll.setMinimumHeight(0)
            self._attn_scroll.setMaximumHeight(40)
        else:
            content_h = _ATTN_CARD_STRIDE_PX * n + 12
            cap = max(160, self.height() // 2)
            clamped = min(content_h, cap)
            self._attn_scroll.setMinimumHeight(min(80, clamped))
            self._attn_scroll.setMaximumHeight(clamped)

    def _toggle_table(self, checked: bool) -> None:
        self.btn_table_toggle.setText("▼  Pipeline Summary" if checked else "►  Pipeline Summary")
        self.table.setVisible(checked)

    def _toggle_file_tree(self, checked: bool) -> None:
        self.btn_files_toggle.setText("▼  Project Files" if checked else "►  Project Files")
        self.edf_tree.setVisible(checked)

    # ---------------------------------------------------------------
    # Actions
    # ---------------------------------------------------------------
    # Allows rerun channel combo to be more editable.
    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        """Dispatch per-cell double-click actions (edit notes, change rerun combo)."""
        # Resolve against the rendered row cache so the index always points
        # to what the user sees, even if the manifest has changed since.
        if row >= len(self._table_rows):
            return
        entry, combo, run = self._table_rows[row]

        if col == _COL_NOTES:
            self._edit_notes(entry)
            return

        if col != _COL_SLEEP_QC:
            return
        # Allow changing the rerun combo on a needs_rerun row if no EDF written yet.
        if run is None or run.sleep_qc != "needs_rerun" or not run.rerun_combo:
            return

        edf_dir = spindle_edf_dir(run.rerun_combo, self.project_root)
        if edf_dir.is_dir() and any(edf_dir.glob(f"{entry.animal_id}*.edf")):
            QMessageBox.information(
                self,
                "EDF already written",
                f"Spindle EDF for {run.rerun_combo} has already been written and cannot be changed.",
            )
            return

        # Same exclusion rule as _make_review_card's dropdown: hide combos
        # that would violate the one-ok invariant or silently rewire another
        # combo's existing rerun chain (see flag_sleep_qc:612).
        ok_combos = {c for c, r in entry.runs.items() if r.sleep_qc == "ok"}
        queued_combos = {
            c for c, r in entry.runs.items()
            if r.sleep_qc == "needs_rerun" and c != combo
        }
        source_combo = run.source_combo
        choices = [
            c for c in CHANNEL_COMBOS
            if c != combo
            and c != source_combo
            and c not in ok_combos
            and c not in queued_combos
        ]
        if not choices:
            QMessageBox.information(
                self,
                "No clean rerun targets",
                "Every other channel combo for this animal is already ok, "
                "queued for rerun, or this row's source combo.",
            )
            return
        new_combo, ok = QInputDialog.getItem(
            self,
            "Change Rerun Combo",
            f"New rerun combo for {entry.animal_id}:",
            choices,
            choices.index(run.rerun_combo) if run.rerun_combo in choices else 0,
            editable=False,
        )
        if not ok or new_combo == run.rerun_combo:
            return

        # Fresh load for the mutation — flag_sleep_qc saves internally.
        manifest = Manifest.load(self.project_root)
        manifest.flag_sleep_qc(entry.animal_id, combo, "needs_rerun", rerun_combo=new_combo)
        self._refresh()
        self.manifest_changed.emit()

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

        # Build one row per (animal, run) pair
        hide_rejected = self.btn_hide_rejected.isChecked()
        rows: list[tuple[ManifestEntry, str, RunEntry | None]] = []
        for entry in manifest:
            if entry.runs:
                for combo, run in entry.runs.items():
                    if hide_rejected and run.sleep_qc == "rejected":
                        continue
                    rows.append((entry, combo, run))
            else:
                # Animal exists but no runs yet — show a placeholder row
                rows.append((entry, "", None))
        # Cache so _on_cell_double_clicked resolves row indices against the
        # exact rendered list rather than a stale fresh-load.
        self._table_rows = rows

        psd_runs = _psd_params.list_runs(self.project_root)
        self._refresh_run_filter(psd_runs)
        # None → "All runs (best)" (best-wins precedence across runs); a string
        # picks a single run and filters PSD File / PSD Status cells to it.
        run_filter: str | None = self.cmb_run_filter.currentData()

        self.table.setRowCount(len(rows))
        for row_idx, (entry, combo, run) in enumerate(rows):
            self._build_table_row(
                row_idx, entry, combo, run, psd_runs=psd_runs, run_filter=run_filter
            )

        self.table.resizeRowsToContents()

        # Shrink table height to content so attention zone / file tree get remaining space
        total_h = self.table.horizontalHeader().height()
        for r in range(self.table.rowCount()):
            total_h += self.table.rowHeight(r)
        self.table.setMaximumHeight(total_h + 4)
        self._refresh_attention_zone(manifest)
        # Reuse psd_runs from above; saves a second scan of project/psd/.
        self._refresh_pipeline_guide(manifest, psd_runs=psd_runs)

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

    def _build_table_row(
        self,
        row_idx: int,
        entry: ManifestEntry,
        combo: str,
        run: RunEntry | None,
        *,
        psd_runs: list[str],
        run_filter: str | None = None,
    ) -> None:
        """Populate one row in the pipeline summary table.

        Pulled out of ``_refresh`` so the cell-by-cell rendering logic
        is isolated and testable. Mutates ``self.table`` in place at the
        given ``row_idx``.

        Args:
            row_idx: Zero-based row index to fill.
            entry: Animal entry for this row.
            combo: Channel combo string; empty for placeholder rows where
                the animal has no runs yet.
            run: The ``RunEntry`` for ``(entry, combo)``, or ``None`` for
                placeholder rows.
            psd_runs: Pre-fetched list of PSD run names. Passed in so a
                single ``_refresh`` doesn't scan ``project/psd/`` once
                per row.
            run_filter: When ``None`` (the "All runs (best)" default), PSD
                File / PSD Status cells use best-wins precedence across
                ``psd_runs``. When set to a specific run name, both cells
                reflect that run only — making "this run isn't computed
                yet" or "this run still needs review" visible from Home.
        """
        spindle_edf_ok = bool(combo) and _any_file_for_animal(
            self.project_root, "spindle_edfs", combo, entry.animal_id
        )
        spindle_out_ok = bool(combo) and _any_file_for_animal(
            self.project_root, "spindle_outputs", combo, entry.animal_id
        )
        sleep_qc = run.sleep_qc if run else None
        psd_status_dict = run.psd_status if run else {}

        if run_filter is None:
            psd_file_ok = bool(combo) and any(
                psd_path(combo, self.project_root, rn).is_file() for rn in psd_runs
            )
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
            psd_file_ok = bool(combo) and psd_path(
                combo, self.project_root, run_filter
            ).is_file()
            psd_status = psd_status_dict.get(run_filter)

        # 0: Animal
        self.table.setItem(row_idx, 0, make_cell(entry.animal_id))

        # 1: Runs
        n_runs = len(entry.runs)
        self.table.setItem(
            row_idx,
            1,
            make_cell(str(n_runs), _MULTIRUN_COLOR if n_runs > 1 else None),
        )

        # 2: Preprocessed EDF (filename only)
        pre = Path(entry.preprocessed_edf).name if entry.preprocessed_edf else "—"
        self.table.setItem(row_idx, 2, make_cell(pre))

        # 3: Channels
        combo_bg = _COMBO_BG.get(combo)
        self.table.setItem(
            row_idx,
            3,
            make_cell(
                combo or "—",
                bg=combo_bg,
                fg=_COMBO_FG if combo_bg else None,
            ),
        )

        # 4: Spindle EDF
        self.table.setItem(
            row_idx,
            4,
            make_cell(
                "✓" if spindle_edf_ok else "—",
                _EXISTS_COLOR if spindle_edf_ok else None,
            ),
        )

        # 5: Spindle Output
        self.table.setItem(
            row_idx,
            5,
            make_cell(
                "✓" if spindle_out_ok else "—",
                _EXISTS_COLOR if spindle_out_ok else None,
            ),
        )

        # 6: Sleep QC
        self.table.setItem(
            row_idx,
            _COL_SLEEP_QC,
            self._build_sleep_qc_cell(entry, run, sleep_qc, spindle_out_ok, combo),
        )

        # 7: PSD File
        self.table.setItem(
            row_idx,
            7,
            make_cell(
                "✓" if psd_file_ok else "—",
                _EXISTS_COLOR if psd_file_ok else None,
            ),
        )

        # 8: PSD Status
        self.table.setItem(
            row_idx, 8, self._build_psd_status_cell(entry, run, psd_status, psd_file_ok)
        )

        # 9: Notes
        self.table.setItem(
            row_idx,
            _COL_NOTES,
            make_cell("📝" if entry.notes.strip() else "—", tooltip=entry.notes or None),
        )

    def _build_sleep_qc_cell(
        self,
        entry: ManifestEntry,
        run: RunEntry | None,
        sleep_qc: str | None,
        spindle_out_ok: bool,
        combo: str,
    ):
        """Build the Sleep QC column cell (handles rerun → done / pending /
        needs_review / needs_rerun branches with the edit-hint tooltip).

        When the row is ``needs_review`` and a *sibling* combo for the same
        animal is already marked ``ok``, the cell appends an inline
        ``(LFC_RSC ok)`` hint + tooltip so the relationship is visible
        from the summary table. (The manifest clears ``rejected_by`` on
        the rejected → needs_review transition, so the cell has to scan
        siblings rather than reading it directly.)
        """
        edit_hint = False
        tooltip = ""
        if sleep_qc is None:
            txt = "pending" if spindle_out_ok else "—"
            bg = _PENDING_COLOR if spindle_out_ok else None
        elif sleep_qc == "needs_rerun" and run is not None and run.rerun_combo:
            rerun_run = entry.runs.get(run.rerun_combo)
            if rerun_run and rerun_run.sleep_qc == "ok":
                txt = "rerun done ✓"
                bg = _RERUN_DONE_COLOR
            else:
                edf_written = _any_file_for_animal(
                    self.project_root, "spindle_edfs", run.rerun_combo, entry.animal_id
                )
                txt = f"rerun → {run.rerun_combo}" + ("" if edf_written else "  ✎")
                bg = _STATUS_COLOR.get("needs_rerun")
                edit_hint = not edf_written
        else:
            label = _SLEEP_QC_LABEL.get(sleep_qc, sleep_qc)
            bg = _STATUS_COLOR.get(sleep_qc)
            sibling_ok = next(
                (c for c, r in entry.runs.items() if c != combo and r.sleep_qc == "ok"),
                None,
            )
            if sibling_ok and sleep_qc == "needs_review":
                txt = f"{label} ({sibling_ok} ok)"
                tooltip = (
                    f"{entry.animal_id} already has {sibling_ok} marked OK. "
                    "This row is queued for re-examination but does not change "
                    f"that — clicking OK here would swap to {combo} instead."
                )
            else:
                txt = label
        cell = make_cell(txt, bg)
        if edit_hint:
            cell.setToolTip("Double-click to change rerun combo")
        elif tooltip:
            cell.setToolTip(tooltip)
        return cell

    def _build_psd_status_cell(
        self,
        entry: ManifestEntry,
        run: RunEntry | None,
        psd_status: str | None,
        psd_file_ok: bool,
    ):
        """Build the PSD Status column cell. See ``_build_table_row`` for
        the best-wins precedence used to collapse the per-run status dict
        down to a single display value."""
        has_drink_mask = (
            run is not None
            and psd_status == "needs_drink_mask"
            and (self.project_root / drink_mask_rel(entry.animal_id)).is_file()
        )
        if psd_status == "drink_mask_applied":
            txt, bg = "drink mask applied", _STATUS_COLOR["drink_mask_applied"]
        elif psd_status == "needs_drink_mask":
            if has_drink_mask:
                txt, bg = "drink mask ready", _STATUS_COLOR["needs_drink_mask"]
            else:
                txt, bg = "needs drink mask", _STATUS_COLOR["needs_drink_mask"]
        elif psd_status == "ok":
            txt, bg = "ok", _EXISTS_COLOR
        elif psd_file_ok:
            txt, bg = "pending", _PENDING_COLOR
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
        rerunning = manifest.needs_rerun_pending()
        rerun_ready = manifest.pending_rerun_review()
        drink_mask = manifest.all_needs_drink_mask()

        self._attn_card_count = len(reviewing) + len(rerunning) + len(rerun_ready) + len(drink_mask)
        self._update_attn_max_height()

        if not reviewing and not rerunning and not rerun_ready and not drink_mask:
            lbl = QLabel("All caught up ✓")
            lbl.setStyleSheet("color: #5a9a5a; font-weight: bold; padding: 4px;")
            self._attn_layout.addWidget(lbl)
            return

        for entry, channels in reviewing:
            self._attn_layout.addWidget(self._make_review_card(entry, channels))
        for entry, channels in rerunning:
            self._attn_layout.addWidget(self._make_rerun_pending_card(entry, channels))
        for entry, channels in rerun_ready:
            self._attn_layout.addWidget(self._make_rerun_ready_card(entry, channels))
        for entry, channels in drink_mask:
            self._attn_layout.addWidget(self._make_drink_mask_card(entry, channels))

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

    def _make_review_card(self, entry: ManifestEntry, channels: str) -> QWidget:
        row_w, h = self._make_card_frame("#fff3cd")
        h.addWidget(QLabel(f"<b>{entry.animal_id}</b>"))
        lbl_ch = QLabel(f"[{channels}]")
        lbl_ch.setStyleSheet("color: #555;")
        h.addWidget(lbl_ch)
        lbl_type = QLabel("Review EDF")
        lbl_type.setStyleSheet("color: #7a6000; font-style: italic;")
        h.addWidget(lbl_type)
        h.addStretch(1)

        btn_open = QPushButton("Open EDF")
        btn_open.setToolTip("View Standard EDF")
        btn_open.setFixedHeight(24)
        btn_open.clicked.connect(lambda _, e=entry, ch=channels: self._open_edf_for_animal(e, ch))
        h.addWidget(btn_open)

        btn_ok = QPushButton("✓ OK")
        btn_ok.setToolTip("File OK, no spindle rerun necessary")
        btn_ok.setFixedHeight(24)
        btn_ok.clicked.connect(
            lambda _, mid=entry.animal_id, ch=channels: self._queue_flag_ok(mid, ch)
        )
        h.addWidget(btn_ok)

        # Build rerun options. Exclude:
        # - current combo (would be a no-op),
        # - any combo already marked ok,
        # - this run's source_combo (it routed *to* here — circular), and
        # - any combo whose own sleep_qc is needs_rerun (flag_sleep_qc at
        #   manifest.py:612 silently overwrites the existing chain when the
        #   target already exists, so we hide that footgun from the UI).
        current_run = entry.runs.get(channels)
        source_combo = current_run.source_combo if current_run else None
        ok_combos = {c for c, r in entry.runs.items() if r.sleep_qc == "ok"}
        queued_combos = {c for c, r in entry.runs.items() if r.sleep_qc == "needs_rerun"}
        rerun_combo = QComboBox()
        rerun_combo.setToolTip("Channel combination to rerun spindle with")
        for c in CHANNEL_COMBOS:
            if (
                c == channels
                or c == source_combo
                or c in ok_combos
                or c in queued_combos
            ):
                continue
            run_for_c = entry.runs.get(c)
            # "ok" and "needs_rerun" already excluded above. "needs_review" is
            # the only non-clean state that still reaches here, so tag it;
            # "rejected" and None show as the bare combo.
            if run_for_c and run_for_c.sleep_qc not in (None, "rejected"):
                label = f"{c} ({_SLEEP_QC_LABEL.get(run_for_c.sleep_qc, run_for_c.sleep_qc)})"
            else:
                label = c
            rerun_combo.addItem(label, c)  # userData = actual combo string

        if rerun_combo.count() > 0:
            h.addWidget(QLabel("Rerun as:"))
            h.addWidget(rerun_combo)

            btn_rerun = QPushButton("Needs Rerun")
            btn_rerun.setToolTip("Mark file to be rerun with the selected channel combo")
            btn_rerun.setFixedHeight(24)
            btn_rerun.clicked.connect(
                lambda _, mid=entry.animal_id, ch=channels, c=rerun_combo: self._queue_flag_rerun(
                    mid, ch, c.currentData()
                )
            )
            h.addWidget(btn_rerun)
        else:
            no_targets_lbl = QLabel("No clean rerun targets")
            no_targets_lbl.setStyleSheet("color: #888; font-style: italic;")
            no_targets_lbl.setToolTip(
                "Every other channel combo is already ok, queued for rerun, "
                "or this run's source combo."
            )
            h.addWidget(no_targets_lbl)

        return row_w

    def _make_simple_attention_card(
        self,
        entry: ManifestEntry,
        channels_text: str,
        *,
        bg: str,
        accent: str,
        type_label: str,
        nav_dest: str,
        nav_text: str,
    ) -> QWidget:
        """Build a one-line attention card with a navigate-to-page link.

        Used by the rerun-pending, rerun-ready, and drink-mask cards — each
        differs only in colors, labels, and the destination page. The
        review card is structurally distinct (has multiple action buttons)
        and stays as its own builder.
        """
        row_w, h = self._make_card_frame(bg)
        h.addWidget(QLabel(f"<b>{entry.animal_id}</b>"))
        lbl_ch = QLabel(channels_text)
        lbl_ch.setStyleSheet("color: #555;")
        h.addWidget(lbl_ch)
        lbl_type = QLabel(type_label)
        lbl_type.setStyleSheet(f"color: {accent}; font-style: italic;")
        h.addWidget(lbl_type)
        h.addStretch(1)
        btn_hint = QPushButton(nav_text)
        btn_hint.setStyleSheet(
            f"color: {accent}; border: none; padding: 0; text-decoration: underline;"
        )
        btn_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_hint.setFlat(True)
        btn_hint.clicked.connect(lambda: self.navigate_to.emit(nav_dest))
        h.addWidget(btn_hint)
        return row_w

    def _make_rerun_pending_card(self, entry: ManifestEntry, channels: str) -> QWidget:
        run = entry.runs.get(channels)
        rerun_combo = run.rerun_combo if run else "?"
        return self._make_simple_attention_card(
            entry,
            f"[{channels}] → [{rerun_combo}]",
            bg="#fde8ce",
            accent="#7a4400",
            type_label="Spindle rerun queued",
            nav_dest="rerun",
            nav_text="→ Spindle Rerun page",
        )

    def _make_rerun_ready_card(self, entry: ManifestEntry, channels: str) -> QWidget:
        return self._make_simple_attention_card(
            entry,
            f"[{channels}]",
            bg="#d9ecf7",
            accent="#005a7a",
            type_label="Rerun ready for review",
            nav_dest="sleep_qc",
            nav_text="→ Sleep QC page",
        )

    def _make_drink_mask_card(self, entry: ManifestEntry, channels: str) -> QWidget:
        return self._make_simple_attention_card(
            entry,
            f"[{channels}]",
            bg="#f0e6ff",
            accent="#5a1d6b",
            type_label="Drink mask needed",
            nav_dest="drink_mask",
            nav_text="→ Drink Mask page",
        )

    def _queue_flag_ok(self, animal_id: str, channels: str) -> None:
        # flag_sleep_qc saves the manifest internally; binding the manifest
        # to a name makes the persistence boundary visible to readers.
        manifest = Manifest.load(self.project_root)
        manifest.flag_sleep_qc(animal_id, channels, "ok")
        self._refresh()
        self.manifest_changed.emit()

    def _queue_flag_rerun(self, animal_id: str, channels: str, rerun_combo: str) -> None:
        manifest = Manifest.load(self.project_root)
        manifest.flag_sleep_qc(
            animal_id, channels, "needs_rerun", rerun_combo=rerun_combo
        )
        self._refresh()
        self.manifest_changed.emit()

    def _open_edf_for_animal(self, entry: ManifestEntry, channels: str) -> None:
        if not entry.preprocessed_edf:
            QMessageBox.warning(self, "No EDF", f"No preprocessed EDF set for {entry.animal_id}.")
            return
        edf_path = self.project_root / entry.preprocessed_edf
        if not edf_path.is_file():
            QMessageBox.warning(self, "File not found", f"EDF not found:\n{edf_path}")
            return

        csv_path = self._find_spindle_csv(entry.animal_id, channels)
        manifest = Manifest.load(self.project_root)

        try:
            win = launch_edf_window(
                edf_path=edf_path,
                csv_path=csv_path,
                manifest=manifest,
                animal_id=entry.animal_id,
                run_channels=channels,
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
        """Return the first ``*labels.csv`` for this (animal, combo), or None.

        Returns None on missing directory / unreadable filesystem rather than
        propagating — the EDF viewer renders fine with ``csv_path=None``.
        """
        try:
            d = spindle_output_dir(channels, self.project_root)
            hits = sorted(d.glob(f"{animal_id}*labels.csv"))
        except OSError:
            return None
        return hits[0] if hits else None
