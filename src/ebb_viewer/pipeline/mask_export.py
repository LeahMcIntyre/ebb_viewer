"""Pipeline orchestration for exporting masks as time-stamped intervals.

Glues the EDF reader and ``ebb.masking`` primitives to the pure helpers in
``ebb.process.mask_export``. Per-animal failures are caught and reported in
the result rather than aborting the whole run — the UI surfaces them in a
status table.
"""

from __future__ import annotations

import contextlib
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
from ebb.io.edf_header import assert_fs_matches, parse_edf_start_datetime
from ebb.io.spindle_csv import FINAL_COLUMN
from ebb.masking.annotations import keyword_mask
from ebb.masking.threshold import commutator_samples
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
from ebb.core.naming import files_for_animal
from ebb_viewer.pipeline.naming import drink_mask_rel, parse_animal_id
from ebb_viewer.pipeline.swd_review import find_swd_file

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class AnimalExportResult:
    animal_id: str
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
) -> ResolvedPaths:
    """Locate EDF, state CSV, drink mask, and SWD MAT for one animal.

    Drink and SWD are optional — they're discovered by presence:
    ``find_swd_file`` (``project_root/swd/``) for SWD, manifest-tracked relative
    path for drink. Raises ``ValueError`` only for required files.
    """
    entry = manifest.get(animal_id)
    if entry is None:
        raise ValueError(f"Animal {animal_id!r} not in manifest")
    combo = manifest.combo
    if not entry.has_spindle:
        raise ValueError(f"Animal {animal_id!r} has no spindle files for combo {combo!r}")

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

    # Offset CSV: optional, aligns video-derived drink mask to EEG start.
    # Convention: at most one *.csv per project in drink_masks/. Multiple
    # CSVs are an error rather than silently picking the first sorted one.
    offset_csvs = sorted(drink_dir.glob("*.csv")) if drink_dir.is_dir() else []
    if len(offset_csvs) > 1:
        names = ", ".join(p.name for p in offset_csvs)
        raise ValueError(
            f"Expected at most one offset CSV in {drink_dir}, found {len(offset_csvs)}: "
            f"{names}. Remove the extra files or pick the canonical one."
        )
    offset_csv = offset_csvs[0] if offset_csvs else None

    swd = find_swd_file(project_root, animal_id)

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
        wake_sub_mask: True = wake sample. Required when ``codes`` lumps wake with
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


def _find_annotation_for_animal(ann_dir: Path | str, animal_id: str) -> Path | None:
    """Locate the annotation file for an animal inside ``ann_dir``.

    Mirrors the EEG viewer's auto-discovery rule used by
    ``on_load_annotation_dir``: .txt matches preferred over .csv over .tsv,
    sorted deterministically, first hit wins. Returns ``None`` if no match.
    """
    d = Path(ann_dir)
    if not d.is_dir():
        return None
    matches = files_for_animal(d, animal_id, ".txt", ".csv", ".tsv")
    return matches[0] if matches else None


def _coerce_param(params: dict[str, Any], key: str, default: Any) -> Any:
    """Return ``params[key]`` if present and not None, else ``default``.

    Note: an explicit ``None`` value in ``params`` is treated the same as a
    missing key. This is intended for scalar params with sensible defaults
    (``fs``, ``winsize``, etc.). Callers that use ``None`` as a meaningful
    sentinel (e.g. boolean flags where ``None`` ≠ default) should read
    ``params`` directly with ``params.get(key, default)`` instead.
    """
    val = params.get(key)
    return default if val is None else val


# ---------------------------------------------------------------------------
# Per-animal export (does EDF I/O)
# ---------------------------------------------------------------------------


@dataclass
class _BuiltMasks:
    """Output of `_build_masks` — every mask + bookkeeping needed to write an export."""

    state_masks_filtered: dict[str, np.ndarray]
    artifact_masks: dict[str, np.ndarray]
    wake_sub_mask: np.ndarray | None
    sd_threshold_mask: np.ndarray
    used_windows: list[tuple[_dt.datetime, _dt.datetime]]
    rec_start: _dt.datetime
    n_samples: int
    annotation_path: Path | None = None


