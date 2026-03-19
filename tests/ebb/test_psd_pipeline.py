import pickle
import numpy as np
import pytest
from pathlib import Path
from ebb.process.psd_compute import _animal_id, out_fraction, match_paths, build_final_pkl


#TO BE CHANGED LATER WHEN MORE FLEXIBILITY IS ADDED
def test_animal_id():
    assert _animal_id(Path("AM0185_6wk_whatever.edf")) == "AM0185"
    assert _animal_id(Path("CW0DA2_P096_KO_foo.csv")) == "CW0DA2"
    assert _animal_id(Path("XYZ123_something.edf")) == "XYZ123"
    assert _animal_id(Path("Mice-1234_tester.edf")) == "Mice-1234"
    assert _animal_id(Path("noidfile.edf")) == "noidfile"


def test_out_fraction_basic():
    mask = np.array([True, True, False, True])      # kept fraction = 0.75
    state = np.array([True, True, True, True])
    assert out_fraction(mask, state) == 0.25

def test_out_fraction_state():
    mask = np.array([True, True, False, True, False, True, True, False])
    state = np.array([False, True, True, True, True, True, False, False])
    # kept fraction in state = 3/5 = 0.6; out fraction = 0.4
    assert out_fraction(mask, state) == 0.4

def test_out_fraction_empty_state_is_nan():
    mask = np.array([True, False, True])
    state = np.array([False, False, False])
    assert np.isnan(out_fraction(mask, state))

def test_match_paths_drink_sparse():
    eeg = [Path("AM0001_x_PROCESSED.edf"), Path("AM0002_x_PROCESSED.edf")]
    st  = [Path("AM0001_states.csv"),      Path("AM0002_states.csv")]

    drink = [Path("AM0002_6wk_combined_predictions.npy")]  # only one exists

    paired = match_paths(eeg, st, swd_paths=None, drink_paths=drink)

    assert paired[0][0].name.startswith("AM0001")
    assert paired[0][1].name.startswith("AM0001")
    assert paired[1][0].name.startswith("AM0002")
    assert paired[1][1].name.startswith("AM0002")
    assert paired[0][3] is None                      # drink missing for AM0001
    assert paired[1][3] == drink[0]                  # drink present for AM0002
    assert paired[0][2] is None and paired[1][2] is None  # swd disabled

def test_match_paths_swd_required():
    eeg = [Path("AM0001_x_PROCESSED.edf"), Path("AM0002_x_PROCESSED.edf")]
    st  = [Path("AM0001_states.csv"),      Path("AM0002_states.csv")]
    swd = [Path("ts_AM0001.mat"),          Path("ts_AM0002.mat")]

    paired = match_paths(eeg, st, swd_paths=swd, drink_paths=None)
    assert paired[0][2] == swd[0]
    assert paired[1][2] == swd[1]

def test_match_paths_extra_eeg_raises():
    """match_paths raises when there are more EEG files than state CSVs.

    This documents the error that batch_estimate's pre-filtering is designed to
    prevent: if you pass all EDFs from standard/ but only a subset of state
    CSVs (e.g. a rerun combo), re_match raises ValueError.
    """
    eeg = [Path("AM0001_x_PROCESSED.edf"), Path("AM0002_x_PROCESSED.edf"),
           Path("AM0003_x_PROCESSED.edf")]
    st  = [Path("AM0001_states.csv"), Path("AM0002_states.csv")]  # AM0003 missing

    try:
        match_paths(eeg, st, swd_paths=None, drink_paths=None)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "Number of paths" in str(e)


def test_batch_estimate_filters_eeg_by_state_csv(tmp_path):
    """batch_estimate only processes EDFs that have a matching spindle CSV.

    Standard/ has 3 animals but the spindle output folder only has CSVs for 2.
    The missing animal should be silently skipped — no ValueError.
    """
    from unittest.mock import patch, MagicMock

    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    # 3 EDF stubs in standard/
    for aid in ("AM001", "AM002", "AM003"):
        (standard / f"{aid}_foo_PREPROCESSED.edf").touch()

    # Only 2 CSVs in spindle output (AM003 missing)
    for aid in ("AM001", "AM002"):
        (spindle_out / f"{aid}_states.csv").touch()

    captured = {}

    def fake_match_paths(eeg_paths, state_paths, swd_paths, drink_paths):
        captured["eeg_paths"] = list(eeg_paths)
        # Return empty list so batch_estimate has nothing to process
        return []

    with patch("ebb.process.psd_compute.match_paths", side_effect=fake_match_paths), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1):
        from ebb.process.psd_compute import batch_estimate
        batch_estimate(eeg_dir=standard, state_dir=spindle_out)

    eeg_animal_ids = {_animal_id(p) for p in captured["eeg_paths"]}
    assert eeg_animal_ids == {"AM001", "AM002"}
    assert "AM003" not in eeg_animal_ids


