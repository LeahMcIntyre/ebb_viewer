"""SWD review window: step through epochs that overlap an SWD and fix their states.

Opened from the SWD Review page for one animal. Shows the EEG trace with the SWD
intervals shaded, the state bar (``reclass_state`` with any saved edits applied), and
the selected 4 s epoch highlighted. ``w``/``n``/``r`` set the selected epoch's state;
Space / Shift+Space (or the buttons) move between SWD epochs; double-click selects any
epoch, so neighbors on either side of an SWD can be edited too. Save writes
``swd_reclassification`` and ``final_state`` (``ebb.process.swd_review.save_swd_review``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal

from ebb.io.spindle_csv import SWD_COLUMN, has_column, read_state_column
from ebb.masking.events import swd_intervals
from ebb.process.swd_review import (
    EPOCH_SEC,
    existing_edits,
    merge_final_state,
    save_swd_review,
    swd_epoch_flags,
)
from ebb_viewer.edf_viewer.mask_builder import state_masks_from_epochs
from ebb_viewer.edf_viewer.masks import Mask, MaskSet
from ebb_viewer.edf_viewer.recording import Recording
from ebb_viewer.edf_viewer.trace_view import TraceView

_SWD_COLOR = (178, 170, 248, 80)
_SELECTED_COLOR = (255, 235, 59, 90)
_REVIEW_WIN_SEC = 20.0
_STATE_NAMES = {"w": "Wake", "n": "NREM", "r": "REM"}
_KEY_TO_STATE = {Qt.Key.Key_W: "w", Qt.Key.Key_N: "n", Qt.Key.Key_R: "r"}


class ReviewTraceView(TraceView):
    """TraceView whose w/n/r keys set a state instead of jumping between state spans."""

    stateKeyPressed = pyqtSignal(str)
    stepKeyPressed = pyqtSignal(int)  # +1 next SWD epoch, -1 previous

    def keyPressEvent(self, ev: QtGui.QKeyEvent) -> None:
        key = ev.key()
        if key in _KEY_TO_STATE:
            self.stateKeyPressed.emit(_KEY_TO_STATE[key])
            ev.accept()
            return
        if key == Qt.Key.Key_Space:
            shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.stepKeyPressed.emit(-1 if shift else 1)
            ev.accept()
            return
        super().keyPressEvent(ev)

    def set_state_masks(self, state_set: MaskSet) -> None:
        super().set_state_masks(state_set)
        self.reclass_pill.setVisible(False)  # not meaningful while reviewing


class SwdReviewWindow(QtWidgets.QMainWindow):
    """Review and edit epoch states around SWDs for one animal."""

    def __init__(
        self,
        recording: Recording,
        csv_path: Path,
        mat_path: Path,
        animal_id: str = "",
        on_saved: Callable[[str], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.rec = recording
        self.csv_path = Path(csv_path)
        self.mat_path = Path(mat_path)
        self.animal_id = animal_id
        self._on_saved = on_saved
        self.fs = int(recording.fs)
        self._samples_per_epoch = self.fs * EPOCH_SEC

        self.reclass = read_state_column(self.csv_path, "reclass_state")  # ValueError if absent
        intervals = swd_intervals(self.mat_path)
        self.flags = swd_epoch_flags(intervals, len(self.reclass))
        self.swd_epochs = [int(i) for i in np.flatnonzero(self.flags)]
        self.edits: dict[int, str] = {}
        if has_column(self.csv_path, SWD_COLUMN):
            self.edits = existing_edits(self.reclass, read_state_column(self.csv_path, SWD_COLUMN))
        self.dirty = False
        self._sel = self.swd_epochs[0] if self.swd_epochs else 0

        self.setWindowTitle(f"SWD review — {animal_id}" if animal_id else "SWD review")
        self._build_ui()

        # SWD intervals are fixed; the "selected epoch" mask moves with the selection.
        n = self.trace.n
        self._swd_mask = Mask(
            name="swd",
            color=_SWD_COLOR,
            spans=[
                (int(s * self.fs), min(int(e * self.fs), n))
                for s, e in intervals
                if e > s and int(s * self.fs) < n
            ],
        )
        self._selected_mask = Mask(name="selected", color=_SELECTED_COLOR)
        self._refresh_state_bar()
        self.select_epoch(self._sel)

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(central)
        lay.setContentsMargins(6, 6, 6, 6)

        top = QtWidgets.QHBoxLayout()
        self.lbl_status = QtWidgets.QLabel("")
        top.addWidget(self.lbl_status, 1)
        self.btn_prev = QtWidgets.QPushButton("← Prev SWD epoch")
        self.btn_next = QtWidgets.QPushButton("Next SWD epoch →")
        self.btn_save = QtWidgets.QPushButton("Save")
        self.btn_save.setToolTip(
            "Writes swd_reclassification and final_state. SWD epochs you did not change "
            "keep their current state."
        )
        for b in (self.btn_prev, self.btn_next, self.btn_save):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keep key events on the trace
            top.addWidget(b)
        lay.addLayout(top)

        hint = QtWidgets.QLabel(
            "w / n / r: set the selected epoch   ·   Space / Shift+Space: next / previous SWD "
            "epoch   ·   double-click: select any epoch   ·   ←/→: scroll"
        )
        hint.setStyleSheet("color: gray; font-size: 11px;")
        lay.addWidget(hint)

        self.trace = ReviewTraceView(
            data=self.rec.data,
            fs=self.fs,
            start_time=self.rec.start_time,
            ch_names=self.rec.ch_names,
            win_sec=_REVIEW_WIN_SEC,
        )
        self.trace.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        lay.addWidget(self.trace, 1)
        self.setCentralWidget(central)

        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.btn_save.clicked.connect(self.save)
        self.trace.stateKeyPressed.connect(self.set_state)
        self.trace.stepKeyPressed.connect(self.step)
        self.trace.timeDoubleClicked.connect(self._on_double_click)

    # ---------------- state ----------------
    @property
    def n_epochs(self) -> int:
        return len(self.reclass)

    def state_of(self, epoch: int) -> str:
        return self.edits.get(epoch, self.reclass[epoch])

    def _current_states(self) -> list[str]:
        return [self.edits.get(i, s) for i, s in enumerate(self.reclass)]

    def _refresh_state_bar(self) -> None:
        self.trace.set_state_masks(state_masks_from_epochs(self._current_states(), self.fs))

    def _update_status(self) -> None:
        i = self._sel
        parts = []
        if self.flags[i]:
            parts.append(f"SWD epoch {self.swd_epochs.index(i) + 1} of {len(self.swd_epochs)}")
        else:
            parts.append(f"non-SWD epoch ({len(self.swd_epochs)} SWD epochs total)")
        t0 = i * EPOCH_SEC
        parts.append(f"epoch #{i} ({t0}–{t0 + EPOCH_SEC} s)")
        state = _STATE_NAMES.get(self.state_of(i), self.state_of(i) or "?")
        if i in self.edits:
            parts.append(f"{state} (was {_STATE_NAMES.get(self.reclass[i], self.reclass[i])})")
        else:
            parts.append(state)
        parts.append(f"{len(self.edits)} edited" + (" · unsaved" if self.dirty else ""))
        self.lbl_status.setText("   ·   ".join(parts))

    # ---------------- actions ----------------
    def select_epoch(self, epoch: int) -> None:
        """Select ``epoch``, center the trace on it and highlight it."""
        epoch = int(np.clip(epoch, 0, max(self.n_epochs - 1, 0)))
        self._sel = epoch
        s0 = epoch * self._samples_per_epoch
        self._selected_mask.spans = [(s0, s0 + self._samples_per_epoch)]
        self.trace.set_masks(MaskSet({"swd": self._swd_mask, "selected": self._selected_mask}))
        self.trace.state_bar.set_highlight((epoch * EPOCH_SEC, (epoch + 1) * EPOCH_SEC))
        self.trace.jump_to_sample(s0 + self._samples_per_epoch // 2)
        self._update_status()
        self.trace.setFocus()

    def step(self, direction: int) -> None:
        """Move to the next (+1) or previous (-1) SWD epoch relative to the selection."""
        if not self.swd_epochs:
            return
        if direction > 0:
            later = [e for e in self.swd_epochs if e > self._sel]
            target = later[0] if later else None
        else:
            earlier = [e for e in self.swd_epochs if e < self._sel]
            target = earlier[-1] if earlier else None
        if target is not None:
            self.select_epoch(target)

    def set_state(self, state: str) -> None:
        """Set the selected epoch to ``state`` ('w'/'n'/'r'); equal to the default is a no-op edit."""
        i = self._sel
        if state == self.reclass[i]:
            changed = self.edits.pop(i, None) is not None
        else:
            changed = self.edits.get(i) != state
            self.edits[i] = state
        if changed:
            self.dirty = True
            self._refresh_state_bar()
            self.trace.state_bar.set_highlight((i * EPOCH_SEC, (i + 1) * EPOCH_SEC))
        self._update_status()

    def _on_double_click(self, t_sec: float) -> None:
        self.select_epoch(int(t_sec // EPOCH_SEC))

    def save(self) -> bool:
        """Write the review to the CSV. Returns True on success."""
        try:
            save_swd_review(self.csv_path, self.mat_path, self.edits)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save failed", str(e))
            return False
        self.dirty = False
        self._update_status()
        if self._on_saved is not None:
            self._on_saved(self.animal_id)
        return True

    def preview_final_state(self) -> list[str]:
        """What ``final_state`` would be if saved now (for tests / display)."""
        from ebb.process.swd_review import build_swd_column

        return merge_final_state(
            self.reclass, build_swd_column(self.reclass, self.flags, self.edits)
        )

    def closeEvent(self, ev: QtGui.QCloseEvent) -> None:
        if self.dirty:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Unsaved SWD review",
                "Save your changes before closing?",
                QtWidgets.QMessageBox.StandardButton.Save
                | QtWidgets.QMessageBox.StandardButton.Discard
                | QtWidgets.QMessageBox.StandardButton.Cancel,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Cancel or (
                reply == QtWidgets.QMessageBox.StandardButton.Save and not self.save()
            ):
                ev.ignore()
                return
        super().closeEvent(ev)


def launch_swd_review(
    edf_path: Path,
    csv_path: Path,
    mat_path: Path,
    animal_id: str = "",
    on_saved: Callable[[str], None] | None = None,
) -> SwdReviewWindow:
    """Load the EDF (same full read as the normal viewer) and return an unshown window."""
    from ebb_viewer.edf_viewer.eeg_viewer import _load_recording

    rec = _load_recording(Path(edf_path), Path(csv_path))
    return SwdReviewWindow(rec, csv_path, mat_path, animal_id=animal_id, on_saved=on_saved)
