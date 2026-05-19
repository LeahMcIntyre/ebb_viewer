"""Variable-length spinbox widget for the Trim To (hrs) sequence.

Holds 1–4 hour-target spinboxes inline with [+] / [−] buttons to add or
remove targets. Returns the current values as a ``list[int]`` in display
order; consumers (the preprocess page) sort at use time. ``compute_trim_stop_samples``
in ``ebb.preprocess.edf`` is already length-agnostic, so the widget can
emit any length in ``[min_count, max_count]``.
"""

from collections.abc import Sequence

from PyQt6.QtCore import QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSpinBox, QWidget


class TrimToWidget(QWidget):
    """1–4 spinboxes plus [+]/[−] buttons; emits ``changed(list[int])``."""

    changed = pyqtSignal(list)

    def __init__(
        self,
        parent=None,
        *,
        minimum: int = 1,
        maximum: int = 168,
        step: int = 1,
        values: Sequence[int] = (48, 72),
        min_count: int = 1,
        max_count: int = 4,
    ):
        super().__init__(parent)
        if min_count < 1 or max_count < min_count:
            raise ValueError(f"invalid count bounds: [{min_count}, {max_count}]")

        self._min = int(minimum)
        self._max = int(maximum)
        self._step = int(step)
        self._min_count = int(min_count)
        self._max_count = int(max_count)

        self._boxes: list[QSpinBox] = []
        self._or_labels: list[QLabel] = []

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

        self.btn_add = QPushButton("+")
        self.btn_add.setFixedSize(24, 24)
        self.btn_add.setToolTip("Add another trim target")
        self.btn_add.clicked.connect(self._on_add_clicked)

        self.btn_remove = QPushButton("−")
        self.btn_remove.setFixedSize(24, 24)
        self.btn_remove.setToolTip("Remove the last trim target")
        self.btn_remove.clicked.connect(self._on_remove_clicked)

        self._layout.addWidget(self.btn_add)
        self._layout.addWidget(self.btn_remove)
        self._layout.addStretch(1)

        # Seed with the provided defaults.
        self.setValue(values)

    # ---- Public API ----------------------------------------------------

    def value(self) -> list[int]:
        """Current spinbox values in display order."""
        return [b.value() for b in self._boxes]

    def setValue(self, values: Sequence[int]) -> None:
        """Replace the current spinboxes with ones for ``values``.

        Rebuilds in a single signal-blocked pass so a bulk update emits
        exactly one ``changed``. Values outside ``[min_count, max_count]``
        in length raise ``ValueError`` — the caller is responsible for
        providing a valid count.
        """
        vals = [int(v) for v in values]
        if not (self._min_count <= len(vals) <= self._max_count):
            raise ValueError(
                f"setValue: got {len(vals)} values; expected "
                f"{self._min_count}–{self._max_count}"
            )

        # Tear down all existing spinboxes + "or" labels.
        while self._boxes:
            self._remove_last_box(emit=False)

        # Add fresh ones with signals blocked, then emit once at the end.
        for v in vals:
            self._add_box(initial=v, emit=False)
        self._refresh_buttons()
        self.changed.emit(self.value())

    # ---- Button handlers ----------------------------------------------

    def _on_add_clicked(self) -> None:
        if len(self._boxes) >= self._max_count:
            return
        # Per design: new spinbox starts at min(last + 24, maximum).
        last = self._boxes[-1].value() if self._boxes else self._min
        initial = min(last + 24, self._max)
        initial = max(initial, self._min)
        self._add_box(initial=initial, emit=True)

    def _on_remove_clicked(self) -> None:
        if len(self._boxes) <= self._min_count:
            return
        self._remove_last_box(emit=True)

    # ---- Internals -----------------------------------------------------

    def _add_box(self, *, initial: int, emit: bool) -> None:
        """Append a spinbox (and a preceding 'or' label when not first)."""
        box = QSpinBox()
        box.setRange(self._min, self._max)
        box.setSingleStep(self._step)
        with QSignalBlocker(box):
            box.setValue(int(initial))
        box.valueChanged.connect(self._on_box_changed)

        # Insert just before the [+] button. If there's already at least
        # one spinbox, also insert an "or" label before this new spinbox.
        insert_at = self._layout.indexOf(self.btn_add)
        if self._boxes:
            or_lbl = QLabel("or")
            or_lbl.setStyleSheet("color: #666; font-size: 11px;")
            self._layout.insertWidget(insert_at, or_lbl)
            insert_at += 1
            self._or_labels.append(or_lbl)
        self._layout.insertWidget(insert_at, box)
        self._boxes.append(box)

        self._refresh_buttons()
        if emit:
            self.changed.emit(self.value())

    def _remove_last_box(self, *, emit: bool) -> None:
        """Remove the last spinbox (and the 'or' label that precedes it)."""
        if not self._boxes:
            return
        box = self._boxes.pop()
        self._layout.removeWidget(box)
        box.deleteLater()
        # The "or" label list mirrors the gaps between boxes — pop the
        # last one if there's still at least one box left.
        if self._or_labels:
            or_lbl = self._or_labels.pop()
            self._layout.removeWidget(or_lbl)
            or_lbl.deleteLater()

        self._refresh_buttons()
        if emit:
            self.changed.emit(self.value())

    def _on_box_changed(self, _val: int) -> None:
        self.changed.emit(self.value())

    def _refresh_buttons(self) -> None:
        n = len(self._boxes)
        self.btn_add.setEnabled(n < self._max_count)
        self.btn_remove.setEnabled(n > self._min_count)
