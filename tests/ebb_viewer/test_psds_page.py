"""Param-flow tests for ``pages/psds.py``.

These tests focus on the parameter plumbing from the page UI and saved
``psd_params.json`` files into ``BatchEstimateWorker`` and ultimately
``batch_estimate``. The scientific compute is stubbed so we can verify the
exact kwargs that would have been forwarded.

After Stage B-2 the page delegates state-group, SD-mask, spindle-noise,
SWD, annotation, and hour-window params to the shared
``MaskParamsWidget`` (``page.mask_widget``); the page itself only owns
channels + fs. Tests that previously inspected ``page._masking_params``
now route through ``page.mask_widget.to_params()``. The dialog-specific
tests (``test_b3_dialog_*``) are dropped — equivalent coverage exists in
``test_mask_params_widget.py``.
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
    widget should fall back to 0.0 — not the legacy 10.0 silently injected
    by the pre-Stage-A page."""
    psd_params.save(tmp_path, "default", {"fs": 250, "states": ["wake"]})
    page = _make_page(qapp, tmp_path)
    assert page.mask_widget.to_params()["ann_pad_after"] == 0.0


def test_b1_ann_pad_after_roundtrips_explicit_value(qapp, tmp_path: Path):
    """An explicit ann_pad_after value in saved params should reload as-is."""
    psd_params.save(
        tmp_path, "default", {"fs": 250, "states": ["wake"], "ann_pad_after": 7.5}
    )
    page = _make_page(qapp, tmp_path)
    assert page.mask_widget.to_params()["ann_pad_after"] == 7.5


def test_b1_ann_pad_after_default_zero_in_pipeline(qapp, tmp_path: Path):
    """When the page builds ann_params for the worker, ann_pad_after must
    default to 0.0 (not silently injected as 10.0)."""
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
    # Replicate _run_pipeline_clicked's ann_params build from widget params.
    wp = page.mask_widget.to_params()
    ann_params = {
        "ann_dir": Path(wp["ann_dir"]),
        "keywords": [k.strip() for k in (wp.get("ann_keywords") or "").split(",") if k.strip()],
        "match_mode": wp.get("ann_match_mode", "contains"),
        "pad_before_sec": float(wp.get("ann_pad_before", 0.0)),
        "pad_after_sec": float(wp.get("ann_pad_after", 0.0)),
    }
    assert ann_params["pad_after_sec"] == 0.0


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


def test_worker_forwards_comm_value(tmp_path: Path):
    """``comm_value`` is a real ``estimate_psd`` kwarg (not UI-only), so the
    worker must pass it through to batch_estimate. A regression here would
    silently fall back to the hardcoded 2000 µV for every PSD."""
    from ebb.process.psd_compute import _UI_ONLY_KWARGS

    params = {
        "fs": 250,
        "channels": [0, 1, 2],
        "comm_value": 1500,
        "winsize": 180,
        "radius": 0.5,
        "nstd": 5.0,
        "noise_thresh": 0.5,
        "states": ["wake"],
    }
    calls = _run_worker_capturing_batch_estimate(tmp_path, params)
    assert calls[0]["comm_value"] == 1500
    # Lock in that comm_value is NOT stripped by _prepare_estimator_kwargs
    # (which would silently re-default it to 2000 µV inside estimate_psd).
    assert "comm_value" not in _UI_ONLY_KWARGS


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
# Save → reload round-trip via the shared widget
# ---------------------------------------------------------------------------


def test_full_masking_roundtrip_psd_params_json(qapp, tmp_path: Path):
    """A psd_params.json written with the full masking suite should reload
    into the widget with no field loss across the (re)serialization."""
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
    # SWD section needs swd_available=True for the radio to engage; place
    # a stub .mat file so the page's _refresh_swd_status enables it.
    (tmp_path / "swd").mkdir()
    (tmp_path / "swd" / "AM001.mat").write_text("")
    psd_params.save(tmp_path, "default", written)

    page = _make_page(qapp, tmp_path)
    wp = page.mask_widget.to_params()
    # swd_mode is the legacy key; widget exposes the boolean shadow.
    assert wp["use_swd_mask"] is True
    assert wp["ann_enabled"] is True
    assert wp["ann_dir"] == str(tmp_path / "annotations")
    assert wp["ann_keywords"] == "drink, artifact"
    assert wp["ann_match_mode"] == "exact"
    assert wp["ann_pad_before"] == 0.5
    assert wp["ann_pad_after"] == 1.5
    assert wp["hw_enabled"] is True
    assert wp["hour_windows"] == [(6.0, 18.0)]
    assert wp["selected_days"] == [0, 1, 2]
    # And the page-local channels + fs both reloaded.
    assert page.spin_fs.value() == 250
    assert page.selected_channels() == [0, 1, 2]


# ---------------------------------------------------------------------------
# Gating + radius precision
# ---------------------------------------------------------------------------


def test_empty_channel_selection_disables_run_button(qapp, tmp_path: Path):
    """Unchecking every channel must gate the Run button.

    Background: ``estimate_psd``'s ``channels=None`` default only kicks in
    when channels is ``None``, not ``[]`` — so an empty list would either
    crash the compute or silently produce nothing.
    """
    page = _make_page(qapp, tmp_path)
    for cb in page._channel_boxes:
        cb.setChecked(False)
    page._validate()
    assert not page.btn_run_pipeline.isEnabled()
    # Toggling channels also fires the signal-driven validate; confirm
    # the live wiring still gates the button.
    page._channel_boxes[0].setChecked(True)
    assert not page.btn_run_pipeline.isEnabled()  # other gates still fail
    for cb in page._channel_boxes:
        cb.setChecked(True)


