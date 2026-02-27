from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

import numpy as np


@dataclass
class Recording:
    data: np.ndarray
    fs: int
    start_time: datetime
    ch_names: Sequence[str]
    csv_path: Optional[Path] = None
