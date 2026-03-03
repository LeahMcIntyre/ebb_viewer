from typing import Callable

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import Qt

from ebb_viewer.edf_viewer.masks import Mask, MaskSet


def _mask_key(mask_set: MaskSet, name: str) -> str:
    """Return the 1-based keyboard shortcut key for this mask, or '' if beyond 9."""
    for idx, mask in enumerate(mask_set):
        if mask.name == name:
            return str(idx + 1) if idx < 9 else ""
    return ""


class MasksDock(QtWidgets.QDockWidget):
    """Dock panel showing each mask as a colored swatch + name + toggle checkbox.

    Args:
        refresh_overlays:
            Callable with no arguments that re-renders overlays on the trace
            view. Passed in so this dock stays decoupled from EegMainWindow.
        parent:
            Parent widget.
    """

    def __init__(self, refresh_overlays: Callable[[], None],
                 navigate_mask: Callable[["Mask", bool], None], parent=None):
        super().__init__("Masks", parent)
        self.setObjectName("MasksDock")
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self._refresh = refresh_overlays
        self._navigate = navigate_mask

        # Scroll area so the list can grow without clipping
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QtWidgets.QWidget()
        self._layout = QtWidgets.QHBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._layout.setSpacing(16)
        self._layout.setContentsMargins(6, 4, 6, 4)

        scroll.setWidget(self._container)
        self.setWidget(scroll)
        self.setMaximumHeight(80)

    # ------------------------------------------------------------------

    def rebuild(self, mask_set: MaskSet, state_set: MaskSet=None) -> None:
        """Clear and repopulate the row list from mask_set."""
        # Remove all existing rows
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for mask in mask_set:
            row = self._make_row(mask_set, mask.name, state_set)
            self._layout.addWidget(row)

    # ------------------------------------------------------------------

    def _make_row(self, mask_set: MaskSet, name: str, state_set: MaskSet=None) -> QtWidgets.QWidget:
        mask = mask_set.get(name)

        row = QtWidgets.QWidget()
        hb = QtWidgets.QHBoxLayout(row)
        hb.setContentsMargins(2, 2, 2, 2)
        hb.setSpacing(6)

        # Toggle checkbox
        cb = QtWidgets.QCheckBox(name)
        cb.setChecked(mask.enabled)
        cb.setIcon(self._swatch_icon(mask.color))

        cb.stateChanged.connect(
            lambda state, m=mask: self._on_toggle(m, state)
        )
        if state_set is not None:
            cb.setToolTip(self._state_overlap(mask, state_set))

        btn_prev = QtWidgets.QPushButton("◀")
        btn_prev.setFixedWidth(24)
        btn_prev.setToolTip(f"Previous {name} span  (Shift+{_mask_key(mask_set, name)})")
        btn_prev.clicked.connect(lambda _, m=mask: self._navigate(m, False))

        btn_next = QtWidgets.QPushButton("▶")
        btn_next.setFixedWidth(24)
        btn_next.setToolTip(f"Next {name} span  ({_mask_key(mask_set, name)})")
        btn_next.clicked.connect(lambda _, m=mask: self._navigate(m, True))

        hb.addWidget(cb)
        hb.addWidget(btn_prev)
        hb.addWidget(btn_next)
        return row

    def _swatch_icon(self, rgba, size=14) -> QtGui.QIcon:
        r, g, b, a = rgba
        pix = QtGui.QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setBrush(QtGui.QColor(r, g, b, a)) 
        p.setPen(QtGui.QPen(QtGui.QColor(180, 180, 180)))
        p.drawRoundedRect(1, 1, size - 1, size - 1, 3, 3)
        p.end()
        return QtGui.QIcon(pix)

    def _on_toggle(self, mask, state: int) -> None:
        mask.enabled = state == Qt.CheckState.Checked.value
        self._refresh()

    def _state_overlap(self, mask: Mask, state_set: MaskSet) -> str:
        msg = []
        for state_mask in state_set:
            overlap = state_mask.overlap_samples(mask) / state_mask.total_samples
            msg.append(f"{state_mask.name[0].upper()}: {100 * overlap:.2f}%")
        return '\n'.join(msg)
