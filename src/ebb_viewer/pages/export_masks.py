"""Export Masks page — write per-animal time-stamped interval CSVs.

Wraps :func:`ebb_viewer.pipeline.mask_export.export_run` with a Qt UI:
output-dir picker, params form (with "Load from PSD run" + a "modified —
no longer matches" indicator), animal multi-select, inline status table,
and a worker thread that emits per-animal progress.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ebb_viewer.pipeline import export_params, psd_params
from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.pipeline.mask_export import (
    ExportResult,
    default_pairs,
    export_run,
)
from ebb_viewer.widgets.mask_params_widget import MaskParamsWidget

# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------


class MaskExportWorker(QThread):
    """Runs ``export_run`` off the GUI thread; emits per-animal progress."""

    progress = pyqtSignal(str, str, int, int)  # animal_id, combo, done, total
    finished_with_result = pyqtSignal(object)  # ExportResult

    def __init__(
        self,
        project_root: Path,
        out_dir: Path,
        manifest: Manifest,
        params: dict[str, Any],
        pairs: list[tuple[str, str]],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._project_root = project_root
        self._out_dir = out_dir
        self._manifest = manifest
        self._params = params
        self._pairs = pairs

    def run(self) -> None:
        result = export_run(
            project_root=self._project_root,
            out_dir=self._out_dir,
            manifest=self._manifest,
            params=self._params,
            pairs=self._pairs,
            progress_cb=lambda a, c, d, t: self.progress.emit(a, c, d, t),
        )
        self.finished_with_result.emit(result)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


class ExportMasksPage(QWidget):
    """Sidebar page #10 — write per-animal interval CSVs to ``exports/<name>/``."""

    navigate_to = pyqtSignal(str)

    def __init__(self, project_root: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.project_root = Path(project_root)

        self._loaded_run_name: str | None = None
        self._loaded_snapshot: dict[str, Any] | None = None
        self._worker: MaskExportWorker | None = None
        self._last_out_dir: Path | None = None
        self._row_for_pair: dict[tuple[str, str], int] = {}

        self._build_ui()
        self._refresh_animals()
        self._update_export_button()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("Export Masks")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        subtitle = QLabel(
            "Export state, artifact, and clean-per-state masks as time-stamped "
            "CSVs (start_s, end_s, sample range, label) for use in other tools."
        )
        subtitle.setStyleSheet("color: #555; font-size: 11px;")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        root.addWidget(self._build_output_section())
        root.addWidget(self._build_params_section())
        root.addWidget(self._build_animals_section())
        root.addWidget(self._build_action_section())
        root.addWidget(self._build_status_section())
        root.addStretch(1)

    # ----- Output ------------------------------------------------------

    def _build_output_section(self) -> QGroupBox:
        gb = QGroupBox("Output")
        v = QVBoxLayout(gb)

        row = QHBoxLayout()
        row.addWidget(QLabel(f"{self.project_root}/exports/"))
        self.le_dirname = QLineEdit()
        self.le_dirname.setPlaceholderText("e.g. dark_phase  (alphanumeric, _ -)")
        self.le_dirname.textChanged.connect(self._on_dirname_changed)
        row.addWidget(self.le_dirname, 1)
        v.addLayout(row)

        self.lbl_dir_status = QLabel("")
        self.lbl_dir_status.setStyleSheet("color: #b00; font-size: 11px;")
        v.addWidget(self.lbl_dir_status)
        return gb

    # ----- Params ------------------------------------------------------

    def _build_params_section(self) -> QGroupBox:
        gb = QGroupBox("Params")
        v = QVBoxLayout(gb)

        # Load-from-run row (optional; build manually otherwise).
        row = QHBoxLayout()
        self.btn_load_run = QPushButton("Load from PSD run…")
        self.btn_load_run.clicked.connect(self._on_load_from_run)
        row.addWidget(self.btn_load_run)
        self.btn_load_export = QPushButton("Load from saved export…")
        self.btn_load_export.clicked.connect(self._on_load_from_export_config)
        self.btn_load_export.setToolTip(
            "Load a previously-run export's params. Saved on every successful export."
        )
        row.addWidget(self.btn_load_export)
        self.lbl_loaded = QLabel("(no run loaded — defaults shown)")
        self.lbl_loaded.setStyleSheet("color: #666; font-size: 11px;")
        row.addWidget(self.lbl_loaded, 1)
        v.addLayout(row)

        self.lbl_modified = QLabel("")
        self.lbl_modified.setStyleSheet("color: #b07000; font-size: 11px; font-style: italic;")
        v.addWidget(self.lbl_modified)

        # Full mask + filter editor.
        swd_available = (self.project_root / "swd").is_dir() and any(
            (self.project_root / "swd").glob("*.mat")
        )
        self.mask_widget = MaskParamsWidget(
            project_root=self.project_root,
            swd_available=swd_available,
        )
        self.mask_widget.changed.connect(self._check_modified)
        v.addWidget(self.mask_widget)
        return gb

    # ----- Animals -----------------------------------------------------

    def _build_animals_section(self) -> QGroupBox:
        gb = QGroupBox("Animals")
        v = QVBoxLayout(gb)

        bar = QHBoxLayout()
        self.lbl_animals_count = QLabel("0 of 0 selected")
        self.lbl_animals_count.setStyleSheet("color: #555; font-size: 11px;")
        bar.addWidget(self.lbl_animals_count, 1)
        btn_all = QPushButton("Select all")
        btn_all.clicked.connect(lambda: self._set_all_animals_checked(True))
        bar.addWidget(btn_all)
        btn_none = QPushButton("Select none")
        btn_none.clicked.connect(lambda: self._set_all_animals_checked(False))
        bar.addWidget(btn_none)
        v.addLayout(bar)

        self.list_animals = QListWidget()
        self.list_animals.setMaximumHeight(180)
        self.list_animals.itemChanged.connect(self._on_animal_check_changed)
        v.addWidget(self.list_animals)
        return gb

    # ----- Action ------------------------------------------------------

    def _build_action_section(self) -> QFrame:
        f = QFrame()
        h = QHBoxLayout(f)
        h.setContentsMargins(0, 0, 0, 0)
        self.btn_export = QPushButton("Export")
        self.btn_export.setStyleSheet("QPushButton { padding: 8px 16px; font-weight: 600; }")
        self.btn_export.clicked.connect(self._on_export_clicked)
        h.addWidget(self.btn_export)
        self.lbl_action_hint = QLabel("")
        self.lbl_action_hint.setStyleSheet("color: #b00; font-size: 11px;")
        h.addWidget(self.lbl_action_hint, 1)
        return f

    # ----- Status ------------------------------------------------------

    def _build_status_section(self) -> QGroupBox:
        gb = QGroupBox("Status")
        v = QVBoxLayout(gb)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        v.addWidget(self.progress_bar)

        self.tbl_status = QTableWidget(0, 4)
        self.tbl_status.setHorizontalHeaderLabels(["Animal", "Combo", "Status", "Message"])
        self.tbl_status.horizontalHeader().setStretchLastSection(True)
        self.tbl_status.verticalHeader().setVisible(False)
        self.tbl_status.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_status.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        v.addWidget(self.tbl_status)

        footer = QHBoxLayout()
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet("font-size: 11px; color: #555;")
        footer.addWidget(self.lbl_summary, 1)
        self.btn_open_folder = QPushButton("Open exports folder")
        self.btn_open_folder.clicked.connect(self._on_open_folder)
        self.btn_open_folder.setEnabled(False)
        footer.addWidget(self.btn_open_folder)
        v.addLayout(footer)

        gb.setVisible(False)
        self._status_box = gb
        return gb

    # ------------------------------------------------------------------
    # Animal listing
    # ------------------------------------------------------------------

    def _refresh_animals(self) -> None:
        manifest = Manifest.load(self.project_root)
        pairs = default_pairs(manifest)
        self.list_animals.blockSignals(True)
        self.list_animals.clear()
        for animal_id, combo in pairs:
            item = QListWidgetItem(f"{animal_id}   ({combo})")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, (animal_id, combo))
            self.list_animals.addItem(item)
        self.list_animals.blockSignals(False)
        self._update_animal_count()
        self._update_export_button()

    def _set_all_animals_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.list_animals.blockSignals(True)
        for i in range(self.list_animals.count()):
            self.list_animals.item(i).setCheckState(state)
        self.list_animals.blockSignals(False)
        self._update_animal_count()
        self._update_export_button()

    def _on_animal_check_changed(self, _item: QListWidgetItem) -> None:
        self._update_animal_count()
        self._update_export_button()

    def _selected_pairs(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for i in range(self.list_animals.count()):
            item = self.list_animals.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def _update_animal_count(self) -> None:
        sel = len(self._selected_pairs())
        total = self.list_animals.count()
        self.lbl_animals_count.setText(f"{sel} of {total} selected")

    # ------------------------------------------------------------------
    # Params: load from PSD run + modified detection
    # ------------------------------------------------------------------

    def _on_load_from_run(self) -> None:
        runs = psd_params.list_runs(self.project_root)
        if not runs:
            QMessageBox.information(
                self,
                "No PSD runs",
                "No saved PSD runs found at psd/<name>/. Compute a PSD run "
                "first, or fill in the params manually.",
            )
            return
        run, ok = QInputDialog.getItem(
            self,
            "Load from PSD run",
            "Run:",
            runs,
            0,
            False,
        )
        if not ok or not run:
            return
        params = psd_params.load(self.project_root, run)
        if params is None:
            QMessageBox.warning(self, "Load failed", f"Could not read params for '{run}'.")
            return
        self._apply_loaded_params(params, run)

    def _on_load_from_export_config(self) -> None:
        configs = export_params.list_configs(self.project_root)
        if not configs:
            QMessageBox.information(
                self,
                "No saved export configs",
                "No saved export configs found at exports/<name>/export_params.json. "
                "Configs are saved automatically after a successful export.",
            )
            return
        name, ok = QInputDialog.getItem(
            self,
            "Load from saved export",
            "Config:",
            configs,
            0,
            False,
        )
        if not ok or not name:
            return
        params = export_params.load(self.project_root, name)
        if params is None:
            QMessageBox.warning(self, "Load failed", f"Could not read params for '{name}'.")
            return
        self._apply_loaded_params(params, f"export:{name}")

    def _apply_loaded_params(self, params: dict[str, Any], run_name: str) -> None:
        # The widget's from_params handles missing keys by leaving defaults
        # and emits one `changed` signal at the end (filtered out by snapshot).
        self.mask_widget.blockSignals(True)
        try:
            self.mask_widget.from_params(params)
        finally:
            self.mask_widget.blockSignals(False)

        self._loaded_run_name = run_name
        self._loaded_snapshot = self._snapshot_widget_values()
        self.lbl_loaded.setText(f"Loaded: '{run_name}'")
        self.lbl_loaded.setStyleSheet("color: #1a5c8a; font-size: 11px;")
        self.lbl_modified.setText("")

    def _snapshot_widget_values(self) -> dict[str, Any]:
        """Snapshot the widget's current params for modification detection."""
        return self.mask_widget.to_params()

    def _check_modified(self, *_args) -> None:
        if self._loaded_snapshot is None:
            return
        if self._snapshot_widget_values() != self._loaded_snapshot:
            self.lbl_modified.setText(f"Modified — no longer matches '{self._loaded_run_name}'")
        else:
            self.lbl_modified.setText("")

    # ------------------------------------------------------------------
    # Output dir validation
    # ------------------------------------------------------------------

    def _on_dirname_changed(self, _text: str) -> None:
        self._update_export_button()

    def _validate_dirname(self) -> tuple[bool, str]:
        name = self.le_dirname.text().strip()
        if not name:
            return False, "Pick an output folder name."
        if not psd_params.valid_run_name(name):
            return False, "Name must be alphanumeric, _, or - (max 64 chars)."
        out_dir = self.project_root / "exports" / name
        if out_dir.exists():
            return False, f"exports/{name}/ already exists. Pick a different name."
        return True, ""

    def _out_dir(self) -> Path:
        return self.project_root / "exports" / self.le_dirname.text().strip()

    # ------------------------------------------------------------------
    # Export action
    # ------------------------------------------------------------------

    def _current_params(self) -> dict[str, Any]:
        """Current params, ready to pass to the export pipeline."""
        return self.mask_widget.to_params()

    def _update_export_button(self) -> None:
        ok_dir, msg_dir = self._validate_dirname()
        n_animals = len(self._selected_pairs())
        params_ok = bool(self.mask_widget.to_params().get("states"))

        ok = ok_dir and n_animals > 0 and params_ok
        self.btn_export.setEnabled(ok and self._worker is None)
        self.btn_export.setText(f"Export {n_animals} animal{'s' if n_animals != 1 else ''}")

        if not params_ok:
            self.lbl_action_hint.setText("Pick at least one state.")
        elif n_animals == 0:
            self.lbl_action_hint.setText("Select at least one animal.")
        elif not ok_dir:
            self.lbl_action_hint.setText(msg_dir)
        else:
            self.lbl_action_hint.setText("")

        self.lbl_dir_status.setText("" if ok_dir or not self.le_dirname.text() else msg_dir)

    def _on_export_clicked(self) -> None:
        if self._worker is not None:
            return
        ok_dir, msg = self._validate_dirname()
        if not ok_dir:
            QMessageBox.warning(self, "Cannot export", msg)
            return
        pairs = self._selected_pairs()
        if not pairs:
            return

        out_dir = self._out_dir()
        manifest = Manifest.load(self.project_root)
        params = self._current_params()

        # Persist the params alongside the export output so the run can be
        # reproduced later via "Load from saved export…".
        try:
            export_params.save(self.project_root, self.le_dirname.text().strip(), params)
        except OSError as e:
            # Non-fatal: warn but still run the export.
            self.lbl_action_hint.setText(f"Note: couldn't save export config ({e}).")

        self._populate_status_table(pairs)
        self._status_box.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(pairs))
        self.progress_bar.setValue(0)
        self.btn_open_folder.setEnabled(False)
        self._last_out_dir = out_dir

        self._worker = MaskExportWorker(
            project_root=self.project_root,
            out_dir=out_dir,
            manifest=manifest,
            params=params,
            pairs=pairs,
            parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_with_result.connect(self._on_finished)
        self._worker.finished.connect(self._on_thread_done)
        self._set_inputs_enabled(False)
        self._worker.start()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for w in (
            self.le_dirname,
            self.btn_load_run,
            self.btn_load_export,
            self.list_animals,
            self.mask_widget,
        ):
            w.setEnabled(enabled)
        self.btn_export.setEnabled(enabled and self._worker is None)

    # ----- Status table ------------------------------------------------

    def _populate_status_table(self, pairs: list[tuple[str, str]]) -> None:
        self.tbl_status.setRowCount(0)
        self._row_for_pair = {}
        for i, (animal_id, combo) in enumerate(pairs):
            self.tbl_status.insertRow(i)
            self.tbl_status.setItem(i, 0, QTableWidgetItem(animal_id))
            self.tbl_status.setItem(i, 1, QTableWidgetItem(combo))
            status_item = QTableWidgetItem("⏳ queued")
            status_item.setForeground(QColor("#666"))
            self.tbl_status.setItem(i, 2, status_item)
            self.tbl_status.setItem(i, 3, QTableWidgetItem(""))
            self._row_for_pair[(animal_id, combo)] = i
        self.lbl_summary.setText(f"0 / {len(pairs)} complete")

    def _set_row_status(
        self,
        animal_id: str,
        combo: str,
        status: str,
        color: str,
        message: str = "",
    ) -> None:
        i = self._row_for_pair.get((animal_id, combo))
        if i is None:
            return
        item = self.tbl_status.item(i, 2)
        item.setText(status)
        item.setForeground(QColor(color))
        if message:
            self.tbl_status.item(i, 3).setText(message)

    def _on_progress(self, animal_id: str, combo: str, done: int, total: int) -> None:
        self.progress_bar.setValue(done)
        self.lbl_summary.setText(f"{done} / {total} complete")

    def _on_finished(self, result: ExportResult) -> None:
        for r in result.results:
            if r.status == "ok":
                self._set_row_status(r.animal_id, r.combo, "✓ done", "#1d7c2c")
            else:
                msg = r.message.splitlines()[0] if r.message else "error"
                self._set_row_status(r.animal_id, r.combo, "✗ error", "#b00", msg)
        ok_count = len(result.successes)
        fail_count = len(result.failures)
        total = len(result.results)
        summary = f"{ok_count} / {total} succeeded"
        if fail_count:
            summary += f"  ({fail_count} failed)"
        self.lbl_summary.setText(summary)
        self.btn_open_folder.setEnabled(True)

    def _on_thread_done(self) -> None:
        self._worker = None
        self._set_inputs_enabled(True)
        self._update_export_button()

    # ----- Open folder -------------------------------------------------

    def _on_open_folder(self) -> None:
        target = self._last_out_dir or (self.project_root / "exports")
        if not target.exists():
            QMessageBox.information(self, "Not found", f"{target} doesn't exist.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_animals()

    def _poll(self) -> None:
        # Match the convention used by other pages so the 10 s main-window timer
        # keeps the animal list in sync after manifest changes elsewhere.
        if self._worker is None:
            self._refresh_animals()
