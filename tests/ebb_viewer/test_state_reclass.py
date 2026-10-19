import numpy as np
import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from ebb.process.nrem_reclass import NremReclass
from ebb_viewer.edf_viewer import mask_builder
from ebb_viewer.edf_viewer.mask_builder import load_reclassified_state_masks
from ebb_viewer.edf_viewer.masks import Mask, MaskSet
from ebb_viewer.edf_viewer.state_legend import ReclassPill


def _fake_result(final: list[str], gate: bool = False) -> NremReclass:
    arr = np.array(final)
    return NremReclass(arr, arr, arr, gate, 0, 0)


def test_reclassified_masks_expand_final_state_per_epoch(monkeypatch):
    fs = 10
    monkeypatch.setattr(
        mask_builder, "reclassify_file", lambda *a, **k: _fake_result(["w", "n", "r", "w"])
    )

    masks, result = load_reclassified_state_masks("x.csv", "x.edf", fs)

    epoch = fs * 4
    assert masks.get("wake").spans == [(0, epoch), (3 * epoch, 4 * epoch)]
    assert masks.get("nrem").spans == [(epoch, 2 * epoch)]
    assert masks.get("rem").spans == [(2 * epoch, 3 * epoch)]
    assert result.gate_applied is False


def test_reclassified_masks_forward_radius(monkeypatch):
    seen = {}

    def fake(csv, edf, *, radius):
        seen["radius"] = radius
        return _fake_result(["w"])

    monkeypatch.setattr(mask_builder, "reclassify_file", fake)
    load_reclassified_state_masks("x.csv", "x.edf", 10, radius=3)
    assert seen["radius"] == 3


@pytest.fixture
def pill(qapp):
    return ReclassPill()


def _click(w: ReclassPill) -> None:
    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(w.rect().center()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseReleaseEvent(ev)


def test_pill_click_emits_toggle_when_available(pill):
    pill.set_available(True)
    got = []
    pill.toggled.connect(got.append)

    _click(pill)
    _click(pill)

    assert got == [True, False]


def test_pill_click_ignored_when_unavailable(pill):
    got = []
    pill.toggled.connect(got.append)
    _click(pill)
    assert got == []


def test_pill_set_checked_does_not_emit(pill):
    pill.set_available(True)
    got = []
    pill.toggled.connect(got.append)
    pill.set_checked(True)
    assert got == []


def test_pill_sits_right_of_state_bar_without_moving_the_plots(qapp):
    from datetime import datetime

    from ebb_viewer.edf_viewer.trace_view import TraceView

    fs = 250
    tv = TraceView(
        data=np.zeros((2, fs * 60)),
        fs=fs,
        start_time=datetime(2025, 1, 1),
        ch_names=("A", "B"),
    )
    tv.resize(900, 400)
    ms = MaskSet()
    ms.add(Mask(name="wake", color=(1, 2, 3, 255)))
    tv.set_state_masks(ms)
    tv.show()
    qapp.processEvents()

    bar_right = tv.state_bar.mapTo(tv, tv.state_bar.rect().topRight()).x()
    plot_right = tv.plots[0].mapTo(tv, tv.plots[0].rect().topRight()).x()
    assert tv.reclass_pill.x() >= bar_right
    assert plot_right <= bar_right + 1
