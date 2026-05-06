"""Tests for compute_pipeline_status in home.py.

Focuses on the PSD step gate: step 6 should be "attention" when some animals
still have sleep_qc == "needs_review", not "active", even if n_ok > 0.
"""

from pathlib import Path

from ebb_viewer.pages.home import compute_pipeline_status
from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry, RunEntry

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


def _setup_psd_run(tmp_path: Path, run_name: str = "default") -> Path:
    """Create psd/<run_name>/ with psd_params.json + psds_channel_merged.pkl."""
    run_dir = tmp_path / "psd" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "psd_params.json").write_text("{}")
    (run_dir / "psds_channel_merged.pkl").touch()
    return run_dir


# ---------------------------------------------------------------------------
# Step 6: PSD gate on Sleep QC resolved
# ---------------------------------------------------------------------------

def test_step6_active_when_all_qc_resolved(tmp_path):
    """Step 6 is 'active' when all animals each have exactly 1 ok run."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s6 = statuses[5]
    assert s6.kind == "active"
    assert "1 ok run" in s6.description


def test_step6_blocked_when_review_pending_and_ok_exists(tmp_path):
    """Step 6 is 'blocked' when some animals still need EDF review."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
        "A002": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s6 = statuses[5]
    assert s6.kind == "blocked"
    assert "1" in s6.description


def test_step6_blocked_message_includes_not_ready_count(tmp_path):
    """Step 6 blocked message names the number of animals not yet ready."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
        "A002": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
        "A003": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s6 = statuses[5]
    assert s6.kind == "blocked"
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


def test_step6_active_when_cascade_rejected_run_exists(tmp_path):
    """An animal with one ok run and one cascade-rejected run is still ready for PSD."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok")},
        # A002: LFC_RSC ok, LSC_RSC cascade-rejected — still has exactly 1 ok run
        "A002": {
            "LFC_RSC": RunEntry(sleep_qc="ok"),
            "LSC_RSC": RunEntry(sleep_qc="rejected", rejected_by="LFC_RSC"),
        },
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s6 = statuses[5]
    assert s6.kind == "active"


def test_step6_done_when_final_pkl_exists(tmp_path):
    """Step 6 is 'done' when psds_channel_merged.pkl exists in a run directory."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    _setup_psd_run(tmp_path)
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
    """Set up filesystem + return psd run_dir with psds_channel_merged.pkl created."""
    _setup_filesystem(tmp_path, combos=combos)
    run_dir = _setup_psd_run(tmp_path)
    for combo in combos:
        (run_dir / f"psds_{combo}.pkl").touch()
    return run_dir


def test_step8_blocked_when_no_final_pkl(tmp_path):
    """Step 8 is 'blocked' until psds_channel_merged.pkl exists."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "needs_drink_mask"})},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[7].kind == "blocked"


def test_step8_attention_when_drink_mask_needed(tmp_path):
    """Step 8 is 'attention' when animals are flagged needs_drink_mask."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "needs_drink_mask"})},
        "A002": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "needs_drink_mask"})},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s8 = statuses[7]
    assert s8.kind == "attention"
    assert "2" in s8.description


def test_step8_done_when_drink_masks_applied(tmp_path):
    """Step 8 is 'done' with count when all flagged animals have masks applied."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "drink_mask_applied"})},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s8 = statuses[7]
    assert s8.kind == "done"
    assert "1" in s8.description


def test_step8_done_none_needed_when_all_ok(tmp_path):
    """Step 8 is 'done (none needed)' when final PKL exists and no animals need a drink mask."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "ok"})},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    s8 = statuses[7]
    assert s8.kind == "done"
    assert "no drink masks needed" in s8.description.lower()




# ---------------------------------------------------------------------------
# Gap 3: regression guard — merged_pkl absent despite reviewed animals
# ---------------------------------------------------------------------------

def test_step7_blocked_when_merged_pkl_absent_despite_reviewed_animals(tmp_path):
    """Step 7 is 'blocked' when no run directories exist even if psd_status flags are set."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "ok"})},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[6].kind == "blocked"


# ---------------------------------------------------------------------------
# Gap 6: step 7 must not show "done" when an animal needs drink mask
# ---------------------------------------------------------------------------

def test_step7_not_done_when_animal_needs_drink_mask(tmp_path):
    """Step 7 must not show 'done' when an animal is flagged needs_drink_mask."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "needs_drink_mask"})},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[6].kind != "done"


def test_step7_done_when_all_reviewed_no_pending_work(tmp_path):
    """Step 7 is 'done' when all PSDs are reviewed and no drink masks pending."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {
        "A001": {"LFC_RSC": RunEntry(sleep_qc="ok", psd_status={"default": "ok"})},
    })
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[6].kind == "done"
