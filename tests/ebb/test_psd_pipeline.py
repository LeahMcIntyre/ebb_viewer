import pickle
from pathlib import Path

import numpy as np
import pytest

from ebb.core.naming import parse_animal_id
from ebb.process.psd_compute import build_run_final_pkl, match_paths, out_fraction

# Direct test cases for parse_animal_id moved to tests/ebb/test_naming.py.


def test_out_fraction_basic():
    mask = np.array([True, True, False, True])  # kept fraction = 0.75
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
    st = [Path("AM0001_states.csv"), Path("AM0002_states.csv")]

    drink = [Path("AM0002_6wk_combined_predictions.npy")]  # only one exists

    paired = match_paths(eeg, st, swd_paths=None, drink_paths=drink)

    assert paired[0][0].name.startswith("AM0001")
    assert paired[0][1].name.startswith("AM0001")
    assert paired[1][0].name.startswith("AM0002")
    assert paired[1][1].name.startswith("AM0002")
    assert paired[0][3] is None  # drink missing for AM0001
    assert paired[1][3] == drink[0]  # drink present for AM0002
    assert paired[0][2] is None and paired[1][2] is None  # swd disabled


def test_match_paths_swd_required():
    eeg = [Path("AM0001_x_PROCESSED.edf"), Path("AM0002_x_PROCESSED.edf")]
    st = [Path("AM0001_states.csv"), Path("AM0002_states.csv")]
    swd = [Path("ts_AM0001.mat"), Path("ts_AM0002.mat")]

    paired = match_paths(eeg, st, swd_paths=swd, drink_paths=None)
    assert paired[0][2] == swd[0]
    assert paired[1][2] == swd[1]


def test_match_paths_extra_eeg_raises():
    """match_paths raises when there are more EEG files than state CSVs.

    This documents the error that batch_estimate's pre-filtering is designed to
    prevent: if you pass all EDFs from standard/ but only a subset of state
    CSVs, re_match raises ValueError.
    """
    eeg = [
        Path("AM0001_x_PROCESSED.edf"),
        Path("AM0002_x_PROCESSED.edf"),
        Path("AM0003_x_PROCESSED.edf"),
    ]
    st = [Path("AM0001_states.csv"), Path("AM0002_states.csv")]  # AM0003 missing

    try:
        match_paths(eeg, st, swd_paths=None, drink_paths=None)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "Number of paths" in str(e)


def test_match_paths_does_not_pair_an_id_with_a_longer_id():
    """GF1192 and GF1192m are different animals; neither may claim the other's files."""
    eeg = [Path("GF1192_x_PROCESSED.edf"), Path("GF1192m_x_PROCESSED.edf")]
    st = [Path("GF1192m_x_labels.csv"), Path("GF1192_x_labels.csv")]
    swd = [Path("GF1192m_ts.mat"), Path("GF1192_ts.mat")]

    paired = match_paths(eeg, st, swd_paths=swd, drink_paths=None)

    assert paired[0][1] == st[1] and paired[0][2] == swd[1]
    assert paired[1][1] == st[0] and paired[1][2] == swd[0]


def test_batch_estimate_filters_eeg_by_state_csv(tmp_path):
    """batch_estimate only processes EDFs that have a matching spindle CSV.

    Standard/ has 3 animals but the spindle output folder only has CSVs for 2.
    The missing animal should be silently skipped — no ValueError.
    """
    from unittest.mock import patch

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

    with (
        patch("ebb.process.psd_compute.match_paths", side_effect=fake_match_paths),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
    ):
        from ebb.process.psd_compute import batch_estimate

        batch_estimate(eeg_dir=standard, state_dir=spindle_out)

    eeg_animal_ids = {parse_animal_id(p) for p in captured["eeg_paths"]}
    assert eeg_animal_ids == {"AM001", "AM002"}
    assert "AM003" not in eeg_animal_ids


def test_match_paths_swd_missing_raises():
    eeg = [Path("AM0001_x_PROCESSED.edf"), Path("AM0002_x_PROCESSED.edf")]
    st = [Path("AM0001_states.csv"), Path("AM0002_states.csv")]
    swd = [Path("ts_AM0001.mat")]  # AM0002 missing

    try:
        match_paths(eeg, st, swd_paths=swd, drink_paths=None)
    except ValueError as e:
        assert "Number of paths in paths and others must match:" in str(e)


# ---------------------------------------------------------------------------
# build_run_final_pkl
# ---------------------------------------------------------------------------


