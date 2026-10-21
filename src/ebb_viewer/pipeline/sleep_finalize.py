"""Consolidate a project's chosen-combo sleep CSVs into an export bundle.

Bridges the manifest (which records each animal's accepted channel combo)
and the pure ``ebb.io.sleep_export`` writer: gather every animal's ok-combo
SPINDLE CSV into one directory, then compute and write the sleep tables.

Lives in ``ebb_viewer`` rather than ``ebb`` because it depends on the
``Manifest``, which is a GUI-side pipeline concept.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from ebb.core.naming import parse_animal_id
from ebb.io.sleep_export import export_sleep
from ebb_viewer.pipeline.manifest import READY_STATUSES, Manifest, spindle_output_dir

# Project recordings are all acquired in the Central time zone; passed to the
# rotate-to-6AM binning so the rotation honors DST transitions.
_RECORDING_TZ = ZoneInfo("America/Chicago")


@dataclass
class SleepExportResult:
    """Outcome of a sleep export run."""

    out_dir: Path
    written: dict[str, Path]
    exported: list[str] = field(default_factory=list)  # animals with an ok combo
    missing_ok: list[str] = field(default_factory=list)  # animals lacking one
    missing_csv: list[str] = field(default_factory=list)  # ok combo but no CSV on disk
    excluded: list[str] = field(default_factory=list)  # exported but marked excluded


def sleep_export_dir(project_root: Path) -> Path:
    return Path(project_root) / "sleep_export"


def _find_animal_csv(animal_id: str, combo: str, project_root: Path) -> Path | None:
    """Return the SPINDLE output CSV for an animal in a combo dir, or None."""
    combo_dir = spindle_output_dir(combo, project_root)
    if not combo_dir.is_dir():
        return None
    for csv_path in sorted(combo_dir.glob("*.csv")):
        if parse_animal_id(csv_path) == animal_id:
            return csv_path
    return None


def build_sleep_export(project_root: Path) -> SleepExportResult:
    """Gather ok-combo CSVs and write the sleep export bundle.

    For every manifest animal with a decided Sleep QC (``"ok"`` or ``"excluded"``),
    copies that combo's SPINDLE CSV into ``sleep_export/chosen_csvs/`` and
    then runs :func:`ebb.io.sleep_export.export_sleep` over the gathered
    directory. Animals without an ok combo (or whose CSV is missing on disk)
    are skipped and reported back so the caller can surface them.

    The ``chosen_csvs`` directory is rebuilt from scratch each run so a
    changed combo decision never leaves a stale CSV behind.
    """
    project_root = Path(project_root)
    manifest = Manifest.load(project_root)

    out_dir = sleep_export_dir(project_root)
    chosen_dir = out_dir / "chosen_csvs"
    if chosen_dir.exists():
        shutil.rmtree(chosen_dir)
    chosen_dir.mkdir(parents=True, exist_ok=True)

    exported: list[str] = []
    missing_ok: list[str] = []
    missing_csv: list[str] = []

    for entry in manifest:
        animal = entry.animal_id
        if entry.sleep_qc not in READY_STATUSES:
            # Only flag animals that have spindle files; an entry without
            # isn't through sleep QC and shouldn't count as "missing ok".
            if entry.has_spindle:
                missing_ok.append(animal)
            continue
        csv_path = _find_animal_csv(animal, manifest.combo, project_root)
        if csv_path is None:
            missing_csv.append(animal)
            continue
        shutil.copy2(csv_path, chosen_dir / csv_path.name)
        exported.append(animal)

    excluded = manifest.excluded_animals()
    written = export_sleep(
        chosen_dir,
        project_root / "standard",
        out_dir,
        begin_hr=6,
        tz=_RECORDING_TZ,
        excluded=excluded,
    )

    return SleepExportResult(
        out_dir=out_dir,
        written=written,
        exported=sorted(exported),
        missing_ok=sorted(missing_ok),
        missing_csv=sorted(missing_csv),
        excluded=sorted(a for a in exported if a in excluded),
    )
