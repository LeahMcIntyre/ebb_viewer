"""Tests for pipeline/manifest.py.

Covers:
- save / load round-trip, including the project-level combo
- reading pre-single-combo (multi-run) manifest files
- flag_sleep_qc / reset_sleep_qc: psd cleanup when leaving "ok"
- flag_psd: sleep_qc guard, drink_mask management
- build_from_standard: disk scanning, has_spindle, existing flags preserved
- filtered views: pending_sleep_qc, needs_review, ready_for_psd,
                  pending_psd_review, needs_drink_mask, needs_drink_mask_rerun,
                  pending_drink_verification
- filtered view mutual exclusivity: psd queues are pairwise disjoint
- input validation errors
"""

import json
from pathlib import Path

import pytest

from ebb_viewer.pipeline.manifest import DEFAULT_COMBO, Manifest, ManifestEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(tmp_path: Path, animals: dict[str, dict]) -> Manifest:
    """Build and save a manifest from {animal_id: ManifestEntry field overrides}.

    Entries default to ``has_spindle=True`` so the filtered views see them.
    """
    m = Manifest(tmp_path)
    for animal_id, fields in animals.items():
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id,
            preprocessed_edf=f"standard/{animal_id}_PREPROCESSED.edf",
            **{"has_spindle": True, **fields},
        )
    m.save()
    return m


def _reload(m: Manifest) -> Manifest:
    return Manifest.load(m.project_root)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def _make_psd_run(tmp_path: Path, run_name: str = "default") -> None:
    run_dir = tmp_path / "psd" / run_name
    run_dir.mkdir(parents=True)
    (run_dir / "psd_params.json").write_text("{}")
    (run_dir / "psds_LFC_RSC.pkl").touch()


# ---------------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_empty(tmp_path):
    m = Manifest.load(tmp_path)
    assert len(m) == 0
    assert m.combo == DEFAULT_COMBO


def test_save_load_roundtrip(tmp_path):
    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(sleep_qc="ok", psd_status={"default": "needs_drink_mask"}),
            "AM002": dict(sleep_qc="needs_review", notes="hello"),
        },
    )
    m2 = _reload(m)

    assert m2.get("AM001").sleep_qc == "ok"
    assert m2.get("AM001").psd_status == {"default": "needs_drink_mask"}
    assert m2.get("AM002").sleep_qc == "needs_review"
    assert m2.get("AM002").notes == "hello"
    assert m2.get("AM002").has_spindle is True


def test_combo_roundtrips_through_save(tmp_path):
    m = Manifest(tmp_path)
    m.combo = "LFC_LSC"
    m.save()
    assert _reload(m).combo == "LFC_LSC"


def test_save_is_atomic(tmp_path):
    """Ensure no partial-write .tmp file is left behind after save."""
    _make_manifest(tmp_path, {"AM001": {}})
    assert not (tmp_path / "manifest.json.tmp").exists()
    assert (tmp_path / "manifest.json").exists()


# ---------------------------------------------------------------------------
# Reading pre-single-combo manifests (TEMPORARY — delete with the read path
# in manifest._entry_from_dict once existing projects have been re-saved)
# ---------------------------------------------------------------------------


def _write_legacy(tmp_path: Path, data: dict) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps(data))


def test_legacy_load_takes_project_combo_run(tmp_path):
    _write_legacy(
        tmp_path,
        {
            "AM001": {
                "preprocessed_edf": "standard/AM001_PREPROCESSED.edf",
                "notes": "keep me",
                "runs": {
                    "LFC_RSC": {
                        "sleep_qc": "ok",
                        "psd_status": {"default": "ok"},
                        "drink_mask": "drink_masks/AM001.npy",
                    },
                    "LSC_RSC": {"sleep_qc": "rejected", "rejected_by": "LFC_RSC"},
                },
            }
        },
    )
    m = Manifest.load(tmp_path)
    entry = m.get("AM001")
    assert m.combo == DEFAULT_COMBO
    assert entry.has_spindle is True
    assert entry.sleep_qc == "ok"
    assert entry.psd_status == {"default": "ok"}
    assert entry.drink_mask == "drink_masks/AM001.npy"
    assert entry.notes == "keep me"


