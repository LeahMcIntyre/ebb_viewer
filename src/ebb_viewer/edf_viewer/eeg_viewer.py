import sys

from pathlib import Path
from datetime import datetime

import pandas as pd

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import Qt
from openseize.file_io import edf

from ebb.masking import get_offset

from ebb_viewer.widgets.drink_mask_dialog import DrinkMaskDialogue
from ebb_viewer.widgets.stft_viewer import STFTPopup, STFTBoundsDialog

from ebb_viewer.edf_viewer.recording import Recording
from ebb_viewer.edf_viewer.trace_view import TraceView
from ebb_viewer.edf_viewer.file_openers import pick_edf_csv, pick_mat, pick_npy_csv
from ebb_viewer.edf_viewer.mask_builder import (
    build_default_masks, load_state_masks, load_swd_mask, load_drink_mask,
    rebuild_artifact_masks, rebuild_spindle_mask, rebuild_drink_mask,
)
from ebb_viewer.edf_viewer.masks_dock import MasksDock

_CHANNEL_COMBOS = ["LFC_RSC", "LFC_LSC", "RSC_LSC", "LFC", "RSC", "LSC"]




class EegMainWindow(QtWidgets.QMainWindow):
    def __init__(self, recording: Recording, initial_dir: str = "", manifest=None, animal_id: str | None = None, run_channels: str | None = None, parent=None):
        super().__init__(parent)
        self.rec = recording
        self.initial_dir = initial_dir
        self.manifest = manifest
        self.animal_id = animal_id
        self.run_channels = run_channels  # channel combo for the spindle run being reviewed

        self.mask_set = build_default_masks(recording)
        self.state_set = None
        self.state_df = None

        # STFT state
        self.stft_fmin = 0
        self.stft_fmax = 120
        self.nperseg = 125  # 0.5 s at 250 Hz
        self._stft_popup = STFTPopup(self, title="EEG STFT")
        self._stft_popup.resize(1200, 800)


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
            try:
                df = pd.read_csv(recording.csv_path)
                self.state_df = df.drop(columns=["state", "threshold"], errors="ignore")
            except Exception:
                self.state_df = None

        # actions/toolbars/menus
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        if self.manifest is not None and self.animal_id is not None and self.run_channels is not None:
            self._build_qc_toolbar()
        self._build_docks()

        self.trace_view.timeDoubleClicked.connect(self.on_time_double_clicked)

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

    # ---------- menus / toolbars / docks ----------

    def _build_menus(self):
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_load_swd)
        m_file.addAction(self.act_load_drink)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)
        m_file.addAction(self.act_info)


        m_view = mb.addMenu("&View")

        m_tools = mb.addMenu("&Tools")
        m_tools.addAction(self.act_stft)
        m_tools.addAction(self.act_stft_bounds)

    def _build_toolbars(self):
        nav_tb = self.addToolBar("Navigation")
        nav_tb.setObjectName("NavigationToolbar")
        # example: add open action here too
        nav_tb.addAction(self.act_open)
        nav_tb.addAction(self.act_load_swd)
        nav_tb.addAction(self.act_load_drink)
        # later, add zoom / “go to next mask” etc.

        tools_tb = self.addToolBar("Tools")
        tools_tb.setObjectName("ToolsToolbar")
        tools_tb.addAction(self.act_stft)
        #tools_tb.addAction(self.act_psd)

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

    def _navigate_mask(self, mask, forward: bool) -> None:
        span = mask.next_span_after(self.trace_view.center_sample) if forward else mask.prev_span_before(self.trace_view.center_sample)
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

        self._qc_status_label = QtWidgets.QLabel()
        self._qc_status_label.setMinimumWidth(130)
        qc_tb.addWidget(self._qc_status_label)
        qc_tb.addSeparator()

        act_ok = QtGui.QAction("✓ Mark OK", self)
        act_ok.triggered.connect(self._flag_qc_ok)
        qc_tb.addAction(act_ok)

        qc_tb.addSeparator()

        # Rerun combo: pick a different combo from the current run_channels
        self._rerun_combo = QtWidgets.QComboBox()
        self._rerun_combo.addItems(_CHANNEL_COMBOS)
        run = self.manifest.get_run(self.animal_id, self.run_channels)
        if run and run.rerun_combo and run.rerun_combo in _CHANNEL_COMBOS:
            self._rerun_combo.setCurrentText(run.rerun_combo)
        else:
            others = [c for c in _CHANNEL_COMBOS if c != self.run_channels]
            if others:
                self._rerun_combo.setCurrentText(others[0])
        qc_tb.addWidget(self._rerun_combo)

        act_rerun = QtGui.QAction("Needs Rerun", self)
        act_rerun.triggered.connect(self._flag_qc_rerun)
        qc_tb.addAction(act_rerun)

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
        _STYLE = {
            "ok":           "color: green; font-weight: bold;",
            "needs_review": "color: #b8860b; font-weight: bold;",
            "needs_rerun":  "color: darkorange; font-weight: bold;",
        }
        txt = (status or "unflagged").replace("_", " ")
        self._qc_status_label.setText(f"QC [{self.run_channels}]: {txt}")
        self._qc_status_label.setStyleSheet(_STYLE.get(status, ""))

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

        self.trace_view.refresh_overlays()
        self.masks_dock.rebuild(self.mask_set, self.state_set)

    # ---------- behavior ----------

    def on_load_swd(self):
        mat_path = pick_mat(self, self.initial_dir)
        if mat_path is None:
            return
        
        try:
            _, n_samples = self.rec.data.shape
            self.mask_set.add(load_swd_mask(mat_path, fs=self.rec.fs, n_samples=n_samples))
            self.trace_view.refresh_overlays()
            self.masks_dock.rebuild(self.mask_set, self.state_set)
            self.rec.swd_path = mat_path
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load Error", f"{type(e).__name__}: {e}")


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
                self.mask_set.add(load_drink_mask(drink_path, fs=self.rec.fs, offset_sec=offset, pad_sec=pad_sec))
                self.trace_view.refresh_overlays()
                self.masks_dock.rebuild(self.mask_set, self.state_set)
                self.rec.drink_path = drink_path
                self.rec.video_offset = offset 
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Load Error", f"{type(e).__name__}: {e}")

    def on_open(self):
        # reuse your existing pick_edf_csv_npy
        edf_path, csv_path = pick_edf_csv(self, self.initial_dir)
        if not edf_path:
            return

        try:
            with edf.Reader(str(edf_path)) as reader:
                data = reader.read(start=0)
                fs = float(250)  # or use reader.header.samples_per_record[0]
                start_str = reader.header.start_time
                date_str = reader.header.start_date

            fmt_eeg = "%d.%m.%y %H.%M.%S"
            start_time = datetime.strptime(f"{date_str} {start_str}", fmt_eeg)
            ch_names = ("LFC", "RSC", "LSC", "EMG")
            rec = Recording(
                edf_path=edf_path,
                data=data,
                fs=fs,
                start_time=start_time,
                ch_names=ch_names,
                csv_path=csv_path,
            )

            # launch a *new* window with the new recording
            win = EegMainWindow(rec, initial_dir=self.initial_dir)
            win.resize(self.width(), self.height())
            win.show()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load Error", f"{type(e).__name__}: {e}")

    def on_time_double_clicked(self, t_sec: float):
        if self.state_df is None:
            return
        epoch_samples = int(4 * self.rec.fs)
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
    """Load an EDF file and return a configured (not yet shown) EegMainWindow."""
    with edf.Reader(str(edf_path)) as reader:
        data = reader.read(start=0)
        fs = int(reader.header.samples_per_record[0])
        start_str = reader.header.start_time
        date_str = reader.header.start_date
    start_time = datetime.strptime(f"{date_str} {start_str}", "%d.%m.%y %H.%M.%S")
    rec = Recording(
        data=data,
        fs=fs,
        start_time=start_time,
        ch_names=("LFC", "RSC", "LSC", "EMG"),
        edf_path=edf_path,
        csv_path=csv_path,
    )
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
    app = QtWidgets.QApplication(sys.argv)
    
    # initial dir and one dataset load (as you already do)
    initial_dir = "/media/matt/Data_A/leah/SRA/SRA_6_mo"
    edf_path, csv_path = pick_edf_csv(None, initial_dir)
    if not edf_path:
        return
    

    """
    initial_dir = "/media/matt/Data_A/leah/Stxbp1 characterization"

    edf_path = '/media/matt/Data_A/leah/Stxbp1 characterization/standard/Mice-1251_KO_15_53_5weeks-3dayEEG_2017-08-11_17_56_14_HK_PREPROCESSED.edf'
    csv_path = '/media/matt/Data_A/leah/Stxbp1 characterization/spindle_outputs/LFC_RSC/Mice-1251_KO_15_53_5weeks-3dayEEG_2017-08-11_17_56_14_HK_PREPROCESSED_SPINDLE_labels.csv'
    """
    with edf.Reader(str(edf_path)) as reader:
        data = reader.read(start=0)
        fs = int(reader.header.samples_per_record[0])
        if fs != 250:
            print(f"Sampling frequency of selected file is {fs}. Please pick a file with a frequency of 250.")
            return
        
        start_str = reader.header.start_time
        date_str = reader.header.start_date

    fmt_eeg = "%d.%m.%y %H.%M.%S"
    start_time = datetime.strptime(f"{date_str} {start_str}", fmt_eeg)
    animal = Path(edf_path).stem.split("_")[0]
    
    ch_names = ("LFC", "RSC", "LSC", "EMG")

    rec = Recording(
        data=data,
        fs=fs,
        start_time=start_time,
        ch_names=ch_names,
        edf_path=edf_path,
        csv_path=csv_path,
    )

    w = EegMainWindow(rec, initial_dir=initial_dir)
    w.setWindowTitle(f"{Path(edf_path).stem} EEG Viewer")
    w.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()