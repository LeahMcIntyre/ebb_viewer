import inspect
import re

import numpy as np
from openseize import producer as make_producer

from ebb import masking
from ebb.masking.annotations import keyword_mask
from ebb_viewer.edf_viewer.recording import Recording
from ebb_viewer.edf_viewer.masks import Mask, MaskSet, ParamSpec


# TODO: Is this the best way to implement? Better to hard code?
def _param_desc(func, name: str) -> str | None:
    """Pull a parameter description from a Google-style Args: section."""
    doc = inspect.getdoc(func) or ""
    m = re.search(r"Args:\s*\n((?:[ \t]+\S.*\n?)+)", doc)
    if not m:
        return None
    pm = re.search(
        rf"^[ \t]+{re.escape(name)}:\s*(.*?)(?=\n[ \t]+\w+:|\Z)",
        m.group(1), re.DOTALL | re.MULTILINE,
    )
    return " ".join(pm.group(1).split()) if pm else None


def _comm_param_specs() -> dict:
    _ct = masking.commutator_threshold
    return {
        'value':      ParamSpec(min=0, units="µV",      desc=_param_desc(_ct, 'value')),
        'radius':     ParamSpec(min=0, units="samples",  desc=_param_desc(_ct, 'radius')),
        'pad':        ParamSpec(min=0, units="samples",  desc=_param_desc(_ct, 'pad')),
        'min_to_pad': ParamSpec(min=0, units="samples",  desc=_param_desc(_ct, 'min_to_pad')),
    }


def _sd_param_specs() -> dict:
    _sd = masking.sd_threshold
    return {
        'nstd':    ParamSpec(min=1, max=10, units="σ",  desc=_param_desc(_sd, 'nstds')),
        'winsize': ParamSpec(min=10,        units="s",  desc=_param_desc(_sd, 'winsize')),
        'radius':  ParamSpec(min=0.0, max=10.0, step=0.1, decimals=2, units="s",
                             desc=_param_desc(_sd, 'radius')),
    }


def _spindle_param_specs() -> dict:
    return {
        'noise_thresh': ParamSpec(min=0.0, max=1.0, step=0.1, decimals=2,
                                  desc=_param_desc(masking.spindle_noise, 'noise_thresh')),
    }


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
    eeg_data = rec.data[:3]
    baseline = np.median(eeg_data, axis=1, keepdims=True)  # shape (3, 1)
    eeg_centered = eeg_data - baseline
    pro = make_producer(eeg_centered, chunksize=chunksize, axis=-1)
    #pro = make_producer(eeg_data, chunksize=chunksize, axis=-1)

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

    c = Mask.from_bool("commutator", (255, 0, 0, 60), ~comm_mask)
    c.metadata.update({'value': 2000, 'radius': 250, 'pad': 250, 'min_to_pad': 10})
    c.param_specs.update(_comm_param_specs())

    sd = Mask.from_bool("sd", (255, 100, 0, 60), ~sd_mask)
    sd.metadata.update({"nstd": 5, "winsize": 180, "radius": 0.5, "comm_mask": True})
    sd.param_specs.update(_sd_param_specs())

    mask_set = MaskSet()
    mask_set.add(c)
    mask_set.add(sd)

    if rec.csv_path is not None:
        spindle_mask = masking.spindle_noise(
            rec.csv_path, noise_thresh=0.5, fs=int(rec.fs), winsize=4, include=False
        )
        sp = Mask.from_bool("spindle_noise", (0, 200, 120, 60), ~spindle_mask)
        sp.metadata.update({"noise_thresh": 0.5})
        sp.param_specs.update(_spindle_param_specs())
        mask_set.add(sp)

    return mask_set


def rebuild_artifact_masks(rec: Recording, comm_meta: dict, sd_meta: dict) -> tuple[Mask, Mask]:
    """Recompute commutator and sd masks from their current metadata dicts."""
    chunksize = int(30e5)
    eeg_data = rec.data[:3]
    baseline = np.median(eeg_data, axis=1, keepdims=True)  # shape (3, 1)
    eeg_centered = eeg_data - baseline
    pro = make_producer(eeg_centered, chunksize=chunksize, axis=-1)

    #pro = make_producer(rec.data[:3], chunksize=chunksize, axis=-1)

    comm_mask, _ = masking.commutator_threshold(
        pro,
        value=comm_meta['value'],
        radius=comm_meta['radius'],
        pad=comm_meta['pad'],
        min_to_pad=comm_meta['min_to_pad'],
    )

    mask_pro = None
    if sd_meta.get('comm_mask', True):
        mask_pro = make_producer(comm_mask, chunksize=int(4.5e4), axis=-1)

    sd_mask = masking.sd_threshold(
        pro,
        nstds=[sd_meta['nstd']],
        winsize=int(sd_meta['winsize'] * rec.fs),
        radius=int(sd_meta['radius'] * rec.fs),
        mask_pro=mask_pro,
    )[0]

    c = Mask.from_bool("commutator", (255, 0, 0, 60), ~comm_mask)
    c.metadata.update(comm_meta)
    c.param_specs.update(_comm_param_specs())

    sd = Mask.from_bool("sd", (255, 100, 0, 60), ~sd_mask)
    sd.metadata.update(sd_meta)
    sd.param_specs.update(_sd_param_specs())

    return c, sd