def _build_masks(paths: ResolvedPaths, params: dict[str, Any]) -> _BuiltMasks:
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
    drink_pad = int(_coerce_param(params, "drink_pad", 2))
    chunksize = int(_coerce_param(params, "chunksize", int(30e5)))
    state_keys = params.get("states") or list(DEFAULT_STATES)
    labels = labels_from_presets(state_keys)

    channels = list(_coerce_param(params, "channels", [0, 1, 2]))

    with edf.Reader(paths.edf) as reader:
        assert_fs_matches(reader, fs, path=paths.edf)
        reader.channels = channels
        pro = producer(reader, chunksize=chunksize, axis=-1)
        n_samples = pro.shape[-1]
        rec_start = parse_edf_start_datetime(reader.header)

        # --- state masks ---
        state_masks_filtered: dict[str, np.ndarray] = {
            label: masking.state(paths.state, codes, fs, winsize=epoch_winsize)
            for label, codes in labels.items()
        }

        # --- wake sub-mask for mixed-wake groups ---
        needs_wake_sub = any("w" in codes and len(codes) > 1 for codes in labels.values())
        if needs_wake_sub:
            wake_sub_mask = masking.state(paths.state, ["w"], fs, winsize=epoch_winsize)
        else:
            wake_sub_mask = None

        # --- artifact masks (True = OK convention) ---
        comm_mask = masking.commutator_threshold(
            pro,
            value=2000,
            **commutator_samples(fs),
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

        use_drink = bool(params.get("use_drink_mask", True))
        use_swd = bool(params.get("use_swd_mask", True))

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
                n_samples=n_samples,
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

        # --- annotation mask (optional) ---
        # Discovered per-animal from `ann_dir`; widget emits the keyword list as
        # a comma-separated string, so split here. keyword_mask returns
        # True=match (artifact); invert to the True=keep convention.
        ann_mask = None
        ann_path: Path | None = None
        if bool(params.get("ann_enabled", False)):
            ann_dir = params.get("ann_dir")
            kw_str = params.get("ann_keywords") or ""
            keywords = [k.strip() for k in kw_str.split(",") if k.strip()]
            if ann_dir and keywords:
                animal_id = parse_animal_id(paths.edf)
                ann_path = _find_annotation_for_animal(ann_dir, animal_id)
                if ann_path is not None:
                    match_arr = keyword_mask(
                        ann_path,
                        keywords=keywords,
                        pad_before_sec=float(params.get("ann_pad_before", 0.0)),
                        pad_after_sec=float(params.get("ann_pad_after", 0.0)),
                        match_mode=params.get("ann_match_mode", "contains"),
                        size=n_samples,
                        fs=fs,
                    )
                    ann_mask = ~match_arr

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
    if ann_mask is not None:
        artifact_masks["annotation"] = ann_mask

    return _BuiltMasks(
        state_masks_filtered=state_masks_filtered,
        artifact_masks=artifact_masks,
        wake_sub_mask=wake_sub_mask,
        sd_threshold_mask=sd_threshold_mask,
        used_windows=used_windows,
        rec_start=rec_start,
        n_samples=n_samples,
        annotation_path=ann_path,
    )


def export_animal(
    project_root: Path,
    out_dir: Path,
    manifest: Manifest,
    animal_id: str,
    params: dict[str, Any],
) -> AnimalExportResult:
    """Build masks and write the four files for one animal.

    Never raises — failures are returned as ``status='error'`` results so the
    batch loop in :func:`export_run` can keep going.
    """
    try:
        paths = resolve_paths(project_root, manifest, animal_id)
        built = _build_masks(paths, params)

        fs = float(_coerce_param(params, "fs", 250))
        epoch_winsize = float(_coerce_param(params, "epoch_winsize", 4.0))
        labels = labels_from_presets(params.get("states") or list(DEFAULT_STATES))

        # Per-state clean intervals — SD-on-wake logic differs per state.
        # Base clean = AND of every artifact mask except sd_threshold (since
        # SD only applies to wake samples).
        base_clean = np.ones(built.n_samples, dtype=bool)
        for source, mask in built.artifact_masks.items():
            if source == "sd_threshold":
                continue
            base_clean = base_clean & mask

        clean_intervals = []
        for label, codes in labels.items():
            clean_for_state = clean_mask_for_state(
                codes,
                base_clean,
                built.sd_threshold_mask,
                built.wake_sub_mask,
            )
            clean_intervals.extend(
                clean_per_state_intervals(
                    {label: built.state_masks_filtered[label]},
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
        artifact_intervals = artifact_masks_to_intervals(built.artifact_masks, fs)

        meta = {
            "animal_id": animal_id,
            "combo": manifest.combo,
            "fs": fs,
            "epoch_winsize_s": epoch_winsize,
            "n_samples": int(built.n_samples),
            "duration_s": built.n_samples / fs,
            "recording_start": built.rec_start.isoformat(),
            "edf_path": str(paths.edf),
            "state_csv_path": str(paths.state),
            "state_column": FINAL_COLUMN,
            "drink_mask_path": str(paths.drink) if paths.drink else None,
            "offset_csv_path": str(paths.offset_csv) if paths.offset_csv else None,
            "swd_path": str(paths.swd) if paths.swd else None,
            "annotation_path": str(built.annotation_path) if built.annotation_path else None,
            "params": dict(params),
            "used_hour_windows": [(s.isoformat(), e.isoformat()) for s, e in built.used_windows],
            "exported_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }

        written = write_animal_export(
            out_dir=out_dir,
            animal_id=animal_id,
            combo=manifest.combo,
            state_intervals=state_intervals,
            artifact_intervals=artifact_intervals,
            clean_intervals=clean_intervals,
            meta=meta,
        )
        return AnimalExportResult(
            animal_id=animal_id,
            status="ok",
            paths=written,
        )
    except Exception as exc:  # noqa: BLE001 — we want to capture every failure mode
        return AnimalExportResult(
            animal_id=animal_id,
            status="error",
            message=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
        )


# ---------------------------------------------------------------------------
# Top-level batch entry point
# ---------------------------------------------------------------------------

ProgressCb = Callable[[str, int, int], None]
"""Signature: ``(animal_id, done, total) -> None``."""


def export_run(
    project_root: Path,
    out_dir: Path,
    manifest: Manifest,
    params: dict[str, Any],
    animal_ids: list[str],
    progress_cb: ProgressCb | None = None,
) -> ExportResult:
    """Export masks for every animal in ``animal_ids``.

    Continues on per-animal error; collects failures in the result so the UI
    can surface them.

    Args:
        project_root: Project root.
        out_dir: Pre-built output directory (e.g. ``project_root/exports/<name>/``).
        manifest: Loaded manifest.
        params: Export params (same shape as ``psd_params.json`` plus optional
            ``epoch_winsize``).
        animal_ids: Animals to export.
        progress_cb: Called *after* each animal with ``(animal, done, total)``.

    Returns:
        :class:`ExportResult` with one :class:`AnimalExportResult` per input animal.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = ExportResult(out_dir=out_dir)
    total = len(animal_ids)
    for i, animal_id in enumerate(animal_ids, start=1):
        per = export_animal(project_root, out_dir, manifest, animal_id, params)
        result.results.append(per)
        if progress_cb is not None:
            # Never let a UI callback abort the batch.
            with contextlib.suppress(Exception):
                progress_cb(animal_id, i, total)
    return result


def default_animals(manifest: Manifest) -> list[str]:
    """Return all animal IDs whose sleep_qc is 'ok'.

    Matches the convention used by the PSD compute page: only OK animals are
    eligible for export.
    """
    return [entry.animal_id for entry in manifest.ready_for_psd()]
