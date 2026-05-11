"""Tests for `_prepare_estimator_kwargs` — the param-dict translation layer.

These guard against the most dangerous failure mode in the PSD pipeline:
a saved psd_params.json (or a fresh widget-emitted dict) reaching
`estimate_psd` with extra UI-only kwargs that would either:
- raise TypeError ("got unexpected kwarg X"), aborting the run
- shadow a real param with a wrongly-named value (silent miscomputation)

Particular attention to keys emitted by the new MaskParamsWidget
(use_swd_mask, use_drink_mask, swd_pad, drink_offset_csv_override,
ann_pad_before, ann_pad_after, ann_dir).
"""

from ebb.process.psd_compute import _UI_ONLY_KWARGS, _prepare_estimator_kwargs

# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_prepare_kwargs_returns_tuple_of_four():
    kwargs, hw, days, ann_by_animal = _prepare_estimator_kwargs({})
    assert kwargs == {}
    assert hw is None
    assert days is None
    assert ann_by_animal == {}


def test_prepare_kwargs_passes_through_estimator_kwargs():
    kwargs, _, _, _ = _prepare_estimator_kwargs(
        {"fs": 250, "winsize": 180, "nstd": 5, "noise_thresh": 0.5}
    )
    # All of these are real estimate_psd kwargs and must survive.
    assert kwargs == {"fs": 250, "winsize": 180, "nstd": 5, "noise_thresh": 0.5}


# ---------------------------------------------------------------------------
# UI-only kwargs are stripped
# ---------------------------------------------------------------------------


def test_strips_all_known_ui_only_kwargs():
    """Every key in _UI_ONLY_KWARGS must be removed from kwargs before forwarding."""
    raw = {key: "sentinel" for key in _UI_ONLY_KWARGS}
    raw["fs"] = 250  # a real kwarg sentinel; must survive
    kwargs, _, _, _ = _prepare_estimator_kwargs(raw)
    for key in _UI_ONLY_KWARGS:
        assert key not in kwargs, f"UI-only key {key!r} leaked into estimator kwargs"
    assert kwargs.get("fs") == 250


def test_strips_widget_emitted_swd_keys():
    """MaskParamsWidget emits both swd_mode and use_swd_mask; both must be stripped."""
    kwargs, _, _, _ = _prepare_estimator_kwargs(
        {"swd_mode": "mask_out", "use_swd_mask": True, "swd_pad": 5, "fs": 250}
    )
    assert "swd_mode" not in kwargs
    assert "use_swd_mask" not in kwargs
    assert "swd_pad" not in kwargs
    assert kwargs["fs"] == 250


def test_strips_widget_emitted_drink_keys():
    """use_drink_mask + drink_offset_csv_override are widget-only; estimate_psd uses drink_path."""
    kwargs, _, _, _ = _prepare_estimator_kwargs(
        {
            "use_drink_mask": False,
            "drink_offset_csv_override": "/foo/bar.csv",
            "drink_pad": 2,
            "fs": 250,
        }
    )
    assert "use_drink_mask" not in kwargs
    assert "drink_offset_csv_override" not in kwargs
    # drink_pad IS a real estimate_psd kwarg and must NOT be stripped.
    assert kwargs.get("drink_pad") == 2


def test_strips_widget_annotation_pad_keys_distinct_from_estimator_keys():
    """Widget emits ann_pad_before/after; estimate_psd wants ann_pad_before_sec/after_sec.
    The widget keys must be stripped so they don't collide.
    """
    kwargs, _, _, _ = _prepare_estimator_kwargs(
        {
            "ann_enabled": True,
            "ann_dir": "/some/dir",
            "ann_keywords": "drink",  # widget shape (string, not list)
            "ann_match_mode": "contains",
            "ann_pad_before": 1.0,
            "ann_pad_after": 2.0,
            "fs": 250,
        }
    )
    for k in (
        "ann_enabled",
        "ann_dir",
        "ann_keywords",
        "ann_match_mode",
        "ann_pad_before",
        "ann_pad_after",
    ):
        assert k not in kwargs, f"widget annotation key {k!r} leaked into estimator kwargs"


# ---------------------------------------------------------------------------
# Annotation params get re-keyed correctly
# ---------------------------------------------------------------------------


def test_ann_params_re_keyed_to_estimator_shape():
    """The page-built ann_params dict spreads into kwargs with the correct *_sec suffix."""
    kwargs, _, _, _ = _prepare_estimator_kwargs(
        {"fs": 250},
        ann_params={
            "ann_dir": "/some/dir",
            "keywords": ["drink", "artifact"],
            "match_mode": "exact",
            "pad_before_sec": 1.0,
            "pad_after_sec": 2.0,
        },
    )
    assert kwargs["ann_keywords"] == ["drink", "artifact"]
    assert kwargs["ann_match_mode"] == "exact"
    assert kwargs["ann_pad_before_sec"] == 1.0
    assert kwargs["ann_pad_after_sec"] == 2.0


