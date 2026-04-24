"""Tests for psd_params state persistence and back-compat.

Covers save/load round-trip of the ``states`` field and the ``states_from_params``
helper's default-and-filter behavior for legacy params.
"""

import json
from pathlib import Path

import pytest

from ebb_viewer.pipeline import psd_params


def test_save_includes_states(tmp_path):
    params = {"fs": 250, "channels": [0, 1, 2], "states": ["wake", "sleep"]}
    psd_params.save(tmp_path, "run1", params)

    loaded = psd_params.load(tmp_path, "run1")
    assert loaded["states"] == ["wake", "sleep"]


def test_save_preserves_unknown_keys_untouched(tmp_path):
    """save/load shouldn't strip arbitrary keys; future-proof against API drift."""
    params = {"fs": 250, "states": ["nrem"], "future_key": "future_value"}
    psd_params.save(tmp_path, "r", params)
    loaded = psd_params.load(tmp_path, "r")
    assert loaded["future_key"] == "future_value"
    assert loaded["states"] == ["nrem"]


def test_states_from_params_returns_saved_list(tmp_path):
    params = {"states": ["wake", "nrem", "sleep"]}
    assert psd_params.states_from_params(params) == ["wake", "nrem", "sleep"]


def test_states_from_params_defaults_when_field_missing():
    """Legacy params written before state selection default to wake/nrem/rem."""
    assert psd_params.states_from_params({"fs": 250}) == ["wake", "nrem", "rem"]


def test_states_from_params_defaults_on_none():
    assert psd_params.states_from_params(None) == ["wake", "nrem", "rem"]


def test_states_from_params_empty_list_treated_as_default():
    """An empty list is treated as 'unset' (better than computing zero PSDs)."""
    assert psd_params.states_from_params({"states": []}) == ["wake", "nrem", "rem"]


def test_states_from_params_filters_unknown_keys():
    """Unknown keys in a hand-edited json don't propagate into callers."""
    out = psd_params.states_from_params({"states": ["wake", "bogus", "rem"]})
    assert out == ["wake", "rem"]


def test_states_from_params_all_unknown_filters_to_empty():
    """If every key is unknown, return empty — caller gets to decide what to do.

    This intentionally differs from the None/missing case because explicit
    garbage is signal the caller should notice, not silent-default to
    wake/nrem/rem.
    """
    assert psd_params.states_from_params({"states": ["foo", "bar"]}) == []


def test_roundtrip_back_compat_for_legacy_run(tmp_path):
    """A run_params.json without a states field loads fine, and
    states_from_params fills the default — matching production flow."""
    run_dir = tmp_path / "psd" / "legacy"
    run_dir.mkdir(parents=True)
    (run_dir / "psd_params.json").write_text(json.dumps({"fs": 250, "winsize": 180}))

    loaded = psd_params.load(tmp_path, "legacy")
    assert "states" not in loaded
    assert psd_params.states_from_params(loaded) == ["wake", "nrem", "rem"]


def test_list_runs_unaffected_by_states_field(tmp_path):
    psd_params.save(tmp_path, "a", {"fs": 250, "states": ["wake"]})
    psd_params.save(tmp_path, "b", {"fs": 250})
    assert psd_params.list_runs(tmp_path) == ["a", "b"]
