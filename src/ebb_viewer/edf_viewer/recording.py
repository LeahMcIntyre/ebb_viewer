from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np


@dataclass
class Recording:
    data: np.ndarray
    fs: int
    start_time: datetime
    ch_names: Sequence[str]
    edf_path: Path
    csv_path: Path | None = None
    swd_path: Path | None = None
    drink_path: Path | None = None
    video_offset: float | None = None

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
