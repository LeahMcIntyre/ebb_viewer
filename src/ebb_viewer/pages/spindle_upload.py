from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QGroupBox, QMessageBox,
    QListWidget, QListView, QPlainTextEdit, QApplication, QInputDialog,
    QLabel, QComboBox, QSizePolicy
)

from ebb.io.sleepyrat import SleepyRatAPI


class SpindleUploadPage(QWidget):
    """
    Upload spindle EDFs from project_root / 'spindle_edfs' / <combo>
    and download labels into project_root / 'spindle_outputs' / <combo>.

    - User picks a subfolder under spindle_edfs as the upload source.
    - Output folder is fixed to spindle_outputs/<same_name>.
    - Remote folder name defaults to that same combo name (editable).
    """

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._api: Optional[SleepyRatAPI] = None



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
        self.remote_folder_edit = QLineEdit()
        form_layout.addRow("Remote folder name:", self.remote_folder_edit)

        folder_hint = QLabel(
            "Inside the selected SleepyRat project, submissions will be grouped "
            "in this folder (e.g. PHP_6w_LFC_RSC)."
        )
        folder_hint.setStyleSheet("color:#777; font-size:10px;")
        folder_hint.setWordWrap(True)
        form_layout.addRow("", folder_hint)

        btn_row = QHBoxLayout()
        self.btn_upload_and_download = QPushButton("Upload, Wait & Download")
        self.btn_download_only = QPushButton("Download Labels Only")

        self.btn_upload_and_download.setEnabled(False)
        self.btn_download_only.setEnabled(False)

        btn_row.addWidget(self.btn_upload_and_download)
        btn_row.addWidget(self.btn_download_only)

        form_layout.addRow(btn_row)


        root.addWidget(gb)

        # --- Log area ---
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(500)
        self.log_box.setPlaceholderText("Status messages will appear here...")
        root.addWidget(self.log_box)

    # ------------- Wiring -------------
    def _wire(self):
        # Spindle EDF selection
        self.btn_refresh_upload.clicked.connect(self._refresh_spindle_dirs)
        self.upload_combo.currentIndexChanged.connect(self._on_upload_combo_changed)

        # SleepyRat project list
        self.btn_refresh_projects.clicked.connect(self._refresh_projects_clicked)
        self.btn_new_project.clicked.connect(self._new_project_clicked)
        self.project_list.currentRowChanged.connect(
            lambda _: self._update_run_enabled()
        )

        # Remote folder text
        self.remote_folder_edit.textChanged.connect(
            lambda _: self._update_run_enabled()
        )

        self.btn_upload_and_download.clicked.connect(self._upload_and_download_clicked)
        self.btn_download_only.clicked.connect(self._download_only_clicked)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_spindle_dirs()
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
            if combo and not self.remote_folder_edit.text().strip():
                self.remote_folder_edit.setText(self.project_root.stem + '_' + combo)

        self._update_run_enabled()

    def _update_run_enabled(self):
        upload_dir = self._current_upload_dir()
        remote_folder = self.remote_folder_edit.text().strip()

        has_upload_dir = upload_dir is not None
        has_remote_folder = bool(remote_folder)

        item = self.project_list.currentItem()
        has_remote_project = item is not None and bool(item.text().strip())

        # Download-only just needs project + remote folder
        can_download_only = has_remote_project and has_remote_folder

        # Upload + download also needs a local upload_dir
        can_upload_and_download = can_download_only and has_upload_dir

        self.btn_download_only.setEnabled(can_download_only)
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
        remote_folder = self.remote_folder_edit.text().strip()

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


    def _download_only_labels(self, project: str, remote_folder: str, out_dir: Path):
        """Shared label-download logic (used by both actions)."""
        api = self._ensure_api()

        # Ensure output dir exists
        out_dir.mkdir(parents=True, exist_ok=True)

        # Warn if output dir is not empty
        existing = [p for p in out_dir.iterdir()]
        if existing:
            msg = (
                "Output folder already exists and is not empty:\n\n"
                f"{out_dir}\n\n"
                "If you continue, new label CSVs will be mixed with existing files.\n"
                "Continue anyway?"
            )
            btn = QMessageBox.question(
                self,
                "Output Folder Not Empty",
                msg,
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Cancel,
            )
            if btn != QMessageBox.StandardButton.Ok:
                return

        # Soft check remote contents
        try:
            info = api.get_submissions(project, remote_folder)
            submissions = info.get("submissions", [])
        except Exception as e:
            self._log(f"ERROR checking remote folder: {e}")
            QMessageBox.critical(
                self,
                "SleepyRat Error",
                f"Could not check remote folder contents for:\n"
                f"project='{project}', folder='{remote_folder}'\n\n{e}",
            )
            return

        if not submissions:
            msg = (
                "No submissions were found in this SleepyRat folder.\n\n"
                f"project='{project}', folder='{remote_folder}'"
            )
            QMessageBox.warning(self, "No Submissions Found", msg)
            return

        # Ask confirmation if there are already submissions
        if submissions:
            msg = (
                "The selected SleepyRat folder has "
                f"{len(submissions)} submission(s).\n\n"
                "Labels will be downloaded for this folder.\n"
                "Continue?"
            )
            btn = QMessageBox.question(
                self,
                "Download Labels",
                msg,
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Cancel,
            )
            if btn != QMessageBox.StandardButton.Ok:
                return

        # --- Download labels ---
        self._log(f"Downloading labels into {out_dir}...")
        try:
            api.download_labels_all(
                project, remote_folder, outdir=out_dir, threshold=0.5
            )
            self._log("Download complete.")
            QMessageBox.information(
                self,
                "Download Complete",
                f"Labels saved under:\n{out_dir}",
            )
        except Exception as e:
            self._log(f"ERROR during label download: {e}")
            QMessageBox.critical(self, "SleepyRat Error", str(e))

    def _upload_and_download_clicked(self):
        ctx = self._get_common_run_context()
        if ctx is None:
            return
        project, remote_folder, upload_dir, out_dir = ctx

        if upload_dir is None:
            QMessageBox.critical(
                self,
                "No Upload Folder",
                "No spindle EDF folder is selected."
            )
            return

        edfs = sorted(upload_dir.glob("*.edf"))
        if not edfs:
            QMessageBox.critical(
                self,
                "No EDF Files Found",
                f"No .edf files were found in:\n{upload_dir}",
            )
            return

        api = self._ensure_api()

        self.btn_upload_and_download.setEnabled(False)
        self.btn_download_only.setEnabled(False)

        self._log(f"Uploading EDFs from {upload_dir} to {project}/{remote_folder}...")
        try:
            api.upload_dir(project, remote_folder, upload_dir)
            self._log("All EDFs uploaded. Waiting for processing...")
            ok = api.wait_for_processing(project, remote_folder)
            if not ok:
                raise RuntimeError(
                    "Processing did not finish within the wait limit."
                )

            # Once processing is done, do the download step
            self._download_only_labels(project, remote_folder, out_dir)

        except Exception as e:
            self._log(f"ERROR during upload/wait/download: {e}")
            QMessageBox.critical(self, "SleepyRat Error", str(e))
        finally:
            self._update_run_enabled()


    def _download_only_clicked(self):
        ctx = self._get_common_run_context()
        if ctx is None:
            return
        project, remote_folder, _upload_dir, out_dir = ctx

        self.btn_upload_and_download.setEnabled(False)
        self.btn_download_only.setEnabled(False)
        try:
            self._download_only_labels(project, remote_folder, out_dir)
        finally:
            self._update_run_enabled()
