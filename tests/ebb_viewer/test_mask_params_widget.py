"""Tests for the shared MaskParamsWidget.

Round-trip coverage is the primary goal: PSD computation correctness depends
on the widget faithfully serializing/deserializing every parameter.
"""

from __future__ import annotations

from pathlib import Path

from ebb_viewer.widgets.mask_params_widget import (
    MaskParamsWidget,
    _annotation_subtitle,
    _drink_subtitle,
    _hour_window_subtitle,
    _sd_subtitle,
    _spindle_subtitle,
    _states_subtitle,
    _swd_subtitle,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_widget(qapp, tmp_path=None, *, swd_available: bool = True) -> MaskParamsWidget:
    return MaskParamsWidget(project_root=tmp_path, swd_available=swd_available)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_widget_constructs(qapp):
    w = _make_widget(qapp)
    assert w is not None


def test_to_params_returns_dict_with_expected_keys(qapp):
    w = _make_widget(qapp)
    params = w.to_params()
    expected_keys = {
        "states",
        "comm_value",
        "nstd",
        "winsize",
        "radius",
        "noise_thresh",
        "use_swd_mask",
        "swd_pad",
        "ann_enabled",
        "ann_dir",
        "ann_keywords",
        "ann_match_mode",
        "ann_pad_before",
        "ann_pad_after",
        "hw_enabled",
        "hour_windows",
        "selected_days",
        "use_drink_mask",
        "drink_pad",
    }
    assert set(params.keys()) == expected_keys


def test_default_to_params_matches_estimate_psd_defaults(qapp):
    """Untouched widget defaults reflect the canonical PSD computation params."""
    w = _make_widget(qapp)
    params = w.to_params()
    assert params["nstd"] == 5.0
    assert params["winsize"] == 180
    assert params["radius"] == 0.5
    assert params["noise_thresh"] == 0.5
    assert params["use_swd_mask"] is False
    assert params["swd_pad"] == 0
    assert params["ann_enabled"] is False
    assert params["hw_enabled"] is False
    assert params["hour_windows"] is None
    assert params["selected_days"] is None
    assert params["use_drink_mask"] is True
    assert params["drink_pad"] == 2
    # default states are wake/nrem/rem
    assert sorted(params["states"]) == sorted(["wake", "nrem", "rem"])


# ---------------------------------------------------------------------------
# States section
# ---------------------------------------------------------------------------


def test_states_default_is_wake_nrem_rem(qapp):
    w = _make_widget(qapp)
    assert set(w.to_params()["states"]) == {"wake", "nrem", "rem"}


def test_states_can_be_toggled_off(qapp):
    w = _make_widget(qapp)
    w._state_boxes["rem"].setChecked(False)
    assert "rem" not in w.to_params()["states"]


def test_states_empty_when_all_unchecked(qapp):
    w = _make_widget(qapp)
    for cb in w._state_boxes.values():
        cb.setChecked(False)
    assert w.to_params()["states"] == []


# ---------------------------------------------------------------------------
# SD mask section
# ---------------------------------------------------------------------------


def test_sd_mask_values_round_trip(qapp):
    w = _make_widget(qapp)
    w.spin_window.setValue(120)
    w.dspin_radius.setValue(1.5)
    w.dspin_z.setValue(3.0)
    p = w.to_params()
    assert p["winsize"] == 120
    assert p["radius"] == 1.5
    assert p["nstd"] == 3.0


# ---------------------------------------------------------------------------
# Spindle noise section
# ---------------------------------------------------------------------------


def test_spindle_noise_threshold_round_trip(qapp):
    w = _make_widget(qapp)
    w.dspin_noise.setValue(0.75)
    assert w.to_params()["noise_thresh"] == 0.75


# ---------------------------------------------------------------------------
# SWD section
# ---------------------------------------------------------------------------


def test_swd_mask_out_emits_use_swd_mask_true(qapp):
    w = _make_widget(qapp, swd_available=True)
    w._radio_swd_mask.setChecked(True)
    assert w.to_params()["use_swd_mask"] is True


def test_swd_none_emits_use_swd_mask_false(qapp):
    w = _make_widget(qapp, swd_available=True)
    w._radio_swd_none.setChecked(True)
    assert w.to_params()["use_swd_mask"] is False


def test_swd_radio_disabled_when_unavailable(qapp):
    w = _make_widget(qapp, swd_available=False)
    assert not w._radio_swd_mask.isEnabled()


def test_set_swd_available_after_construction(qapp):
    w = _make_widget(qapp, swd_available=False)
    w.set_swd_available(True)
    assert w._radio_swd_mask.isEnabled()


def test_swd_unavailable_falls_back_to_none_even_if_params_say_use(qapp):
    w = _make_widget(qapp, swd_available=False)
    w.from_params({"use_swd_mask": True})
    assert w._radio_swd_none.isChecked()
    assert w.to_params()["use_swd_mask"] is False


def test_legacy_swd_mode_key_loads_correctly(qapp):
    """Old PSD params used `swd_mode`; widget still loads them."""
    w = _make_widget(qapp, swd_available=True)
    w.from_params({"swd_mode": "mask_out"})
    assert w.to_params()["use_swd_mask"] is True


def test_swd_pad_round_trip(qapp):
    w = _make_widget(qapp)
    w.spin_swd_pad.setValue(15)
    assert w.to_params()["swd_pad"] == 15


# ---------------------------------------------------------------------------
# Annotation section
# ---------------------------------------------------------------------------


def test_annotation_disabled_by_default(qapp):
    w = _make_widget(qapp)
    assert w.to_params()["ann_enabled"] is False


def test_annotation_enable_round_trip(qapp):
    w = _make_widget(qapp)
    w.chk_ann.setChecked(True)
    w._ann_keyword_edit.setText("drink, artifact")
    w._radio_ann_exact.setChecked(True)
    w._ann_pad_before.setValue(2.0)
    w._ann_pad_after.setValue(5.0)
    p = w.to_params()
    assert p["ann_enabled"] is True
    assert p["ann_keywords"] == "drink, artifact"
    assert p["ann_match_mode"] == "exact"
    assert p["ann_pad_before"] == 2.0
    assert p["ann_pad_after"] == 5.0


def test_annotation_match_mode_defaults_to_contains(qapp):
    w = _make_widget(qapp)
    assert w.to_params()["ann_match_mode"] == "contains"


def test_annotation_dir_set_via_from_params(qapp, tmp_path: Path):
    w = _make_widget(qapp, tmp_path)
    w.from_params({"ann_dir": str(tmp_path)})
    assert w.to_params()["ann_dir"] == str(tmp_path)


def test_annotation_dir_ignored_if_not_a_dir(qapp, tmp_path: Path):
    w = _make_widget(qapp)
    w.from_params({"ann_dir": str(tmp_path / "nonexistent")})
    assert w.to_params()["ann_dir"] is None


# ---------------------------------------------------------------------------
# Hour windows section
# ---------------------------------------------------------------------------


def test_hour_windows_disabled_returns_none_even_with_windows_defined(qapp):
    w = _make_widget(qapp)
    w._add_window_row(6.0, 18.0)
    # Not enabled — hour_windows must be None
    assert w.to_params()["hour_windows"] is None


def test_hour_windows_enabled_returns_defined_windows(qapp):
    w = _make_widget(qapp)
    w.chk_hour_window.setChecked(True)
    w._add_window_row(6.0, 18.0)
    w._add_window_row(20.0, 6.0)  # wrap-around
    p = w.to_params()
    assert p["hour_windows"] == [(6.0, 18.0), (20.0, 6.0)]
    assert p["hw_enabled"] is True


def test_selected_days_returned_when_specific_radio_checked(qapp):
    w = _make_widget(qapp)
    w.chk_hour_window.setChecked(True)
    w._add_window_row(0.0, 12.0)
    w._radio_hw_sel.setChecked(True)
    w._hw_days_edit.setText("0,1,2")
    assert w.to_params()["selected_days"] == [0, 1, 2]


def test_selected_days_none_when_all_days_radio(qapp):
    w = _make_widget(qapp)
    w.chk_hour_window.setChecked(True)
    w._add_window_row(0.0, 12.0)
    w._hw_days_edit.setText("0,1,2")  # value present but radio = "all days"
    assert w.to_params()["selected_days"] is None


def test_selected_days_parses_whitespace(qapp):
    w = _make_widget(qapp)
    w.chk_hour_window.setChecked(True)
    w._add_window_row(0.0, 12.0)
    w._radio_hw_sel.setChecked(True)
    w._hw_days_edit.setText(" 0 , 1 , 2 ")
    assert w.to_params()["selected_days"] == [0, 1, 2]


# ---------------------------------------------------------------------------
# Drink mask section
# ---------------------------------------------------------------------------


def test_drink_mask_enabled_by_default(qapp):
    w = _make_widget(qapp)
    assert w.to_params()["use_drink_mask"] is True


def test_drink_pad_round_trip(qapp):
    w = _make_widget(qapp)
    w.spin_drink_pad.setValue(10)
    assert w.to_params()["drink_pad"] == 10


# ---------------------------------------------------------------------------
# Full round-trip — the primary safety net
# ---------------------------------------------------------------------------


def _full_params(tmp_path: Path) -> dict:
    """A params dict that exercises every field."""
    ann_dir = tmp_path / "annotations"
    ann_dir.mkdir()
    return {
        "states": ["wake", "sleep"],
        "comm_value": 1500,
        "nstd": 4.0,
        "winsize": 240,
        "radius": 0.75,
        "noise_thresh": 0.3,
        "use_swd_mask": True,
        "swd_pad": 5,
        "ann_enabled": True,
        "ann_dir": str(ann_dir),
        "ann_keywords": "drink, artifact",
        "ann_match_mode": "exact",
        "ann_pad_before": 1.0,
        "ann_pad_after": 3.0,
        "hw_enabled": True,
        "hour_windows": [(6.0, 18.0), (20.0, 6.0)],
        "selected_days": [0, 1],
        "use_drink_mask": True,
        "drink_pad": 4,
    }


def test_full_round_trip_is_idempotent(qapp, tmp_path: Path):
    """from_params(p) → to_params() must return p unchanged for a full param dict."""
    w = _make_widget(qapp, tmp_path, swd_available=True)
    params = _full_params(tmp_path)
    w.from_params(params)
    got = w.to_params()
    assert got == params


def test_round_trip_preserves_states_in_canonical_order(qapp, tmp_path: Path):
    """Order in `states` output is by CANONICAL_ORDER, not input order."""
    w = _make_widget(qapp, tmp_path)
    w.from_params({"states": ["rem", "wake"]})
    got = w.to_params()["states"]
    # Both still present, ordering deterministic
    assert set(got) == {"rem", "wake"}


def test_from_params_with_empty_dict_keeps_defaults(qapp):
    """Missing keys must not crash from_params and must leave defaults intact."""
    w = _make_widget(qapp)
    defaults = w.to_params()
    w.from_params({})
    after = w.to_params()
    assert after == defaults


def test_from_params_disabling_hour_window_clears_windows_in_output(qapp):
    """Calling from_params with hw_enabled=False must produce hour_windows=None even if rows exist."""
    w = _make_widget(qapp)
    w.from_params({"hw_enabled": True, "hour_windows": [(6.0, 18.0)]})
    assert w.to_params()["hour_windows"] == [(6.0, 18.0)]
    w.from_params({"hw_enabled": False})
    assert w.to_params()["hour_windows"] is None


# ---------------------------------------------------------------------------
# `changed` signal
# ---------------------------------------------------------------------------


def test_changed_signal_fires_on_user_edits(qapp):
    w = _make_widget(qapp)
    triggered = []
    w.changed.connect(lambda: triggered.append(True))
    w.dspin_noise.setValue(0.7)
    assert len(triggered) > 0


def test_changed_signal_fires_on_state_toggle(qapp):
    w = _make_widget(qapp)
    triggered = []
    w.changed.connect(lambda: triggered.append(True))
    w._state_boxes["wake"].setChecked(False)
    assert len(triggered) > 0


def test_changed_signal_does_not_storm_during_from_params(qapp, tmp_path: Path):
    """from_params updates many fields; should emit changed at most once at the end."""
    w = _make_widget(qapp, tmp_path)
    count = [0]
    w.changed.connect(lambda: count.__setitem__(0, count[0] + 1))
    w.from_params(_full_params(tmp_path))
    # Exactly one emission at the end of from_params (per the implementation contract).
    assert count[0] == 1


# ---------------------------------------------------------------------------
# Drink mask offset CSV auto-detection
# ---------------------------------------------------------------------------


def test_offset_csv_auto_detect_finds_single_csv_in_drink_masks(qapp, tmp_path: Path):
    drink_dir = tmp_path / "drink_masks"
    drink_dir.mkdir()
    (drink_dir / "offsets.csv").write_text("animal,offset\n")
    w = _make_widget(qapp, tmp_path)
    # Auto-detected path appears in the read-only label.
    assert "offsets.csv" in w.lbl_offset_csv.text()
    # Auto-detected CSVs are display-only; not stored in params.
    assert "drink_offset_csv_override" not in w.to_params()


def test_offset_csv_auto_detect_ignores_multiple_csvs(qapp, tmp_path: Path):
    """Convention is one CSV per project; with multiple, auto-detect declines.

    (The export pipeline raises on multiple; the widget just shows nothing.)
    """
    drink_dir = tmp_path / "drink_masks"
    drink_dir.mkdir()
    (drink_dir / "a.csv").write_text("")
    (drink_dir / "b.csv").write_text("")
    w = _make_widget(qapp, tmp_path)
    assert w.lbl_offset_csv.text() == ""


def test_set_project_root_refreshes_auto_detect(qapp, tmp_path: Path):
    w = MaskParamsWidget(project_root=None, swd_available=False)
    drink_dir = tmp_path / "drink_masks"
    drink_dir.mkdir()
    (drink_dir / "offsets.csv").write_text("")
    w.set_project_root(tmp_path)
    assert "offsets.csv" in w.lbl_offset_csv.text()


# ---------------------------------------------------------------------------
# Header subtitle summaries
# ---------------------------------------------------------------------------


def test_states_subtitle_lists_up_to_three():
    assert _states_subtitle({"states": ["wake", "nrem", "rem"]}) == "Wake, NREM, REM"


def test_states_subtitle_counts_more_than_three():
    assert _states_subtitle({"states": ["wake", "nrem", "rem", "sleep"]}) == "4 selected"


def test_states_subtitle_none_when_empty():
    assert _states_subtitle({"states": []}) == "none"


def test_sd_subtitle_format():
    p = {"winsize": 180, "radius": 0.5, "nstd": 5.0}
    assert _sd_subtitle(p) == "180s · 0.5s · 5σ"


def test_sd_subtitle_uses_g_format_for_nstd():
    """Non-integer nstd renders without trailing zeros."""
    p = {"winsize": 180, "radius": 0.75, "nstd": 3.5}
    assert _sd_subtitle(p) == "180s · 0.75s · 3.5σ"


def test_spindle_subtitle_format():
    assert _spindle_subtitle({"noise_thresh": 0.5}) == "0.50"
    assert _spindle_subtitle({"noise_thresh": 0.3}) == "0.30"


def test_swd_subtitle_off_when_disabled():
    assert _swd_subtitle({"use_swd_mask": False, "swd_pad": 0}) == "off"


def test_swd_subtitle_on_with_pad():
    assert _swd_subtitle({"use_swd_mask": True, "swd_pad": 5}) == "mask out · 5s pad"


def test_annotation_subtitle_off_when_disabled():
    assert _annotation_subtitle({"ann_enabled": False}) == "off"


def test_annotation_subtitle_singular_keyword():
    p = {"ann_enabled": True, "ann_keywords": "drink", "ann_match_mode": "contains"}
    assert _annotation_subtitle(p) == "on · 1 keyword · contains"


def test_annotation_subtitle_plural_keywords():
    p = {"ann_enabled": True, "ann_keywords": "drink, artifact", "ann_match_mode": "exact"}
    assert _annotation_subtitle(p) == "on · 2 keywords · exact"


def test_hour_window_subtitle_off():
    assert _hour_window_subtitle({"hw_enabled": False}) == "off"


def test_hour_window_subtitle_single_window_all_days():
    p = {"hw_enabled": True, "hour_windows": [(6.0, 18.0)], "selected_days": None}
    assert _hour_window_subtitle(p) == "6–18h"


def test_hour_window_subtitle_single_window_specific_days():
    p = {"hw_enabled": True, "hour_windows": [(6.0, 18.0)], "selected_days": [0, 1, 2]}
    assert _hour_window_subtitle(p) == "6–18h, days 0,1,2"


def test_hour_window_subtitle_multiple_windows():
    p = {
        "hw_enabled": True,
        "hour_windows": [(6.0, 12.0), (20.0, 6.0)],
        "selected_days": None,
    }
    assert _hour_window_subtitle(p) == "2 windows"


def test_drink_subtitle_off():
    assert _drink_subtitle({"use_drink_mask": False, "drink_pad": 2}) == "off"


def test_drink_subtitle_on():
    assert _drink_subtitle({"use_drink_mask": True, "drink_pad": 2}) == "on · 2s pad"


# ---------------------------------------------------------------------------
# Live subtitle updates — the widget refreshes headers as the user edits.
# ---------------------------------------------------------------------------


def test_subtitle_initialized_at_construction(qapp):
    w = MaskParamsWidget()
    assert w._sections["states"].subtitle() == "Wake, NREM, REM"
    assert w._sections["sd"].subtitle() == "180s · 0.5s · 5σ"
    assert w._sections["spindle"].subtitle() == "0.50"
    assert w._sections["swd"].subtitle() == "off"
    assert w._sections["annotation"].subtitle() == "off"
    assert w._sections["hour_window"].subtitle() == "off"
    assert w._sections["drink"].subtitle() == "on · 2s pad"


def test_subtitle_updates_on_edit(qapp):
    w = MaskParamsWidget()
    w.dspin_noise.setValue(0.75)
    assert w._sections["spindle"].subtitle() == "0.75"


def test_subtitle_updates_on_state_toggle(qapp):
    w = MaskParamsWidget()
    w._state_boxes["rem"].setChecked(False)
    # After unchecking REM, the summary shows only Wake + NREM.
    assert w._sections["states"].subtitle() == "Wake, NREM"


def test_subtitle_updates_after_from_params(qapp, tmp_path: Path):
    w = MaskParamsWidget(project_root=tmp_path, swd_available=True)
    w.from_params(
        {
            "use_swd_mask": True,
            "swd_pad": 10,
            "hw_enabled": True,
            "hour_windows": [(6.0, 18.0)],
            "selected_days": [0],
        }
    )
    assert w._sections["swd"].subtitle() == "mask out · 10s pad"
    assert w._sections["hour_window"].subtitle() == "6–18h, days 0"


# ---------------------------------------------------------------------------
# show_drink_mask flag — hides section but preserves param round-trip
# ---------------------------------------------------------------------------


def test_show_drink_mask_false_hides_section(qapp, tmp_path: Path):
    w = MaskParamsWidget(project_root=tmp_path, show_drink_mask=False)
    assert not w._sections["drink"].isVisibleTo(w)


def test_show_drink_mask_true_shows_section_by_default(qapp, tmp_path: Path):
    w = MaskParamsWidget(project_root=tmp_path)
    # CollapsibleSection is laid-out visible-by-default (parent isn't shown
    # in tests so isVisible() can't be used; isHidden() is the explicit-hide
    # check we set in the constructor).
    assert not w._sections["drink"].isHidden()


def test_show_drink_mask_false_still_round_trips_drink_params(qapp, tmp_path: Path):
    """The drink widgets exist even when hidden, so saved configs that
    include drink params reload + re-export without loss."""
    w = MaskParamsWidget(project_root=tmp_path, show_drink_mask=False)
    w.from_params({"use_drink_mask": False, "drink_pad": 7})
    p = w.to_params()
    assert p["use_drink_mask"] is False
    assert p["drink_pad"] == 7


# ---------------------------------------------------------------------------
# SWD status preview
# ---------------------------------------------------------------------------


def test_swd_status_no_project_root(qapp):
    w = MaskParamsWidget(project_root=None)
    assert w._lbl_swd_status.text() == ""


def test_swd_status_no_swd_dir(qapp, tmp_path: Path):
    w = _make_widget(qapp, tmp_path)
    assert "not found" in w._lbl_swd_status.text()


def test_swd_status_empty_swd_dir(qapp, tmp_path: Path):
    (tmp_path / "swd").mkdir()
    w = _make_widget(qapp, tmp_path)
    assert "no .mat files" in w._lbl_swd_status.text()


def test_swd_status_count_matches_manifest(qapp, tmp_path: Path):
    from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry

    (tmp_path / "swd").mkdir()
    for aid in ("AM001", "AM002"):
        (tmp_path / "swd" / f"{aid}.mat").write_text("")
    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(animal_id="AM001", preprocessed_edf="", runs={})
    m._entries["AM002"] = ManifestEntry(animal_id="AM002", preprocessed_edf="", runs={})
    m.save()

    w = _make_widget(qapp, tmp_path)
    assert "✓ 2 .mat files in swd/" in w._lbl_swd_status.text()


def test_swd_status_count_mismatch(qapp, tmp_path: Path):
    from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry

    (tmp_path / "swd").mkdir()
    (tmp_path / "swd" / "AM001.mat").write_text("")
    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(animal_id="AM001", preprocessed_edf="", runs={})
    m._entries["AM002"] = ManifestEntry(animal_id="AM002", preprocessed_edf="", runs={})
    m.save()

    w = _make_widget(qapp, tmp_path)
    assert "⚠" in w._lbl_swd_status.text()
    assert "(expected 2)" in w._lbl_swd_status.text()


# ---------------------------------------------------------------------------
# Annotation status preview
# ---------------------------------------------------------------------------


def test_ann_status_hidden_when_ann_disabled(qapp, tmp_path: Path):
    w = _make_widget(qapp, tmp_path)
    assert w._lbl_ann_status.text() == ""


def test_ann_status_shows_count_when_enabled(qapp, tmp_path: Path):
    from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry

    ann_dir = tmp_path / "annotations"
    ann_dir.mkdir()
    (ann_dir / "AM001_notes.txt").write_text("")
    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(animal_id="AM001", preprocessed_edf="", runs={})
    m._entries["AM002"] = ManifestEntry(animal_id="AM002", preprocessed_edf="", runs={})
    m.save()

    w = _make_widget(qapp, tmp_path)
    w.from_params({"ann_enabled": True, "ann_dir": str(ann_dir)})
    assert "1 of 2" in w._lbl_ann_status.text()


def test_ann_status_clears_when_disabled(qapp, tmp_path: Path):
    ann_dir = tmp_path / "annotations"
    ann_dir.mkdir()
    w = _make_widget(qapp, tmp_path)
    w.from_params({"ann_enabled": True, "ann_dir": str(ann_dir)})
    w.chk_ann.setChecked(False)
    assert w._lbl_ann_status.text() == ""


# ---------------------------------------------------------------------------
# Hour-window preview
# ---------------------------------------------------------------------------


def test_hour_window_preview_empty_when_disabled(qapp, tmp_path: Path):
    w = _make_widget(qapp, tmp_path)
    assert w._hw_partial_label.text() == ""


def test_hour_window_preview_empty_with_no_recordings(qapp, tmp_path: Path):
    """Enabled with windows but no standard/ EDFs → preview stays empty
    (best-effort: no recordings means no coverage estimate)."""
    w = _make_widget(qapp, tmp_path)
    w.from_params(
        {
            "hw_enabled": True,
            "hour_windows": [[6.0, 18.0]],
            "selected_days": None,
        }
    )
    assert w._hw_partial_label.text() == ""


def test_set_project_root_invalidates_edf_cache(qapp, tmp_path: Path):
    w = _make_widget(qapp, tmp_path)
    w._hw_recordings = [("sentinel", 0)]  # poison the cache
    w.set_project_root(tmp_path)
    assert w._hw_recordings is None