def test_channel_gate_label_when_channels_are_sole_failure(qapp, tmp_path: Path):
    """When every other gate passes, the empty-channels gate must surface
    its dedicated label so the user understands why Run is disabled."""
    (tmp_path / "standard").mkdir()
    spindle = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle.mkdir(parents=True)
    (spindle / "AM001_LFC_RSC.csv").write_text("rawstate\n")
    from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry

    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        has_spindle=True,
        sleep_qc="ok",
    )
    m.save()

    page = _make_page(qapp, tmp_path)
    for cb in page._channel_boxes:
        cb.setChecked(False)
    page._validate()
    assert not page.btn_run_pipeline.isEnabled()
    assert "channel" in page._gate_label.text().lower()


def test_radius_two_decimals_no_rounding(qapp, tmp_path: Path):
    """Saved ``radius=0.75`` must reload as 0.75 via the widget's spinbox.

    The MaskParamsWidget's SD-mask radius spinbox uses 2 decimals + 0.05
    step specifically to prevent silent rounding of saved values.
    """
    psd_params.save(tmp_path, "default", {"fs": 250, "states": ["wake"], "radius": 0.75})
    page = _make_page(qapp, tmp_path)
    assert page.mask_widget.dspin_radius.value() == 0.75


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
    for k in ("fs", "channels", "winsize", "radius", "nstd", "noise_thresh", "states"):
        assert saved[k] == params[k]
    assert saved["hw_enabled"] is True
    assert saved["hour_windows"] == [[6.0, 18.0]]
    assert saved["selected_days"] == [0]
    assert saved["swd_mode"] == "mask_out"
    assert saved["ann_enabled"] is True
    assert saved["ann_dir"] == str(ann_dir)
    assert saved["ann_keywords"] == "drink"
    assert saved["ann_match_mode"] == "contains"
    assert saved["ann_pad_before"] == 0.0
    assert saved["ann_pad_after"] == 2.0


# ---------------------------------------------------------------------------
# Stage B-2 — page → widget integration smoke
# ---------------------------------------------------------------------------


def test_page_has_mask_widget_with_drink_hidden(qapp, tmp_path: Path):
    """PSD page constructs the shared widget with show_drink_mask=False
    (PSD initial compute never applies drink masks)."""
    page = _make_page(qapp, tmp_path)
    assert page.mask_widget is not None
    assert page.mask_widget._sections["drink"].isHidden()


def test_page_validate_uses_widget_states(qapp, tmp_path: Path):
    """``_validate`` reads selected states from the widget, not from any
    page-local state-checkbox list."""
    page = _make_page(qapp, tmp_path)
    # Uncheck all state boxes via the widget.
    for cb in page.mask_widget._state_boxes.values():
        cb.setChecked(False)
    page._validate()
    assert not page.btn_run_pipeline.isEnabled()


def test_page_widget_changed_propagates_to_gate_label(qapp, tmp_path: Path):
    """Toggling a widget state checkbox re-renders the page gate.

    Set up just enough state for the states-gate to be the sole unmet
    requirement, then uncheck every state via the widget and assert the
    gate label flips to the dedicated "select a state" message.
    """
    (tmp_path / "standard").mkdir()
    spindle = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle.mkdir(parents=True)
    (spindle / "AM001_LFC_RSC.csv").write_text("rawstate\n")
    from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry

    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        has_spindle=True,
        sleep_qc="ok",
    )
    m.save()

    page = _make_page(qapp, tmp_path)
    for cb in page.mask_widget._state_boxes.values():
        cb.setChecked(False)
    # The widget.changed → page._validate wiring should re-render the gate
    # without us calling _validate explicitly.
    assert "state" in page._gate_label.text().lower()
    assert not page.btn_run_pipeline.isEnabled()


# ---------------------------------------------------------------------------
# Sampling-frequency auto-detect on showEvent
# ---------------------------------------------------------------------------


def test_autodetect_fs_fills_when_spinbox_at_default(qapp, tmp_path: Path, monkeypatch):
    """On show, if spin_fs is still at the hardcoded DEFAULT_FS sentinel,
    detect_fs_from_standard runs and the box gets the file's fs."""
    import ebb_viewer.pages.psds as psds_mod

    page = _make_page(qapp, tmp_path)
    assert page.spin_fs.value() == psds_mod.DEFAULT_FS  # sanity

    monkeypatch.setattr(psds_mod, "detect_fs_from_standard", lambda _root: 500)
    page._maybe_autodetect_fs()

    assert page.spin_fs.value() == 500


def test_autodetect_fs_does_not_override_user_value(qapp, tmp_path: Path, monkeypatch):
    """When the user (or saved params) has moved the SpinBox off the
    default, the auto-detect must leave it alone."""
    import ebb_viewer.pages.psds as psds_mod

    page = _make_page(qapp, tmp_path)
    page.spin_fs.setValue(1000)

    monkeypatch.setattr(psds_mod, "detect_fs_from_standard", lambda _root: 500)
    page._maybe_autodetect_fs()

    assert page.spin_fs.value() == 1000


def test_autodetect_fs_noop_when_detect_returns_none(qapp, tmp_path: Path, monkeypatch):
    """No readable EDF (detect returns None) → SpinBox stays at default."""
    import ebb_viewer.pages.psds as psds_mod

    page = _make_page(qapp, tmp_path)

    monkeypatch.setattr(psds_mod, "detect_fs_from_standard", lambda _root: None)
    page._maybe_autodetect_fs()

    assert page.spin_fs.value() == psds_mod.DEFAULT_FS
