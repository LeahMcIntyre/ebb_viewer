"""Smoke tests for the Sleep section of the Finalize page."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry


def _make_page(qapp, tmp_path: Path):
    from ebb_viewer.pages.finalize import FinalizePage

    return FinalizePage(project_root=tmp_path)


def _seed(tmp_path: Path, sleep_qc: dict[str, str | None]) -> None:
    m = Manifest(tmp_path)
    for animal_id, status in sleep_qc.items():
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id,
            preprocessed_edf=f"{animal_id}_PREPROCESSED.edf",
            has_spindle=True,
            sleep_qc=status,
        )
    m.save()


def test_sleep_status_all_accepted(qapp, tmp_path: Path):
    _seed(tmp_path, {"AM001": "ok"})
    page = _make_page(qapp, tmp_path)
    page._refresh_sleep_section()
    assert "✓" in page._sleep_status_lbl.text()
    assert page._btn_export_sleep.isEnabled()


def test_sleep_status_flags_missing(qapp, tmp_path: Path):
    _seed(
        tmp_path,
        {"AM001": "ok", "AM002": "needs_review"},
    )
    page = _make_page(qapp, tmp_path)
    page._refresh_sleep_section()
    assert "⚠" in page._sleep_status_lbl.text()
    assert "AM002" in page._sleep_status_lbl.text()
    # Still exportable — one animal is accepted.
    assert page._btn_export_sleep.isEnabled()


def test_sleep_export_disabled_when_none_accepted(qapp, tmp_path: Path):
    _seed(tmp_path, {"AM001": "needs_review"})
    page = _make_page(qapp, tmp_path)
    page._refresh_sleep_section()
    assert not page._btn_export_sleep.isEnabled()


def test_sleep_export_writes_bundle(qapp, tmp_path: Path):
    per_hr = 3600 // 4
    csv_path = tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_run.csv"
    csv_path.parent.mkdir(parents=True)
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rawstate", "final_state"])
        for s in ["w"] * (24 * per_hr):
            w.writerow([s, s])
    (tmp_path / "standard").mkdir()
    (tmp_path / "standard" / "AM001_PREPROCESSED.edf").write_bytes(b"")
    _seed(tmp_path, {"AM001": "ok"})

    page = _make_page(qapp, tmp_path)
    fake_start = datetime(2024, 1, 1, 6, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ), patch("ebb_viewer.pages.finalize.QMessageBox.information"):
        page._on_export_sleep()

    out = tmp_path / "sleep_export"
    assert (out / "sleep_export.xlsx").exists()
    assert (out / "chosen_csvs" / "AM001_run.csv").exists()


def test_finalize_marks_excluded_animals_in_the_sealed_pkl(qapp, tmp_path: Path):
    import pickle

    import numpy as np
    from PyQt6.QtWidgets import QMessageBox

    _seed(tmp_path, {"AM001": "ok", "AM002": "ok"})
    m = Manifest.load(tmp_path)
    m.exclude_sleep_qc("AM002", "signal lost")
    psd_dir = tmp_path / "psd" / "default"
    psd_dir.mkdir(parents=True)
    recs = [
        {"path": Path(f"/d/{a}_x_PROCESSED.edf"), "freqs": np.array([1.0]), "psd": np.array([[1.0]])}
        for a in ("AM001", "AM002")
    ]
    with open(psd_dir / "psds_LFC_RSC.pkl", "wb") as f:
        pickle.dump(recs, f)

    page = _make_page(qapp, tmp_path)
    with patch.object(QMessageBox, "information") as info, patch(
        "ebb_viewer.pages.finalize.confirm_unfinished_swd_review", return_value=True
    ):
        page._on_finalize("default")

    with open(psd_dir / "psds_final.pkl", "rb") as f:
        final = pickle.load(f)
    assert [(r["excluded"], r["exclusion_reason"]) for r in final] == [(False, ""), (True, "signal lost")]
    message = info.call_args.args[2]
    assert "AM002" in message and "excluded_animals.csv" in message
    assert (psd_dir / "excluded_animals.csv").exists()


def test_run_card_lists_excluded_animals_before_sealing(qapp, tmp_path: Path):
    from PyQt6.QtWidgets import QLabel

    _seed(tmp_path, {"AM001": "ok", "AM002": "ok"})
    Manifest.load(tmp_path).exclude_sleep_qc("AM002", "signal lost")
    run_dir = tmp_path / "psd" / "default"
    run_dir.mkdir(parents=True)
    (run_dir / "psd_params.json").write_text("{}")
    (run_dir / "psds_LFC_RSC.pkl").touch()

    page = _make_page(qapp, tmp_path)
    page._refresh()
    texts = [lbl.text() for lbl in page.findChildren(QLabel)]
    assert any("1 excluded animal(s) are kept in psds_final.pkl" in t and "AM002" in t for t in texts)
