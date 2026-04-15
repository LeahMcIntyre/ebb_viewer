"""Runtime patches for third-party packages.

Applied at ``ebb`` import time. Patches are written to be safe no-ops on
platforms / versions that don't have the underlying bug, so they can stay on
unconditionally.
"""
from __future__ import annotations

import numpy as np
from openseize.file_io import edf as _oz_edf


def _patch_openseize_records_int32_overflow() -> None:
    """Fix int32 overflow in ``Reader._records`` for EDFs larger than ~2 GB.

    On Windows, ``numpy`` defaults integer arrays to ``int32``. openseize
    computes record offsets as ``a * bytes_per_record`` where ``a`` is a numpy
    scalar derived from ``np.array(samples_per_record)``. For multi-GB EDFs the
    product exceeds 2**31 and silently wraps, so ``np.fromfile(..., offset=...)``
    reads garbage (or nothing) and the caller writes an empty/corrupt file.

    Casting ``a`` and ``bytes_per_record`` to Python ``int`` (arbitrary
    precision) before the multiply avoids the overflow. On Linux/macOS numpy
    defaults to int64 and this cast is a behavioral no-op.

    Upstream: https://github.com/mscaudill/openseize (as of 1.3.0).
    """
    if getattr(_oz_edf.Reader, "_ebb_int32_patch_applied", False):
        return

    def _records(self, a: int, b: int):
        if a >= self.header.num_records:
            return np.empty((1, 0))
        b = min(b, self.header.num_records)
        cnt = b - a

        self._fobj.seek(0)
        bytes_per_record = int(sum(self.header.samples_per_record)) * 2
        # int() casts prevent int32 overflow on Windows for files > ~2 GB.
        offset = int(self.header.header_bytes) + int(a) * bytes_per_record
        nsamples = int(cnt) * int(sum(self.header.samples_per_record))
        recs = np.fromfile(self._fobj, "<i2", nsamples, offset=offset)
        arr = recs.reshape(cnt, sum(self.header.samples_per_record))
        return arr

    _oz_edf.Reader._records = _records
    _oz_edf.Reader._ebb_int32_patch_applied = True


def apply_all() -> None:
    _patch_openseize_records_int32_overflow()
