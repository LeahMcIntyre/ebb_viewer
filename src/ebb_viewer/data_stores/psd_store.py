"""In-memory PSD store loaded from a per-run pkl file.

Indexes one ``psds_*.pkl`` file as ``by_animal[animal][state][channel] -> (freqs, psd)``
for the PSD review widgets to consume.
"""

import pickle
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from ebb_viewer.pipeline.naming import parse_animal_id


def parse_animal_from_path_masks(rec: dict) -> str:
    """Animal display key including ``_artifact`` / ``_drink`` suffixes for variant PSDs."""
    animal = parse_animal_id(rec["path"])
    a_mask = "_artifact" if rec.get("used_artifact", False) else ""
    d_mask = "_drink" if rec.get("used_drink", False) else ""
    return f"{animal}{a_mask}{d_mask}"


class PSDStore:
    """Indexed view of a single ``psds_*.pkl`` for the PSD review widgets.

    Layout: ``by_animal[animal][state][channel_name] -> (freqs, psd)``.

    Raises ``ValueError`` on load if the PKL's records have mismatched
    frequency vectors — every record in a run is expected to be computed on
    the same frequency grid.
    """

    def __init__(
        self,
        pkl_path: str | Path,
        *,
        channel_names: Sequence[str] | None = None,
        parse_animal=parse_animal_from_path_masks,
    ):
        self.pkl_path = Path(pkl_path)
        self.channel_names = list(channel_names) if channel_names else None
        self.parse_animal = parse_animal
        self.first_freqs: np.ndarray = np.empty(0)

        self.by_animal: dict[str, dict[str, dict[str, tuple[np.ndarray, np.ndarray]]]] = {}
        self._source_combos: dict[str, str] = {}  # raw_animal_id -> source_combo
        self._load()

    def _load(self):
        with open(self.pkl_path, "rb") as f:
            items = pickle.load(f)
        if isinstance(items, dict):
            items = [items]

        self.first_freqs = np.asarray(items[0]["freqs"], float)
        for rec in items:
            freqs = np.asarray(rec["freqs"], float)
            # Validate before mutating so a mismatch can't leave the store
            # half-populated.
            if not np.allclose(self.first_freqs, freqs):
                raise ValueError(
                    f"PSDs in {self.pkl_path} do not have PSDs with the same frequency values."
                )

            animal = self.parse_animal(rec)
            raw_animal = parse_animal_id(rec["path"])
            if "source_combo" in rec:
                self._source_combos[raw_animal] = rec["source_combo"]

            # behavior is stored as e.g. ('threshold', 'wake'); index 1 is the state.
            bhv = rec.get("behavior", (None, None))
            state = bhv[1] if isinstance(bhv, (list, tuple)) and len(bhv) >= 2 else "unknown"

            psd = np.asarray(rec["psd"], float)  # shape (C, F)
            chidx = list(rec["channels"])

            ch_map: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            for i, ci in enumerate(chidx):
                name = (
                    self.channel_names[ci]
                    if (self.channel_names and 0 <= ci < len(self.channel_names))
                    else str(ci)
                )
                ch_map[name] = (freqs, psd[i])

            self.by_animal.setdefault(animal, {})[state] = ch_map

    def animals(self) -> list[str]:
        return sorted(self.by_animal.keys())

    def states(self, animal: str) -> list[str]:
        return sorted(self.by_animal.get(animal, {}).keys())

    def get(self, animal: str, state: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        return self.by_animal[animal][state]

    def freqs(self):
        return self.first_freqs

    def freq_res(self):
        return self.first_freqs[1] - self.first_freqs[0]

    def freq_range(self):
        return [self.first_freqs[0], self.first_freqs[-1]]

    def source_combo(self, animal_id: str) -> "str | None":
        """Return the source_combo for animal_id if present in the PKL (final PKL only)."""
        return self._source_combos.get(animal_id)
