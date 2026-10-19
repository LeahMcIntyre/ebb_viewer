import numpy as np
import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from ebb.process.nrem_reclass import NremReclass
from ebb_viewer.edf_viewer import mask_builder
from ebb_viewer.edf_viewer.mask_builder import load_reclassified_state_masks
from ebb_viewer.edf_viewer.masks import Mask, MaskSet
from ebb_viewer.edf_viewer.state_legend import StateLegend


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
def legend(qapp):
    w = StateLegend()
    ms = MaskSet()
    for name in ("wake", "nrem", "rem"):
        ms.add(Mask(name=name, color=(1, 2, 3, 255)))
    w.rebuild(ms)
    w.resize(w.sizeHint().width() + 20, 20)
    return w


def _click(w: StateLegend, pos: QPoint) -> None:
    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseReleaseEvent(ev)


def test_pill_click_emits_toggle_when_enabled(legend):
    legend.set_reclass_enabled(True)
    got = []
    legend.reclass_toggled.connect(got.append)
    pill = legend._pill_rect(legend.fontMetrics()).center()

    _click(legend, pill)
    _click(legend, pill)

    assert got == [True, False]


def test_pill_click_ignored_when_disabled(legend):
    got = []
    legend.reclass_toggled.connect(got.append)
    _click(legend, legend._pill_rect(legend.fontMetrics()).center())
    assert got == []
