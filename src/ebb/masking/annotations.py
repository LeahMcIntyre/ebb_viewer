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
    pad_sec: float,
    size: int,
    fs: float,
    **kwargs,
) -> npt.NDArray[np.bool_]:
    """Returns a boolean mask by matching annotation labels as substrings.

    Unlike ``artifact``, which requires exact label matches, this function
    marks any annotation whose label *contains* a keyword (case-insensitive)
    as an artifact.  The masked region for each matching annotation spans
    ``[t, t + pad_sec)`` from the annotation start, making it suitable for
    events that are annotated only at their onset.

    Times are adjusted relative to the first annotation in the file, consistent
    with ``artifact``.

    Args:
        path:
            Pinnacle annotation file path.
        keywords:
            Substrings to search for in annotation labels.  An annotation
            matches if its label contains *any* keyword (case-insensitive).
        pad_sec:
            Duration in seconds to mask after each matching annotation start.
        size:
            Length of the boolean mask to return (number of samples).
        fs:
            Sampling rate in Hz.
        kwargs:
            Forwarded to openseize's Pinnacle initializer (e.g. ``start=6``).

    Returns:
        A 1-D boolean array of length ``size`` where masked regions are False.

    Examples:
        >>> from ebb.masking.annotations import keyword_mask
        >>> mask = keyword_mask("annots.txt", keywords=["drink"], pad_sec=10,
        ...                     size=n_samples, fs=250)
    """
    start = kwargs.pop('start', 6)
    with annotations.Pinnacle(path, start=start, **kwargs) as reader:
        annotes = reader.read()

    if not annotes:
        return np.ones(size, dtype=bool)

    keywords_lower = [k.strip().lower() for k in keywords if k.strip()]
    if not keywords_lower:
        return np.ones(size, dtype=bool)

    # Adjust times relative to first annotation, consistent with artifact()
    t0 = annotes[0].time
    matched_times = [
        ann.time - t0
        for ann in annotes
        if ann.label is not None
        and any(kw in ann.label.strip().lower() for kw in keywords_lower)
    ]

    arr = np.ones(size, dtype=bool)
    pad_samples = max(1, int(pad_sec * fs))
    for t in matched_times:
        start_sample = int(t * fs)
        end_sample = min(start_sample + pad_samples, size)
        if 0 <= start_sample < size:
            arr[start_sample:end_sample] = False

    return arr
