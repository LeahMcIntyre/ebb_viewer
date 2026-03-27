"""Tests for compute_pipeline_status in home.py.

Focuses on the PSD step gate: step 6 should be "attention" when some animals
still have sleep_qc == "needs_review", not "active", even if n_ok > 0.
"""

import pytest
from pathlib import Path

from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry, RunEntry
from ebb_viewer.pages.home import compute_pipeline_status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manifest(tmp_path: Path, animals: dict) -> Manifest:
    m = Manifest(tmp_path)
    for animal_id, runs in animals.items():
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id,
            preprocessed_edf=f"standard/{animal_id}_PREPROCESSED.edf",
            runs=runs,
        )
    m.save()
    return m


def _setup_filesystem(tmp_path: Path, *, combos: list[str]) -> None:
    """Create minimal filesystem state: standard EDF, spindle EDFs and outputs for each combo."""
    (tmp_path / "standard").mkdir()
    (tmp_path / "standard" / "A001_PREPROCESSED.edf").touch()
    for combo in combos:
        edf_dir = tmp_path / "spindle_edfs" / combo
        edf_dir.mkdir(parents=True)
        (edf_dir / "A001_spindle.edf").touch()
        csv_dir = tmp_path / "spindle_outputs" / combo
        csv_dir.mkdir(parents=True)
        (csv_dir / "A001_labels.csv").touch()


# ---------------------------------------------------------------------------
# Step 6: PSD gate on Sleep QC resolved
# ---------------------------------------------------------------------------

def test_step6_active_when_all_qc_resolved(tmp_path):
    """Step 6 is 'active' when n_ok > 0 and no animals need Sleep QC review."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s6 = statuses[5]
    assert s6.kind == "active"
    assert "ready to compute" in s6.description


def test_step6_attention_when_review_pending_and_ok_exists(tmp_path):
    """Step 6 is 'attention' (not 'active') when some animals still need EDF review."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
        "A002": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s6 = statuses[5]
    assert s6.kind == "attention"
    assert "Sleep QC" in s6.description


def test_step6_attention_message_includes_count(tmp_path):
    """Step 6 attention message names the number of animals still needing review."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
        "A002": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
        "A003": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s6 = statuses[5]
    assert s6.kind == "attention"
    assert "2" in s6.description


def test_step6_blocked_when_no_ok_animals(tmp_path):
    """Step 6 remains 'blocked' when there are no ok animals, even with reviews pending."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s6 = statuses[5]
    assert s6.kind == "blocked"


def test_step6_active_when_review_animals_are_rejected(tmp_path):
    """Rejected animals don't trigger the attention gate — only needs_review does."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
        "A002": {"LFC_RSC": RunEntry(sleep_qc="rejected")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s6 = statuses[5]
    assert s6.kind == "active"


def test_step6_done_when_final_pkl_exists(tmp_path):
    """Step 6 is 'done' when psds_channel_merged.pkl exists regardless of review state."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    psd_dir = tmp_path / "psd"
    psd_dir.mkdir()
    (psd_dir / "psds_channel_merged.pkl").touch()
    (psd_dir / "psds_LFC_RSC.pkl").touch()
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s6 = statuses[5]
    assert s6.kind == "done"


# ---------------------------------------------------------------------------
# Step 8: Drink Mask gate
# ---------------------------------------------------------------------------

def _setup_with_final_pkl(tmp_path: Path, combos: list[str]) -> Path:
    """Set up filesystem + return psd_dir with psds_channel_merged.pkl created."""
    _setup_filesystem(tmp_path, combos=combos)
    psd_dir = tmp_path / "psd"
    psd_dir.mkdir()
    (psd_dir / "psds_channel_merged.pkl").touch()
    for combo in combos:
        (psd_dir / f"psds_{combo}.pkl").touch()
    return psd_dir


def test_step8_blocked_when_no_final_pkl(tmp_path):
    """Step 8 is 'blocked' until psds_channel_merged.pkl exists."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="needs_drink_mask")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[7].kind == "blocked"


def test_step8_attention_when_drink_mask_needed(tmp_path):
    """Step 8 is 'attention' when animals are flagged needs_drink_mask."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="needs_drink_mask")},
        "A002": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="needs_drink_mask")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s8 = statuses[7]
    assert s8.kind == "attention"
    assert "2" in s8.description


