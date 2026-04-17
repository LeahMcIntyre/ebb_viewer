"""Tests for state-selection flow in psd_compute.

Covers:
- batch_estimate translates the ``states`` kwarg into a ``labels`` dict that
  reaches estimate_psd via functools.partial
- an explicit ``labels`` kwarg wins over ``states``
- when neither is supplied, estimate_psd's default label dict is used
- ``states`` never leaks to estimate_psd as an unknown kwarg
- rerun_with_drink_masks performs the same translation
"""

from pathlib import Path
from unittest.mock import patch

import pickle
import pytest


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
        "used_swd": False,
        "used_drink": True,
        "freqs": [0.5, 1.0],
        "psd": [[1.0, 2.0], [3.0, 4.0]],
    }


def _capture_partial_kwargs():
    captured: dict = {}

    def fake_partial(fn, **kwargs):
        captured.update(kwargs)
        return lambda *a: []

    return captured, fake_partial


# ---------------------------------------------------------------------------
# batch_estimate
# ---------------------------------------------------------------------------

def test_batch_estimate_translates_states_to_labels(tmp_path):
    standard = tmp_path / "standard"; standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    captured, fake_partial = _capture_partial_kwargs()

    with patch("ebb.process.psd_compute.match_paths", return_value=[]), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1), \
         patch("ebb.process.psd_compute.partial", side_effect=fake_partial):
        from ebb.process.psd_compute import batch_estimate
        batch_estimate(
            eeg_dir=standard,
            state_dir=spindle_out,
            states=["wake", "sleep"],
        )

    # labels injected, states stripped
    assert captured["labels"] == {"wake": ["w"], "sleep": ["n", "r"]}
    assert "states" not in captured


def test_batch_estimate_explicit_labels_wins_over_states(tmp_path):
    standard = tmp_path / "standard"; standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    captured, fake_partial = _capture_partial_kwargs()
    custom_labels = {"my_state": ["n"]}

    with patch("ebb.process.psd_compute.match_paths", return_value=[]), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1), \
         patch("ebb.process.psd_compute.partial", side_effect=fake_partial):
        from ebb.process.psd_compute import batch_estimate
        batch_estimate(
            eeg_dir=standard,
            state_dir=spindle_out,
            states=["wake"],
            labels=custom_labels,
        )

    assert captured["labels"] == custom_labels


def test_batch_estimate_no_states_no_labels_injected(tmp_path):
    """Without states= or labels=, estimate_psd's default applies — partial
    gets no labels kwarg."""
    standard = tmp_path / "standard"; standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    captured, fake_partial = _capture_partial_kwargs()

    with patch("ebb.process.psd_compute.match_paths", return_value=[]), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1), \
         patch("ebb.process.psd_compute.partial", side_effect=fake_partial):
        from ebb.process.psd_compute import batch_estimate
        batch_estimate(eeg_dir=standard, state_dir=spindle_out)

    assert "labels" not in captured
    assert "states" not in captured


def test_batch_estimate_unknown_state_raises(tmp_path):
    standard = tmp_path / "standard"; standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    with patch("ebb.process.psd_compute.match_paths", return_value=[]), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1):
        from ebb.process.psd_compute import batch_estimate
        with pytest.raises(KeyError):
            batch_estimate(
                eeg_dir=standard,
                state_dir=spindle_out,
                states=["wake", "not_a_state"],
            )


def test_batch_estimate_single_lumped_state(tmp_path):
    standard = tmp_path / "standard"; standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    captured, fake_partial = _capture_partial_kwargs()

    with patch("ebb.process.psd_compute.match_paths", return_value=[]), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1), \
         patch("ebb.process.psd_compute.partial", side_effect=fake_partial):
        from ebb.process.psd_compute import batch_estimate
        batch_estimate(
            eeg_dir=standard,
            state_dir=spindle_out,
            states=["all"],
        )

    assert captured["labels"] == {"all": ["w", "n", "r"]}


# ---------------------------------------------------------------------------
# rerun_with_drink_masks
# ---------------------------------------------------------------------------

def _setup_drink_rerun_dirs(tmp_path):
    """Minimal scaffolding for rerun_with_drink_masks to reach the partial() call."""
    eeg_dir = tmp_path / "standard"; eeg_dir.mkdir()
    spindle_root = tmp_path / "spindle_outputs"
    drink_dir = tmp_path / "drink_masks"; drink_dir.mkdir()
    psd_dir = tmp_path / "psd" / "default"; psd_dir.mkdir(parents=True)

    combo_dir = spindle_root / "LFC_RSC"; combo_dir.mkdir(parents=True)
    (eeg_dir / "AM001_foo_PREPROCESSED.edf").touch()
    (combo_dir / "AM001_states.csv").touch()
    (drink_dir / "AM001_drink.npy").touch()

    # psds_channel_merged.pkl — source_combo matches
    with open(psd_dir / "psds_channel_merged.pkl", "wb") as f:
        pickle.dump([_make_psd_record("AM001")], f)

    return dict(
        psd_dir=tmp_path / "psd",
        eeg_dir=eeg_dir,
        spindle_root=spindle_root,
        drink_dir=drink_dir,
    )


def test_rerun_with_drink_masks_translates_states_to_labels(tmp_path):
    dirs = _setup_drink_rerun_dirs(tmp_path)
    captured, fake_partial = _capture_partial_kwargs()

    with patch("ebb.process.psd_compute.match_paths", return_value=[]), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1), \
         patch("ebb.process.psd_compute.partial", side_effect=fake_partial):
        from ebb.process.psd_compute import rerun_with_drink_masks
        rerun_with_drink_masks(
            **dirs,
            animal_combos={"AM001": "LFC_RSC"},
            run_name="default",
            states=["wake", "nrem"],
        )

    assert captured["labels"] == {"wake": ["w"], "nrem": ["n"]}
    assert "states" not in captured


def test_rerun_with_drink_masks_no_states_no_labels(tmp_path):
    dirs = _setup_drink_rerun_dirs(tmp_path)
    captured, fake_partial = _capture_partial_kwargs()

    with patch("ebb.process.psd_compute.match_paths", return_value=[]), \
         patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1), \
         patch("ebb.process.psd_compute.partial", side_effect=fake_partial):
        from ebb.process.psd_compute import rerun_with_drink_masks
        rerun_with_drink_masks(
            **dirs,
            animal_combos={"AM001": "LFC_RSC"},
            run_name="default",
        )

    assert "labels" not in captured
    assert "states" not in captured
