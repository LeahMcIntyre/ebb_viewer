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
    """Step 6 is 'done' when psds_final.pkl exists regardless of review state."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    psd_dir = tmp_path / "psd"
    psd_dir.mkdir()
    (psd_dir / "psds_final.pkl").touch()
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
    """Set up filesystem + return psd_dir with psds_final.pkl created."""
    _setup_filesystem(tmp_path, combos=combos)
    psd_dir = tmp_path / "psd"
    psd_dir.mkdir()
    (psd_dir / "psds_final.pkl").touch()
    for combo in combos:
        (psd_dir / f"psds_{combo}.pkl").touch()
    return psd_dir


def test_step8_blocked_when_no_final_pkl(tmp_path):
    """Step 8 is 'blocked' until psds_final.pkl exists."""
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
