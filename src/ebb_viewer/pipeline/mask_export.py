"""Pipeline orchestration for exporting masks as time-stamped intervals.

Glues the EDF reader and ``ebb.masking`` primitives to the pure helpers in
``ebb.process.mask_export``. Per-animal failures are caught and reported in
the result rather than aborting the whole run — the UI surfaces them in a
status table.
"""

from __future__ import annotations

import datetime as _dt
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from openseize import producer
from openseize.file_io import edf

from ebb import masking
from ebb.process.mask_export import (
    artifact_masks_to_intervals,
    build_state_intervals,
    clean_per_state_intervals,
    write_animal_export,
)
from ebb.process.state_presets import DEFAULT_STATES, labels_from_presets
from ebb_viewer.pipeline.manifest import (
    Manifest,
    spindle_output_dir,
)
from ebb_viewer.pipeline.naming import drink_mask_rel

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class AnimalExportResult:
    animal_id: str
    combo: str
    status: str  # "ok" | "error"
    message: str = ""
    paths: dict[str, Path] = field(default_factory=dict)


@dataclass
class ExportResult:
    out_dir: Path
    results: list[AnimalExportResult] = field(default_factory=list)

    @property
    def successes(self) -> list[AnimalExportResult]:
        return [r for r in self.results if r.status == "ok"]

    @property
    def failures(self) -> list[AnimalExportResult]:
        return [r for r in self.results if r.status == "error"]


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedPaths:
    edf: Path
    state: Path
    drink: Path | None
    swd: Path | None
    offset_csv: Path | None


def resolve_paths(
    project_root: Path,
    manifest: Manifest,
    animal_id: str,
    combo: str,
) -> ResolvedPaths:
    """Locate EDF, state CSV, drink mask, and SWD MAT for one (animal, combo).

    Drink and SWD are optional — they're discovered by presence:
    ``project_root/swd/<animal_id>_*.mat`` for SWD, manifest-tracked relative
    path for drink. Raises ``ValueError`` only for required files.
    """
    entry = manifest.get(animal_id)
    if entry is None:
        raise ValueError(f"Animal {animal_id!r} not in manifest")
    if combo not in entry.runs:
        raise ValueError(f"Animal {animal_id!r} has no run for combo {combo!r}")

    edf_path = Path(project_root) / entry.preprocessed_edf
    if not edf_path.exists():
        raise ValueError(f"Preprocessed EDF not found: {edf_path}")

    matches = sorted(spindle_output_dir(combo, project_root).glob(f"{animal_id}_*.csv"))
    if not matches:
        raise ValueError(f"No state CSV found for {animal_id!r} in spindle_outputs/{combo}/")
    state_path = matches[0]

    # Drink masks: discover by file presence at the canonical path. The
    # manifest's run.drink_mask field tracks the PSD-review "applied" state,
    # not whether the file exists — for export we want any drink mask that's
    # actually on disk regardless of review workflow status.
    drink_dir = Path(project_root) / "drink_masks"
    drink_candidate = Path(project_root) / drink_mask_rel(animal_id)
    drink = drink_candidate if drink_candidate.is_file() else None

    # Offset CSV: optional. Aligns video-derived drink mask to EEG start.
    # Convention (matches the Drink Mask page): first *.csv in drink_masks/.
    offset_csvs = sorted(drink_dir.glob("*.csv")) if drink_dir.is_dir() else []
    offset_csv = offset_csvs[0] if offset_csvs else None

    swd_dir = Path(project_root) / "swd"
    swd_matches = sorted(swd_dir.glob(f"{animal_id}_*.mat")) if swd_dir.is_dir() else []
    swd = swd_matches[0] if swd_matches else None

    return ResolvedPaths(
        edf=edf_path,
        state=state_path,
        drink=drink,
        swd=swd,
        offset_csv=offset_csv,
    )


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without EDF I/O)
# ---------------------------------------------------------------------------


