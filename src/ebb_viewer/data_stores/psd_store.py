import pickle
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from ebb_viewer.pipeline.naming import parse_animal_id


def parse_animal_from_path(path: str | Path) -> str:
    return parse_animal_id(path)


def parse_animal_from_path_masks(rec: dict) -> str:
    animal = parse_animal_id(rec["path"])
    a_mask = "_artifact" if rec.get("used_artifact", False) else ""
    d_mask = "_drink" if rec.get("used_drink", False) else ""
    return f"{animal}{a_mask}{d_mask}"


class PSDStore:
    # by_animal[animal][state][channel_name] -> (freqs, psd)
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
        self.first_freqs = []

        self.by_animal: dict[str, dict[str, dict[str, tuple[np.ndarray, np.ndarray]]]] = {}
        self._load()

    def _load(self):
        with open(self.pkl_path, "rb") as f:
            items = pickle.load(f)
        if isinstance(items, dict):
            items = [items]

        # TODO: Better way to implement this?

        self._source_combos: dict[str, str] = {}  # raw_animal_id -> source_combo

        self.first_freqs = np.asarray(items[0]["freqs"], float)
        for rec in items:
            animal = self.parse_animal(rec)
            raw_animal = parse_animal_id(rec["path"])
            if "source_combo" in rec:
                self._source_combos[raw_animal] = rec["source_combo"]
            # behavior like ('threshold','wake') -> we care about state='wake'
            bhv = rec.get("behavior", (None, None))

            # TODO: This is a bit hacky; improve behavior handling
            state = bhv[1] if isinstance(bhv, (list, tuple)) and len(bhv) >= 2 else "unknown"

            freqs = np.asarray(rec["freqs"], float)
            psd = np.asarray(rec["psd"], float)  # shape (C, F)
            chidx = list(rec["channels"])

            # channel map
            ch_map: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            for i, ci in enumerate(chidx):
                name = (
                    self.channel_names[ci]
                    if (self.channel_names and 0 <= ci < len(self.channel_names))
                    else str(ci)
                )
                ch_map[name] = (freqs, psd[i])

            self.by_animal.setdefault(animal, {})[state] = ch_map

            # Raise an error if the freqs are not all the same
            if not np.allclose(self.first_freqs, freqs):
                raise ValueError(
                    f"PSDs in {self.pkl_path} do not have PSDs with the same frequency values."
                )

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