def test_legacy_load_ignores_other_combos(tmp_path):
    """An animal whose only ok run is under another combo shows as unflagged."""
    _write_legacy(
        tmp_path,
        {
            "AM001": {
                "preprocessed_edf": "x.edf",
                "runs": {"LSC_RSC": {"sleep_qc": "ok"}},
            }
        },
    )
    entry = Manifest.load(tmp_path).get("AM001")
    assert entry.has_spindle is False
    assert entry.sleep_qc is None


@pytest.mark.parametrize("old_status", ["needs_rerun", "rejected"])
def test_legacy_load_drops_removed_statuses(tmp_path, old_status):
    _write_legacy(
        tmp_path,
        {
            "AM001": {
                "preprocessed_edf": "x.edf",
                "runs": {"LFC_RSC": {"sleep_qc": old_status, "rerun_combo": "LSC_RSC"}},
            }
        },
    )
    entry = Manifest.load(tmp_path).get("AM001")
    assert entry.has_spindle is True
    assert entry.sleep_qc is None


def test_legacy_load_tolerates_malformed_psd_status(tmp_path):
    _write_legacy(
        tmp_path,
        {
            "AM001": {
                "preprocessed_edf": "x.edf",
                "runs": {"LFC_RSC": {"sleep_qc": "ok", "psd_status": None}},
            }
        },
    )
    assert Manifest.load(tmp_path).get("AM001").psd_status == {}


def test_build_from_standard_rewrites_legacy_file_in_new_format(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _write_legacy(
        tmp_path,
        {"AM001": {"preprocessed_edf": "standard/AM001_PREPROCESSED.edf", "runs": {}}},
    )
    Manifest.build_from_standard(tmp_path)

    raw = json.loads((tmp_path / "manifest.json").read_text())
    assert raw["combo"] == DEFAULT_COMBO
    assert set(raw["animals"]) == {"AM001"}
    assert "runs" not in raw["animals"]["AM001"]


# ---------------------------------------------------------------------------
# flag_sleep_qc / reset_sleep_qc
# ---------------------------------------------------------------------------


def test_flag_sleep_qc_persisted(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": {}})
    m.flag_sleep_qc("AM001", "ok")
    assert _reload(m).get("AM001").sleep_qc == "ok"


def test_flag_sleep_qc_invalid_status(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": {}})
    with pytest.raises(ValueError, match="Invalid sleep_qc status"):
        m.flag_sleep_qc("AM001", "bogus")


@pytest.mark.parametrize("removed_status", ["needs_rerun", "rejected"])
def test_flag_sleep_qc_rejects_removed_statuses(tmp_path, removed_status):
    m = _make_manifest(tmp_path, {"AM001": {}})
    with pytest.raises(ValueError, match="Invalid sleep_qc status"):
        m.flag_sleep_qc("AM001", removed_status)


def test_unok_clears_psd_status(tmp_path):
    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(
                sleep_qc="ok",
                psd_status={"default": "drink_mask_applied"},
                drink_mask="drink_masks/AM001.npy",
            )
        },
    )
    m.flag_sleep_qc("AM001", "needs_review")
    entry = m.get("AM001")
    assert entry.psd_status == {}
    assert entry.drink_mask is None


def test_reflagging_ok_keeps_psd_status(tmp_path):
    m = _make_manifest(
        tmp_path, {"AM001": dict(sleep_qc="ok", psd_status={"default": "ok"})}
    )
    m.flag_sleep_qc("AM001", "ok")
    assert m.get("AM001").psd_status == {"default": "ok"}


def test_review_to_ok_and_back_does_not_touch_psd_status(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": dict(sleep_qc="needs_review")})
    m.flag_sleep_qc("AM001", "ok")
    m.flag_psd("AM001", "ok")
    m.flag_sleep_qc("AM001", "needs_review")
    assert m.get("AM001").psd_status == {}


def test_reset_sleep_qc_clears_status_and_psd(tmp_path):
    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(
                sleep_qc="ok",
                psd_status={"default": "ok"},
                drink_mask="drink_masks/AM001.npy",
            )
        },
    )
    m.reset_sleep_qc("AM001")
    entry = _reload(m).get("AM001")
    assert entry.sleep_qc is None
    assert entry.psd_status == {}
    assert entry.drink_mask is None


