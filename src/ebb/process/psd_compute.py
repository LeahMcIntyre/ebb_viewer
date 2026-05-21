"""Per-animal PSD computation and batch orchestration.

Two layers:
- `estimate_psd`: single-file PSD. Builds state masks (one per group in
  `labels`), artifact masks (commutator threshold, SD threshold within
  wake, SPINDLE noise, SWD events, drink events, annotation keywords,
  time-of-day windows), combines them, and emits one `PSDResult` per
  (state-group ∩ all-artifacts).
- `batch_estimate` / `rerun_with_drink_masks`: multiprocess drivers that
  pair EEG files with their state/SWD/drink/annotation companions and
  fan `estimate_psd` calls out to a process pool. The two functions
  share the same kwarg-prep logic via `_prepare_estimator_kwargs`.

Output is a list of `PSDResult` dataclasses; `batch_estimate` optionally
pickles a list of dicts for downstream merging by `build_final_pkl`.
"""

import dataclasses
import multiprocessing
import pickle
import time
import warnings
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

import numpy as np
import numpy.typing as npt
from openseize import producer
from openseize.file_io import edf, path_utils
from openseize.spectra import estimators

from ebb import masking
from ebb.core import concurrency, metastores
from ebb.core.naming import parse_animal_id
from ebb.io.edf_header import assert_fs_matches, parse_edf_start_datetime
from ebb.masking.annotations import keyword_mask
from ebb.process.state_presets import labels_from_presets

# Commutator-artifact threshold tunings used by `estimate_psd`. Values were
# calibrated for the project's EDF acquisition; centralizing them here makes
# them easier to find and adjust than burying inside the function call.
_COMMUTATOR_VALUE_UV = 2000  # absolute amplitude limit (μV) for commutator
_COMMUTATOR_RADIUS_SAMPLES = 250  # 1 s @ 250 Hz: merge events closer than this
_COMMUTATOR_PAD_SAMPLES = 250  # 1 s @ 250 Hz: extend each event by this much
_COMMUTATOR_MIN_TO_PAD = 10  # only events longer than this get the pad
_COMMUTATOR_MASK_CHUNKSIZE = 45_000  # chunksize for streaming the comm mask

# UI-only kwargs that may arrive from saved psd_params.json but must be
# stripped before forwarding to `estimate_psd`.
_UI_ONLY_KWARGS = (
    "path",
    "state_path",
    "swd_mode",
    "use_swd_mask",  # widget-emitted boolean shadow of swd_mode (export-side key)
    "swd_pad",  # used by export pipeline only; estimate_psd has no SWD pad
    "use_drink_mask",  # widget-emitted; estimate_psd uses drink_path presence instead
    "drink_offset_csv_override",  # used by export pipeline only
    "ann_enabled",
    "ann_dir",  # estimate_psd takes annotation_path per-animal; not a kwarg
    "ann_keywords",  # estimate_psd uses ann_keywords directly — see below
    "ann_match_mode",  # but the widget emits a different key shape — re-keyed by
    "ann_pad_before",  # the page before forwarding via ann_params, so strip here.
    "ann_pad_after",
    "time_filter_enabled",
    "tod_start",
    "tod_end",
    "time_filter_days",  # legacy
    "hw_enabled",
)


@dataclasses.dataclass
class PSDResult:
    """PSD + minimal metadata needed for downstream exports."""

    path: Path
    channels: tuple[int, ...]
    behavior: tuple[str, ...]  # e.g. ("threshold", "wake")
    n_estimates: int
    spindle_out_frac: float
    comm_out_frac: float
    sd_out_frac: float
    swd_out_frac: float
    ann_out_frac: float
    used_swd: bool
    used_drink: bool
    used_ann: bool
    freqs: npt.NDArray[np.floating]
    psd: npt.NDArray[np.floating]
    used_windows: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    # Each tuple: (window_start_isoformat, window_end_isoformat)


def out_fraction(mask: npt.NDArray[np.bool_], state_mask: npt.NDArray[np.bool_]) -> float:
    """Fraction of samples excluded by mask within a given state_mask."""
    kept = mask[state_mask]
    if kept.size == 0:
        return float("nan")
    return 1.0 - float(kept.mean())


