"""Tests for the Drink Mask page: animal table, readiness checklist and Apply button."""

from __future__ import annotations

from pathlib import Path

from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry
from ebb_viewer.pipeline.naming import drink_mask_rel


def _make_page(qapp, tmp_path: Path):
    from ebb_viewer.pages.drink_mask import DrinkMaskPage

    page = DrinkMaskPage(project_root=tmp_path)
    page._refresh_run_selector()
    return page


def _project(tmp_path: Path, animals: dict[str, str], *, masks: tuple[str, ...] = ()):
    """Project with one PSD run 'r1'; ``animals`` maps id -> psd_status for r1."""
    (tmp_path / "standard").mkdir()
    psd_params.save(tmp_path, "r1", {"fs": 250, "channels": [0, 1, 2], "states": ["wake"]})
    m = Manifest(tmp_path)
    for animal, status in animals.items():
        m._entries[animal] = ManifestEntry(
            animal_id=animal,
            preprocessed_edf=f"{animal}_PREPROCESSED.edf",
            has_spindle=True,
            sleep_qc="ok",
            psd_status={"r1": status},
        )
    m.save()
    for animal in masks:
        path = tmp_path / drink_mask_rel(animal)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def test_table_lists_flagged_and_applied_animals(qapp, tmp_path: Path):
    _project(
        tmp_path,
        {"AM001": "needs_drink_mask", "AM002": "needs_drink_mask", "AM003": "drink_mask_applied"},
        masks=("AM001", "AM003"),
    )
    page = _make_page(qapp, tmp_path)
    rows = [
        (
            page._table.item(r, 0).text(),
            page._table.item(r, 1).text(),
            page._table.item(r, 2).text(),
        )
        for r in range(page._table.rowCount())
    ]
    assert rows == [
        ("AM001", "needs mask", "✓ found"),
        ("AM002", "needs mask", "✗ missing"),
        ("AM003", "mask applied — verify", "✓ found"),
    ]


def test_apply_enabled_when_flagged_animal_has_a_mask(qapp, tmp_path: Path):
    _project(tmp_path, {"AM001": "needs_drink_mask", "AM002": "needs_drink_mask"}, masks=("AM001",))
    page = _make_page(qapp, tmp_path)
    assert page.btn_apply.isEnabled()
    assert "(1)" in page.btn_apply.text()
    # An animal without a file only warns: it is skipped, not blocking.
    assert "AM002" in page._checks_lbl.text()


def test_apply_blocked_without_any_mask_file(qapp, tmp_path: Path):
    _project(tmp_path, {"AM001": "needs_drink_mask"})
    page = _make_page(qapp, tmp_path)
    assert not page.btn_apply.isEnabled()
    assert "No mask files yet" in page._checks_lbl.text()


def test_apply_blocked_when_nothing_is_flagged(qapp, tmp_path: Path):
    _project(tmp_path, {"AM001": "ok"})
    page = _make_page(qapp, tmp_path)
    assert not page.btn_apply.isEnabled()
    assert page._fix_page == "psd_review"
    assert page._table.isHidden()


def test_ambiguous_offset_csvs_block_apply(qapp, tmp_path: Path):
    """Two CSVs used to be silently ignored; now Apply is blocked until only one is left."""
    _project(tmp_path, {"AM001": "needs_drink_mask"}, masks=("AM001",))
    d = tmp_path / "drink_masks"
    (d / "a.csv").write_text("Animal,Offset\n")
    (d / "b.csv").write_text("Animal,Offset\n")
    page = _make_page(qapp, tmp_path)
    assert not page.btn_apply.isEnabled()
    assert "keep only one" in page._checks_lbl.text()


def test_invalid_offset_csv_blocks_apply(qapp, tmp_path: Path):
    _project(tmp_path, {"AM001": "needs_drink_mask"}, masks=("AM001",))
    (tmp_path / "drink_masks" / "offsets.csv").write_text("Mouse,Seconds\n")
    page = _make_page(qapp, tmp_path)
    assert not page.btn_apply.isEnabled()


def test_valid_offset_csv_keeps_apply_enabled(qapp, tmp_path: Path):
    _project(tmp_path, {"AM001": "needs_drink_mask"}, masks=("AM001",))
    (tmp_path / "drink_masks" / "offsets.csv").write_text("Animal,Offset\nAM001,2\n")
    page = _make_page(qapp, tmp_path)
    assert page.btn_apply.isEnabled()


def test_missing_psd_params_blocks_apply_and_points_to_psd_compute(qapp, tmp_path: Path):
    (tmp_path / "standard").mkdir()
    page = _make_page(qapp, tmp_path)
    assert not page.btn_apply.isEnabled()
    assert page._fix_page == "psd_compute"


def test_log_hidden_until_first_message(qapp, tmp_path: Path):
    page = _make_page(qapp, tmp_path)
    assert page.log_box.isHidden()
    page._log("hello")
    assert not page.log_box.isHidden()
