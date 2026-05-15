"""Preset groupings of Spindle sleep-state codes for PSD computation.

Each preset maps a canonical group name to the list of Spindle rawstate codes
that should be lumped together into a single mask (and therefore a single PSD)
when that preset is selected.

The UI offers these as multi-select checkboxes. Selected presets are persisted
in psd_params.json as a list of keys (e.g. ["wake", "nrem", "rem"]) and
translated to a ``labels`` dict at call time via :func:`labels_from_presets`.
"""

from collections.abc import Iterable

RAW_CODE_DISPLAY: dict[str, str] = {
    "w": "Wake",
    "n": "NREM",
    "r": "REM",
}


STATE_PRESETS: dict[str, list[str]] = {
    "wake": ["w"],
    "nrem": ["n"],
    "rem": ["r"],
    "sleep": ["n", "r"],
    "all": ["w", "n", "r"],
}

DEFAULT_STATES: tuple[str, ...] = ("wake", "nrem", "rem")

PRESET_DESCRIPTIONS: dict[str, str] = {
    "wake": "Wake epochs only",
    "nrem": "NREM epochs only",
    "rem": "REM epochs only",
    "sleep": "One PSD computed over NREM + REM epochs combined",
    "all": "One PSD computed over Wake + NREM + REM epochs combined",
}

PRESET_DISPLAY: dict[str, str] = {
    "wake": "Wake",
    "nrem": "NREM",
    "rem": "REM",
    "sleep": "Sleep (NREM+REM)",
    "all": "All (Wake+NREM+REM)",
}

CANONICAL_ORDER: tuple[str, ...] = ("wake", "nrem", "rem", "sleep", "all")


def labels_from_presets(preset_keys: Iterable[str]) -> dict[str, list[str]]:
    """Build an ``estimate_psd`` labels dict from an iterable of preset keys.

    Unknown keys raise ``KeyError`` so typos in saved params don't silently
    produce an empty labels dict (which would compute no PSDs).
    """
    keys = list(preset_keys)
    if not keys:
        raise ValueError("At least one state preset must be selected.")
    labels: dict[str, list[str]] = {}
    for k in keys:
        if k not in STATE_PRESETS:
            raise KeyError(f"Unknown state preset: {k!r}")
        labels[k] = list(STATE_PRESETS[k])
    return labels


def overlap_groups(preset_keys: Iterable[str]) -> dict[str, list[str]]:
    """Return raw epoch codes that appear in more than one selected group.

    Maps each shared code (e.g. ``"r"``) to the list of preset keys that
    contain it, in the caller-supplied iteration order. Useful for surfacing
    to the UI that, say, REM epochs will feed into both a REM-only PSD and a
    lumped Sleep PSD when both groups are selected.

    Unknown preset keys are silently ignored (so a typo in saved params
    doesn't crash this UI helper — `labels_from_presets` is the strict path).
    """
    code_to_groups: dict[str, list[str]] = {}
    for key in preset_keys:
        codes = STATE_PRESETS.get(key)
        if codes is None:
            continue
        for code in codes:
            groups = code_to_groups.setdefault(code, [])
            if key not in groups:
                groups.append(key)
    return {code: groups for code, groups in code_to_groups.items() if len(groups) > 1}


def canonical_sort_states(names: Iterable[str]) -> list[str]:
    """Sort state names: presets in canonical order first, then alphabetical."""
    seen = set(names)
    ordered = [n for n in CANONICAL_ORDER if n in seen]
    extras = sorted(n for n in seen if n not in CANONICAL_ORDER)
    return ordered + extras


def gather_states_from_store(store) -> list[str]:
    """Union of state names across all animals in ``store``, canonically sorted.

    Args:
        store: Any object exposing ``animals() -> Iterable[str]`` and
            ``states(animal) -> Iterable[str]`` (matches the
            `ebb_viewer.data_stores.psd_store.PSDStore` interface).

    Returns:
        Sorted list of state names. Falls back to the three single-state
        presets (wake/nrem/rem) when the store is empty — keeps the PSD
        grid page usable even when no PSDs have been computed yet.
    """
    found: set[str] = set()
    for animal in store.animals():
        found.update(store.states(animal))
    if not found:
        return list(CANONICAL_ORDER[:3])
    return canonical_sort_states(found)
