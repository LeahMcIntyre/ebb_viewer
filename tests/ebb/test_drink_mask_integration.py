"""Tests for drink-mask integration in PSD computation.

Covers:
- batch_estimate passes offset_path through to estimate_psd via kwargs
- batch_estimate passes drink_dir through correctly
- rerun_with_drink_masks validates source_combo, writes psds_drink.pkl,
  regenerates psds_channel_merged_drink.pkl, never touches psds_channel_merged.pkl
- rerun_with_drink_masks raises when psds_channel_merged.pkl missing or combo mismatches
- rerun_with_drink_masks raises when no EDF files found for target animals
- DrinkMaskRerunWorker.run calls rerun_with_drink_masks with correct args
- BatchEstimateWorker.run passes drink_dir=None, embeds params in PKL, saves psd_params.json
- PSDPage._detect_offset_csv finds first CSV or returns None
"""

import pickle
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_psd_record(animal_id: str, combo: str = "LFC_RSC") -> dict:
    return {
        "path": str(Path(f"{animal_id}_foo_PREPROCESSED.edf")),
        "source_combo": combo,
        "channels": (0, 1),
        "behavior": ("threshold", "wake"),
        "n_estimates": 10,
        "spindle_out_frac": 0.1,
        "comm_out_frac": 0.05,
        "sd_out_frac": 0.02,
        "swd_out_frac": 0.0,
        "drink_out_frac": 0.03,
        "used_swd": False,
        "used_drink": True,
        "freqs": [0.5, 1.0],
        "psd": [[1.0, 2.0], [3.0, 4.0]],
    }


def _write_pkl(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(records, f)


# ---------------------------------------------------------------------------
# batch_estimate: offset_path flows through kwargs
# ---------------------------------------------------------------------------

def test_batch_estimate_passes_offset_path(tmp_path):
    """offset_path is injected into kwargs and reaches the estimator partial."""
    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    for aid in ("AM001", "AM002"):
        (standard / f"{aid}_foo_PREPROCESSED.edf").touch()
        (spindle_out / f"{aid}_states.csv").touch()

    offset_csv = tmp_path / "drink_masks" / "offsets.csv"
    offset_csv.parent.mkdir()
    offset_csv.touch()

    captured_kwargs = {}

    def fake_partial(fn, **kwargs):
        captured_kwargs.update(kwargs)
        return lambda *a: []

    with patch("ebb.process.psd_compute.match_paths", return_value=[]), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1), \
         patch("ebb.process.psd_compute.functools.partial", side_effect=fake_partial):
        from ebb.process.psd_compute import batch_estimate
        batch_estimate(
            eeg_dir=standard,
            state_dir=spindle_out,
            offset_path=offset_csv,
            fs=250,
        )

    assert captured_kwargs.get("offset_path") == offset_csv


def test_batch_estimate_no_offset_path_not_in_kwargs(tmp_path):
    """When offset_path is not passed, it is not injected into kwargs."""
    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    captured_kwargs = {}

    def fake_partial(fn, **kwargs):
        captured_kwargs.update(kwargs)
        return lambda *a: []

    with patch("ebb.process.psd_compute.match_paths", return_value=[]), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1), \
         patch("ebb.process.psd_compute.functools.partial", side_effect=fake_partial):
        from ebb.process.psd_compute import batch_estimate
        batch_estimate(eeg_dir=standard, state_dir=spindle_out)

    assert "offset_path" not in captured_kwargs


def test_batch_estimate_passes_drink_dir(tmp_path):
    """drink_dir is passed to match_paths as drink_paths."""
    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)
    drink_dir = tmp_path / "drink_masks"
    drink_dir.mkdir()
    (drink_dir / "AM001.npy").touch()

    captured = {}

    def fake_match_paths(eeg_paths, state_paths, swd_paths, drink_paths):
        captured["drink_paths"] = drink_paths
        return []

    with patch("ebb.process.psd_compute.match_paths", side_effect=fake_match_paths), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1):
        from ebb.process.psd_compute import batch_estimate
        batch_estimate(eeg_dir=standard, state_dir=spindle_out, drink_dir=drink_dir)

    assert captured["drink_paths"] is not None
    assert any("AM001.npy" in str(p) for p in captured["drink_paths"])


