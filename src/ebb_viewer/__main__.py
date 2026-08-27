"""Entry point for ``python -m ebb_viewer`` and the ``ebb-viewer`` script.

Prompts the user for a project root directory, then launches the
``MainWindow`` against it. The project root is the directory that holds
(or will hold) ``standard/``, ``spindle_edfs/``, ``spindle_outputs/``,
``psd/``, and ``manifest.json``.
"""

import os
import sys
from pathlib import Path

# PyQt6's Wayland backend miscomputes QMessageBox size hints, clipping the
# title bar and body text on short dialogs. Force the xcb (X11) backend on
# Linux/Wayland sessions before QApplication is constructed.
if sys.platform == "linux" and os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from ebb_viewer.main_window import MainWindow  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    project_dir = QFileDialog.getExistingDirectory(
        None,
        "Select project folder (contains original EEG EDFs to be processed)",
        "",
    )

    # User cancelled the picker → exit cleanly.
    if not project_dir:
        sys.exit(0)

    win = MainWindow(project_root=Path(project_dir))
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