def estimate_psd(
    path: str | Path,
    state_path: str | Path,
    swd_path: str | Path | None = None,
    drink_path: str | Path | None = None,
    annotation_path: str | Path | None = None,
    offset_path: str | Path | None = None,
    channels: Sequence[int] | None = None,
    winsize: int = 180,
    radius: float = 0.5,
    nstd: int = 5,
    fs: float = 250,
    chunksize: int = int(30e5),
    labels: dict[str, Sequence[str]] | None = None,
    verbose: bool = True,
    noise_thresh: float = 0.5,
    comm_value: int = _COMMUTATOR_VALUE_UV,
    drink_pad: int = 2,
    s_prob: float | None = None,
    ann_keywords: list[str] | None = None,
    ann_match_mode: str = "contains",
    ann_pad_before_sec: float = 0.0,
    ann_pad_after_sec: float = 0.0,
    hour_windows: list[tuple[float, float]] | None = None,
    selected_days: list[int] | None = None,
    **kwargs,
) -> list[PSDResult]:
    """Estimate PSDs for one EDF, one PSDResult per (state-group ∩ artifacts).

    For each label group in `labels`, builds a state mask (which samples
    belong to that group), intersects it with the combined artifact mask
    (commutator + SD-within-wake + SPINDLE noise + SWD + drink + annotation
    + time-of-day), and estimates a PSD on the surviving samples.

    Args:
        path:
            EDF whose PSD will be estimated.
        state_path:
            SPINDLE-scored CSV file. The `rawstate` column drives state
            masks; `noise_probs` drives the SPINDLE noise mask.
        swd_path:
            Optional `.mat` file of SWD timestamps to mask out.
        drink_path:
            Optional `.npy` 1 Hz boolean array of drinking events (True =
            drinking event).
        annotation_path:
            Optional Pinnacle annotation file. Combined with `ann_keywords`
            to mask out events whose label matches.
        offset_path:
            Optional CSV with `Animal,Offset` columns; the offset (seconds)
            shifts the drink mask to align with the EEG.
        channels:
            EEG channel indices to use. Defaults to `[0, 1, 2]` if None.
        winsize:
            Window length in seconds for SD-threshold artifact detection.
            See `ebb.masking.threshold.sd_threshold`.
        radius:
            Seconds below which two detected SD-threshold artifacts are
            merged into one. See `ebb.masking.threshold.sd_threshold`.
        nstd:
            Number of standard deviations a sample must exceed to be
            flagged as an SD artifact.
        fs:
            EDF sampling rate (Hz).
        chunksize:
            Samples per producer chunk during streaming.
        labels:
            Group name → list of SPINDLE rawstate codes. Defaults to
            `{"wake": ["w"], "nrem": ["n"], "rem": ["r"]}` if None. Groups
            containing `"w"` plus other states get SD thresholding applied
            only to their wake-sub samples.
        verbose:
            Print per-PSD progress lines.
        noise_thresh:
            SPINDLE noise probability threshold (>= → epoch is noise).
        drink_pad:
            Pad each drink event by this many seconds on each side. (The
            unit is seconds despite the unsuffixed name; preserved for
            backwards compatibility.)
        s_prob:
            If set, restricts state masks to epochs whose class probability
            >= `s_prob` (uses `masking.state_prob` instead of `masking.state`).
        ann_keywords, ann_match_mode, ann_pad_before_sec, ann_pad_after_sec:
            Annotation-mask params (see `ebb.masking.annotations.keyword_mask`).
        hour_windows:
            Optional list of `(hour_start, hour_end)` decimal-hour pairs;
            the mask keeps samples within any window. Each window may wrap
            midnight (`hour_end < hour_start`).
        selected_days:
            0-based calendar-day indices to keep, applied to `hour_windows`.
        **kwargs:
            Forwarded to openseize's `estimators.psd`.

    Returns:
        One `PSDResult` per state group with at least one surviving sample.
        Groups with no surviving samples are silently skipped.
    """

    path, state_path = Path(path), Path(state_path)
    channels = list(channels) if channels is not None else [0, 1, 2]
    if labels is None:
        labels = {"wake": ["w"], "nrem": ["n"], "rem": ["r"]}
    animal = parse_animal_id(path)
    if verbose:
        print(animal)
    with edf.Reader(path) as reader:
        assert_fs_matches(reader, fs, path=path)
        # build a producer
        reader.channels = list(channels)
        pro = producer(reader, chunksize=chunksize, axis=-1)

        # build state masks
        state_masks = {}

        if s_prob is not None:
            for label, code in labels.items():
                state_masks[label] = masking.state_prob(
                    state_path, code[0], fs, winsize=4, sprob=s_prob
                )
        else:
            for label, code in labels.items():
                state_masks[label] = masking.state(state_path, code, fs, winsize=4)

        # Wake sub-mask for mixed groups that lump wake with sleep states.
        # SD thresholding should only gate the wake portion of such groups,
        # since SD calibrates to wake amplitudes and would over-mask quieter
        # NREM/REM samples if applied uniformly.
        needs_wake_sub = any("w" in codes and len(codes) > 1 for codes in labels.values())
        if needs_wake_sub:
            if s_prob is not None:
                wake_sub_mask = masking.state_prob(state_path, "w", fs, winsize=4, sprob=s_prob)
            else:
                wake_sub_mask = masking.state(state_path, ["w"], fs, winsize=4)
        else:
            wake_sub_mask = None

        # Compute commutator artifact threshold mask. ``value`` (µV) is
        # surfaced as a user-editable param; radius / pad / min_to_pad
        # remain hardcoded — see TODO "psd_compute: Commutator mask
        # params should scale with user-set fs" for the fs-coupling
        # cleanup needed before exposing them.
        comm_mask = masking.commutator_threshold(
            pro,
            value=comm_value,
            radius=_COMMUTATOR_RADIUS_SAMPLES,
            pad=_COMMUTATOR_PAD_SAMPLES,
            min_to_pad=_COMMUTATOR_MIN_TO_PAD,
        )[0]

        spindle_mask = masking.spindle_noise(
            state_path, noise_thresh=noise_thresh, fs=fs, winsize=4, include=False
        )

        wsize, rad = (winsize * fs), (radius * fs)

        comm_pro = producer(comm_mask, chunksize=_COMMUTATOR_MASK_CHUNKSIZE, axis=-1)
        sd_threshold_mask = masking.sd_threshold(
            pro,
            [nstd],
            winsize=wsize,
            radius=rad,
            mask_pro=comm_pro,
        )[0]
        if verbose:
            print(f"{animal} SD threshold mask computed")

        # Compute SWD mask if path provided
        if swd_path is not None:
            swd_mask = masking.swd(path=swd_path, n_samples=pro.shape[-1], fs=fs, pad_sec=0)
        else:
            swd_mask = np.ones(pro.shape[-1], dtype=bool)

        # Get offset and drink mask
        if drink_path:
            if verbose:
                print(f"Drink Mask For Animal {animal}")
            offset = (
                masking.get_offset(drink_path, offset_path) if offset_path is not None else None
            )
            drink_mask = masking.drinking_mask(
                drink_path, offset, fs=fs, pad_sec=drink_pad, n_samples=pro.shape[-1]
            )
        else:
            drink_mask = np.ones(pro.shape[-1], dtype=bool)

        # Build annotation mask if a path and keywords were provided
        n_samples = pro.shape[-1]
        _ann_keywords = ann_keywords or []
        if annotation_path is not None and _ann_keywords:
            ann_mask = keyword_mask(
                annotation_path,
                keywords=_ann_keywords,
                size=n_samples,
                fs=fs,
                pad_before_sec=ann_pad_before_sec,
                pad_after_sec=ann_pad_after_sec,
                match_mode=ann_match_mode,
            )
        else:
            ann_mask = np.ones(n_samples, dtype=bool)

        # Build hour-window mask if requested
        if hour_windows is not None:
            rec_start = parse_edf_start_datetime(reader.header)
            tod_mask, used_windows = masking.hour_window_mask(
                rec_start,
                n_samples,
                fs,
                hour_windows,
                selected_days,
            )
            if verbose:
                for ws, we in used_windows:
                    print(f"  {animal}: {ws.strftime('%Y-%m-%d %H:%M')}–{we.strftime('%H:%M')}")
        else:
            tod_mask = np.ones(n_samples, dtype=bool)
            used_windows = []

        # Combine all artifact masks
        artifact_mask = comm_mask & spindle_mask & swd_mask & drink_mask & ann_mask & tod_mask

        metamask = metastores.MetaMask(threshold=artifact_mask, **state_masks)
        # compute psd estimates for each mask combination
        result = []
        for combo_state, mask in metamask.combinations():
            state_name = combo_state[1]
            st_mask = state_masks[state_name]

            if "threshold" not in combo_state:
                # only compute psds for mask that include the threshold
                continue

            if not np.any(mask):
                # some mice may not exhibit all behavior states
                if verbose:
                    print(f"mask {combo_state} has no data ... skipping")
                continue

            codes = labels[state_name]
            if "w" in codes:
                if len(codes) == 1:
                    mask &= sd_threshold_mask
                    sd_out = out_fraction(sd_threshold_mask, st_mask)
                else:
                    # Mixed group (wake + non-wake): apply SD threshold only to
                    # the wake portion. `~wake_sub_mask | sd_threshold_mask`
                    # passes every non-wake sample (so NREM/REM unaffected) and
                    # passes wake samples only if they survive the SD threshold.
                    # All three operands have length pro.shape[-1] by
                    # construction, so the broadcast is unambiguous.
                    mask &= ~wake_sub_mask | sd_threshold_mask
                    sd_out = out_fraction(sd_threshold_mask, st_mask & wake_sub_mask)
            else:
                sd_out = 0.0

            spindle_out = out_fraction(spindle_mask, st_mask)
            comm_out = out_fraction(comm_mask, st_mask)
            swd_out = out_fraction(swd_mask, st_mask)
            ann_out = out_fraction(ann_mask, st_mask)

            if verbose:
                print(f"Computing PSD for producer with mask: {combo_state}")

            masked_pro = producer(pro, chunksize, axis=-1, mask=mask)
            cnt, freqs, psds = estimators.psd(masked_pro, fs=fs, **kwargs)

            # `used_*` flags record whether each source was *configured*, not
            # whether it actually masked any samples. To know the latter,
            # check the corresponding `*_out_frac` field (0.0 = no samples
            # excluded by that source within this state).
            r = PSDResult(
                path=path,
                channels=channels,
                behavior=combo_state,
                n_estimates=int(cnt),
                spindle_out_frac=float(spindle_out),
                comm_out_frac=float(comm_out),
                sd_out_frac=float(sd_out),
                swd_out_frac=float(swd_out),
                ann_out_frac=float(ann_out),
                used_swd=swd_path is not None,
                used_drink=drink_path is not None,
                used_ann=bool(annotation_path is not None and _ann_keywords),
                freqs=freqs,
                psd=psds,
                used_windows=[(ws.isoformat(), we.isoformat()) for ws, we in used_windows],
            )

            result.append(r)
    return result


