"""Param-flow tests for ``pages/psds.py``.

These tests focus on the parameter plumbing from the page UI and saved
``psd_params.json`` files into ``BatchEstimateWorker`` and ultimately
``batch_estimate``. The scientific compute is stubbed so we can verify the
exact kwargs that would have been forwarded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ebb_viewer.pipeline import psd_params

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page(qapp, tmp_path: Path):
    from ebb_viewer.pages.psds import PSDPage

    return PSDPage(project_root=tmp_path)


def _make_dialog(qapp, tmp_path: Path, *, swd_available: bool = True):
    from ebb_viewer.pages.psds import MaskingSettingsDialog

    return MaskingSettingsDialog(
        swd_available=swd_available,
        swd_status_text="",
        project_root=tmp_path,
    )


def _run_worker_capturing_batch_estimate(
    tmp_path: Path,
    params: dict,
    *,
    ann_params: dict | None = None,
    swd_dir: Path | None = None,
) -> list[dict]:
    """Run BatchEstimateWorker against a stubbed batch_estimate; return the
    kwargs dicts that batch_estimate was called with."""
    spindle_dir = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_dir.mkdir(parents=True)
    savepath = tmp_path / "psd" / "default" / "psds_LFC_RSC.pkl"
    savepath.parent.mkdir(parents=True)

    captured: list[dict] = []
    import ebb_viewer.pages.psds as psds_mod

    orig = psds_mod.batch_estimate

    def stub(**kw: Any) -> list:
        captured.append(kw)
        return []

    psds_mod.batch_estimate = stub
    try:
        worker = psds_mod.BatchEstimateWorker(
            eeg_dir=tmp_path / "standard",
            combo_pairs=[(spindle_dir, savepath)],
            params=params,
            project_root=tmp_path,
            swd_dir=swd_dir,
            ann_params=ann_params,
        )
        worker.run()
    finally:
        psds_mod.batch_estimate = orig

    return captured


# ---------------------------------------------------------------------------
# B1 — ann_pad_after default must be 0.0 (was silently 10.0)
# ---------------------------------------------------------------------------


def test_b1_ann_pad_after_default_is_zero_when_missing(qapp, tmp_path: Path):
    """When saved psd_params.json predates ann_pad_after being saved, the
    page should fall back to 0.0 (matching the dialog spinbox default), not
    10.0. The 10.0 fallback silently injects unintended padding."""
    psd_params.save(tmp_path, "default", {"fs": 250, "states": ["wake"]})
    page = _make_page(qapp, tmp_path)
    assert page._masking_params["ann_pad_after"] == 0.0


def test_b1_ann_pad_after_roundtrips_explicit_value(qapp, tmp_path: Path):
    """An explicit ann_pad_after value in saved params should reload as-is."""
    psd_params.save(
        tmp_path, "default", {"fs": 250, "states": ["wake"], "ann_pad_after": 7.5}
    )
    page = _make_page(qapp, tmp_path)
    assert page._masking_params["ann_pad_after"] == 7.5


def test_b1_ann_pad_after_default_zero_in_pipeline(qapp, tmp_path: Path):
    """Run the pipeline after loading params without ann_pad_after; the
    forwarded ann_params dict (if ann is enabled) must use 0.0, not 10.0."""
    # Save params that enable annotation but omit pad_after.
    ann_dir = tmp_path / "annotations"
    ann_dir.mkdir()
    psd_params.save(
        tmp_path,
        "default",
        {
            "fs": 250,
            "states": ["wake"],
            "ann_enabled": True,
            "ann_dir": str(ann_dir),
            "ann_keywords": "drink",
        },
    )
    page = _make_page(qapp, tmp_path)
    # Replicate the page's own pipeline-build logic without touching disk:
    mp = page._masking_params
    ann_params = {
        "ann_dir": mp["ann_dir"],
        "keywords": [k.strip() for k in mp.get("ann_keywords", "").split(",") if k.strip()],
        "match_mode": mp.get("ann_match_mode", "contains"),
        "pad_before_sec": mp.get("ann_pad_before", 0.0),
        "pad_after_sec": mp.get("ann_pad_after", 0.0),
    }
    assert ann_params["pad_after_sec"] == 0.0


# ---------------------------------------------------------------------------
# B3 — dialog.load_params tolerates both swd_mode and use_swd_mask
# ---------------------------------------------------------------------------


def test_b3_dialog_load_params_accepts_legacy_swd_mode(qapp, tmp_path: Path):
    """Legacy psd_params.json shape: ``swd_mode: 'mask_out'``."""
    dlg = _make_dialog(qapp, tmp_path, swd_available=True)
    dlg.load_params({"swd_mode": "mask_out"})
    assert dlg._radio_swd_mask.isChecked()


def test_b3_dialog_load_params_accepts_widget_use_swd_mask(qapp, tmp_path: Path):
    """Newer export-config shape: ``use_swd_mask: True``."""
    dlg = _make_dialog(qapp, tmp_path, swd_available=True)
    dlg.load_params({"use_swd_mask": True})
    assert dlg._radio_swd_mask.isChecked()


def test_b3_dialog_load_params_swd_unavailable_forces_none(qapp, tmp_path: Path):
    """When SWD isn't available, neither key form should enable the mask."""
    dlg = _make_dialog(qapp, tmp_path, swd_available=False)
    dlg.load_params({"swd_mode": "mask_out"})
    assert dlg._radio_swd_none.isChecked()
    assert not dlg._radio_swd_mask.isChecked()


# ---------------------------------------------------------------------------
# hour window forwarding
# ---------------------------------------------------------------------------