# ---------------------------------------------------------------------------
# rerun_with_drink_masks
# ---------------------------------------------------------------------------

def _setup_rerun_dirs(tmp_path, animals=("AM001", "AM002"), combo="LFC_RSC"):
    """Create standard/, spindle_outputs/<combo>/, drink_masks/, and psd/ dirs."""
    standard = tmp_path / "standard"
    standard.mkdir(exist_ok=True)
    spindle_out = tmp_path / "spindle_outputs" / combo
    spindle_out.mkdir(parents=True, exist_ok=True)
    drink_dir = tmp_path / "drink_masks"
    drink_dir.mkdir(exist_ok=True)
    psd_dir = tmp_path / "psd"
    psd_dir.mkdir(exist_ok=True)

    for aid in animals:
        (standard / f"{aid}_foo_PREPROCESSED.edf").touch()
        (spindle_out / f"{aid}_states.csv").touch()
        (drink_dir / f"{aid}.npy").touch()

    return standard, spindle_out, drink_dir, psd_dir


def test_rerun_writes_drink_pkl_and_final_drink_pkl(tmp_path):
    """rerun_with_drink_masks writes psds_drink.pkl and psds_channel_merged_drink.pkl;
    psds_channel_merged.pkl is not modified."""
    standard, spindle_out, drink_dir, psd_dir = _setup_rerun_dirs(tmp_path)

    # psds_channel_merged.pkl has both animals; AM002 is the target
    final_records = [_make_psd_record("AM001"), _make_psd_record("AM002")]
    _write_pkl(psd_dir / "psds_channel_merged.pkl", final_records)

    new_record = _make_psd_record("AM002")

    with patch("ebb.process.psd_compute.match_paths",
               return_value=[(standard / "AM002_foo_PREPROCESSED.edf",
                              spindle_out / "AM002_states.csv",
                              None,
                              drink_dir / "AM002.npy")]), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1), \
         patch("ebb.process.psd_compute.estimate_psd", return_value=[MagicMock(**new_record)]), \
         patch("ebb.process.psd_compute.dataclasses.asdict", return_value=new_record):
        from ebb.process.psd_compute import rerun_with_drink_masks
        drink_pkl, final_drink_pkl = rerun_with_drink_masks(
            psd_dir=psd_dir,
            eeg_dir=standard,
            spindle_root=tmp_path / "spindle_outputs",
            drink_dir=drink_dir,
            animal_combos={"AM002": "LFC_RSC"},
            fs=250,
            channels=[0, 1],
        )

    # psds_channel_merged.pkl is untouched
    with open(psd_dir / "psds_channel_merged.pkl", "rb") as f:
        final = pickle.load(f)
    assert [Path(r["path"]).stem.split("_")[0] for r in final] == ["AM001", "AM002"]

    # psds_drink.pkl contains only AM002
    with open(drink_pkl, "rb") as f:
        drink = pickle.load(f)
    assert [Path(r["path"]).stem.split("_")[0] for r in drink] == ["AM002"]

    # psds_channel_merged_drink.pkl has AM001 (from merged) + AM002 (from drink)
    with open(final_drink_pkl, "rb") as f:
        merged = pickle.load(f)
    ids = [Path(r["path"]).stem.split("_")[0] for r in merged]
    assert "AM001" in ids
    assert ids.count("AM002") == 1


def test_rerun_accumulates_drink_pkl_across_sessions(tmp_path):
    """A second rerun adds to psds_drink.pkl without duplicating prior entries."""
    standard, spindle_out, drink_dir, psd_dir = _setup_rerun_dirs(
        tmp_path, animals=("AM001", "AM002")
    )
    final_records = [_make_psd_record("AM001"), _make_psd_record("AM002")]
    _write_pkl(psd_dir / "psds_channel_merged.pkl", final_records)

    new_record = _make_psd_record("AM001")

    def run_rerun(animal_id):
        rec = _make_psd_record(animal_id)
        with patch("ebb.process.psd_compute.match_paths",
                   return_value=[(standard / f"{animal_id}_foo_PREPROCESSED.edf",
                                  spindle_out / f"{animal_id}_states.csv",
                                  None, drink_dir / f"{animal_id}.npy")]), \
             patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1), \
             patch("ebb.process.psd_compute.estimate_psd", return_value=[MagicMock(**rec)]), \
             patch("ebb.process.psd_compute.dataclasses.asdict", return_value=rec):
            from ebb.process.psd_compute import rerun_with_drink_masks
            rerun_with_drink_masks(
                psd_dir=psd_dir,
                eeg_dir=standard,
                spindle_root=tmp_path / "spindle_outputs",
                drink_dir=drink_dir,
                animal_combos={animal_id: "LFC_RSC"},
                fs=250,
            )

    run_rerun("AM001")
    run_rerun("AM002")

    with open(psd_dir / "psds_drink.pkl", "rb") as f:
        drink = pickle.load(f)
    ids = [Path(r["path"]).stem.split("_")[0] for r in drink]
    assert sorted(ids) == ["AM001", "AM002"]


