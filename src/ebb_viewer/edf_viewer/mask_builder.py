"""Factory functions that translate UI metadata dicts into ebb.masking calls.

Defaults intentionally mirror those in `estimate_psd` so the viewer shows what
the PSD pipeline actually computes; they are duplicated here rather than
imported to keep `ebb_viewer` independent of `ebb.process` orchestration.
"""

import inspect
import re

import numpy as np
from openseize import producer as make_producer

from ebb import masking
from ebb.masking.annotations import keyword_mask
from ebb.io.spindle_csv import FINAL_COLUMN, STATE_COLUMNS, read_state_column
from ebb_viewer.edf_viewer.masks import Mask, MaskSet, ParamSpec
from ebb_viewer.edf_viewer.recording import Recording


def _param_desc(func, name: str) -> str | None:
    """Pull a parameter description from a Google-style ``Args:`` block.

    Returns None if the docstring lacks an Args block or the parameter isn't
    found. Callers handle None gracefully (no tooltip is set), so this only
    breaks if upstream functions switch to a different docstring style.
    """
    doc = inspect.getdoc(func) or ""
    m = re.search(r"Args:\s*\n((?:[ \t]+\S.*\n?)+)", doc)
    if not m:
        return None
    pm = re.search(
        rf"^[ \t]+{re.escape(name)}:\s*(.*?)(?=\n[ \t]+\w+:|\Z)",
        m.group(1),
        re.DOTALL | re.MULTILINE,
    )
    return " ".join(pm.group(1).split()) if pm else None


def _comm_param_specs() -> dict:
    _ct = masking.commutator_threshold
    return {
        "value": ParamSpec(min=0, units="µV", desc=_param_desc(_ct, "value")),
        "radius": ParamSpec(min=0, units="samples", desc=_param_desc(_ct, "radius")),
        "pad": ParamSpec(min=0, units="samples", desc=_param_desc(_ct, "pad")),
        "min_to_pad": ParamSpec(min=0, units="samples", desc=_param_desc(_ct, "min_to_pad")),
    }


def _sd_param_specs() -> dict:
    _sd = masking.sd_threshold
    return {
        "nstd": ParamSpec(min=1, max=10, units="σ", desc=_param_desc(_sd, "nstds")),
        "winsize": ParamSpec(min=10, units="s", desc=_param_desc(_sd, "winsize")),
        "radius": ParamSpec(
            min=0.0, max=10.0, step=0.1, decimals=2, units="s", desc=_param_desc(_sd, "radius")
        ),
    }


def _spindle_param_specs() -> dict:
    return {
        "noise_thresh": ParamSpec(
            min=0.0,
            max=1.0,
            step=0.1,
            decimals=2,
            desc=_param_desc(masking.spindle_noise, "noise_thresh"),
        ),
    }


# Wake: amber, NREM: steel-blue, REM: coral — fully opaque since the state bar
# is a dedicated strip (not overlaid on traces).
_STATE_COLORS = {
    "wake": (255, 200, 50, 255),
    "nrem": (70, 130, 200, 255),
    "rem": (200, 70, 70, 255),
}
_EPOCH_SEC = 4  # SPINDLE epoch length
_STATE_LABELS = {
    "wake": ["w"],
    "nrem": ["n"],
    "rem": ["r"],
}


_DEFAULT_COMM_META = {"value": 2000, "radius": 250, "pad": 250, "min_to_pad": 10}
_DEFAULT_SD_META = {"nstd": 5, "winsize": 180, "radius": 0.5, "comm_mask": True}


