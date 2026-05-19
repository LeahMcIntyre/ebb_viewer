"""Tests for the variable-length TrimToWidget.

Covers the new 1–4 spinbox behaviour: defaults, setValue, add/remove
button semantics, signal emissions, and bound enforcement.
"""

from __future__ import annotations

import pytest

from ebb_viewer.widgets.trim_to_widget import TrimToWidget


def _make(qapp, **kwargs) -> TrimToWidget:
    return TrimToWidget(**kwargs)


# ---- Construction / defaults ---------------------------------------------


def test_default_construction_has_two_spinboxes(qapp):
    w = _make(qapp)
    assert w.value() == [48, 72]
    assert w.btn_add.isEnabled()
    # 2 boxes > min_count(1), so remove is enabled.
    assert w.btn_remove.isEnabled()


def test_invalid_count_bounds_raises(qapp):
    with pytest.raises(ValueError):
        TrimToWidget(min_count=0, max_count=4)
    with pytest.raises(ValueError):
        TrimToWidget(min_count=3, max_count=2)


# ---- setValue ------------------------------------------------------------


def test_setvalue_to_four(qapp):
    w = _make(qapp)
    seen: list[list[int]] = []
    w.changed.connect(lambda v: seen.append(list(v)))
    w.setValue([24, 48, 72, 96])
    assert w.value() == [24, 48, 72, 96]
    assert seen[-1] == [24, 48, 72, 96]
    # At max_count, [+] disabled.
    assert not w.btn_add.isEnabled()
    assert w.btn_remove.isEnabled()


def test_setvalue_to_one(qapp):
    w = _make(qapp)
    w.setValue([60])
    assert w.value() == [60]
    # At min_count, [−] disabled.
    assert not w.btn_remove.isEnabled()
    assert w.btn_add.isEnabled()


def test_setvalue_out_of_bounds_raises(qapp):
    w = _make(qapp)
    with pytest.raises(ValueError):
        w.setValue([])
    with pytest.raises(ValueError):
        w.setValue([1, 2, 3, 4, 5])


# ---- Add button ----------------------------------------------------------


def test_add_button_seeds_at_last_plus_24(qapp):
    w = _make(qapp)  # default [48, 72]
    w.btn_add.click()
    assert w.value() == [48, 72, 96]
    w.btn_add.click()
    assert w.value() == [48, 72, 96, 120]
    # Now at max_count.
    assert not w.btn_add.isEnabled()


def test_add_button_caps_at_maximum(qapp):
    # Default max=168; from 168 the seed would be min(168+24, 168) = 168.
    w = _make(qapp, values=(168,))
    w.btn_add.click()
    assert w.value() == [168, 168]


def test_add_button_disabled_at_max_count(qapp):
    w = _make(qapp, values=(1, 2, 3, 4))
    assert not w.btn_add.isEnabled()
    # Clicking shouldn't change anything (defensive).
    w.btn_add.click()
    assert w.value() == [1, 2, 3, 4]


# ---- Remove button -------------------------------------------------------


def test_remove_button_pops_last(qapp):
    w = _make(qapp)  # [48, 72]
    w.btn_remove.click()
    assert w.value() == [48]
    assert not w.btn_remove.isEnabled()
    # Add re-enables remove.
    w.btn_add.click()
    assert len(w.value()) == 2
    assert w.btn_remove.isEnabled()


def test_remove_button_disabled_at_min_count(qapp):
    w = _make(qapp, values=(48,))
    assert not w.btn_remove.isEnabled()
    w.btn_remove.click()  # no-op
    assert w.value() == [48]


# ---- changed signal ------------------------------------------------------


def test_changed_signal_fires_on_value_edit(qapp):
    w = _make(qapp)
    seen: list[list[int]] = []
    w.changed.connect(lambda v: seen.append(list(v)))
    w._boxes[0].setValue(36)
    assert seen[-1] == [36, 72]


def test_changed_signal_fires_on_add_and_remove(qapp):
    w = _make(qapp)
    seen: list[list[int]] = []
    w.changed.connect(lambda v: seen.append(list(v)))
    w.btn_add.click()
    assert seen[-1] == [48, 72, 96]
    w.btn_remove.click()
    assert seen[-1] == [48, 72]
