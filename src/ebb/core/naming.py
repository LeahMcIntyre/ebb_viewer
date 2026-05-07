"""Canonical helpers for parsing identifiers out of project file paths.

Animal IDs are encoded as the leading token of every project filename
(EDFs, SPINDLE CSVs, SWD MATs, drink-mask NPYs, annotation files), up to
the first underscore. `parse_animal_id` is the single source of truth.
"""

import re
from pathlib import Path

_ANIMAL_ID_RE = re.compile(r"[^_]+")


def parse_animal_id(path: str | Path) -> str:
    """Return the animal ID from a project file path.

    The animal ID is the leading run of non-underscore characters in the
    file's stem. Matches the project's filename convention
    `<animal_id>_<rest>.<ext>` (e.g. `AM0185_6wk_PREPROCESSED.edf` →
    `"AM0185"`). Hyphenated IDs like `"Mice-1234"` are preserved.

    Args:
        path: Path-like whose stem encodes the animal ID.

    Returns:
        The leading non-underscore token, or the full stem if the stem
        contains no non-underscore characters at the start (degenerate
        input — should not occur in practice).
    """
    stem = Path(path).stem
    m = _ANIMAL_ID_RE.match(stem)
    return m.group(0) if m else stem