def test_rerun_raises_when_final_pkl_missing(tmp_path):
    """FileNotFoundError raised when psds_channel_merged.pkl does not exist."""
    standard, _, drink_dir, psd_dir = _setup_rerun_dirs(tmp_path)

    from ebb.process.psd_compute import rerun_with_drink_masks
    with pytest.raises(FileNotFoundError, match="psds_channel_merged.pkl"):
        rerun_with_drink_masks(
            psd_dir=psd_dir,
            eeg_dir=standard,
            spindle_root=tmp_path / "spindle_outputs",
            drink_dir=drink_dir,
            animal_combos={"AM001": "LFC_RSC"},
        )


def test_rerun_raises_on_combo_mismatch(tmp_path):
    """ValueError raised when source_combo in psds_channel_merged.pkl differs from manifest combo."""
    standard, _, drink_dir, psd_dir = _setup_rerun_dirs(tmp_path)
    # AM001 is stored under LFC_RSC in psds_channel_merged.pkl
    _write_pkl(psd_dir / "psds_channel_merged.pkl", [_make_psd_record("AM001", combo="LFC_RSC")])

    from ebb.process.psd_compute import rerun_with_drink_masks
    with pytest.raises(ValueError, match="Combo mismatch"):
        rerun_with_drink_masks(
            psd_dir=psd_dir,
            eeg_dir=standard,
            spindle_root=tmp_path / "spindle_outputs",
            drink_dir=drink_dir,
            animal_combos={"AM001": "RSC_LSC"},   # wrong combo
        )


def test_rerun_with_drink_masks_raises_when_no_edfs(tmp_path):
    """ValueError raised when no EDF files match the target animal IDs."""
    _, _, drink_dir, psd_dir = _setup_rerun_dirs(tmp_path, animals=("AM001",))
    standard = tmp_path / "standard_empty"
    standard.mkdir()  # no EDFs
    _write_pkl(psd_dir / "psds_channel_merged.pkl", [_make_psd_record("AM001")])

    from ebb.process.psd_compute import rerun_with_drink_masks
    with pytest.raises(ValueError, match="No EDF files found"):
        rerun_with_drink_masks(
            psd_dir=psd_dir,
            eeg_dir=standard,
            spindle_root=tmp_path / "spindle_outputs",
            drink_dir=drink_dir,
            animal_combos={"AM001": "LFC_RSC"},
        )


# ---------------------------------------------------------------------------
# BatchEstimateWorker
# ---------------------------------------------------------------------------

def _run_batch_worker(tmp_path, params=None, offset_path=None):
    """Run BatchEstimateWorker with a recording batch_estimate stub; return calls."""
    if params is None:
        params = {"fs": 250, "channels": [0, 1]}
    spindle_dir = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_dir.mkdir(parents=True)
    psd_dir = tmp_path / "psd"
    psd_dir.mkdir(exist_ok=True)
    savepath = psd_dir / "psds_LFC_RSC.pkl"

    pairs = [(spindle_dir, savepath)]
    calls = []

    import ebb.process.psd_compute as psd_mod
    orig = psd_mod.batch_estimate

    def recording_be(**kw):
        calls.append(kw)
        return []  # empty results list

    psd_mod.batch_estimate = recording_be
    try:
        from ebb_viewer.pages.psds import BatchEstimateWorker
        worker = BatchEstimateWorker(
            eeg_dir=tmp_path / "standard",
            combo_pairs=pairs,
            params=params,
            project_root=tmp_path,
            offset_path=offset_path,
        )
        worker.run()
    finally:
        psd_mod.batch_estimate = orig

    return calls, savepath


