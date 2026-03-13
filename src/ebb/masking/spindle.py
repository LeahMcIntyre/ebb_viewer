import csv
import functools
from pathlib import Path
from typing import List, Optional, Tuple, Union, Iterable

import numpy as np
import numpy.typing as npt

def state(path: Union[str, Path], 
          labels: List[str],
          fs: int = 250, 
          winsize: int = 4, 
          include=True
) -> npt.NDArray[np.bool_]:
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
            returned mask.
            
    Returns:
        A 1-D boolean array state mask 
    """
    
    
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

def state_prob(path: Union[str, Path], 
          label: str,
          fs: int = 250, 
          winsize: int = 4, 
          sprob=0.9,
) -> npt.NDArray[np.bool_]:
    """Returns a boolean mask from a spindle sleep score csv file. Uses values from 'rawstate' column
    as to include values listed as spindle artifacts (separate artifact mask). Default returns True for samples where 
    rawstate matches label. 

    Args:
        path:
            A path to a spindle file.
        labels:
            A label to to get the class probability for.
        fs:
            The sampling rate of the data this mask will be applied.
        winsize:
            The window length in seconds that spindle used to estimate states.
        state_prob: 
            The class probability the an epoch must be to be considered as being the label
            
    Returns:
        A 1-D boolean array state mask 
    """
    state_mask = state(path, labels=[label], fs=fs, winsize=winsize, include=True)

    p_column = {'w': 'class_prob_0', 'n': 'class_prob_1', 'r': 'class_prob_2'}
    def above_thresh(val):
        return float(val) >= sprob
    

    prob_mask = _expand_spindle_column(
        path=path,
        column_name=p_column[label],
        fs=fs,
        winsize=winsize,
        value_fn=above_thresh,
        include=True
    )

    return state_mask & prob_mask

def spindle_noise(path: Union[str, Path], 
                  noise_thresh: float = 0.5,
                  fs: int = 250, 
                  winsize: int = 4, 
                  include=False
) -> npt.NDArray[np.bool_]:
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
            returned mask.
            
    Returns:
        A 1-D boolean array state mask         
    """
    
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


def _expand_spindle_column(path, column_name, fs, winsize, value_fn, include=True):
    """Generic helper to read a column from spindle CSV and expand to sample mask.

    Args:
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

    Returns:
        1-D boolean array mask
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