def _compute_artifact_masks(
    rec: Recording, comm_meta: dict, sd_meta: dict
) -> tuple[np.ndarray, np.ndarray]:
    """Run commutator + SD-threshold on `rec`, returning both raw boolean arrays.

    Centers each channel on its median before producer construction so the
    SD-threshold's per-window stats aren't biased by DC offsets. SD's
    commutator-mask gating is controlled by `sd_meta["comm_mask"]` (default True).
    """
    chunksize = int(30e5)
    eeg_data = rec.data[:3]
    baseline = np.median(eeg_data, axis=1, keepdims=True)  # shape (3, 1)
    pro = make_producer(eeg_data - baseline, chunksize=chunksize, axis=-1)

    comm_mask, _ = masking.commutator_threshold(
        pro,
        value=comm_meta["value"],
        radius=comm_meta["radius"],
        pad=comm_meta["pad"],
        min_to_pad=comm_meta["min_to_pad"],
    )

    mask_pro = (
        make_producer(comm_mask, chunksize=int(4.5e4), axis=-1)
        if sd_meta.get("comm_mask", True)
        else None
    )
    sd_mask = masking.sd_threshold(
        pro,
        nstds=[sd_meta["nstd"]],
        winsize=int(sd_meta["winsize"] * rec.fs),
        radius=int(sd_meta["radius"] * rec.fs),
        mask_pro=mask_pro,
    )[0]
    return comm_mask, sd_mask


def _wrap_artifact_masks(
    comm_mask: np.ndarray, sd_mask: np.ndarray, comm_meta: dict, sd_meta: dict
) -> tuple[Mask, Mask]:
    """Wrap raw boolean arrays as viewer-side Mask objects with metadata + specs."""
    c = Mask.from_bool("commutator", (255, 0, 0, 80), ~comm_mask)
    c.metadata.update(comm_meta)
    c.param_specs.update(_comm_param_specs())

    sd = Mask.from_bool("sd", (255, 100, 0, 80), ~sd_mask)
    sd.metadata.update(sd_meta)
    sd.param_specs.update(_sd_param_specs())
    return c, sd


def build_default_masks(rec: Recording) -> MaskSet:
    """Compute default artifact masks from a Recording using the same
    parameters as estimate_psd. Always computes commutator and SD masks.
    Adds spindle_noise mask if rec.csv_path is available.
    """
    comm_meta = dict(_DEFAULT_COMM_META)
    sd_meta = dict(_DEFAULT_SD_META)
    comm_mask, sd_mask = _compute_artifact_masks(rec, comm_meta, sd_meta)
    c, sd = _wrap_artifact_masks(comm_mask, sd_mask, comm_meta, sd_meta)

    mask_set = MaskSet()
    mask_set.add(c)
    mask_set.add(sd)

    if rec.csv_path is not None:
        spindle_mask = masking.spindle_noise(
            rec.csv_path, noise_thresh=0.5, fs=int(rec.fs), winsize=4, include=False
        )
        sp = Mask.from_bool("spindle_noise", (0, 200, 120, 80), ~spindle_mask)
        sp.metadata.update({"noise_thresh": 0.5})
        sp.param_specs.update(_spindle_param_specs())
        mask_set.add(sp)

    return mask_set


def rebuild_artifact_masks(rec: Recording, comm_meta: dict, sd_meta: dict) -> tuple[Mask, Mask]:
    """Recompute commutator and sd masks from their current metadata dicts."""
    comm_mask, sd_mask = _compute_artifact_masks(rec, comm_meta, sd_meta)
    return _wrap_artifact_masks(comm_mask, sd_mask, comm_meta, sd_meta)


def rebuild_spindle_mask(csv_path, fs: int, meta: dict) -> Mask:
    """Recompute spindle_noise mask from its current metadata dict."""
    arr = masking.spindle_noise(
        csv_path, noise_thresh=meta["noise_thresh"], fs=fs, winsize=4, include=False
    )
    sp = Mask.from_bool("spindle_noise", (0, 200, 120, 80), ~arr)
    sp.metadata.update(meta)
    sp.param_specs.update(_spindle_param_specs())
    return sp


def rebuild_drink_mask(drink_path, fs: int, meta: dict) -> Mask:
    """Recompute drink mask from its current metadata dict."""
    arr = masking.drinking_mask(
        drink_path, fs=fs, offset_sec=meta["offset"], pad_sec=meta["pad_sec"]
    )
    d = Mask.from_bool("drink", (0, 140, 255, 80), ~arr)
    d.metadata.update(meta)
    d.param_specs.update({"pad_sec": ParamSpec(min=0, units="s")})
    return d


