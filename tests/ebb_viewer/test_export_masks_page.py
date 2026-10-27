"""Integration tests for ExportMasksPage — verify the page's params flow.

These run against an empty project root (no animals on disk) but the widget
plumbing is fully exercised: from_params → widget → to_params, modified
detection, params delegation to the pipeline.
"""

from __future__ import annotations

from pathlib import Path

from ebb_viewer.pages.export_masks import ExportMasksPage
from ebb_viewer.pipeline import export_params, psd_params


def _make_page(qapp, tmp_path: Path) -> ExportMasksPage:
    return ExportMasksPage(project_root=tmp_path)


def test_page_constructs_with_empty_project(qapp, tmp_path: Path):
    page = _make_page(qapp, tmp_path)
    assert page is not None
    # The mask widget is mounted; current_params returns widget defaults.
    p = page._current_params()
    assert "states" in p
    assert "nstd" in p


def test_default_params_match_widget_defaults(qapp, tmp_path: Path):
    page = _make_page(qapp, tmp_path)
    p = page._current_params()
    assert p["nstd"] == 5.0
    assert p["winsize"] == 180
    assert p["radius"] == 0.5
    assert p["noise_thresh"] == 0.5
    assert p["use_drink_mask"] is True
    assert p["use_swd_mask"] is False
    assert sorted(p["states"]) == ["nrem", "rem", "wake"]


def test_apply_loaded_params_from_psd_run(qapp, tmp_path: Path):
    """Loading a PSD run's params populates the widget end-to-end."""
    psd_params.save(
        tmp_path,
        "run_a",
        {
            "nstd": 4.0,
            "winsize": 240,
            "radius": 0.75,
            "noise_thresh": 0.3,
            "states": ["wake", "sleep"],
            "use_swd_mask": True,
            "hw_enabled": True,
            "hour_windows": [[6.0, 18.0]],
            "selected_days": [0, 1],
        },
    )
    page = _make_page(qapp, tmp_path)
    page._apply_loaded_params(
        psd_params.load(tmp_path, "run_a"), source="psd", run_name="run_a"
    )

    p = page._current_params()
    assert p["nstd"] == 4.0
    assert p["winsize"] == 240
    assert p["radius"] == 0.75
    assert p["noise_thresh"] == 0.3
    assert sorted(p["states"]) == ["sleep", "wake"]
    assert p["hw_enabled"] is True
    assert p["hour_windows"] == [(6.0, 18.0)]
    assert p["selected_days"] == [0, 1]


def test_modified_label_clears_after_load(qapp, tmp_path: Path):
    page = _make_page(qapp, tmp_path)
    page._apply_loaded_params({"nstd": 3.0}, source="psd", run_name="run_a")
    assert page.lbl_modified.text() == ""


def test_modified_label_appears_after_editing_loaded_params(qapp, tmp_path: Path):
    page = _make_page(qapp, tmp_path)
    page._apply_loaded_params({"nstd": 3.0}, source="psd", run_name="run_a")
    # Edit the widget; should trigger modified state.
    page.mask_widget.dspin_z.setValue(7.0)
    assert "Modified" in page.lbl_modified.text()
    assert "run_a" in page.lbl_modified.text()


# ---------------------------------------------------------------------------
# Page-owned params (channels, fs) — these live on the page, not the mask
# widget, so they need their own coverage to confirm they reach _current_params
# (consumed by export_run) and round-trip through _apply_loaded_params.
# ---------------------------------------------------------------------------


def test_current_params_includes_channels_and_fs(qapp, tmp_path: Path):
    """``_current_params`` merges page-owned channels + fs into the widget
    params. A regression here would silently send ``[0, 1, 2]`` and 250 Hz
    to ``export_run`` (its defaults) regardless of the page's UI state."""
    page = _make_page(qapp, tmp_path)
    # Untick LFC; bump fs.
    page._channel_boxes[0].setChecked(False)
    page.spin_fs.setValue(500)

    p = page._current_params()
    assert p["channels"] == [1, 2]
    assert p["fs"] == 500


def test_apply_loaded_params_restores_channels_and_fs(qapp, tmp_path: Path):
    """Loading a saved run with non-default channels + fs must restore both
    page-owned controls, not just the widget params."""
    page = _make_page(qapp, tmp_path)
    page._apply_loaded_params(
        {"states": ["wake"], "channels": [0, 2], "fs": 1000},
        source="psd",
        run_name="run_a",
    )
    assert page.selected_channels() == [0, 2]
    assert page.spin_fs.value() == 1000
    # And the loaded snapshot includes them, so subsequent edits flag modified.
    assert page._loaded_snapshot["channels"] == [0, 2]
    assert page._loaded_snapshot["fs"] == 1000


def test_modified_label_appears_after_editing_channels(qapp, tmp_path: Path):
    """Channel-selection changes must trip the Modified state — channels
    are part of the export config, so a drift from the loaded run should
    surface to the user."""
    page = _make_page(qapp, tmp_path)
    page._apply_loaded_params(
        {"states": ["wake"], "channels": [0, 1, 2]}, source="psd", run_name="run_a"
    )
    assert page.lbl_modified.text() == ""
    page._channel_boxes[0].setChecked(False)
    assert "Modified" in page.lbl_modified.text()


