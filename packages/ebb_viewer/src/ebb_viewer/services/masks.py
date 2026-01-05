from pathlib import Path
from typing import List, Union, Dict, Any

import numpy as np
from ebb.masking import state


def build_spindle_state_mask(
    csv_path: Union[str, Path],
    labels: List[str],
    *,
    fs: int = 250,
    winsize: int = 4,
    include: bool = True,
) -> Dict[str, Any]:
    mask = state(
        csv_path,
        labels,
        fs=fs,
        winsize=winsize,
        include=include,
    )

    mask = np.asarray(mask, dtype=bool)
    n = mask.size
    true_frac = float(mask.mean()) if n else 0.0
    false_frac = 1.0 - true_frac

    return {
        "path": str(csv_path),
        "n_samples": n,
        "true_frac": true_frac,
        "false_frac": false_frac,
        "mask": mask,  # keep for later plotting; you can drop this if you want
    }
