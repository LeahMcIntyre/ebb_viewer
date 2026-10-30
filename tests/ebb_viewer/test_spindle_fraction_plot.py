"""Tests for the Sleep QC Spindle mask view (``widgets/spindle_fraction_plot.py``)."""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from ebb_viewer.pages.sleep_qc_visualizer import SleepQCGridPage
from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry
from ebb_viewer.widgets.spindle_fraction_plot import SpindleFractionPlot, animal_percent_text


def _frac_df() -> pd.DataFrame:
    rows = []
    for animal, fracs in {
        "A1": (0.1, 0.05, 0.0, 0.07),
        "A2": (0.3, 0.2, float("nan"), 0.25),
    }.items():
        for state, f in zip(["Wake", "NREM", "REM", "Total"], fracs, strict=True):
            rows.append({"mouse_id": animal, "state": state, "fraction": f})
    return pd.DataFrame(rows)


def test_animal_percent_text_lists_every_state_as_percent():
    df = _frac_df()
    assert animal_percent_text(df, "A1") == "Wake 10.0% · NREM 5.0% · REM 0.0% · Total 7.0%"
    assert "REM n/a" in animal_percent_text(df, "A2")


def test_plot_draws_and_click_shows_that_animals_percentages(qapp):
    plot = SpindleFractionPlot()
    plot.set_data(_frac_df(), title="x", gated={"A2"})
    assert plot._strip.isHidden()

    class Spot:
        def data(self):
            return "A2"

    seen: list[str] = []
    plot.animal_clicked.connect(seen.append)
    plot._on_dot_clicked(None, [Spot()], None)
    assert not plot._strip.isHidden()
    assert "A2" in plot._strip_lbl.text() and "Wake 30.0%" in plot._strip_lbl.text()
    assert seen == ["A2"]


def test_plot_handles_no_data(qapp):
    plot = SpindleFractionPlot()
    plot.set_data(None)
    plot.set_data(pd.DataFrame(columns=["mouse_id", "state", "fraction"]))


def _write_csv(path: Path, epochs: list[tuple[str, float]]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rawstate", "noise_probs", "final_state"])
        for state, prob in epochs:
            w.writerow([state, prob, state])


def test_page_spindle_mask_view_switches_and_computes_percentages(qapp, tmp_path: Path):
    m = Manifest(tmp_path)
    m._entries["A1"] = ManifestEntry(animal_id="A1", preprocessed_edf="x.edf", has_spindle=True)
    m.save()
    out = tmp_path / "spindle_outputs" / m.combo
    out.mkdir(parents=True)
    _write_csv(out / "A1_labels.csv", [("w", 0.9), ("w", 0.1), ("n", 0.1), ("n", 0.1)])

    page = SleepQCGridPage(project_root=tmp_path)
    page._data = (None, None, None, None)  # the view needs only the CSVs, not the sleep tables
    page._set_view("mask")

    assert page.btn_spindle.isChecked()
    assert not page.btn_overview.isChecked() and not page.btn_view_sleep.isChecked()
    assert not page._frac_widget.isHidden() and page.grid.isHidden()
    df = page._get_frac_df()
    wake = df[(df["mouse_id"] == "A1") & (df["state"] == "Wake")]["fraction"].iloc[0]
    total = df[(df["mouse_id"] == "A1") & (df["state"] == "Total")]["fraction"].iloc[0]
    assert wake == 0.5 and total == 0.25

    page._set_view("sleep")
    assert page._frac_widget.isHidden() and not page.grid.isHidden()
