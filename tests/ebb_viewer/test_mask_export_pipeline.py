"""Tests for the mask-export orchestration layer.

Covers the pure helpers (``resolve_paths`` and ``clean_mask_for_state``) and
``export_run``'s continue-on-error behavior. EDF-reading paths
(``_build_masks`` / ``export_animal`` happy path) are exercised at integration
time against real project data — they are not meaningfully testable with
mocks alone.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ebb_viewer.pipeline import mask_export as me
from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry

# ---------------------------------------------------------------------------
# Manifest builders
# ---------------------------------------------------------------------------


def _make_manifest(tmp_path: Path, animal_id: str, combo: str) -> Manifest:
    """Build a manifest (project combo = ``combo``) with one OK animal."""
    m = Manifest(tmp_path)
    m.combo = combo
    edf_rel = f"standard/{animal_id}_2025_01_01_00_00_00_PREPROCESSED.edf"
    (tmp_path / "standard").mkdir(parents=True, exist_ok=True)
    (tmp_path / edf_rel).touch()  # exists; contents irrelevant for path resolution
    entry = ManifestEntry(
        animal_id=animal_id,
        preprocessed_edf=edf_rel,
        has_spindle=True,
        sleep_qc="ok",
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

    paths = me.resolve_paths(tmp_path, manifest, "Mice-1")
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
    paths = me.resolve_paths(tmp_path, manifest, "Mice-1")
    assert paths.offset_csv == offset_csv


# ---------------------------------------------------------------------------
# _find_annotation_for_animal
# ---------------------------------------------------------------------------


def test_find_annotation_returns_none_when_dir_missing(tmp_path):
    assert me._find_annotation_for_animal(tmp_path / "nonexistent", "Mice-1") is None


def test_find_annotation_returns_none_when_dir_empty(tmp_path):
    (tmp_path / "annot").mkdir()
    assert me._find_annotation_for_animal(tmp_path / "annot", "Mice-1") is None


def test_find_annotation_returns_none_when_no_match_for_animal(tmp_path):
    d = tmp_path / "annot"
    d.mkdir()
    (d / "OtherMouse_notes.txt").write_text("...")
    assert me._find_annotation_for_animal(d, "Mice-1") is None


def test_find_annotation_matches_txt_by_animal_prefix(tmp_path):
    d = tmp_path / "annot"
    d.mkdir()
    target = d / "Mice-1_notes.txt"
    target.write_text("...")
    assert me._find_annotation_for_animal(d, "Mice-1") == target


def test_find_annotation_matches_csv_by_animal_prefix(tmp_path):
    d = tmp_path / "annot"
    d.mkdir()
    target = d / "Mice-1_notes.csv"
    target.write_text("...")
    assert me._find_annotation_for_animal(d, "Mice-1") == target


def test_find_annotation_prefers_txt_over_csv(tmp_path):
    """Mirrors EEG viewer's discovery: .txt matches come first."""
    d = tmp_path / "annot"
    d.mkdir()
    (d / "Mice-1_notes.csv").write_text("...")
    txt = d / "Mice-1_notes.txt"
    txt.write_text("...")
    assert me._find_annotation_for_animal(d, "Mice-1") == txt


def test_find_annotation_deterministic_when_multiple_txt(tmp_path):
    """With multiple matching .txts, the sorted-first one wins (deterministic)."""
    d = tmp_path / "annot"
    d.mkdir()
    (d / "Mice-1_a.txt").write_text("...")
    (d / "Mice-1_b.txt").write_text("...")
    assert me._find_annotation_for_animal(d, "Mice-1") == d / "Mice-1_a.txt"


def test_find_annotation_does_not_match_partial_prefix(tmp_path):
    """`Mice-1` must not match a file belonging to `Mice-10`."""
    d = tmp_path / "annot"
    d.mkdir()
    (d / "Mice-10_notes.txt").write_text("...")
    assert me._find_annotation_for_animal(d, "Mice-1") is None


def test_resolve_paths_raises_on_multiple_offset_csvs(tmp_path):
    """Convention is one offset CSV per project — ambiguity is an error."""
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    _drop_drink_npy(tmp_path, "Mice-1")
    drink_dir = tmp_path / "drink_masks"
    (drink_dir / "offsets_a.csv").write_text("Animal,Offset\nMice-1,1.0\n")
    (drink_dir / "offsets_b.csv").write_text("Animal,Offset\nMice-1,2.0\n")
    with pytest.raises(ValueError, match="Expected at most one offset CSV"):
        me.resolve_paths(tmp_path, manifest, "Mice-1")


