"""Tests for pipeline/manifest.py.

Covers:
- save / load round-trip
- old-format migration (including notes preservation)
- flag_sleep_qc: one-ok invariant, cascade-rejection, restoration, psd cleanup
- reset_sleep_qc: sibling restoration, psd cleanup
- flag_psd: sleep_qc guard, drink_mask management
- add_run: auto-rejection when ok run exists, source_combo bypass
- load() integrity checks: multi-ok repair, orphaned rejected_by cleanup
- build_from_standard: disk scanning, auto-rejection of new combos
- filtered views: pending_sleep_qc, needs_review, needs_rerun,
                  pending_psd_review, needs_drink_mask, needs_drink_mask_rerun,
                  pending_rerun_review
- input validation errors
"""

import json
import warnings
from pathlib import Path

import pytest

from ebb_viewer.pipeline.manifest import (
    Manifest,
    ManifestEntry,
    RunEntry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manifest(tmp_path: Path, animals: dict[str, dict]) -> Manifest:
    """Build and save a manifest from a dict of {animal_id: {combo: RunEntry}}."""
    m = Manifest(tmp_path)
    for animal_id, runs in animals.items():
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id,
            preprocessed_edf=f"standard/{animal_id}_PREPROCESSED.edf",
            runs=runs,
        )
    m.save()
    return m


def _reload(m: Manifest) -> Manifest:
    return Manifest.load(m.project_root)


# ---------------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------------

def test_load_missing_file_returns_empty(tmp_path):
    m = Manifest.load(tmp_path)
    assert len(m) == 0


def test_save_load_roundtrip(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="needs_drink_mask")},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
    })
    m2 = _reload(m)

    assert m2.get_run("AM001", "LFC_RSC").sleep_qc == "ok"
    assert m2.get_run("AM001", "LFC_RSC").psd_status == "needs_drink_mask"
    assert m2.get_run("AM002", "LFC_RSC").sleep_qc == "needs_review"


def test_save_is_atomic(tmp_path):
    """Ensure no partial-write .tmp file is left behind after save."""
    m = _make_manifest(tmp_path, {"AM001": {"LFC_RSC": RunEntry()}})
    assert not (tmp_path / "manifest.json.tmp").exists()
    assert (tmp_path / "manifest.json").exists()


# ---------------------------------------------------------------------------
# Old-format migration
# ---------------------------------------------------------------------------

def _write_old_format(tmp_path: Path, data: dict) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps(data))


def test_migration_basic(tmp_path):
    _write_old_format(tmp_path, {
        "AM001": {
            "preprocessed_edf": "standard/AM001_PREPROCESSED.edf",
            "spindle_channels": "LFC_RSC",
            "sleep_qc": "ok",
            "psd_status": "needs_drink_mask",
            "drink_mask": None,
            "rerun_channels": None,
        }
    })
    m = Manifest.load(tmp_path)
    run = m.get_run("AM001", "LFC_RSC")
    assert run is not None
    assert run.sleep_qc == "ok"
    assert run.psd_status == "needs_drink_mask"


def test_migration_rerun_channels_status(tmp_path):
    """Old 'rerun_channels' sleep_qc value maps to 'needs_rerun'."""
    _write_old_format(tmp_path, {
        "AM001": {
            "preprocessed_edf": "standard/AM001_PREPROCESSED.edf",
            "spindle_channels": "LFC_RSC",
            "sleep_qc": "rerun_channels",
            "rerun_channels": "LSC_RSC",
            "psd_status": None,
            "drink_mask": None,
        }
    })
    m = Manifest.load(tmp_path)
    run = m.get_run("AM001", "LFC_RSC")
    assert run.sleep_qc == "needs_rerun"
    assert run.rerun_combo == "LSC_RSC"


def test_migration_preserves_notes(tmp_path):
    _write_old_format(tmp_path, {
        "AM001": {
            "preprocessed_edf": "standard/AM001_PREPROCESSED.edf",
            "spindle_channels": "LFC_RSC",
            "sleep_qc": None,
            "psd_status": None,
            "drink_mask": None,
            "rerun_channels": None,
            "notes": "check this animal",
        }
    })
    m = Manifest.load(tmp_path)
    assert m.get("AM001").notes == "check this animal"


# ---------------------------------------------------------------------------
# flag_sleep_qc — one-ok invariant
# ---------------------------------------------------------------------------

def test_flag_ok_cascade_rejects_siblings(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc=None),
            "LSC_RSC": RunEntry(sleep_qc="needs_review"),
            "RSC_LSC": RunEntry(sleep_qc=None),
        }
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "ok")

    assert m.get_run("AM001", "LFC_RSC").sleep_qc == "ok"
    assert m.get_run("AM001", "LSC_RSC").sleep_qc == "rejected"
    assert m.get_run("AM001", "RSC_LSC").sleep_qc == "rejected"


