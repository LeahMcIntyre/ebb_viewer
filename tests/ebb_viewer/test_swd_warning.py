"""Warnings shown while SWD review is on but unfinished: helper, dialog, Sleep QC label, pages."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry
from ebb_viewer.pipeline.swd_review import find_swd_file, swd_review_gaps
from ebb_viewer.widgets.swd_warning import confirm_unfinished_swd_review


def _project(tmp_path: Path, animals: dict[str, tuple[int, int | None]], *, enabled=True, swd=True,
             waived=()):
    """animals: id -> (reviewed, total) SWD progress; swd=False leaves them without SWD files."""
    (tmp_path / "swd").mkdir(parents=True, exist_ok=True)
    m = Manifest(tmp_path)
    for animal, (reviewed, total) in animals.items():
        m._entries[animal] = ManifestEntry(
            animal, f"standard/{animal}_PREPROCESSED.edf", has_spindle=True,
            swd_reviewed=reviewed, swd_total=total, swd_waived=animal in waived,
        )
        if swd:
            (tmp_path / "swd" / f"{animal}.mat").touch()
    m.swd_review_enabled = enabled
    m.save()
    return Manifest.load(tmp_path)


def test_find_swd_file_moved_to_pipeline_still_matches_real_names(tmp_path):
    (tmp_path / "swd").mkdir()
    (tmp_path / "swd" / "Mice-1256.mat").touch()
    assert find_swd_file(tmp_path, "Mice-1256").name == "Mice-1256.mat"


def test_no_gaps_when_review_is_off(tmp_path):
    m = _project(tmp_path, {"A1": (0, 5)}, enabled=False)
    assert not swd_review_gaps(tmp_path, m)
    m = _project(tmp_path / "b", {"A1": (0, 5)}, enabled=False, swd=False)
    assert not swd_review_gaps(tmp_path / "b", m)


def test_not_started_and_in_progress_are_unfinished_done_is_not(tmp_path):
    m = _project(tmp_path, {"A1": (0, 5), "A2": (2, 5), "A3": (5, 5), "A4": (0, None)})
    gaps = swd_review_gaps(tmp_path, m)
    assert gaps.unfinished == ["A1", "A2", "A4"] and gaps.missing == []


def test_an_empty_swd_file_needs_no_review(tmp_path):
    m = _project(tmp_path, {"A1": (0, 0)})  # empty .mat -> zero SWD epochs
    assert not swd_review_gaps(tmp_path, m)


def test_animals_without_an_swd_file_are_gaps_until_confirmed(tmp_path):
    m = _project(tmp_path, {"A1": (0, None), "A2": (0, None)}, swd=False, waived=("A2",))
    gaps = swd_review_gaps(tmp_path, m)
    assert gaps.missing == ["A1"]  # A2 was confirmed as needing none
    assert gaps.unfinished == []


def test_animal_filter_narrows_the_check(tmp_path):
    m = _project(tmp_path, {"A1": (0, 5), "A2": (0, 5)})
    assert swd_review_gaps(tmp_path, m, {"A2"}).unfinished == ["A2"]


def test_dialog_skipped_when_there_are_no_gaps(qapp, tmp_path):
    _project(tmp_path, {"A1": (5, 5)})
    with patch("ebb_viewer.widgets.swd_warning.QMessageBox.question") as q:
        assert confirm_unfinished_swd_review(None, tmp_path) is True
    assert not q.called


@pytest.mark.parametrize("answer,expected", [("Yes", True), ("Cancel", False)])
def test_dialog_lists_animals_and_returns_the_choice(qapp, tmp_path, answer, expected):
    from PyQt6.QtWidgets import QMessageBox

    _project(tmp_path, {"A1": (1, 5), "A2": (0, 5)})
    (tmp_path / "swd" / "A2.mat").unlink()  # A2 also has no SWD file
    reply = getattr(QMessageBox.StandardButton, answer)
    with patch("ebb_viewer.widgets.swd_warning.QMessageBox.question", return_value=reply) as q:
        assert confirm_unfinished_swd_review(None, tmp_path) is expected
    text = q.call_args.args[2]
    assert "A1" in text and "A2" in text
    assert "No SWD file" in text and "not finished" in text
    assert q.call_args.args[4] == QMessageBox.StandardButton.Cancel  # Cancel is the default


def test_sleep_qc_shows_label_only_while_unfinished(qapp, tmp_path):
    from ebb_viewer.pages.sleep_qc_visualizer import SleepQCGridPage

    _project(tmp_path, {"A1": (1, 5), "A2": (5, 5)})
    page = SleepQCGridPage(project_root=tmp_path)
    assert not page.lbl_swd.isHidden()
    assert "1 not finished" in page.lbl_swd.text() and "A1" in page.lbl_swd.toolTip()

    m = Manifest.load(tmp_path)
    m.set_swd_progress("A1", 5, 5)
    page._refresh_manifest()
    assert page.lbl_swd.isHidden()


def test_sleep_qc_label_mentions_animals_without_an_swd_file(qapp, tmp_path):
    from ebb_viewer.pages.sleep_qc_visualizer import SleepQCGridPage

    _project(tmp_path, {"A1": (5, 5), "A2": (0, None)}, waived=())
    (tmp_path / "swd" / "A2.mat").unlink()
    page = SleepQCGridPage(project_root=tmp_path)
    assert "1 without an SWD file" in page.lbl_swd.text()
    assert "No SWD file: A2" in page.lbl_swd.toolTip()


def test_sleep_qc_hides_label_when_review_is_off(qapp, tmp_path):
    from ebb_viewer.pages.sleep_qc_visualizer import SleepQCGridPage

    _project(tmp_path, {"A1": (0, 5)}, enabled=False)
    assert SleepQCGridPage(project_root=tmp_path).lbl_swd.isHidden()


def test_finalize_sleep_export_stops_when_user_cancels(qapp, tmp_path):
    from ebb_viewer.pages.finalize import FinalizePage

    _project(tmp_path, {"A1": (0, 5)})
    page = FinalizePage(project_root=tmp_path)
    with (
        patch("ebb_viewer.pages.finalize.confirm_unfinished_swd_review", return_value=False),
        patch("ebb_viewer.pipeline.sleep_finalize.build_sleep_export") as build,
    ):
        page._on_export_sleep()
    assert not build.called


def test_psd_run_stops_when_user_cancels(qapp, tmp_path):
    from ebb_viewer.pages.psds import PSDPage

    m = _project(tmp_path, {"A1": (0, 5)})
    m._entries["A1"].sleep_qc = "ok"
    m.save()
    (tmp_path / "standard").mkdir()
    out = tmp_path / "spindle_outputs" / m.combo
    out.mkdir(parents=True)
    (out / "A1_x.csv").write_text("state,final_state\nw,w\n")
    page = PSDPage(project_root=tmp_path)

    with (
        patch("ebb_viewer.pages.psds.confirm_unfinished_swd_review", return_value=False) as confirm,
        patch("ebb_viewer.pages.psds.QMessageBox.warning"),
    ):
        page._run_pipeline_clicked()

    assert confirm.called  # reached the SWD check, then stopped
    assert not (tmp_path / "psd").exists() or not any((tmp_path / "psd").iterdir())
