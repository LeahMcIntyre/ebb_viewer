"""SwdReviewWindow: selection, w/n/r editing, SWD-epoch stepping, state bar, saving."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox
from scipy.io import savemat

from ebb.io.spindle_csv import FINAL_COLUMN, RECLASS_COLUMN, SWD_COLUMN, read_state_column
from ebb_viewer.edf_viewer.mask_builder import state_masks_from_epochs
from ebb_viewer.edf_viewer.recording import Recording
from ebb_viewer.edf_viewer.swd_review import SwdReviewWindow

FS = 250
EPOCH = 4
RECLASS = list("wnnnrwnnwwrw")  # 12 epochs
SWD_EPOCHS = [1, 2, 6]  # intervals below


def _write_csv(path: Path, swd_col: list[str] | None = None) -> None:
    header = ["state", RECLASS_COLUMN, FINAL_COLUMN] + ([SWD_COLUMN] if swd_col else [])
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for i, s in enumerate(RECLASS):
            row = [s, s, s]
            if swd_col:
                row[2] = swd_col[i] or s
                row.append(swd_col[i])
            w.writerow(row)


@pytest.fixture
def win(qapp, tmp_path):
    csv_path = tmp_path / "A1_x.csv"
    _write_csv(csv_path)
    mat = tmp_path / "A1_swd.mat"
    savemat(mat, {"DEL_ts": [[5.0, 9.0], [24.5, 25.0]]})  # epochs 1-2 and 6
    rec = Recording(
        data=np.zeros((4, len(RECLASS) * EPOCH * FS)),
        fs=FS,
        start_time=datetime(2025, 1, 1),
        ch_names=("LFC", "RSC", "LSC", "EMG"),
        edf_path=tmp_path / "A1.edf",
        csv_path=csv_path,
    )
    saved: list[str] = []
    w = SwdReviewWindow(rec, csv_path, mat, animal_id="A1", on_saved=saved.append)
    w.saved = saved
    w.show()
    qapp.processEvents()
    yield w
    w.dirty = False  # never prompt during teardown
    w.close()


def _key(w, key, mod=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(w.trace, key, mod)


def test_opens_on_first_swd_epoch(win):
    assert win.swd_epochs == SWD_EPOCHS
    assert win._sel == 1
    assert "SWD epoch 1 of 3" in win.lbl_status.text()


def test_space_steps_through_swd_epochs_only(win):
    _key(win, Qt.Key.Key_Space)
    assert win._sel == 2
    _key(win, Qt.Key.Key_Space)
    assert win._sel == 6
    _key(win, Qt.Key.Key_Space)  # already last
    assert win._sel == 6
    _key(win, Qt.Key.Key_Space, Qt.KeyboardModifier.ShiftModifier)
    assert win._sel == 2


def test_wnr_keys_set_state_instead_of_jumping(win):
    _key(win, Qt.Key.Key_W)  # epoch 1 was 'n'
    assert win.edits == {1: "w"}
    assert win.state_of(1) == "w"
    assert win.dirty
    assert win._sel == 1  # did not jump to the next wake span


def test_state_bar_updates_after_an_edit(win):
    _key(win, Qt.Key.Key_W)
    expected = state_masks_from_epochs(["w", "w", "n", "n", "r", "w", "n", "n", "w", "w", "r", "w"], FS)
    got = win.trace.state_set
    for name in ("wake", "nrem", "rem"):
        assert got.get(name).spans == expected.get(name).spans


def test_setting_back_to_the_default_removes_the_edit(win):
    _key(win, Qt.Key.Key_W)
    _key(win, Qt.Key.Key_N)  # back to the original 'n'
    assert win.edits == {}


def test_double_click_selects_a_non_swd_neighbor_and_it_can_be_edited(win):
    win._on_double_click(3 * EPOCH + 1.0)  # epoch 3, next to SWD epoch 2
    assert win._sel == 3 and not win.flags[3]
    assert "non-SWD" in win.lbl_status.text()
    _key(win, Qt.Key.Key_R)
    assert win.edits == {3: "r"}


def test_save_writes_columns_and_notifies(win, tmp_path):
    _key(win, Qt.Key.Key_W)  # epoch 1 n -> w
    win._on_double_click(3 * EPOCH + 1.0)
    _key(win, Qt.Key.Key_R)  # epoch 3 n -> r
    expected_final = win.preview_final_state()

    assert win.save() is True

    csv_path = tmp_path / "A1_x.csv"
    swd_col = read_state_column(csv_path, SWD_COLUMN)
    assert swd_col == ["", "w", "n", "r", "", "", "n", "", "", "", "", ""]
    assert read_state_column(csv_path, FINAL_COLUMN) == expected_final
    assert expected_final[1] == "w" and expected_final[3] == "r"
    assert not win.dirty
    assert win.saved == ["A1"]


def test_reopening_loads_saved_edits(win, tmp_path, qapp):
    _key(win, Qt.Key.Key_W)
    win.save()
    mat = tmp_path / "A1_swd.mat"
    rec = win.rec
    again = SwdReviewWindow(rec, tmp_path / "A1_x.csv", mat, animal_id="A1")
    assert again.edits == {1: "w"}
    again.dirty = False
    again.close()


def test_closing_with_unsaved_changes_can_be_cancelled(win):
    _key(win, Qt.Key.Key_W)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
        assert win.close() is False
    assert win.dirty


def test_missing_reclass_state_column_raises(qapp, tmp_path):
    p = tmp_path / "A1_x.csv"
    p.write_text("state\nw\nn\n")
    mat = tmp_path / "A1_swd.mat"
    savemat(mat, {"DEL_ts": [[1.0, 2.0]]})
    rec = Recording(
        data=np.zeros((4, 2 * EPOCH * FS)),
        fs=FS,
        start_time=datetime(2025, 1, 1),
        ch_names=("LFC", "RSC", "LSC", "EMG"),
        edf_path=tmp_path / "A1.edf",
    )
    with pytest.raises(ValueError, match="reclass_state"):
        SwdReviewWindow(rec, p, mat)