def clean_mask_for_state(
    codes: list[str],
    base_clean: np.ndarray,
    sd_threshold_mask: np.ndarray,
    wake_sub_mask: np.ndarray | None,
) -> np.ndarray:
    """Return a True=clean mask for a state with the given letter codes.

    Mirrors ``estimate_psd``'s SD-on-wake logic so exported clean intervals
    line up with what the PSD pipeline analyzes.

    Args:
        codes: Letter codes that make up the state group (e.g. ``['w']`` for
            wake, ``['w', 'n', 'r']`` for the ``"all"`` lumped preset).
        base_clean: Pre-AND'd combination of every artifact mask that applies
            uniformly across states (commutator, spindle noise, drink, hour
            window, etc.). True = clean.
        sd_threshold_mask: SD-threshold mask, True = OK.
        wake_sub_mask: True = wake sample (rawstate or rawstate ∩ sprob,
            depending on caller). Required when ``codes`` lumps wake with
            other states; ignored otherwise.

    Returns:
        1-D boolean array, True where the sample is clean for this state.
    """
    if "w" not in codes:
        return base_clean
    if len(codes) == 1:
        return base_clean & sd_threshold_mask
    if wake_sub_mask is None:
        raise ValueError("wake_sub_mask is required when 'w' is lumped with other state codes")
    return base_clean & (~wake_sub_mask | sd_threshold_mask)


def _coerce_param(params: dict[str, Any], key: str, default: Any) -> Any:
    val = params.get(key)
    return default if val is None else val


# ---------------------------------------------------------------------------
# Per-animal export (does EDF I/O)
# ---------------------------------------------------------------------------


def _read_recording_start(reader: edf.Reader) -> _dt.datetime:
    start_str = reader.header.start_time  # "HH.MM.SS"
    date_str = reader.header.start_date  # "DD.MM.YY"
    return _dt.datetime.strptime(f"{date_str} {start_str}", "%d.%m.%y %H.%M.%S")


