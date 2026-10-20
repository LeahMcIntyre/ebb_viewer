"""SWD review helpers shared by pages: locating an animal's SWD file and finding review gaps."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from ebb_viewer.pipeline.manifest import Manifest, swd_review_status

# Same rule PSD compute uses to pair SWD files with animals (psd_compute.match_paths): an
# optional "<letters/digits>ts_" prefix, then the animal ID up to the next "_".
_SWD_ANIMAL = re.compile(r"^(?:[A-Za-z0-9]*ts_)?([^_]+)")


def find_swd_file(project_root: Path, animal_id: str) -> Path | None:
    """The ``swd/*.mat`` file for ``animal_id`` (first, sorted), or None.

    Matches ``Mice-1256.mat`` and ``JK1011_P063_DEL_ts.mat``, but not another animal whose ID
    merely starts with the same characters (A1 vs A10). An empty .mat counts as a file.
    """
    swd_dir = Path(project_root) / "swd"
    for mat in sorted(swd_dir.glob("*.mat")) if swd_dir.is_dir() else []:
        m = _SWD_ANIMAL.match(mat.stem)
        if m and m.group(1) == animal_id:
            return mat
    return None


@dataclass
class SwdReviewGaps:
    """What stands between a project and a finished SWD review (sorted animal IDs)."""

    missing: list[str] = field(default_factory=list)  # no SWD file and not confirmed as none
    unfinished: list[str] = field(default_factory=list)  # has an SWD file, review not finished

    def __bool__(self) -> bool:
        return bool(self.missing or self.unfinished)


def swd_review_gaps(
    project_root: Path, manifest: Manifest, animal_ids: set[str] | None = None
) -> SwdReviewGaps:
    """Animals that still need an SWD file (or a confirmation that none is needed) or a review.

    Empty unless the project turned SWD review on. Every animal with spindle output needs an
    SWD file (an empty one is fine) or the user's confirmation that it has none
    (``ManifestEntry.swd_waived``). ``animal_ids`` narrows the check, e.g. to the animals a PSD
    run will use.
    """
    gaps = SwdReviewGaps()
    if not manifest.swd_review_enabled:
        return gaps
    for e in manifest:
        if not e.has_spindle or (animal_ids is not None and e.animal_id not in animal_ids):
            continue
        if find_swd_file(project_root, e.animal_id) is None:
            if not e.swd_waived:
                gaps.missing.append(e.animal_id)
        elif swd_review_status(e) != "done":
            gaps.unfinished.append(e.animal_id)
    gaps.missing.sort()
    gaps.unfinished.sort()
    return gaps