def test_batch_worker_always_passes_drink_dir_none(tmp_path):
    """BatchEstimateWorker always passes drink_dir=None (clean compute)."""
    calls, _ = _run_batch_worker(tmp_path)
    assert len(calls) == 1
    assert calls[0]["drink_dir"] is None


def test_batch_worker_always_passes_savepath_none(tmp_path):
    """BatchEstimateWorker passes savepath=None and saves PKL manually."""
    calls, _ = _run_batch_worker(tmp_path)
    assert calls[0]["savepath"] is None


def test_batch_worker_passes_offset_path(tmp_path):
    """BatchEstimateWorker forwards offset_path when provided."""
    offset_csv = tmp_path / "offsets.csv"
    offset_csv.touch()
    calls, _ = _run_batch_worker(tmp_path, offset_path=offset_csv)
    assert calls[0]["offset_path"] == offset_csv


def test_batch_worker_offset_path_none_when_not_given(tmp_path):
    """BatchEstimateWorker passes offset_path=None when not provided."""
    calls, _ = _run_batch_worker(tmp_path)
    assert calls[0]["offset_path"] is None


def test_batch_worker_saves_pkl_with_params(tmp_path):
    """BatchEstimateWorker saves PKL manually with params embedded in each record."""
    import dataclasses

    params = {"fs": 250, "channels": [0, 1]}
    spindle_dir = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_dir.mkdir(parents=True)
    savepath = tmp_path / "psd" / "psds_LFC_RSC.pkl"
    savepath.parent.mkdir(parents=True)

    fake_result = MagicMock()
    fake_result_dict = {"path": "AM001_PREPROCESSED.edf", "psd": [1.0]}

    import ebb.process.psd_compute as psd_mod
    orig = psd_mod.batch_estimate
    psd_mod.batch_estimate = lambda **kw: [fake_result]

    import ebb_viewer.pages.psds as psds_mod
    orig_asdict = psds_mod.dataclasses.asdict

    def fake_asdict(obj):
        return dict(fake_result_dict)

    psds_mod.dataclasses.asdict = fake_asdict
    try:
        from ebb_viewer.pages.psds import BatchEstimateWorker
        worker = BatchEstimateWorker(
            eeg_dir=tmp_path / "standard",
            combo_pairs=[(spindle_dir, savepath)],
            params=params,
            project_root=tmp_path,
        )
        worker.run()
    finally:
        psd_mod.batch_estimate = orig
        psds_mod.dataclasses.asdict = orig_asdict

    with open(savepath, "rb") as f:
        records = pickle.load(f)

    assert len(records) == 1
    assert records[0]["params"] == params


def test_batch_worker_saves_psd_params_json(tmp_path):
    """BatchEstimateWorker saves psd_params.json after computing."""
    import json
    params = {"fs": 250, "channels": [0, 1], "winsize": 180, "radius": 0.5}

    psd_dir = tmp_path / "psd"
    psd_dir.mkdir()
    spindle_dir = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_dir.mkdir(parents=True)
    savepath = psd_dir / "psds_LFC_RSC.pkl"

    import ebb.process.psd_compute as psd_mod
    orig = psd_mod.batch_estimate
    psd_mod.batch_estimate = lambda **kw: []
    try:
        from ebb_viewer.pages.psds import BatchEstimateWorker
        worker = BatchEstimateWorker(
            eeg_dir=tmp_path / "standard",
            combo_pairs=[(spindle_dir, savepath)],
            params=params,
            project_root=tmp_path,
        )
        worker.run()
    finally:
        psd_mod.batch_estimate = orig

    params_file = tmp_path / "psd" / "psd_params.json"
    assert params_file.exists()
    saved = json.loads(params_file.read_text())
    # saved includes swd_mode alongside the compute params
    assert {k: v for k, v in saved.items() if k != "swd_mode"} == params
    assert saved["swd_mode"] == "none"


# ---------------------------------------------------------------------------
# Testing gaps (PIPELINE_AUDIT.md)
# ---------------------------------------------------------------------------

