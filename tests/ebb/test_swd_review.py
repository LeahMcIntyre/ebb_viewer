"""SWD epoch review library: overlap, the swd_reclassification column, final_state merge,
and keeping saved review across a Reclassify re-run."""

import csv
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from ebb.io.spindle_csv import FINAL_COLUMN, RECLASS_COLUMN, SWD_COLUMN, read_state_column
from ebb.masking.events import swd_intervals
from ebb.process import nrem_reclass as nr
from ebb.process import swd_review as sr

# --- swd_intervals ------------------------------------------------------------


def _mat(path: Path, value, key="DEL_ts") -> Path:
    savemat(path, {key: value})
    return path


def test_swd_intervals_reads_pairs_and_ignores_extra_columns(tmp_path):
    p = _mat(tmp_path / "a.mat", [[1.0, 2.5, 99], [10.0, 12.0, 99]])
    assert swd_intervals(p).tolist() == [[1.0, 2.5], [10.0, 12.0]]


def test_swd_intervals_single_event_and_empty_and_fallback_key(tmp_path):
    assert swd_intervals(_mat(tmp_path / "one.mat", [3.0, 4.0])).tolist() == [[3.0, 4.0]]
    assert swd_intervals(_mat(tmp_path / "none.mat", np.empty((0, 2)))).shape == (0, 2)
    assert swd_intervals(_mat(tmp_path / "k.mat", [[1.0, 2.0]], key="final_ts")).tolist() == [
        [1.0, 2.0]
    ]


def test_swd_intervals_rejects_malformed_shapes(tmp_path):
    with pytest.raises(ValueError, match="expected 1D or 2D"):
        swd_intervals(_mat(tmp_path / "bad.mat", np.zeros((2, 2, 2))))


# --- epoch overlap ------------------------------------------------------------


def _flags(intervals, n=5):
    return "".join("X" if f else "-" for f in sr.swd_epoch_flags(intervals, n))


def test_any_overlap_marks_epoch():
    assert _flags([[5.0, 6.0]]) == "-X---"  # inside epoch 1 (4-8 s)
    assert _flags([[7.9, 8.1]]) == "-XX--"  # clips the edge of epoch 2
    assert _flags([[3.0, 9.0]]) == "XXX--"


def test_touching_an_epoch_edge_is_not_overlap():
    assert _flags([[0.0, 4.0]]) == "X----"  # stops exactly where epoch 1 starts
    assert _flags([[8.0, 12.0]]) == "--X--"  # starts exactly where epoch 1 ends


def test_intervals_beyond_the_recording_and_empty_are_safe():
    assert _flags([[100.0, 120.0]]) == "-----"
    assert _flags(np.empty((0, 2))) == "-----"
    assert _flags([[-5.0, 1.0]]) == "X----"


# --- column rule --------------------------------------------------------------

RECLASS = ["w", "n", "n", "r", "w"]


def test_only_reviewed_swd_epochs_get_a_value_the_rest_stay_blank():
    # epochs 1 and 2 overlap an SWD, but only epoch 1 has been reviewed
    assert sr.build_swd_column(RECLASS, {1}, {}) == ["", "n", "", "", ""]
    assert sr.build_swd_column(RECLASS, set(), {}) == [""] * 5  # nothing reviewed yet


def test_edit_on_swd_epoch_and_on_non_swd_neighbor():
    col = sr.build_swd_column(RECLASS, {1, 2}, {1: "w", 3: "n"})
    assert col == ["", "w", "n", "n", ""]  # epoch 3 is a non-SWD neighbor edit


def test_edit_equal_to_current_state_on_unreviewed_epoch_is_a_noop():
    assert sr.build_swd_column(RECLASS, {1}, {3: "r"})[3] == ""


def test_invalid_edits_and_epochs_rejected():
    with pytest.raises(ValueError, match="invalid state"):
        sr.build_swd_column(RECLASS, set(), {0: "x"})
    with pytest.raises(ValueError, match="epoch 9"):
        sr.build_swd_column(RECLASS, set(), {9: "w"})
    with pytest.raises(ValueError, match="reviewed epoch 9"):
        sr.build_swd_column(RECLASS, {9}, {})


def test_reviewed_epochs_are_the_non_blank_swd_epochs():
    flags = np.array([False, True, True, False, False])
    col = ["", "n", "", "n", ""]  # epoch 3 is a non-SWD neighbor edit, not a reviewed SWD epoch
    assert sr.reviewed_epochs(col, flags) == {1}


