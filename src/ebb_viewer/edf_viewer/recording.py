from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence

import numpy as np


@dataclass
class Recording:
    data: np.ndarray
    fs: int
    start_time: datetime
    ch_names: Sequence[str]
    edf_path: Path
    csv_path: Optional[Path] = None
    swd_path: Optional[Path] = None
    drink_path: Optional[Path] = None
    video_offset: Optional[float] = None

    @property
    def recording_length(self):
        _, n_samples = self.data.shape
        return timedelta(seconds=n_samples / self.fs)
    
    def __str__(self):
        fields = [
            ("File",         self.edf_path),
            ("Fs",           f"{self.fs} Hz"),
            ("Start",        self.start_time),
            ("Duration",     self.recording_length),
            ("Channels",     ", ".join(self.ch_names)),
            ("State CSV",    self.csv_path or "—"),
            ("SWD",          self.swd_path or "—"),
            ("Drink",        self.drink_path or "—"),
            ("Video offset", self.video_offset if self.video_offset is not None else "—"),
        ]
        width = max(len(k) for k, _ in fields)
        return "\n".join(f"{k:<{width}}  {v}" for k, v in fields)