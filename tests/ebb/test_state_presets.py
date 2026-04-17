"""Tests for ebb.process.state_presets — preset→labels translation,
canonical ordering, and the default/error contract.
"""

import pytest

from ebb.process.state_presets import (
    CANONICAL_ORDER,
    DEFAULT_STATES,
    PRESET_DESCRIPTIONS,
    PRESET_DISPLAY,
    STATE_PRESETS,
    canonical_sort_states,
    labels_from_presets,
)


# ---------------------------------------------------------------------------
# STATE_PRESETS shape
# ---------------------------------------------------------------------------

def test_state_presets_has_all_five_keys():
    assert set(STATE_PRESETS) == {"wake", "nrem", "rem", "sleep", "all"}


def test_state_presets_single_state_groups():
    assert STATE_PRESETS["wake"] == ["w"]
    assert STATE_PRESETS["nrem"] == ["n"]
    assert STATE_PRESETS["rem"] == ["r"]


def test_state_presets_lumped_groups():
    assert sorted(STATE_PRESETS["sleep"]) == ["n", "r"]
    assert sorted(STATE_PRESETS["all"]) == ["n", "r", "w"]


def test_default_states_is_wake_nrem_rem():
    assert DEFAULT_STATES == ("wake", "nrem", "rem")


def test_canonical_order_starts_with_single_states():
    assert CANONICAL_ORDER[:3] == ("wake", "nrem", "rem")


def test_every_preset_has_display_and_description():
    for key in STATE_PRESETS:
        assert key in PRESET_DISPLAY
        assert key in PRESET_DESCRIPTIONS
        assert PRESET_DISPLAY[key]
        assert PRESET_DESCRIPTIONS[key]


# ---------------------------------------------------------------------------
# labels_from_presets
# ---------------------------------------------------------------------------

def test_labels_from_presets_default():
    labels = labels_from_presets(DEFAULT_STATES)
    assert labels == {"wake": ["w"], "nrem": ["n"], "rem": ["r"]}


def test_labels_from_presets_single_group():
    assert labels_from_presets(["sleep"]) == {"sleep": ["n", "r"]}


def test_labels_from_presets_mixed_single_and_lumped():
    labels = labels_from_presets(["wake", "sleep"])
    assert labels == {"wake": ["w"], "sleep": ["n", "r"]}


def test_labels_from_presets_all_group():
    assert labels_from_presets(["all"]) == {"all": ["w", "n", "r"]}


def test_labels_from_presets_preserves_iteration_order():
    """Caller-supplied order flows into the returned dict (Python 3.7+ dict order)."""
    labels = labels_from_presets(["rem", "wake", "nrem"])
    assert list(labels.keys()) == ["rem", "wake", "nrem"]


def test_labels_from_presets_returns_copies_not_aliases():
    """Mutating the returned lists must not alter STATE_PRESETS."""
    labels = labels_from_presets(["sleep"])
    labels["sleep"].append("x")
    assert STATE_PRESETS["sleep"] == ["n", "r"]


def test_labels_from_presets_unknown_key_raises():
    with pytest.raises(KeyError):
        labels_from_presets(["wake", "bogus"])


def test_labels_from_presets_empty_raises():
    with pytest.raises(ValueError):
        labels_from_presets([])


def test_labels_from_presets_accepts_any_iterable():
    assert labels_from_presets(iter(["wake"])) == {"wake": ["w"]}


def test_labels_from_presets_duplicates_collapse_to_last():
    """A user who somehow supplies duplicates still gets a valid dict."""
    labels = labels_from_presets(["wake", "wake"])
    assert labels == {"wake": ["w"]}


# ---------------------------------------------------------------------------
# canonical_sort_states
# ---------------------------------------------------------------------------

def test_canonical_sort_default_three():
    assert canonical_sort_states(["rem", "nrem", "wake"]) == ["wake", "nrem", "rem"]


def test_canonical_sort_includes_sleep_after_rem():
    # sleep/all come after single states in canonical order
    assert canonical_sort_states(["sleep", "wake"]) == ["wake", "sleep"]
    assert canonical_sort_states(["all", "nrem", "wake"]) == ["wake", "nrem", "all"]


def test_canonical_sort_unknown_keys_appended_alphabetically():
    result = canonical_sort_states(["zzzz", "aaa", "wake"])
    assert result == ["wake", "aaa", "zzzz"]


def test_canonical_sort_empty():
    assert canonical_sort_states([]) == []


def test_canonical_sort_tolerates_duplicates():
    assert canonical_sort_states(["wake", "wake", "nrem"]) == ["wake", "nrem"]