def _write_pkl(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(records, f)


def test_build_run_final_pkl_uses_base_when_no_drink(tmp_path):
    psd_dir = tmp_path / "psd" / "default"
    _write_pkl(psd_dir / "psds_LFC_RSC.pkl", ["base"])

    out = build_run_final_pkl(tmp_path, "LFC_RSC")

    assert out == psd_dir / "psds_final.pkl"
    with open(out, "rb") as f:
        assert pickle.load(f) == ["base"]


def test_build_run_final_pkl_prefers_drink_overlay(tmp_path):
    psd_dir = tmp_path / "psd" / "default"
    _write_pkl(psd_dir / "psds_LFC_RSC.pkl", ["base"])
    _write_pkl(psd_dir / "psds_LFC_RSC_drink.pkl", ["drink"])

    out = build_run_final_pkl(tmp_path, "LFC_RSC")

    with open(out, "rb") as f:
        assert pickle.load(f) == ["drink"]


def test_build_run_final_pkl_raises_when_nothing_computed(tmp_path):
    with pytest.raises(FileNotFoundError, match="Compute PSDs"):
        build_run_final_pkl(tmp_path, "LFC_RSC")


# ---------------------------------------------------------------------------
# batch_estimate: annotation mask params
# ---------------------------------------------------------------------------


def test_batch_estimate_injects_ann_kwargs(tmp_path):
    """ann_params keywords, match mode, and padding are injected into the estimator partial."""
    from unittest.mock import patch

    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)
    ann_dir = tmp_path / "annotations"
    ann_dir.mkdir()

    captured_kwargs = {}

    def fake_partial(fn, **kwargs):
        captured_kwargs.update(kwargs)
        return lambda *a: []

    with (
        patch("ebb.process.psd_compute.match_paths", return_value=[]),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
        patch("ebb.process.psd_compute.partial", side_effect=fake_partial),
    ):
        from ebb.process.psd_compute import batch_estimate

        batch_estimate(
            eeg_dir=standard,
            state_dir=spindle_out,
            ann_params={
                "ann_dir": ann_dir,
                "keywords": ["artifact", "noise"],
                "match_mode": "contains",
                "pad_before_sec": 1.0,
                "pad_after_sec": 2.0,
            },
        )

    assert captured_kwargs["ann_keywords"] == ["artifact", "noise"]
    assert captured_kwargs["ann_match_mode"] == "contains"
    assert captured_kwargs["ann_pad_before_sec"] == 1.0
    assert captured_kwargs["ann_pad_after_sec"] == 2.0


def test_batch_estimate_no_ann_kwargs_when_ann_params_none(tmp_path):
    """When ann_params is None, no annotation kwargs reach the estimator."""
    from unittest.mock import patch

    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    captured_kwargs = {}

    def fake_partial(fn, **kwargs):
        captured_kwargs.update(kwargs)
        return lambda *a: []

    with (
        patch("ebb.process.psd_compute.match_paths", return_value=[]),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
        patch("ebb.process.psd_compute.partial", side_effect=fake_partial),
    ):
        from ebb.process.psd_compute import batch_estimate

        batch_estimate(eeg_dir=standard, state_dir=spindle_out)

    assert "ann_keywords" not in captured_kwargs
    assert "ann_match_mode" not in captured_kwargs


def test_batch_estimate_extends_pairs_with_annotation_paths(tmp_path):
    """Each paired tuple has the matching annotation file as a 5th element;
    animals without a file get None."""
    from unittest.mock import patch

    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)
    ann_dir = tmp_path / "annotations"
    ann_dir.mkdir()

    edf_a = standard / "AM001_foo_PREPROCESSED.edf"
    edf_b = standard / "AM002_foo_PREPROCESSED.edf"
    edf_a.touch()
    edf_b.touch()
    (spindle_out / "AM001_states.csv").touch()
    (spindle_out / "AM002_states.csv").touch()

    # Only AM001 has an annotation file
    ann_file = ann_dir / "AM001_events.txt"
    ann_file.touch()

    called_with = []

    def fake_estimate_psd(*args, **kwargs):
        called_with.append(args)
        return []

    base_pairs = [
        (edf_a, spindle_out / "AM001_states.csv", None, None),
        (edf_b, spindle_out / "AM002_states.csv", None, None),
    ]

    with (
        patch("ebb.process.psd_compute.match_paths", return_value=base_pairs),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
        patch("ebb.process.psd_compute.estimate_psd", side_effect=fake_estimate_psd),
    ):
        from ebb.process.psd_compute import batch_estimate

        batch_estimate(
            eeg_dir=standard,
            state_dir=spindle_out,
            ann_params={
                "ann_dir": ann_dir,
                "keywords": ["event"],
                "match_mode": "contains",
                "pad_before_sec": 0.0,
                "pad_after_sec": 0.0,
            },
        )

    am001_args = next(a for a in called_with if "AM001" in str(a[0]))
    am002_args = next(a for a in called_with if "AM002" in str(a[0]))
    assert am001_args[4] == ann_file
    assert am002_args[4] is None
