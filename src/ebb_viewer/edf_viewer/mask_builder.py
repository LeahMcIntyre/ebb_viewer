from openseize import producer as make_producer

from ebb import masking

from ebb_viewer.edf_viewer.recording import Recording
from ebb_viewer.edf_viewer.masks import Mask, MaskSet

# Wake: amber, NREM: steel-blue, REM: coral — fully opaque since the state bar
# is a dedicated strip (not overlaid on traces).
_STATE_COLORS = {
    "wake": (255, 200, 50,  255),
    "nrem": (70,  130, 200, 255),
    "rem":  (200, 70,  70,  255),
}
_STATE_LABELS = {
    "wake": ["w"],
    "nrem": ["n"],
    "rem":  ["r"],
}


def build_default_masks(rec: Recording) -> MaskSet:
    """Compute default artifact masks from a Recording using the same
    parameters as estimate_psd. Always computes commutator and SD masks.
    Adds spindle_noise mask if rec.csv_path is available.
    """
    chunksize = int(30e5)
    eeg_data = rec.data[:3]  # EEG channels only, not EMG
    pro = make_producer(eeg_data, chunksize=chunksize, axis=-1)

    comm_mask, _ = masking.commutator_threshold(
        pro, value=2000, radius=250, pad=250, min_to_pad=10
    )

    comm_pro = make_producer(comm_mask, chunksize=int(4.5e4), axis=-1)
    sd_mask = masking.sd_threshold(
        pro,
        nstds=[5],
        winsize=int(180 * rec.fs),
        radius=int(0.5 * rec.fs),
        mask_pro=comm_pro,
    )[0]

    mask_set = MaskSet()
    mask_set.add(Mask.from_bool("commutator", (255, 0, 0, 60), ~comm_mask))
    mask_set.add(Mask.from_bool("sd_5std",    (255, 100, 0, 60), ~sd_mask))

    if rec.csv_path is not None:
        spindle_mask = masking.spindle_noise(
            rec.csv_path, noise_thresh=0.5, fs=int(rec.fs), winsize=4, include=False
        )
        mask_set.add(Mask.from_bool("spindle_noise", (0, 200, 120, 60), ~spindle_mask))

    return mask_set




def load_state_masks(csv_path, fs: int) -> MaskSet:
    """Build a MaskSet of Wake / NREM / REM spans from a SleepyRat CSV."""
    import numpy as np
    mask_set = MaskSet()
    for name, labels in _STATE_LABELS.items():
        arr = masking.state(csv_path, labels, fs=fs, winsize=4, include=True)
        mask_set.add(Mask.from_bool(name, _STATE_COLORS[name], arr))
    return mask_set

def load_swd_mask(swd_path, fs:int, n_samples:int) -> Mask:
    arr = masking.swd(swd_path, fs=fs, n_samples=n_samples)
    return Mask.from_bool("swd", (178, 170, 248, 60), ~arr)