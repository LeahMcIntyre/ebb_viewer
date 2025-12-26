"""This module contains functions for building 1-D boolean masks. These masks
may be built from human annotated text files, spindle state text files or
computationally computed using a local z-score threshold.

Functions:
    threshold:
        Returns a 1-D boolean by z-score thresholding produced values from
        a producer.
    artifact:
        Returns a 1-D boolean by reading human created annotations stored in
        a Pinnacle annotations file.
    state:
        Returns a 1-D boolean by reading Spindle detected sleep and wake states
        from a Spindle formatted file.
    drinking_mask:
        Returns a 1-D boolean by reading a npy file from the video-based drinking
        classification

"""

import csv
import functools
from itertools import zip_longest
from pathlib import Path
from typing import List, Optional, Tuple, Union, Iterable

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.io import loadmat

from openseize.core.producer import producer, Producer
from openseize.file_io import annotations
from ebbv2.core import arraytools



def threshold(pro: Producer,
              nstds: List[float],
              winsize: int,
              mask_pro: Optional[Producer] = None,
              radius: Optional[int] = None,
) -> List[npt.NDArray[np.bool_]]:
    """Thresholds the z-score of produced values using each standard deviation
    in nstds.

    Args:
        pro:
            A producer of ndarrays to be thresholded.
        nstds:
            A list of standard deviations to threshold normalized producer
            values.
        winsize:
            The number of samples used to estimate the mean and standard
            deviation to normalize the produced values by.
        mask_pro:
            Optional: A producer of a commutator artifact mask to apply when calculating
            the standard deviation (so commutator artifacts will not inflate standard deviation). 
        radius:
            Optional: The max distance below which all intermediate samples between two
            samples are interpolated to be False.

    Returns:
        A list of 1-D boolean arrays one per standard dev. in nstds.
    """

    # Set chunksize of the producer
    pro.chunksize = winsize
    if mask_pro:
        mask_pro.chunksize = winsize
    axis = pro.axis

    # initialize some mask
    masks = [np.ones(pro.shape[axis], dtype=bool) for std in nstds]
    # Iterate through the data producer and the mask (if provided) together
    mask_pro_iter = iter(mask_pro) if mask_pro else None
    for idx, arr in enumerate(pro):
        if mask_pro_iter:
            commute_mask = next(mask_pro_iter)
            # Create array that masks out commutator artifacts and calculate sd 
            masked_arr = arr[:, commute_mask]
        else:
            masked_arr = arr

        mu = np.mean(masked_arr, axis=axis, keepdims=True)
        std = np.std(masked_arr, axis=axis, keepdims=True)

        if not np.any(std):
            std = np.ones_like(std)

        arr -= mu
        arr /= std
        for sigma, mask in zip(nstds, masks):
            _, cols = np.where(np.abs(arr) > sigma)
            cols = np.unique(cols + idx * pro.chunksize)
            mask[cols] = False

    # Fill between 2 False events with False if sample distance < radius
    if radius:
        for mask in masks:
            for epoch in arraytools.aggregate1d(~mask, radius):
                mask[slice(*epoch)] = False

    return masks

def commutator_threshold(pro: Producer,
                    value: int,
                    radius: int,
                    pad: int,
                    min_to_pad:int,
                    two_sided=True):
    """Creates a mask that thresholds samples produced from pro at a
    constant value.

    Args:
        pro:
            A producer of ndarrays to be thresholded.
        value:
            The amplitude limit above or below which values in returned mask
            will be set to False.
        radius:
            The max distance below which all intermediate samples between two
            samples are interpolated to be False.
        pad:
            amount of samples to also mask following a detected event that
            exceeds min_to_pad samples
        min_to_pad:
            if a detected event's length in samples exceeds this value a padding
            of the event occurs.
        two_sided:
            A boolean indicating if the threshold should be applied at both
            + and - abs(value).

    Returns:
        A boolean mask the same length as the producer
    """

    axis = pro.axis

    mask = np.ones(pro.shape[axis], dtype=bool)

    for idx, arr in enumerate(pro):

        x = np.abs(arr) if two_sided else arr
        _, cols = np.where(x > value)
        cols = np.unique(cols + idx * pro.chunksize)
        mask[cols] = False

    epochs = []
    if np.all(mask):
        return mask, epochs

    for epoch in arraytools.aggregate1d(~mask, radius):

        # min_to_pad ensures we don't pad artifacts which can exceed value
        if epoch[1] - epoch[0] > min_to_pad:
            epoch += np.array([0, pad])

        mask[slice(*epoch)] = False
        epochs.append(epoch)

    return mask, epochs


