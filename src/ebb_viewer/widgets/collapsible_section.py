"""Reusable collapsible section: clickable header + toggleable body."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class CollapsibleSection(QWidget):
    """Wraps a body widget with a clickable header that toggles its visibility.

    Designed as a drop-in alternative to ``QGroupBox`` when vertical space
    matters. The header is a flat ``QToolButton`` showing a right/down arrow
    next to the title; clicking it toggles the body.

    Emits ``toggled_visibility(bool)`` whenever the body is shown/hidden.
    """

    toggled_visibility = pyqtSignal(bool)

    _BTN_QSS = (
        "QToolButton { border: 1px solid #ccc; border-radius: 3px;"
        " padding: 4px 8px; background: #f5f5f5; color: #333; font-weight: 600;"
        " text-align: left; }"
        "QToolButton:checked { background: #e8e8e8; }"
        "QToolButton:hover { background: #ebebeb; }"
    )
    _BTN_ACTIVE_QSS = _BTN_QSS + "QToolButton { border-left: 3px solid #1a5fa8; }"
    _SUBTITLE_QSS = "color: #666; font-size: 11px; padding-right: 8px; background: transparent;"
    _SUBTITLE_ACTIVE_QSS = (
        "color: #1a5fa8; font-size: 11px; font-weight: bold; padding-right: 8px; "
        "background: transparent;"
    )

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
        self._btn.setStyleSheet(self._BTN_QSS)
        self._btn.clicked.connect(self._on_toggle)

        # Right-aligned dim subtitle (e.g. summary of current settings).
        self._subtitle_lbl = QLabel("")
        self._subtitle_lbl.setStyleSheet(self._SUBTITLE_QSS)
        self._subtitle_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        )

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(2)
        header_row.addWidget(self._btn, 1)
        header_row.addWidget(self._subtitle_lbl)

        self._body.setVisible(not collapsed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(header_row)
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

    def set_subtitle(self, text: str) -> None:
        """Set a short summary string displayed right-aligned in the header."""
        self._subtitle_lbl.setText(text)

    def set_active(self, active: bool) -> None:
        """Mark the section as switched on: blue accent on the header and subtitle."""
        self._btn.setStyleSheet(self._BTN_ACTIVE_QSS if active else self._BTN_QSS)
        self._subtitle_lbl.setStyleSheet(self._SUBTITLE_ACTIVE_QSS if active else self._SUBTITLE_QSS)

    def subtitle(self) -> str:
        return self._subtitle_lbl.text()