def test_resolve_paths_drink_discovered_by_file_presence_only(tmp_path):
    """Drink file on disk is sufficient — manifest tracking is irrelevant for export."""
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    # No run.drink_mask set; just an .npy at the canonical path.
    drink_full = _drop_drink_npy(tmp_path, "Mice-1")
    paths = me.resolve_paths(tmp_path, manifest, "Mice-1")
    assert paths.drink == drink_full


def test_resolve_paths_finds_swd_when_present(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    swd_dir = tmp_path / "swd"
    swd_dir.mkdir()
    swd_path = swd_dir / "Mice-1_2025_01_01.mat"
    swd_path.touch()
    paths = me.resolve_paths(tmp_path, manifest, "Mice-1")
    assert paths.swd == swd_path


def test_resolve_paths_finds_swd_named_with_the_bare_animal_id(tmp_path):
    """Real projects name SWD files Mice-1256.mat (no underscore after the ID)."""
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    (tmp_path / "swd").mkdir()
    (tmp_path / "swd" / "Mice-10.mat").touch()  # a different animal sharing the prefix
    swd_path = tmp_path / "swd" / "Mice-1.mat"
    swd_path.touch()
    assert me.resolve_paths(tmp_path, manifest, "Mice-1").swd == swd_path


def test_resolve_paths_no_swd_when_missing(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    paths = me.resolve_paths(tmp_path, manifest, "Mice-1")
    assert paths.swd is None


def test_resolve_paths_unknown_animal_raises(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    with pytest.raises(ValueError, match="not in manifest"):
        me.resolve_paths(tmp_path, manifest, "Mice-99")


def test_resolve_paths_no_spindle_files_raises(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    manifest.get("Mice-1").has_spindle = False
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    with pytest.raises(ValueError, match="no spindle files"):
        me.resolve_paths(tmp_path, manifest, "Mice-1")


def test_resolve_paths_missing_edf_raises(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    (tmp_path / manifest.get("Mice-1").preprocessed_edf).unlink()
    with pytest.raises(ValueError, match="EDF not found"):
        me.resolve_paths(tmp_path, manifest, "Mice-1")


def test_resolve_paths_missing_state_csv_raises(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    # No state CSV created.
    with pytest.raises(ValueError, match="No state CSV found"):
        me.resolve_paths(tmp_path, manifest, "Mice-1")


def test_resolve_paths_no_drink_when_file_missing(tmp_path):
    manifest = _make_manifest(tmp_path, "Mice-1", "LFC_RSC")
    _make_state_csv(tmp_path, "Mice-1", "LFC_RSC")
    paths = me.resolve_paths(tmp_path, manifest, "Mice-1")
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

    def fake_export_animal(project_root, out_dir, manifest, animal_id, params):
        calls.append(animal_id)
        if animal_id == "BAD":
            return me.AnimalExportResult(animal_id=animal_id, status="error", message="boom")
        return me.AnimalExportResult(animal_id=animal_id, status="ok")

    monkeypatch.setattr(me, "export_animal", fake_export_animal)

    animal_ids = ["A", "BAD", "B"]
    result = me.export_run(tmp_path, out_dir, manifest, params={}, animal_ids=animal_ids)

    assert calls == animal_ids  # ran every animal despite the failure in the middle
    assert len(result.successes) == 2
    assert len(result.failures) == 1
    assert result.failures[0].animal_id == "BAD"
    assert "boom" in result.failures[0].message


def test_export_run_creates_out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        me,
        "export_animal",
        lambda *a, **kw: me.AnimalExportResult(animal_id="A", status="ok"),
    )
    out_dir = tmp_path / "exports" / "fresh"
    assert not out_dir.exists()
    me.export_run(tmp_path, out_dir, Manifest(tmp_path), params={}, animal_ids=["A"])
    assert out_dir.is_dir()


def test_export_run_invokes_progress_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(
        me,
        "export_animal",
        lambda *a, **kw: me.AnimalExportResult(animal_id=a[3], status="ok"),
    )
    progress = []
    me.export_run(
        tmp_path,
        tmp_path / "out",
        Manifest(tmp_path),
        params={},
        animal_ids=["A", "B"],
        progress_cb=lambda an, d, t: progress.append((an, d, t)),
    )
    assert progress == [("A", 1, 2), ("B", 2, 2)]


def test_export_run_progress_cb_failure_is_swallowed(tmp_path, monkeypatch):
    """A buggy UI callback shouldn't abort the export batch."""
    monkeypatch.setattr(
        me,
        "export_animal",
        lambda *a, **kw: me.AnimalExportResult(animal_id=a[3], status="ok"),
    )

    def bad_cb(*_):
        raise RuntimeError("UI exploded")

    result = me.export_run(
        tmp_path,
        tmp_path / "out",
        Manifest(tmp_path),
        params={},
        animal_ids=["A", "B"],
        progress_cb=bad_cb,
    )
    assert len(result.successes) == 2


# ---------------------------------------------------------------------------
# default_animals
# ---------------------------------------------------------------------------


def test_default_animals_returns_only_ok(tmp_path):
    m = Manifest(tmp_path)
    for animal_id, status in (("A", "ok"), ("B", "needs_review"), ("C", "ok"), ("D", None)):
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id,
            preprocessed_edf=f"{animal_id}.edf",
            has_spindle=True,
            sleep_qc=status,
        )
    assert me.default_animals(m) == ["A", "C"]


# ---------------------------------------------------------------------------
# fs-mismatch guard
# ---------------------------------------------------------------------------


def test_build_masks_raises_on_fs_mismatch(tmp_path):
    """_build_masks must abort when the user-set fs disagrees with the EDF
    header — mask windows are computed as winsize*fs / radius*fs and would
    otherwise silently run at the wrong sample count."""
    paths = me.ResolvedPaths(
        edf=tmp_path / "AM001_PREPROCESSED.edf",
        state=tmp_path / "AM001_states.csv",
        drink=None,
        swd=None,
        offset_csv=None,
    )

    reader = MagicMock()
    reader.__enter__ = MagicMock(return_value=reader)
    reader.__exit__ = MagicMock(return_value=False)
    reader.header.samples_per_record = [250, 250, 250, 250]  # file is 250 Hz

    with patch.object(me.edf, "Reader", return_value=reader):
        with pytest.raises(ValueError, match=r"file is 250 Hz but caller passed fs=500"):
            me._build_masks(paths, params={"fs": 500, "channels": [0, 1, 2]})


# ---------------------------------------------------------------------------
# commutator amplitude limit
# ---------------------------------------------------------------------------


class _StopAfterCommutator(Exception):
    """Raised by the patched commutator mask to end ``_build_masks`` early."""


def _commutator_value_used(tmp_path, params):
    """The ``value`` that ``_build_masks`` passes to the commutator mask for ``params``."""
    paths = me.ResolvedPaths(
        edf=tmp_path / "AM001_PREPROCESSED.edf",
        state=tmp_path / "AM001_states.csv",
        drink=None,
        swd=None,
        offset_csv=None,
    )
    reader = MagicMock()
    reader.__enter__ = MagicMock(return_value=reader)
    reader.__exit__ = MagicMock(return_value=False)
    pro = MagicMock()
    pro.shape = (1000,)
    seen = {}

    def fake_commutator(_pro, **kwargs):
        seen.update(kwargs)
        raise _StopAfterCommutator

    with (
        patch.object(me.edf, "Reader", return_value=reader),
        patch.object(me, "assert_fs_matches"),
        patch.object(me, "parse_edf_start_datetime"),
        patch.object(me, "producer", return_value=pro),
        patch.object(me.masking, "state", return_value=np.ones(1000, dtype=bool)),
        patch.object(me.masking, "commutator_threshold", side_effect=fake_commutator),
    ):
        with pytest.raises(_StopAfterCommutator):
            me._build_masks(paths, params=params)
    return seen["value"]


def test_build_masks_uses_the_commutator_limit_from_the_params(tmp_path):
    assert _commutator_value_used(tmp_path, {"comm_value": 3500}) == 3500


def test_build_masks_commutator_limit_defaults_to_2000_uv(tmp_path):
    assert _commutator_value_used(tmp_path, {}) == 2000
