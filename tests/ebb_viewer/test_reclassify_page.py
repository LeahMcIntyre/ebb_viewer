"""ReclassifyPage: the worker must actually run and report back (regression: the
unreferenced worker was GC'd before ``thread.started → run``, hanging forever)."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ebb.process.nrem_reclass import NremReclass
from ebb_viewer.pipeline.manifest import Manifest


def test_run_completes_and_records_gate(qapp, tmp_path: Path, monkeypatch):
    from ebb_viewer.pages import reclassify as rc

    out = tmp_path / "spindle_outputs" / "LFC_RSC"
    out.mkdir(parents=True)
    (out / "A1_x.csv").write_text("state,noise_prob\nn,0\n")
    (tmp_path / "standard").mkdir()
    (tmp_path / "standard" / "A1_PREPROCESSED.edf").touch()

    states = np.array(["n"])
    fake = NremReclass(
        states,
        states,
        states,
        gate_applied=True,
        bouts_before=1,
        bouts_after=2,
        flips=np.array([False]),
    )
    monkeypatch.setattr(rc, "reclassify_dir_to_csv", lambda *a, on_animal=None, **k: {"A1": fake})

    Manifest.build_from_standard(tmp_path)

    page = rc.ReclassifyPage(project_root=tmp_path)
    page._run()
    deadline = time.time() + 10
    while page._thread is not None and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.02)

    assert page._thread is None
    entry = Manifest.load(tmp_path).get("A1")
    assert entry.reclass_gate_applied is True
    assert (entry.reclass_flips_kept, entry.reclass_flips_cancelled) == (0, 0)


def test_rerun_warns_when_sleep_qc_already_flagged_and_can_cancel(
    qapp, tmp_path: Path, monkeypatch
):
    from PyQt6.QtWidgets import QMessageBox

    from ebb_viewer.pages import reclassify as rc

    out = tmp_path / "spindle_outputs" / "LFC_RSC"
    out.mkdir(parents=True)
    (out / "A1_x.csv").write_text("state,noise_prob\nn,0\n")
    (tmp_path / "standard").mkdir()
    (tmp_path / "standard" / "A1_PREPROCESSED.edf").touch()
    m = Manifest.build_from_standard(tmp_path)
    m._entries["A1"].sleep_qc = "ok"
    m.save()

    called = []
    monkeypatch.setattr(rc, "reclassify_dir_to_csv", lambda *a, **k: called.append(1) or {})
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

    page = rc.ReclassifyPage(project_root=tmp_path)
    page._run()

    assert page._thread is None and not called  # cancelled before starting
    assert Manifest.load(tmp_path).get("A1").sleep_qc == "ok"  # flags never reset


def test_gate_label_distinguishes_unknown_from_not_reclassified():
    from ebb_viewer.pages.reclassify import gate_label

    assert gate_label(False, None) == "—"
    assert gate_label(True, None).startswith("unknown")
    assert gate_label(True, True) == "applied"
    assert gate_label(True, False) == "not needed"
