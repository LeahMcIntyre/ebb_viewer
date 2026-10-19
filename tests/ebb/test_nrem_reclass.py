"""Tests for the NREM reclassification protocol (gap fill + EMG gate)."""

import csv
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from ebb.process import nrem_reclass as nr
from ebb.process.sleep_compute import compute_sleep_bins_df, compute_spindle_fractions


def _flips(spec: str, radius: int = 1) -> str:
    """Spec chars: UPPER = clean epoch, lower = artifact-flagged epoch."""
    states = np.array([c.lower() for c in spec])
    artifact = np.array([c.islower() for c in spec])
    flips = nr.gap_fill_flips(states, artifact, radius)
    return "".join("F" if f else "-" for f in flips)


def _write_csv(path: Path, epochs: list[tuple[str, float]], threshold: float | None = 0.5) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "state", "noise_probs", "rawstate", "threshold", "final_state"])
        for i, (state, noise) in enumerate(epochs):
            thr = "" if (i > 0 or threshold is None) else str(threshold)
            w.writerow([i, state, noise, state, thr, state])


# --- gap fill -----------------------------------------------------------


def test_gap_fill_only_flagged_epochs_flip_in_description_example():
    # raw: N N* N N N* N N -- neither clean N has artifact on both sides
    assert _flips("NnNNnNN") == "-F--F--"


def test_gap_fill_clean_epoch_between_two_artifacts_flips():
    assert _flips("nNn") == "FFF"  # the flagged ends are NREM themselves, so they flip too


def test_gap_fill_needs_artifact_on_both_sides():
    assert _flips("NNN") == "---"
    assert _flips("nNN") == "F--"  # artifact on one side only: just the flagged epoch
    assert _flips("NNn") == "--F"


def test_gap_fill_any_state_neighbours_bracket():
    states = np.array(["w", "n", "r"])
    artifact = np.array([True, False, True])
    assert nr.gap_fill_flips(states, artifact).tolist() == [False, True, False]


def test_gap_fill_never_flips_non_nrem_even_if_flagged():
    states = np.array(["w", "r", "w"])
    artifact = np.array([True, True, True])
    assert not nr.gap_fill_flips(states, artifact).any()


def test_gap_fill_radius_two():
    states = np.array(["n"] * 5)
    artifact = np.array([True, False, False, False, True])
    assert nr.gap_fill_flips(states, artifact, radius=1).tolist() == [True] + [False] * 3 + [True]
    # radius 2: epoch 2 sees artifact at distance 2 both sides; 1 and 3 only one side
    assert nr.gap_fill_flips(states, artifact, radius=2).tolist() == [True, False, True, False, True]


def test_gap_fill_edges_have_no_phantom_neighbours():
    states = np.array(["n", "n"])
    assert not nr.gap_fill_flips(states, np.array([False, False])).any()


# --- bouts and the gate decision -----------------------------------------


def test_count_bouts():
    assert nr.count_bouts(np.array([], dtype=bool)) == 0
    assert nr.count_bouts(np.array([1, 1, 0, 1, 0, 0, 1], dtype=bool)) == 3
    assert nr.count_bouts(np.array([1, 1, 1], dtype=bool)) == 1
    assert nr.count_bouts(np.array([0, 0], dtype=bool)) == 0


def test_count_bouts_assigns_each_bout_to_the_period_it_starts_in():
    nrem = np.array([0, 1, 1, 1, 0, 1, 1, 0], dtype=bool)
    light = np.array([1, 1, 1, 0, 0, 0, 0, 0], dtype=bool)
    # bout 1 starts in light (and runs into dark) -> counted; bout 2 starts in dark -> not
    assert nr.count_bouts(nrem, light) == 1
    assert nr.count_bouts(nrem, ~light) == 1
    assert nr.count_bouts(nrem) == 2


@pytest.mark.parametrize(
    "before, after, expected",
    [(10, 10, False), (10, 11, False), (10, 12, True), (10, 5, False), (0, 0, False)],
)
def test_needs_emg_gate_requires_more_than_ten_percent_rise(before, after, expected):
    assert nr.needs_emg_gate(before, after) is expected


# --- clock / light period -------------------------------------------------


