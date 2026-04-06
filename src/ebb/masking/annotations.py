from pathlib import Path
from typing import List, Optional, Tuple, Union, Iterable

import numpy as np
import numpy.typing as npt

from openseize.file_io import annotations

def artifact(path: Union[str, Path],
             size: int,
             labels: List[str],
             fs: float,
             between: Tuple[Union[str, None], Union[str, None]]=(None, None),
             include = False,
             **kwargs,
) -> npt.NDArray[np.bool_]:
    """Returns a boolean mask from a Pinnacle annotations file.

    Args:
        path:
            Pinnacle file path containing annotations.
        size:
            The length of the mask to return.
        labels:
            The artifact labels that are to be marked False in the returned
            boolean.
        fs:
            The sampling rate in Hertz of the data acquisition.
        between:
            The start and stop annotation labels between which labeled
            annotations will be included in the mask.
        kwargs:
            Keyword arguments are passed to openseize's Pinnacle initializer.

    Examples:
        >>> from openseize import demos
        >>> import numpy as np
        >>> path = demos.paths.locate('annotations_001.txt')
        >>> fs = 5000
        >>> size = 3775 * 5000
        >>> amask = artifact(path, size=size, labels=['rest'], fs=fs)
        >>> # validate 1st set of Falses in mask occurs at 1st annote
        >>> with annotations.Pinnacle(path, start=6) as reader:
        ...     annotes = reader.read('rest')
        >>> start, duration = annotes[0].time, annotes[0].duration
        >>> np.any(amask[int(start*5000): int((start+duration) * 5000)])
        False

    Returns:
        A 1-D boolean mask in which labeled indices are marked False.
    """

    start = kwargs.pop('start', 6)
    with annotations.Pinnacle(path, start=start, **kwargs) as reader:
        annotes = reader.read()

    # get first and last annote to return that are in between
    a, b = between
    first = next(ann for ann in annotes if ann.label == a) if a else annotes[0]
    last = next(ann for ann in annotes if ann.label == b) if a else annotes[-1]


    #filter the annotes for requested labels and filter between
    labels_clean = {lbl.strip().lower() for lbl in labels}

    annotes = [
        ann for ann in annotes
        if ann.label is not None
        and ann.label.strip().lower() in labels_clean
    ]
    
    annotes = [ann for ann in annotes if first.time <= ann.time <= last.time]
    # adjust the annote times relative to first annote
    for annote in annotes:
        annote.time -= first.time

    return annotations.as_mask(annotes, size, fs, include=include)


def keyword_mask(
    path: Union[str, Path],
    keywords: List[str],
    size: int,
    fs: float,
    pad_after_sec: float = 0.0,
    pad_before_sec: float = 0.0,
    match_mode: str = "contains",
    **kwargs,
) -> npt.NDArray[np.bool_]:
    """Returns a boolean mask by matching annotation labels.

    For each matching annotation at time ``t``, the masked region spans
    ``[t - pad_before_sec, t + pad_after_sec)``.  At minimum, the sample at
    ``t`` is always masked (i.e. ``pad_after_sec=0`` still marks one sample).

    Times are adjusted relative to the first annotation in the file, consistent
    with ``artifact``.

    Args:
        path:
            Pinnacle annotation file path.
        keywords:
            Labels (or substrings) to match.  Case-insensitive.  An annotation
            matches if *any* keyword matches according to ``match_mode``.
        size:
            Length of the boolean mask to return (number of samples).
        fs:
            Sampling rate in Hz.
        pad_after_sec:
            Seconds to mask *after* each matching annotation.  Defaults to 0
            (only the annotation sample itself is masked).
        pad_before_sec:
            Seconds to mask *before* each matching annotation.  Defaults to 0.
        match_mode:
            ``"contains"`` (default) — annotation label contains the keyword
            as a substring.  ``"exact"`` — full label must equal the keyword.
        kwargs:
            Forwarded to openseize's Pinnacle initializer (e.g. ``start=6``).

    Returns:
        A 1-D boolean array of length ``size`` where masked regions are False.

    Examples:
        >>> from ebb.masking.annotations import keyword_mask
        >>> mask = keyword_mask("annots.txt", keywords=["drink"],
        ...                     pad_after_sec=10, size=n_samples, fs=250)
    """
    start = kwargs.pop('start', 6)
    with annotations.Pinnacle(path, start=start, **kwargs) as reader:
        annotes = reader.read()

    if not annotes:
        return np.ones(size, dtype=bool)

    keywords_lower = [k.strip().lower() for k in keywords if k.strip()]
    if not keywords_lower:
        return np.ones(size, dtype=bool)

    if match_mode == "exact":
        keywords_set = set(keywords_lower)
        def _matches(label: str) -> bool:
            return label.strip().lower() in keywords_set
    else:
        def _matches(label: str) -> bool:
            return any(kw in label.strip().lower() for kw in keywords_lower)

    # Adjust times relative to first annotation, consistent with artifact()
    t0 = annotes[0].time
    matched_times = [
        ann.time - t0
        for ann in annotes
        if ann.label is not None and _matches(ann.label)
    ]

    arr = np.ones(size, dtype=bool)
    before_samples = int(pad_before_sec * fs)
    after_samples = max(1, int(pad_after_sec * fs))
    for t in matched_times:
        t_sample = int(t * fs)
        start_sample = max(0, t_sample - before_samples)
        end_sample = min(t_sample + after_samples, size)
        if start_sample < size:
            arr[start_sample:end_sample] = False

    return arr
