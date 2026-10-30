"""Tests for ``pages/spindle.py``: the warning before the project combo changes."""

from __future__ import annotations

from pathlib import Path

from ebb_viewer.pages.spindle import combo_change_warning


def _edf(root: Path, combo: str) -> None:
    d = root / "spindle_edfs" / combo
    d.mkdir(parents=True)
    (d / "A001_SPINDLE.edf").touch()


def test_no_warning_for_the_same_combo(tmp_path: Path):
    _edf(tmp_path, "LFC_RSC")
    assert combo_change_warning(tmp_path, "LFC_RSC", "LFC_RSC") is None


def test_no_warning_while_the_current_combo_is_only_the_default(tmp_path: Path):
    assert combo_change_warning(tmp_path, "LFC_RSC", "LFC_LSC") is None


def test_warning_names_both_combos_and_the_manifest_when_work_exists(tmp_path: Path):
    _edf(tmp_path, "LFC_RSC")
    msg = combo_change_warning(tmp_path, "LFC_RSC", "LFC_LSC")
    assert msg and "LFC_RSC" in msg and "LFC_LSC" in msg and "manifest.json" in msg


def test_warning_when_only_outputs_exist(tmp_path: Path):
    d = tmp_path / "spindle_outputs" / "LFC_RSC"
    d.mkdir(parents=True)
    (d / "A001_labels.csv").touch()
    assert combo_change_warning(tmp_path, "LFC_RSC", "RSC_LSC") is not None
