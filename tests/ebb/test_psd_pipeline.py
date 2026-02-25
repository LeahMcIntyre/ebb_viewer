import numpy as np
from pathlib import Path
from ebb.process.psd_compute import _animal_id, out_fraction, match_paths


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

def test_match_paths_swd_missing_raises():
    eeg = [Path("AM0001_x_PROCESSED.edf"), Path("AM0002_x_PROCESSED.edf")]
    st  = [Path("AM0001_states.csv"),      Path("AM0002_states.csv")]
    swd = [Path("ts_AM0001.mat")]  # AM0002 missing

    try:
        match_paths(eeg, st, swd_paths=swd, drink_paths=None)
    except ValueError as e:
        assert "Number of paths in paths and others must match:" in str(e)
   
