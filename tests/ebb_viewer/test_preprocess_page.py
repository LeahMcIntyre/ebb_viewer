"""Tests for ``pages/preprocess.py``: the warning for uncombined restart chunks."""

from __future__ import annotations

from pathlib import Path

from ebb_viewer.pages.preprocess import PreprocessPage, duplicate_animal_edfs


def test_duplicate_animal_edfs_finds_animals_with_several_files():
    paths = [
        Path("AM001_P096_x.edf"),
        Path("AM001_P098_x.edf"),
        Path("AM002_P097_x.edf"),
    ]
    assert duplicate_animal_edfs(paths) == {"AM001": ["AM001_P096_x.edf", "AM001_P098_x.edf"]}


def test_duplicate_animal_edfs_is_empty_when_every_animal_has_one_file():
    assert duplicate_animal_edfs([Path("AM001_a.edf"), Path("AM002_a.edf")]) == {}


def test_page_warns_when_an_animal_has_several_edfs(qapp, tmp_path: Path):
    for name in ("AM001_P096_x.edf", "AM001_P098_x.edf", "AM002_P097_x.edf"):
        (tmp_path / name).write_bytes(b"")
    page = PreprocessPage(project_root=tmp_path)
    page._scan_edfs()
    assert not page._chunk_label.isHidden()
    assert "1 animal has more than one EDF" in page._chunk_label.text()
    assert "AM001" in page._chunk_label.text()


def test_page_has_no_warning_for_one_edf_per_animal(qapp, tmp_path: Path):
    for name in ("AM001_a.edf", "AM002_a.edf"):
        (tmp_path / name).write_bytes(b"")
    page = PreprocessPage(project_root=tmp_path)
    page._scan_edfs()
    assert page._chunk_label.isHidden()