def test_light_period_mask_boundaries():
    start = datetime(2024, 1, 1, 19, 59, 56)  # epoch 1 begins at 20:00:00
    m = nr.light_period_mask(start, 3)
    assert m.tolist() == [True, False, False]
    # 05:59:56 is still dark, 06:00:00 is light
    m = nr.light_period_mask(datetime(2024, 1, 1, 5, 59, 56), 2)
    assert m.tolist() == [False, True]


def test_light_period_mask_wraps_midnight():
    m = nr.light_period_mask(datetime(2024, 1, 1, 23, 59, 56), 3)
    assert m.tolist() == [False, False, False]


# --- EMG cutoff -----------------------------------------------------------


def test_emg_cutoff_median_plus_k_mad_over_nrem_only():
    rms = np.array([1.0, 2.0, 3.0, 4.0, 100.0, 5000.0])
    nrem = np.array([True, True, True, True, True, False])  # last is not NREM
    # median 3, |dev| = [2,1,0,1,97] -> MAD 1 -> 3 + 5*1
    assert nr.emg_cutoff(rms, nrem, k=5) == pytest.approx(8.0)


def test_emg_cutoff_ignores_nan_and_handles_empty():
    rms = np.array([1.0, np.nan, 3.0])
    assert nr.emg_cutoff(rms, np.array([True, True, True]), k=1) == pytest.approx(2.0 + 1.0)
    assert nr.emg_cutoff(rms, np.array([False] * 3)) == float("inf")


# --- whole-file protocol ---------------------------------------------------


@pytest.fixture
def start_at_8am(monkeypatch):
    monkeypatch.setattr(nr, "read_edf_start_datetime", lambda p: datetime(2024, 1, 1, 8, 0, 0))


def test_no_gate_when_bout_count_does_not_rise(tmp_path, start_at_8am):
    # [N N N* W W] x 20: flipping bout edges never splits a bout
    epochs = [("n", 0.0), ("n", 0.0), ("n", 0.9), ("w", 0.0), ("w", 0.0)] * 20
    _write_csv(tmp_path / "A_x.csv", epochs)
    res = nr.reclassify_file(tmp_path / "A_x.csv", tmp_path / "A_PREPROCESSED.edf")
    assert not res.gate_applied
    assert res.bouts_before == res.bouts_after == 20
    assert (res.final_state == res.gapfill_state).all()
    assert (res.rawstate != res.gapfill_state).sum() == 20


def test_gate_keeps_only_flips_with_high_emg(tmp_path, start_at_8am):
    # One long NREM bout, artifact at every 4th epoch: gap fill shatters it.
    n = 200
    epochs = [("n", 0.9 if i % 4 == 3 else 0.0) for i in range(n)]
    _write_csv(tmp_path / "A_x.csv", epochs)

    rms = 1.0 + 0.1 * (np.arange(n) % 5)  # background EMG with some spread (MAD > 0)
    rms[3] = 50.0  # only the first artifact epoch has real movement
    res = nr.reclassify_file(
        tmp_path / "A_x.csv", tmp_path / "A_PREPROCESSED.edf", rms_fn=lambda p: rms
    )
    assert res.gate_applied
    assert res.bouts_before == 1 and res.bouts_after > 1.1
    assert (res.rawstate != res.gapfill_state).sum() == 50  # gap fill flips every flagged epoch
    assert (res.rawstate != res.final_state).nonzero()[0].tolist() == [3]
    # the gate only cancels, never adds
    assert set(np.flatnonzero(res.rawstate != res.final_state)) <= set(
        np.flatnonzero(res.rawstate != res.gapfill_state)
    )


def test_gate_cancels_flips_when_edf_shorter_than_csv(tmp_path, start_at_8am):
    n = 40
    epochs = [("n", 0.9 if i % 4 == 3 else 0.0) for i in range(n)]
    _write_csv(tmp_path / "A_x.csv", epochs)
    short_rms = 1.0 + 0.1 * (np.arange(10) % 5)
    short_rms[3] = 50.0
    res = nr.reclassify_file(
        tmp_path / "A_x.csv", tmp_path / "A_PREPROCESSED.edf", rms_fn=lambda p: short_rms
    )
    assert res.gate_applied
    # only the movement epoch inside the EMG recording is flipped; flips past its end are cancelled
    assert np.flatnonzero(res.rawstate != res.final_state).tolist() == [3]


