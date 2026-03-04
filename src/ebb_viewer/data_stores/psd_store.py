from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union
import numpy as np, pickle

# TODO: Make this more flexible/customizable
def parse_animal_from_path(path: Union[str, Path]) -> str:
    """Example: take the EDF stem up to first space as the animal ID."""
    stem = Path(path).stem
    return stem.split('_')[0] if "_" in stem else stem

def parse_animal_from_path_masks(rec: Dict) -> str:
    stem = Path(rec['path']).stem
    animal = stem.split('_')[0] if "_" in stem else stem
    a_mask = "_artifact" if rec.get('used_artifact', False) else ""
    d_mask = "_drink" if rec.get('used_drink', False) else ""
    return f"{animal}{a_mask}{d_mask}"

class PSDStore:
    # by_animal[animal][state][channel_name] -> (freqs, psd)
    def __init__(
        self,
        pkl_path: Union[str, Path],
        *,
        channel_names: Optional[Sequence[str]] = None,
        parse_animal = parse_animal_from_path_masks,
    ):
        self.pkl_path = Path(pkl_path)
        self.channel_names = list(channel_names) if channel_names else None
        self.parse_animal = parse_animal
        self.first_freqs = []

        self.by_animal: Dict[str, Dict[str, Dict[str, Tuple[np.ndarray, np.ndarray]]]] = {}
        self._load()

    def _load(self):
        with open(self.pkl_path, "rb") as f:
            items = pickle.load(f)
        if isinstance(items, dict):
            items = [items]

        # TODO: Better way to implement this?

        self.first_freqs = np.asarray(items[0]["freqs"], float)
        for rec in items:
            animal = self.parse_animal(rec)
            # behavior like ('threshold','wake') -> we care about state='wake'
            bhv = rec.get("behavior", (None, None))

            # TODO: This is a bit hacky; improve behavior handling
            state = bhv[1] if isinstance(bhv, (list, tuple)) and len(bhv) >= 2 else "unknown"

            freqs = np.asarray(rec["freqs"], float)
            psd   = np.asarray(rec["psd"],   float)  # shape (C, F)
            chidx = list(rec["channels"])

            # channel map
            ch_map: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
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
                raise ValueError(f"PSDs in {self.pkl_path} do not have PSDs with the same frequency values.")

    def animals(self) -> List[str]:
        return sorted(self.by_animal.keys())

    def states(self, animal: str) -> List[str]:
        return sorted(self.by_animal.get(animal, {}).keys())

    def get(self, animal: str, state: str) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
        return self.by_animal[animal][state]

    def freqs(self):
        return self.first_freqs
    
    def freq_res(self):
        return (self.first_freqs[1]-self.first_freqs[0])
    
    def freq_range(self):
        return [self.first_freqs[0], self.first_freqs[-1]]