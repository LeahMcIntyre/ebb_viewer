"""Pipeline manifest: tracks each animal through the processing stages.

Stages:
  1. Preprocess       raw EDFs → standard/
  2. Spindle write    standard/ → spindle_edfs/<COMBO>/
  3. Upload/Download  spindle_edfs/<COMBO>/ ↔ SleepyRat → spindle_outputs/<COMBO>/
  3b. Reclassify      spindle_outputs/<COMBO>/ CSVs gain a reclass_state column
  4. Sleep QC gate    flag per animal: ok | needs_review
  5. PSD compute      standard/ + spindle_outputs/<COMBO>/ → psd/<RUN>/psds_<COMBO>.pkl
  6. PSD review gate  flag per (animal, psd_run_name): ok | needs_drink_mask

The manifest lives at project_root/manifest.json.  One entry per animal;
animal ID = first '_'-separated token of the preprocessed EDF stem.

A project uses a single channel combo (``Manifest.combo``, default
``DEFAULT_COMBO``), stored at the top level of manifest.json.  Every animal's
spindle files live under ``spindle_edfs/<combo>/`` and
``spindle_outputs/<combo>/``.
"""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ebb.process.sleep_flagging import default_thresholds
from ebb_viewer.pipeline import psd_params as _pp
from ebb_viewer.pipeline.naming import drink_mask_rel, parse_animal_id

# ---------------------------------------------------------------------------
# Valid status values
# ---------------------------------------------------------------------------

DEFAULT_COMBO = "LFC_RSC"
SLEEP_QC_STATUSES = frozenset({"ok", "needs_review", "excluded"})
# Statuses ``flag_sleep_qc`` sets; "excluded" goes through ``exclude_sleep_qc`` (it needs a reason).
_FLAGGABLE_STATUSES = frozenset({"ok", "needs_review"})
# Sleep QC decided: the animal goes through PSD compute and every export. An excluded
# animal is still computed; only its label says to leave it out of the analysis.
READY_STATUSES = frozenset({"ok", "excluded"})
PSD_STATUSES = frozenset({"ok", "needs_drink_mask", "drink_mask_applied"})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ManifestEntry:
    """Pipeline state for a single animal."""

    animal_id: str

    # Stage 1 — Preprocess
    preprocessed_edf: str  # relative path from project_root

    # Stage 2 — True once spindle EDFs/outputs for this animal exist on disk
    has_spindle: bool = False

    # Sleep QC
    sleep_qc: str | None = None  # None | "ok" | "needs_review" | "excluded"

    # NREM reclassification — whether the EMG gate was applied when
    # ``reclass_state`` was written to the spindle CSV (None = not run yet)
    reclass_gate_applied: bool | None = None

    # SWD review (optional, project-level): SWD epochs reviewed and how many SWD epochs the animal
    # has (a cache for pages that must not read CSVs; the SWD Review page keeps it in sync, and the
    # CSV's swd_reclassification column is the source of truth). ``swd_total`` is None until
    # known. ``swd_waived``: the user confirmed this animal has no SWD file and needs none.
    swd_reviewed: int = 0
    swd_total: int | None = None
    swd_waived: bool = False

    # PSD review — keyed by psd run name (e.g. "default", "light_phase")
    psd_status: dict = field(
        default_factory=dict
    )  # {run_name: "ok"|"needs_drink_mask"|"drink_mask_applied"}
    drink_mask: str | None = None  # relative path to .npy (shared across psd runs)

    notes: str = ""


# ---------------------------------------------------------------------------
# Derived path helpers (not stored; computed on demand)
# ---------------------------------------------------------------------------


def swd_review_status(entry: ManifestEntry) -> str:
    """``"not_started"`` | ``"in_progress"`` | ``"done"`` for an animal that has an SWD file.

    An unknown total counts as not started; a file with no SWD epochs (``swd_total == 0``,
    e.g. an empty .mat) has nothing to review and is done.
    """
    if entry.swd_total is None:
        return "not_started"
    if entry.swd_reviewed >= entry.swd_total:
        return "done"
    return "in_progress" if entry.swd_reviewed > 0 else "not_started"


def spindle_edf_dir(channels: str, project_root: Path) -> Path:
    return project_root / "spindle_edfs" / channels


def spindle_output_dir(channels: str, project_root: Path) -> Path:
    return project_root / "spindle_outputs" / channels


def psd_run_dir(project_root: Path, run_name: str) -> Path:
    return Path(project_root) / "psd" / run_name


def psd_path(channels: str, project_root: Path, run_name: str = "default") -> Path:
    return psd_run_dir(project_root, run_name) / f"psds_{channels}.pkl"


