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
                  pending_rerun_review, pending_drink_verification
- filtered view mutual exclusivity: psd queues are pairwise disjoint
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
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "needs_drink_mask"})},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
    })
    m2 = _reload(m)

    assert m2.get_run("AM001", "LFC_RSC").sleep_qc == "ok"
    assert m2.get_run("AM001", "LFC_RSC").psd_status == {"default": "needs_drink_mask"}
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
    assert run.psd_status == {"default": "needs_drink_mask"}


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
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "needs_drink_mask"})}
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_review")

    run = m.get_run("AM001", "LFC_RSC")
    assert run.psd_status == {}
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
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "ok"})}
    })
    m.reset_sleep_qc("AM001", "LFC_RSC")

    run = m.get_run("AM001", "LFC_RSC")
    assert run.psd_status == {}
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
    assert m.get_run("AM001", "LFC_RSC").psd_status == {"default": "needs_drink_mask"}


def test_flag_psd_drink_mask_applied_sets_path(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")}
    })
    m.flag_psd("AM001", "LFC_RSC", "drink_mask_applied")
    run = m.get_run("AM001", "LFC_RSC")
    assert run.psd_status == {"default": "drink_mask_applied"}
    assert run.drink_mask == "drink_masks/AM001.npy"


def test_flag_psd_ok_clears_drink_mask(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "drink_mask_applied"},
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


def test_build_stamps_source_combo_when_rerun_target_found_on_disk(tmp_path):
    """Externally placed rerun output is recognised as a rerun on sync.

    Scenario: LFC_RSC flagged needs_rerun → RSC. User places the RSC CSV
    directly on disk and clicks 'Sync from filesystem'. The RSC run should
    have source_combo='LFC_RSC' so pending_rerun_review() fires.
    """
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_states.csv")
    m = Manifest.build_from_standard(tmp_path)
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_rerun", rerun_combo="RSC")

    # Externally place the rerun output
    _touch(tmp_path / "spindle_outputs" / "RSC" / "AM001_states.csv")
    m2 = Manifest.build_from_standard(tmp_path)

    rsc_run = m2.get_run("AM001", "RSC")
    assert rsc_run is not None
    assert rsc_run.source_combo == "LFC_RSC"
    assert rsc_run.sleep_qc is None  # unreviewed, not auto-rejected


def test_build_edf_only_does_not_stamp_source_combo(tmp_path):
    """EDF placed in spindle_edfs/ without a matching CSV must NOT stamp source_combo.

    Stamping source_combo causes needs_rerun_pending() to exclude the original
    run (treating it as 'Rerun page done'), which makes the item disappear from
    the attention zone and Rerun page queue even though upload hasn't happened.
    The Rerun page's add_run() is the correct place to stamp source_combo.
    """
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_states.csv")
    m = Manifest.build_from_standard(tmp_path)
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_rerun", rerun_combo="RSC")

    # Only the EDF placed — output CSV not present yet
    _touch(tmp_path / "spindle_edfs" / "RSC" / "AM001_PREPROCESSED.edf")
    m2 = Manifest.build_from_standard(tmp_path)

    rsc_run = m2.get_run("AM001", "RSC")
    assert rsc_run is not None
    assert rsc_run.source_combo is None   # NOT stamped — Rerun page must still act
    # LFC_RSC must still appear in needs_rerun_pending so the orange card stays up
    pending = m2.needs_rerun_pending()
    assert any(e.animal_id == "AM001" for e, _ in pending)


def test_build_no_source_combo_when_no_rerun_pointer(tmp_path):
    """A new combo with no rerun pointer should NOT get source_combo stamped."""
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_states.csv")
    _touch(tmp_path / "spindle_outputs" / "RSC" / "AM001_states.csv")
    m = Manifest.build_from_standard(tmp_path)

    rsc_run = m.get_run("AM001", "RSC")
    assert rsc_run is not None
    assert rsc_run.source_combo is None


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
    # pending_psd_review is gated on psds_channel_merged.pkl existing
    run_dir = tmp_path / "psd" / "default"
    run_dir.mkdir(parents=True)
    (run_dir / "psd_params.json").write_text("{}")
    (run_dir / "psds_channel_merged.pkl").touch()

    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "ok"})},
        "AM003": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
    })
    pending = m.pending_psd_review("default")
    animal_ids = [e.animal_id for e, _ in pending]
    assert "AM001" in animal_ids
    assert "AM002" not in animal_ids   # already reviewed
    assert "AM003" not in animal_ids   # sleep_qc not ok