def test_reset_non_ok_is_safe(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": dict(sleep_qc="needs_review")})
    m.reset_sleep_qc("AM001")
    assert m.get("AM001").sleep_qc is None


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def test_set_notes_persisted(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": {}})
    m.set_notes("AM001", "check EMG")
    assert _reload(m).get("AM001").notes == "check EMG"


def test_set_notes_overwrites_existing(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": dict(notes="old")})
    m.set_notes("AM001", "new")
    assert _reload(m).get("AM001").notes == "new"


# ---------------------------------------------------------------------------
# flag_psd / reset_psd_status
# ---------------------------------------------------------------------------


def test_flag_psd_requires_ok_sleep_qc(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": dict(sleep_qc="needs_review")})
    with pytest.raises(ValueError, match="sleep_qc"):
        m.flag_psd("AM001", "ok")


def test_flag_psd_sets_status(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": dict(sleep_qc="ok")})
    m.flag_psd("AM001", "needs_drink_mask")
    assert m.get("AM001").psd_status == {"default": "needs_drink_mask"}


def test_flag_psd_drink_mask_applied_sets_path(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": dict(sleep_qc="ok")})
    m.flag_psd("AM001", "drink_mask_applied")
    entry = m.get("AM001")
    assert entry.psd_status == {"default": "drink_mask_applied"}
    assert entry.drink_mask == "drink_masks/AM001.npy"


def test_flag_psd_ok_clears_drink_mask(tmp_path):
    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(
                sleep_qc="ok",
                psd_status={"default": "drink_mask_applied"},
                drink_mask="drink_masks/AM001.npy",
            )
        },
    )
    m.flag_psd("AM001", "ok")
    assert m.get("AM001").drink_mask is None


def test_flag_psd_ok_keeps_drink_mask_when_another_run_applied(tmp_path):
    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(
                sleep_qc="ok",
                psd_status={"default": "drink_mask_applied", "dark": "needs_drink_mask"},
                drink_mask="drink_masks/AM001.npy",
            )
        },
    )
    m.flag_psd("AM001", "ok", run_name="dark")
    assert m.get("AM001").drink_mask == "drink_masks/AM001.npy"


def test_flag_psd_invalid_status(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": dict(sleep_qc="ok")})
    with pytest.raises(ValueError, match="Invalid psd_status"):
        m.flag_psd("AM001", "bogus")


def test_reset_psd_status_clears_one_run(tmp_path):
    m = _make_manifest(
        tmp_path,
        {"AM001": dict(sleep_qc="ok", psd_status={"default": "ok", "dark": "ok"})},
    )
    m.reset_psd_status("AM001", "dark")
    assert m.get("AM001").psd_status == {"default": "ok"}


# ---------------------------------------------------------------------------
# build_from_standard
# ---------------------------------------------------------------------------


def test_build_picks_up_new_edfs(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "standard" / "AM002_PREPROCESSED.edf")
    m = Manifest.build_from_standard(tmp_path)
    assert "AM001" in m
    assert "AM002" in m
    assert m.get("AM001").has_spindle is False


def test_build_marks_spindle_outputs_for_project_combo(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_states.csv")
    m = Manifest.build_from_standard(tmp_path)
    assert m.get("AM001").has_spindle is True


def test_build_marks_spindle_edfs_for_project_combo(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_edfs" / "LFC_RSC" / "AM001_SPINDLE.edf")
    m = Manifest.build_from_standard(tmp_path)
    assert m.get("AM001").has_spindle is True


def test_build_ignores_other_combo_folders(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_outputs" / "LSC_RSC" / "AM001_states.csv")
    m = Manifest.build_from_standard(tmp_path)
    assert m.get("AM001").has_spindle is False


def test_build_uses_manifest_combo_setting(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_outputs" / "LSC_RSC" / "AM001_states.csv")
    m = Manifest(tmp_path)
    m.combo = "LSC_RSC"
    m.save()
    assert Manifest.build_from_standard(tmp_path).get("AM001").has_spindle is True


def test_build_does_not_overwrite_existing_status(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_states.csv")
    m = Manifest.build_from_standard(tmp_path)
    m.flag_sleep_qc("AM001", "ok")

    m2 = Manifest.build_from_standard(tmp_path)
    assert m2.get("AM001").sleep_qc == "ok"


def test_build_ignores_files_for_unknown_animals(tmp_path):
    _touch(tmp_path / "standard" / "AM001_PREPROCESSED.edf")
    _touch(tmp_path / "spindle_outputs" / "LFC_RSC" / "AM999_states.csv")
    m = Manifest.build_from_standard(tmp_path)
    assert "AM999" not in m


# ---------------------------------------------------------------------------
# Filtered views
# ---------------------------------------------------------------------------


def test_pending_sleep_qc(tmp_path):
    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(sleep_qc=None),
            "AM002": dict(sleep_qc="ok"),
            "AM003": dict(sleep_qc=None, has_spindle=False),
        },
    )
    animal_ids = [e.animal_id for e in m.pending_sleep_qc()]
    assert animal_ids == ["AM001"]  # AM003 has no spindle files yet


def test_needs_review(tmp_path):
    m = _make_manifest(
        tmp_path,
        {"AM001": dict(sleep_qc="needs_review"), "AM002": dict(sleep_qc="ok")},
    )
    assert [e.animal_id for e in m.needs_review()] == ["AM001"]


def test_ready_for_psd(tmp_path):
    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(sleep_qc="ok"),
            "AM002": dict(sleep_qc="needs_review"),
            "AM003": dict(sleep_qc=None),
        },
    )
    assert [e.animal_id for e in m.ready_for_psd()] == ["AM001"]


def test_pending_psd_review(tmp_path):
    # pending_psd_review is gated on psds_LFC_RSC.pkl existing
    _make_psd_run(tmp_path)

    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(sleep_qc="ok"),
            "AM002": dict(sleep_qc="ok", psd_status={"default": "ok"}),
            "AM003": dict(sleep_qc="needs_review"),
        },
    )
    animal_ids = [e.animal_id for e in m.pending_psd_review("default")]
    assert "AM001" in animal_ids
    assert "AM002" not in animal_ids  # already reviewed
    assert "AM003" not in animal_ids  # sleep_qc not ok


def test_pending_psd_review_skips_excluded_until_unexcluded(tmp_path):
    _make_psd_run(tmp_path)
    m = _make_manifest(tmp_path, {"AM001": dict(sleep_qc="ok"), "AM002": dict(sleep_qc="excluded")})
    assert [e.animal_id for e in m.pending_psd_review("default")] == ["AM001"]
    assert [e.animal_id for e in m.all_pending_psd_review()] == ["AM001"]

    m.flag_sleep_qc("AM002", "ok")  # un-excluded straight to ok: it needs a real review now
    assert {e.animal_id for e in m.pending_psd_review("default")} == {"AM001", "AM002"}


def test_pending_psd_review_empty_without_final_pkl(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": dict(sleep_qc="ok")})
    # No psds_LFC_RSC.pkl → empty
    assert m.pending_psd_review("default") == []


def test_needs_drink_mask_requires_ok_sleep_qc(tmp_path):
    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(sleep_qc="ok", psd_status={"default": "needs_drink_mask"}),
            "AM002": dict(sleep_qc="needs_review", psd_status={"default": "needs_drink_mask"}),
        },
    )
    animal_ids = [e.animal_id for e in m.needs_drink_mask("default")]
    assert "AM001" in animal_ids
    assert "AM002" not in animal_ids


def test_needs_drink_mask_rerun_requires_mask_file(tmp_path):
    _touch(tmp_path / "drink_masks" / "AM001.npy")

    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(sleep_qc="ok", psd_status={"default": "needs_drink_mask"}),
            "AM002": dict(sleep_qc="ok", psd_status={"default": "needs_drink_mask"}),
        },
    )
    animal_ids = [e.animal_id for e in m.needs_drink_mask_rerun("default")]
    assert "AM001" in animal_ids
    assert "AM002" not in animal_ids  # no mask file on disk


