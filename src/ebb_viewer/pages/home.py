from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QComboBox, QInputDialog, QMessageBox, QScrollArea,
)

from ebb_viewer.widgets.tree_view import ProjectTree
from ebb_viewer.pipeline.manifest import (
    Manifest, ManifestEntry, RunEntry,
    psd_path, spindle_output_dir,
)
from ebb_viewer.pipeline.manifest import spindle_edf_dir
from ebb_viewer.pipeline.naming import CHANNEL_COMBOS, drink_mask_rel


# Pipeline stage columns
_COLUMNS = [
    "Animal", "Runs", "Preprocessed", "Channels",
    "Spindle EDF", "Spindle Output",
    "Sleep QC", "PSD File", "PSD Status",
]

_MULTIRUN_COLOR = QColor("#dce8f7")   # light blue = animal has multiple runs

_STATUS_COLOR = {
    "ok":                  QColor("#d4edda"),   # green
    "needs_review":        QColor("#FFF3CD"),   # yellow
    "needs_rerun":         QColor("#E97B7B"),   # red
    "rejected":            QColor("#e0e0e0"),   # gray
    "needs_drink_mask":    QColor("#E97B7B"),   # red
    "drink_mask_applied":  QColor("#d4edda"),   # green
}
_RERUN_DONE_COLOR = QColor("#c8c8c8")           # gray = rerun resolved
_PENDING_COLOR = QColor("#f0f0f0")            # light gray = reached but not yet flagged
_EXISTS_COLOR  = QColor("#d4edda")            # green

# Combo badge colours for the Channels column
_COMBO_BG: dict[str, QColor] = {
    "LFC_RSC": QColor("#5ba3d9"),
    "LFC_LSC": QColor("#ffab5e"),
    "RSC_LSC": QColor("#5ec45e"),
    "LFC":     QColor("#e86e6e"),
    "RSC":     QColor("#b89cd8"),
    "LSC":     QColor("#b3896e"),
}
_COMBO_FG = QColor("#ffffff")


