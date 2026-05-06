"""Numpy helpers for working with 1D boolean arrays as discrete event spans."""

from collections import deque

import numpy as np
import numpy.typing as npt


def discretize_bool(mask: npt.NDArray[np.bool_]) -> npt.NDArray[np.intp]:
    """Returns discrete start and stop indexes for True runs in mask.

    Args:
        mask:
            A 1-D boolean array to discretize into events.

    Examples:
        >>> import numpy as np
        >>> x = np.array([1, 1, 0, 0, 0, 1, 1, 0, 1], dtype=bool)
        >>> discretize_bool(x)
        array([[0, 2],
               [5, 7],
               [8, 9]])

    Returns:
        An ndarray of shape (events, 2) with [start, stop) slicing semantics.
    """

    # Append a sentinel False so a True run at the end produces a closing changepoint.
    if mask[-1]:
        mask = np.append(mask, False)

    # prepend=0 ensures a leading True at index 0 registers as a +1 transition.
    changepoints = np.diff(mask, prepend=0)
    return np.where(changepoints)[0].reshape(-1, 2)


def aggregate1d(arr: npt.NDArray[np.bool_], radius: float) -> npt.NDArray[np.intp]:
    """Returns start, stop indices for runs of True elements in a 1D
    boolean array that are within `radius` distance of one another.

    Args:
        arr:
            A 1-D boolean whose True runs are to be aggregated.
        radius:
            The maximum index distance between two True elements in arr below
            which the elements are combined into the same run.

    Examples:
        >>> x = np.array([0, 1, 1, 0, 1, 0, 0, 0, 1, 0, 0, 1], dtype=bool)
        >>> y = aggregate1d(x, radius=3)
        >>> y
        array([[ 1,  5],
               [ 8, 12]])

    Returns:
        A 2D array of shape (n, 2) with [start, stop) indices for each
        aggregated True run. Returns an empty (0, 2) array if `arr` has no
        True elements.
    """

    if arr.ndim > 1:
        raise ValueError("arr argument must be 1D")

    locs = np.flatnonzero(arr)
    if locs.size == 0:
        return np.empty((0, 2), dtype=int)

    result = []
    deck = deque(locs)
    sublist = [deck.popleft()]
    while deck:
        item = deck.popleft()
        if abs(item - sublist[-1]) <= radius:
            sublist.append(item)
        else:
            result.append(sublist)
            sublist = [item]
    result.append(sublist)

    # +1 on stop for [start, stop) slicing consistency
    return np.array([(r[0], r[-1] + 1) for r in result], dtype=int)
