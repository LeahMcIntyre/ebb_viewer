
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QDir, Qt
from PyQt6.QtGui import QFileSystemModel
from PyQt6.QtWidgets import QTreeView, QVBoxLayout, QWidget


class ProjectTree(QWidget):
    def __init__(self, parent=None, name_filters=None, show_sizes=True, show_types=True, show_dates=False):
        super().__init__(parent)

        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Files)
        self.model.setReadOnly(True)
        if name_filters:
            self.model.setNameFilters(name_filters)
            self.model.setNameFilterDisables(False)

        self.view = QTreeView(self)
        self.view.setModel(self.model)
        self.view.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.view.setSelectionMode(QTreeView.SelectionMode.NoSelection)
        self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.view.setUniformRowHeights(True)
        self.view.setAlternatingRowColors(True)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.view.setHeaderHidden(False)
        self.view.setColumnHidden(1, not show_sizes)  # size
        self.view.setColumnHidden(2, not show_types)  # type
        self.view.setColumnHidden(3, not show_dates)  # date

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)

    def set_root(self, root_path: str | Path | None):
        # If missing/invalid → show nothing
        if not root_path:
            self.view.setModel(None)
            return
        p = Path(root_path)
        if not p.exists():
            self.view.setModel(None)
            return

        # Attach model and point to the directory
        if self.view.model() is None:
            self.view.setModel(self.model)
        idx = self.model.setRootPath(str(p))
        self.view.setRootIndex(idx)
        self.view.header().resizeSection(0, 320)
        self.view.expandToDepth(1)