def test_pending_psd_review_empty_without_final_pkl(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
    })
    # No psds_channel_merged.pkl → empty
    assert m.pending_psd_review("default") == []


def test_needs_drink_mask_requires_ok_sleep_qc(tmp_path):
    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "needs_drink_mask"})},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="needs_review", psd_status={"default": "needs_drink_mask"})},
    })
    result = m.needs_drink_mask("default")
    animal_ids = [e.animal_id for e, _ in result]
    assert "AM001" in animal_ids
    assert "AM002" not in animal_ids


def test_needs_drink_mask_rerun_requires_mask_file(tmp_path):
    mask_file = tmp_path / "drink_masks" / "AM001.npy"
    mask_file.parent.mkdir(parents=True)
    mask_file.touch()

    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "needs_drink_mask"})},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "needs_drink_mask"})},
    })
    result = m.needs_drink_mask_rerun("default")
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


def test_needs_rerun_pending_excludes_when_csv_present(tmp_path):
    """needs_rerun_pending drops an item only once the output CSV is on disk.

    If source_combo is stamped but no CSV exists (e.g. upload was cancelled),
    the item must still appear so the user can re-trigger from the Rerun page.
    """
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc="needs_rerun", rerun_combo="LSC"),
            "LSC":     RunEntry(sleep_qc=None, source_combo=None),
        },
    })
    # No CSV yet: appears
    assert len(m.needs_rerun_pending()) == 1

    # Stamp source_combo but still no CSV — should still appear
    m._entries["AM001"].runs["LSC"].source_combo = "LFC_RSC"
    m.save()
    m2 = Manifest.load(m.project_root)
    assert len(m2.needs_rerun_pending()) == 1

    # CSV downloaded — should now disappear (pending_rerun_review takes over)
    csv = tmp_path / "spindle_outputs" / "LSC" / "AM001_states.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.touch()
    assert len(m2.needs_rerun_pending()) == 0


def test_needs_rerun_pending_still_shows_before_source_combo_stamped(tmp_path):
    """Before the Rerun page processes it, the item must appear in the queue."""
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc="needs_rerun", rerun_combo="LSC"),
            # LSC present but not yet registered as a rerun
            "LSC":     RunEntry(sleep_qc=None, source_combo=None),
        },
    })
    assert len(m.needs_rerun_pending()) == 1


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


def test_flag_needs_rerun_resets_existing_rerun_run_from_ok(tmp_path):
    """Re-flagging needs_rerun when rerun run already exists and was accepted
    resets it to sleep_qc=None so it re-enters pending_rerun_review."""
    output_dir = tmp_path / "spindle_outputs" / "LFC"
    output_dir.mkdir(parents=True)
    (output_dir / "AM001_states.csv").touch()

    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc="needs_review"),
            "LFC":     RunEntry(sleep_qc="ok", source_combo="LFC_RSC"),
        },
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_rerun", rerun_combo="LFC")

    rerun_run = m._entries["AM001"].runs["LFC"]
    assert rerun_run.sleep_qc is None
    assert rerun_run.source_combo == "LFC_RSC"
    # With CSV present the animal should appear in pending_rerun_review
    assert any(e.animal_id == "AM001" for e, _ in m.pending_rerun_review())


def test_flag_needs_rerun_resets_existing_rerun_run_from_rejected(tmp_path):
    """Re-flagging needs_rerun when rerun run was cascade-rejected also resets it."""
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc="needs_review"),
            "LFC":     RunEntry(sleep_qc="rejected", rejected_by="LFC_RSC"),
        },
    })
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_rerun", rerun_combo="LFC")

    rerun_run = m._entries["AM001"].runs["LFC"]
    assert rerun_run.sleep_qc is None
    assert rerun_run.source_combo == "LFC_RSC"
    assert rerun_run.rejected_by is None
    # No CSV yet → appears in needs_rerun_pending (Rerun queue)
    assert any(e.animal_id == "AM001" for e, _ in m.needs_rerun_pending())


# ---------------------------------------------------------------------------
# Testing gaps (PIPELINE_AUDIT.md)
# ---------------------------------------------------------------------------

