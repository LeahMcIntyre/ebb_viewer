"""Pipeline manifest: tracks each animal through the processing stages.

Stages:
  1. Preprocess       raw EDFs → standard/
  2. Spindle write    standard/ → spindle_edfs/<COMBO>/
  3. Upload/Download  spindle_edfs/<COMBO>/ ↔ SleepyRat → spindle_outputs/<COMBO>/
  4. Sleep QC gate    flag: ok | needs_review | rerun_channels
  5. PSD compute      standard/ + spindle_outputs/<COMBO>/ → psd/psds_<COMBO>.pkl
  6. PSD review gate  flag: ok | needs_drink_mask

The manifest lives at project_root/manifest.json.  One entry per animal;
animal ID = first '_'-separated token of the preprocessed EDF stem.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# Valid status values
# ---------------------------------------------------------------------------

SLEEP_QC_STATUSES = frozenset({"ok", "needs_review", "rerun_channels"})
PSD_STATUSES = frozenset({"ok", "needs_drink_mask"})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ManifestEntry:
    """Pipeline state for a single animal."""

    animal_id: str

    # Stage 1 — Preprocess
    preprocessed_edf: str           # relative path from project_root

    # Stage 2 — Spindle write
    spindle_channels: str | None = None   # e.g. "LFC_RSC"

    # Stage 4 — Sleep QC gate
    sleep_qc: str | None = None           # None | "ok" | "needs_review" | "rerun_channels"
    rerun_channels: str | None = None     # set only when sleep_qc == "rerun_channels"

    # Stage 6 — PSD review gate
    psd_status: str | None = None         # None | "ok" | "needs_drink_mask"
    drink_mask: str | None = None         # relative path to .npy

    notes: str = ""


# ---------------------------------------------------------------------------
# Derived path helpers (not stored; computed on demand)
# ---------------------------------------------------------------------------

def spindle_edf_dir(entry: ManifestEntry, project_root: Path) -> Path:
    if entry.spindle_channels is None:
        raise ValueError(f"{entry.animal_id}: spindle_channels not set")
    return project_root / "spindle_edfs" / entry.spindle_channels


def spindle_output_dir(entry: ManifestEntry, project_root: Path) -> Path:
    if entry.spindle_channels is None:
        raise ValueError(f"{entry.animal_id}: spindle_channels not set")
    return project_root / "spindle_outputs" / entry.spindle_channels


def psd_path(entry: ManifestEntry, project_root: Path) -> Path:
    if entry.spindle_channels is None:
        raise ValueError(f"{entry.animal_id}: spindle_channels not set")
    return project_root / "psd" / f"psds_{entry.spindle_channels}.pkl"


def drink_mask_path(entry: ManifestEntry, project_root: Path) -> Path | None:
    if entry.drink_mask is None:
        return None
    return project_root / entry.drink_mask


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
        """Load from manifest.json; return empty manifest if file is missing."""
        m = cls(project_root)
        if not m.path.exists():
            return m
        with m.path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        for animal_id, d in raw.items():
            m._entries[animal_id] = ManifestEntry(animal_id=animal_id, **d)
        return m

    @classmethod
    def build_from_standard(cls, project_root: Path) -> "Manifest":
        """Load existing manifest, scan standard/ + spindle folders, and sync.

        - Adds entries for any new EDFs found in standard/ (animal_id + preprocessed_edf).
        - For entries where spindle_channels is None, scans spindle_edfs/ and
          spindle_outputs/ to infer the channel combo from the folder structure.
        - Existing non-None fields are never overwritten.
        """
        m = cls.load(project_root)

        # 1. Add new entries from standard/
        standard = project_root / "standard"
        if standard.is_dir():
            for edf in sorted(standard.glob("*.edf")):
                animal_id = edf.stem.split("_")[0]
                if animal_id not in m._entries:
                    m._entries[animal_id] = ManifestEntry(
                        animal_id=animal_id,
                        preprocessed_edf=str(edf.relative_to(project_root)),
                    )

        # 2. Infer spindle_channels for entries that don't have it set yet.
        #    Scan spindle_edfs/<COMBO>/ and spindle_outputs/<COMBO>/ for files
        #    matching the animal_id prefix.  Prefer spindle_outputs if found there
        #    (more likely to be the completed run), fall back to spindle_edfs.
        #    If both contain multiple combos for the same animal, pick the most
        #    recently modified file's combo.
        for subdir in ("spindle_outputs", "spindle_edfs"):
            root_dir = project_root / subdir
            if not root_dir.is_dir():
                continue
            # Build: animal_id -> [(mtime, combo), ...]
            found: dict[str, list[tuple[float, str]]] = {}
            for combo_dir in root_dir.iterdir():
                if not combo_dir.is_dir():
                    continue
                combo = combo_dir.name
                for f in combo_dir.iterdir():
                    animal_id = f.stem.split("_")[0]
                    if animal_id in m._entries:
                        found.setdefault(animal_id, []).append(
                            (f.stat().st_mtime, combo)
                        )
            # Apply: pick the combo from the most recently modified file
            for animal_id, hits in found.items():
                if m._entries[animal_id].spindle_channels is None:
                    best_combo = max(hits, key=lambda x: x[0])[1]
                    m._entries[animal_id].spindle_channels = best_combo

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
            d = asdict(entry)
            d.pop("animal_id")   # stored as key, not field
            data[animal_id] = d
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

    def __iter__(self) -> Iterator[ManifestEntry]:
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, animal_id: str) -> bool:
        return animal_id in self._entries

    # ------------------------------------------------------------------
    # Filtered views
    # ------------------------------------------------------------------

    def pending_sleep_qc(self) -> list[ManifestEntry]:
        """Entries that have spindle outputs but haven't been QC'd yet."""
        return [
            e for e in self
            if e.spindle_channels is not None and e.sleep_qc is None
        ]

    def needs_review(self) -> list[ManifestEntry]:
        """Entries flagged for EDF viewer review."""
        return [e for e in self if e.sleep_qc == "needs_review"]

    def needs_rerun(self) -> list[ManifestEntry]:
        """Entries flagged for spindle rerun with different channels."""
        return [e for e in self if e.sleep_qc == "rerun_channels"]

    def pending_psd_review(self) -> list[ManifestEntry]:
        """Entries that have a PSD file but haven't been reviewed yet."""
        return [
            e for e in self
            if e.spindle_channels is not None
            and psd_path(e, self.project_root).exists()
            and e.psd_status is None
        ]

    def needs_drink_mask(self) -> list[ManifestEntry]:
        """Entries flagged as having drinking sidebands in the PSD."""
        return [e for e in self if e.psd_status == "needs_drink_mask"]

    # ------------------------------------------------------------------
    # Flagging
    # ------------------------------------------------------------------

    def flag_sleep_qc(
        self,
        animal_id: str,
        status: str,
        rerun_channels: str | None = None,
    ) -> None:
        """Set the sleep QC flag for an animal and save.

        Args:
            animal_id: Animal to update.
            status: One of "ok", "needs_review", "rerun_channels".
            rerun_channels: Channel combo string (e.g. "RSC_LSC") required
                when status == "rerun_channels".
        """
        if status not in SLEEP_QC_STATUSES:
            raise ValueError(f"Invalid sleep_qc status {status!r}; must be one of {SLEEP_QC_STATUSES}")
        if status == "rerun_channels" and not rerun_channels:
            raise ValueError("rerun_channels must be provided when status == 'rerun_channels'")
        entry = self._entries[animal_id]
        entry.sleep_qc = status
        entry.rerun_channels = rerun_channels if status == "rerun_channels" else None
        self.save()

    def flag_psd(
        self,
        animal_id: str,
        status: str,
        drink_mask: str | None = None,
    ) -> None:
        """Set the PSD review flag for an animal and save.

        Args:
            animal_id: Animal to update.
            status: One of "ok", "needs_drink_mask".
            drink_mask: Relative path to .npy file (e.g. "drink_masks/Mice-1234.npy")
                required when status == "needs_drink_mask".
        """
        if status not in PSD_STATUSES:
            raise ValueError(f"Invalid psd_status {status!r}; must be one of {PSD_STATUSES}")
        entry = self._entries[animal_id]
        entry.psd_status = status
        entry.drink_mask = drink_mask if status == "needs_drink_mask" else None
        self.save()

    def set_spindle_channels(self, animal_id: str, channels: str) -> None:
        """Record which channel combo was used for spindle write and save."""
        self._entries[animal_id].spindle_channels = channels
        self.save()

    def reset_sleep_qc(self, animal_id: str) -> None:
        """Clear sleep QC status (e.g. after a channel rerun) and save."""
        entry = self._entries[animal_id]
        entry.sleep_qc = None
        entry.rerun_channels = None
        self.save()

    def reset_psd_status(self, animal_id: str) -> None:
        """Clear PSD status (e.g. after drink mask rerun) and save."""
        self._entries[animal_id].psd_status = None
        self.save()