def test_flag_ok_cascade_stores_prev_status(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc=None),
            "LSC_RSC": RunEntry(sleep_qc="needs_review"),
        }
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "ok")

    sibling = m.get_run("AM001", "LSC_RSC")
    assert sibling.prev_sleep_qc == "needs_review"
    assert sibling.rejected_by == "LFC_RSC"


def test_flag_ok_does_not_touch_already_rejected_siblings(tmp_path):
    """A sibling that was already explicitly rejected keeps its existing metadata."""
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc=None),
            "LSC_RSC": RunEntry(sleep_qc="rejected", rejected_by=None),
        }
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "ok")

    sibling = m.get_run("AM001", "LSC_RSC")
    assert sibling.sleep_qc == "rejected"
    assert sibling.rejected_by is None  # untouched


def test_flag_ok_clears_own_cascade_metadata(tmp_path):
    """The run being set to ok should have no cascade metadata itself."""
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc="rejected", rejected_by="LSC_RSC", prev_sleep_qc="needs_review"),
        }
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "ok")

    run = m.get_run("AM001", "LFC_RSC")
    assert run.prev_sleep_qc is None
    assert run.rejected_by is None


def test_unok_restores_cascade_siblings(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc=None),
            "LSC_RSC": RunEntry(sleep_qc="needs_review"),
        }
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "ok")
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_review")

    sibling = m.get_run("AM001", "LSC_RSC")
    assert sibling.sleep_qc == "needs_review"
    assert sibling.prev_sleep_qc is None
    assert sibling.rejected_by is None


def test_unok_does_not_restore_independently_rejected_siblings(tmp_path):
    """Siblings rejected before the cascade (rejected_by=None) stay rejected."""
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc=None),
            "LSC_RSC": RunEntry(sleep_qc="rejected", rejected_by=None),
        }
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "ok")
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_review")

    assert m.get_run("AM001", "LSC_RSC").sleep_qc == "rejected"


def test_unok_clears_psd_status(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="needs_drink_mask")}
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_review")

    run = m.get_run("AM001", "LFC_RSC")
    assert run.psd_status is None
    assert run.drink_mask is None


def test_leaving_rejected_clears_cascade_metadata(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(
                sleep_qc="rejected",
                rejected_by="LSC_RSC",
                prev_sleep_qc="needs_review",
            )
        }
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_review")

    run = m.get_run("AM001", "LFC_RSC")
    assert run.sleep_qc == "needs_review"
    assert run.prev_sleep_qc is None
    assert run.rejected_by is None


def test_flag_sleep_qc_persisted(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": {"LFC_RSC": RunEntry()}})
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_review")
    assert _reload(m).get_run("AM001", "LFC_RSC").sleep_qc == "needs_review"


def test_flag_needs_rerun_stores_combo(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": {"LFC_RSC": RunEntry()}})
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_rerun", rerun_combo="LSC_RSC")

    run = m.get_run("AM001", "LFC_RSC")
    assert run.sleep_qc == "needs_rerun"
    assert run.rerun_combo == "LSC_RSC"


# ---------------------------------------------------------------------------
# reset_sleep_qc
# ---------------------------------------------------------------------------

def test_reset_restores_cascade_siblings(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc=None),
            "LSC_RSC": RunEntry(sleep_qc="needs_review"),
        }
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "ok")
    m.reset_sleep_qc("AM001", "LFC_RSC")

    assert m.get_run("AM001", "LFC_RSC").sleep_qc is None
    sibling = m.get_run("AM001", "LSC_RSC")
    assert sibling.sleep_qc == "needs_review"
    assert sibling.rejected_by is None


def test_reset_clears_psd_status(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="ok")}
    })
    m.reset_sleep_qc("AM001", "LFC_RSC")

    run = m.get_run("AM001", "LFC_RSC")
    assert run.psd_status is None
    assert run.drink_mask is None


def test_reset_non_ok_run_is_safe(tmp_path):
    """reset_sleep_qc on a non-ok run should not raise or corrupt state."""
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="needs_review")}
    })
    m.reset_sleep_qc("AM001", "LFC_RSC")
    assert m.get_run("AM001", "LFC_RSC").sleep_qc is None


# ---------------------------------------------------------------------------
# flag_psd
# ---------------------------------------------------------------------------

def test_flag_psd_requires_ok_sleep_qc(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="needs_review")}
    })
    with pytest.raises(ValueError, match="sleep_qc"):
        m.flag_psd("AM001", "LFC_RSC", "ok")