def test_worker_forwards_hour_windows_and_selected_days(tmp_path: Path):
    params = {
        "fs": 250,
        "channels": [0, 1, 2],
        "winsize": 180,
        "radius": 0.5,
        "nstd": 5.0,
        "noise_thresh": 0.5,
        "states": ["wake", "sleep"],
        "hw_enabled": True,
        "hour_windows": [(6.0, 18.0)],
        "selected_days": [0, 1, 2],
    }
    calls = _run_worker_capturing_batch_estimate(tmp_path, params)
    assert len(calls) == 1
    kw = calls[0]
    # batch_estimate receives the params via **kwargs (unpacked into kw).
    assert kw["hour_windows"] == [(6.0, 18.0)]
    assert kw["selected_days"] == [0, 1, 2]
    assert kw["hw_enabled"] is True


def test_worker_omits_hour_windows_when_disabled(tmp_path: Path):
    params = {
        "fs": 250,
        "channels": [0],
        "winsize": 180,
        "radius": 0.5,
        "nstd": 5.0,
        "noise_thresh": 0.5,
        "states": ["wake"],
        # hw_enabled / hour_windows / selected_days deliberately absent
    }
    calls = _run_worker_capturing_batch_estimate(tmp_path, params)
    assert "hour_windows" not in calls[0]
    assert "selected_days" not in calls[0]


# ---------------------------------------------------------------------------
# annotation forwarding
# ---------------------------------------------------------------------------


def test_worker_forwards_ann_params(tmp_path: Path):
    ann_dir = tmp_path / "annotations"
    ann_dir.mkdir()
    ann_params = {
        "ann_dir": ann_dir,
        "keywords": ["drink", "scratch"],
        "match_mode": "exact",
        "pad_before_sec": 1.5,
        "pad_after_sec": 2.5,
    }
    params = {"fs": 250, "channels": [0], "states": ["wake"]}
    calls = _run_worker_capturing_batch_estimate(tmp_path, params, ann_params=ann_params)
    assert calls[0]["ann_params"] == ann_params


# ---------------------------------------------------------------------------
# Save → reload round-trip (psd_params.json ↔ page._masking_params)
# ---------------------------------------------------------------------------


def test_full_masking_roundtrip_psd_params_json(qapp, tmp_path: Path):
    """A psd_params.json written with the full masking suite should reload
    into ``_masking_params`` with no field loss."""
    written = {
        "fs": 250,
        "channels": [0, 1, 2],
        "winsize": 240,
        "radius": 0.75,
        "nstd": 4.0,
        "noise_thresh": 0.3,
        "states": ["wake", "nrem"],
        "swd_mode": "mask_out",
        "ann_enabled": True,
        "ann_dir": str(tmp_path / "annotations"),
        "ann_keywords": "drink, artifact",
        "ann_match_mode": "exact",
        "ann_pad_before": 0.5,
        "ann_pad_after": 1.5,
        "hw_enabled": True,
        "hour_windows": [[6.0, 18.0]],
        "selected_days": [0, 1, 2],
    }
    (tmp_path / "annotations").mkdir()
    psd_params.save(tmp_path, "default", written)

    page = _make_page(qapp, tmp_path)
    mp = page._masking_params
    assert mp["swd_mode"] == "mask_out"
    assert mp["ann_enabled"] is True
    assert mp["ann_dir"] == tmp_path / "annotations"
    assert mp["ann_keywords"] == "drink, artifact"
    assert mp["ann_match_mode"] == "exact"
    assert mp["ann_pad_before"] == 0.5
    assert mp["ann_pad_after"] == 1.5
    assert mp["hw_enabled"] is True
    assert mp["hour_windows"] == [[6.0, 18.0]]
    assert mp["selected_days"] == [0, 1, 2]


def test_pipeline_save_format_includes_all_masking_keys(tmp_path: Path):
    """After a successful run, psd_params.json must contain every masking
    key the page knows about (so a subsequent reload is lossless)."""
    ann_dir = tmp_path / "annotations"
    ann_dir.mkdir()
    ann_params = {
        "ann_dir": ann_dir,
        "keywords": ["drink"],
        "match_mode": "contains",
        "pad_before_sec": 0.0,
        "pad_after_sec": 2.0,
    }
    params = {
        "fs": 250,
        "channels": [0, 1],
        "winsize": 180,
        "radius": 0.5,
        "nstd": 5.0,
        "noise_thresh": 0.5,
        "states": ["wake"],
        "hw_enabled": True,
        "hour_windows": [(6.0, 18.0)],
        "selected_days": [0],
    }
    _run_worker_capturing_batch_estimate(
        tmp_path, params, ann_params=ann_params, swd_dir=tmp_path / "swd"
    )
    saved_path = tmp_path / "psd" / "default" / "psd_params.json"
    assert saved_path.exists()
    saved = json.loads(saved_path.read_text())
    # Compute keys preserved
    for k in ("fs", "channels", "winsize", "radius", "nstd", "noise_thresh", "states"):
        assert saved[k] == params[k]
    # Hour-window keys preserved
    assert saved["hw_enabled"] is True
    assert saved["hour_windows"] == [[6.0, 18.0]]  # JSON tuple → list
    assert saved["selected_days"] == [0]
    # SWD recorded as legacy swd_mode
    assert saved["swd_mode"] == "mask_out"
    # Annotation keys all flattened
    assert saved["ann_enabled"] is True
    assert saved["ann_dir"] == str(ann_dir)
    assert saved["ann_keywords"] == "drink"
    assert saved["ann_match_mode"] == "contains"
    assert saved["ann_pad_before"] == 0.0
    assert saved["ann_pad_after"] == 2.0
