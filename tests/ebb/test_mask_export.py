"""Tests for ebb.process.mask_export."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from ebb.process.mask_export import (
    IntervalRow,
    artifact_masks_to_intervals,
    build_state_intervals,
    clean_per_state_intervals,
    mask_to_intervals,
    write_animal_export,
    write_intervals_csv,
    write_meta_json,
)

FS = 250.0
WINSIZE = 4.0
SAMPLES_PER_EPOCH = int(FS * WINSIZE)  # 1000


def _write_state_csv(path: Path, rawstates, extra_cols=None) -> None:
    """Write a minimal Spindle scoring CSV with a ``rawstate`` column."""
    extra_cols = extra_cols or {}
    header = ["rawstate", *extra_cols.keys()]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for i, rs in enumerate(rawstates):
            w.writerow([rs, *(extra_cols[k][i] for k in extra_cols)])


def test_empty_mask_returns_empty_list():
    assert mask_to_intervals(np.array([], dtype=bool), FS) == []


def test_all_false_mask_returns_empty_list():
    assert mask_to_intervals(np.zeros(1000, dtype=bool), FS) == []


def test_all_true_mask_returns_single_full_interval():
    rows = mask_to_intervals(np.ones(1000, dtype=bool), FS)
    assert rows == [IntervalRow(start_s=0.0, end_s=4.0, start_sample=0, end_sample=1000)]


def test_single_run_in_middle():
    mask = np.zeros(1000, dtype=bool)
    mask[250:500] = True  # 1.0 s to 2.0 s at fs=250
    rows = mask_to_intervals(mask, FS)
    assert rows == [IntervalRow(start_s=1.0, end_s=2.0, start_sample=250, end_sample=500)]


def test_multiple_disjoint_runs():
    mask = np.zeros(1000, dtype=bool)
    mask[100:200] = True
    mask[400:450] = True
    mask[800:1000] = True  # touches the right edge
    rows = mask_to_intervals(mask, FS)
    assert [(r.start_sample, r.end_sample) for r in rows] == [(100, 200), (400, 450), (800, 1000)]


def test_leading_true_run():
    mask = np.zeros(500, dtype=bool)
    mask[0:100] = True
    rows = mask_to_intervals(mask, FS)
    assert rows == [IntervalRow(start_s=0.0, end_s=0.4, start_sample=0, end_sample=100)]


def test_trailing_true_run():
    mask = np.zeros(500, dtype=bool)
    mask[400:500] = True  # ends on last sample
    rows = mask_to_intervals(mask, FS)
    assert rows == [IntervalRow(start_s=1.6, end_s=2.0, start_sample=400, end_sample=500)]


def test_single_sample_run():
    mask = np.zeros(100, dtype=bool)
    mask[50] = True
    rows = mask_to_intervals(mask, FS)
    assert rows == [IntervalRow(start_s=50 / FS, end_s=51 / FS, start_sample=50, end_sample=51)]


def test_label_propagates_to_every_row():
    mask = np.zeros(100, dtype=bool)
    mask[10:20] = True
    mask[30:40] = True
    rows = mask_to_intervals(mask, FS, label="wake")
    assert all(r.label == "wake" for r in rows)


def test_seconds_use_supplied_fs():
    mask = np.zeros(200, dtype=bool)
    mask[100:200] = True
    rows = mask_to_intervals(mask, fs=100.0)
    assert rows == [IntervalRow(start_s=1.0, end_s=2.0, start_sample=100, end_sample=200)]


def test_2d_mask_raises():
    with pytest.raises(ValueError):
        mask_to_intervals(np.zeros((2, 100), dtype=bool), FS)


def test_end_sample_is_exclusive():
    """end_sample = N means the run covers samples [start, end), matching slicing."""
    mask = np.zeros(10, dtype=bool)
    mask[3:7] = True
    rows = mask_to_intervals(mask, FS)
    assert rows[0].end_sample == 7
    assert mask[rows[0].start_sample : rows[0].end_sample].all()
    assert not mask[rows[0].end_sample :].any()


def test_intervals_are_disjoint_and_sorted():
    rng = np.random.default_rng(0)
    mask = rng.random(10000) > 0.5
    rows = mask_to_intervals(mask, FS)
    samples = [(r.start_sample, r.end_sample) for r in rows]
    assert samples == sorted(samples)
    for (_, e1), (s2, _) in zip(samples, samples[1:]):
        assert e1 < s2  # at least one False between them


# ---------- build_state_intervals ----------


def test_state_intervals_single_epoch(tmp_path):
    csv_path = tmp_path / "states.csv"
    _write_state_csv(csv_path, ["w"])
    rows = build_state_intervals(csv_path, fs=FS, winsize=WINSIZE)
    assert rows == [IntervalRow(start_s=0.0, end_s=4.0, start_sample=0, end_sample=1000, label="wake")]


def test_state_intervals_runs_are_merged(tmp_path):
    csv_path = tmp_path / "states.csv"
    _write_state_csv(csv_path, ["w", "w", "n", "n", "n", "r", "w"])
    rows = build_state_intervals(csv_path, fs=FS, winsize=WINSIZE)
    assert [(r.start_sample, r.end_sample, r.label) for r in rows] == [
        (0, 2000, "wake"),
        (2000, 5000, "nrem"),
        (5000, 6000, "rem"),
        (6000, 7000, "wake"),
    ]


def test_state_intervals_cover_full_recording(tmp_path):
    """Every epoch should be in exactly one row; no gaps, no overlaps."""
    csv_path = tmp_path / "states.csv"
    labels = ["w", "n", "r", "w", "n", "n", "r", "r", "w"]
    _write_state_csv(csv_path, labels)
    rows = build_state_intervals(csv_path, fs=FS, winsize=WINSIZE)
    assert rows[0].start_sample == 0
    assert rows[-1].end_sample == len(labels) * SAMPLES_PER_EPOCH
    for prev, nxt in zip(rows, rows[1:]):
        assert prev.end_sample == nxt.start_sample
        assert prev.label != nxt.label  # otherwise they should have merged


def test_state_intervals_preserve_unknown_codes(tmp_path):
    csv_path = tmp_path / "states.csv"
    _write_state_csv(csv_path, ["w", "?", "?", "n"])
    rows = build_state_intervals(csv_path, fs=FS, winsize=WINSIZE)
    assert [r.label for r in rows] == ["wake", "?", "nrem"]


def test_state_intervals_custom_mapping(tmp_path):
    csv_path = tmp_path / "states.csv"
    _write_state_csv(csv_path, ["w", "n", "r"])
    rows = build_state_intervals(
        csv_path, fs=FS, winsize=WINSIZE, code_to_name={"w": "WAKE", "n": "NREM", "r": "REM"}
    )
    assert [r.label for r in rows] == ["WAKE", "NREM", "REM"]


def test_state_intervals_empty_csv(tmp_path):
    csv_path = tmp_path / "states.csv"
    _write_state_csv(csv_path, [])
    assert build_state_intervals(csv_path, fs=FS, winsize=WINSIZE) == []


def test_state_intervals_missing_column_raises(tmp_path):
    csv_path = tmp_path / "bad.csv"
    with open(csv_path, "w", newline="") as f:
        csv.writer(f).writerow(["state", "epoch"])
    with pytest.raises(ValueError, match="rawstate"):
        build_state_intervals(csv_path, fs=FS, winsize=WINSIZE)


def test_state_intervals_winsize_affects_sample_boundaries(tmp_path):
    csv_path = tmp_path / "states.csv"
    _write_state_csv(csv_path, ["w", "n"])
    rows = build_state_intervals(csv_path, fs=FS, winsize=2.0)  # 500 samples/epoch
    assert [(r.start_sample, r.end_sample) for r in rows] == [(0, 500), (500, 1000)]


# ---------- artifact_masks_to_intervals ----------


def test_artifact_intervals_inverts_psd_convention():
    """PSD masks store True=OK; intervals should cover the False (artifact) regions."""
    comm = np.ones(1000, dtype=bool)
    comm[100:200] = False  # commutator artifact 0.4–0.8 s
    rows = artifact_masks_to_intervals({"commutator": comm}, fs=FS)
    assert rows == [
        IntervalRow(start_s=0.4, end_s=0.8, start_sample=100, end_sample=200, label="commutator")
    ]


def test_artifact_intervals_label_per_source():
    comm = np.ones(1000, dtype=bool)
    comm[100:200] = False
    sd = np.ones(1000, dtype=bool)
    sd[500:600] = False
    rows = artifact_masks_to_intervals({"commutator": comm, "sd_threshold": sd}, fs=FS)
    labels_by_start = {r.start_sample: r.label for r in rows}
    assert labels_by_start == {100: "commutator", 500: "sd_threshold"}


def test_artifact_intervals_overlap_emitted_as_separate_rows():
    """Overlapping artifacts from different sources should both appear (not merged)."""
    comm = np.ones(1000, dtype=bool)
    comm[100:300] = False
    sd = np.ones(1000, dtype=bool)
    sd[200:400] = False
    rows = artifact_masks_to_intervals({"commutator": comm, "sd_threshold": sd}, fs=FS)
    assert len(rows) == 2
    spans = {(r.label, r.start_sample, r.end_sample) for r in rows}
    assert spans == {("commutator", 100, 300), ("sd_threshold", 200, 400)}


def test_artifact_intervals_all_clean_returns_empty():
    rows = artifact_masks_to_intervals(
        {"commutator": np.ones(500, dtype=bool), "sd_threshold": np.ones(500, dtype=bool)},
        fs=FS,
    )
    assert rows == []


def test_artifact_intervals_sorted_by_start_then_label():
    a = np.ones(1000, dtype=bool)
    a[600:700] = False
    a[100:200] = False
    b = np.ones(1000, dtype=bool)
    b[100:200] = False  # same start as a's first artifact → label tiebreak
    rows = artifact_masks_to_intervals({"sd_threshold": a, "commutator": b}, fs=FS)
    keys = [(r.start_sample, r.label) for r in rows]
    assert keys == sorted(keys)


def test_artifact_intervals_empty_dict():
    assert artifact_masks_to_intervals({}, fs=FS) == []


# ---------- clean_per_state_intervals ----------


def test_clean_per_state_state_minus_artifacts():
    """Wake epoch [0,500) with artifact [100,200) → two clean wake rows."""
    wake = np.zeros(1000, dtype=bool)
    wake[0:500] = True
    artifact_clean = np.ones(1000, dtype=bool)
    artifact_clean[100:200] = False  # an artifact spans this region
    rows = clean_per_state_intervals({"wake": wake}, artifact_clean, fs=FS)
    assert [(r.start_sample, r.end_sample, r.label) for r in rows] == [
        (0, 100, "wake"),
        (200, 500, "wake"),
    ]


def test_clean_per_state_artifact_outside_state_is_irrelevant():
    """Artifacts outside the state mask shouldn't fragment the state's clean run."""
    wake = np.zeros(1000, dtype=bool)
    wake[0:500] = True
    artifact_clean = np.ones(1000, dtype=bool)
    artifact_clean[700:800] = False  # artifact during NREM, not wake
    rows = clean_per_state_intervals({"wake": wake}, artifact_clean, fs=FS)
    assert [(r.start_sample, r.end_sample) for r in rows] == [(0, 500)]


def test_clean_per_state_multiple_states():
    wake = np.zeros(1000, dtype=bool)
    wake[0:300] = True
    nrem = np.zeros(1000, dtype=bool)
    nrem[300:1000] = True
    artifact_clean = np.ones(1000, dtype=bool)
    artifact_clean[150:200] = False  # in wake
    artifact_clean[500:550] = False  # in nrem
    rows = clean_per_state_intervals({"wake": wake, "nrem": nrem}, artifact_clean, fs=FS)
    assert [(r.start_sample, r.end_sample, r.label) for r in rows] == [
        (0, 150, "wake"),
        (200, 300, "wake"),
        (300, 500, "nrem"),
        (550, 1000, "nrem"),
    ]


def test_clean_per_state_fully_artifacted_state_returns_empty_for_that_state():
    wake = np.zeros(1000, dtype=bool)
    wake[0:200] = True
    nrem = np.zeros(1000, dtype=bool)
    nrem[200:1000] = True
    artifact_clean = np.ones(1000, dtype=bool)
    artifact_clean[0:200] = False  # all of wake is an artifact
    rows = clean_per_state_intervals({"wake": wake, "nrem": nrem}, artifact_clean, fs=FS)
    assert all(r.label == "nrem" for r in rows)


def test_clean_per_state_sorted_by_start_sample():
    wake = np.zeros(1000, dtype=bool)
    wake[100:200] = True
    wake[800:900] = True
    nrem = np.zeros(1000, dtype=bool)
    nrem[400:500] = True
    rows = clean_per_state_intervals(
        {"wake": wake, "nrem": nrem}, np.ones(1000, dtype=bool), fs=FS
    )
    starts = [r.start_sample for r in rows]
    assert starts == sorted(starts)


# ---------- writers ----------


def test_write_intervals_csv_writes_header_even_when_empty(tmp_path):
    path = tmp_path / "empty.csv"
    write_intervals_csv(path, [], label_column="state")
    with open(path) as f:
        rows = list(csv.reader(f))
    assert rows == [["start_s", "end_s", "start_sample", "end_sample", "state"]]


def test_write_intervals_csv_writes_rows(tmp_path):
    path = tmp_path / "states.csv"
    rows = [
        IntervalRow(start_s=0.0, end_s=4.0, start_sample=0, end_sample=1000, label="wake"),
        IntervalRow(start_s=4.0, end_s=8.0, start_sample=1000, end_sample=2000, label="nrem"),
    ]
    write_intervals_csv(path, rows, label_column="state")
    with open(path) as f:
        out = list(csv.reader(f))
    assert out == [
        ["start_s", "end_s", "start_sample", "end_sample", "state"],
        ["0.0", "4.0", "0", "1000", "wake"],
        ["4.0", "8.0", "1000", "2000", "nrem"],
    ]


def test_write_intervals_csv_label_column_configurable(tmp_path):
    path = tmp_path / "artifacts.csv"
    write_intervals_csv(path, [], label_column="source")
    with open(path) as f:
        header = next(csv.reader(f))
    assert header[-1] == "source"


def test_write_intervals_csv_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "deep" / "out.csv"
    write_intervals_csv(path, [], label_column="state")
    assert path.exists()


def test_write_meta_json_roundtrips(tmp_path):
    path = tmp_path / "meta.json"
    meta = {"fs": 250, "winsize": 4, "params": {"sd_nstd": 5, "sprob": 0.9}}
    write_meta_json(path, meta)
    assert json.loads(path.read_text()) == meta


def test_write_meta_json_serializes_paths_via_default_str(tmp_path):
    """Path objects in meta should round-trip via default=str rather than blowing up."""
    path = tmp_path / "meta.json"
    edf = tmp_path / "Mice-1234_PREPROCESSED.edf"
    write_meta_json(path, {"edf_path": edf})
    loaded = json.loads(path.read_text())
    assert loaded == {"edf_path": str(edf)}


def test_write_animal_export_writes_four_files(tmp_path):
    out = tmp_path / "exports"
    paths = write_animal_export(
        out_dir=out,
        animal_id="Mice-1234",
        combo="LFC_RSC",
        state_intervals=[IntervalRow(0.0, 4.0, 0, 1000, "wake")],
        artifact_intervals=[],
        clean_intervals=[IntervalRow(0.0, 4.0, 0, 1000, "wake")],
        meta={"fs": 250},
    )
    expected = {
        out / "Mice-1234_LFC_RSC_states.csv",
        out / "Mice-1234_LFC_RSC_artifacts.csv",
        out / "Mice-1234_LFC_RSC_clean_per_state.csv",
        out / "Mice-1234_LFC_RSC_meta.json",
    }
    assert set(paths.values()) == expected
    assert all(p.exists() for p in paths.values())


def test_write_animal_export_uses_correct_label_columns(tmp_path):
    paths = write_animal_export(
        out_dir=tmp_path,
        animal_id="A",
        combo="LFC_RSC",
        state_intervals=[],
        artifact_intervals=[],
        clean_intervals=[],
        meta={},
    )
    with open(paths["states"]) as f:
        assert next(csv.reader(f))[-1] == "state"
    with open(paths["artifacts"]) as f:
        assert next(csv.reader(f))[-1] == "source"
    with open(paths["clean_per_state"]) as f:
        assert next(csv.reader(f))[-1] == "state"
