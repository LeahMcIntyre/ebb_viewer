"""Compute notch-filtered PSDs for the Stxbp1 characterization set.

Reproduces the run parameters saved in
/Users/leahmcintyre/Data/nri/Stxbp1_characterization/psd/jerk_jump_swd/psd_params.json
(the established, non-notch pipeline run for this project) against the
`standard/` EDFs, except:

- bidirectional notch filtering (60 Hz +/- NOTCH_HALFWIDTH_HZ, order
  NOTCH_ORDER) is applied via psd_compute_notch.batch_estimate before
  masking/PSD estimation, instead of the unfiltered ebb.process.psd_compute
  pipeline.
- drink masking is left off (drink_dir=None), unlike the reference run
  (use_drink_mask: true in psd_params.json).

Only the LFC_RSC channel combo is processed: per manifest.json, all 24
animals have sleep_qc == "ok" on LFC_RSC, so the other combo folders under
spindle_outputs/ (LFC_LSC, LSC, RSC, RSC_LSC) are stale single-animal
reruns, not part of the authoritative dataset.

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

OUT_DIR = PROJECT_ROOT / "psd" / f"jerk_jump_swd_notch_{60 - NOTCH_HALFWIDTH_HZ}_{60 + NOTCH_HALFWIDTH_HZ}"
OUT_PKL = OUT_DIR / "psds_LFC_RSC.pkl"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = psd_compute_notch.batch_estimate(
        eeg_dir=EEG_DIR,
        state_dir=STATE_DIR,
        swd_dir=SWD_DIR,
        drink_dir=None,
        ncores=6,
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
