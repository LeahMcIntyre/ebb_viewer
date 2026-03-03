# model.py (or top of file for now)
import bisect
from dataclasses import dataclass, field
from typing import Iterator, List, Tuple, Dict, Optional
import numpy as np

Span = Tuple[int, int]  # [start_sample, end_sample)


@dataclass
class ParamSpec:
    """UI constraints for a single metadata parameter."""
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    decimals: int = 4        # for float widgets only
    units: Optional[str] = None  # displayed as spinbox suffix, e.g. " s", " Hz"
    desc: Optional[str] = None


@dataclass
class Mask:
    """A single 1D mask aligned to samples (no channels, just time)."""
    name: str
    color: tuple[int, int, int, int]  # RGBA
    spans: List[Span] = field(default_factory=list)
    enabled: bool = True  # we'll use this later for toggling
    metadata: Dict = field(default_factory=dict)
    param_specs: Dict[str, ParamSpec] = field(default_factory=dict)

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
    
    @property
    def total_samples(self) -> int:
        """Total number of samples spanned by this mask."""
        return sum(e - s for s, e in self.spans)

    def next_span_after(self, sample: int) -> "Span | None":
        """First span that starts after `sample`, or None.

        If `sample` falls inside a span, the span after it is returned.
        """
        if not self.spans:
            return None
        starts = [s for s, _ in self.spans]
        idx = bisect.bisect_right(starts, sample)
        return self.spans[idx] if idx < len(self.spans) else None

    def prev_span_before(self, sample: int) -> "Span | None":
        """Last span whose start is strictly before `sample`, or None.

        If `sample` is exactly at a span's start, the span before it is returned.
        If `sample` falls inside a span, that span is returned (jump to its start).
        """
        if not self.spans:
            return None
        starts = [s for s, _ in self.spans]
        idx = bisect.bisect_left(starts, sample) - 1
        return self.spans[idx] if idx >= 0 else None

    def overlap_samples(self, other: "Mask") -> int:
        """Number of samples where this mask and `other` both have spans."""
        total = 0
        i, j = 0, 0
        while i < len(self.spans) and j < len(other.spans):
            #Get the next span that starts latest (lo) and then the span that ends first (hi)
            lo = max(self.spans[i][0], other.spans[j][0])
            hi = min(self.spans[i][1], other.spans[j][1])
            # If lo > hi then one span ends before the other starts 
            if lo < hi:
                total += hi - lo
            # Advance the span tracker of whichever span ends first
            if self.spans[i][1] < other.spans[j][1]:
                i += 1
            else:
                j += 1
        return total



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