def test_build_final_pkl_warns_and_skips_when_combo_pkl_missing(tmp_path):
    """Gap 1: build_final_pkl emits a warning and silently skips animals whose
    combo PKL doesn't exist. The merged PKL is still written containing only
    animals whose combo PKL is present.

    build_final_pkl groups animals by combo, then loads each combo's PKL.
    The warning fires when the PKL for a combo is entirely absent on disk.
    """
    import warnings
    import pickle
    from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry, RunEntry

    psd_dir = tmp_path / "psd"
    psd_dir.mkdir()

    # AM001 uses LFC_RSC (PKL will be present); AM002 uses RSC_LSC (PKL absent)
    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="standard/AM001_PREPROCESSED.edf",
        runs={"LFC_RSC": RunEntry(sleep_qc="ok")},
    )
    m._entries["AM002"] = ManifestEntry(
        animal_id="AM002",
        preprocessed_edf="standard/AM002_PREPROCESSED.edf",
        runs={"RSC_LSC": RunEntry(sleep_qc="ok")},
    )
    m.save()

    # Only create PKL for LFC_RSC; RSC_LSC PKL is intentionally absent
    am001_record = _make_psd_record("AM001", combo="LFC_RSC")
    _write_pkl(psd_dir / "psds_LFC_RSC.pkl", [am001_record])

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from ebb.process.psd_compute import build_final_pkl
        out = build_final_pkl(tmp_path, m)

    # Warning emitted for the missing RSC_LSC PKL
    assert any("PKL not found" in str(warning.message) for warning in w), \
        "Expected a warning about the missing per-combo PKL"

    # Merged PKL written; AM001 present, AM002 absent (its combo PKL was missing)
    with open(out, "rb") as f:
        records = pickle.load(f)
    animal_ids = {Path(r["path"]).stem.split("_")[0] for r in records}
    assert "AM001" in animal_ids
    assert "AM002" not in animal_ids


def test_batch_estimate_writes_empty_pkl_when_no_matching_edfs(tmp_path):
    """Gap 7: When no EDF files match the state CSV animal IDs, batch_estimate
    writes an empty list to savepath rather than silently not writing.
    """
    import pickle
    from unittest.mock import patch

    eeg_dir = tmp_path / "standard"
    eeg_dir.mkdir()
    state_dir = tmp_path / "spindle_outputs" / "LFC_RSC"
    state_dir.mkdir(parents=True)
    (state_dir / "AM001_states.csv").touch()
    # No EDF files in eeg_dir — no matches

    savepath = tmp_path / "psd" / "psds_LFC_RSC.pkl"
    savepath.parent.mkdir(parents=True)

    with patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1), \
         patch("ebb.process.psd_compute.match_paths", return_value=[]):
        from ebb.process.psd_compute import batch_estimate
        batch_estimate(
            eeg_dir=eeg_dir,
            state_dir=state_dir,
            savepath=savepath,
        )

    assert savepath.exists(), "savepath should be written even with 0 results"
    with open(savepath, "rb") as f:
        result = pickle.load(f)
    assert result == [], f"Expected empty list, got {result!r}"


# ---------------------------------------------------------------------------
# DrinkMaskRerunWorker (now in drink_mask.py)
# ---------------------------------------------------------------------------

def test_drink_mask_rerun_worker_calls_rerun(tmp_path):
    """Worker calls rerun_with_drink_masks with the right args."""
    drink_dir = tmp_path / "drink_masks"
    drink_dir.mkdir()
    psd_dir = tmp_path / "psd"
    psd_dir.mkdir()
    standard = tmp_path / "standard"
    standard.mkdir()
    (tmp_path / "spindle_outputs" / "LFC_RSC").mkdir(parents=True)

    calls = []

    import ebb.process.psd_compute as psd_mod
    orig = psd_mod.rerun_with_drink_masks

    def recording_rerun(**kw):
        calls.append(kw)

    psd_mod.rerun_with_drink_masks = recording_rerun
    try:
        from ebb_viewer.pages.drink_mask import DrinkMaskRerunWorker
        worker = DrinkMaskRerunWorker(
            psd_dir=psd_dir,
            eeg_dir=standard,
            spindle_root=tmp_path / "spindle_outputs",
            drink_dir=drink_dir,
            animal_combos={"AM001": "LFC_RSC", "AM002": "LFC_RSC"},
            offset_path=None,
            params={"fs": 250, "winsize": 180, "radius": 0.5, "nstd": 5.0, "noise_thresh": 0.5},
        )
        worker.run()
    finally:
        psd_mod.rerun_with_drink_masks = orig

    assert len(calls) == 1
    c = calls[0]
    assert c["psd_dir"] == psd_dir
    assert c["eeg_dir"] == standard
    assert c["spindle_root"] == tmp_path / "spindle_outputs"
    assert c["drink_dir"] == drink_dir
    assert c["animal_combos"] == {"AM001": "LFC_RSC", "AM002": "LFC_RSC"}
    assert c.get("offset_path") is None


