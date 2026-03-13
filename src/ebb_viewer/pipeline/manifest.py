"""Pipeline manifest: tracks each animal through the processing stages.

Stages:
  1. Preprocess       raw EDFs → standard/
  2. Spindle write    standard/ → spindle_edfs/<COMBO>/
  3. Upload/Download  spindle_edfs/<COMBO>/ ↔ SleepyRat → spindle_outputs/<COMBO>/
  4. Sleep QC gate    flag per run: ok | needs_review | needs_rerun
  5. PSD compute      standard/ + spindle_outputs/<COMBO>/ → psd/psds_<COMBO>.pkl
  6. PSD review gate  flag per run: ok | needs_drink_mask
  7. Final merge      psd/psds_final.pkl (one entry per animal from their ok run)

The manifest lives at project_root/manifest.json.  One entry per animal;
animal ID = first '_'-separated token of the preprocessed EDF stem.

Each animal may have multiple spindle runs, one per channel combo tried
(e.g. "LFC_RSC" initially, then "LSC_RSC" if a rerun was needed).
Each run has its own independent QC lifecycle.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

from ebb_viewer.pipeline.naming import drink_mask_rel, parse_animal_id


# ---------------------------------------------------------------------------
# Valid status values
# ---------------------------------------------------------------------------

SLEEP_QC_STATUSES = frozenset({"ok", "needs_review", "needs_rerun", "rejected"})
PSD_STATUSES      = frozenset({"ok", "needs_drink_mask", "drink_mask_applied"})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RunEntry:
    """State for one (animal × channel combo) spindle run."""
    sleep_qc:     str | None = None   # None | "ok" | "needs_review" | "needs_rerun" | "rejected"
    rerun_combo:  str | None = None   # target combo when sleep_qc == "needs_rerun"
    source_combo: str | None = None   # combo that triggered this run as a rerun
    psd_status:   str | None = None   # None | "ok" | "needs_drink_mask"
    drink_mask:   str | None = None   # relative path to .npy


@dataclass
class ManifestEntry:
    """Pipeline state for a single animal, across all spindle runs."""

    animal_id: str

    # Stage 1 — Preprocess
    preprocessed_edf: str           # relative path from project_root

    # Stage 2+ — one RunEntry per channel combo tried
    runs: dict[str, RunEntry] = field(default_factory=dict)
    # key = channel combo string, e.g. "LFC_RSC"

    notes: str = ""


# ---------------------------------------------------------------------------
# Derived path helpers (not stored; computed on demand)
# ---------------------------------------------------------------------------

def spindle_edf_dir(channels: str, project_root: Path) -> Path:
    return project_root / "spindle_edfs" / channels


def spindle_output_dir(channels: str, project_root: Path) -> Path:
    return project_root / "spindle_outputs" / channels


def psd_path(channels: str, project_root: Path) -> Path:
    return project_root / "psd" / f"psds_{channels}.pkl"


def final_psd_path(project_root: Path) -> Path:
    return project_root / "psd" / "psds_final.pkl"


def drink_mask_path(run: RunEntry, project_root: Path) -> Path | None:
    if run.drink_mask is None:
        return None
    return project_root / run.drink_mask


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _run_to_dict(run: RunEntry) -> dict:
    return asdict(run)


def _run_from_dict(d: dict) -> RunEntry:
    return RunEntry(**{k: v for k, v in d.items() if k in RunEntry.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

class Manifest:
    """Ordered collection of ManifestEntry objects, backed by manifest.json."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.path = self.project_root / "manifest.json"
        self._entries: dict[str, ManifestEntry] = {}

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, project_root: Path) -> "Manifest":
        """Load from manifest.json; return empty manifest if file is missing.

        Handles migration from the old flat format (spindle_channels, sleep_qc,
        psd_status as top-level fields) to the new per-run dict format.
        """
        m = cls(project_root)
        if not m.path.exists():
            return m
        with m.path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        for animal_id, d in raw.items():
            # --- migration from old flat format ---
            if "spindle_channels" in d:
                old_ch      = d.pop("spindle_channels")
                old_qc      = d.pop("sleep_qc", None)
                old_rerun   = d.pop("rerun_channels", None)
                old_psd     = d.pop("psd_status", None)
                old_drink   = d.pop("drink_mask", None)
                d.pop("notes", None)
                runs: dict[str, RunEntry] = {}
                if old_ch:
                    # Map old "rerun_channels" status → "needs_rerun"
                    if old_qc == "rerun_channels":
                        runs[old_ch] = RunEntry(
                            sleep_qc="needs_rerun",
                            rerun_combo=old_rerun,
                        )
                    else:
                        runs[old_ch] = RunEntry(
                            sleep_qc=old_qc,
                            psd_status=old_psd,
                            drink_mask=old_drink,
                        )
                m._entries[animal_id] = ManifestEntry(
                    animal_id=animal_id,
                    preprocessed_edf=d.get("preprocessed_edf", ""),
                    runs=runs,
                    notes=d.get("notes", ""),
                )
            else:
                # New format
                runs_raw = d.pop("runs", {})
                runs = {combo: _run_from_dict(r) for combo, r in runs_raw.items()}
                m._entries[animal_id] = ManifestEntry(
                    animal_id=animal_id,
                    runs=runs,
                    **d,
                )
        return m

    @classmethod
    def build_from_standard(cls, project_root: Path) -> "Manifest":
        """Load existing manifest, scan standard/ + spindle folders, and sync.

        - Adds ManifestEntry for any new EDFs found in standard/.
        - Adds a RunEntry for each (animal, combo) found in spindle_edfs/ or
          spindle_outputs/ that doesn't already have one.
        - Existing entries and run statuses are never overwritten.
        """
        m = cls.load(project_root)

        # 1. Add new animal entries from standard/
        standard = project_root / "standard"
        if standard.is_dir():
            for edf in sorted(standard.glob("*.edf")):
                animal_id = parse_animal_id(edf)
                if animal_id not in m._entries:
                    m._entries[animal_id] = ManifestEntry(
                        animal_id=animal_id,
                        preprocessed_edf=str(edf.relative_to(project_root)),
                    )

        # 2. Add RunEntry for each (animal, combo) found on disk
        for subdir in ("spindle_outputs", "spindle_edfs"):
            root_dir = project_root / subdir
            if not root_dir.is_dir():
                continue
            for combo_dir in sorted(root_dir.iterdir()):
                if not combo_dir.is_dir():
                    continue
                combo = combo_dir.name
                for f in combo_dir.iterdir():
                    animal_id = parse_animal_id(f)
                    if animal_id not in m._entries:
                        continue
                    entry = m._entries[animal_id]
                    if combo not in entry.runs:
                        entry.runs[combo] = RunEntry()

        # 3. Add RunEntry for each combo found in psd/psds_<COMBO>.pkl files
        psd_dir = project_root / "psd"
        if psd_dir.is_dir():
            for pkl in sorted(psd_dir.glob("psds_*.pkl")):
                combo = pkl.stem[len("psds_"):]
                for entry in m._entries.values():
                    if combo not in entry.runs:
                        entry.runs[combo] = RunEntry()

        m.save()
        return m

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Atomically write manifest.json."""
        self.project_root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        data = {}
        for animal_id, entry in self._entries.items():
            data[animal_id] = {
                "preprocessed_edf": entry.preprocessed_edf,
                "notes": entry.notes,
                "runs": {
                    combo: _run_to_dict(run)
                    for combo, run in entry.runs.items()
                },
            }
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.path)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def add(self, entry: ManifestEntry) -> None:
        self._entries[entry.animal_id] = entry

    def get(self, animal_id: str) -> ManifestEntry | None:
        return self._entries.get(animal_id)

    def get_run(self, animal_id: str, channels: str) -> RunEntry | None:
        entry = self._entries.get(animal_id)
        if entry is None:
            return None
        return entry.runs.get(channels)

    def add_run(self, animal_id: str, channels: str, source_combo: str | None = None) -> RunEntry:
        """Add a RunEntry for (animal_id, channels) if not present; return it."""
        entry = self._entries[animal_id]
        if channels not in entry.runs:
            entry.runs[channels] = RunEntry(source_combo=source_combo)
            self.save()
        return entry.runs[channels]

    def __iter__(self) -> Iterator[ManifestEntry]:
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, animal_id: str) -> bool:
        return animal_id in self._entries

    # ------------------------------------------------------------------
    # Filtered views — return (entry, channels) tuples
    # ------------------------------------------------------------------

    def pending_sleep_qc(self) -> list[tuple[ManifestEntry, str]]:
        """Runs that exist but haven't been QC'd yet."""
        return [
            (entry, combo)
            for entry in self
            for combo, run in entry.runs.items()
            if run.sleep_qc is None
        ]

    def needs_review(self) -> list[tuple[ManifestEntry, str]]:
        """Runs flagged for EDF viewer review."""
        return [
            (entry, combo)
            for entry in self
            for combo, run in entry.runs.items()
            if run.sleep_qc == "needs_review"
        ]

    def pending_rerun_review(self) -> list[tuple[ManifestEntry, str]]:
        """Rerun combos that have been processed and are awaiting review.

        A combo is pending review when:
        - it was triggered as a rerun (source_combo is set)
        - it has not yet been reviewed (sleep_qc is None)
        - spindle outputs exist on disk
        """
        return [
            (entry, combo)
            for entry in self
            for combo, run in entry.runs.items()
            if run.source_combo is not None
            and run.sleep_qc is None
            and spindle_output_dir(combo, self.project_root).is_dir()
            and any(spindle_output_dir(combo, self.project_root).iterdir())
        ]

    def needs_rerun(self) -> list[tuple[ManifestEntry, str]]:
        """Runs flagged for spindle rerun with a different channel combo."""
        return [
            (entry, combo)
            for entry in self
            for combo, run in entry.runs.items()
            if run.sleep_qc == "needs_rerun"
        ]

    def pending_psd_review(self) -> list[tuple[ManifestEntry, str]]:
        """Runs whose PSD file exists but hasn't been reviewed yet."""
        return [
            (entry, combo)
            for entry in self
            for combo, run in entry.runs.items()
            if run.sleep_qc == "ok"
            and run.psd_status is None
            and psd_path(combo, self.project_root).exists()
        ]

    def needs_drink_mask(self) -> list[tuple[ManifestEntry, str]]:
        """Runs flagged as having drinking sidebands in the PSD."""
        return [
            (entry, combo)
            for entry in self
            for combo, run in entry.runs.items()
            if run.psd_status == "needs_drink_mask"
        ]

    def needs_drink_mask_rerun(self) -> list[tuple[ManifestEntry, str]]:
        """Runs flagged needs_drink_mask where the drink mask file is present on disk."""
        return [
            (entry, combo)
            for entry in self
            for combo, run in entry.runs.items()
            if run.psd_status == "needs_drink_mask"
            and (self.project_root / drink_mask_rel(entry.animal_id)).is_file()
        ]

    # ------------------------------------------------------------------
    # Flagging
    # ------------------------------------------------------------------

    def flag_sleep_qc(
        self,
        animal_id: str,
        channels: str,
        status: str,
        rerun_combo: str | None = None,
    ) -> None:
        """Set the sleep QC flag for a specific (animal, channels) run.

        Args:
            animal_id:   Animal to update.
            channels:    Channel combo string identifying the run (e.g. "LFC_RSC").
            status:      One of "ok", "needs_review", "needs_rerun", "rejected".
            rerun_combo: New channel combo to use for the rerun; required when
                         status == "needs_rerun".
        """
        if status not in SLEEP_QC_STATUSES:
            raise ValueError(f"Invalid sleep_qc status {status!r}; must be one of {SLEEP_QC_STATUSES}")
        if status == "needs_rerun" and not rerun_combo:
            raise ValueError("rerun_combo required when status == 'needs_rerun'")
        run = self._entries[animal_id].runs[channels]
        run.sleep_qc = status
        run.rerun_combo = rerun_combo if status == "needs_rerun" else None
        self.save()

    def flag_psd(self, animal_id: str, channels: str, status: str) -> None:
        """Set the PSD review flag for a specific (animal, channels) run.

        Args:
            animal_id:  Animal to update.
            channels:   Channel combo string identifying the run.
            status:     One of "ok", "needs_drink_mask", "drink_mask_applied".
        """
        if status not in PSD_STATUSES:
            raise ValueError(f"Invalid psd_status {status!r}; must be one of {PSD_STATUSES}")
        run = self._entries[animal_id].runs[channels]
        run.psd_status = status
        if status == "drink_mask_applied":
            run.drink_mask = drink_mask_rel(animal_id)
        elif status == "ok":
            run.drink_mask = None
        # "needs_drink_mask": leave drink_mask as None until rerun is applied
        self.save()

    def reset_sleep_qc(self, animal_id: str, channels: str) -> None:
        """Clear sleep QC status for a specific run."""
        run = self._entries[animal_id].runs[channels]
        run.sleep_qc = None
        run.rerun_combo = None
        self.save()

    def reset_psd_status(self, animal_id: str, channels: str) -> None:
        """Clear PSD review status for a specific run."""
        self._entries[animal_id].runs[channels].psd_status = None
        self.save()
