"""Preset groupings of Spindle sleep-state codes for PSD computation.

Each preset maps a canonical group name to the list of Spindle rawstate codes
that should be lumped together into a single mask (and therefore a single PSD)
when that preset is selected.

The UI offers these as multi-select checkboxes. Selected presets are persisted
in psd_params.json as a list of keys (e.g. ["wake", "nrem", "rem"]) and
translated to a ``labels`` dict at call time via :func:`labels_from_presets`.
"""

from typing import Dict, Iterable, List, Tuple


STATE_PRESETS: Dict[str, List[str]] = {
    "wake":  ["w"],
    "nrem":  ["n"],
    "rem":   ["r"],
    "sleep": ["n", "r"],
    "all":   ["w", "n", "r"],
}

DEFAULT_STATES: Tuple[str, ...] = ("wake", "nrem", "rem")

PRESET_DESCRIPTIONS: Dict[str, str] = {
    "wake":  "Wake epochs only",
    "nrem":  "NREM epochs only",
    "rem":   "REM epochs only",
    "sleep": "NREM and REM epochs lumped into one PSD",
    "all":   "Wake, NREM, and REM epochs lumped into one PSD",
}

PRESET_DISPLAY: Dict[str, str] = {
    "wake":  "Wake",
    "nrem":  "NREM",
    "rem":   "REM",
    "sleep": "Sleep (NREM+REM)",
    "all":   "All (Wake+NREM+REM)",
}

CANONICAL_ORDER: Tuple[str, ...] = ("wake", "nrem", "rem", "sleep", "all")


def labels_from_presets(preset_keys: Iterable[str]) -> Dict[str, List[str]]:
    """Build an ``estimate_psd`` labels dict from an iterable of preset keys.

    Unknown keys raise ``KeyError`` so typos in saved params don't silently
    produce an empty labels dict (which would compute no PSDs).
    """
    keys = list(preset_keys)
    if not keys:
        raise ValueError("At least one state preset must be selected.")
    labels: Dict[str, List[str]] = {}
    for k in keys:
        if k not in STATE_PRESETS:
            raise KeyError(f"Unknown state preset: {k!r}")
        labels[k] = list(STATE_PRESETS[k])
    return labels


def canonical_sort_states(names: Iterable[str]) -> List[str]:
    """Sort state names: presets in canonical order first, then alphabetical."""
    seen = set(names)
    ordered = [n for n in CANONICAL_ORDER if n in seen]
    extras = sorted(n for n in seen if n not in CANONICAL_ORDER)
    return ordered + extras
