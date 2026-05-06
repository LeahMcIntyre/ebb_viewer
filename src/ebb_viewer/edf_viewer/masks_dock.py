from collections.abc import Callable

from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt

from ebb_viewer.edf_viewer.masks import Mask, MaskSet, ParamSpec


class MaskParamsDialog(QtWidgets.QDialog):
    def __init__(self, mask: Mask, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{mask.name} — Parameters")
        self.setModal(True)
        self._widgets: dict[str, tuple[QtWidgets.QWidget, type]] = {}

        form = QtWidgets.QFormLayout()
        for k, v in mask.metadata.items():
            spec = mask.param_specs.get(k)
            w = self._make_widget(v, spec)
            if spec and spec.desc is not None:
                w.setToolTip(spec.desc)
            self._widgets[k] = (w, type(v))
            form.addRow(k + ":", w)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def _make_widget(self, v, spec: ParamSpec | None = None) -> QtWidgets.QWidget:
        if isinstance(v, bool):  # must come before int (bool subclasses int)
            w = QtWidgets.QCheckBox()
            w.setChecked(v)
            return w
        if isinstance(v, int):
            w = QtWidgets.QSpinBox()
            lo = int(spec.min) if spec and spec.min is not None else -(10**9)
            hi = int(spec.max) if spec and spec.max is not None else 10**9
            w.setRange(lo, hi)
            if spec and spec.step is not None:
                w.setSingleStep(int(spec.step))
            if spec and spec.units is not None:
                w.setSuffix(f" {spec.units}")
            w.setValue(v)
            return w
        if isinstance(v, float):
            w = QtWidgets.QDoubleSpinBox()
            lo = spec.min if spec and spec.min is not None else -(10**9)
            hi = spec.max if spec and spec.max is not None else 10**9
            w.setRange(lo, hi)
            if spec and spec.step is not None:
                w.setSingleStep(spec.step)
            w.setDecimals(spec.decimals if spec else 4)
            if spec and spec.units is not None:
                w.setSuffix(f" {spec.units}")
            w.setValue(v)
            return w
        w = QtWidgets.QLineEdit(str(v))
        return w

    def values(self) -> dict:
        out = {}
        for k, (w, t) in self._widgets.items():
            if isinstance(w, QtWidgets.QCheckBox):
                out[k] = w.isChecked()
            elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                out[k] = w.value()
            else:
                text = w.text()
                try:
                    out[k] = t(text)
                except (ValueError, TypeError):
                    out[k] = text
        return out


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

    def __init__(
        self,
        refresh_overlays: Callable[[], None],
        navigate_mask: Callable[[Mask, bool], None],
        on_mask_rebuild: Callable[[Mask], None] | None = None,
        parent=None,
    ):
        super().__init__("Masks", parent)
        self.setObjectName("MasksDock")
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self._refresh = refresh_overlays
        self._navigate = navigate_mask
        self._on_rebuild = on_mask_rebuild

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

    def rebuild(self, mask_set: MaskSet, state_set: MaskSet = None) -> None:
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

    def _make_row(
        self, mask_set: MaskSet, name: str, state_set: MaskSet = None
    ) -> QtWidgets.QWidget:
        mask = mask_set.get(name)

        row = QtWidgets.QWidget()
        hb = QtWidgets.QHBoxLayout(row)
        hb.setContentsMargins(2, 2, 2, 2)
        hb.setSpacing(6)

        # Toggle checkbox
        cb = QtWidgets.QCheckBox(name)
        cb.setChecked(mask.enabled)
        cb.setIcon(self._swatch_icon(mask.color))

        cb.stateChanged.connect(lambda state, m=mask: self._on_toggle(m, state))
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

        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, m=mask: self._show_context_menu(row, pos, m)
        )

        return row

    def _show_context_menu(self, widget, pos, mask: Mask) -> None:
        menu = QtWidgets.QMenu(self)
        act = menu.addAction("Parameters…")
        act.triggered.connect(lambda: self._show_metadata_dialog(mask))
        menu.exec(widget.mapToGlobal(pos))

    def _show_metadata_dialog(self, mask: Mask) -> None:
        dlg = MaskParamsDialog(mask, parent=self)
        if dlg.exec():
            mask.metadata.update(dlg.values())
            if self._on_rebuild:
                self._on_rebuild(mask)

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
        return "\n".join(msg)