def rebuild_spindle_mask(csv_path, fs: int, meta: dict) -> Mask:
    """Recompute spindle_noise mask from its current metadata dict."""
    arr = masking.spindle_noise(
        csv_path, noise_thresh=meta['noise_thresh'], fs=fs, winsize=4, include=False
    )
    sp = Mask.from_bool("spindle_noise", (0, 200, 120, 60), ~arr)
    sp.metadata.update(meta)
    sp.param_specs.update(_spindle_param_specs())
    return sp


def rebuild_drink_mask(drink_path, fs: int, meta: dict) -> Mask:
    """Recompute drink mask from its current metadata dict."""
    arr = masking.drinking_mask(
        drink_path, fs=fs, offset_sec=meta['offset'], pad_sec=meta['pad_sec']
    )
    d = Mask.from_bool("drink", (0, 140, 255, 60), ~arr)
    d.metadata.update(meta)
    d.param_specs.update({'pad_sec': ParamSpec(min=0, units="s")})
    return d


def load_state_masks(csv_path, fs: int) -> MaskSet:
    """Build a MaskSet of Wake / NREM / REM spans from a SleepyRat CSV."""
    import numpy as np
    mask_set = MaskSet()
    for name, labels in _STATE_LABELS.items():
        arr = masking.state(csv_path, labels, fs=fs, winsize=4, include=True)
        mask_set.add(Mask.from_bool(name, _STATE_COLORS[name], arr))
    return mask_set

def _annotation_param_specs() -> dict:
    return {
        "keywords": ParamSpec(desc="Comma-separated substrings to match in annotation labels (case-insensitive)"),
        "pad_sec":  ParamSpec(min=0.0, max=3600.0, step=1.0, decimals=1, units="s",
                              desc="Seconds to mask after each matching annotation start"),
    }


def build_annotation_mask(annotation_path, keywords: list[str], pad_sec: float,
                           n_samples: int, fs: float) -> Mask:
    """Build an annotation keyword mask from a Pinnacle annotation file."""
    arr = keyword_mask(annotation_path, keywords=keywords, pad_sec=pad_sec,
                       size=n_samples, fs=fs)
    m = Mask.from_bool("annotation", (150, 0, 200, 60), ~arr)
    m.metadata.update({"keywords": ", ".join(keywords), "pad_sec": pad_sec})
    m.param_specs.update(_annotation_param_specs())
    return m


def rebuild_annotation_mask(annotation_path, n_samples: int, fs: float, meta: dict) -> Mask:
    """Recompute annotation mask from its current metadata dict."""
    keywords = [k.strip() for k in meta["keywords"].split(",") if k.strip()]
    arr = keyword_mask(annotation_path, keywords=keywords, pad_sec=meta["pad_sec"],
                       size=n_samples, fs=fs)
    m = Mask.from_bool("annotation", (150, 0, 200, 60), ~arr)
    m.metadata.update(meta)
    m.param_specs.update(_annotation_param_specs())
    return m


def load_swd_mask(swd_path, fs:int, n_samples:int) -> Mask:
    arr = masking.swd(swd_path, fs=fs, n_samples=n_samples)
    return Mask.from_bool("swd", (178, 170, 248, 60), ~arr)

def load_drink_mask(drink_path, fs:int, offset_sec:float, pad_sec:int) -> Mask:
    arr = masking.drinking_mask(drink_path, fs=fs, offset_sec=offset_sec, pad_sec=pad_sec)
    d = Mask.from_bool("drink", (0, 140, 255, 60), ~arr)
    d.metadata.update({"offset": offset_sec, "pad_sec": pad_sec})
    d.param_specs.update({
        'pad_sec': ParamSpec(min=0, units="s"),
    })
    return d
