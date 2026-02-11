from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QCoreApplication
import sys

from ebb_viewer.main_window import MainWindow

def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
