"""Smoke tests for the Sleep section of the Finalize page."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry, RunEntry


def _make_page(qapp, tmp_path: Path):
    from ebb_viewer.pages.finalize import FinalizePage

    return FinalizePage(project_root=tmp_path)


def _seed(tmp_path: Path, runs: dict[str, dict[str, RunEntry]]) -> None:
    m = Manifest(tmp_path)
    for animal_id, combo_runs in runs.items():
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id,
            preprocessed_edf=f"{animal_id}_PREPROCESSED.edf",
            runs=combo_runs,
        )
    m.save()


def test_sleep_status_all_accepted(qapp, tmp_path: Path):
    _seed(tmp_path, {"AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")}})
    page = _make_page(qapp, tmp_path)
    page._refresh_sleep_section()
    assert "✓" in page._sleep_status_lbl.text()
    assert page._btn_export_sleep.isEnabled()


def test_sleep_status_flags_missing(qapp, tmp_path: Path):
    _seed(
        tmp_path,
        {
            "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
            "AM002": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
        },
    )
    page = _make_page(qapp, tmp_path)
    page._refresh_sleep_section()
    assert "⚠" in page._sleep_status_lbl.text()
    assert "AM002" in page._sleep_status_lbl.text()
    # Still exportable — one animal is accepted.
    assert page._btn_export_sleep.isEnabled()


def test_sleep_export_disabled_when_none_accepted(qapp, tmp_path: Path):
    _seed(tmp_path, {"AM001": {"LFC_RSC": RunEntry(sleep_qc="needs_review")}})
    page = _make_page(qapp, tmp_path)
    page._refresh_sleep_section()
    assert not page._btn_export_sleep.isEnabled()


def test_sleep_export_writes_bundle(qapp, tmp_path: Path):
    per_hr = 3600 // 4
    csv_path = tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_run.csv"
    csv_path.parent.mkdir(parents=True)
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rawstate"])
        for s in ["w"] * (24 * per_hr):
            w.writerow([s])
    (tmp_path / "standard").mkdir()
    (tmp_path / "standard" / "AM001_PREPROCESSED.edf").write_bytes(b"")
    _seed(tmp_path, {"AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")}})

    page = _make_page(qapp, tmp_path)
    fake_start = datetime(2024, 1, 1, 6, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ), patch("ebb_viewer.pages.finalize.QMessageBox.information"):
        page._on_export_sleep()

    out = tmp_path / "sleep_export"
    assert (out / "sleep_export.xlsx").exists()
    assert (out / "chosen_csvs" / "AM001_run.csv").exists()