def test_emg_not_read_when_gate_not_needed(tmp_path, start_at_8am):
    _write_csv(tmp_path / "A_x.csv", [("n", 0.0), ("n", 0.9), ("w", 0.0)] * 10)

    def boom(_):
        raise AssertionError("EMG must only be read when the gate applies")

    nr.reclassify_file(tmp_path / "A_x.csv", tmp_path / "A_PREPROCESSED.edf", rms_fn=boom)


def test_dark_period_bouts_do_not_trigger_gate(tmp_path, monkeypatch):
    # Recording starts 20:00 and is shorter than 10 h, so it never reaches the light period.
    monkeypatch.setattr(nr, "read_edf_start_datetime", lambda p: datetime(2024, 1, 1, 20, 0, 0))
    epochs = [("n", 0.9 if i % 4 == 3 else 0.0) for i in range(200)]
    _write_csv(tmp_path / "A_x.csv", epochs)
    res = nr.reclassify_file(tmp_path / "A_x.csv", tmp_path / "A_PREPROCESSED.edf")
    assert res.bouts_before == res.bouts_after == 0
    assert not res.gate_applied


def test_threshold_column_overrides_default(tmp_path, start_at_8am):
    epochs = [("w", 0.0), ("n", 0.6), ("w", 0.0)] * 10
    _write_csv(tmp_path / "hi_x.csv", epochs, threshold=0.9)
    _write_csv(tmp_path / "lo_x.csv", epochs, threshold=None)  # default 0.5
    edf = tmp_path / "x_PREPROCESSED.edf"
    assert (nr.reclassify_file(tmp_path / "hi_x.csv", edf).rawstate
            == nr.reclassify_file(tmp_path / "hi_x.csv", edf).final_state).all()
    lo = nr.reclassify_file(tmp_path / "lo_x.csv", edf)
    assert (lo.rawstate != lo.final_state).sum() == 10


def test_new_format_columns(tmp_path, start_at_8am):
    p = tmp_path / "A_x.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state", "noise_prob"])
        w.writerows([["n", 0.9], ["w", 0.0]])
    res = nr.reclassify_file(p, tmp_path / "A_PREPROCESSED.edf")
    assert res.final_state.tolist() == ["w", "w"]


def test_reclassify_dir_skips_animals_without_edf(tmp_path, start_at_8am):
    _write_csv(tmp_path / "A_x.csv", [("n", 0.9), ("w", 0.0)])
    _write_csv(tmp_path / "B_x.csv", [("n", 0.9), ("w", 0.0)])
    edfs = tmp_path / "standard"
    edfs.mkdir()
    (edfs / "A_PREPROCESSED.edf").touch()
    with pytest.warns(UserWarning, match="No EDF for animal 'B'"):
        out = nr.reclassify_dir(tmp_path, edfs)
    assert list(out) == ["A"]


# --- sleep_compute override --------------------------------------------------


def test_states_by_animal_overrides_csv_in_bins_and_fractions(tmp_path):
    _write_csv(tmp_path / "A_x.csv", [("n", 0.9), ("n", 0.0), ("w", 0.0), ("w", 0.0)])
    override = {"A": ["w", "n", "w", "w"]}

    raw = compute_sleep_bins_df(tmp_path, bin_hours=1)
    new = compute_sleep_bins_df(tmp_path, bin_hours=1, states_by_animal=override)
    frac = lambda df, s: df.loc[df["state"] == s, "frac_time"].sum()  # noqa: E731
    assert frac(raw, "n") == pytest.approx(0.5) and frac(new, "n") == pytest.approx(0.25)

    f_raw = compute_spindle_fractions(tmp_path)
    f_new = compute_spindle_fractions(tmp_path, states_by_animal=override)
    nrem = lambda df: df[df["state"] == "NREM"].iloc[0]  # noqa: E731
    assert nrem(f_raw).total_count == 2 and nrem(f_raw).spindle_count == 1
    assert nrem(f_new).total_count == 1 and nrem(f_new).spindle_count == 0
    wake = f_new[f_new["state"] == "Wake"].iloc[0]
    assert wake.total_count == 3 and wake.spindle_count == 1


