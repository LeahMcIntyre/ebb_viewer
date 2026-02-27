from openseize import producer as make_producer

from ebb import masking

from ebb_viewer.edf_viewer.recording import Recording
from ebb_viewer.edf_viewer.masks import Mask, MaskSet



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