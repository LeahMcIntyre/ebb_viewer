"""Tests for the no-scroll spinbox subclasses."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent

from ebb_viewer.widgets.no_scroll_spinbox import NoScrollDoubleSpinBox, NoScrollSpinBox


def _wheel_event(angle_delta: int) -> QWheelEvent:
    """Construct a synthetic wheel event."""
    return QWheelEvent(
        QPointF(0, 0),  # pos
        QPointF(0, 0),  # globalPos
        QPoint(0, 0),  # pixelDelta
        QPoint(0, angle_delta),  # angleDelta — 120 = one notch
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,  # inverted
    )


def test_no_scroll_spinbox_ignores_wheel(qapp):
    box = NoScrollSpinBox()
    box.setRange(0, 100)
    box.setValue(50)
    box.wheelEvent(_wheel_event(120))
    assert box.value() == 50
    box.wheelEvent(_wheel_event(-120))
    assert box.value() == 50


def test_no_scroll_double_spinbox_ignores_wheel(qapp):
    box = NoScrollDoubleSpinBox()
    box.setRange(0.0, 10.0)
    box.setValue(2.5)
    box.wheelEvent(_wheel_event(120))
    assert box.value() == 2.5
    box.wheelEvent(_wheel_event(-120))
    assert box.value() == 2.5


def test_no_scroll_spinbox_still_responds_to_setValue(qapp):
    """Sanity: blocking wheel doesn't break the normal value-setting API."""
    box = NoScrollSpinBox()
    box.setRange(0, 100)
    box.setValue(50)
    box.setValue(75)
    assert box.value() == 75


def test_no_scroll_spinbox_still_responds_to_stepUp(qapp):
    """Sanity: the up/down step API still works (used by the spinbox arrow buttons)."""
    box = NoScrollSpinBox()
    box.setRange(0, 100)
    box.setValue(50)
    box.stepUp()
    assert box.value() == 51
    box.stepDown()
    assert box.value() == 50
