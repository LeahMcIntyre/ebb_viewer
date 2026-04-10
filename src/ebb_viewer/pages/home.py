from pathlib import Path
from typing import NamedTuple, Literal

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QWidget,
    QPushButton, QTableWidget, QHeaderView, QSizePolicy,
    QComboBox, QInputDialog, QMessageBox, QScrollArea,
)

from ebb_viewer.widgets.tree_view import ProjectTree
from ebb_viewer.widgets.table_helpers import make_cell
from ebb_viewer.pipeline.manifest import (
    Manifest, ManifestEntry, RunEntry,
    psd_path, spindle_output_dir, final_psd_path, merged_psd_path,
)
from ebb_viewer.pipeline.manifest import spindle_edf_dir
from ebb_viewer.pipeline.naming import CHANNEL_COMBOS, drink_mask_rel
from ebb_viewer.pipeline.theme import COMBO_BADGE_HEX, STATUS_COLOR_HEX


# Pipeline stage columns
_COLUMNS = [
    "Animal", "Runs", "Preprocessed", "Channels",
    "Spindle EDF", "Spindle Output",
    "Sleep QC", "PSD File", "PSD Status",
]

_MULTIRUN_COLOR = QColor("#dce8f7")   # light blue = animal has multiple runs

_STATUS_COLOR = {k: QColor(v) for k, v in STATUS_COLOR_HEX.items()}
_RERUN_DONE_COLOR = QColor("#c8c8c8")   # gray = rerun resolved
_PENDING_COLOR    = QColor("#f0f0f0")   # light gray = reached but not yet flagged
_EXISTS_COLOR     = QColor("#d4edda")   # green

# Combo badge colours for the Channels column
_COMBO_BG: dict[str, QColor] = {k: QColor(v) for k, v in COMBO_BADGE_HEX.items()}
_COMBO_FG = QColor("#ffffff")

_SLEEP_QC_LABEL: dict[str, str] = {
    "needs_review": "Review EDF",
    "needs_rerun":  "Rerun Queued",
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
    "9. Finalize",
]

_STEP_PAGE_NAMES = [
    "preprocess", "spindle_write", "spindle_upload",
    "sleep_qc", "rerun", "psd_compute", "psd_review",
    "drink_mask", "finalize",
]

_GUIDE_ICON       = {"done": "✓", "attention": "⚠", "active": "→", "blocked": "○"}
_GUIDE_ICON_COLOR = {
    "done":      "#3a7d44",
    "attention": "#b06000",
    "active":    "#1a5fa8",
    "blocked":   "#999999",
}
_GUIDE_ROW_HIGHLIGHT = "#eef4fc"