def _star_call(fn_args):
    """Module-level unpacker for pool.imap — lambdas aren't picklable with spawn."""
    fn, args = fn_args
    return fn(*args)


def _prepare_estimator_kwargs(
    kwargs: dict,
    ann_params: dict | None = None,
    offset_path: str | Path | None = None,
) -> tuple[dict, list[tuple[float, float]] | None, list[int] | None, dict[str, Path]]:
    """Prepare kwargs to pass to `estimate_psd` via `partial`.

    Mutates `kwargs` in place (stripping UI-only keys, migrating legacy
    `hour_window` → `hour_windows`, translating `states` preset list →
    `labels` dict, spreading `ann_params` into `kwargs`, setting
    `offset_path` if supplied) and returns the surviving values that need
    to be passed positionally rather than via `kwargs`.

    Returns:
        Tuple of (kwargs, hour_windows, selected_days, ann_by_animal). The
        returned `kwargs` is the same dict that was passed in (mutated).
    """
    for key in _UI_ONLY_KWARGS:
        kwargs.pop(key, None)

    hour_windows = kwargs.pop("hour_windows", None)
    legacy_hw = kwargs.pop("hour_window", None)  # migrate old single-window saves
    if hour_windows is None and legacy_hw is not None:
        hour_windows = [tuple(legacy_hw)]
    selected_days = kwargs.pop("selected_days", None)

    # Translate preset-key list (as saved in psd_params.json) → labels dict.
    # Explicit labels= wins; absent both → estimate_psd's default applies.
    states = kwargs.pop("states", None)
    if states is not None and "labels" not in kwargs:
        kwargs["labels"] = labels_from_presets(states)

    if offset_path is not None:
        kwargs["offset_path"] = offset_path

    ann_by_animal: dict[str, Path] = {}
    if ann_params:
        ann_dir = ann_params.get("ann_dir")
        if ann_dir and Path(ann_dir).is_dir():
            for f in list(Path(ann_dir).glob("*.txt")) + list(Path(ann_dir).glob("*.csv")):
                ann_by_animal[parse_animal_id(f)] = f
        kwargs.update(
            {
                "ann_keywords": ann_params.get("keywords") or [],
                "ann_match_mode": ann_params.get("match_mode", "contains"),
                "ann_pad_before_sec": ann_params.get("pad_before_sec", 0.0),
                "ann_pad_after_sec": ann_params.get("pad_after_sec", 0.0),
            }
        )

    return kwargs, hour_windows, selected_days, ann_by_animal


