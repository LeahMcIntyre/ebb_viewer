"""Reusable collapsible section: clickable header + toggleable body."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """Wraps a body widget with a clickable header that toggles its visibility.

    Designed as a drop-in alternative to ``QGroupBox`` when vertical space
    matters. The header is a flat ``QToolButton`` showing a right/down arrow
    next to the title; clicking it toggles the body.

    Emits ``toggled_visibility(bool)`` whenever the body is shown/hidden.
    """

    toggled_visibility = pyqtSignal(bool)

    def __init__(
        self,
        title: str,
        body: QWidget,
        parent: QWidget | None = None,
        *,
        collapsed: bool = True,
    ):
        super().__init__(parent)
        self._body = body

        self._btn = QToolButton()
        self._btn.setText(title)
        self._btn.setCheckable(True)
        self._btn.setChecked(not collapsed)
        self._btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._btn.setArrowType(
            Qt.ArrowType.DownArrow if not collapsed else Qt.ArrowType.RightArrow
        )
        self._btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn.setStyleSheet(
            "QToolButton { border: 1px solid #ccc; border-radius: 3px;"
            " padding: 4px 8px; background: #f5f5f5; color: #333; font-weight: 600;"
            " text-align: left; }"
            "QToolButton:checked { background: #e8e8e8; }"
            "QToolButton:hover { background: #ebebeb; }"
        )
        self._btn.clicked.connect(self._on_toggle)

        self._body.setVisible(not collapsed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._btn)
        layout.addWidget(self._body)

    def _on_toggle(self, checked: bool) -> None:
        self._body.setVisible(checked)
        self._btn.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )
        self.toggled_visibility.emit(checked)

    def set_collapsed(self, collapsed: bool) -> None:
        """Programmatically expand (False) or collapse (True) the section."""
        self._btn.setChecked(not collapsed)
        self._on_toggle(not collapsed)

    def is_collapsed(self) -> bool:
        return not self._btn.isChecked()
