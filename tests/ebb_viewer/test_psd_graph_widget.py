"""Tests for PSDGridPage's notch-aware interpolation-range default."""

from __future__ import annotations

from pathlib import Path

from ebb_viewer.pipeline import psd_params
from ebb_viewer.widgets.psd_graph_widget import (
    _DEFAULT_INTERP_RANGE,
    _NOTCH_INTERP_RANGE,
    PSDGridPage,
)


class _FakeStore:
    """Minimal PSDStore-like double: no animals, so PSDGridPage skips render."""

    def animals(self):
        return []

    def states(self, animal):
        return []

    def get(self, animal, state):
        return {}


def _make_page(qapp, *, project_root=None, run_name: str = "default") -> PSDGridPage:
    return PSDGridPage(
        store=_FakeStore(),
        channel_names=["LFC", "RSC"],
        states=["wake"],
        run_name=run_name,
        project_root=project_root,
    )


def test_interp_range_defaults_narrow_with_no_project_root(qapp):
    w = _make_page(qapp, project_root=None)
    assert w.interp_range == _DEFAULT_INTERP_RANGE


def test_interp_range_defaults_narrow_with_no_psd_params_file(qapp, tmp_path: Path):
    """A run predating the notch filter has no psd_params.json — treated as
    apply_notch=False."""
    w = _make_page(qapp, project_root=tmp_path, run_name="default")
    assert w.interp_range == _DEFAULT_INTERP_RANGE


def test_interp_range_widens_when_notch_was_applied(qapp, tmp_path: Path):
    psd_params.save(tmp_path, "notched", {"apply_notch": True})
    w = _make_page(qapp, project_root=tmp_path, run_name="notched")
    assert w.interp_range == _NOTCH_INTERP_RANGE


def test_interp_range_stays_narrow_when_notch_was_not_applied(qapp, tmp_path: Path):
    psd_params.save(tmp_path, "unnotched", {"apply_notch": False})
    w = _make_page(qapp, project_root=tmp_path, run_name="unnotched")
    assert w.interp_range == _DEFAULT_INTERP_RANGE


def test_interp_range_stays_narrow_when_apply_notch_key_missing(qapp, tmp_path: Path):
    """A run saved before apply_notch existed as a key — treated as False."""
    psd_params.save(tmp_path, "legacy", {"nstd": 5})
    w = _make_page(qapp, project_root=tmp_path, run_name="legacy")
    assert w.interp_range == _DEFAULT_INTERP_RANGE