def match_paths(
    eeg_paths: Sequence[Path],
    state_paths: Sequence[Path],
    swd_paths: Sequence[Path] | None = None,
    drink_paths: Sequence[Path] | None = None,
    *,
    eeg_state_pat: str = r"[^_]+",
    eeg_swd_pat: str = r"^(?:[A-Za-z0-9]*ts_)?([^_]+)",
) -> list[tuple[Path, Path, Path | None, Path | None]]:
    """
    Match EEG EDFs to:
      - required state CSV
      - optional SWD MAT (if swd_paths provided, requires all EEGs to have SWD)
      - optional per-file drink NPY (may be missing)

    Returns list of tuples:
        (eeg_path, state_path, swd_path_or_None, drink_path_or_None)
    """

    eeg_paths = list(eeg_paths)

    # re_match is fine here because it's required to be complete
    eeg_state_pairs = path_utils.re_match(eeg_paths, state_paths, eeg_state_pat)
    state_by_eeg: dict[Path, Path] = {ep: sp for ep, sp in eeg_state_pairs}

    # ---- OPTIONAL EEG <-> SWD (Applied to all or to none) ----
    if swd_paths is not None:
        eeg_swd_pairs = path_utils.re_match(eeg_paths, swd_paths, eeg_swd_pat)
        swd_by_eeg: dict[Path, Path] = {ep: sp for ep, sp in eeg_swd_pairs}
    else:
        swd_by_eeg = {ep: None for ep in eeg_paths}

    # per-file sparse OK): drink masks via animal-id dict
    drink_by_animal: dict[str, Path] = {}
    if drink_paths is not None:
        drink_by_animal = {parse_animal_id(p): p for p in drink_paths}

    # Build final paired list (no zip truncation)
    paired: list[tuple[Path, Path, Path | None, Path | None]] = []
    for ep in eeg_paths:
        animal = parse_animal_id(ep)
        paired.append(
            (
                ep,
                state_by_eeg[ep],
                swd_by_eeg[ep],
                drink_by_animal.get(animal),
            )
        )

    return paired