def test_modified_label_appears_after_editing_fs(qapp, tmp_path: Path):
    """Sampling-freq changes must also trip the Modified state."""
    page = _make_page(qapp, tmp_path)
    page._apply_loaded_params(
        {"states": ["wake"], "fs": 250}, source="psd", run_name="run_a"
    )
    assert page.lbl_modified.text() == ""
    page.spin_fs.setValue(500)
    assert "Modified" in page.lbl_modified.text()


def test_load_from_export_config_populates_widget(qapp, tmp_path: Path):
    """Export configs round-trip the full widget params dict."""
    saved = {
        "nstd": 6.5,
        "winsize": 120,
        "radius": 1.0,
        "noise_thresh": 0.7,
        "states": ["wake"],
        "use_swd_mask": False,
        "swd_pad": 3,
        "use_drink_mask": False,
        "drink_pad": 5,
        "ann_enabled": False,
        "ann_dir": None,
        "ann_keywords": "",
        "ann_match_mode": "contains",
        "ann_pad_before": 0.0,
        "ann_pad_after": 0.0,
        "hw_enabled": False,
        "hour_windows": None,
        "selected_days": None,
    }
    export_params.save(tmp_path, "my_export", saved)

    page = _make_page(qapp, tmp_path)
    # Simulate the load button's behavior.
    page._apply_loaded_params(
        export_params.load(tmp_path, "my_export"),
        source="export",
        run_name="my_export",
    )

    p = page._current_params()
    for key, expected in saved.items():
        assert p[key] == expected, f"key {key!r}: expected {expected!r}, got {p[key]!r}"


def test_export_button_disabled_when_no_states_selected(qapp, tmp_path: Path):
    page = _make_page(qapp, tmp_path)
    # Uncheck every state.
    for cb in page.mask_widget._state_boxes.values():
        cb.setChecked(False)
    page._update_export_button()
    assert not page.btn_export.isEnabled()
    assert "state" in page.lbl_action_hint.text().lower()


def test_swd_availability_detection(qapp, tmp_path: Path):
    """If swd/ has .mat files, the widget's SWD mask-out radio is enabled."""
    (tmp_path / "swd").mkdir()
    (tmp_path / "swd" / "AM001.mat").write_text("")
    page = _make_page(qapp, tmp_path)
    assert page.mask_widget._radio_swd_mask.isEnabled()


def test_swd_unavailable_when_no_mat_files(qapp, tmp_path: Path):
    page = _make_page(qapp, tmp_path)
    assert not page.mask_widget._radio_swd_mask.isEnabled()


def test_load_from_psd_run_refreshes_section_subtitles(qapp, tmp_path: Path):
    """Regression: header summaries must update on Load from PSD run.

    Earlier the page wrapped from_params in blockSignals(True), which
    also blocked the widget's internal `changed` signal — preventing
    _refresh_subtitles from running.
    """
    psd_params.save(
        tmp_path,
        "run_a",
        {
            "hw_enabled": True,
            "hour_windows": [[6.0, 18.0]],
            "selected_days": [0, 1, 2],
            "noise_thresh": 0.75,
        },
    )
    page = _make_page(qapp, tmp_path)
    page._apply_loaded_params(
        psd_params.load(tmp_path, "run_a"), source="psd", run_name="run_a"
    )
    assert page.mask_widget._sections["hour_window"].subtitle() == "6–18h, days 0,1,2"
    assert page.mask_widget._sections["spindle"].subtitle() == "0.75"


# ---------------------------------------------------------------------------
# Sampling-frequency auto-detect on showEvent
# ---------------------------------------------------------------------------


def test_autodetect_fs_fills_when_spinbox_at_default(qapp, tmp_path: Path, monkeypatch):
    """Same auto-detect rule as the PSD Compute page — fill on show only if
    the SpinBox is still at the hardcoded DEFAULT_FS sentinel."""
    import ebb_viewer.pages.export_masks as em_mod

    page = _make_page(qapp, tmp_path)
    assert page.spin_fs.value() == em_mod.DEFAULT_FS

    monkeypatch.setattr(em_mod, "detect_fs_from_standard", lambda _root: 500)
    page._maybe_autodetect_fs()

    assert page.spin_fs.value() == 500


def test_autodetect_fs_does_not_override_user_value(qapp, tmp_path: Path, monkeypatch):
    import ebb_viewer.pages.export_masks as em_mod

    page = _make_page(qapp, tmp_path)
    page.spin_fs.setValue(1000)

    monkeypatch.setattr(em_mod, "detect_fs_from_standard", lambda _root: 500)
    page._maybe_autodetect_fs()

    assert page.spin_fs.value() == 1000


def test_autodetect_fs_noop_when_detect_returns_none(qapp, tmp_path: Path, monkeypatch):
    import ebb_viewer.pages.export_masks as em_mod

    page = _make_page(qapp, tmp_path)

    monkeypatch.setattr(em_mod, "detect_fs_from_standard", lambda _root: None)
    page._maybe_autodetect_fs()

    assert page.spin_fs.value() == em_mod.DEFAULT_FS