#TODO: Should this be centrilized somewhere else?
def compute_pipeline_status(project_root: Path, manifest: Manifest) -> list[StepStatus]:
    root = Path(project_root)

    # --- filesystem facts ---
    # Step 1 done: standard dir exists and has at least 1 edf
    standard_dir = root / "standard"
    standard_edfs = list(standard_dir.glob("*.edf")) if standard_dir.is_dir() else []
    step1_done = bool(standard_edfs)

    # Step 2 done: spindle edfs dir exist and contains at least 1 dir with at least 1 edf
    spindle_edfs_dir = root / "spindle_edfs"
    step2_done = spindle_edfs_dir.is_dir() and any(
        True for sd in spindle_edfs_dir.iterdir()
        if sd.is_dir() and any(sd.glob("*.edf"))
    )

    # Step 3 done: spindle outputs dir exists and contains at least 1 dir with at least 1 csv 
    spindle_outputs_dir = root / "spindle_outputs"
    step3_done = spindle_outputs_dir.is_dir() and any(
        True for sd in spindle_outputs_dir.iterdir()
        if sd.is_dir() and any(sd.glob("*.csv"))
    )

    # --- manifest facts ---
    n_review      = len(manifest.needs_review())
    n_pending_qc  = len(manifest.pending_sleep_qc())
    n_ok          = sum(1 for e in manifest if any(r.sleep_qc == "ok" for r in e.runs.values()))
    n_rerun       = len(manifest.needs_rerun())
    n_animals     = sum(1 for _ in manifest)
    n_ready_psd   = len(manifest.ready_for_psd())
    n_rerun_pend  = len(manifest.needs_rerun_pending())
    n_rerun_ready = len(manifest.pending_rerun_review())
    n_psd_pending = len(manifest.pending_psd_review())

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
    # Special case: manifest was regenerated from files after a completed run.
    # psds_final.pkl exists (project done) but sleep_qc is all None (manifest lost).
    # Suppress the false-alarm attention state — the project is already finished.
    if final_psd_path(root).exists() and n_ok == 0 and n_pending_qc > 0:
        s4 = StepStatus("done", "PSDs finalized — sleep QC history not available")
    elif step3_done and n_pending_qc == 0 and n_review == 0 and n_ok > 0:
        s4 = StepStatus("done", f"{n_ok} animal{'s' if n_ok != 1 else ''} marked ok")
    elif step3_done and (n_review > 0 or n_pending_qc > 0):
        parts = []
        if n_review:     parts.append(f"{n_review} flagged for EDF review")
        if n_pending_qc: parts.append(f"{n_pending_qc} not yet assessed")
        s4 = StepStatus("attention", ", ".join(parts))
    elif step3_done:
        s4 = StepStatus("active", "Ready — review sleep QC for each animal")
    else:
        s4 = StepStatus("blocked", "Requires step 3")

    # --- Step 5: Spindle Rerun ---
    # TODO: Do I want the ready to review to be in this part?
    qc_complete = step3_done and n_pending_qc == 0 and n_ok > 0
    if n_rerun_pend > 0 or n_rerun_ready > 0:
        parts = []
        if n_rerun_pend:  parts.append(f"{n_rerun_pend} upload pending")
        if n_rerun_ready: parts.append(f"{n_rerun_ready} ready to review")
        s5 = StepStatus("attention", ", ".join(parts))
    elif n_rerun > 0 and n_rerun_pend == 0 and n_rerun_ready == 0:
        s5 = StepStatus("done", f"{n_rerun} rerun{'s' if n_rerun != 1 else ''} accepted")
    elif qc_complete and n_review == 0:
        s5 = StepStatus("done", "No reruns needed")
    else:
        s5 = StepStatus("blocked", "Requires step 4 completion")

    # --- Step 6: PSD Computation ---
    
    #TODO: Rework how this is computed, I do not think this is clear what it means
    psd_dir = root / "psd"
    combos_with_csv: set[str] = set()
    if spindle_outputs_dir.is_dir():
        combos_with_csv = {
            sd.name for sd in spindle_outputs_dir.iterdir()
            if sd.is_dir() and any(sd.glob("*.csv"))
        }
    combos_with_pkl: set[str] = set()
    if psd_dir.is_dir():
        combos_with_pkl = {
            p.stem[len("psds_"):] for p in psd_dir.glob("psds_*.pkl")
            if p.stem not in {"psds_channel_merged", "psds_channel_merged_drink", "psds_final"}
        }
    missing_pkls = combos_with_csv - combos_with_pkl
    merged_pkl = merged_psd_path(root)
    final_pkl = final_psd_path(root)

    all_ready_for_psd = n_animals > 0 and n_ready_psd == n_animals

    if merged_pkl.exists() and not missing_pkls:
        s6 = StepStatus("done", "All PSDs computed, channel merged PKL ready")
    elif combos_with_pkl and (missing_pkls or not merged_pkl.exists()):
        msg = f"{len(missing_pkls)} combo PKL(s) missing" if missing_pkls else "Run Build Channel Merged PKL"
        s6 = StepStatus("attention", msg)
    elif all_ready_for_psd:
        s6 = StepStatus("active", f"Ready — {n_animals} animal{'s' if n_animals != 1 else ''} each have exactly 1 ok run")
    elif n_ok > 0:
        n_not_ready = n_animals - n_ready_psd
        s6 = StepStatus("blocked", f"{n_not_ready} animal{'s' if n_not_ready != 1 else ''} not yet ready")
    else:
        s6 = StepStatus("blocked", "Requires all animals to have exactly 1 ok run (step 4)")

    # --- Step 7: PSD Review ---
    n_needs_drink = len(manifest.needs_drink_mask())
    any_psd_reviewed = any(
        r.psd_status is not None
        for e in manifest for r in e.runs.values()
        if r.sleep_qc == "ok"
    )
    if n_psd_pending > 0:
        s7 = StepStatus("attention", f"{n_psd_pending} PSD{'s' if n_psd_pending != 1 else ''} to review")
    elif n_needs_drink > 0 and merged_pkl.exists():
        s7 = StepStatus("attention", f"{n_needs_drink} animal{'s' if n_needs_drink != 1 else ''} need drink mask")
    elif final_pkl.exists():
        s7 = StepStatus("done", "All PSDs reviewed and finalized")
    elif merged_pkl.exists() and n_psd_pending == 0 and any_psd_reviewed:
        s7 = StepStatus("attention", "All reviewed — click Finalize to seal")
    elif merged_pkl.exists():
        s7 = StepStatus("active", "Ready — open PSD Review page")
    else:
        s7 = StepStatus("blocked", "Requires channel merged PKL (step 6)")

    # --- Step 8: Drink Mask ---
    # n_needs_drink already computed above
    n_drink_applied = sum(
        1 for e in manifest for r in e.runs.values()
        if r.psd_status == "drink_mask_applied"
    )
    if not merged_pkl.exists():
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

    # --- Step 9: Finalize ---
    if final_pkl.exists():
        s9 = StepStatus("done", "psds_final.pkl written")
    elif merged_pkl.exists() and n_psd_pending == 0 and n_needs_drink == 0:
        s9 = StepStatus("attention", "Ready — click Finalize to seal psds_final.pkl")
    else:
        s9 = StepStatus("blocked", "Requires all PSDs reviewed (steps 7–8)")

    return [s1, s2, s3, s4, s5, s6, s7, s8, s9]


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
        self._open_windows: list = []
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
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)           # Preprocessed EDF
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
        """Build 7 step rows and store (icon_lbl, name_lbl, desc_lbl, btn) refs."""
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
        self.btn_guide_toggle.setText(
            "▼  Pipeline Steps" if checked else "►  Pipeline Steps"
        )
        self._guide_container.setVisible(checked)

    def _refresh_pipeline_guide(self, manifest: Manifest) -> None:
        statuses = compute_pipeline_status(self.project_root, manifest)
        next_idx: int | None = next(
            (i for i, s in enumerate(statuses) if s.kind in ("active", "attention")),
            None,
        )
        for i, (st, (icon_lbl, name_lbl, desc_lbl, btn)) in enumerate(
            zip(statuses, self._guide_row_refs)
        ):
            color = _GUIDE_ICON_COLOR[st.kind]
            icon_lbl.setText(_GUIDE_ICON[st.kind])
            icon_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
            desc_lbl.setText(st.description)
            desc_lbl.setStyleSheet(f"color: {color};")

            is_next = (i == next_idx)
            name_lbl.setStyleSheet("font-weight: bold;" if is_next else "")
            row_w = icon_lbl.parent()
            row_w.setStyleSheet(
                f"background-color: {_GUIDE_ROW_HIGHLIGHT}; border-radius: 3px;"
                if is_next else ""
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
            content_h = 48 * n + 12  # ~48 px per card + layout overhead
            cap = max(160, self.height() // 2)
            clamped = min(content_h, cap)
            self._attn_scroll.setMinimumHeight(min(80, clamped))
            self._attn_scroll.setMaximumHeight(clamped)

    def _toggle_table(self, checked: bool) -> None:
        self.btn_table_toggle.setText(
            "▼  Pipeline Summary" if checked else "►  Pipeline Summary"
        )
        self.table.setVisible(checked)

    def _toggle_file_tree(self, checked: bool) -> None:
        self.btn_files_toggle.setText("▼  Project Files" if checked else "►  Project Files")
        self.edf_tree.setVisible(checked)

    # ---------------------------------------------------------------
    # Actions
    # ---------------------------------------------------------------
    # Allows rerun channel combo to be more editable. 
    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        """Allow changing the rerun combo on a needs_rerun row if no EDF written yet."""
        if col != 6:
            return
        manifest = Manifest.load(self.project_root)
        hide_rejected = self.btn_hide_rejected.isChecked()
        rows: list[tuple[ManifestEntry, str, RunEntry]] = []
        for entry in manifest:
            if entry.runs:
                for combo, run in entry.runs.items():
                    if hide_rejected and run.sleep_qc == "rejected":
                        continue
                    rows.append((entry, combo, run))
            else:
                rows.append((entry, "", None))

        if row >= len(rows):
            return
        entry, combo, run = rows[row]
        if run is None or run.sleep_qc != "needs_rerun" or not run.rerun_combo:
            return

        edf_dir = spindle_edf_dir(run.rerun_combo, self.project_root)
        if edf_dir.is_dir() and any(edf_dir.glob(f"{entry.animal_id}*.edf")):
            QMessageBox.information(
                self, "EDF already written",
                f"Spindle EDF for {run.rerun_combo} has already been written and cannot be changed.",
            )
            return

        choices = [c for c in CHANNEL_COMBOS if c != combo]
        new_combo, ok = QInputDialog.getItem(
            self, "Change Rerun Combo",
            f"New rerun combo for {entry.animal_id}:",
            choices,
            choices.index(run.rerun_combo) if run.rerun_combo in choices else 0,
            editable=False,
        )
        if not ok or new_combo == run.rerun_combo:
            return

        manifest.flag_sleep_qc(entry.animal_id, combo, "needs_rerun", rerun_combo=new_combo)
        self._refresh()
        self.manifest_changed.emit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._do_import()

    def _do_import(self, show_zero: bool = False) -> None:
        before = sum(1 for _ in Manifest.load(self.project_root))
        Manifest.build_from_standard(self.project_root)
        after = sum(1 for _ in Manifest.load(self.project_root))
        n_new = after - before
        self._refresh()
        if n_new > 0:
            self._import_lbl.setText(
                f"✓ {n_new} new animal{'s' if n_new != 1 else ''} imported"
            )
            self._import_lbl.setVisible(True)
        elif show_zero:
            self._import_lbl.setText("No new animals found")
            self._import_lbl.setVisible(True)
        else:
            self._import_lbl.setVisible(False)

    def _poll(self):
        self._refresh()

    def _refresh(self):
        manifest = Manifest.load(self.project_root)

        # Build one row per (animal, run) pair
        hide_rejected = self.btn_hide_rejected.isChecked()
        rows: list[tuple[ManifestEntry, str, RunEntry]] = []
        for entry in manifest:
            if entry.runs:
                for combo, run in entry.runs.items():
                    if hide_rejected and run.sleep_qc == "rejected":
                        continue
                    rows.append((entry, combo, run))
            else:
                # Animal exists but no runs yet — show a placeholder row
                rows.append((entry, "", None))

        final_pkl_exists = final_psd_path(self.project_root).exists()
        self.table.setRowCount(len(rows))
        for row_idx, (entry, combo, run) in enumerate(rows):
            spindle_edf_ok  = bool(combo) and _any_file_for_animal(
                self.project_root, "spindle_edfs", combo, entry.animal_id)
            spindle_out_ok  = bool(combo) and _any_file_for_animal(
                self.project_root, "spindle_outputs", combo, entry.animal_id)
            psd_file_ok     = bool(combo) and psd_path(combo, self.project_root).is_file()

            sleep_qc   = run.sleep_qc   if run else None
            psd_status = run.psd_status if run else None

            # 0: Animal
            self.table.setItem(row_idx, 0, make_cell(entry.animal_id))

            # 1: Runs
            n_runs = len(entry.runs)
            self.table.setItem(row_idx, 1, make_cell(
                str(n_runs),
                _MULTIRUN_COLOR if n_runs > 1 else None,
            ))

            # 2: Preprocessed EDF (filename only)
            pre = Path(entry.preprocessed_edf).name if entry.preprocessed_edf else "—"
            self.table.setItem(row_idx, 2, make_cell(pre))

            # 3: Channels
            combo_bg = _COMBO_BG.get(combo)
            self.table.setItem(row_idx, 3, make_cell(
                combo or "—",
                bg=combo_bg,
                fg=_COMBO_FG if combo_bg else None,
            ))

            # 4: Spindle EDF
            self.table.setItem(row_idx, 4, make_cell(
                "✓" if spindle_edf_ok else "—",
                _EXISTS_COLOR if spindle_edf_ok else None,
            ))

            # 5: Spindle Output
            self.table.setItem(row_idx, 5, make_cell(
                "✓" if spindle_out_ok else "—",
                _EXISTS_COLOR if spindle_out_ok else None,
            ))

            # 6: Sleep QC
            edit_hint = False
            if sleep_qc is None:
                # If psds_final.pkl exists the project is complete; manifest was likely
                # regenerated and we have no sleep_qc history — show "—" not "pending".
                if final_pkl_exists:
                    txt = "—"
                    bg  = None
                else:
                    txt = "pending" if spindle_out_ok else "—"
                    bg  = _PENDING_COLOR if spindle_out_ok else None
            elif sleep_qc == "needs_rerun" and run.rerun_combo:
                rerun_run = entry.runs.get(run.rerun_combo)
                if rerun_run and rerun_run.sleep_qc == "ok":
                    txt = "rerun done ✓"
                    bg  = _RERUN_DONE_COLOR
                else:
                    edf_written = _any_file_for_animal(
                        self.project_root, "spindle_edfs", run.rerun_combo, entry.animal_id)
                    txt = f"rerun → {run.rerun_combo}" + ("" if edf_written else "  ✎")
                    bg  = _STATUS_COLOR.get("needs_rerun")
                    edit_hint = not edf_written
            else:
                txt = _SLEEP_QC_LABEL.get(sleep_qc, sleep_qc)
                bg  = _STATUS_COLOR.get(sleep_qc)
            cell_6 = make_cell(txt, bg)
            if edit_hint:
                cell_6.setToolTip("Double-click to change rerun combo")
            self.table.setItem(row_idx, 6, cell_6)

            # 7: PSD File
            self.table.setItem(row_idx, 7, make_cell(
                "✓" if psd_file_ok else "—",
                _EXISTS_COLOR if psd_file_ok else None,
            ))

            # 8: PSD Status
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
            self.table.setItem(row_idx, 8, make_cell(txt, bg))

        self.table.resizeRowsToContents()

        # Shrink table height to content so attention zone / file tree get remaining space
        total_h = self.table.horizontalHeader().height()
        for r in range(self.table.rowCount()):
            total_h += self.table.rowHeight(r)
        self.table.setMaximumHeight(total_h + 4)
        self._refresh_attention_zone(manifest)
        self._refresh_pipeline_guide(manifest)

    # ---------------------------------------------------------------
    # Needs Attention zone
    # ---------------------------------------------------------------
    def _refresh_attention_zone(self, manifest: Manifest) -> None:
        while self._attn_layout.count():
            item = self._attn_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        reviewing       = manifest.needs_review()
        rerunning       = manifest.needs_rerun_pending()
        rerun_ready     = manifest.pending_rerun_review()
        drink_mask      = manifest.needs_drink_mask()

        merged_pkl = merged_psd_path(self.project_root)
        final_pkl  = final_psd_path(self.project_root)
        n_ok = sum(1 for e in manifest if any(r.sleep_qc == "ok" for r in e.runs.values()))
        ready_to_finalize = (
            n_ok > 0
            and merged_pkl.exists()
            and not final_pkl.exists()
            and not manifest.pending_psd_review()
            and not drink_mask
        )

        self._attn_card_count = (
            len(reviewing) + len(rerunning) + len(rerun_ready)
            + len(drink_mask) + (1 if ready_to_finalize else 0)
        )
        self._update_attn_max_height()

        if not reviewing and not rerunning and not rerun_ready and not drink_mask and not ready_to_finalize:
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
        if ready_to_finalize:
            self._attn_layout.addWidget(self._make_finalize_card())

    def _make_card_frame(self, bg_color: str) -> "tuple[QWidget, QHBoxLayout]":
        """Create an attention card frame. Returns (widget, layout)."""
        row_w = QWidget()
        row_w.setObjectName("attnRow")
        row_w.setMaximumHeight(42)
        row_w.setStyleSheet(f"QWidget#attnRow {{ background-color: {bg_color}; border-radius: 3px; }}")
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

        # Build rerun options: exclude current combo and any already-ok combos
        ok_combos = {c for c, r in entry.runs.items() if r.sleep_qc == "ok"}
        rerun_combo = QComboBox()
        rerun_combo.setToolTip("Channel combination to rerun spindle with")
        for c in CHANNEL_COMBOS:
            if c == channels or c in ok_combos:
                continue
            run_for_c = entry.runs.get(c)
            # "ok" already excluded via ok_combos above; only suppress "rejected" and None
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
                lambda _, mid=entry.animal_id, ch=channels, c=rerun_combo:
                    self._queue_flag_rerun(mid, ch, c.currentData())
            )
            h.addWidget(btn_rerun)

        return row_w

    def _make_rerun_pending_card(self, entry: ManifestEntry, channels: str) -> QWidget:
        run = entry.runs.get(channels)
        rerun_combo = run.rerun_combo if run else "?"

        row_w, h = self._make_card_frame("#fde8ce")
        h.addWidget(QLabel(f"<b>{entry.animal_id}</b>"))
        lbl = QLabel(f"[{channels}] → [{rerun_combo}]")
        lbl.setStyleSheet("color: #555;")
        h.addWidget(lbl)
        lbl_type = QLabel("Spindle rerun queued")
        lbl_type.setStyleSheet("color: #7a4400; font-style: italic;")
        h.addWidget(lbl_type)
        h.addStretch(1)
        btn_hint = QPushButton("→ Spindle Rerun page")
        btn_hint.setStyleSheet("color: #7a4400; border: none; padding: 0; text-decoration: underline;")
        btn_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_hint.setFlat(True)
        btn_hint.clicked.connect(lambda: self.navigate_to.emit("rerun"))
        h.addWidget(btn_hint)

        return row_w

    def _make_rerun_ready_card(self, entry: ManifestEntry, channels: str) -> QWidget:
        row_w, h = self._make_card_frame("#d9ecf7")
        h.addWidget(QLabel(f"<b>{entry.animal_id}</b>"))
        lbl = QLabel(f"[{channels}]")
        lbl.setStyleSheet("color: #555;")
        h.addWidget(lbl)
        lbl_type = QLabel("Rerun ready for review")
        lbl_type.setStyleSheet("color: #005a7a; font-style: italic;")
        h.addWidget(lbl_type)
        h.addStretch(1)
        btn_hint = QPushButton("→ Sleep QC page")
        btn_hint.setStyleSheet("color: #005a7a; border: none; padding: 0; text-decoration: underline;")
        btn_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_hint.setFlat(True)
        btn_hint.clicked.connect(lambda: self.navigate_to.emit("sleep_qc"))
        h.addWidget(btn_hint)

        return row_w

    def _make_drink_mask_card(self, entry: ManifestEntry, channels: str) -> QWidget:
        row_w, h = self._make_card_frame("#f0e6ff")
        h.addWidget(QLabel(f"<b>{entry.animal_id}</b>"))
        lbl_ch = QLabel(f"[{channels}]")
        lbl_ch.setStyleSheet("color: #555;")
        h.addWidget(lbl_ch)
        lbl_type = QLabel("Drink mask needed")
        lbl_type.setStyleSheet("color: #5a1d6b; font-style: italic;")
        h.addWidget(lbl_type)
        h.addStretch(1)
        btn_hint = QPushButton("→ Drink Mask page")
        btn_hint.setStyleSheet(
            "color: #5a1d6b; border: none; padding: 0; text-decoration: underline;"
        )
        btn_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_hint.setFlat(True)
        btn_hint.clicked.connect(lambda: self.navigate_to.emit("drink_mask"))
        h.addWidget(btn_hint)
        return row_w

    def _make_finalize_card(self) -> QWidget:
        row_w, h = self._make_card_frame("#d4edda")
        lbl_type = QLabel("All PSDs reviewed — ready to finalize")
        lbl_type.setStyleSheet("color: #155724; font-style: italic;")
        h.addWidget(lbl_type)
        h.addStretch(1)
        btn_hint = QPushButton("→ Finalize")
        btn_hint.setStyleSheet("color: #155724; border: none; padding: 0; text-decoration: underline;")
        btn_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_hint.setFlat(True)
        btn_hint.clicked.connect(lambda: self.navigate_to.emit("finalize"))
        h.addWidget(btn_hint)
        return row_w

    def _queue_flag_ok(self, animal_id: str, channels: str) -> None:
        Manifest.load(self.project_root).flag_sleep_qc(animal_id, channels, "ok")
        self._refresh()
        self.manifest_changed.emit()

    def _queue_flag_rerun(self, animal_id: str, channels: str, rerun_combo: str) -> None:
        Manifest.load(self.project_root).flag_sleep_qc(
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

        from ebb_viewer.edf_viewer.eeg_viewer import launch_edf_window
        try:
            win = launch_edf_window(
                edf_path=edf_path,
                csv_path=csv_path,
                manifest=manifest,
                animal_id=entry.animal_id,
                run_channels=channels,
                initial_dir=str(self.project_root),
            )
            win.resize(1200, 800)
            win.show()
            self._open_windows.append(win)
        except Exception as e:
            QMessageBox.critical(self, "Error opening EDF", f"{type(e).__name__}: {e}")

    def _find_spindle_csv(self, animal_id: str, channels: str) -> Path | None:
        try:
            d = spindle_output_dir(channels, self.project_root)
            hits = sorted(d.glob(f"{animal_id}*labels.csv"))
            return hits[0] if hits else None
        except Exception:
            return None
