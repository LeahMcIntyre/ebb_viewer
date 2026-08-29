"""Tests for state-selection flow in psd_compute.

Covers:
- batch_estimate translates the ``states`` kwarg into a ``labels`` dict that
  reaches estimate_psd via functools.partial
- an explicit ``labels`` kwarg wins over ``states``
- when neither is supplied, estimate_psd's default label dict is used
- ``states`` never leaks to estimate_psd as an unknown kwarg
- rerun_with_drink_masks performs the same translation
- estimate_psd gates the SD threshold mask to wake samples, even when wake
  is lumped into a multi-state group (e.g. the "all" preset).
"""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
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
    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    captured, fake_partial = _capture_partial_kwargs()

    with (
        patch("ebb.process.psd_compute.match_paths", return_value=[]),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
        patch("ebb.process.psd_compute.partial", side_effect=fake_partial),
    ):
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
    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    captured, fake_partial = _capture_partial_kwargs()
    custom_labels = {"my_state": ["n"]}

    with (
        patch("ebb.process.psd_compute.match_paths", return_value=[]),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
        patch("ebb.process.psd_compute.partial", side_effect=fake_partial),
    ):
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
    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    captured, fake_partial = _capture_partial_kwargs()

    with (
        patch("ebb.process.psd_compute.match_paths", return_value=[]),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
        patch("ebb.process.psd_compute.partial", side_effect=fake_partial),
    ):
        from ebb.process.psd_compute import batch_estimate

        batch_estimate(eeg_dir=standard, state_dir=spindle_out)

    assert "labels" not in captured
    assert "states" not in captured


def test_batch_estimate_unknown_state_raises(tmp_path):
    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    with (
        patch("ebb.process.psd_compute.match_paths", return_value=[]),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
    ):
        from ebb.process.psd_compute import batch_estimate

        with pytest.raises(KeyError):
            batch_estimate(
                eeg_dir=standard,
                state_dir=spindle_out,
                states=["wake", "not_a_state"],
            )


def test_estimate_psd_raises_on_fs_mismatch():
    """estimate_psd must abort if the user-supplied fs disagrees with the
    EDF header — otherwise mask windows silently use the wrong sample count."""
    from ebb.process import psd_compute

    reader = MagicMock()
    reader.__enter__ = MagicMock(return_value=reader)
    reader.__exit__ = MagicMock(return_value=False)
    reader.header.samples_per_record = [250, 250, 250, 250]  # file is 250 Hz

    with patch.object(psd_compute.edf, "Reader", return_value=reader):
        with pytest.raises(ValueError, match=r"file is 250 Hz but caller passed fs=500"):
            psd_compute.estimate_psd(
                path=Path("AM001_PREPROCESSED.edf"),
                state_path=Path("AM001_states.csv"),
                fs=500,  # user typed the wrong value
                verbose=False,
            )


def test_batch_estimate_empty_paired_skips_savepath_write(tmp_path):
    """When match_paths yields nothing, batch_estimate must not write the
    savepath — silently pickling an empty list there causes downstream
    build_final_pkl to skip the combo with no clue why."""
    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)
    savepath = tmp_path / "psds_LFC_RSC.pkl"

    _, fake_partial = _capture_partial_kwargs()

    with (
        patch("ebb.process.psd_compute.match_paths", return_value=[]),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
        patch("ebb.process.psd_compute.partial", side_effect=fake_partial),
    ):
        from ebb.process.psd_compute import batch_estimate

        with pytest.warns(UserWarning, match="no EDF files"):
            results = batch_estimate(
                eeg_dir=standard,
                state_dir=spindle_out,
                savepath=savepath,
            )

    assert results == []
    assert not savepath.exists()


