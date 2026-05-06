"""Tests for the mask-export orchestration layer.

Covers the pure helpers (``resolve_paths`` and ``clean_mask_for_state``) and
``export_run``'s continue-on-error behavior. EDF-reading paths
(``_build_masks`` / ``export_animal`` happy path) are exercised at integration
time against real project data — they are not meaningfully testable with
mocks alone.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ebb_viewer.pipeline import mask_export as me
from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry, RunEntry

# ---------------------------------------------------------------------------
# Manifest builders
# ---------------------------------------------------------------------------


def _make_manifest(tmp_path: Path, animal_id: str, combo: str) -> Manifest:
    """Build a manifest with one OK run for a single animal/combo."""
    m = Manifest(tmp_path)
    edf_rel = f"standard/{animal_id}_2025_01_01_00_00_00_PREPROCESSED.edf"
    (tmp_path / "standard").mkdir(parents=True, exist_ok=True)
    (tmp_path / edf_rel).touch()  # exists; contents irrelevant for path resolution
    entry = ManifestEntry(
        animal_id=animal_id,
        preprocessed_edf=edf_rel,
        runs={combo: RunEntry(sleep_qc="ok")},
    )
    m._entries[animal_id] = entry
    return m


def _drop_drink_npy(tmp_path: Path, animal_id: str) -> Path:
    """Create a drink_masks/<animal>.npy file at the canonical path."""
    path = tmp_path / "drink_masks" / f"{animal_id}.npy"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def _make_state_csv(tmp_path: Path, animal_id: str, combo: str) -> Path:
    out = tmp_path / "spindle_outputs" / combo
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / f"{animal_id}_2025_01_01_states.csv"
    csv_path.write_text("rawstate\nw\nn\nr\n")
    return csv_path


# ---------------------------------------------------------------------------
# resolve_paths
# ---------------------------------------------------------------------------


def test_resolve_paths_finds_edf_state_and_drink(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    state_csv = _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    drink_full = _drop_drink_npy(tmp_path, "Mice-1")

    paths = me.resolve_paths(tmp_path, manifest, "Mice-1", "LFC_RSC")
    assert paths.edf == tmp_path / "standard/Mice-1_2025_01_01_00_00_00_PREPROCESSED.edf"
    assert paths.state == state_csv
    assert paths.drink == drink_full
    assert paths.swd is None  # no swd dir → None
    assert paths.offset_csv is None  # no offset CSV in drink_masks/


def test_resolve_paths_finds_offset_csv_in_drink_masks_dir(tmp_path):
    """Any *.csv in drink_masks/ is treated as the offset CSV (matches Drink Mask page)."""
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    _drop_drink_npy(tmp_path, "Mice-1")
    offset_csv = tmp_path / "drink_masks" / "offsets.csv"
    offset_csv.write_text("Animal,Offset\nMice-1,3.5\n")
    paths = me.resolve_paths(tmp_path, manifest, "Mice-1", "LFC_RSC")
    assert paths.offset_csv == offset_csv


def test_resolve_paths_drink_discovered_by_file_presence_only(tmp_path):
    """Drink file on disk is sufficient — manifest tracking is irrelevant for export."""
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    # No run.drink_mask set; just an .npy at the canonical path.
    drink_full = _drop_drink_npy(tmp_path, "Mice-1")
    paths = me.resolve_paths(tmp_path, manifest, "Mice-1", "LFC_RSC")
    assert paths.drink == drink_full


def test_resolve_paths_finds_swd_when_present(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    swd_dir = tmp_path / "swd"
    swd_dir.mkdir()
    swd_path = swd_dir / "Mice-1_2025_01_01.mat"
    swd_path.touch()
    paths = me.resolve_paths(tmp_path, manifest, "Mice-1", "LFC_RSC")
    assert paths.swd == swd_path


def test_resolve_paths_no_swd_when_missing(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    paths = me.resolve_paths(tmp_path, manifest, "Mice-1", "LFC_RSC")
    assert paths.swd is None


def test_resolve_paths_unknown_animal_raises(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    with pytest.raises(ValueError, match="not in manifest"):
        me.resolve_paths(tmp_path, manifest, "Mice-99", "LFC_RSC")


def test_resolve_paths_unknown_combo_raises(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    with pytest.raises(ValueError, match="no run for combo"):
        me.resolve_paths(tmp_path, manifest, "Mice-1", "LSC_RSC")


def test_resolve_paths_missing_edf_raises(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    (tmp_path / manifest.get("Mice-1").preprocessed_edf).unlink()
    with pytest.raises(ValueError, match="EDF not found"):
        me.resolve_paths(tmp_path, manifest, "Mice-1", "LFC_RSC")


def test_resolve_paths_missing_state_csv_raises(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    # No state CSV created.
    with pytest.raises(ValueError, match="No state CSV found"):
        me.resolve_paths(tmp_path, manifest, "Mice-1", "LFC_RSC")


def test_resolve_paths_no_drink_when_file_missing(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    paths = me.resolve_paths(tmp_path, manifest, "Mice-1", "LFC_RSC")
    assert paths.drink is None


# ---------------------------------------------------------------------------
# clean_mask_for_state
# ---------------------------------------------------------------------------


def test_clean_mask_for_pure_wake_applies_sd_uniformly():
    base = np.ones(100, dtype=bool)
    sd = np.ones(100, dtype=bool)
    sd[20:40] = False  # SD-rejected region
    out = me.clean_mask_for_state(["w"], base, sd, wake_sub_mask=None)
    assert not out[20:40].any()
    assert out[:20].all() and out[40:].all()


def test_clean_mask_for_non_wake_state_ignores_sd():
    """SD threshold doesn't apply to NREM/REM, even if it'd reject samples."""
    base = np.ones(100, dtype=bool)
    sd = np.zeros(100, dtype=bool)  # SD says everything is bad
    out_nrem = me.clean_mask_for_state(["n"], base, sd, wake_sub_mask=None)
    out_rem = me.clean_mask_for_state(["r"], base, sd, wake_sub_mask=None)
    assert out_nrem.all()
    assert out_rem.all()


def test_clean_mask_for_mixed_wake_group_applies_sd_only_to_wake():
    """For 'all' (wake+nrem+rem), SD gates wake samples but leaves others alone."""
    base = np.ones(100, dtype=bool)
    sd = np.ones(100, dtype=bool)
    sd[10:30] = False
    sd[60:80] = False
    wake_sub = np.zeros(100, dtype=bool)
    wake_sub[0:50] = True  # wake = first half

    out = me.clean_mask_for_state(["w", "n", "r"], base, sd, wake_sub_mask=wake_sub)

    # Wake samples in 10:30 are SD-rejected → False.
    assert not out[10:30].any()
    # Wake samples 30:50 are clean.
    assert out[30:50].all()
    # Non-wake samples 60:80 should NOT be SD-rejected.
    assert out[60:80].all()


def test_clean_mask_mixed_wake_without_sub_mask_raises():
    base = np.ones(100, dtype=bool)
    sd = np.ones(100, dtype=bool)
    with pytest.raises(ValueError, match="wake_sub_mask"):
        me.clean_mask_for_state(["w", "n", "r"], base, sd, wake_sub_mask=None)


def test_clean_mask_respects_base_artifacts():
    """Base artifacts (commutator, drink, etc.) carry through regardless of state."""
    base = np.ones(100, dtype=bool)
    base[50:60] = False  # artifact
    sd = np.ones(100, dtype=bool)
    out = me.clean_mask_for_state(["n"], base, sd, wake_sub_mask=None)
    assert not out[50:60].any()


# ---------------------------------------------------------------------------
# export_run continues on error
# ---------------------------------------------------------------------------


def test_export_run_collects_failures_and_continues(tmp_path, monkeypatch):
    """One animal blowing up shouldn't abort the rest; failure goes in the result."""
    manifest = Manifest(tmp_path)
    out_dir = tmp_path / "exports" / "test"

    calls = []

    def fake_export_animal(project_root, out_dir, manifest, animal_id, combo, params):
        calls.append((animal_id, combo))
        if animal_id == "BAD":
            return me.AnimalExportResult(
                animal_id=animal_id, combo=combo, status="error", message="boom"
            )
        return me.AnimalExportResult(animal_id=animal_id, combo=combo, status="ok")

    monkeypatch.setattr(me, "export_animal", fake_export_animal)

    pairs = [("A", "LFC_RSC"), ("BAD", "LFC_RSC"), ("B", "LSC_RSC")]
    result = me.export_run(tmp_path, out_dir, manifest, params={}, pairs=pairs)

    assert calls == pairs  # ran every animal despite the failure in the middle
    assert len(result.successes) == 2
    assert len(result.failures) == 1
    assert result.failures[0].animal_id == "BAD"
    assert "boom" in result.failures[0].message