def test_flag_psd_sets_status(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")}
    })
    m.flag_psd("AM001", "LFC_RSC", "needs_drink_mask")
    assert m.get_run("AM001", "LFC_RSC").psd_status == "needs_drink_mask"


def test_flag_psd_drink_mask_applied_sets_path(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")}
    })
    m.flag_psd("AM001", "LFC_RSC", "drink_mask_applied")
    run = m.get_run("AM001", "LFC_RSC")
    assert run.psd_status == "drink_mask_applied"
    assert run.drink_mask == "drink_masks/AM001.npy"


def test_flag_psd_ok_clears_drink_mask(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="drink_mask_applied",
                                      drink_mask="drink_masks/AM001.npy")}
    })
    m.flag_psd("AM001", "LFC_RSC", "ok")
    assert m.get_run("AM001", "LFC_RSC").drink_mask is None


def test_flag_psd_invalid_status(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")}})
    with pytest.raises(ValueError, match="Invalid psd_status"):
        m.flag_psd("AM001", "LFC_RSC", "bogus")


# ---------------------------------------------------------------------------
# add_run
# ---------------------------------------------------------------------------

def test_add_run_creates_bare_run_when_no_ok(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": {}})
    run = m.add_run("AM001", "LFC_RSC")
    assert run.sleep_qc is None
    assert run.rejected_by is None


def test_add_run_auto_rejects_when_ok_exists(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")}
    })
    run = m.add_run("AM001", "LSC_RSC")
    assert run.sleep_qc == "rejected"
    assert run.rejected_by == "LFC_RSC"


def test_add_run_with_source_combo_never_auto_rejects(tmp_path):
    """Deliberate reruns always start unreviewed regardless of existing ok run."""
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")}
    })
    run = m.add_run("AM001", "LSC_RSC", source_combo="LFC_RSC")
    assert run.sleep_qc is None
    assert run.rejected_by is None


def test_add_run_returns_existing_without_overwriting(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="needs_review")}
    })
    run = m.add_run("AM001", "LFC_RSC")
    assert run.sleep_qc == "needs_review"


# ---------------------------------------------------------------------------
# load() integrity checks
# ---------------------------------------------------------------------------

def test_load_fixes_multiple_ok_runs(tmp_path):
    """If the JSON has two ok runs, load() keeps the first and cascade-rejects the rest."""
    data = {
        "AM001": {
            "preprocessed_edf": "standard/AM001_PREPROCESSED.edf",
            "notes": "",
            "runs": {
                "LFC_RSC": {"sleep_qc": "ok", "rerun_combo": None, "source_combo": None,
                            "psd_status": None, "drink_mask": None,
                            "prev_sleep_qc": None, "rejected_by": None},
                "LSC_RSC": {"sleep_qc": "ok", "rerun_combo": None, "source_combo": None,
                            "psd_status": None, "drink_mask": None,
                            "prev_sleep_qc": None, "rejected_by": None},
            }
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(data))

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m = Manifest.load(tmp_path)
    assert any("multiple ok runs" in str(x.message) for x in w)

    combos = {c: r.sleep_qc for c, r in m.get("AM001").runs.items()}
    ok_count = sum(1 for s in combos.values() if s == "ok")
    assert ok_count == 1


def test_load_clears_orphaned_rejected_by(tmp_path):
    """rejected_by pointing at a missing/non-ok combo should be cleared."""
    data = {
        "AM001": {
            "preprocessed_edf": "standard/AM001_PREPROCESSED.edf",
            "notes": "",
            "runs": {
                "LFC_RSC": {"sleep_qc": "rejected", "rerun_combo": None, "source_combo": None,
                            "psd_status": None, "drink_mask": None,
                            "prev_sleep_qc": "needs_review",
                            "rejected_by": "LSC_RSC"},  # LSC_RSC not present
            }
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(data))
    m = Manifest.load(tmp_path)

    run = m.get_run("AM001", "LFC_RSC")
    assert run.rejected_by is None
    assert run.prev_sleep_qc is None


# ---------------------------------------------------------------------------
# build_from_standard
# ---------------------------------------------------------------------------

def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def test_build_picks_up_new_edfs(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "standard" / "AM002_PREPROCESSED.edf")
    m = Manifest.build_from_standard(tmp_path)
    assert "AM001" in m
    assert "AM002" in m


def test_build_picks_up_spindle_outputs(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_states.csv")
    m = Manifest.build_from_standard(tmp_path)
    assert m.get_run("AM001", "LFC_RSC") is not None


def test_build_auto_rejects_new_combo_when_ok_exists(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_states.csv")
    m = Manifest.build_from_standard(tmp_path)
    m.flag_sleep_qc("AM001", "LFC_RSC", "ok")

    # New combo appears on disk
    _touch(tmp_path / "spindle_outputs" / "LSC_RSC" / "AM001_states.csv")
    m2 = Manifest.build_from_standard(tmp_path)

    new_run = m2.get_run("AM001", "LSC_RSC")
    assert new_run.sleep_qc == "rejected"
    assert new_run.rejected_by == "LFC_RSC"


def test_build_does_not_overwrite_existing_status(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_states.csv")
    m = Manifest.build_from_standard(tmp_path)
    m.flag_sleep_qc("AM001", "LFC_RSC", "ok")

    m2 = Manifest.build_from_standard(tmp_path)
    assert m2.get_run("AM001", "LFC_RSC").sleep_qc == "ok"


# ---------------------------------------------------------------------------
# Filtered views
# ---------------------------------------------------------------------------

def test_pending_sleep_qc(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc=None)},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="ok")},
    })
    pending = m.pending_sleep_qc()
    animal_ids = [e.animal_id for e, _ in pending]
    assert "AM001" in animal_ids
    assert "AM002" not in animal_ids