def test_batch_estimate_single_lumped_state(tmp_path):
    standard = tmp_path / "standard"
    standard.mkdir()
    spindle_out = tmp_path / "spindle_outputs" / "LFC_RSC"
    spindle_out.mkdir(parents=True)

    captured, fake_partial = _capture_partial_kwargs()

    with (
        patch("ebb.process.psd_compute.match_paths", return_value=[]),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
        patch("ebb.process.psd_compute.partial", side_effect=fake_partial),
    ):
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
    eeg_dir = tmp_path / "standard"
    eeg_dir.mkdir()
    spindle_root = tmp_path / "spindle_outputs"
    drink_dir = tmp_path / "drink_masks"
    drink_dir.mkdir()
    psd_dir = tmp_path / "psd" / "default"
    psd_dir.mkdir(parents=True)

    combo_dir = spindle_root / "LFC_RSC"
    combo_dir.mkdir(parents=True)
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

    with (
        patch("ebb.process.psd_compute.match_paths", return_value=[]),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
        patch("ebb.process.psd_compute.partial", side_effect=fake_partial),
    ):
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

    with (
        patch("ebb.process.psd_compute.match_paths", return_value=[]),
        patch("ebb.process.psd_compute.concurrency.set_cores", return_value=1),
        patch("ebb.process.psd_compute.partial", side_effect=fake_partial),
    ):
        from ebb.process.psd_compute import rerun_with_drink_masks

        rerun_with_drink_masks(
            **dirs,
            animal_combos={"AM001": "LFC_RSC"},
            run_name="default",
        )

    assert "labels" not in captured
    assert "states" not in captured


# ---------------------------------------------------------------------------
# estimate_psd: SD threshold is gated to wake samples within any group
# ---------------------------------------------------------------------------


def _run_estimate_psd(labels, wake, nrem, rem, sd):
    """Invoke estimate_psd with all heavy deps mocked.

    Returns (results, captured) where captured["producer_calls"] is the list
    of mask arrays passed to the masked producer (one per PSD computed, in
    label order) and captured["state_calls"] is the ordered list of code
    tuples passed to masking.state.
    """
    from ebb.process import psd_compute

    n = len(sd)
    captured = {"producer_calls": [], "state_calls": []}
    single = {"w": wake, "n": nrem, "r": rem}

    def fake_state(state_path, code, fs, winsize):
        captured["state_calls"].append(tuple(code))
        out = np.zeros(n, dtype=bool)
        for c in code:
            out |= single[c]
        return out

    def fake_producer(*args, **kwargs):
        if "mask" in kwargs:
            captured["producer_calls"].append(kwargs["mask"].copy())
        m = MagicMock()
        m.shape = (n,)
        return m

    reader = MagicMock()
    reader.__enter__ = MagicMock(return_value=reader)
    reader.__exit__ = MagicMock(return_value=False)
    reader.channels = []
    reader.shape = (3, n)
    # assert_fs_matches reads samples_per_record[0]; set it so the
    # mismatch guard passes for the fs=10 call below.
    reader.header.samples_per_record = [10, 10, 10, 10]

    notch_instance = MagicMock(side_effect=lambda pro_arg, *a, **kw: pro_arg)

    with (
        patch.object(psd_compute.edf, "Reader", return_value=reader),
        patch.object(psd_compute, "producer", side_effect=fake_producer),
        patch.object(psd_compute.masking, "state", side_effect=fake_state),
        patch.object(
            psd_compute.masking, "commutator_threshold", return_value=(np.ones(n, dtype=bool),)
        ),
        patch.object(psd_compute.masking, "spindle_noise", return_value=np.ones(n, dtype=bool)),
        patch.object(psd_compute.masking, "sd_threshold", return_value=(sd.copy(),)),
        patch.object(
            psd_compute.estimators, "psd", return_value=(1, np.array([1.0]), np.zeros((3, 1)))
        ),
        patch.object(psd_compute, "NotchButterworth", return_value=notch_instance),
    ):
        results = psd_compute.estimate_psd(
            path=Path("AM001_foo_PREPROCESSED.edf"),
            state_path=Path("AM001_states.csv"),
            channels=[0, 1, 2],
            labels=labels,
            fs=10,
            chunksize=n,
            verbose=False,
        )
    return results, captured


def _by_state(results):
    return {r.behavior[1]: r for r in results}


def test_pure_wake_group_applies_sd_to_whole_mask():
    n = 20
    wake = np.zeros(n, dtype=bool)
    wake[0:10] = True
    nrem = np.zeros(n, dtype=bool)
    nrem[10:15] = True
    rem = np.zeros(n, dtype=bool)
    rem[15:20] = True
    # SD keeps 5 of 10 wake samples (even indices)
    sd = np.zeros(n, dtype=bool)
    sd[0:10:2] = True

    results, captured = _run_estimate_psd(
        labels={"wake": ["w"]},
        wake=wake,
        nrem=nrem,
        rem=rem,
        sd=sd,
    )

    assert len(captured["producer_calls"]) == 1
    np.testing.assert_array_equal(captured["producer_calls"][0], wake & sd)
    assert _by_state(results)["wake"].sd_out_frac == pytest.approx(0.5)