def _build_masks(
    paths: ResolvedPaths,
    params: dict[str, Any],
) -> tuple[
    dict[str, np.ndarray],  # state_masks_raw (rawstate, no sprob)
    dict[str, np.ndarray],  # state_masks_filtered (sprob applied if set)
    dict[str, np.ndarray],  # artifact_masks (True=OK)
    np.ndarray | None,  # wake_sub_mask (only if mixed-wake group present)
    np.ndarray,  # sd_threshold_mask (separate; always built)
    list[tuple[_dt.datetime, _dt.datetime]],  # used hour windows
    _dt.datetime,  # recording start
    int,  # n_samples
]:
    """Open the EDF and build every mask we need to write the three CSVs.

    ``estimate_psd``'s mask construction is the source of truth for which
    primitives apply with which params; this function mirrors it as closely
    as possible so exports stay consistent with PSD analyses.
    """
    fs = float(_coerce_param(params, "fs", 250))
    epoch_winsize = float(_coerce_param(params, "epoch_winsize", 4.0))
    sd_winsize_s = float(_coerce_param(params, "winsize", 180))
    sd_radius_s = float(_coerce_param(params, "radius", 0.5))
    nstd = float(_coerce_param(params, "nstd", 5))
    noise_thresh = float(_coerce_param(params, "noise_thresh", 0.5))
    s_prob = params.get("s_prob")  # may legitimately be None
    drink_pad = int(_coerce_param(params, "drink_pad", 2))
    chunksize = int(_coerce_param(params, "chunksize", int(30e5)))
    state_keys = params.get("states") or list(DEFAULT_STATES)
    labels = labels_from_presets(state_keys)

    channels = list(_coerce_param(params, "channels", [0, 1, 2]))

    with edf.Reader(paths.edf) as reader:
        reader.channels = channels
        pro = producer(reader, chunksize=chunksize, axis=-1)
        n_samples = pro.shape[-1]
        rec_start = _read_recording_start(reader)

        # --- state masks ---
        state_masks_raw: dict[str, np.ndarray] = {}
        state_masks_filtered: dict[str, np.ndarray] = {}
        for label, codes in labels.items():
            state_masks_raw[label] = masking.state(paths.state, codes, fs, winsize=epoch_winsize)
            if s_prob is not None and len(codes) == 1:
                state_masks_filtered[label] = masking.state_prob(
                    paths.state, codes[0], fs, winsize=epoch_winsize, sprob=s_prob
                )
            else:
                # Lumped groups can't be filtered with the single-class sprob;
                # just OR the per-code filtered masks together.
                if s_prob is not None:
                    parts = [
                        masking.state_prob(paths.state, c, fs, winsize=epoch_winsize, sprob=s_prob)
                        for c in codes
                    ]
                    state_masks_filtered[label] = np.any(parts, axis=0)
                else:
                    state_masks_filtered[label] = state_masks_raw[label]

        # --- wake sub-mask for mixed-wake groups ---
        needs_wake_sub = any("w" in codes and len(codes) > 1 for codes in labels.values())
        if needs_wake_sub:
            if s_prob is not None:
                wake_sub_mask = masking.state_prob(
                    paths.state, "w", fs, winsize=epoch_winsize, sprob=s_prob
                )
            else:
                wake_sub_mask = masking.state(paths.state, ["w"], fs, winsize=epoch_winsize)
        else:
            wake_sub_mask = None

        # --- artifact masks (True = OK convention) ---
        comm_mask = masking.commutator_threshold(
            pro,
            value=2000,
            radius=250,
            pad=250,
            min_to_pad=10,
        )[0]
        spindle_mask = masking.spindle_noise(
            paths.state,
            noise_thresh=noise_thresh,
            fs=fs,
            winsize=epoch_winsize,
            include=False,
        )

        comm_pro = producer(comm_mask, chunksize=int(4.5e4), axis=-1)
        sd_threshold_mask = masking.sd_threshold(
            pro,
            [nstd],
            winsize=sd_winsize_s * fs,
            radius=sd_radius_s * fs,
            mask_pro=comm_pro,
        )[0]

        use_drink = bool(_coerce_param(params, "use_drink_mask", True))
        use_swd = bool(_coerce_param(params, "use_swd_mask", True))

        if paths.drink is not None and use_drink:
            offset = None
            if paths.offset_csv is not None:
                try:
                    offset = masking.get_offset(paths.drink, paths.offset_csv)
                except Exception as exc:  # missing animal row, malformed CSV, etc.
                    print(
                        f"  warning: could not read drink offset for "
                        f"{paths.drink.stem!r} from {paths.offset_csv.name}: {exc}"
                    )
                    offset = None
            drink_mask = masking.drinking_mask(
                paths.drink,
                offset,
                fs=fs,
                pad_sec=drink_pad,
            )
        else:
            drink_mask = np.ones(n_samples, dtype=bool)

        if paths.swd is not None and use_swd:
            swd_pad = int(_coerce_param(params, "swd_pad", 0))
            swd_mask = masking.swd(
                path=paths.swd,
                n_samples=n_samples,
                fs=fs,
                pad_sec=swd_pad,
            )
        else:
            swd_mask = None

        hour_windows = params.get("hour_windows")
        if hour_windows:
            tod_mask, used_windows = masking.hour_window_mask(
                rec_start,
                n_samples,
                fs,
                hour_windows,
                params.get("selected_days"),
            )
        else:
            tod_mask = np.ones(n_samples, dtype=bool)
            used_windows = []

    artifact_masks: dict[str, np.ndarray] = {
        "commutator": comm_mask,
        "spindle_noise": spindle_mask,
        "sd_threshold": sd_threshold_mask,
    }
    if paths.drink is not None and use_drink:
        artifact_masks["drink"] = drink_mask
    if swd_mask is not None:
        artifact_masks["swd"] = swd_mask
    if hour_windows:
        artifact_masks["outside_hour_window"] = tod_mask

    return (
        state_masks_raw,
        state_masks_filtered,
        artifact_masks,
        wake_sub_mask,
        sd_threshold_mask,
        used_windows,
        rec_start,
        n_samples,
    )


