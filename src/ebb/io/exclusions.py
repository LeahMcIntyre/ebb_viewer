"""Mark excluded animals (Sleep QC or PSD review) inside sealed outputs.

Excluded animals are still computed and kept in the sealed PSD outputs; Finalize records the exclusions
as of the moment it runs so a file loaded on its own says which animals to leave
out. ``excluded`` maps animal ID to the exclusion reason.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ebb.core.naming import parse_animal_id

EXCLUDED_FILENAME = "excluded_animals.csv"


def annotate_records(items, excluded: dict[str, str]):
    """Add ``excluded`` and ``exclusion_reason`` to each PSD record (a dict, or a list of them).

    The animal is read from the record's ``path`` like the PSD store does.
    """
    records = [items] if isinstance(items, dict) else items
    for rec in records:
        animal = parse_animal_id(rec["path"])
        rec["excluded"] = animal in excluded
        rec["exclusion_reason"] = excluded.get(animal, "")
    return items


def write_excluded_animals(directory: str | Path, excluded: dict[str, str]) -> Path:
    """Write ``excluded_animals.csv`` (animal, reason) into ``directory``.

    Always written, header only when nothing is excluded, so a missing file never has to
    mean "none excluded".
    """
    path = Path(directory) / EXCLUDED_FILENAME
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["animal", "reason"])
        for animal in sorted(excluded):
            w.writerow([animal, excluded[animal]])
    return path
