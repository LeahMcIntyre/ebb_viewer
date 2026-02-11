"""A script for computing EEG PSDs stored as MetaArrays with shape
(spindle_state x file x channels x frequencies).
"""

import copy
import re
import functools
import time
import dataclasses
from multiprocessing import Pool
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Sequence


import numpy as np
import numpy.typing as npt
import pandas as pd

from openseize import producer
from openseize.file_io import edf, path_utils
from openseize.spectra import estimators

from ebb.core import concurrency, metastores
from ebb import masking

@dataclasses.dataclass
class PSDResult:
    """PSD + minimal metadata needed for downstream exports."""
    path: Path
    channels: Tuple[int, ...]
    behavior: Tuple[str, ...]          # e.g. ("threshold", "wake")
    n_estimates: int
    spindle_out_frac: float
    comm_out_frac: float
    sd_out_frac: float
    swd_out_frac: float
    used_swd: bool
    used_drink: bool
    freqs: npt.NDArray[np.floating]
    psd: npt.NDArray[np.floating]

def out_fraction(mask: npt.NDArray[np.bool_], state_mask: npt.NDArray[np.bool_]) -> float:
    """Fraction of samples excluded by mask within a given state_mask."""
    kept = mask[state_mask]
    if kept.size == 0:
        return float("nan")
    return 1.0 - float(kept.mean())


def estimate_psd(
    path: Union[str, Path],
    state_path: Union[str, Path],
    swd_path: Union[str, Path] = None,
    drink_path: Union[str, Path] = None,
    offset_path: Union[str, Path] = None,
    channels: List = [0, 1, 2],
    nstd: int = 5,
    fs: float = 250,
    chunksize: int = int(30e5),
    labels: Dict = {'wake': ['w'], 'nrem': ['n'], 'rem': ['r']},
    verbose: bool = True,
    **kwargs,
) -> List[PSDResult]:
    """Estimates the Power spectral density of EEG data stored to an EDF at path
    for each state in a states path CSV file.

    Args:
        path:
            Path to an EDF file whose PSD will be estimated.
        state_path:
            Path to a Spindle generated CSV file of states.For the updated SleepyRat web service, artifact slider can be set as desired: 
            'rawstate' column is used. 
        drink_path:
            Path to a .npy file containing 1Hz 1D-Boolean array as a drink mask (drinking events
            are true).
        offset_path:
            Path to a .csv file containing the animal ID and the offset between the eeg start 
            and vidoe (drink mask) start. 
        channels:
            The channels for which PSDs will be estimated.
        fs:
            The sampling rate of the data in the EDF.
        labels:
            A dict of label names and spindle codes one per state for which PSDs
            will be computed.
        winsize:
            The size of the window for threshold artifact detection using the
            threshold mask. This value has units of seconds. Please see
            ebb.masking.threshold
        nstds:
            The number of standard deviations a deflection must cross to be
            considered an artifact. Please see ebb.masking.threshold
        radius:
            The number of secs below which two detected artifacts will be merged
            into a single artifact. Please see ebb.masking.threshold.
        verbose:
            Boolean indicating if information about which PSD is currently being
            computed should print to stdout.
        **kwargs:
            All kwargs are passed to openseize's psd estimator function.

    Returns:
        A list of PSDResult instances one per file and state in paths and
        labels.
    """

    path, state_path = Path(path), Path(state_path)
    # get the mouse id from path
    animal = path.stem.split('_')[0]
    print(animal)
    with edf.Reader(path) as reader:

        # build a producer
        reader.channels = list(channels)
        pro = producer(reader, chunksize=chunksize, axis=-1)

        # build state masks
        state_masks = {}
        for label, code in labels.items():
            state_masks[label] = (masking.state(state_path, code, fs, winsize=4))

        print(f"{animal}: {reader.shape}")
        #Compute commutator artifact threshold mask
        comm_mask = masking.commutator_threshold(pro, value=2000,
                radius=250,pad=250, min_to_pad=10)[0]
        
        spindle_mask = masking.spindle_noise(state_path, noise_thresh=0.5, fs=fs, winsize=4, include=False)

        comm_pro = producer(comm_mask, chunksize=4.5e4, axis=-1)
        sd_threshold_mask = masking.threshold(
            pro,
            [nstd],
            winsize=4.5e4,
            radius=125,
            mask_pro=comm_pro,
        )[0]
        print(f"{animal} SD threshold mask computed")

        #Compute SWD mask if path provided
        if swd_path is not None:
            swd_mask = masking.swd(path=swd_path, n_samples=pro.shape[-1], fs=fs, pad_sec=0)
        else:
            swd_mask = np.ones(pro.shape[-1], dtype=bool)
        
        
        #Get offset and drink mask
        #TODO: FIX THIS MESS LEAH
        if drink_path:
            print(f"Drink Mask For Animal {animal}")
            if offset_path:
                offset = masking.get_offset(drink_path, offset_path)
            drink_mask = masking.drinking_mask(drink_path, offset, fs=fs)
        else:
            drink_mask = np.ones(pro.shape[-1], dtype=bool)

        #Combine all artifact masks
        artifact_mask = comm_mask & spindle_mask & swd_mask & drink_mask


        metamask = metastores.MetaMask(threshold=artifact_mask, **state_masks)
        # compute psd estimates for each mask combination
        result = []
        for combo_state, mask in metamask.combinations():

            state_name = combo_state[1]

            if 'threshold' not in combo_state:
                # only compute psds for mask that include the threshold
                continue

            if not np.any(mask):
                # some mice may not exhibit all behavior states
                print(f'mask {combo_state} has no data ... skipping')
                continue
                
            if 'wake' in combo_state:
                # Only apply sd thresholding during wake
                mask &= sd_threshold_mask


            st_mask = state_masks[state_name]
            spindle_out = out_fraction(spindle_mask, st_mask)
            comm_out = out_fraction(comm_mask, st_mask)
            sd_out = out_fraction(sd_threshold_mask, st_mask)
            swd_out = out_fraction(swd_mask, st_mask)


            if verbose:
                print(f'Computing PSD for producer with mask: {combo_state}',
                      end='\n')
                
            masked_pro = producer(pro, chunksize, axis=-1, mask=mask)
            cnt, freqs, psds = estimators.psd(masked_pro, fs=fs, **kwargs)

            r = PSDResult(
                    path=path,
                    channels=channels,
                    behavior=combo_state,
                    n_estimates=int(cnt),
                    spindle_out_frac=float(spindle_out),
                    comm_out_frac=float(comm_out),
                    sd_out_frac=float(sd_out),
                    swd_out_frac=float(swd_out),
                    used_swd=bool(swd_path is not None),
                    used_drink=bool(drink_path is not None),
                    freqs=freqs,
                    psd=psds,
                )

            result.append(r)
    return result