def test_step8_done_when_drink_masks_applied(tmp_path):
    """Step 8 is 'done' with count when all flagged animals have masks applied."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="drink_mask_applied")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s8 = statuses[7]
    assert s8.kind == "done"
    assert "1" in s8.description


def test_step8_done_none_needed_when_all_ok(tmp_path):
    """Step 8 is 'done (none needed)' when final PKL exists and no animals need a drink mask."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="ok")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s8 = statuses[7]
    assert s8.kind == "done"
    assert "no drink masks needed" in s8.description.lower()


# ---------------------------------------------------------------------------
# Step 9: Finalize gate
# ---------------------------------------------------------------------------

def test_step9_blocked_when_no_merged_pkl(tmp_path):
    """Step 9 is 'blocked' when psds_channel_merged.pkl doesn't exist."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[8].kind == "blocked"


def test_step9_blocked_when_psd_review_pending(tmp_path):
    """Step 9 is 'blocked' when some PSDs are still pending review."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status=None)},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[8].kind == "blocked"


def test_step9_blocked_when_drink_mask_pending(tmp_path):
    """Step 9 is 'blocked' when animals still need drink mask."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="needs_drink_mask")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[8].kind == "blocked"


def test_step9_attention_when_all_reviewed_not_finalized(tmp_path):
    """Step 9 is 'attention' when all PSDs are reviewed but psds_final.pkl not yet written."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="ok")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s9 = statuses[8]
    assert s9.kind == "attention"
    assert "finalize" in s9.description.lower()


# ---------------------------------------------------------------------------
# Gap 11: special PKL names excluded from combos_with_pkl
# ---------------------------------------------------------------------------

def test_step6_special_pkl_names_not_counted_as_combo_pkls(tmp_path):
    """psds_channel_merged.pkl, psds_channel_merged_drink.pkl, and psds_final.pkl
    must not be counted as per-combo PKLs.

    Without the exclusion filter these files would make combos_with_pkl non-empty,
    changing the step 6 branch that fires.  With the filter, only real combo PKLs
    (e.g. psds_LFC_RSC.pkl) count — so step 6 must not report 'done' when the
    per-combo PKL is absent even though the special PKLs are present.
    """
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    psd_dir = tmp_path / "psd"
    psd_dir.mkdir()
    (psd_dir / "psds_channel_merged.pkl").touch()
    (psd_dir / "psds_channel_merged_drink.pkl").touch()
    (psd_dir / "psds_final.pkl").touch()
    # psds_LFC_RSC.pkl intentionally absent
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[5].kind != "done"


def test_step9_done_when_final_pkl_exists(tmp_path):
    """Step 9 is 'done' when psds_final.pkl exists."""
    psd_dir = _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    (psd_dir / "psds_final.pkl").touch()
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="ok")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[8].kind == "done"


# ---------------------------------------------------------------------------
# Gap 3: regression guard — merged_pkl deleted after partial/full review
# ---------------------------------------------------------------------------

def test_step9_blocked_when_merged_pkl_absent_despite_reviewed_animals(tmp_path):
    """Step 9 is 'blocked' when merged_pkl is absent even if psd_status flags are set.

    pending_psd_review() returns [] when merged_pkl is absent, making n_psd_pending=0.
    Step 9 must still be 'blocked' because merged_pkl.exists() gates it.
    """
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="ok")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[8].kind == "blocked"


def test_step7_blocked_when_merged_pkl_absent_despite_reviewed_animals(tmp_path):
    """Step 7 is 'blocked' when merged_pkl is absent even if psd_status flags are set."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="ok")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[6].kind == "blocked"


# ---------------------------------------------------------------------------
# Gap 6: step 7 must not show "done" when an animal is re-flagged after finalization
# ---------------------------------------------------------------------------

def test_step7_not_done_when_final_pkl_exists_but_animal_needs_drink_mask(tmp_path):
    """Step 7 must not show 'done' when final_pkl exists but an animal is re-flagged needs_drink_mask.

    Bug: final_pkl.exists() was checked before n_needs_drink, causing step 7 to
    report 'done' even though a drink mask still needs to be applied.
    """
    psd_dir = _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    (psd_dir / "psds_final.pkl").touch()
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="needs_drink_mask")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[6].kind != "done"


def test_step7_done_when_final_pkl_exists_and_no_pending_work(tmp_path):
    """Step 7 is 'done' when final_pkl exists and all animals are reviewed with no pending drink masks."""
    psd_dir = _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    (psd_dir / "psds_final.pkl").touch()
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status="ok")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[6].kind == "done"
