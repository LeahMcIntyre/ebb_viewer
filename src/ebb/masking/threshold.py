from typing import List, Optional

import numpy as np
import numpy.typing as npt

from openseize.core.producer import producer, Producer
from ebb.core import arraytools

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

import numpy as np
from scipy.signal import stft

def detect_sideband_mask(
    data,
    fs,
    nperseg=125,
    band50=(48, 52),
    band70=(68, 72),
    z_thr=4.0,
    min_dur_sec=3.0,
    gap_sec=0.75,              # <= fill short dips below threshold inside an event
    require_both=True,
    combine_channels="any",    # "any" | "all" | "mean"
    win_sec_ref=60.0,
    n_samples_ref=300,
    seed=0,
):
    """
    Returns a SAMPLE-LEVEL boolean mask:
      True  = clean
      False = detected sideband event

    Detection is done on STFT time bins, then:
      1) fill short gaps (<= gap_sec) inside events
      2) keep only events lasting >= min_dur_sec
      3) map flagged STFT bins back to samples (False)
    """

    def _fill_gaps_and_min_duration(hits, dt, gap_sec, min_dur_sec):
        hits = hits.astype(bool)
        n = hits.size
        if n == 0:
            return hits

        gap_bins = int(np.round(gap_sec / dt)) if gap_sec is not None else 0
        min_bins = int(np.ceil(min_dur_sec / dt)) if min_dur_sec is not None else 1

        # ---- 1) Fill short internal gaps (False runs bounded by True) ----
        x = hits.copy()
        if gap_bins > 0:
            i = 0
            while i < n:
                if x[i]:
                    i += 1
                    continue
                j = i
                while j < n and (not x[j]):
                    j += 1
                run_len = j - i

                left_true = (i - 1 >= 0) and x[i - 1]
                right_true = (j < n) and x[j]
                if left_true and right_true and run_len <= gap_bins:
                    x[i:j] = True
                i = j

        # ---- 2) Keep only True runs with length >= min_bins ----
        keep = np.zeros_like(x, dtype=bool)
        i = 0
        while i < n:
            if not x[i]:
                i += 1
                continue
            j = i
            while j < n and x[j]:
                j += 1
            if (j - i) >= min_bins:
                keep[i:j] = True
            i = j

        return keep

    nch, n = data.shape
    noverlap = nperseg // 2
    hop = nperseg - noverlap

    # -----------------------------
    # 1) Build GLOBAL robust baseline
    # -----------------------------
    rng = np.random.default_rng(seed)
    win_len = int(win_sec_ref * fs)
    max_start = n - win_len
    if max_start <= 0:
        raise ValueError("Recording too short for reference building.")

    starts = rng.integers(0, max_start, size=min(n_samples_ref, max_start))

    b50_vals = []
    b70_vals = []

    for s0 in starts:
        s1 = s0 + win_len
        for ch in range(nch):
            f, t, Z = stft(
                data[ch, s0:s1],
                fs=fs,
                nperseg=nperseg,
                noverlap=noverlap,
                boundary=None
            )
            p_db = 10.0 * np.log10(np.abs(Z) ** 2 + 1e-12)

            m50 = (f >= band50[0]) & (f <= band50[1])
            m70 = (f >= band70[0]) & (f <= band70[1])

            if np.any(m50):
                b50_vals.append(np.mean(p_db[m50, :], axis=0))
            if np.any(m70):
                b70_vals.append(np.mean(p_db[m70, :], axis=0))

    if not b50_vals or not b70_vals:
        raise ValueError("Reference building failed (empty band values). Check band50/band70 and fs/nperseg.")

    b50_all = np.concatenate(b50_vals)
    b70_all = np.concatenate(b70_vals)

    med50 = np.median(b50_all)
    mad50 = np.median(np.abs(b50_all - med50)) + 1e-6
    med70 = np.median(b70_all)
    mad70 = np.median(np.abs(b70_all - med70)) + 1e-6

    # -----------------------------
    # 2) Compute band z-series for full recording
    #    (chunked to be safe on 48h)
    # -----------------------------
    chunk_sec = 600.0  # 10 minutes
    chunk_len = int(chunk_sec * fs)

    # overlap chunks slightly so events near boundaries aren't lost
    chunk_step = max(chunk_len - hop * 4, chunk_len // 2)

    hits_list = []
    t_list = []

    for s0 in range(0, n - nperseg, chunk_step):
        s1 = min(s0 + chunk_len, n)
        seg_len = s1 - s0
        if seg_len < (nperseg + hop):  # need at least ~2 time bins
            break

        z50_ch = []
        z70_ch = []

        for ch in range(nch):
            f, t, Z = stft(
                data[ch, s0:s1],
                fs=fs,
                nperseg=nperseg,
                noverlap=noverlap,
                boundary=None
            )
            p_db = 10.0 * np.log10(np.abs(Z) ** 2 + 1e-12)

            m50 = (f >= band50[0]) & (f <= band50[1])
            m70 = (f >= band70[0]) & (f <= band70[1])

            if not (np.any(m50) and np.any(m70)):
                continue

            b50 = np.mean(p_db[m50, :], axis=0)
            b70 = np.mean(p_db[m70, :], axis=0)

            z50_ch.append((b50 - med50) / mad50)
            z70_ch.append((b70 - med70) / mad70)

        if not z50_ch:
            continue

        z50_ch = np.vstack(z50_ch)
        z70_ch = np.vstack(z70_ch)

        if combine_channels == "any":
            z50 = np.nanmax(z50_ch, axis=0)
            z70 = np.nanmax(z70_ch, axis=0)
        elif combine_channels == "all":
            z50 = np.nanmin(z50_ch, axis=0)
            z70 = np.nanmin(z70_ch, axis=0)
        else:  # "mean"
            z50 = np.nanmean(z50_ch, axis=0)
            z70 = np.nanmean(z70_ch, axis=0)

        if require_both:
            hits = (z50 >= z_thr) & (z70 >= z_thr)
        else:
            hits = (z50 >= z_thr) | (z70 >= z_thr)

        t_abs = t + (s0 / fs)

        hits_list.append(hits.astype(bool))
        t_list.append(t_abs)

    if not hits_list:
        return np.ones(n, dtype=bool)

    hits_all = np.concatenate(hits_list)
    t_all = np.concatenate(t_list)

    # -----------------------------
    # 3) Fill short gaps + enforce min duration on STFT bins
    # -----------------------------
    dt = float(np.median(np.diff(t_all))) if t_all.size > 1 else (hop / fs)
    keep = _fill_gaps_and_min_duration(hits_all, dt=dt, gap_sec=gap_sec, min_dur_sec=min_dur_sec)

    # -----------------------------
    # 4) Convert kept STFT bins -> sample-level mask (False where flagged)
    # -----------------------------
    mask = np.ones(n, dtype=bool)  # True = clean
    # Map each kept time bin to the corresponding analysis window in samples.
    # For SciPy stft, time bin i corresponds approximately to a window centered at i*hop.
    # We'll conservatively mark [i*hop, i*hop + nperseg) as False.
    for i, flagged in enumerate(keep):
        if not flagged:
            continue
        a = int(round(t_all[i] * fs))
        b = min(a + nperseg, n)
        mask[a:b] = False

    return mask