def test_states_by_animal_leaves_other_animals_on_csv(tmp_path):
    _write_csv(tmp_path / "A_x.csv", [("n", 0.0)] * 4)
    _write_csv(tmp_path / "B_x.csv", [("n", 0.0)] * 4)
    df = compute_sleep_bins_df(tmp_path, bin_hours=1, states_by_animal={"A": ["w"] * 4})
    n_frac = df[df["state"] == "n"].set_index("mouse_id")["frac_time"]
    assert "A" not in n_frac.index and n_frac["B"] == 1.0


# --- writing reclass_state into the CSVs --------------------------------


def _fragmenting_epochs() -> list[tuple[str, float]]:
    # NREM run with artifact epochs inside it: gap fill splits it into more bouts.
    return [("n", 0.0), ("n", 0.9), ("n", 0.0), ("n", 0.0), ("n", 0.9), ("n", 0.0), ("w", 0.0)] * 4


def test_reclassify_dir_to_csv_adds_column_and_backs_up_original(tmp_path, start_at_8am):
    states = tmp_path / "states"
    edfs = tmp_path / "edfs"
    states.mkdir()
    edfs.mkdir()
    epochs = _fragmenting_epochs()
    _write_csv(states / "A_x.csv", epochs)
    (edfs / "A_PREPROCESSED.edf").touch()
    original = (states / "A_x.csv").read_text()

    out = nr.reclassify_dir_to_csv(states, edfs, rms_fn=lambda p: np.full(len(epochs), 100.0))

    with (states / "A_x.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["reclass_state"] for r in rows] == out["A"].final_state.tolist()
    assert [r["final_state"] for r in rows] == out["A"].final_state.tolist()
    assert list(rows[0])[:5] == ["index", "state", "noise_probs", "rawstate", "threshold"]
    assert (states / "_original" / "A_x.csv").read_text() == original


def test_reclassify_dir_to_csv_is_idempotent(tmp_path, start_at_8am):
    states = tmp_path / "states"
    edfs = tmp_path / "edfs"
    states.mkdir()
    edfs.mkdir()
    epochs = _fragmenting_epochs()
    _write_csv(states / "A_x.csv", epochs)
    (edfs / "A_PREPROCESSED.edf").touch()
    original = (states / "A_x.csv").read_text()
    kw = dict(rms_fn=lambda p: np.full(len(epochs), 100.0))

    nr.reclassify_dir_to_csv(states, edfs, **kw)
    first = (states / "A_x.csv").read_text()
    nr.reclassify_dir_to_csv(states, edfs, **kw)

    assert (states / "A_x.csv").read_text() == first
    assert (states / "_original" / "A_x.csv").read_text() == original  # backup not overwritten


def test_write_column_rejects_length_mismatch(tmp_path):
    from ebb.io.spindle_csv import write_columns

    _write_csv(tmp_path / "A_x.csv", [("n", 0.0), ("w", 0.0)])
    with pytest.raises(ValueError, match="rows"):
        write_columns(tmp_path / "A_x.csv", {"reclass_state": ["n"]})


def test_rerun_after_reclass_reads_original_states_not_final(tmp_path, start_at_8am):
    """final_state/reclass_state must never feed back in as the input states."""
    states = tmp_path / "states"
    edfs = tmp_path / "edfs"
    states.mkdir()
    edfs.mkdir()
    epochs = _fragmenting_epochs()
    _write_csv(states / "A_x.csv", epochs)
    (edfs / "A_PREPROCESSED.edf").touch()
    kw = dict(rms_fn=lambda p: np.full(len(epochs), 100.0))

    first = nr.reclassify_dir_to_csv(states, edfs, **kw)["A"]
    second = nr.reclassify_dir_to_csv(states, edfs, **kw)["A"]

    assert second.rawstate.tolist() == first.rawstate.tolist() == [e[0] for e in epochs]


def test_read_state_column(tmp_path):
    from ebb.io.spindle_csv import read_state_column

    p = tmp_path / "A_x.csv"
    p.write_text("state,final_state\nw,n\n\nn,r\n")
    assert read_state_column(p, "final_state") == ["n", "r"]
    with pytest.raises(ValueError, match="nope"):
        read_state_column(p, "nope")
