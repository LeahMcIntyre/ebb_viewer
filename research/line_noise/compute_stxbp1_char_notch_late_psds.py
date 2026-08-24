"""Compute notch-filtered PSDs for the Stxbp1 characterization set, with the
notch applied late (after artifact-detection masks, not before).

Same reference run parameters as compute_stxbp1_char_notch_psds.py (see that
script's docstring for the full rationale -- same paths, same masks, drink
masking still left off), but uses psd_compute_notch.batch_estimate_late_notch
instead of batch_estimate. That means:

- comm_mask and sd_threshold_mask (masking.commutator_threshold /
  masking.sd_threshold) are computed from the *raw* signal.
- The notch filter is applied to the continuous producer only after those
  masks are built, right before the per-state PSD loop -- so only the
  values that actually go into estimators.psd are filtered.

See estimate_psd_late_notch's docstring in psd_compute_notch.py for why this
still filters the continuous producer rather than the masked one (filtering
a masked producer would filter across artificial discontinuities, since
openseize's masked producer skips False samples rather than zeroing them).

Output goes to a separate directory (jerk_jump_swd_notch_57_63_late/) so it
doesn't overwrite the early-notch run in jerk_jump_swd_notch_57_63/.

Run with the ebb-dev environment's python. Takes ~4 minutes for 24 animals.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import psd_compute_notch

PROJECT_ROOT = Path("/Users/leahmcintyre/Data/nri/Stxbp1_characterization")
EEG_DIR = PROJECT_ROOT / "standard"
STATE_DIR = PROJECT_ROOT / "spindle_outputs" / "LFC_RSC"
SWD_DIR = PROJECT_ROOT / "swd"
ANN_DIR = PROJECT_ROOT / "annotations"

NOTCH_HALFWIDTH_HZ = 3  # 60 +/- 3 = 57-63 Hz
NOTCH_ORDER = 8

OUT_DIR = (
    PROJECT_ROOT / "psd" / f"jerk_jump_swd_notch_{60 - NOTCH_HALFWIDTH_HZ}_{60 + NOTCH_HALFWIDTH_HZ}_late"
)
OUT_PKL = OUT_DIR / "psds_LFC_RSC.pkl"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = psd_compute_notch.batch_estimate_late_notch(
        eeg_dir=EEG_DIR,
        state_dir=STATE_DIR,
        swd_dir=SWD_DIR,
        drink_dir=None,
        ncores=15,
        fs=250,
        nstd=5,
        winsize=180,
        radius=0.5,
        noise_thresh=0.5,
        comm_value=2000,
        swd_pad=0,
        notch_halfwidth_hz=NOTCH_HALFWIDTH_HZ,
        notch_order=NOTCH_ORDER,
        ann_params={
            "ann_dir": str(ANN_DIR),
            "keywords": ["jerk", "jump"],
            "match_mode": "contains",
            "pad_before_sec": 0.0,
            "pad_after_sec": 2.0,
        },
        verbose=True,
        savepath=OUT_PKL,
    )
    print(f"Computed {len(results)} PSD results")
    print(f"Saved to {OUT_PKL}")


if __name__ == "__main__":
    main()
