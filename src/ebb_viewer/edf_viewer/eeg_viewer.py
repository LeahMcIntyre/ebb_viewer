import sys

from pathlib import Path
from datetime import datetime

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import Qt
from openseize.file_io import edf

from ebb_viewer.edf_viewer.recording import Recording
from ebb_viewer.edf_viewer.trace_view import TraceView
from ebb_viewer.edf_viewer.file_openers import pick_edf_csv
from ebb_viewer.edf_viewer.mask_builder import build_default_masks
from ebb_viewer.edf_viewer.masks_dock import MasksDock




class EegMainWindow(QtWidgets.QMainWindow):
    def __init__(self, recording: Recording, initial_dir: str = "", parent=None):
        super().__init__(parent)
        self.rec = recording
        self.initial_dir = initial_dir
        self.mask_set = build_default_masks(recording)

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

        # actions/toolbars/menus
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_docks()  # empty placeholders for now

        # example: connect time double-click upwards
        #self.trace_view.timeDoubleClicked.connect(self.on_time_double_clicked)

    # ---------- actions ----------

    def _build_actions(self):
        self.act_open = QtGui.QAction("&Open…", self)
        self.act_open.setShortcut("Ctrl+O")
        self.act_open.triggered.connect(self.on_open)

        self.act_quit = QtGui.QAction("&Quit", self)
        self.act_quit.setShortcut("Ctrl+Q")
        self.act_quit.triggered.connect(self.close)

        # stub actions for future tools
        self.act_stft = QtGui.QAction("Plot STFT", self)
        #self.act_psd = QtGui.QAction("Plot PSD", self)
        # connect these later when STFTPopup is reattached

    # ---------- menus / toolbars / docks ----------

    def _build_menus(self):
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        m_file.addAction(self.act_open)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        m_view = mb.addMenu("&View")
        # later: add dock toggle actions here

        m_tools = mb.addMenu("&Tools")
        m_tools.addAction(self.act_stft)
        #m_tools.addAction(self.act_psd)

    def _build_toolbars(self):
        nav_tb = self.addToolBar("Navigation")
        nav_tb.setObjectName("NavigationToolbar")
        # example: add open action here too
        nav_tb.addAction(self.act_open)
        # later, add zoom / “go to next mask” etc.

        tools_tb = self.addToolBar("Tools")
        tools_tb.setObjectName("ToolsToolbar")
        tools_tb.addAction(self.act_stft)
        #tools_tb.addAction(self.act_psd)

    def _build_docks(self):
        self.masks_dock = MasksDock(
            refresh_overlays=self.trace_view.refresh_overlays,
            parent=self,
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.masks_dock)
        self.masks_dock.rebuild(self.mask_set)

    # ---------- behavior ----------

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
    """
    def on_time_double_clicked(self, t_sec: float):
        # placeholder: later you can do your state_df lookup here
        QtWidgets.QMessageBox.information(
            self,
            "Time Double Clicked",
            f"You double-clicked at {t_sec:.3f} seconds",
        )"""
    

def main():
    app = QtWidgets.QApplication(sys.argv)

    # initial dir and one dataset load (as you already do)
    initial_dir = "/media/matt/Data_A/leah/SRA/SRA_6_week"
    edf_path, csv_path = pick_edf_csv(None, initial_dir)
    if not edf_path:
        return

    with edf.Reader(str(edf_path)) as reader:
        data = reader.read(start=0)
        fs = float(reader.header.samples_per_record[0])
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
        csv_path=csv_path,
    )

    w = EegMainWindow(rec, initial_dir=initial_dir)
    w.setWindowTitle(f"{Path(edf_path).stem} EEG Viewer")
    w.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()