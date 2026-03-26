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
    """A single mask aligned to samples.

    For uniform masks (same spans on all channels), populate `spans`.
    For per-channel masks, populate `per_channel_spans` instead; `spans`
    will be ignored by the renderer in that case.
    """
    name: str
    color: tuple[int, int, int, int]  # RGBA
    spans: List[Span] = field(default_factory=list)
    enabled: bool = True
    metadata: Dict = field(default_factory=dict)
    param_specs: Dict[str, ParamSpec] = field(default_factory=dict)
    per_channel_spans: Optional[Dict[int, List[Span]]] = field(default=None)

    @property
    def all_spans(self) -> List[Span]:
        """Sorted, merged union of spans across all channels (for navigation/overlap)."""
        if self.per_channel_spans is None:
            return self.spans
        combined = sorted(
            (span for spans in self.per_channel_spans.values() for span in spans),
            key=lambda s: s[0],
        )
        merged: List[Span] = []
        for start, end in combined:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    def spans_for_channel(self, ch_idx: int) -> List[Span]:
        """Return the spans to display for a given channel index."""
        if self.per_channel_spans is not None:
            return self.per_channel_spans.get(ch_idx, [])
        return self.spans

    @classmethod
    def from_per_channel_intervals(
        cls,
        name: str,
        color,
        intervals_by_channel: Dict[int, np.ndarray],
        fs: int,
        n_samples: int,
    ) -> "Mask":
        """Build a per-channel mask from per-channel [start_sec, end_sec] interval arrays.

        Args:
            intervals_by_channel: mapping of channel index → (N, 2) array of
                [start_sec, end_sec] pairs in seconds.
            fs: sample rate in Hz.
            n_samples: total length of the recording in samples.
        """
        per_channel_spans: Dict[int, List[Span]] = {}
        for ch_idx, intervals in intervals_by_channel.items():
            intervals = np.asarray(intervals)
            if intervals.size == 0:
                continue
            if intervals.ndim == 1:
                intervals = intervals.reshape(1, 2)
            spans: List[Span] = []
            for start_sec, end_sec in intervals:
                s = max(0, int(np.floor(start_sec * fs)))
                e = min(n_samples, int(np.ceil(end_sec * fs)))
                if s < e:
                    spans.append((s, e))
            if spans:
                per_channel_spans[ch_idx] = spans
        return cls(name=name, color=color, per_channel_spans=per_channel_spans)

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
        """Total number of samples spanned by this mask (union across channels)."""
        return sum(e - s for s, e in self.all_spans)

    def next_span_after(self, sample: int) -> "Span | None":
        """First span that starts after `sample`, or None.

        If `sample` falls inside a span, the span after it is returned.
        Uses the union of all channels for per-channel masks.
        """
        spans = self.all_spans
        if not spans:
            return None
        starts = [s for s, _ in spans]
        idx = bisect.bisect_right(starts, sample)
        return spans[idx] if idx < len(spans) else None

    def prev_span_before(self, sample: int) -> "Span | None":
        """Last span whose start is strictly before `sample`, or None.

        If `sample` is exactly at a span's start, the span before it is returned.
        If `sample` falls inside a span, that span is returned (jump to its start).
        Uses the union of all channels for per-channel masks.
        """
        spans = self.all_spans
        if not spans:
            return None
        starts = [s for s, _ in spans]
        idx = bisect.bisect_left(starts, sample) - 1
        return spans[idx] if idx >= 0 else None

    def overlap_samples(self, other: "Mask") -> int:
        """Number of samples where this mask and `other` both have spans.

        Uses the union across channels for per-channel masks.
        """
        a, b = self.all_spans, other.all_spans
        total = 0
        i, j = 0, 0
        while i < len(a) and j < len(b):
            lo = max(a[i][0], b[j][0])
            hi = min(a[i][1], b[j][1])
            if lo < hi:
                total += hi - lo
            if a[i][1] < b[j][1]:
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