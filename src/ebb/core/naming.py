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


def files_for_animal(directory: str | Path, animal_id: str, *endings: str) -> list[Path]:
    """Files in ``directory`` that belong to exactly ``animal_id``.

    A file belongs to an animal when `parse_animal_id` of its name equals the
    ID, so ``GF1192`` never picks up ``GF1192m_...`` the way a ``GF1192*``
    glob would. ``endings`` are filename endings (``".txt"``, ``"labels.csv"``);
    results are grouped by ending in the order given (so callers can prefer
    one over another), each group sorted. With no endings, any file matches.
    Returns ``[]`` when ``directory`` does not exist.
    """
    d = Path(directory)
    if not d.is_dir():
        return []
    mine = sorted(p for p in d.iterdir() if p.is_file() and parse_animal_id(p) == animal_id)
    if not endings:
        return mine
    return [p for ending in endings for p in mine if p.name.endswith(ending)]