def test_add_run_does_not_reset_ok_when_stamping_source_combo(tmp_path):
    """Gap 2: add_run stamping source_combo on an existing ok run must NOT reset sleep_qc.

    Previously the elif branch unconditionally set run.sleep_qc = None, which
    would silently violate the one-ok invariant if the run happened to be the
    ok combo.
    """
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "ok"}),
            "RSC_LSC": RunEntry(sleep_qc="rejected", rejected_by="LFC_RSC"),
        },
    })
    # Stamp source_combo on the ok run (e.g., retroactive provenance)
    m.add_run("AM001", "LFC_RSC", source_combo="RSC_LSC")

    run = m._entries["AM001"].runs["LFC_RSC"]
    assert run.sleep_qc == "ok", "ok run must not be reset by add_run"
    assert run.source_combo == "RSC_LSC"
    assert run.psd_status == {"default": "ok"}, "psd_status must be preserved"
    # Sibling should still be rejected (cascade intact)
    assert m._entries["AM001"].runs["RSC_LSC"].sleep_qc == "rejected"


def test_dead_zone_needs_rerun_with_csv_and_no_source_combo(tmp_path):
    """Gap 5: animal with needs_rerun + CSV present + source_combo=None is invisible
    to both needs_rerun_pending (excluded by CSV) and pending_rerun_review
    (excluded by missing source_combo). Documents the dead zone.
    """
    # Create the CSV on disk so CSV check sees it
    csv = tmp_path / "spindle_outputs" / "RSC" / "AM001_states.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.touch()

    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc="needs_rerun", rerun_combo="RSC"),
            "RSC":     RunEntry(sleep_qc=None, source_combo=None),
        },
    })

    # CSV present → excluded from needs_rerun_pending
    assert len(m.needs_rerun_pending()) == 0
    # source_combo=None → excluded from pending_rerun_review
    assert len(m.pending_rerun_review()) == 0
    # Animal IS visible in needs_rerun() for history purposes
    assert any(combo == "LFC_RSC" for _, combo in m.needs_rerun())


def test_needs_rerun_pending_excludes_when_rerun_run_reviewed(tmp_path):
    """Gap 8: needs_rerun_pending excludes when the rerun run has any non-None sleep_qc.

    Covers the case where the rerun combo was cascade-rejected (sleep_qc="rejected")
    rather than explicitly accepted — the original stays needs_rerun in the manifest
    for history, but should no longer appear in the Rerun queue.
    """
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc="needs_rerun", rerun_combo="RSC"),
            "RSC":     RunEntry(sleep_qc="rejected", source_combo="LFC_RSC"),
        },
    })
    # Rerun run has sleep_qc="rejected" (non-None) → must not appear in queue
    assert len(m.needs_rerun_pending()) == 0
    # Original still shows in needs_rerun() (historical record)
    assert any(combo == "LFC_RSC" for _, combo in m.needs_rerun())


def test_sibling_psd_status_cleared_when_restored_to_non_ok(tmp_path):
    """Gap 9: When un-okaying restores a sibling to a non-ok status, any stale
    psd_status/drink_mask on that sibling must be cleared.

    Without this, a sibling restored to sleep_qc=None but carrying psd_status="ok"
    would be silently skipped by pending_psd_review() (which requires psd_status is None)
    if the sibling is later made ok again.
    """
    # Set up: RSC has stale psd_status (injected directly to simulate edge case)
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc="ok"),
            "RSC":     RunEntry(sleep_qc="rejected", rejected_by="LFC_RSC",
                                prev_sleep_qc=None, psd_status={"default": "ok"}),
        },
    })
    # Un-ok LFC_RSC → RSC restored to sleep_qc=None (prev_sleep_qc was None)
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_review")

    rsc = m._entries["AM001"].runs["RSC"]
    assert rsc.sleep_qc is None
    # psd_status must be cleared since RSC is not restored to ok
    assert rsc.psd_status == {}
    assert rsc.drink_mask is None


