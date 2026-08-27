"""Column-name resolution for SPINDLE-scored CSVs.

SleepyRat's output columns changed between versions. The old format stores
the clean per-epoch state (`w`/`n`/`r`) under `rawstate` and the artifact-
coded value under `state`; the new format has only `state`, holding the
same clean values `rawstate` used to. Noise probability moved from
`noise_probs` (old) to `noise_prob` (new). ebb needs to keep reading both,
since old-format files already exist on disk alongside new ones.
"""

from collections.abc import Sequence

# Order matters: `rawstate` must win when both are present (old format),
# since old `state` can hold artifact codes (`1`/`2`/`3`) instead of a
# clean state value.
STATE_COLUMNS = ("rawstate", "state")
NOISE_COLUMNS = ("noise_probs", "noise_prob")


def resolve_column(header: Sequence[str], candidates: Sequence[str]) -> str:
    """Return the first of `candidates` present in `header`.

    Raises:
        ValueError: if none of `candidates` are present in `header`.
    """
    for name in candidates:
        if name in header:
            return name
    raise ValueError(f"None of {list(candidates)} found in CSV header {list(header)}")
