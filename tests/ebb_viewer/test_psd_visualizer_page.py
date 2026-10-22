"""Tests for the PSD Visualizer's pass switch (review PSDs / verify drink masks)."""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np

from ebb_viewer.pages.psd_visualizer import REVIEW, VERIFY, PSDVisualizer, default_pass
from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import (
    DrinkLoopCounts,
    Manifest,
    ManifestEntry,
    psd_drink_path,
    psd_path,
)

COMBO = "LFC_RSC"


def _write_pkl(path: Path, animals: list[str], *, drink: bool) -> None:
    freqs = np.arange(0.5, 100, 0.5)
    records = [
        {
            "path": f"{a}_x.edf",
            "freqs": freqs,
            "psd": np.ones((2, len(freqs))),
            "behavior": ("threshold", "wake"),
            "channels": [0, 1],
            "used_artifact": False,
            "used_drink": drink,
        }
        for a in animals
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(records, f)


def _project(tmp_path: Path, statuses: dict[str, str | None], *, drink_pkl: bool) -> None:
    """One run 'r1'; ``statuses`` maps animal -> psd_status (None = not reviewed yet)."""
    psd_params.save(tmp_path, "r1", {"fs": 250, "channels": [0, 1], "states": ["wake"]})
    m = Manifest(tmp_path)
    for animal, status in statuses.items():
        m._entries[animal] = ManifestEntry(
            animal_id=animal,
            preprocessed_edf=f"{animal}_PREPROCESSED.edf",
            has_spindle=True,
            sleep_qc="ok",
            psd_status={"r1": status} if status else {},
        )
    m.save()
    animals = list(statuses)
    _write_pkl(psd_path(COMBO, tmp_path, "r1"), animals, drink=False)
    if drink_pkl:
        _write_pkl(psd_drink_path(COMBO, tmp_path, "r1"), animals, drink=True)


def _open(qapp, tmp_path: Path) -> PSDVisualizer:
    page = PSDVisualizer(project_root=tmp_path)
    page._refresh_run_selector(auto_plot=True)
    return page


def _listed(page: PSDVisualizer) -> list[str]:
    cmb = page.psd_page.cmb_animal
    return [cmb.itemText(i) for i in range(cmb.count())]


def test_default_pass_is_verify_only_when_everything_is_reviewed():
    def counts(unreviewed, to_verify):
        return DrinkLoopCounts(unreviewed, 0, 0, to_verify, 0)

    assert default_pass(counts(0, 2), True) == VERIFY
    assert default_pass(counts(1, 2), True) == REVIEW  # still PSDs to review: stay in pass 1
    assert default_pass(counts(0, 2), False) == REVIEW  # no drink pkl to show
    assert default_pass(counts(0, 0), True) == REVIEW


def test_unreviewed_animals_keep_the_review_pass_even_when_a_drink_pkl_exists(qapp, tmp_path: Path):
    """Regression: the drink pkl used to win whenever it existed, hiding pass 1."""
    _project(tmp_path, {"AM001": None, "AM002": "drink_mask_applied"}, drink_pkl=True)
    page = _open(qapp, tmp_path)
    assert page.btn_review.isChecked()
    assert page.psd_page is not None and not page.psd_page.drink_review


def test_verify_pass_opens_when_everything_is_reviewed_and_lists_only_animals_to_verify(
    qapp, tmp_path: Path
):
    _project(
        tmp_path,
        {"AM001": "ok", "AM002": "drink_mask_applied", "AM003": "drink_mask_applied"},
        drink_pkl=True,
    )
    page = _open(qapp, tmp_path)
    assert page.btn_verify.isChecked()
    assert page.psd_page.drink_review
    assert [k.replace("_drink", "") for k in _listed(page)] == ["AM002", "AM003"]
    page.psd_page.chk_show_all.setChecked(True)
    assert len(_listed(page)) == 3


def test_buttons_carry_the_counts(qapp, tmp_path: Path):
    _project(
        tmp_path, {"AM001": None, "AM002": "ok", "AM003": "drink_mask_applied"}, drink_pkl=True
    )
    page = _open(qapp, tmp_path)
    assert "(1 left)" in page.btn_review.text()
    assert "(1 to check)" in page.btn_verify.text()


def test_verify_is_disabled_without_a_drink_pkl(qapp, tmp_path: Path):
    _project(tmp_path, {"AM001": None}, drink_pkl=False)
    page = _open(qapp, tmp_path)
    assert not page.btn_verify.isEnabled()
    assert page.btn_review.isEnabled()


def test_user_can_switch_passes(qapp, tmp_path: Path):
    _project(tmp_path, {"AM001": "ok", "AM002": "drink_mask_applied"}, drink_pkl=True)
    page = _open(qapp, tmp_path)
    assert page.psd_page.drink_review
    page.btn_review.click()
    assert not page.psd_page.drink_review
    page._refresh_run_selector(auto_plot=True)  # coming back to the page keeps the choice
    assert not page.psd_page.drink_review


def test_flagged_animals_point_to_the_drink_mask_page(qapp, tmp_path: Path):
    _project(tmp_path, {"AM001": "ok", "AM002": "needs_drink_mask"}, drink_pkl=False)
    page = _open(qapp, tmp_path)
    assert page._next_page == "drink_mask"
    assert not page._next_frame.isHidden()


def test_verifying_marks_the_animal_ok(qapp, tmp_path: Path):
    _project(tmp_path, {"AM001": "drink_mask_applied"}, drink_pkl=True)
    page = _open(qapp, tmp_path)
    page.psd_page._flag_psd_ok()
    assert Manifest.load(tmp_path).get("AM001").psd_status == {"r1": "ok"}
    assert "(0 to check)" in page.btn_verify.text()


def test_redo_sends_the_animal_back_to_needs_mask(qapp, tmp_path: Path):
    _project(tmp_path, {"AM001": "drink_mask_applied"}, drink_pkl=True)
    page = _open(qapp, tmp_path)
    page.psd_page._flag_drink_mask()
    assert Manifest.load(tmp_path).get("AM001").psd_status == {"r1": "needs_drink_mask"}