def load_state_masks(csv_path, fs: int) -> MaskSet:
    """Build a MaskSet of Wake / NREM / REM spans from a SleepyRat CSV (original states)."""
    mask_set = MaskSet()
    for name, labels in _STATE_LABELS.items():
        arr = masking.state(csv_path, labels, fs=fs, winsize=4, include=True, columns=STATE_COLUMNS)
        mask_set.add(Mask.from_bool(name, _STATE_COLORS[name], arr))
    return mask_set


def load_reclassified_state_masks(csv_path, fs: int) -> MaskSet:
    """Like `load_state_masks`, from the CSV's ``final_state`` column.

    ``final_state`` is written by the Reclassify step (NREM gap fill + EMG gate,
    plus any SWD overrides). Its per-epoch labels are expanded to sample
    resolution.

    Raises:
        ValueError: if the CSV has no ``final_state`` column.
    """
    final_state = np.array(read_state_column(csv_path, FINAL_COLUMN))
    samples_per_epoch = fs * _EPOCH_SEC
    mask_set = MaskSet()
    for name, labels in _STATE_LABELS.items():
        arr = np.repeat(np.isin(final_state, labels), samples_per_epoch)
        mask_set.add(Mask.from_bool(name, _STATE_COLORS[name], arr))
    return mask_set


def _annotation_param_specs() -> dict:
    return {
        "keywords": ParamSpec(desc="Comma-separated labels to match (case-insensitive)"),
        "match_mode": ParamSpec(desc="'contains' — substring match; 'exact' — full label match"),
        "pad_before_sec": ParamSpec(
            min=0.0,
            max=3600.0,
            step=1.0,
            decimals=1,
            units="s",
            desc="Seconds to mask before each matching annotation",
        ),
        "pad_after_sec": ParamSpec(
            min=0.0,
            max=3600.0,
            step=1.0,
            decimals=1,
            units="s",
            desc="Seconds to mask after each matching annotation",
        ),
    }


def build_annotation_mask(
    annotation_path,
    keywords: list[str],
    pad_before_sec: float,
    pad_after_sec: float,
    match_mode: str,
    n_samples: int,
    fs: float,
) -> Mask:
    """Build an annotation keyword mask from a Pinnacle annotation file."""
    arr = keyword_mask(
        annotation_path,
        keywords=keywords,
        pad_before_sec=pad_before_sec,
        pad_after_sec=pad_after_sec,
        match_mode=match_mode,
        size=n_samples,
        fs=fs,
    )
    m = Mask.from_bool("annotation", (150, 0, 200, 80), ~arr)
    m.metadata.update(
        {
            "keywords": ", ".join(keywords),
            "match_mode": match_mode,
            "pad_before_sec": pad_before_sec,
            "pad_after_sec": pad_after_sec,
        }
    )
    m.param_specs.update(_annotation_param_specs())
    return m


def rebuild_annotation_mask(annotation_path, n_samples: int, fs: float, meta: dict) -> Mask:
    """Recompute annotation mask from its current metadata dict."""
    keywords = [k.strip() for k in meta["keywords"].split(",") if k.strip()]
    arr = keyword_mask(
        annotation_path,
        keywords=keywords,
        pad_before_sec=meta.get("pad_before_sec", 0.0),
        pad_after_sec=meta.get("pad_after_sec", 0.0),
        match_mode=meta.get("match_mode", "contains"),
        size=n_samples,
        fs=fs,
    )
    m = Mask.from_bool("annotation", (150, 0, 200, 80), ~arr)
    m.metadata.update(meta)
    m.param_specs.update(_annotation_param_specs())
    return m


def load_swd_mask(swd_path, fs: int, n_samples: int) -> Mask:
    arr = masking.swd(swd_path, fs=fs, n_samples=n_samples)
    return Mask.from_bool("swd", (178, 170, 248, 80), ~arr)


def load_drink_mask(drink_path, fs: int, offset_sec: float, pad_sec: int) -> Mask:
    arr = masking.drinking_mask(drink_path, fs=fs, offset_sec=offset_sec, pad_sec=pad_sec)
    d = Mask.from_bool("drink", (0, 140, 255, 80), ~arr)
    d.metadata.update({"offset": offset_sec, "pad_sec": pad_sec})
    d.param_specs.update(
        {
            "pad_sec": ParamSpec(min=0, units="s"),
        }
    )
    return d
