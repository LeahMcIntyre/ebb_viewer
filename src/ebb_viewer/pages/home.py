from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QVBoxLayout, QLabel, QWidget

from ebb_viewer.widgets.tree_view import ProjectTree

class HomePage(QWidget):
    def __init__(self, parent=None, *, project_root: Path):
        super().__init__(parent)
        self.project_root = project_root

        self._build_ui()

    # ---------------- UI ----------------
    def _build_ui(self):
        root_layout = QVBoxLayout(self)

        lbl = QLabel("Files in Current Project")
        lbl.setStyleSheet("font-weight: bold; font-size: 15px;")
        root_layout.addWidget(lbl)

        self.edf_tree = ProjectTree()

        self.edf_tree.set_root(root_path=self.project_root)
        root_layout.addWidget(self.edf_tree)


