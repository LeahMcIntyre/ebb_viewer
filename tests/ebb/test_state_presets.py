"""Tests for ebb.process.state_presets — preset→labels translation,
canonical ordering, and the default/error contract.
"""

import pytest

from ebb.process.state_presets import (
    CANONICAL_ORDER,
    DEFAULT_STATES,
    PRESET_DESCRIPTIONS,
    PRESET_DISPLAY,
    RAW_CODE_DISPLAY,
    STATE_PRESETS,
    canonical_sort_states,
    gather_states_from_store,
    labels_from_presets,
    overlap_groups,
)


class _FakeStore:
    """Minimal PSDStore stub matching the animals()/states(animal) surface."""

    def __init__(self, per_animal: dict):
        self._data = per_animal

    def animals(self):
        return list(self._data.keys())

    def states(self, animal):
        return list(self._data[animal])


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


def test_canonical_sort_mixes_presets_and_custom_names():
    """Custom (non-preset) names come after all canonical presets, alphabetized."""
    result = canonical_sort_states(["my_custom", "wake", "sleep", "another"])
    assert result == ["wake", "sleep", "another", "my_custom"]


# ---------------------------------------------------------------------------
# overlap_groups
# ---------------------------------------------------------------------------


def test_overlap_groups_none_when_disjoint():
    assert overlap_groups(["wake", "nrem", "rem"]) == {}


def test_overlap_groups_none_for_single_selection():
    assert overlap_groups(["sleep"]) == {}


def test_overlap_groups_rem_shared_between_rem_and_sleep():
    assert overlap_groups(["rem", "sleep"]) == {"r": ["rem", "sleep"]}


def test_overlap_groups_all_overlaps_everything_selected():
    out = overlap_groups(["wake", "nrem", "rem", "sleep", "all"])
    assert out == {
        "w": ["wake", "all"],
        "n": ["nrem", "sleep", "all"],
        "r": ["rem", "sleep", "all"],
    }


def test_overlap_groups_preserves_input_order():
    out = overlap_groups(["sleep", "rem"])
    assert out == {"r": ["sleep", "rem"]}


def test_overlap_groups_ignores_unknown_keys():
    assert overlap_groups(["rem", "sleep", "bogus"]) == {"r": ["rem", "sleep"]}


def test_raw_code_display_covers_all_preset_codes():
    """Every raw code referenced by STATE_PRESETS has a display name."""
    all_codes = {c for codes in STATE_PRESETS.values() for c in codes}
    assert all_codes <= set(RAW_CODE_DISPLAY)


# ---------------------------------------------------------------------------
# gather_states_from_store — locks PSDGridPage panel ordering
# ---------------------------------------------------------------------------


def test_gather_states_from_store_canonical_presets():
    store = _FakeStore({"m1": ["rem", "wake"], "m2": ["nrem", "wake"]})
    assert gather_states_from_store(store) == ["wake", "nrem", "rem"]


def test_gather_states_from_store_empty_store_falls_back_to_defaults():
    assert gather_states_from_store(_FakeStore({})) == ["wake", "nrem", "rem"]


def test_gather_states_from_store_mixed_presets_and_custom_names():
    """Custom group names trail canonical presets in alphabetical order."""
    store = _FakeStore(
        {
            "m1": ["sleep", "zebra_group"],
            "m2": ["wake", "alpha_group"],
        }
    )
    assert gather_states_from_store(store) == [
        "wake",
        "sleep",
        "alpha_group",
        "zebra_group",
    ]


def test_gather_states_from_store_only_custom_names():
    store = _FakeStore({"m1": ["beta", "alpha"]})
    assert gather_states_from_store(store) == ["alpha", "beta"]