def test_merge_final_state_and_existing_edits():
    col = ["", "w", "n", "n", ""]
    assert sr.merge_final_state(RECLASS, col) == ["w", "w", "n", "n", "w"]
    assert sr.existing_edits(RECLASS, col) == {1: "w", 3: "n"}  # epoch 2 is an unedited copy


# --- refresh after Reclassify re-run -----------------------------------------


def test_refresh_keeps_edits_and_refreshes_unedited_copies():
    old_reclass = ["w", "n", "n", "r", "w"]
    old_swd = ["", "w", "n", "n", ""]  # 1: edit, 2: unedited copy, 3: neighbor edit
    new_reclass = ["w", "n", "w", "r", "w"]  # epoch 2's state changed in the re-run
    assert sr.refresh_swd_after_reclass(old_reclass, old_swd, new_reclass) == [
        "",
        "w",
        "w",  # unedited copy follows the new reclass_state
        "n",
        "",
    ]


def test_refresh_rejects_length_mismatch():
    with pytest.raises(ValueError, match="lengths"):
        sr.refresh_swd_after_reclass(["w"], ["", ""], ["w"])


# --- files --------------------------------------------------------------------


def _write_csv(path: Path, states: list[str]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "state", "noise_probs", "rawstate", "threshold", "final_state"])
        for i, s in enumerate(states):
            w.writerow([i, s, 0.0, s, "0.5" if i == 0 else "", s])


@pytest.fixture
def start_at_8am(monkeypatch):
    monkeypatch.setattr(nr, "read_edf_start_datetime", lambda p: datetime(2024, 1, 1, 8, 0, 0))


def _project(tmp_path: Path, states: list[str]):
    out = tmp_path / "out"
    edfs = tmp_path / "edfs"
    out.mkdir()
    edfs.mkdir()
    _write_csv(out / "A_x.csv", states)
    (edfs / "A_PREPROCESSED.edf").touch()
    mat = _mat(tmp_path / "A_swd.mat", [[4.0, 9.0]])  # epochs 1, 2
    return out, edfs, mat


def test_save_writes_swd_column_and_final_state(tmp_path, start_at_8am):
    states = ["w", "n", "n", "r", "w"]
    out, edfs, mat = _project(tmp_path, states)
    kw = dict(rms_fn=lambda p: np.full(len(states), 100.0))
    nr.reclassify_dir_to_csv(out, edfs, **kw)

    counts = sr.save_swd_review(out / "A_x.csv", mat, {1: "w", 3: "n"}, reviewed={1})

    assert counts == (2, 1, 2)  # 2 SWD epochs, 1 reviewed, 2 edited
    # epoch 2 overlaps the SWD but was not reviewed, so it stays blank
    assert read_state_column(out / "A_x.csv", SWD_COLUMN) == ["", "w", "", "n", ""]
    assert read_state_column(out / "A_x.csv", FINAL_COLUMN) == ["w", "w", "n", "n", "w"]
    assert read_state_column(out / "A_x.csv", RECLASS_COLUMN) == states  # untouched


def test_save_is_idempotent_and_edits_can_be_undone(tmp_path, start_at_8am):
    states = ["w", "n", "n", "r", "w"]
    out, edfs, mat = _project(tmp_path, states)
    nr.reclassify_dir_to_csv(out, edfs, rms_fn=lambda p: np.full(5, 100.0))
    sr.save_swd_review(out / "A_x.csv", mat, {1: "w"}, reviewed={1})
    sr.save_swd_review(out / "A_x.csv", mat, {1: "w"}, reviewed={1})
    assert read_state_column(out / "A_x.csv", FINAL_COLUMN)[1] == "w"

    sr.save_swd_review(out / "A_x.csv", mat, {}, reviewed=set())  # user reverted everything
    assert read_state_column(out / "A_x.csv", FINAL_COLUMN) == states


def test_reclassify_rerun_keeps_swd_edits(tmp_path, start_at_8am):
    states = ["w", "n", "n", "r", "w"]
    out, edfs, mat = _project(tmp_path, states)
    kw = dict(rms_fn=lambda p: np.full(5, 100.0))
    nr.reclassify_dir_to_csv(out, edfs, **kw)
    sr.save_swd_review(out / "A_x.csv", mat, {1: "w", 3: "n"}, reviewed={1, 2})

    nr.reclassify_dir_to_csv(out, edfs, **kw)  # re-run Reclassify

    assert read_state_column(out / "A_x.csv", SWD_COLUMN) == ["", "w", "n", "n", ""]
    assert read_state_column(out / "A_x.csv", FINAL_COLUMN) == ["w", "w", "n", "n", "w"]
