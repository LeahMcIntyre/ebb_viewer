import time

from PyQt6.QtWidgets import (
    QVBoxLayout, QGroupBox, QGridLayout, QLabel, QCheckBox,
    QPushButton, QHBoxLayout, QSpacerItem, QSizePolicy,
    QMessageBox, QFormLayout, QLineEdit, QWidget, QFrame,
    QPlainTextEdit, QApplication,
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal
from pathlib import Path
from typing import Optional

from ebb.preprocess.edf import spindle, batch as batch_preprocess
from ebb_viewer.pipeline.manifest import Manifest
from ebb_viewer.widgets.worker_helpers import launch_worker


class SpindleWritePage(QWidget):
    navigate_to = pyqtSignal(str)

    CH_LABELS = {
        "Ch0": "LFC",
        "Ch1": "RSC",
        "Ch2": "LSC",
        "Ch3": "EMG (always included)",
    }

    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = Path(project_root)

        # Will be updated by _refresh_standard_dir
        self.standard_folder: Optional[Path] = None

        self._build_ui()
        self._wire()

        # Initial refresh + validation
        self._refresh_standard_dir()
        self._update_target_path()
        self._validate()

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)

        # ----- Folder selection group -----
        folder_gb = QGroupBox("Folder Selection")
        folder_gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        folder_gb.setObjectName("folderBox")

        top_form = QFormLayout(folder_gb)

        # Standard folder (read-only, driven by project_root/standard)
        self.lbl_standard = QLineEdit("Checking for standard folder…")
        self.lbl_standard.setReadOnly(True)
        top_form.addRow("Standard EDF Folder:", self.lbl_standard)

        # Channel combo name (read-only, derived from selected EEG channels)
        self.combo_name_edit = QLineEdit("")
        self.combo_name_edit.setReadOnly(True)
        top_form.addRow("Channel Combo:", self.combo_name_edit)

        # Target spindle EDF folder (editable but prefilled from project_root)
        self.target_name_edit = QLineEdit()
        self.target_name_edit.setStyleSheet(
            "QLineEdit { padding-top: 0px; padding-bottom: 0px; }"
        )
        self.target_name_edit.setReadOnly(True)
        top_form.addRow("Target Directory:", self.target_name_edit)

        # ----- Channel selection group -----
        gb = QGroupBox("Channel Selection")
        gb.setObjectName("channelBox")
        gb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.setStyleSheet("""
        QGroupBox#folderBox, QGroupBox#channelBox {
            font: 550;
        }
        QGroupBox#folderBox *, QGroupBox#channelBox * {
            font: 400;
        }
        """)

        grid = QGridLayout(gb)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        self.lbl_rule = QLabel(
            "Select either <b>exactly 1</b> or <b>exactly 2</b> of the first three channels."
        )
        self.lbl_rule.setTextFormat(Qt.TextFormat.RichText)
        grid.addWidget(self.lbl_rule, 0, 0, 1, 3)

        self.cb_ch0 = QCheckBox(f"Ch0 — {self.CH_LABELS['Ch0']}")
        self.cb_ch0.setChecked(True)
        self.cb_ch1 = QCheckBox(f"Ch1 — {self.CH_LABELS['Ch1']}")
        self.cb_ch1.setChecked(True)
        self.cb_ch2 = QCheckBox(f"Ch2 — {self.CH_LABELS['Ch2']}")
        grid.addWidget(self.cb_ch0, 1, 0)
        grid.addWidget(self.cb_ch1, 1, 1)
        grid.addWidget(self.cb_ch2, 1, 2)

        grid.addItem(
            QSpacerItem(0, 6, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum),
            2, 0, 1, 3
        )

        self.cb_ch3 = QCheckBox(f"Ch3 — {self.CH_LABELS['Ch3']}")
        self.cb_ch3.setChecked(True)
        self.cb_ch3.setEnabled(False)
        self.cb_ch3.setToolTip("This channel is required and will always be processed.")

        self.lbl_lock = QLabel("🔒 Always included — no selection required")
        f = QFont()
        f.setPointSize(f.pointSize() - 1)
        self.lbl_lock.setFont(f)
        self.lbl_lock.setStyleSheet("color: #666;")

        lock_row = QHBoxLayout()
        lock_row.addWidget(self.cb_ch3)
        lock_row.addWidget(self.lbl_lock)
        lock_row.addStretch(1)
        grid.addLayout(lock_row, 3, 0, 1, 3)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: #b00020;")
        grid.addWidget(self.lbl_status, 4, 0, 1, 3)

        # ----- Actions -----
        actions = QHBoxLayout()
        self.btn_apply = QPushButton("Run Spindle Preprocessor")
        self.btn_apply.setEnabled(False)
        actions.addWidget(self.btn_apply)

        root.addWidget(folder_gb)
        root.addWidget(gb)
        root.addLayout(actions)


        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(300)
        self.log_box.setPlaceholderText("Status messages will appear here…")
        root.addWidget(self.log_box)

        # Post-run hint (hidden until a run succeeds)
        self._hint_frame = QFrame()
        self._hint_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._hint_frame.setStyleSheet(
            "QFrame { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; }"
        )
        hint_layout = QHBoxLayout(self._hint_frame)
        hint_layout.setContentsMargins(10, 6, 10, 6)
        hint_lbl = QLabel("✓ Done. Spindle EDFs written.")
        hint_layout.addWidget(hint_lbl, 1)
        btn_go_upload = QPushButton("→ Spindle Upload")
        btn_go_upload.clicked.connect(lambda: self.navigate_to.emit("spindle_upload"))
        hint_layout.addWidget(btn_go_upload)
        self._hint_frame.setVisible(False)
        root.addWidget(self._hint_frame)

        root.addStretch()


    # ------------ Wiring / Signals ------------
    def _wire(self):
        # Channels drive validation + combo/target updates
        self.cb_ch0.toggled.connect(self._on_channels_changed)
        self.cb_ch1.toggled.connect(self._on_channels_changed)
        self.cb_ch2.toggled.connect(self._on_channels_changed)
        self.btn_apply.clicked.connect(self._run_spindle_btn)

    def _on_channels_changed(self, _checked: bool):
        self._update_target_path()
        self._validate()

    # ------------ Refresh when page is shown ------------
    def showEvent(self, event):
        """Whenever the page is shown, re-check if 'standard' exists."""
        super().showEvent(event)
        self._refresh_standard_dir()
        self._update_target_path()
        self._validate()

    def _refresh_standard_dir(self) -> None:
        """
        Look for a folder named 'standard' in project_root.
        If it exists, use it; otherwise show 'Run preprocessing first'.
        """
        candidate = self.project_root / "standard"

        if candidate.exists() and candidate.is_dir():
            self.standard_folder = candidate
            self.lbl_standard.setText(str(candidate))
            self.lbl_standard.setToolTip(str(candidate))
        else:
            self.standard_folder = None
            self.lbl_standard.setText("No standard folder available. Run preprocessing first.")
            self.lbl_standard.setToolTip("")

    # ------------ Actions ------------
    def _run_spindle_btn(self):
        channels = self._selected_indices()

        if self.standard_folder is None:
            QMessageBox.critical(
                self,
                "No Standard EDF Folder",
                "Standard folder is not set.\n\n"
                "Make sure preprocessing has been run and a 'standard' folder "
                "exists in your project root."
            )
            return

        if not self.standard_folder.exists():
            QMessageBox.critical(
                self,
                "Standard Folder Missing",
                f"Standard folder does not exist:\n{self.standard_folder}"
            )
            return

        # Derive combo name from selected EEG channels (Ch0–Ch2)
        eeg_labels = self._current_eeg_labels()
        if not eeg_labels:
            QMessageBox.critical(
                self,
                "No Channels Selected",
                "Please select at least one EEG channel."
            )
            return

        # Simple combo name, e.g. "LFC_RSC"
        combo_name = "_".join(eeg_labels)

        # Default target dir based on our canonical structure under project_root
        spindle_root = self.project_root / "spindle_edfs"
        default_target = spindle_root / combo_name

        # Allow user to override target path if they really want
        target_text = self.target_name_edit.text().strip()
        target_dir = Path(target_text) if target_text else default_target

        # If the user cleared the field, confirm using default
        if not target_text:
            msg = (
                "No target folder specified.\n\n"
                f"Use default spindle folder for this combo?\n\n{default_target}"
            )
            btn = QMessageBox.question(
                self,
                "No Target Folder Selected",
                msg
            )
            if btn != QMessageBox.StandardButton.Yes:
                return
            self.target_name_edit.setText(str(default_target))
            self.target_name_edit.setToolTip(str(default_target))
            target_dir = default_target

        # Reject if target already exists — contents would be silently mixed
        if target_dir.exists():
            QMessageBox.critical(
                self,
                "Folder Already Exists",
                f"The spindle output folder already exists:\n{target_dir}\n\n"
                "Delete it first or choose a different channel combination.",
            )
            return

        try:
            spindle_root.mkdir(parents=True, exist_ok=True)
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Folder Error",
                f"Could not create spindle folder(s):\n{target_dir}\n\n{e}",
            )
            return

        self.btn_apply.setEnabled(False)
        self._hint_frame.setVisible(False)

        self._spindle_thread = QThread(self)
        self._spindle_worker = _SpindleWriteWorker(
            standard_folder=self.standard_folder,
            target_dir=target_dir,
            channels=channels,
        )
        self._spindle_worker.log.connect(self._log)
        launch_worker(
            self._spindle_thread, self._spindle_worker,
            on_finished=self._on_spindle_done,
            on_error=lambda msg: (
                self._validate(),
                QMessageBox.critical(self, "Spindle Preprocess failed", msg),
            ),
        )

    def _log(self, msg: str):
        self.log_box.appendPlainText(msg)
        QApplication.processEvents()

    def _on_spindle_done(self):
        Manifest.build_from_standard(self.project_root)
        self._validate()
        self._hint_frame.setVisible(True)

    # ------------ Validation ------------
    def _validate(self):
        n = len(self._selected_indices())

        if n == 2:
            # 1 EEG + EMG
            self.lbl_status.setText("1 selected. You can apply.")
            self.lbl_status.setStyleSheet("color: #0a7f2e;")
            self._update_target_path()

        elif n == 3:
            # 2 EEG + EMG
            self.lbl_status.setText("Perfect - Two selected. You can apply.")
            self.lbl_status.setStyleSheet("color: #0a7f2e;")
            self._update_target_path()

        else:
            msg = (
                "Select 1 or 2 channels from Ch0–Ch2."
                if n < 2
                else "Maximum is 2 channels from Ch0–2."
            )
            self.lbl_status.setText(msg)
            self.lbl_status.setStyleSheet("color: #b00020;")
            self.btn_apply.setEnabled(False)

        run_enabled = (n == 2) or (n == 3)
        if self.standard_folder is None:
            run_enabled = False
        self.btn_apply.setEnabled(run_enabled)

    # ------------ Helpers ------------
    def _selected_indices(self):
        """Return selected channel indices including EMG (3)."""
        sel = []
        if self.cb_ch0.isChecked():
            sel.append(0)
        if self.cb_ch1.isChecked():
            sel.append(1)
        if self.cb_ch2.isChecked():
            sel.append(2)
        sel.append(3)  # ch3 always (EMG)
        return sel

    def _current_eeg_labels(self):
        """Return labels for selected EEG channels (Ch0–Ch2), e.g. ['LFC','RSC']."""
        labels = []
        if self.cb_ch0.isChecked():
            labels.append(self.CH_LABELS["Ch0"])
        if self.cb_ch1.isChecked():
            labels.append(self.CH_LABELS["Ch1"])
        if self.cb_ch2.isChecked():
            labels.append(self.CH_LABELS["Ch2"])
        return labels

    def _update_target_path(self):
        """
        Update suggested combo name and target folder whenever project,
        standard folder, or channel selection changes.
        """
        if self.standard_folder is None:
            self.combo_name_edit.setText("")
            self.combo_name_edit.setToolTip("")
            self.target_name_edit.setText("")
            self.target_name_edit.setToolTip("")
            return

        eeg_labels = self._current_eeg_labels()
        if not eeg_labels:
            self.combo_name_edit.setText("")
            self.combo_name_edit.setToolTip("")
            self.target_name_edit.setText("")
            self.target_name_edit.setToolTip("")
            return

        combo_name = "_".join(eeg_labels)  # e.g. "LFC_RSC"
        target = self.project_root / "spindle_edfs" / combo_name

        self.combo_name_edit.setText(combo_name)
        self.combo_name_edit.setToolTip(combo_name)
        self.target_name_edit.setText(str(target))
        self.target_name_edit.setToolTip(str(target))


class _SpindleWriteWorker(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, *, standard_folder, target_dir, channels, parent=None):
        super().__init__(parent)
        self.standard_folder = standard_folder
        self.target_dir = target_dir
        self.channels = channels

    def run(self):
        try:
            n = sum(1 for _ in self.standard_folder.glob("*.edf"))
            if not n:
                self.log.emit("No EDF files found in standard folder.")
                self.finished.emit()
                return
            self.log.emit(f"Starting spindle preprocessing on {n} file(s)…")
            t0 = time.perf_counter()
            outs = batch_preprocess(
                spindle, self.standard_folder,
                target=self.target_dir,
                channels=self.channels,
                verbose=False,
            )
            elapsed = time.perf_counter() - t0
            self.log.emit(f"Done: {len(outs)} file(s) written — {elapsed:.2f}s")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