def test_sibling_psd_status_preserved_when_restored_to_ok(tmp_path):
    """Gap 9 (complement): When a sibling IS restored to ok, preserve its psd_status
    so the user doesn't lose already-completed PSD review work.
    """
    # RSC was previously ok with reviewed PSD, then LFC_RSC was made ok (cascade-rejecting RSC)
    m = _make_manifest(tmp_path, {
        "AM001": {
            "LFC_RSC": RunEntry(sleep_qc="ok"),
            "RSC":     RunEntry(sleep_qc="rejected", rejected_by="LFC_RSC",
                                prev_sleep_qc="ok", psd_status={"default": "ok"}),
        },
    })
    # Un-ok LFC_RSC → RSC restored to its prev_sleep_qc="ok"
    m.flag_sleep_qc("AM001", "LFC_RSC", "needs_review")

    rsc = m._entries["AM001"].runs["RSC"]
    assert rsc.sleep_qc == "ok"
    assert rsc.psd_status == {"default": "ok"}  # preserved — PSD review work not lost


# ---------------------------------------------------------------------------
# Gap 12: orphan-cleared run is re-actionable after load()
# ---------------------------------------------------------------------------

def test_load_orphan_cleared_run_is_actionable(tmp_path):
    """After load() clears orphaned rejected_by, the run can be flagged without error.

    Extends test_load_clears_orphaned_rejected_by: verifies not just that the
    metadata is cleared but that the run is in a valid, actionable state.
    """
    data = {
        "AM001": {
            "preprocessed_edf": "standard/AM001_PREPROCESSED.edf",
            "notes": "",
            "runs": {
                "LFC_RSC": {
                    "sleep_qc": "rejected",
                    "rerun_combo": None, "source_combo": None,
                    "psd_status": None, "drink_mask": None,
                    "prev_sleep_qc": "needs_review",
                    "rejected_by": "LSC_RSC",  # orphan — LSC_RSC not present
                },
            }
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(data))
    m = Manifest.load(tmp_path)

    # Orphan cleared — run should now be flaggable without raising
    m.flag_sleep_qc("AM001", "LFC_RSC", "ok")
    assert m.get_run("AM001", "LFC_RSC").sleep_qc == "ok"


# ---------------------------------------------------------------------------
# Gap 13: PSD status queues are pairwise disjoint (no double-counting in Finalize)
# ---------------------------------------------------------------------------

def test_psd_queues_are_pairwise_disjoint(tmp_path):
    """pending_psd_review, needs_drink_mask, and pending_drink_verification
    are mutually exclusive — each psd_status value belongs to exactly one queue.
    """
    run_dir = tmp_path / "psd" / "default"
    run_dir.mkdir(parents=True)
    (run_dir / "psd_params.json").write_text("{}")
    (run_dir / "psds_channel_merged.pkl").touch()  # required for pending_psd_review

    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "needs_drink_mask"})},
        "AM003": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "drink_mask_applied"})},
        "AM004": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "ok"})},
    })

    pending_review   = {(e.animal_id, c) for e, c in m.pending_psd_review("default")}
    needs_drink      = {(e.animal_id, c) for e, c in m.needs_drink_mask("default")}
    drink_verif      = {(e.animal_id, c) for e, c in m.pending_drink_verification("default")}

    assert not (pending_review & needs_drink),   "overlap: pending_review ∩ needs_drink"
    assert not (pending_review & drink_verif),   "overlap: pending_review ∩ drink_verif"
    assert not (needs_drink    & drink_verif),   "overlap: needs_drink ∩ drink_verif"

    # Each animal lands in exactly the right queue
    assert ("AM001", "LFC_RSC") in pending_review
    assert ("AM002", "LFC_RSC") in needs_drink
    assert ("AM003", "LFC_RSC") in drink_verif
    assert all(("AM004", "LFC_RSC") not in q for q in (pending_review, needs_drink, drink_verif))


def test_pending_count_no_double_count(tmp_path):
    """Summing the three disjoint queues gives the correct total pending count."""
    run_dir = tmp_path / "psd" / "default"
    run_dir.mkdir(parents=True)
    (run_dir / "psd_params.json").write_text("{}")
    (run_dir / "psds_channel_merged.pkl").touch()

    m = _make_manifest(tmp_path, {
        "AM001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
        "AM002": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "needs_drink_mask"})},
        "AM003": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "drink_mask_applied"})},
    })

    total = (
        len(m.pending_psd_review("default"))
        + len(m.needs_drink_mask("default"))
        + len(m.pending_drink_verification("default"))
    )
    assert total == 3  # one animal in each queue, no double-counting