def batch_estimate(
    eeg_dir: str | Path,
    state_dir: str | Path,
    swd_dir: str | Path | None = None,
    drink_dir: str | Path | None = None,
    offset_path: str | Path | None = None,
    ncores: int | None = None,
    verbose: bool = True,
    savepath: str | Path | None = None,
    progress_fn: Callable | None = None,
    ann_params: dict | None = None,
    **kwargs,
) -> list[PSDResult]:
    """Concurrently estimate PSDs across every EDF in `eeg_dir`.

    Pairs each EDF with its SPINDLE CSV (required), SWD `.mat` (optional),
    drink `.npy` (optional, sparse), and annotation file (optional, sparse),
    then fans `estimate_psd` calls out to a process pool.

    Args:
        eeg_dir:
            Directory of EDFs (matched on `*PROCESSED.edf`).
        state_dir:
            Directory of SPINDLE-scored CSVs. Authoritative for which animals
            are included — EDFs without a matching CSV are skipped.
        swd_dir:
            Optional directory of SWD `.mat` files (one per animal).
        drink_dir:
            Optional directory of drink-mask `.npy` files (sparse — animals
            without a matching file get no drink mask).
        offset_path:
            Optional CSV mapping animal IDs to drink-EEG offset seconds.
        ncores:
            Worker count. None = use all available, capped by file count.
        verbose:
            Forwarded to `estimate_psd` and used for the batch-level banner.
        savepath:
            If set, pickles results as a list of dicts here (used by the
            two-step pipeline; downstream `build_final_pkl` consumes these).
        progress_fn:
            Optional callable invoked with a status string per file.
        ann_params:
            Optional dict with keys `ann_dir`, `keywords`, `match_mode`,
            `pad_before_sec`, `pad_after_sec`. Annotation files are matched
            to EDFs by animal ID.
        **kwargs:
            Forwarded to `estimate_psd`. UI-only keys in `_UI_ONLY_KWARGS`
            are stripped first (so saved psd_params.json can be passed as-is).

    Returns:
        Flat list of PSDResults across all animals × state groups.
    """

    warnings.filterwarnings("ignore", category=ResourceWarning)

    kwargs, hour_windows, selected_days, ann_by_animal = _prepare_estimator_kwargs(
        kwargs, ann_params, offset_path
    )

    # pair the eeg paths with the state paths
    state_paths = sorted(Path(state_dir).glob("*.csv"))
    # Only process EDFs that have a matching spindle CSV — the state CSV is
    # authoritative for which animals to include in this batch.
    state_animal_ids = {parse_animal_id(p) for p in state_paths}
    eeg_paths = sorted(
        p for p in Path(eeg_dir).glob("*PROCESSED.edf") if parse_animal_id(p) in state_animal_ids
    )
    swd_paths = (
        sorted(p for p in Path(swd_dir).glob("*.mat") if parse_animal_id(p) in state_animal_ids)
        if swd_dir
        else None
    )
    drink_paths = sorted(Path(drink_dir).glob("*.npy")) if drink_dir else None

    paired_base = match_paths(eeg_paths, state_paths, swd_paths, drink_paths)

    # Extend to 5-tuples: (eeg, state, swd, drink, annotation_path_or_None)
    paired = [(*base, ann_by_animal.get(parse_animal_id(base[0]))) for base in paired_base]

    # set number of cpu workers and print to stdout
    workers = concurrency.set_cores(ncores, len(paired))
    msg = f"Executing Batch on {len(paired)} files using {workers} cores."
    print(msg)

    estimator = partial(
        estimate_psd, hour_windows=hour_windows, selected_days=selected_days, **kwargs
    )
    n = len(paired)
    if n == 0:
        warnings.warn(
            f"batch_estimate: no EDF files in {eeg_dir} matched state CSVs in {state_dir}. "
            "Skipping batch (no output pickle written).",
            stacklevel=2,
        )
        return []
    t0 = time.perf_counter()
    if workers == 1:
        results_nested = []
        for i, args in enumerate(paired):
            if progress_fn:
                progress_fn(f"  [{i + 1}/{n}] {args[0].name}…")
            results_nested.append(estimator(*args))
    else:
        results_nested = []
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(workers) as pool:
            for i, result in enumerate(pool.imap(_star_call, [(estimator, a) for a in paired])):
                if progress_fn:
                    progress_fn(f"  [{i + 1}/{n}] done")
                results_nested.append(result)

    elapsed = time.perf_counter() - t0
    print(f"Batch processed {len(paired)} files in {elapsed} secs")

    results = [obj for sublist in results_nested for obj in sublist]

    if savepath is not None:
        r = [dataclasses.asdict(result) for result in results]
        with open(savepath, "wb") as outfile:
            pickle.dump(r, outfile)

    # flatten the list of list of PSDResult data instances
    return results


