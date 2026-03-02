from typing import List, Optional

import numpy as np
import numpy.typing as npt

from openseize.core.producer import producer, Producer
from ebb.core import arraytools

def sd_threshold(pro: Producer,
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
        arr = arr.copy()
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