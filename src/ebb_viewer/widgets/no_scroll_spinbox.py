"""QSpinBox / QDoubleSpinBox variants that ignore mouse-wheel events.

Default Qt behaviour responds to wheel scrolling, which causes accidental
value changes when a user scrolls a form containing spinboxes. These
subclasses drop wheel events entirely; values change only via typing,
arrow keys, or the up/down step buttons.
"""

from __future__ import annotations

from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QDoubleSpinBox, QSpinBox


class NoScrollSpinBox(QSpinBox):
    """Integer spinbox that ignores mouse wheel events."""

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 — Qt API
        event.ignore()


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    """Float spinbox that ignores mouse wheel events."""

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 — Qt API
        event.ignore()
