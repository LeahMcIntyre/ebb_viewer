# ebb_viewer/__main__.py

import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QFileDialog

from ebb_viewer.main_window import MainWindow  # whatever your path is

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 1. Ask user to pick a project folder
    project_dir = QFileDialog.getExistingDirectory(
        None,
        "Select project folder (contains original EEG EDFs to be processed)",
        "",  # optional: last used dir or home
    )

    # If they cancel → just quit
    if not project_dir:
        sys.exit(0)

    project_root = Path(project_dir)

    # 2. Create main window with that project root
    win = MainWindow(project_root=project_root)
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
