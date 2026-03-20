"""Tests for drink-mask integration in PSD computation.

Covers:
- batch_estimate passes offset_path through to estimate_psd via kwargs
- batch_estimate passes drink_dir through correctly
- rerun_with_drink_masks validates source_combo, writes psds_drink.pkl,
  regenerates psds_final_drink.pkl, never touches psds_final.pkl
- rerun_with_drink_masks raises when psds_final.pkl missing or combo mismatches
- rerun_with_drink_masks raises when no EDF files found for target animals
- DrinkMaskRerunWorker.run calls rerun_with_drink_masks with correct args
- BatchEstimateWorker.run passes drink_dir and offset_path to batch_estimate
- PSDPage._drink_masks_dir returns project_root/drink_masks
- PSDPage._detect_offset_csv finds first CSV or returns None
- PSDPage._refresh_drink_mask_info updates labels correctly
- PSDPage._validate enables btn_drink_mask when rerun needed
- PSDPage._on_drink_mask_done flags manifest and emits manifest_changed
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
        # Return a callable that does nothing
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
    """rerun_with_drink_masks writes psds_drink.pkl and psds_final_drink.pkl;
    psds_final.pkl is not modified."""
    standard, spindle_out, drink_dir, psd_dir = _setup_rerun_dirs(tmp_path)

    # psds_final.pkl has both animals; AM002 is the target
    final_records = [_make_psd_record("AM001"), _make_psd_record("AM002")]
    _write_pkl(psd_dir / "psds_final.pkl", final_records)

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

    # psds_final.pkl is untouched
    with open(psd_dir / "psds_final.pkl", "rb") as f:
        final = pickle.load(f)
    assert [Path(r["path"]).stem.split("_")[0] for r in final] == ["AM001", "AM002"]

    # psds_drink.pkl contains only AM002
    with open(drink_pkl, "rb") as f:
        drink = pickle.load(f)
    assert [Path(r["path"]).stem.split("_")[0] for r in drink] == ["AM002"]

    # psds_final_drink.pkl has AM001 (from final) + AM002 (from drink)
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
    _write_pkl(psd_dir / "psds_final.pkl", final_records)

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
    """FileNotFoundError raised when psds_final.pkl does not exist."""
    standard, _, drink_dir, psd_dir = _setup_rerun_dirs(tmp_path)

    from ebb.process.psd_compute import rerun_with_drink_masks
    with pytest.raises(FileNotFoundError, match="psds_final.pkl"):
        rerun_with_drink_masks(
            psd_dir=psd_dir,
            eeg_dir=standard,
            spindle_root=tmp_path / "spindle_outputs",
            drink_dir=drink_dir,
            animal_combos={"AM001": "LFC_RSC"},
        )


def test_rerun_raises_on_combo_mismatch(tmp_path):
    """ValueError raised when source_combo in psds_final.pkl differs from manifest combo."""
    standard, _, drink_dir, psd_dir = _setup_rerun_dirs(tmp_path)
    # AM001 is stored under LFC_RSC in psds_final.pkl
    _write_pkl(psd_dir / "psds_final.pkl", [_make_psd_record("AM001", combo="LFC_RSC")])

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
    _write_pkl(psd_dir / "psds_final.pkl", [_make_psd_record("AM001")])

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

def test_batch_estimate_worker_passes_drink_dir_and_offset(tmp_path):
    """Worker passes drink_dir and offset_path to batch_estimate."""
    drink_dir = tmp_path / "drink_masks"
    offset_csv = drink_dir / "offsets.csv"
    pairs = [(tmp_path / "spindle_out", tmp_path / "out.pkl")]

    captured = {}

    def fake_batch_estimate(**kwargs):
        captured.update(kwargs)
        return []

    with patch("ebb.process.psd_compute.batch_estimate", side_effect=fake_batch_estimate):
        from ebb_viewer.pages.psds import BatchEstimateWorker
        worker = BatchEstimateWorker(
            eeg_dir=tmp_path / "standard",
            combo_pairs=pairs,
            params={"fs": 250, "channels": [0, 1]},
            drink_dir=drink_dir,
            offset_path=offset_csv,
        )
        # Patch batch_estimate at the import location used by the worker
        with patch("ebb.process.psd_compute.batch_estimate") as mock_be:
            mock_be.return_value = []
            # simulate the import inside run()
            import ebb.process.psd_compute as psd_mod
            orig = psd_mod.batch_estimate

            calls = []

            def recording_be(**kw):
                calls.append(kw)
                return []

            psd_mod.batch_estimate = recording_be
            try:
                worker.run()
            finally:
                psd_mod.batch_estimate = orig

    assert len(calls) == 1
    assert calls[0]["drink_dir"] == drink_dir
    assert calls[0]["offset_path"] == offset_csv


def test_batch_estimate_worker_none_drink_dir(tmp_path):
    """Worker passes drink_dir=None when not provided."""
    pairs = [(tmp_path / "spindle_out", tmp_path / "out.pkl")]

    import ebb.process.psd_compute as psd_mod
    orig = psd_mod.batch_estimate
    calls = []

    def recording_be(**kw):
        calls.append(kw)
        return []

    psd_mod.batch_estimate = recording_be
    try:
        from ebb_viewer.pages.psds import BatchEstimateWorker
        worker = BatchEstimateWorker(
            eeg_dir=tmp_path / "standard",
            combo_pairs=pairs,
            params={"fs": 250, "channels": [0, 1]},
        )
        worker.run()
    finally:
        psd_mod.batch_estimate = orig

    assert calls[0]["drink_dir"] is None
    assert calls[0]["offset_path"] is None


# ---------------------------------------------------------------------------
# DrinkMaskRerunWorker
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
        from ebb_viewer.pages.psds import DrinkMaskRerunWorker
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
        from ebb_viewer.pages.psds import DrinkMaskRerunWorker
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
        from ebb_viewer.pages.psds import DrinkMaskRerunWorker
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
    # Allow running headless if a virtual display is available
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    return app


@pytest.fixture()
def page(tmp_path, qapp):
    """Construct a PSDPage against a bare tmp_path project root."""
    from ebb_viewer.pages.psds import PSDPage
    w = PSDPage(project_root=tmp_path)
    yield w, tmp_path
    w.close()


# ---------------------------------------------------------------------------
# PSDPage helpers
# ---------------------------------------------------------------------------

def test_drink_masks_dir(page):
    w, tmp_path = page
    assert w._drink_masks_dir() == tmp_path / "drink_masks"


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


def test_refresh_drink_mask_info_no_dir(page):
    w, _ = page
    w._refresh_drink_mask_info()
    assert "Not found" in w.lbl_drink_dir.text()
    assert w.lbl_offset_csv.text() == "None"


def test_refresh_drink_mask_info_with_masks(page):
    w, tmp_path = page
    d = tmp_path / "drink_masks"
    d.mkdir()
    (d / "AM001.npy").touch()
    (d / "AM002.npy").touch()
    w._refresh_drink_mask_info()
    assert str(d) in w.lbl_drink_dir.text()
    assert "2 masks" in w._lbl_drink_count.text()
    assert w.lbl_offset_csv.text() == "None"


def test_refresh_drink_mask_info_single_mask(page):
    w, tmp_path = page
    d = tmp_path / "drink_masks"
    d.mkdir()
    (d / "AM001.npy").touch()
    w._refresh_drink_mask_info()
    assert "1 mask" in w._lbl_drink_count.text()


def test_refresh_drink_mask_info_with_csv(page):
    w, tmp_path = page
    d = tmp_path / "drink_masks"
    d.mkdir()
    (d / "AM001.npy").touch()
    (d / "offsets.csv").touch()
    w._refresh_drink_mask_info()
    assert w.lbl_offset_csv.text() == "offsets.csv"


def test_refresh_drink_mask_info_dir_exists_no_npys(page):
    w, tmp_path = page
    d = tmp_path / "drink_masks"
    d.mkdir()
    w._refresh_drink_mask_info()
    assert "no .npy files" in w._lbl_drink_count.text()


# ---------------------------------------------------------------------------
# PSDPage._validate: drink mask button state
# ---------------------------------------------------------------------------

def _make_manifest_json(tmp_path: Path, animal_id: str, combo: str,
                         psd_status: str, has_npy: bool) -> None:
    """Write a minimal manifest.json and optionally the .npy file."""
    if has_npy:
        d = tmp_path / "drink_masks"
        d.mkdir(exist_ok=True)
        (d / f"{animal_id}.npy").touch()

    import json
    data = {
        animal_id: {
            "animal_id": animal_id,
            "preprocessed_edf": f"standard/{animal_id}_PREPROCESSED.edf",
            "runs": {
                combo: {
                    "sleep_qc": "ok",
                    "rerun_combo": None,
                    "psd_status": psd_status,
                    "drink_mask": None,
                    "rejected_by": None,
                    "source_combo": None,
                }
            },
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(data))


def test_validate_drink_button_enabled_when_flagged(tmp_path, qapp):
    """btn_drink_mask enabled when animal is needs_drink_mask and .npy present."""
    _make_manifest_json(tmp_path, "AM001", "LFC_RSC", "needs_drink_mask", has_npy=True)

    from ebb_viewer.pages.psds import PSDPage
    w = PSDPage(project_root=tmp_path)
    w._validate()
    assert w.btn_drink_mask.isEnabled()
    w.close()


def test_validate_drink_button_disabled_without_npy(tmp_path, qapp):
    """btn_drink_mask stays disabled when .npy is missing even if flagged."""
    _make_manifest_json(tmp_path, "AM001", "LFC_RSC", "needs_drink_mask", has_npy=False)

    from ebb_viewer.pages.psds import PSDPage
    w = PSDPage(project_root=tmp_path)
    w._validate()
    assert not w.btn_drink_mask.isEnabled()
    w.close()


def test_validate_drink_button_disabled_when_psd_ok(tmp_path, qapp):
    """btn_drink_mask disabled when psd_status is 'ok' (nothing to rerun)."""
    _make_manifest_json(tmp_path, "AM001", "LFC_RSC", "ok", has_npy=True)

    from ebb_viewer.pages.psds import PSDPage
    w = PSDPage(project_root=tmp_path)
    w._validate()
    assert not w.btn_drink_mask.isEnabled()
    w.close()


# ---------------------------------------------------------------------------
# PSDPage._on_drink_mask_done: manifest update
# ---------------------------------------------------------------------------

def test_on_drink_mask_done_flags_manifest(tmp_path, qapp):
    """_on_drink_mask_done calls flag_psd(drink_mask_applied) and saves."""
    _make_manifest_json(tmp_path, "AM001", "LFC_RSC", "needs_drink_mask", has_npy=True)

    from ebb_viewer.pages.psds import PSDPage
    from ebb_viewer.pipeline.manifest import Manifest

    w = PSDPage(project_root=tmp_path)
    w._computing = True
    w._pending_drink_rerun = {"AM001": "LFC_RSC"}

    emitted = []
    w.manifest_changed.connect(lambda: emitted.append(True))

    w._on_drink_mask_done()

    assert not w._computing
    assert w._pending_drink_rerun == {}
    assert emitted  # manifest_changed was emitted

    m = Manifest.load(tmp_path)
    entry = m.get("AM001")
    assert entry.runs["LFC_RSC"].psd_status == "drink_mask_applied"
    assert entry.runs["LFC_RSC"].drink_mask == "drink_masks/AM001.npy"
    w.close()


def test_on_drink_mask_done_skips_missing_runs(tmp_path, qapp):
    """_on_drink_mask_done silently ignores animals/combos not in manifest."""
    _make_manifest_json(tmp_path, "AM001", "LFC_RSC", "needs_drink_mask", has_npy=True)

    from ebb_viewer.pages.psds import PSDPage
    w = PSDPage(project_root=tmp_path)
    w._computing = True
    # Include an animal/combo that doesn't exist — should not raise
    w._pending_drink_rerun = {"AM001": "LFC_RSC", "AM999": "BOGUS_COMBO"}

    w._on_drink_mask_done()  # must not raise

    assert w._pending_drink_rerun == {}
    w.close()