def drinking_mask(mask_path: Union[str, Path],
                  offset_sec: Optional[float] = None,
                  fs: int = 250, 
                  pad_sec: int = 2):
    """
    Builds a drinking mask from a 1 Hz .npy file.

    Args:
        mask_path:
            Path to a 1D boolean/int array at 1 Hz (per-second labels).
        offset_sec:
            Optional: The value (in seconds) to pad to the beginning of the mask
        fs: 
            Target sampling rate for the output mask (samples/sec).
        pad_sec: 
            Pad events by this many seconds on each side (at 1 Hz before upsampling).

    Returns:
        A 1-D boolean array where drinking events and padding are False.
    """
    mask_sec = np.asarray(np.load(Path(mask_path)), dtype=bool)  # per-second mask
    
    # Dilate events by pad_sec on each side at 1 Hz
    pad = int(pad_sec)
    # Convolution-based dilation at 1 Hz
    k = np.ones(2 * pad + 1, dtype=int)
    dil = np.convolve(mask_sec.astype(int), k, mode='same') > 0
    mask_sec = dil

    # --- upsample to sample rate ---
    mask_samples = np.repeat(mask_sec, fs)


    # --- apply offset as a right shift (insert False at start, drop tail) ---
    if (offset_sec):
        shift = int(round(offset_sec * fs))
        mask_samples = np.pad(mask_samples, (shift, 0), constant_values=False)[:-shift]
    
    return ~mask_samples.astype(bool)

def get_offset(mask_path, offset_path):
    
    animal = Path(mask_path).stem.split('_')[0]
    offsets = pd.read_csv(offset_path)
    #Get the offset between the mask from video and the eeg recording
    return offsets[offsets['Animal']==animal]['Offset'].values[0]


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



def state(path: Union[str, Path], 
          labels: List[str],
          fs: int = 250, 
          winsize: int = 4, 
          include=True):
    """Returns a boolean mask from a spindle sleep score csv file. Uses values from 'rawstate' column
    as to include values listed as spindle artifacts (separate artifact mask). Default returns True for samples where 
    rawstate matches label. 

    Args:
        path:
            A path to a spindle file.
        labels:
            A list of labels to include or exclude depending on include
            argument.
        fs:
            The sampling rate of the data this mask will be applied.
        winsize:
            The window length in seconds that spindle used to estimate states.
        include:
            A boolean indicating if labels should be included (i.e. True) and
            all else False or labels should be excluded (i.e. False) from the
            returned mask."""

    def is_in_labels(s):
        return s in labels

    return _expand_spindle_column(
        path=path,
        column_name="rawstate",
        fs=fs,
        winsize=winsize,
        value_fn=is_in_labels,
        include=include,
    )   

def spindle_noise(path: Union[str, Path], 
                  noise_thresh: float = 0.5,
                  fs: int = 250, 
                  winsize: int = 4, 
                  include=False):
    """Returns a boolean mask from a spindle sleep score csv file. Default returns False for 
    samples with a noise probability >= noise_thresh. 

    Args:
        path:
            A path to a spindle file.
        noise_thresh:
            A noise probability threshold between 0-1. Samples with value >= noise_thresh will be False
            in mask (when include=False). 
        fs:
            The sampling rate of the data this mask will be applied.
        winsize:
            The window length in seconds that spindle used to estimate states.
        include:
            A boolean indicating if labels should be included (i.e. True) and
            all else False or labels should be excluded (i.e. False) from the
            returned mask."""
    
    def above_thresh(val):
        return float(val) >= noise_thresh

    return _expand_spindle_column(
        path=path,
        column_name="noise_probs",
        fs=fs,
        winsize=winsize,
        value_fn=above_thresh,
        include=include,
    )