def build_run_final_pkl(project_root, run_name: str = "default") -> Path:
    """Seal a completed PSD run by copying the latest merged PKL to psds_final.pkl.

    Prefers `psds_channel_merged_drink.pkl` (which contains drink-masked
    overrides — see `rerun_with_drink_masks`) over `psds_channel_merged.pkl`.
    Raises `FileNotFoundError` if neither exists. Returns the path written.

    Distinct from `build_final_pkl`, which builds the channel-merged PKL in
    the first place from per-combo PKLs + manifest sleep_qc decisions.
    """
    psd_dir = Path(project_root) / "psd" / run_name
    drink = psd_dir / "psds_channel_merged_drink.pkl"
    base = psd_dir / "psds_channel_merged.pkl"
    source = drink if drink.exists() else base
    if not source.exists():
        raise FileNotFoundError(f"No merged PKL found in {psd_dir}. Run 'Compute PSDs' first.")
    with open(source, "rb") as f:
        data = pickle.load(f)
    out = psd_dir / "psds_final.pkl"
    tmp = out.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(data, f)
    tmp.replace(out)
    return out


def build_final_pkl(project_root, manifest, run_name: str = "default") -> Path:
    """Build psds_channel_merged.pkl by merging per-combo PKLs.

    For each animal whose manifest entry has `sleep_qc == "ok"` for some
    combo, load their record from `psds_<ok_combo>.pkl` in
    `psd/<run_name>/`, annotate with `source_combo`, and write the
    aggregated list to `psds_channel_merged.pkl` (atomically). Returns the
    path written.

    Distinct from `build_run_final_pkl`, which seals an existing merged PKL
    by copying it to `psds_final.pkl`.
    """
    project_root = Path(project_root)
    psd_dir = project_root / "psd" / run_name

    # Group animals by their ok combo
    combo_to_animals: dict = {}
    for entry in manifest:
        ok_combo = next((c for c, r in entry.runs.items() if r.sleep_qc == "ok"), None)
        if ok_combo is None:
            continue
        combo_to_animals.setdefault(ok_combo, []).append(entry.animal_id)

    final_records = []
    for combo, animal_ids in combo_to_animals.items():
        pkl = psd_dir / f"psds_{combo}.pkl"
        if not pkl.exists():
            warnings.warn(
                f"build_final_pkl: PKL not found for combo '{combo}': {pkl}", stacklevel=2
            )
            continue
        with open(pkl, "rb") as f:
            records = pickle.load(f)
        if isinstance(records, dict):
            records = [records]

        animal_ids_set = set(animal_ids)
        for rec in records:
            rec_animal = parse_animal_id(rec["path"])
            if rec_animal in animal_ids_set:
                rec = dict(rec)
                rec["source_combo"] = combo
                final_records.append(rec)

    out_path = psd_dir / "psds_channel_merged.pkl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(final_records, f)
    tmp.replace(out_path)
    return out_path