def test_match_paths_swd_missing_raises():
    eeg = [Path("AM0001_x_PROCESSED.edf"), Path("AM0002_x_PROCESSED.edf")]
    st  = [Path("AM0001_states.csv"),      Path("AM0002_states.csv")]
    swd = [Path("ts_AM0001.mat")]  # AM0002 missing

    try:
        match_paths(eeg, st, swd_paths=swd, drink_paths=None)
    except ValueError as e:
        assert "Number of paths in paths and others must match:" in str(e)


# ---------------------------------------------------------------------------
# build_final_pkl
# ---------------------------------------------------------------------------

def _make_psd_record(animal_id: str, combo: str) -> dict:
    """Minimal PSD record as produced by batch_estimate."""
    return {
        "path": str(Path(f"{animal_id}_foo_PREPROCESSED.edf")),
        "channels": (0, 1),
        "behavior": ("threshold", "wake"),
        "n_estimates": 10,
        "spindle_out_frac": 0.1,
        "comm_out_frac": 0.05,
        "sd_out_frac": 0.02,
        "swd_out_frac": 0.0,
        "used_swd": False,
        "used_drink": False,
        "freqs": [0.5, 1.0, 2.0],
        "psd": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
    }


def _write_combo_pkl(psd_dir: Path, combo: str, records: list) -> Path:
    psd_dir.mkdir(parents=True, exist_ok=True)
    p = psd_dir / f"psds_{combo}.pkl"
    with open(p, "wb") as f:
        pickle.dump(records, f)
    return p


class _FakeRun:
    def __init__(self, sleep_qc):
        self.sleep_qc = sleep_qc


class _FakeEntry:
    def __init__(self, animal_id, ok_combo):
        self.animal_id = animal_id
        self.runs = {ok_combo: _FakeRun("ok")} if ok_combo else {}


class _FakeManifest:
    def __init__(self, entries):
        self._entries = entries

    def __iter__(self):
        return iter(self._entries)


def test_build_final_pkl_basic(tmp_path):
    psd_dir = tmp_path / "psd"

    _write_combo_pkl(psd_dir, "LFC_RSC", [
        _make_psd_record("AM001", "LFC_RSC"),
        _make_psd_record("AM002", "LFC_RSC"),
    ])

    manifest = _FakeManifest([
        _FakeEntry("AM001", "LFC_RSC"),
        _FakeEntry("AM002", "LFC_RSC"),
    ])

    out = build_final_pkl(tmp_path, manifest)
    assert out == psd_dir / "psds_final.pkl"
    assert out.exists()

    with open(out, "rb") as f:
        records = pickle.load(f)

    assert len(records) == 2
    animal_ids = {Path(r["path"]).stem.split("_")[0] for r in records}
    assert animal_ids == {"AM001", "AM002"}
    for r in records:
        assert r["source_combo"] == "LFC_RSC"


def test_build_final_pkl_filters_to_ok_combo(tmp_path):
    """Only animals with ok sleep_qc are included."""
    psd_dir = tmp_path / "psd"

    _write_combo_pkl(psd_dir, "LFC_RSC", [
        _make_psd_record("AM001", "LFC_RSC"),
        _make_psd_record("AM002", "LFC_RSC"),
    ])

    # AM002 has no ok combo
    manifest = _FakeManifest([
        _FakeEntry("AM001", "LFC_RSC"),
        _FakeEntry("AM002", None),
    ])

    out = build_final_pkl(tmp_path, manifest)
    with open(out, "rb") as f:
        records = pickle.load(f)

    assert len(records) == 1
    assert Path(records[0]["path"]).stem.split("_")[0] == "AM001"


def test_build_final_pkl_multiple_combos(tmp_path):
    """Animals from different ok combos are consolidated."""
    psd_dir = tmp_path / "psd"

    _write_combo_pkl(psd_dir, "LFC_RSC", [_make_psd_record("AM001", "LFC_RSC")])
    _write_combo_pkl(psd_dir, "LSC_RSC", [_make_psd_record("AM002", "LSC_RSC")])

    manifest = _FakeManifest([
        _FakeEntry("AM001", "LFC_RSC"),
        _FakeEntry("AM002", "LSC_RSC"),
    ])

    out = build_final_pkl(tmp_path, manifest)
    with open(out, "rb") as f:
        records = pickle.load(f)

    assert len(records) == 2
    by_animal = {Path(r["path"]).stem.split("_")[0]: r for r in records}
    assert by_animal["AM001"]["source_combo"] == "LFC_RSC"
    assert by_animal["AM002"]["source_combo"] == "LSC_RSC"


def test_build_final_pkl_missing_combo_pkl_warns(tmp_path):
    """Missing per-combo PKL emits a warning and skips that combo."""
    manifest = _FakeManifest([_FakeEntry("AM001", "LFC_RSC")])

    with pytest.warns(UserWarning, match="PKL not found"):
        out = build_final_pkl(tmp_path, manifest)

    with open(out, "rb") as f:
        records = pickle.load(f)
    assert records == []