def test_drink_mask_rerun_worker_injects_offset_path(tmp_path):
    """Worker passes offset_path to rerun_with_drink_masks when provided."""
    drink_dir = tmp_path / "drink_masks"
    drink_dir.mkdir()
    offset_csv = drink_dir / "offsets.csv"
    offset_csv.touch()

    calls = []

    import ebb.process.psd_compute as psd_mod
    orig = psd_mod.rerun_with_drink_masks

    def recording_rerun(**kw):
        calls.append(kw)

    psd_mod.rerun_with_drink_masks = recording_rerun
    try:
        from ebb_viewer.pages.drink_mask import DrinkMaskRerunWorker
        worker = DrinkMaskRerunWorker(
            psd_dir=tmp_path / "psd",
            eeg_dir=tmp_path / "standard",
            spindle_root=tmp_path / "spindle_outputs",
            drink_dir=drink_dir,
            animal_combos={"AM001": "LFC_RSC"},
            offset_path=offset_csv,
            params={"fs": 250, "winsize": 180, "radius": 0.5, "nstd": 5.0, "noise_thresh": 0.5},
        )
        worker.run()
    finally:
        psd_mod.rerun_with_drink_masks = orig

    assert calls[0].get("offset_path") == offset_csv


def test_drink_mask_rerun_worker_emits_error_on_exception(tmp_path):
    """Worker emits error signal when rerun_with_drink_masks raises."""
    import ebb.process.psd_compute as psd_mod
    orig = psd_mod.rerun_with_drink_masks
    psd_mod.rerun_with_drink_masks = MagicMock(side_effect=RuntimeError("boom"))

    errors = []
    try:
        from ebb_viewer.pages.drink_mask import DrinkMaskRerunWorker
        worker = DrinkMaskRerunWorker(
            psd_dir=tmp_path / "psd",
            eeg_dir=tmp_path / "standard",
            spindle_root=tmp_path / "spindle_outputs",
            drink_dir=tmp_path / "drink_masks",
            animal_combos={"AM001": "LFC_RSC"},
            offset_path=None,
            params={"fs": 250, "winsize": 180, "radius": 0.5, "nstd": 5.0, "noise_thresh": 0.5},
        )
        worker.error.connect(errors.append)
        worker.run()
    finally:
        psd_mod.rerun_with_drink_masks = orig

    assert errors == ["boom"]


# ---------------------------------------------------------------------------
# QApplication fixture (no pytest-qt required)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """Create a QApplication for the session (skips if display unavailable)."""
    import os
    import sys
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    return app


@pytest.fixture()
def page(tmp_path, qapp):
    """Construct a DrinkMaskPage against a bare tmp_path project root."""
    from ebb_viewer.pages.drink_mask import DrinkMaskPage
    w = DrinkMaskPage(project_root=tmp_path)
    yield w, tmp_path
    w.close()


# ---------------------------------------------------------------------------
# DrinkMaskPage helpers
# ---------------------------------------------------------------------------

def test_detect_offset_csv_none_when_no_dir(page):
    w, _ = page
    assert w._detect_offset_csv() is None


def test_detect_offset_csv_none_when_dir_empty(page):
    w, tmp_path = page
    (tmp_path / "drink_masks").mkdir()
    assert w._detect_offset_csv() is None


def test_detect_offset_csv_returns_first_csv(page):
    w, tmp_path = page
    d = tmp_path / "drink_masks"
    d.mkdir()
    (d / "offsets.csv").touch()
    (d / "zoo.csv").touch()
    result = w._detect_offset_csv()
    assert result == d / "offsets.csv"