def test_aggregate_views_dedupe_across_psd_runs(tmp_path):
    _make_psd_run(tmp_path, "default")
    _make_psd_run(tmp_path, "dark")
    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(
                sleep_qc="ok",
                psd_status={"default": "needs_drink_mask", "dark": "needs_drink_mask"},
            ),
        },
    )
    assert [e.animal_id for e in m.all_needs_drink_mask()] == ["AM001"]


# ---------------------------------------------------------------------------
# PSD status queues are pairwise disjoint (no double-counting in Finalize)
# ---------------------------------------------------------------------------


def test_psd_queues_are_pairwise_disjoint(tmp_path):
    """pending_psd_review, needs_drink_mask, and pending_drink_verification
    are mutually exclusive — each psd_status value belongs to exactly one queue.
    """
    _make_psd_run(tmp_path)  # required for pending_psd_review

    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(sleep_qc="ok"),
            "AM002": dict(sleep_qc="ok", psd_status={"default": "needs_drink_mask"}),
            "AM003": dict(sleep_qc="ok", psd_status={"default": "drink_mask_applied"}),
            "AM004": dict(sleep_qc="ok", psd_status={"default": "ok"}),
        },
    )

    pending_review = {e.animal_id for e in m.pending_psd_review("default")}
    needs_drink = {e.animal_id for e in m.needs_drink_mask("default")}
    drink_verif = {e.animal_id for e in m.pending_drink_verification("default")}

    assert not (pending_review & needs_drink), "overlap: pending_review ∩ needs_drink"
    assert not (pending_review & drink_verif), "overlap: pending_review ∩ drink_verif"
    assert not (needs_drink & drink_verif), "overlap: needs_drink ∩ drink_verif"

    # Each animal lands in exactly the right queue
    assert "AM001" in pending_review
    assert "AM002" in needs_drink
    assert "AM003" in drink_verif
    assert all("AM004" not in q for q in (pending_review, needs_drink, drink_verif))