def test_export_run_creates_out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        me,
        "export_animal",
        lambda *a, **kw: me.AnimalExportResult(animal_id="A", combo="X", status="ok"),
    )
    out_dir = tmp_path / "exports" / "fresh"
    assert not out_dir.exists()
    me.export_run(tmp_path, out_dir, Manifest(tmp_path), params={}, pairs=[("A", "X")])
    assert out_dir.is_dir()


def test_export_run_invokes_progress_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(
        me,
        "export_animal",
        lambda *a, **kw: me.AnimalExportResult(animal_id=a[3], combo=a[4], status="ok"),
    )
    progress = []
    me.export_run(
        tmp_path,
        tmp_path / "out",
        Manifest(tmp_path),
        params={},
        pairs=[("A", "X"), ("B", "Y")],
        progress_cb=lambda an, co, d, t: progress.append((an, co, d, t)),
    )
    assert progress == [("A", "X", 1, 2), ("B", "Y", 2, 2)]


def test_export_run_progress_cb_failure_is_swallowed(tmp_path, monkeypatch):
    """A buggy UI callback shouldn't abort the export batch."""
    monkeypatch.setattr(
        me,
        "export_animal",
        lambda *a, **kw: me.AnimalExportResult(animal_id=a[3], combo=a[4], status="ok"),
    )

    def bad_cb(*_):
        raise RuntimeError("UI exploded")

    result = me.export_run(
        tmp_path,
        tmp_path / "out",
        Manifest(tmp_path),
        params={},
        pairs=[("A", "X"), ("B", "Y")],
        progress_cb=bad_cb,
    )
    assert len(result.successes) == 2


# ---------------------------------------------------------------------------
# default_pairs
# ---------------------------------------------------------------------------


def test_default_pairs_returns_only_ok_runs(tmp_path):
    m = Manifest(tmp_path)
    m._entries["A"] = ManifestEntry(
        animal_id="A",
        preprocessed_edf="x.edf",
        runs={
            "LFC_RSC": RunEntry(sleep_qc="ok"),
            "LSC_RSC": RunEntry(sleep_qc="rejected"),
        },
    )
    m._entries["B"] = ManifestEntry(
        animal_id="B",
        preprocessed_edf="y.edf",
        runs={"LFC_RSC": RunEntry(sleep_qc="needs_review")},
    )
    m._entries["C"] = ManifestEntry(
        animal_id="C",
        preprocessed_edf="z.edf",
        runs={"LSC_RSC": RunEntry(sleep_qc="ok")},
    )
    pairs = me.default_pairs(m)
    assert sorted(pairs) == [("A", "LFC_RSC"), ("C", "LSC_RSC")]