import re
from pathlib import Path

def _animal_id(p: Path, pattern: str = r"[^_]+") -> str:
    """Join key used across EDF/CSV/MAT/NPY: everything before first underscore."""
    m = re.match(pattern, p.stem)
    return m.group(0) if m else p.stem



def match_paths(
    eeg_paths: Sequence[Path],
    state_paths: Sequence[Path],
    swd_paths: Optional[Sequence[Path]] = None,
    drink_paths: Optional[Sequence[Path]] = None,
    *,
    eeg_state_pat: str = r"[^_]+",
    eeg_swd_pat: str = r"^(?:[A-Za-z0-9]*ts_)?([^_]+)",
) -> List[Tuple[Path, Path, Optional[Path], Optional[Path]]]:
    """
    Match EEG EDFs to:
      - required state CSV
      - optional SWD MAT (if swd_paths provided, requires all EEGs to have SWD)
      - optional per-file drink NPY (may be missing)

    Returns list of tuples:
        (eeg_path, state_path, swd_path_or_None, drink_path_or_None)
    """

    eeg_paths = list(eeg_paths)

    # re_match is fine here because it's required to be complete
    eeg_state_pairs = path_utils.re_match(eeg_paths, state_paths, eeg_state_pat)
    state_by_eeg: Dict[Path, Path] = {ep: sp for ep, sp in eeg_state_pairs}

    # ---- OPTIONAL EEG <-> SWD (Applied to all or to none) ----
    if swd_paths is not None:
        eeg_swd_pairs = path_utils.re_match(eeg_paths, swd_paths, eeg_swd_pat)
        swd_by_eeg: Dict[Path, Path] = {ep: sp for ep, sp in eeg_swd_pairs}
    else:
        swd_by_eeg = {ep: None for ep in eeg_paths}

    # per-file sparse OK): drink masks via animal-id dict
    drink_by_animal: Dict[str, Path] = {}
    if drink_paths is not None:
        drink_by_animal = {_animal_id(p): p for p in drink_paths}

    # Build final paired list (no zip truncation) 
    paired: List[Tuple[Path, Path, Optional[Path], Optional[Path]]] = []
    for ep in eeg_paths:
        animal = _animal_id(ep)
        paired.append((
            ep,
            state_by_eeg[ep],
            swd_by_eeg[ep],
            drink_by_animal.get(animal, None),
        ))

    return paired

def batch_estimate(
    eeg_dir: Union[str, Path],
    state_dir: Union[str, Path],
    swd_dir: Union[str, Path] = None,
    drink_dir: Union[str, Path] = None,
    ncores: Optional[int] = None,
    verbose: bool = True,
    **kwargs,
) -> List[PSDResult]:
    """Concurrently estimates PSDResults from a directories of EEG files and
    Spindle state files.

    Args:
        eeg_dir:
            Directory to EEG files to estimate PSDs of.
        state_dir:
            Directory of spindle files one per EEG file in eeg_dir indicating
            sleep states.
        swd_dir:
            Optional directory of SWD .mat files one per EEG file in eeg_dir.
        mask_dir:
            Optional directory of .npy mask files one per EEG file in eeg_dir. Need to add more flexibility. 
        pattern:
            A regex string for pairing EEG files with Spindle state files.
        ncores:
            The number of processing cores to utilize to concurrently process
            EEG files.
        kwargs:
            Any valid kwarg for the estimate function.

    Returns:
        A list of lists of PSDResults, one PSD result for each file and state.
    """

    # remove any path arguments from kwargs
    [kwargs.pop(x, None) for x in ('path', 'state_path')]

    # pair the eeg paths with the state paths
    eeg_paths = sorted(Path(eeg_dir).glob('*PROCESSED.edf'))
    state_paths = sorted(Path(state_dir).glob('*.csv'))
    swd_paths = sorted(Path(swd_dir).glob("*.mat")) if swd_dir else None
    drink_paths = sorted(Path(drink_dir).glob("*.npy")) if drink_dir else None


    paired = match_paths(eeg_paths, state_paths, swd_paths, drink_paths)

    
    # set number of cpu workers and print to stdout
    workers = concurrency.set_cores(ncores, len(paired))
    msg = f'Executing Batch on {len(paired)} files using' f' {workers} cores.'
    print(msg)

    # construct a partial to pass to Multiprocess pool
    estimator = functools.partial(estimate_psd, **kwargs)
    t0 = time.perf_counter()
    with Pool(workers) as pool:
        results = pool.starmap(estimator, paired)
    elapsed = time.perf_counter() - t0
    print(f'Batch processed {len(paired)} files in {elapsed} secs')

    # flatten the list of list of PSDResult data instances
    return [obj for sublist in results for obj in sublist]