def _cell(text: str, bg: QColor | None = None, fg: QColor | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if bg is not None:
        item.setBackground(bg)
    if fg is not None:
        item.setForeground(fg)
    return item


def _any_file_for_animal(root: Path, subdir: str, channels: str, animal_id: str) -> bool:
    """True if any file matching animal_id* exists in root/subdir/channels/."""
    d = root / subdir / channels
    return d.is_dir() and any(d.glob(f"{animal_id}*"))


class HomePage(QWidget):
    manifest_changed = pyqtSignal()
    navigate_to = pyqtSignal(str)  # page name: "rerun" | "sleep_qc"

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

        self.btn_hide_rejected = QPushButton("Hide Rejected")
        self.btn_hide_rejected.setCheckable(True)
        self.btn_hide_rejected.setChecked(True)
        self.btn_hide_rejected.setToolTip("Toggle visibility of rejected runs in the table")
        self.btn_hide_rejected.toggled.connect(self._refresh)
        hdr.addWidget(self.btn_hide_rejected)

        self.btn_build = QPushButton("Sync from filesystem")
        self.btn_build.setToolTip(
            "Scan standard/, spindle_edfs/, and spindle_outputs/ to add new "
            "animals and runs not yet in the manifest"
        )
        self.btn_build.clicked.connect(self._build_manifest)
        hdr.addWidget(self.btn_build)

        root_layout.addLayout(hdr)

        # --- needs attention zone ---
        lbl_attn = QLabel("Needs Attention")
        lbl_attn.setStyleSheet("font-weight: bold; font-size: 13px;")
        root_layout.addWidget(lbl_attn)

        self._attn_container = QWidget()
        self._attn_layout = QVBoxLayout(self._attn_container)
        self._attn_layout.setContentsMargins(0, 2, 0, 4)
        self._attn_layout.setSpacing(3)

        self._attn_scroll = QScrollArea()
        self._attn_scroll.setWidget(self._attn_container)
        self._attn_scroll.setWidgetResizable(True)
        self._attn_scroll.setMinimumHeight(80)
        self._attn_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root_layout.addWidget(self._attn_scroll, stretch=1)

        # --- pipeline summary table (collapsible) ---
        self.btn_table_toggle = QPushButton("▼  Pipeline Summary")
        self.btn_table_toggle.setCheckable(True)
        self.btn_table_toggle.setChecked(True)
        self.btn_table_toggle.setStyleSheet(
            "font-weight: bold; font-size: 13px; text-align: left; border: none; padding: 0;"
        )
        self.btn_table_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_table_toggle.toggled.connect(self._toggle_table)
        root_layout.addWidget(self.btn_table_toggle)

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

    def _build_manifest(self):
        Manifest.build_from_standard(self.project_root)
        self._refresh()

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
            self.table.setItem(row_idx, 0, _cell(entry.animal_id))

            # 1: Runs
            n_runs = len(entry.runs)
            self.table.setItem(row_idx, 1, _cell(
                str(n_runs),
                _MULTIRUN_COLOR if n_runs > 1 else None,
            ))

            # 2: Preprocessed EDF (filename only)
            pre = Path(entry.preprocessed_edf).name if entry.preprocessed_edf else "—"
            self.table.setItem(row_idx, 2, _cell(pre))

            # 3: Channels
            combo_bg = _COMBO_BG.get(combo)
            self.table.setItem(row_idx, 3, _cell(
                combo or "—",
                bg=combo_bg,
                fg=_COMBO_FG if combo_bg else None,
            ))

            # 4: Spindle EDF
            self.table.setItem(row_idx, 4, _cell(
                "✓" if spindle_edf_ok else "—",
                _EXISTS_COLOR if spindle_edf_ok else None,
            ))

            # 5: Spindle Output
            self.table.setItem(row_idx, 5, _cell(
                "✓" if spindle_out_ok else "—",
                _EXISTS_COLOR if spindle_out_ok else None,
            ))

            # 6: Sleep QC
            if sleep_qc is None:
                txt = "pending" if spindle_out_ok else "—"
                bg  = _PENDING_COLOR if spindle_out_ok else None
            elif sleep_qc == "needs_rerun" and run.rerun_combo:
                rerun_run = entry.runs.get(run.rerun_combo)
                if rerun_run and rerun_run.sleep_qc == "ok":
                    txt = "rerun done ✓"
                    bg  = _RERUN_DONE_COLOR
                else:
                    txt = f"rerun → {run.rerun_combo}"
                    bg  = _STATUS_COLOR.get("needs_rerun")
            else:
                txt = sleep_qc
                bg  = _STATUS_COLOR.get(sleep_qc)
            self.table.setItem(row_idx, 6, _cell(txt, bg))

            # 7: PSD File
            self.table.setItem(row_idx, 7, _cell(
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
            self.table.setItem(row_idx, 8, _cell(txt, bg))

        self.table.resizeRowsToContents()

        # Shrink table height to content so attention zone / file tree get remaining space
        total_h = self.table.horizontalHeader().height()
        for r in range(self.table.rowCount()):
            total_h += self.table.rowHeight(r)
        self.table.setMaximumHeight(total_h + 4)
        self._refresh_attention_zone(manifest)

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

        if not reviewing and not rerunning and not rerun_ready:
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

    def _make_review_card(self, entry: ManifestEntry, channels: str) -> QWidget:
        row_w = QWidget()
        row_w.setObjectName("attnRow")
        row_w.setMaximumHeight(42)
        row_w.setStyleSheet("QWidget#attnRow { background-color: #fff3cd; border-radius: 3px; }")
        h = QHBoxLayout(row_w)
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(8)

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

        rerun_combo = QComboBox()
        rerun_combo.setToolTip("Channel combination to rerun spindle with")
        rerun_combo.addItems(CHANNEL_COMBOS)
        others = [c for c in CHANNEL_COMBOS if c != channels]
        if others:
            rerun_combo.setCurrentText(others[0])
        h.addWidget(QLabel("Rerun as:"))
        h.addWidget(rerun_combo)

        btn_rerun = QPushButton("Needs Rerun")
        btn_rerun.setToolTip("Mark file to be rerun with the selected channel combo")
        btn_rerun.setFixedHeight(24)
        btn_rerun.clicked.connect(
            lambda _, mid=entry.animal_id, ch=channels, c=rerun_combo:
                self._queue_flag_rerun(mid, ch, c.currentText())
        )
        h.addWidget(btn_rerun)

        return row_w

    def _make_rerun_pending_card(self, entry: ManifestEntry, channels: str) -> QWidget:
        run = entry.runs.get(channels)
        rerun_combo = run.rerun_combo if run else "?"

        row_w = QWidget()
        row_w.setObjectName("attnRow")
        row_w.setMaximumHeight(42)
        row_w.setStyleSheet("QWidget#attnRow { background-color: #fde8ce; border-radius: 3px; }")
        h = QHBoxLayout(row_w)
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(8)

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
        row_w = QWidget()
        row_w.setObjectName("attnRow")
        row_w.setMaximumHeight(42)
        row_w.setStyleSheet("QWidget#attnRow { background-color: #d9ecf7; border-radius: 3px; }")
        h = QHBoxLayout(row_w)
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(8)

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
