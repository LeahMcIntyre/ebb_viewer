import unicodedata
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QGroupBox, QMessageBox,
    QListWidget, QPlainTextEdit, QApplication, QInputDialog,
    QLabel, QComboBox, QSizePolicy, QFrame
)

from ebb.io.sleepyrat import SleepyRatAPI
from ebb_viewer.pipeline import sleepyrat_config
from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.widgets.worker_helpers import launch_worker


def _norm_stem(path: "str | Path") -> str:
    """Normalize a file stem for SleepyRat comparison (NFC unicode, spaces→underscores)."""
    return unicodedata.normalize("NFC", Path(path).stem).replace(" ", "_")


class SpindleUploadPage(QWidget):
    """
    Upload spindle EDFs from project_root / 'spindle_edfs' / <combo>
    and download labels into project_root / 'spindle_outputs' / <combo>.

    - User picks a subfolder under spindle_edfs as the upload source.
    - Output folder is fixed to spindle_outputs/<same_name>.
    - Remote folder name defaults to that same combo name (editable).
    """

    navigate_to = pyqtSignal(str)

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._api: Optional[SleepyRatAPI] = None
        self._pending_save: Optional[tuple[str, str, str]] = None  # (combo, project, remote_folder)
        self._projects_fetched = False
        self._known_folders: Optional[set[str]] = None

        self._build_ui()
        self._wire()
        self._refresh_spindle_dirs()
        self._update_run_enabled()

    # ------------- API helper & small helpers -------------
    def _ensure_api(self) -> SleepyRatAPI:
        if self._api is None:
            self._api = SleepyRatAPI()
        return self._api

    def _spindle_root(self) -> Path:
        return self.project_root / "spindle_edfs"

    def _outputs_root(self) -> Path:
        return self.project_root / "spindle_outputs"

    def _current_combo_name(self) -> str:
        idx = self.upload_combo.currentIndex()
        if idx < 0:
            return ""
        return self.upload_combo.itemText(idx).strip()

    def _current_upload_dir(self) -> Optional[Path]:
        path_str = self.upload_dir_edit.text().strip()
        return Path(path_str) if path_str else None

    def _current_output_dir(self) -> Optional[Path]:
        combo = self._current_combo_name()
        if not combo:
            return None
        return self._outputs_root() / combo

    #  UI -------------
    def _build_ui(self):
        root = QVBoxLayout(self)

        lbl = QLabel("Sleep Staging — Upload & Download")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        desc = QLabel(
            "Select a Spindle project and folder to upload EDF files for sleep scoring. Epochs are classified as "
            "Wake, NREM, or REM in 4-second windows. If the remote folder already exists, only new files will be "
            "uploaded; already-processed files will be skipped. Label CSVs are downloaded automatically when ready."
        )

        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")

        root.addWidget(lbl)
        root.addWidget(desc)

        gb = QGroupBox("SleepyRat Upload")
        form_layout = QFormLayout(gb)

        # --- Upload combo (spindle_edfs subfolders) ---
        upload_row = QHBoxLayout()
        self.upload_combo = QComboBox()
        self.upload_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.btn_refresh_upload = QPushButton("Rescan")
        upload_row.addWidget(self.upload_combo, 1)
        upload_row.addWidget(self.btn_refresh_upload)

        self.upload_dir_edit = QLineEdit()
        self.upload_dir_edit.setReadOnly(True)

        form_layout.addRow("Spindle EDF set (subfolder of 'spindle_edfs'):", upload_row)
        form_layout.addRow("Selected upload folder:", self.upload_dir_edit)

        self.upload_hint = QLabel(
            "Looking for subfolders under project_root / 'spindle_edfs'."
        )
        self.upload_hint.setStyleSheet("color:#777; font-size:10px;")
        self.upload_hint.setWordWrap(True)
        form_layout.addRow("", self.upload_hint)

        # --- Auto output folder (read-only) ---
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setReadOnly(True)

        out_hint = QLabel(
            "Outputs will be written to project_root / 'spindle_outputs' / <combo>."
        )
        out_hint.setStyleSheet("color:#777; font-size:10px;")
        out_hint.setWordWrap(True)

        form_layout.addRow("Labels output folder:", self.output_dir_edit)
        form_layout.addRow("", out_hint)

        # --- SleepyRat project list ---
        proj_box = QGroupBox("SleepyRat Project")
        proj_v = QVBoxLayout(proj_box)

        proj_btn_row = QHBoxLayout()
        self.btn_refresh_projects = QPushButton("Refresh")
        self.btn_new_project = QPushButton("New…")
        proj_btn_row.addWidget(self.btn_refresh_projects)
        proj_btn_row.addWidget(self.btn_new_project)
        proj_btn_row.addStretch(1)

        self.project_list = QListWidget()
        self.project_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

        proj_v.addLayout(proj_btn_row)
        proj_v.addWidget(self.project_list)
        form_layout.addRow(proj_box)

        proj_hint = QLabel(
            "Select the SleepyRat project where this run should be stored."
        )
        proj_hint.setStyleSheet("color:#777; font-size:10px;")
        proj_hint.setWordWrap(True)
        form_layout.addRow("", proj_hint)

        # --- SleepyRat remote folder name ---
        self.remote_folder_edit = QComboBox()
        self.remote_folder_edit.setEditable(True)
        form_layout.addRow("Remote folder name:", self.remote_folder_edit)

        folder_desc = QLabel(
            "Inside the selected SleepyRat project, edf files will be grouped "
            "in this folder (e.g. PHP_6w_LFC_RSC)."
        )
        folder_desc.setStyleSheet("color:#777; font-size:10px;")
        folder_desc.setWordWrap(True)
        form_layout.addRow("", folder_desc)

        self.remote_folder_hint = QLabel("")
        self.remote_folder_hint.setStyleSheet("color:#555; font-size:10px;")
        self.remote_folder_hint.setWordWrap(True)
        form_layout.addRow("", self.remote_folder_hint)

        btn_row = QHBoxLayout()
        self.btn_upload_and_download = QPushButton("Process Spindle")

        self.btn_upload_and_download.setEnabled(False)

        btn_row.addWidget(self.btn_upload_and_download)

        form_layout.addRow(btn_row)


        root.addWidget(gb)

        # --- Log area ---
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(500)
        self.log_box.setPlaceholderText("Status messages will appear here...")
        root.addWidget(self.log_box)

        spindle_citation = QLabel(
            "sleepyRat Team. (2026). sleepyRat: Web platform for automated rodent sleep scoring based on EEG/EMG analysis [Software]. https://sleepyrat.ai/"
        )
        spindle_citation.setWordWrap(True)
        spindle_citation.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(spindle_citation)

        # Post-download hint (hidden until a download succeeds)
        self._hint_frame = QFrame()
        self._hint_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._hint_frame.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QHBoxLayout(self._hint_frame)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        hint_lbl = QLabel("✓ Done. Labels downloaded — ready for Sleep QC.")
        hint_layout.addWidget(hint_lbl, 1)
        btn_go_qc = QPushButton("→ Sleep QC")
        btn_go_qc.clicked.connect(lambda: self.navigate_to.emit("sleep_qc"))
        hint_layout.addWidget(btn_go_qc)
        self._hint_frame.setVisible(False)
        root.addWidget(self._hint_frame)

    # ------------- Wiring -------------
    def _wire(self):
        # Spindle EDF selection
        self.btn_refresh_upload.clicked.connect(self._refresh_spindle_dirs)
        self.upload_combo.currentIndexChanged.connect(self._on_upload_combo_changed)

        # SleepyRat project list
        self.btn_refresh_projects.clicked.connect(self._refresh_projects_clicked)
        self.btn_new_project.clicked.connect(self._new_project_clicked)
        self.project_list.currentItemChanged.connect(
            lambda *_: self._on_project_selected()
        )

        # Remote folder text
        self.remote_folder_edit.currentTextChanged.connect(
            lambda _: (self._update_run_enabled(), self._update_folder_hint())
        )

        self.btn_upload_and_download.clicked.connect(self._upload_and_download_clicked)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_spindle_dirs()
        if not self._projects_fetched:
            self._projects_fetched = True
            self._refresh_projects_clicked()
        self._update_run_enabled()

    # ------------- Helpers -------------
    def _log(self, msg: str):
        self.log_box.appendPlainText(msg)
        QApplication.processEvents()

    def _refresh_spindle_dirs(self):
        """
        Look under project_root / 'spindle_edfs' for subfolders.
        Populate the combo box with those folder names.
        If none exist, show a hint that spindle EDFs need to be created.
        """
        root = self._spindle_root()

        self.upload_combo.blockSignals(True)
        self.upload_combo.clear()
        self.upload_dir_edit.clear()
        self.upload_combo.blockSignals(False)

        if not root.exists() or not root.is_dir():
            self.upload_hint.setText(
                f"No 'spindle_edfs' folder found under:\n{root}\n\n"
                "Spindle EDFs need to be created before using this page."
            )
            self.output_dir_edit.clear()
            #self.btn_run.setEnabled(False)
            return

        subdirs = sorted(p for p in root.iterdir() if p.is_dir())

        if not subdirs:
            self.upload_hint.setText(
                f"'spindle_edfs' exists but has no subfolders:\n{root}\n\n"
                "Spindle EDFs need to be created before using this page."
            )
            self.output_dir_edit.clear()
            #self.btn_run.setEnabled(False)
            return

        self.upload_hint.setText(
            f"Found {len(subdirs)} folder(s) under 'spindle_edfs'. "
            "Select one to upload its EDFs."
        )

        self.upload_combo.blockSignals(True)
        for sub in subdirs:
            # display folder name, keep full path as userData
            self.upload_combo.addItem(sub.name, str(sub))
        self.upload_combo.blockSignals(False)

        if self.upload_combo.count() > 0:
            self.upload_combo.setCurrentIndex(0)
            self._on_upload_combo_changed(self.upload_combo.currentIndex())

    def _on_upload_combo_changed(self, index: int):
        """
        When user picks a spindle_edfs subfolder from the combo:
        - update upload_dir_edit
        - update output_dir_edit (spindle_outputs/combo)
        - if remote folder is empty, default it to combo name
        """
        if index < 0:
            self.upload_dir_edit.clear()
            self.output_dir_edit.clear()
        else:
            path_str = self.upload_combo.itemData(index)
            self.upload_dir_edit.setText(path_str or "")

            out_dir = self._current_output_dir()
            self.output_dir_edit.setText(str(out_dir) if out_dir else "")

            combo = self._current_combo_name()
            if combo:
                current = self.remote_folder_edit.currentText().strip()
                auto_prefix = self.project_root.stem + "_"
                if not current or current.startswith(auto_prefix):
                    self.remote_folder_edit.setCurrentText(auto_prefix + combo)

        self._update_run_enabled()

    def _on_project_selected(self):
        self._known_folders = None
        item = self.project_list.currentItem()
        if item is None:
            self._update_folder_hint()
            self._update_run_enabled()
            return
        project = item.text().strip()
        current_text = self.remote_folder_edit.currentText()
        self.remote_folder_edit.blockSignals(True)
        self.remote_folder_edit.clear()
        self.remote_folder_edit.setCurrentText(current_text)
        self.remote_folder_edit.blockSignals(False)
        self._update_folder_hint()
        self._update_run_enabled()
        self._fetch_folders(project)

    def _fetch_folders(self, project: str):
        api = self._ensure_api()
        try:
            names = api.folder_names(project)
        except Exception as e:
            self._log(f"Could not fetch folders for '{project}': {e}")
            return
        self._on_folders_fetched(project, names)

    def _on_folders_fetched(self, project: str, names: list[str]):
        self._known_folders = set(names)
        current_text = self.remote_folder_edit.currentText()
        self.remote_folder_edit.blockSignals(True)
        self.remote_folder_edit.clear()
        for name in sorted(names):
            self.remote_folder_edit.addItem(name)
        self.remote_folder_edit.setCurrentText(current_text)
        self.remote_folder_edit.blockSignals(False)
        self._update_folder_hint()
        self._update_run_enabled()

    def _update_folder_hint(self):
        text = self.remote_folder_edit.currentText().strip()
        if self._known_folders is None or not text:
            self.remote_folder_hint.setText("")
        elif text in self._known_folders:
            self.remote_folder_hint.setText(
                "Existing folder — already-uploaded edf files will be skipped; "
                "missing labels will be downloaded."
            )
        else:
            self.remote_folder_hint.setText("New folder — will be created on upload.")

    def _update_run_enabled(self):
        upload_dir = self._current_upload_dir()
        remote_folder = self.remote_folder_edit.currentText().strip()

        has_upload_dir = upload_dir is not None
        has_remote_folder = bool(remote_folder)

        item = self.project_list.currentItem()
        has_remote_project = item is not None and bool(item.text().strip())

        # Download-only just needs project + remote folder
        can_download_only = has_remote_project and has_remote_folder

        # Upload + download also needs a local upload_dir
        can_upload_and_download = can_download_only and has_upload_dir

        self.btn_upload_and_download.setEnabled(can_upload_and_download)


    # ------------- SleepyRat – project list -------------
    def _refresh_projects_clicked(self):
        api = self._ensure_api()
        self._log("Fetching SleepyRat projects...")
        try:
            names = api.project_names()
        except Exception as e:
            self._log(f"ERROR fetching projects: {e}")
            QMessageBox.critical(self, "SleepyRat Error", str(e))
            return

        self.project_list.blockSignals(True)
        self.project_list.clear()
        for name in names:
            self.project_list.addItem(name)
        self.project_list.blockSignals(False)

        if names and self.project_list.currentRow() < 0:
            self.project_list.setCurrentRow(0)

        self._log(f"Loaded {len(names)} project(s) from SleepyRat.")
        self._update_run_enabled()

    def _new_project_clicked(self):
        api = self._ensure_api()

        name, ok = QInputDialog.getText(
            self,
            "New SleepyRat Project",
            "Project name:",
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        desc, _ = QInputDialog.getText(
            self,
            "Project Description",
            "Description (optional):",
        )
        desc = (desc or "").strip()

        self._log(f"Creating SleepyRat project '{name}'...")
        try:
            api.create_project(name, description=desc)
        except Exception as e:
            self._log(f"ERROR creating project: {e}")
            QMessageBox.critical(self, "SleepyRat Error", str(e))
            return

        # Refresh list and select the new project
        self._refresh_projects_clicked()
        for row in range(self.project_list.count()):
            item = self.project_list.item(row)
            if item and item.text() == name:
                self.project_list.setCurrentRow(row)
                break
        self._log(f"Project '{name}' created and selected.")

    # ------------- Run action -------------
    def _get_common_run_context(self):
        """Return (project, remote_folder, upload_dir, out_dir) or show errors and return None."""
        upload_dir = self._current_upload_dir()
        remote_folder = self.remote_folder_edit.currentText().strip()

        # SleepyRat project
        item = self.project_list.currentItem()
        project = item.text().strip() if item else ""

        if not project:
            QMessageBox.critical(
                self,
                "No SleepyRat Project",
                "Please select a SleepyRat project."
            )
            return None

        if not remote_folder:
            QMessageBox.critical(
                self,
                "No Remote Folder",
                "Please enter a remote folder name."
            )
            return None

        out_dir = self._current_output_dir()
        if out_dir is None:
            QMessageBox.critical(
                self,
                "Output Folder Error",
                "Could not determine output folder (combo name missing)."
            )
            return None

        return project, remote_folder, upload_dir, out_dir


    def _check_output_dir(self, out_dir: Path) -> bool:
        """Return True if safe to proceed (user confirmed or dir is empty)."""
        if out_dir.exists() and any(out_dir.iterdir()):
            btn = QMessageBox.question(
                self, "Output Folder Not Empty",
                f"Output folder is not empty:\n\n{out_dir}\n\n"
                "New CSVs will be mixed with existing files. Continue?",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Cancel,
            )
            return btn == QMessageBox.StandardButton.Ok
        return True

    def _launch_worker(self, project, remote_folder, out_dir, *, upload_dir=None, save_combo: str | None = None):
        self.btn_upload_and_download.setEnabled(False)
        self._pending_save = (save_combo, project, remote_folder) if save_combo else None

        self._sr_thread = QThread(self)
        self._sr_worker = SleepyRatWorker(project, remote_folder, out_dir, upload_dir=upload_dir)
        self._sr_worker.log.connect(self._log)
        launch_worker(self._sr_thread, self._sr_worker,
                      on_finished=self._on_sr_done,
                      on_error=self._on_sr_error)

    def _on_sr_done(self):
        if self._pending_save:
            combo, project, remote_folder = self._pending_save
            sleepyrat_config.save_combo(self.project_root, combo, project, remote_folder)
            self._pending_save = None
        Manifest.build_from_standard(self.project_root)
        self._update_run_enabled()
        self._hint_frame.setVisible(True)

    def _on_sr_error(self, msg: str):
        self._log(f"ERROR: {msg}")
        QMessageBox.critical(self, "SleepyRat Error", msg)
        self._update_run_enabled()

    def _upload_and_download_clicked(self):
        ctx = self._get_common_run_context()
        if ctx is None:
            return
        project, remote_folder, upload_dir, out_dir = ctx

        if upload_dir is None:
            QMessageBox.critical(self, "No Upload Folder", "No spindle EDF folder is selected.")
            return
        edfs = sorted(upload_dir.glob("*.edf"))
        if not edfs:
            QMessageBox.critical(self, "No EDF Files Found",
                                 f"No .edf files were found in:\n{upload_dir}")
            return
        if not self._check_output_dir(out_dir):
            return
        combo = self._current_combo_name()
        self._launch_worker(project, remote_folder, out_dir, upload_dir=upload_dir, save_combo=combo)

    def _download_only_clicked(self):
        ctx = self._get_common_run_context()
        if ctx is None:
            return
        project, remote_folder, _upload_dir, out_dir = ctx
        if not self._check_output_dir(out_dir):
            return
        self._launch_worker(project, remote_folder, out_dir, upload_dir=None)


class SleepyRatWorker(QObject):
    log      = pyqtSignal(str)
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, project, remote_folder, out_dir,
                 upload_dir=None, files=None, parent=None):
        super().__init__(parent)
        self.project       = project
        self.remote_folder = remote_folder
        self.out_dir       = Path(out_dir)
        self.upload_dir    = Path(upload_dir) if upload_dir else None
        self.files         = list(files) if files else None

    @staticmethod
    def _existing_stems(api, project: str, remote_folder: str) -> set[str]:
        """Return the set of already-uploaded submission stems (no extension) from SleepyRat.

        Returns an empty set if the folder doesn't exist yet or the call fails.
        """
        try:
            names = api.get_submission_names(project, remote_folder)
            return {_norm_stem(n.strip()) for n in names}
        except Exception:
            return set()

    def run(self):
        from ebb.io.sleepyrat import SleepyRatAPI
        try:
            api = SleepyRatAPI()

            if self.files is not None:
                # Explicit file list (rerun path) — check remote before uploading anything.
                self.log.emit("Checking for existing edf files on SleepyRat...")
                existing = self._existing_stems(api, self.project, self.remote_folder)

                to_upload = [p for p in self.files if _norm_stem(p) not in existing]
                already_there = len(self.files) - len(to_upload)
                if already_there:
                    self.log.emit(
                        f"Found {already_there} submission(s) already on SleepyRat "
                        f"— downloading instead of re-uploading."
                    )
                for p in to_upload:
                    self.log.emit(f"Uploading {p.name}...")
                    api.upload_edf(self.project, self.remote_folder, p)
                if to_upload:
                    self.log.emit("Upload complete. Waiting for SleepyRat processing...")
                    ok = api.wait_for_processing(self.project, self.remote_folder)
                    if not ok:
                        raise RuntimeError("Processing did not finish within the wait limit.")
                else:
                    self.log.emit("All edf files already on SleepyRat, skipping upload and wait.")

            elif self.upload_dir is not None:
                # Directory batch — glob EDFs, skip already-uploaded by remote check.
                edfs = sorted(self.upload_dir.glob("*.edf"))
                self.log.emit("Checking for existing edf files on SleepyRat...")
                existing = self._existing_stems(api, self.project, self.remote_folder)
                to_upload = [p for p in edfs if _norm_stem(p) not in existing]
                already_there = len(edfs) - len(to_upload)
                if already_there:
                    self.log.emit(f"Skipping {already_there} already-uploaded edf file(s).")
                for p in to_upload:
                    self.log.emit(f"Uploading {p.name}...")
                    api.upload_edf(self.project, self.remote_folder, p)
                if to_upload:
                    self.log.emit("Upload complete. Waiting for SleepyRat processing...")
                    ok = api.wait_for_processing(self.project, self.remote_folder)
                    if not ok:
                        raise RuntimeError("Processing did not finish within the wait limit.")
                else:
                    self.log.emit("All edf files already uploaded, skipping wait.")

            self.log.emit("Checking remote files...")
            info = api.get_submissions(self.project, self.remote_folder)
            submissions = info.get("submissions", [])
            if not submissions:
                raise RuntimeError(
                    f"No files found in project='{self.project}', "
                    f"folder='{self.remote_folder}'"
                )

            self.out_dir.mkdir(parents=True, exist_ok=True)
            all_names = [s["name"] for s in submissions]

            # When given an explicit file list, only download labels for those files.
            if self.files is not None:
                target_stems = {_norm_stem(p) for p in self.files}
                names = [n for n in all_names if _norm_stem(n) in target_stems]
                skipped_remote = len(all_names) - len(names)
                if skipped_remote:
                    self.log.emit(f"Limiting download to {len(names)} file(s) (skipping {skipped_remote} unrelated submission(s) in folder).")
            else:
                names = all_names
            to_download = [
                name for name in names
                if not (self.out_dir / (Path(name).stem + "_labels.csv")).exists()
            ]
            skipped = len(names) - len(to_download)
            if skipped:
                self.log.emit(f"Skipping {skipped} already-downloaded file(s).")
            self.log.emit(f"Downloading {len(to_download)} sleep state csv(s) to {self.out_dir}...")
            for name in to_download:
                out_path = self.out_dir / (Path(name).stem + "_labels.csv")
                labels = api.download_labels(self.project, self.remote_folder, name, threshold=0.5)
                with open(out_path, "w") as f:
                    f.write(labels)
            self.log.emit("Done.")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