def psd_drink_path(channels: str, project_root: Path, run_name: str = "default") -> Path:
    """Drink-mask-corrected overlay of ``psd_path`` (see ``rerun_with_drink_masks``)."""
    return psd_run_dir(project_root, run_name) / f"psds_{channels}_drink.pkl"


def drink_mask_path(entry: ManifestEntry, project_root: Path) -> Path | None:
    if entry.drink_mask is None:
        return None
    return project_root / entry.drink_mask


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _entry_to_dict(entry: ManifestEntry) -> dict:
    return {
        "preprocessed_edf": entry.preprocessed_edf,
        "notes": entry.notes,
        "has_spindle": entry.has_spindle,
        "sleep_qc": entry.sleep_qc,
        "reclass_gate_applied": entry.reclass_gate_applied,
        "swd_reviewed": entry.swd_reviewed,
        "swd_total": entry.swd_total,
        "swd_waived": entry.swd_waived,
        "psd_status": entry.psd_status,
        "drink_mask": entry.drink_mask,
    }


def _entry_from_dict(animal_id: str, d: dict, combo: str) -> ManifestEntry:
    """Build a ManifestEntry from a JSON-loaded dict.

    TEMPORARY multi-combo read path: manifests written before the single-combo
    change store ``runs: {combo: {...}}``.  Take the run for the project combo
    and drop everything else (other combos, rerun/cascade bookkeeping,
    "needs_rerun"/"rejected" statuses).  Delete this branch once existing
    projects have been re-saved.
    """
    if "runs" in d:
        run = d["runs"].get(combo) or {}
        sleep_qc = run.get("sleep_qc")
        psd_status = run.get("psd_status")
        return ManifestEntry(
            animal_id=animal_id,
            preprocessed_edf=d.get("preprocessed_edf", ""),
            notes=d.get("notes", ""),
            has_spindle=combo in d["runs"],
            sleep_qc=sleep_qc if sleep_qc in SLEEP_QC_STATUSES else None,
            psd_status=psd_status if isinstance(psd_status, dict) else {},
            drink_mask=run.get("drink_mask"),
        )
    return ManifestEntry(
        animal_id=animal_id,
        preprocessed_edf=d.get("preprocessed_edf", ""),
        notes=d.get("notes", ""),
        has_spindle=d.get("has_spindle", False),
        sleep_qc=d.get("sleep_qc"),
        reclass_gate_applied=d.get("reclass_gate_applied"),
        swd_reviewed=int(d.get("swd_reviewed", 0)),
        swd_total=d.get("swd_total"),
        swd_waived=bool(d.get("swd_waived", False)),
        psd_status=d.get("psd_status") or {},
        drink_mask=d.get("drink_mask"),
    )


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class Manifest:
    """Ordered collection of ManifestEntry objects, backed by manifest.json."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.path = self.project_root / "manifest.json"
        self.combo = DEFAULT_COMBO
        self.swd_review_enabled = False  # project opt-in for the SWD review page
        self.flag_thresholds = default_thresholds()  # Sleep QC flagging cutoffs, by metric key
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
        # Pre-single-combo files are a bare {animal_id: {...}} dict.
        if "animals" in raw:
            m.combo = raw.get("combo", DEFAULT_COMBO)
            m.swd_review_enabled = bool(raw.get("swd_review_enabled", False))
            m.flag_thresholds.update(raw.get("flag_thresholds", {}))
            raw = raw["animals"]
        for animal_id, d in raw.items():
            m._entries[animal_id] = _entry_from_dict(animal_id, d, m.combo)
        return m

    @classmethod
    def build_from_standard(cls, project_root: Path) -> "Manifest":
        """Load existing manifest, scan standard/ + spindle folders, and sync.

        - Adds ManifestEntry for any new EDFs found in standard/.
        - Marks ``has_spindle`` for animals with a file in the project combo's
          spindle_edfs/ or spindle_outputs/ folder.
        - Existing flags are never overwritten.

        Saves only if something was added or changed.
        Must be called from the main thread.
        """
        m = cls.load(project_root)
        dirty = False

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
                    dirty = True

        # 2. Flag animals that have spindle files for the project combo.
        # PSD files (psds_<COMBO>.pkl) are aggregates, not per-animal,
        # so they don't tell us which animals have spindle files — skip them.
        for folder in (
            spindle_output_dir(m.combo, project_root),
            spindle_edf_dir(m.combo, project_root),
        ):
            if not folder.is_dir():
                continue
            for f in folder.iterdir():
                entry = m._entries.get(parse_animal_id(f))
                if entry is not None and not entry.has_spindle:
                    entry.has_spindle = True
                    dirty = True

        # An old-format file is rewritten in the new format on first sync.
        if dirty or _is_legacy_file(m.path):
            m.save()
        return m

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Atomically write manifest.json."""
        self.project_root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        data = {
            "combo": self.combo,
            "swd_review_enabled": self.swd_review_enabled,
            "flag_thresholds": self.flag_thresholds,
            "animals": {aid: _entry_to_dict(e) for aid, e in self._entries.items()},
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

    def set_notes(self, animal_id: str, notes: str) -> None:
        """Set free-text notes for an animal."""
        self._entries[animal_id].notes = notes
        self.save()

    def set_reclass_gates(self, gates: dict[str, bool]) -> None:
        """Record per-animal EMG-gate results from a reclassification run."""
        for animal_id, applied in gates.items():
            if animal_id in self._entries:
                self._entries[animal_id].reclass_gate_applied = applied
        self.save()

    def set_swd_review_enabled(self, enabled: bool) -> None:
        """Turn the optional SWD review on or off for the whole project."""
        self.swd_review_enabled = enabled
        self.save()

    def set_swd_waived(self, animal_id: str, waived: bool = True) -> None:
        """Confirm (or undo) that an animal needs no SWD file for the SWD review."""
        self._entries[animal_id].swd_waived = waived
        self.save()

    def set_swd_progress(self, animal_id: str, reviewed: int, total: int) -> None:
        """Record how many of an animal's ``total`` SWD epochs its saved review covers."""
        entry = self._entries[animal_id]
        entry.swd_reviewed = reviewed
        entry.swd_total = total
        self.save()

    def __iter__(self) -> Iterator[ManifestEntry]:
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, animal_id: str) -> bool:
        return animal_id in self._entries

    # ------------------------------------------------------------------
    # Filtered views
    # ------------------------------------------------------------------

    def _filter(self, predicate: Callable[[ManifestEntry], bool]) -> list[ManifestEntry]:
        return [e for e in self if e.has_spindle and predicate(e)]

    def pending_sleep_qc(self) -> list[ManifestEntry]:
        """Animals with spindle files that haven't been QC'd yet."""
        return self._filter(lambda e: e.sleep_qc is None)

    def needs_review(self) -> list[ManifestEntry]:
        """Animals flagged for EDF viewer review."""
        return self._filter(lambda e: e.sleep_qc == "needs_review")

    def ready_for_psd(self) -> list[ManifestEntry]:
        """Animals with sleep_qc "ok" or "excluded" — the gate for PSD computation."""
        return self._filter(lambda e: e.sleep_qc in READY_STATUSES)

    def pending_psd_review(self, run_name: str) -> list[ManifestEntry]:
        """Animals with ok sleep QC whose PSD hasn't been reviewed yet for run_name.

        Gated on psds_<combo>.pkl existing for that run.
        """
        if not psd_path(self.combo, self.project_root, run_name).exists():
            return []
        return self._filter(lambda e: e.sleep_qc in READY_STATUSES and run_name not in e.psd_status)

    def needs_drink_mask(self, run_name: str) -> list[ManifestEntry]:
        """Animals flagged as having drinking sidebands in the PSD for run_name."""
        return self._filter(
            lambda e: e.sleep_qc in READY_STATUSES and e.psd_status.get(run_name) == "needs_drink_mask"
        )

    def needs_drink_mask_rerun(self, run_name: str) -> list[ManifestEntry]:
        """Animals flagged needs_drink_mask where the drink mask file is present on disk."""
        root = self.project_root
        return self._filter(
            lambda e: (
                e.sleep_qc in READY_STATUSES
                and e.psd_status.get(run_name) == "needs_drink_mask"
                and (root / drink_mask_rel(e.animal_id)).is_file()
            )
        )

    def pending_drink_verification(self, run_name: str) -> list[ManifestEntry]:
        """Animals with drink_mask_applied — ready for Pass 2 PSD verification."""
        return self._filter(
            lambda e: e.sleep_qc in READY_STATUSES and e.psd_status.get(run_name) == "drink_mask_applied"
        )

    def _aggregate_across_runs(
        self,
        per_run_method: Callable[[str], list[ManifestEntry]],
    ) -> list[ManifestEntry]:
        """Union of `per_run_method(run_name)` over every PSD run, deduped."""
        seen: set[str] = set()
        result: list[ManifestEntry] = []
        for run_name in _pp.list_runs(self.project_root):
            for entry in per_run_method(run_name):
                if entry.animal_id not in seen:
                    seen.add(entry.animal_id)
                    result.append(entry)
        return result

    def all_pending_psd_review(self) -> list[ManifestEntry]:
        """Pending PSD review across ALL runs — for sidebar badge counts."""
        return self._aggregate_across_runs(self.pending_psd_review)

    def all_needs_drink_mask(self) -> list[ManifestEntry]:
        """Needs-drink-mask across ALL runs — for sidebar badge counts."""
        return self._aggregate_across_runs(self.needs_drink_mask)

    def all_pending_drink_verification(self) -> list[ManifestEntry]:
        """Pending drink verification across ALL runs — for sidebar badge counts."""
        return self._aggregate_across_runs(self.pending_drink_verification)

    # ------------------------------------------------------------------
    # Flagging
    # ------------------------------------------------------------------

    def flag_sleep_qc(self, animal_id: str, status: str) -> None:
        """Set the sleep QC flag for an animal.

        Leaving "ok" or "excluded" for another status clears PSD review progress,
        which is only valid while the animal is ready for PSD.
        """
        if status not in _FLAGGABLE_STATUSES:
            raise ValueError(
                f"Invalid sleep_qc status {status!r}; must be one of {set(_FLAGGABLE_STATUSES)} "
                "(use exclude_sleep_qc to exclude)"
            )
        self._set_sleep_qc(animal_id, status)
        self.save()

    def exclude_sleep_qc(self, animal_id: str, reason: str) -> None:
        """Exclude an animal from analysis, recording ``reason`` in its notes.

        The reason is appended to ``notes`` as an ``Excluded: <reason>`` line.
        Undo with ``flag_sleep_qc`` or ``reset_sleep_qc``; the note stays.

        Raises:
            ValueError: if ``reason`` is empty or whitespace.
        """
        reason = reason.strip()
        if not reason:
            raise ValueError("A reason is required to exclude an animal")
        entry = self._entries[animal_id]
        self._set_sleep_qc(animal_id, "excluded")
        line = f"Excluded: {reason}"
        entry.notes = f"{entry.notes}\n{line}" if entry.notes else line
        self.save()

    def _set_sleep_qc(self, animal_id: str, status: str) -> None:
        """Set the status; leaving the ready statuses clears PSD review progress."""
        entry = self._entries[animal_id]
        if entry.sleep_qc in READY_STATUSES and status not in READY_STATUSES:
            entry.psd_status = {}
            entry.drink_mask = None
        entry.sleep_qc = status

    def flag_psd(self, animal_id: str, status: str, run_name: str = "default") -> None:
        """Set the PSD review flag for (animal, run_name).

        Args:
            animal_id:  Animal to update.
            status:     One of "ok", "needs_drink_mask", "drink_mask_applied".
            run_name:   PSD run name (e.g. "light_phase").

        Raises:
            ValueError: if the animal's sleep_qc is not "ok" or "excluded".
        """
        if status not in PSD_STATUSES:
            raise ValueError(f"Invalid psd_status {status!r}; must be one of {PSD_STATUSES}")
        entry = self._entries[animal_id]
        if entry.sleep_qc not in READY_STATUSES:
            raise ValueError(
                f"Cannot set PSD status for animal {animal_id!r}: "
                f"sleep_qc is {entry.sleep_qc!r}, expected 'ok' or 'excluded'."
            )
        entry.psd_status[run_name] = status
        if status == "drink_mask_applied":
            entry.drink_mask = drink_mask_rel(animal_id)
        # Clear drink_mask only if no other psd run still has drink_mask_applied.
        # "needs_drink_mask" is left as-is since the mask file may still be needed.
        elif status == "ok" and not any(
            v == "drink_mask_applied" for k, v in entry.psd_status.items() if k != run_name
        ):
            entry.drink_mask = None
        self.save()

    def reset_psd_status(self, animal_id: str, run_name: str = "default") -> None:
        """Clear PSD review status for (animal, run_name)."""
        self._entries[animal_id].psd_status.pop(run_name, None)
        self.save()

    def reset_sleep_qc(self, animal_id: str) -> None:
        """Clear sleep QC status (and the PSD metadata that depends on it)."""
        entry = self._entries[animal_id]
        entry.sleep_qc = None
        entry.psd_status = {}
        entry.drink_mask = None
        self.save()


def _is_legacy_file(path: Path) -> bool:
    """True if manifest.json exists in the pre-single-combo (bare animal dict) format."""
    if not path.exists():
        return False
    with path.open("r", encoding="utf-8") as f:
        return "animals" not in json.load(f)