def test_needs_review(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="ok")},
    })
    assert len(m.needs_review()) == 1
    assert m.needs_review()[0][0].animal_id == "AM001"


def test_needs_rerun(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="needs_rerun", rerun_combo="LSC_RSC")},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="ok")},
    })
    assert len(m.needs_rerun()) == 1


def test_pending_psd_review(tmp_path):
    psd_file = tmp_path / "psd" / "psds_LFC_RSC.pkl"
    psd_file.parent.mkdir(parents=True)
    psd_file.touch()

    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status=None)},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="ok")},
        "AM003": {"LFC_RSC": RunEntry(sleep_qc="needs_review", psd_status=None)},
    })
    pending = m.pending_psd_review()
    animal_ids = [e.animal_id for e, _ in pending]
    assert "AM001" in animal_ids
    assert "AM002" not in animal_ids   # already reviewed
    assert "AM003" not in animal_ids   # sleep_qc not ok


def test_needs_drink_mask_requires_ok_sleep_qc(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="needs_drink_mask")},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="needs_review", psd_status="needs_drink_mask")},
    })
    result = m.needs_drink_mask()
    animal_ids = [e.animal_id for e, _ in result]
    assert "AM001" in animal_ids
    assert "AM002" not in animal_ids


def test_needs_drink_mask_rerun_requires_mask_file(tmp_path):
    mask_file = tmp_path / "drink_masks" / "AM001.npy"
    mask_file.parent.mkdir(parents=True)
    mask_file.touch()

    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="needs_drink_mask")},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="needs_drink_mask")},
    })
    result = m.needs_drink_mask_rerun()
    animal_ids = [e.animal_id for e, _ in result]
    assert "AM001" in animal_ids
    assert "AM002" not in animal_ids  # no mask file on disk


def test_pending_rerun_review(tmp_path):
    output_dir = tmp_path / "spindle_outputs" / "LSC_RSC"
    output_dir.mkdir(parents=True)
    (output_dir / "AM001_states.csv").touch()

    m = _make_manifest(tmp_path, {
        "AM001": {"LSC_RSC": RunEntry(sleep_qc=None, source_combo="LFC_RSC")},
        "AM002": {"LSC_RSC": RunEntry(sleep_qc="ok",  source_combo="LFC_RSC")},
        "AM003": {"LSC_RSC": RunEntry(sleep_qc=None,  source_combo=None)},
    })
    result = m.pending_rerun_review()
    animal_ids = [e.animal_id for e, _ in result]
    assert "AM001" in animal_ids   # unreviewed rerun with outputs on disk
    assert "AM002" not in animal_ids  # already reviewed
    assert "AM003" not in animal_ids  # no source_combo (not a rerun)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_flag_sleep_qc_invalid_status(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": {"LFC_RSC": RunEntry()}})
    with pytest.raises(ValueError, match="Invalid sleep_qc status"):
        m.flag_sleep_qc("AM001", "LFC_RSC", "bogus")


def test_flag_needs_rerun_requires_rerun_combo(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": {"LFC_RSC": RunEntry()}})
    with pytest.raises(ValueError, match="rerun_combo required"):
        m.flag_sleep_qc("AM001", "LFC_RSC", "needs_rerun")


def test_flag_needs_rerun_rerun_combo_cannot_equal_channels(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": {"LFC_RSC": RunEntry()}})
    with pytest.raises(ValueError, match="cannot be the same"):
        m.flag_sleep_qc("AM001", "LFC_RSC", "needs_rerun", rerun_combo="LFC_RSC")