def test_pending_count_no_double_count(tmp_path):
    """Summing the three disjoint queues gives the correct total pending count."""
    _make_psd_run(tmp_path)

    m = _make_manifest(
        tmp_path,
        {
            "AM001": dict(sleep_qc="ok"),
            "AM002": dict(sleep_qc="ok", psd_status={"default": "needs_drink_mask"}),
            "AM003": dict(sleep_qc="ok", psd_status={"default": "drink_mask_applied"}),
        },
    )

    total = (
        len(m.pending_psd_review("default"))
        + len(m.needs_drink_mask("default"))
        + len(m.pending_drink_verification("default"))
    )
    assert total == 3  # one animal in each queue, no double-counting


def test_reclass_gate_roundtrip(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": dict(), "AM002": dict()})
    assert m.get("AM001").reclass_gate_applied is None

    m.set_reclass_gates({"AM001": True, "AM002": False, "GHOST": True})
    m2 = _reload(m)

    assert m2.get("AM001").reclass_gate_applied is True
    assert m2.get("AM002").reclass_gate_applied is False
    assert m2.get("GHOST") is None


def test_swd_review_fields_roundtrip(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": dict(), "AM002": dict()})
    assert m.swd_review_enabled is False and m.get("AM001").swd_reviewed == 0

    m.set_swd_review_enabled(True)
    m.set_swd_progress("AM001", reviewed=3, total=5)
    m2 = _reload(m)

    assert m2.swd_review_enabled is True
    assert (m2.get("AM001").swd_reviewed, m2.get("AM001").swd_total) == (3, 5)
    assert (m2.get("AM002").swd_reviewed, m2.get("AM002").swd_total) == (0, None)  # total unknown


def test_swd_review_status_from_saved_progress():
    from ebb_viewer.pipeline.manifest import swd_review_status

    e = ManifestEntry("A", "standard/A.edf")
    assert swd_review_status(e) == "not_started"  # total unknown
    e.swd_reviewed, e.swd_total = 0, 5
    assert swd_review_status(e) == "not_started"
    e.swd_reviewed = 2
    assert swd_review_status(e) == "in_progress"
    e.swd_reviewed = 5
    assert swd_review_status(e) == "done"
    e.swd_reviewed, e.swd_total = 0, 0  # an empty SWD file: nothing to review
    assert swd_review_status(e) == "done"


def test_swd_waived_roundtrip(tmp_path):
    m = _make_manifest(tmp_path, {"AM001": dict()})
    assert m.get("AM001").swd_waived is False
    m.set_swd_waived("AM001")
    assert _reload(m).get("AM001").swd_waived is True
    m.set_swd_waived("AM001", False)
    assert _reload(m).get("AM001").swd_waived is False


# --- exclusion and flagging thresholds -----------------------------------


def test_exclude_requires_a_reason(tmp_path):
    m = _make_manifest(tmp_path, {"A1": {"sleep_qc": "needs_review"}})
    with pytest.raises(ValueError, match="reason"):
        m.exclude_sleep_qc("A1", "   ")
    assert m.get("A1").sleep_qc == "needs_review"


def test_exclude_sets_status_and_appends_to_notes(tmp_path):
    m = _make_manifest(tmp_path, {"A1": {"notes": "cage change day 2"}, "A2": {}})
    m.exclude_sleep_qc("A1", " lost EEG signal ")
    m.exclude_sleep_qc("A2", "seizures")
    assert m.get("A1").sleep_qc == "excluded"
    assert m.get("A1").notes == "cage change day 2\nExcluded: lost EEG signal"
    assert m.get("A2").notes == "Excluded: seizures"
    assert Manifest.load(tmp_path).get("A1").sleep_qc == "excluded"


def test_exclude_from_ok_keeps_psd_progress(tmp_path):
    """Excluded animals are still computed, so ok <-> excluded does not reset PSD review."""
    m = _make_manifest(tmp_path, {"A1": {"sleep_qc": "ok", "psd_status": {"default": "ok"}}})
    m.exclude_sleep_qc("A1", "bad file")
    assert m.get("A1").psd_status == {"default": "ok"}
    m.flag_sleep_qc("A1", "ok")
    assert m.get("A1").psd_status == {"default": "ok"}


def test_unexclude_to_needs_review_clears_psd_progress(tmp_path):
    m = _make_manifest(tmp_path, {"A1": {"sleep_qc": "excluded", "psd_status": {"default": "ok"}}})
    m.flag_sleep_qc("A1", "needs_review")
    assert m.get("A1").psd_status == {}


def test_excluded_animals_are_ready_for_psd_and_can_be_psd_flagged(tmp_path):
    _make_psd_run(tmp_path)
    m = _make_manifest(tmp_path, {"A1": {"sleep_qc": "excluded"}, "A2": {"sleep_qc": "needs_review"}})
    assert [e.animal_id for e in m.ready_for_psd()] == ["A1"]
    assert m.pending_psd_review("default") == []  # excluded: computed, but not queued for review
    m.flag_psd("A1", "needs_drink_mask")
    assert [e.animal_id for e in m.needs_drink_mask("default")] == ["A1"]
    with pytest.raises(ValueError, match="'ok' or 'excluded'"):
        m.flag_psd("A2", "ok")


def test_unexclude_keeps_the_note(tmp_path):
    m = _make_manifest(tmp_path, {"A1": {}})
    m.exclude_sleep_qc("A1", "bad file")
    m.flag_sleep_qc("A1", "ok")
    assert m.get("A1").sleep_qc == "ok"
    assert m.get("A1").notes == "Excluded: bad file"
    m.exclude_sleep_qc("A1", "still bad")
    m.reset_sleep_qc("A1")
    assert m.get("A1").sleep_qc is None


def test_flag_sleep_qc_rejects_excluded(tmp_path):
    m = _make_manifest(tmp_path, {"A1": {}})
    with pytest.raises(ValueError, match="exclude_sleep_qc"):
        m.flag_sleep_qc("A1", "excluded")


def test_flag_thresholds_default_and_read_from_manifest_file(tmp_path):
    m = _make_manifest(tmp_path, {"A1": {}})
    assert m.flag_thresholds["nrem_short"] == 400
    raw = json.loads(m.path.read_text())
    raw["flag_thresholds"] = {"nrem_short": 250}  # edited by hand in manifest.json
    m.path.write_text(json.dumps(raw))
    loaded = Manifest.load(tmp_path)
    assert loaded.flag_thresholds["nrem_short"] == 250
    assert loaded.flag_thresholds["pct_nrem"] == 30  # others keep defaults