def swd(path: Union[str, Path], 
        n_samples: int, 
        fs: int = 250, 
        label: str ='DEL_ts', 
        pad_sec: int=0):
    
    """
    Builds a mask from a .mat file containing time stamps of SWDs.

    Args:
        path:
            Path to a .mat file containing the SWDs
        n_samples:
            Number of samples the mask must be (number of samples in .edf file)
        fs: 
            Target sampling rate for the output mask (samples/sec).
        label:
            Label the timestamp matric is save under in .mat file. Defaults to 'DEL_ts'. If 
            label is not in the file, the first object in file will be taken as key. 
        pad_sec: 
            Pad swd events by this many seconds on each side (at 1 Hz before upsampling).

    Returns:
        A 1-D boolean array where drinking events and padding are False.
    """

    data = loadmat(path, squeeze_me=True, struct_as_record=False)

    # pick key
    keys = [k for k in data.keys() if not k.startswith('__')]
    key = label if label in keys else keys[0]

    swds = np.asarray(data[key])

    # --- handle completely empty arrays: no SWDs at all ---
    if swds.size == 0:
        return np.ones(n_samples, dtype=bool)

    # --- normalize shape to (N, 2) of [start_s, stop_s] ---
    if swds.ndim == 1:
        # If it's exactly 2 values, assume a single [start, stop]
        if swds.shape[0] == 2:
            swds = swds[np.newaxis, :]
        else:
            raise ValueError(
                f"Unexpected 1D swd array shape {swds.shape} in {path}; "
                "expected length 2 for [start, stop]."
            )
    elif swds.ndim == 2:
        if swds.shape[1] == 0:
            # (0, 0) or (0, ?) case: no intervals
            return np.ones(n_samples, dtype=bool)
        elif swds.shape[1] >= 2:
            swds = swds[:, 0:2]
        else:
            raise ValueError(
                f"2D swd array has shape {swds.shape} but needs at least 2 columns "
                "for [start, stop]."
            )
    else:
        raise ValueError(
            f"swds has ndim={swds.ndim}, expected 1D or 2D in {path}"
        )

    # now swds is (N, 2) or (0, 2)
    if swds.shape[0] == 0:
        # no intervals -> all True
        return np.ones(n_samples, dtype=bool)
    
    if pad_sec > 0:
        swds = swds + [(-1*pad_sec), pad_sec]


    iv = _seconds_to_intervals(swds, fs, n_samples)
    iv = _normalize_intervals(iv, n_samples)
    swd_mask = _intervals_to_bool_false(iv, n_samples)

    return swd_mask


def _expand_spindle_column(path, column_name, fs, winsize, value_fn, include=True):
    """Generic helper to read a column from spindle CSV and expand to sample mask.

    Parameters
    ----------
    path : str or Path
        Path to CSV file.
    column_name : str
        Name of the column to extract.
    fs : int
        Sampling rate in Hz.
    winsize : int or float
        Window size in seconds (matches spindle scoring resolution).
    value_fn : callable
        Function that maps a string value → bool (True means keep).
    include : bool
        If False, invert the resulting mask.
    """
    with open(path, "r", newline="") as infile:
        reader = csv.reader(infile)
        header = next(reader)

        if column_name not in header:
            raise ValueError(
                f"Spindle file format needs update. Expected a '{column_name}' "
                "column in the CSV header."
            )

        idx = header.index(column_name)
        values = [row[idx] for row in reader]

    mask = np.array([value_fn(v) for v in values], dtype=bool)
    if not include:
        mask = ~mask

    mask = np.atleast_2d(mask)
    expanded = np.repeat(mask, fs * winsize, axis=0)
    return expanded.flatten(order="F")