def test_ann_params_none_does_not_inject_annotation_kwargs():
    kwargs, _, _, _ = _prepare_estimator_kwargs({"fs": 250}, ann_params=None)
    assert "ann_keywords" not in kwargs
    assert "ann_match_mode" not in kwargs


# ---------------------------------------------------------------------------
# Hour windows are extracted out of kwargs
# ---------------------------------------------------------------------------


def test_hour_windows_extracted_from_kwargs():
    kwargs, hw, days, _ = _prepare_estimator_kwargs(
        {"hour_windows": [(6, 18)], "selected_days": [0, 1], "fs": 250}
    )
    assert hw == [(6, 18)]
    assert days == [0, 1]
    assert "hour_windows" not in kwargs
    assert "selected_days" not in kwargs


def test_legacy_hour_window_singular_migrates_to_plural():
    """Old saves used a single (start, end) under 'hour_window'; new code expects list."""
    kwargs, hw, _, _ = _prepare_estimator_kwargs({"hour_window": [6, 18], "fs": 250})
    assert hw == [(6, 18)]
    assert "hour_window" not in kwargs


def test_explicit_hour_windows_wins_over_legacy_hour_window():
    """If both keys are present, the new key wins and legacy is silently dropped."""
    kwargs, hw, _, _ = _prepare_estimator_kwargs(
        {"hour_windows": [(20, 6)], "hour_window": [0, 12], "fs": 250}
    )
    assert hw == [(20, 6)]
    assert "hour_window" not in kwargs


# ---------------------------------------------------------------------------
# States preset → labels translation
# ---------------------------------------------------------------------------


def test_states_translated_to_labels():
    kwargs, _, _, _ = _prepare_estimator_kwargs({"states": ["wake", "nrem", "rem"], "fs": 250})
    assert "states" not in kwargs
    assert "labels" in kwargs
    # labels dict maps display_name → underlying state codes
    assert set(kwargs["labels"]) == {"wake", "nrem", "rem"}


def test_explicit_labels_wins_over_states():
    """If both states= and labels= are present, labels wins (advanced override)."""
    kwargs, _, _, _ = _prepare_estimator_kwargs(
        {"states": ["wake"], "labels": {"custom": ["w"]}, "fs": 250}
    )
    assert kwargs["labels"] == {"custom": ["w"]}


# ---------------------------------------------------------------------------
# Full widget → estimator end-to-end shape
# ---------------------------------------------------------------------------


def test_full_widget_emitted_dict_does_not_crash_estimator_kwargs_prep():
    """A complete widget-emitted dict (as in psd_params.json) survives kwargs prep."""
    widget_dict = {
        # Real estimate_psd kwargs
        "fs": 250,
        "winsize": 180,
        "radius": 0.5,
        "nstd": 5.0,
        "noise_thresh": 0.5,
        "drink_pad": 2,
        "channels": [0, 1, 2],
        "states": ["wake", "nrem"],
        # UI-only / widget-only
        "swd_mode": "mask_out",
        "use_swd_mask": True,
        "swd_pad": 5,
        "use_drink_mask": True,
        "drink_offset_csv_override": None,
        "ann_enabled": True,
        "ann_dir": "/some/dir",
        "ann_keywords": "drink",
        "ann_match_mode": "contains",
        "ann_pad_before": 1.0,
        "ann_pad_after": 2.0,
        "hw_enabled": True,
        "hour_windows": [(6, 18)],
        "selected_days": [0, 1],
    }
    kwargs, hw, days, _ = _prepare_estimator_kwargs(widget_dict)

    # Real estimator kwargs survived
    for real_key in ("fs", "winsize", "radius", "nstd", "noise_thresh", "drink_pad", "channels"):
        assert real_key in kwargs, f"real estimator kwarg {real_key!r} was incorrectly stripped"

    # All UI-only keys gone
    ui_only = [
        "swd_mode",
        "use_swd_mask",
        "swd_pad",
        "use_drink_mask",
        "drink_offset_csv_override",
        "ann_enabled",
        "ann_dir",
        "ann_pad_before",
        "ann_pad_after",
        "hw_enabled",
        "states",
        "hour_windows",
        "selected_days",
    ]
    for ui_key in ui_only:
        assert ui_key not in kwargs, f"UI-only key {ui_key!r} leaked into estimator kwargs"

    # Hour windows extracted to positional return
    assert hw == [(6, 18)]
    assert days == [0, 1]