def rerun_with_drink_masks(
    psd_dir: str | Path,
    eeg_dir: str | Path,
    spindle_root: str | Path,
    drink_dir: str | Path,
    animal_combos: dict[str, str],
    offset_path: str | Path | None = None,
    swd_dir: str | Path | None = None,
    ncores: int | None = None,
    ann_params: dict | None = None,
    run_name: str = "default",
    **kwargs,
) -> tuple[Path, Path]:
    """Recompute PSDs for specific animals with drink masks.

    Validates that source_combo in psds_channel_merged.pkl matches the provided
    animal_combos mapping. Results are accumulated in psds_drink.pkl
    (replacing per animal on each call). psds_channel_merged_drink.pkl is regenerated
    as psds_channel_merged.pkl with all psds_drink.pkl animals overriding their entries.
    Neither psds_channel_merged.pkl nor any psds_<COMBO>.pkl is modified.

    Args:
        psd_dir:       Directory containing psds_channel_merged.pkl and output pkls.
        eeg_dir:       Directory of preprocessed EDF files.
        spindle_root:  Root of spindle_outputs/ (combo subdirs live here).
        drink_dir:     Directory of drink mask .npy files (one per animal).
        animal_combos: {animal_id: ok_combo} mapping for animals to rerun.
        offset_path:   Optional CSV for video-EEG time alignment.
        swd_dir:       Optional directory of SWD .mat files (one per animal).
        ncores:        Number of parallel workers (None = auto).
        ann_params:    Optional annotation mask config dict (same format as batch_estimate).
        **kwargs:      Passed through to estimate_psd (fs, winsize, etc.).

    Returns:
        Tuple of (psds_drink.pkl path, psds_channel_merged_drink.pkl path).
    """
    psd_dir = Path(psd_dir) / run_name
    eeg_dir = Path(eeg_dir)
    spindle_root = Path(spindle_root)
    drink_dir = Path(drink_dir)
    animal_ids_set = set(animal_combos)

    # --- Validate source_combo in psds_channel_merged.pkl against manifest combos ---
    merged_path = psd_dir / "psds_channel_merged.pkl"
    if not merged_path.exists():
        raise FileNotFoundError(
            f"psds_channel_merged.pkl not found at {merged_path}. Build the channel merged PKL first."
        )
    with open(merged_path, "rb") as f:
        merged_data: list[dict] = pickle.load(f)
    if isinstance(merged_data, dict):
        merged_data = [merged_data]

    merged_combo_by_animal: dict[str, str] = {}
    for rec in merged_data:
        animal = parse_animal_id(rec["path"])
        if animal in animal_ids_set:
            merged_combo_by_animal.setdefault(animal, rec.get("source_combo"))

    mismatches = []
    for animal_id, manifest_combo in animal_combos.items():
        merged_combo = merged_combo_by_animal.get(animal_id)
        if merged_combo is None:
            mismatches.append(f"  {animal_id}: not found in psds_channel_merged.pkl")
        elif merged_combo != manifest_combo:
            mismatches.append(
                f"  {animal_id}: psds_channel_merged has '{merged_combo}', manifest says '{manifest_combo}'"
            )
    if mismatches:
        raise ValueError(
            "Combo mismatch between psds_final.pkl and manifest:\n" + "\n".join(mismatches)
        )

    # --- Run estimate_psd grouped by combo ---
    combo_to_animals: dict[str, list[str]] = {}
    for animal_id, combo in animal_combos.items():
        combo_to_animals.setdefault(combo, []).append(animal_id)

    warnings.filterwarnings("ignore", category=ResourceWarning)

    kwargs, hour_windows, selected_days, ann_by_animal = _prepare_estimator_kwargs(
        kwargs, ann_params, offset_path
    )

    estimator = partial(
        estimate_psd, hour_windows=hour_windows, selected_days=selected_days, **kwargs
    )
    all_new_dicts: list[dict] = []

    for combo, animals in combo_to_animals.items():
        animals_set = set(animals)
        state_dir = spindle_root / combo
        eeg_paths = [
            p
            for p in sorted(Path(eeg_dir).glob("*PROCESSED.edf"))
            if parse_animal_id(p) in animals_set
        ]
        if not eeg_paths:
            raise ValueError(f"No EDF files found for animals {animals_set} in {eeg_dir}")
        state_paths = [p for p in sorted(state_dir.glob("*.csv")) if parse_animal_id(p) in animals_set]
        drink_paths = [p for p in sorted(drink_dir.glob("*.npy")) if parse_animal_id(p) in animals_set]
        swd_paths = (
            [p for p in sorted(Path(swd_dir).glob("*.mat")) if parse_animal_id(p) in animals_set]
            if swd_dir
            else None
        )
        base_paired = match_paths(
            eeg_paths, state_paths, swd_paths=swd_paths, drink_paths=drink_paths
        )
        paired = [(*base, ann_by_animal.get(parse_animal_id(base[0]))) for base in base_paired]

        workers = concurrency.set_cores(ncores, len(paired))
        t0 = time.perf_counter()
        if workers == 1:
            results_nested = [estimator(*args) for args in paired]
        else:
            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(workers) as pool:
                results_nested = pool.starmap(estimator, paired)
        elapsed = time.perf_counter() - t0
        print(f"Drink-mask rerun ({combo}): {len(paired)} files in {elapsed:.1f}s")

        new_dicts = [dataclasses.asdict(r) for sublist in results_nested for r in sublist]
        for d in new_dicts:
            d["source_combo"] = combo
        all_new_dicts.extend(new_dicts)

    # --- Update psds_drink.pkl (accumulate, replace per animal) ---
    drink_pkl = psd_dir / "psds_drink.pkl"
    if drink_pkl.exists():
        with open(drink_pkl, "rb") as f:
            existing_drink: list[dict] = pickle.load(f)
        if isinstance(existing_drink, dict):
            existing_drink = [existing_drink]
    else:
        existing_drink = []

    kept_drink = [
        e for e in existing_drink if parse_animal_id(e["path"]) not in animal_ids_set
    ]
    tmp = drink_pkl.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(kept_drink + all_new_dicts, f)
    tmp.replace(drink_pkl)

    # --- Regenerate psds_channel_merged_drink.pkl ---
    # Use all accumulated drink records (not just this session's) to override merged
    with open(drink_pkl, "rb") as f:
        all_drink: list[dict] = pickle.load(f)
    drink_animals = {parse_animal_id(r["path"]) for r in all_drink}
    merged_base_kept = [
        r for r in merged_data if parse_animal_id(r["path"]) not in drink_animals
    ]
    merged_drink_path = psd_dir / "psds_channel_merged_drink.pkl"
    tmp2 = merged_drink_path.with_suffix(".pkl.tmp")
    with open(tmp2, "wb") as f:
        pickle.dump(merged_base_kept + all_drink, f)
    tmp2.replace(merged_drink_path)

    return drink_pkl, merged_drink_path