def test_pure_nrem_group_does_not_apply_sd():
    n = 20
    wake = np.zeros(n, dtype=bool)
    wake[0:10] = True
    nrem = np.zeros(n, dtype=bool)
    nrem[10:20] = True
    rem = np.zeros(n, dtype=bool)
    sd = np.zeros(n, dtype=bool)  # would remove everything if applied

    results, captured = _run_estimate_psd(
        labels={"nrem": ["n"]},
        wake=wake,
        nrem=nrem,
        rem=rem,
        sd=sd,
    )

    np.testing.assert_array_equal(captured["producer_calls"][0], nrem)
    assert _by_state(results)["nrem"].sd_out_frac == 0.0


def test_all_group_applies_sd_only_to_wake_samples():
    """Regression: the "all" preset must still gate wake samples by SD, but
    must leave NREM/REM samples inside the lumped group untouched."""
    n = 20
    wake = np.zeros(n, dtype=bool)
    wake[0:10] = True
    nrem = np.zeros(n, dtype=bool)
    nrem[10:15] = True
    rem = np.zeros(n, dtype=bool)
    rem[15:20] = True
    # SD keeps 5/10 wake samples and would reject ALL non-wake samples if
    # applied uniformly — the test fails under the old `'wake' in combo`
    # behavior (no SD) AND under a hypothetical global-SD regression.
    sd = np.zeros(n, dtype=bool)
    sd[0:10:2] = True

    results, captured = _run_estimate_psd(
        labels={"all": ["w", "n", "r"]},
        wake=wake,
        nrem=nrem,
        rem=rem,
        sd=sd,
    )

    mask = captured["producer_calls"][0]
    state_all = wake | nrem | rem
    expected = state_all & (~wake | sd)
    np.testing.assert_array_equal(mask, expected)
    # NREM and REM samples are preserved even though SD is False across them
    assert mask[10:15].all()
    assert mask[15:20].all()
    # Wake samples are gated by SD
    np.testing.assert_array_equal(mask[0:10], sd[0:10])
    # sd_out_frac reports the fraction of wake samples in the group that SD
    # removed (5 of 10 wake samples rejected → 0.5).
    assert _by_state(results)["all"].sd_out_frac == pytest.approx(0.5)


def test_sleep_group_without_wake_does_not_apply_sd():
    """A multi-state group with no wake code must skip SD gating entirely."""
    n = 20
    wake = np.zeros(n, dtype=bool)
    wake[0:10] = True
    nrem = np.zeros(n, dtype=bool)
    nrem[10:15] = True
    rem = np.zeros(n, dtype=bool)
    rem[15:20] = True
    sd = np.zeros(n, dtype=bool)  # would zero the group if SD were applied

    results, captured = _run_estimate_psd(
        labels={"sleep": ["n", "r"]},
        wake=wake,
        nrem=nrem,
        rem=rem,
        sd=sd,
    )

    np.testing.assert_array_equal(captured["producer_calls"][0], nrem | rem)
    assert _by_state(results)["sleep"].sd_out_frac == 0.0


def test_wake_submask_not_computed_when_no_mixed_wake_group():
    """If every selected group is single-code, masking.state is only called
    once per group — no extra ['w'] lookup for a wake sub-mask."""
    n = 20
    wake = np.zeros(n, dtype=bool)
    wake[0:10] = True
    nrem = np.zeros(n, dtype=bool)
    nrem[10:20] = True
    rem = np.zeros(n, dtype=bool)
    sd = np.ones(n, dtype=bool)

    _, captured = _run_estimate_psd(
        labels={"wake": ["w"], "nrem": ["n"]},
        wake=wake,
        nrem=nrem,
        rem=rem,
        sd=sd,
    )

    assert captured["state_calls"] == [("w",), ("n",)]


def test_wake_submask_computed_for_mixed_wake_group():
    """When a multi-code group contains wake, masking.state is called once
    per group PLUS once more to build the wake sub-mask."""
    n = 20
    wake = np.zeros(n, dtype=bool)
    wake[0:10] = True
    nrem = np.zeros(n, dtype=bool)
    nrem[10:15] = True
    rem = np.zeros(n, dtype=bool)
    rem[15:20] = True
    sd = np.ones(n, dtype=bool)

    _, captured = _run_estimate_psd(
        labels={"all": ["w", "n", "r"]},
        wake=wake,
        nrem=nrem,
        rem=rem,
        sd=sd,
    )

    assert captured["state_calls"] == [("w", "n", "r"), ("w",)]
