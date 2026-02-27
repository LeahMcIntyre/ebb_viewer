# model.py (or top of file for now)
from dataclasses import dataclass, field
from typing import Iterator, List, Tuple, Dict
import numpy as np

Span = Tuple[int, int]  # [start_sample, end_sample)


@dataclass
class Mask:
    """A single 1D mask aligned to samples (no channels, just time)."""
    name: str
    color: tuple[int, int, int, int]  # RGBA
    spans: List[Span] = field(default_factory=list)
    enabled: bool = True  # we'll use this later for toggling

    @classmethod
    def from_bool(cls, name: str, color, arr: np.ndarray) -> "Mask":
        """Convert a (n_samples,) bool array into contiguous True spans."""
        arr = np.asarray(arr, dtype=bool)
        if arr.ndim != 1:
            raise ValueError("Mask array must be 1D (n_samples,)")

        n = arr.size
        if n == 0:
            return cls(name=name, color=color, spans=[])

        x = arr.astype(int)
        diff = np.diff(x)
        starts = np.where(diff == 1)[0] + 1
        stops  = np.where(diff == -1)[0] + 1

        if arr[0]:
            starts = np.r_[0, starts]
        if arr[-1]:
            stops = np.r_[stops, n]

        spans: List[Span] = [(int(s), int(e)) for s, e in zip(starts, stops)]
        return cls(name=name, color=color, spans=spans)


@dataclass
class MaskSet:
    """Simple collection of masks keyed by name."""
    masks: Dict[str, Mask] = field(default_factory=dict)

    def add(self, mask: Mask) -> None:
        self.masks[mask.name] = mask

    def get(self, name: str) -> Mask | None:
        return self.masks.get(name)

    def __iter__(self) -> Iterator[Mask]:
        return iter(self.masks.values())