def export_animal(
    project_root: Path,
    out_dir: Path,
    manifest: Manifest,
    animal_id: str,
    combo: str,
    params: dict[str, Any],
) -> AnimalExportResult:
    """Build masks and write the four files for one (animal, combo).

    Never raises — failures are returned as ``status='error'`` results so the
    batch loop in :func:`export_run` can keep going.
    """
    try:
        paths = resolve_paths(project_root, manifest, animal_id, combo)
        (
            state_masks_raw,
            state_masks_filtered,
            artifact_masks,
            wake_sub_mask,
            sd_threshold_mask,
            used_windows,
            rec_start,
            n_samples,
        ) = _build_masks(paths, params)

        fs = float(_coerce_param(params, "fs", 250))
        epoch_winsize = float(_coerce_param(params, "epoch_winsize", 4.0))
        labels = labels_from_presets(params.get("states") or list(DEFAULT_STATES))

        # Per-state clean intervals — SD-on-wake logic differs per state.
        # Base clean = AND of every artifact mask except sd_threshold (since
        # SD only applies to wake samples).
        base_clean = np.ones(n_samples, dtype=bool)
        for source, mask in artifact_masks.items():
            if source == "sd_threshold":
                continue
            base_clean = base_clean & mask

        clean_intervals = []
        for label, codes in labels.items():
            clean_for_state = clean_mask_for_state(
                codes,
                base_clean,
                sd_threshold_mask,
                wake_sub_mask,
            )
            clean_intervals.extend(
                clean_per_state_intervals(
                    {label: state_masks_filtered[label]},
                    clean_for_state,
                    fs,
                )
            )
        clean_intervals.sort(key=lambda r: (r.start_sample, r.label))

        state_intervals = build_state_intervals(
            paths.state,
            fs=fs,
            winsize=epoch_winsize,
        )
        artifact_intervals = artifact_masks_to_intervals(artifact_masks, fs)

        meta = {
            "animal_id": animal_id,
            "combo": combo,
            "fs": fs,
            "epoch_winsize_s": epoch_winsize,
            "n_samples": int(n_samples),
            "duration_s": n_samples / fs,
            "recording_start": rec_start.isoformat(),
            "edf_path": str(paths.edf),
            "state_csv_path": str(paths.state),
            "drink_mask_path": str(paths.drink) if paths.drink else None,
            "offset_csv_path": str(paths.offset_csv) if paths.offset_csv else None,
            "swd_path": str(paths.swd) if paths.swd else None,
            "params": dict(params),
            "used_hour_windows": [(s.isoformat(), e.isoformat()) for s, e in used_windows],
            "exported_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }

        written = write_animal_export(
            out_dir=out_dir,
            animal_id=animal_id,
            combo=combo,
            state_intervals=state_intervals,
            artifact_intervals=artifact_intervals,
            clean_intervals=clean_intervals,
            meta=meta,
        )
        return AnimalExportResult(
            animal_id=animal_id,
            combo=combo,
            status="ok",
            paths=written,
        )
    except Exception as exc:  # noqa: BLE001 — we want to capture every failure mode
        return AnimalExportResult(
            animal_id=animal_id,
            combo=combo,
            status="error",
            message=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
        )


# ---------------------------------------------------------------------------
# Top-level batch entry point
# ---------------------------------------------------------------------------

ProgressCb = Callable[[str, str, int, int], None]
"""Signature: ``(animal_id, combo, done, total) -> None``."""


def export_run(
    project_root: Path,
    out_dir: Path,
    manifest: Manifest,
    params: dict[str, Any],
    pairs: list[tuple[str, str]],
    progress_cb: ProgressCb | None = None,
) -> ExportResult:
    """Export masks for every ``(animal_id, combo)`` pair.

    Continues on per-animal error; collects failures in the result so the UI
    can surface them.

    Args:
        project_root: Project root.
        out_dir: Pre-built output directory (e.g. ``project_root/exports/<name>/``).
        manifest: Loaded manifest.
        params: Export params (same shape as ``psd_params.json`` plus optional
            ``epoch_winsize``).
        pairs: ``(animal_id, combo)`` pairs to export.
        progress_cb: Called *after* each pair with ``(animal, combo, done, total)``.

    Returns:
        :class:`ExportResult` with one :class:`AnimalExportResult` per input pair.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = ExportResult(out_dir=out_dir)
    total = len(pairs)
    for i, (animal_id, combo) in enumerate(pairs, start=1):
        per = export_animal(project_root, out_dir, manifest, animal_id, combo, params)
        result.results.append(per)
        if progress_cb is not None:
            try:
                progress_cb(animal_id, combo, i, total)
            except Exception:
                pass  # never let a UI callback abort the batch
    return result


def default_pairs(manifest: Manifest) -> list[tuple[str, str]]:
    """Return all (animal_id, combo) pairs whose run is sleep_qc='ok'.

    Matches the convention used by the PSD compute page: only OK runs are
    eligible because they're the canonical run for an animal.
    """
    return [
        (entry.animal_id, combo)
        for entry in manifest
        for combo, run in entry.runs.items()
        if run.sleep_qc == "ok"
    ]