def _normalize_intervals(iv: np.ndarray, n: int) -> np.ndarray:
    """Clip to [0,n], drop empty, sort, and merge touching/overlapping intervals."""
    iv = np.clip(iv, 0, n)
    iv = iv[iv[:, 0] < iv[:, 1]]  # Remove invalid intervals
    if iv.size == 0: return iv

    iv = iv[np.argsort(iv[:, 0])]  # Sort intervals by start time
    merged = [iv[0]]
    
    for s, e in iv[1:]:
        ms, me = merged[-1]
        if s <= me:  # Overlap or touch -> merge
            merged[-1][1] = max(me, e)
        else:
            merged.append([s, e])

    return np.asarray(merged)

def _seconds_to_intervals(spans_s: Iterable[Tuple[float, float]], fs: float, n: int) -> np.ndarray:
    """Convert (start, stop) seconds to clipped, merged sample intervals."""
    arr = np.asarray(spans_s)
    if arr.size == 0: return np.empty((0, 2))
    
    # Convert seconds to sample indices
    a = np.floor(arr[:, 0] * fs).astype(int)
    b = np.ceil(arr[:, 1] * fs).astype(int)
    
    return _normalize_intervals(np.column_stack([a, b]), n)

def _intervals_to_bool_false(intervals: np.ndarray, n: int) -> np.ndarray:
    """Create a boolean mask marking the intervals as False."""
    mask = np.ones(n, dtype=bool)
    if not intervals.size: return mask
    
    diff = np.zeros(n + 1, dtype=int)
    np.add.at(diff, np.clip(intervals[:, 0], 0, n), 1)
    np.add.at(diff, np.clip(intervals[:, 1], 0, n), -1)
    
    covered = np.cumsum(diff[:-1]) > 0
    mask[covered] = False
    return mask


# DEPRECATION NOTICE
# The next release of openseize will handle producing between values along axis
# so the following will be removed when openseize v1.3.0 is released.
def _between_gen(reader, start, stop, chunksize, axis):
    """A generating function returns a generator of ndarrays of samples between
    start and stop.

    Args:
        reader:
            An openseize reader instance.
        start:
            The index at which production of values from reader begins.
        stop:
            The index at which production of values from reader ends.
        chunksize:
            The number of samples to return along axis of each yield ndarray.
        axis:
            The axis along which samples will be produced.
    
    Returns:
        A generator of ndarrays of chunksize shape along axis between start and
        stop.

    Notes:
        This is a protected module-level function that is not intended for
        external calling. Its placement at module level versus nesting is to
        support concurrent processing.
    """

    starts = np.arange(start, stop, int(chunksize))
    for a, b in zip_longest(starts, starts[1:], fillvalue=stop):
        yield reader.read(a,b)

def between_pro(reader, start, stop, chunksize, axis=-1):
    """Returns a producer from a reader instance that produces values between
    start and stop.

    Args:
        reader:
            An openseize reader instance.
        start:
            The index at which production of values from reader begins.
            The index at which production of values from reader ends.
        axis:
            The axis along which production should occur. Defaults to last axis.

    Examples:
        >>> from openseize.demos import paths
        >>> from openseize.file_io import edf
        >>> path = paths.locate('recording_001.edf')
        >>> reader = edf.Reader(path)
        >>> reader.channels = [0,1,2]
        >>> # read samples 10 to 1155 in chunks of 100
        >>> pro = between_pro(reader, 10, 1155, chunksize=100)
        >>> np.allclose(pro.to_array(), reader.read(10, 1155))
        True

    Returns:
        A producer instance producing samples between start and stop along axis.
    """

    # build a partial freezing all arg of _between_gen
    gen_func = functools.partial(_between_gen, reader, start, stop, chunksize, 
                                 axis)
    # compute the shape of the new producer
    shape = list(reader.shape)
    shape[axis] = stop - start

    return producer(gen_func, chunksize, axis, shape=shape)

