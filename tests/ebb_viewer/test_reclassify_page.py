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
    fake = NremReclass(states, states, states, gate_applied=True, bouts_before=1, bouts_after=2)
    monkeypatch.setattr(rc, "reclassify_dir_to_csv", lambda *a, on_animal=None, **k: {"A1": fake})

    Manifest.build_from_standard(tmp_path)

    page = rc.ReclassifyPage(project_root=tmp_path)
    page._run()
    deadline = time.time() + 10
    while page._thread is not None and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.02)

    assert page._thread is None
    assert Manifest.load(tmp_path).get("A1").reclass_gate_applied is True
