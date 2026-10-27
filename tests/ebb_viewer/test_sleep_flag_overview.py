"""Tests for the Sleep QC flagging overview widget."""

import numpy as np
import pandas as pd
from unittest.mock import MagicMock

from ebb_viewer.widgets.sleep_flag_overview import FlagOverview

BASE = {"nrem_short_h": 2, "dark_bouts_h": 5, "pct_rem": 8, "pct_nrem": 50,
        "pct_wake": 42, "max_bin_rem": 10}
THRESHOLDS = {"nrem_short_h": 6, "dark_bouts_h": 15, "pct_rem": 10, "pct_nrem": 30,
              "pct_wake": 70, "max_bin_rem": 35}


def _table(**overrides) -> pd.DataFrame:
    rows = {"A1": dict(BASE), "A2": dict(BASE), "A3": {**BASE, **overrides}}
    return pd.DataFrame(rows).T.rename_axis("animal")


def _click(w: FlagOverview, animal: str) -> None:
    spots = np.empty(1, dtype=object)  # pyqtgraph hands over an ndarray, not a list
    spots[0] = MagicMock(data=MagicMock(return_value=animal))
    w._on_dot_clicked(None, spots, None)


def test_flagged_animals_lists_metrics_past_thresholds(qapp):
    w = FlagOverview()
    w.set_data(_table(nrem_short_h=8, pct_nrem=20), THRESHOLDS, {})
    assert w.flagged_animals() == {"A3": ["nrem_short_h", "pct_nrem"]}


def test_empty_and_single_animal_tables_do_not_raise(qapp):
    w = FlagOverview()
    w.set_data(None, THRESHOLDS, {})
    w.set_data(pd.DataFrame(columns=list(BASE)), THRESHOLDS, {})
    w.set_data(_table().iloc[:1], THRESHOLDS, {})  # one animal: no box, still a dot


def test_nan_metric_is_skipped(qapp):
    w = FlagOverview()
    w.set_data(_table(max_bin_rem=np.nan), THRESHOLDS, {})
    assert w.flagged_animals() == {}


def test_click_selects_and_flag_button_emits(qapp):
    w = FlagOverview()
    w.set_data(_table(nrem_short_h=8), THRESHOLDS, {})
    got, flagged = [], []
    w.animal_clicked.connect(got.append)
    w.flag_requested.connect(flagged.append)

    _click(w, "A3")
    assert got == ["A3"] and w.selected == "A3"
    assert "nrem_short_h" not in w._strip_lbl.text()  # shows the label, not the key
    assert "Short" in w._strip_lbl.text()
    w._btn_flag.click()
    assert flagged == ["A3"]


def test_flag_button_disabled_when_already_flagged_or_excluded(qapp):
    w = FlagOverview()
    w.set_data(_table(), THRESHOLDS, {"A1": "needs_review", "A2": "excluded"})
    _click(w, "A1")
    assert not w._btn_flag.isEnabled() and "Flagged" in w._btn_flag.text()
    _click(w, "A2")
    assert not w._btn_flag.isEnabled()
    _click(w, "A3")
    assert w._btn_flag.isEnabled()


def test_dismiss_clears_selection(qapp):
    w = FlagOverview()
    w.set_data(_table(), THRESHOLDS, {})
    got = []
    w.animal_clicked.connect(got.append)
    _click(w, "A1")
    w._dismiss()
    assert w.selected is None and got[-1] == ""


def test_each_thresholded_metric_has_a_labelled_line(qapp):
    import pyqtgraph as pg

    w = FlagOverview()
    w.set_data(_table(), THRESHOLDS, {})
    for key, cutoff in THRESHOLDS.items():
        (line,) = [i for i in w._plots[key].items if isinstance(i, pg.InfiniteLine)]
        assert line.value() == cutoff
        assert f"{cutoff:g}" in line.label.textItem.toPlainText()


def test_click_on_overlapping_dots_selects_the_first(qapp):
    """Regression: several dots under the cursor arrive as a multi-element ndarray."""
    w = FlagOverview()
    w.set_data(_table(), THRESHOLDS, {})
    spots = np.empty(2, dtype=object)
    spots[0] = MagicMock(data=MagicMock(return_value="A1"))
    spots[1] = MagicMock(data=MagicMock(return_value="A2"))
    w._on_dot_clicked(None, spots, None)
    assert w.selected == "A1"
