"""Tests for compute_pipeline_status in home.py.

Focuses on the PSD step gate: step 5 should be "attention" when some animals
still have sleep_qc == "needs_review", not "active", even if n_ok > 0.
"""

from pathlib import Path

from ebb_viewer.pages.home import compute_pipeline_status
from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(tmp_path: Path, animals: dict) -> Manifest:
    m = Manifest(tmp_path)
    for animal_id, fields in animals.items():
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id,
            preprocessed_edf=f"standard/{animal_id}_PREPROCESSED.edf",
            has_spindle=True,
            **fields,
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
    """Create psd/<run_name>/ with psd_params.json + psds_LFC_RSC.pkl."""
    run_dir = tmp_path / "psd" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "psd_params.json").write_text("{}")
    (run_dir / "psds_LFC_RSC.pkl").touch()
    return run_dir


# ---------------------------------------------------------------------------
# Step 5: PSD gate on Sleep QC resolved
# ---------------------------------------------------------------------------


def test_step5_active_when_all_qc_resolved(tmp_path):
    """Step 5 is 'active' when all animals are marked ok."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok"),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    s5 = statuses[6]
    assert s5.kind == "active"
    assert "marked ok" in s5.description


def test_sleep_qc_step_counts_excluded_as_decided(tmp_path):
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {"A001": dict(sleep_qc="ok"), "A002": dict(sleep_qc="excluded")})
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[5].kind == "done"
    assert statuses[5].description == "1 animal marked ok, 1 excluded"
    assert statuses[6].kind == "active"  # PSD compute can run: excluded animals are still computed
    assert statuses[6].description == "Ready — 2 animals (1 excluded, still computed)"


def test_step5_blocked_when_review_pending_and_ok_exists(tmp_path):
    """Step 5 is 'blocked' when some animals still need EDF review."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok"),
            "A002": dict(sleep_qc="needs_review"),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    s5 = statuses[6]
    assert s5.kind == "blocked"
    assert "1" in s5.description


def test_step5_blocked_message_includes_not_ready_count(tmp_path):
    """Step 5 blocked message names the number of animals not yet ready."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok"),
            "A002": dict(sleep_qc="needs_review"),
            "A003": dict(sleep_qc="needs_review"),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    s5 = statuses[6]
    assert s5.kind == "blocked"
    assert "2" in s5.description


def test_step5_blocked_when_no_ok_animals(tmp_path):
    """Step 5 remains 'blocked' when there are no ok animals, even with reviews pending."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="needs_review"),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    s5 = statuses[6]
    assert s5.kind == "blocked"


def test_step5_done_when_final_pkl_exists(tmp_path):
    """Step 5 is 'done' when psds_LFC_RSC.pkl exists in a run directory."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    _setup_psd_run(tmp_path)
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok"),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    s5 = statuses[6]
    assert s5.kind == "done"


# ---------------------------------------------------------------------------
# Step 7: Drink Mask gate
# ---------------------------------------------------------------------------


def _setup_with_final_pkl(tmp_path: Path, combos: list[str]) -> Path:
    """Set up filesystem + return psd run_dir with psds_LFC_RSC.pkl created."""
    _setup_filesystem(tmp_path, combos=combos)
    run_dir = _setup_psd_run(tmp_path)
    for combo in combos:
        (run_dir / f"psds_{combo}.pkl").touch()
    return run_dir


def test_step7_blocked_when_no_final_pkl(tmp_path):
    """Step 7 is 'blocked' until psds_LFC_RSC.pkl exists."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok", psd_status={"default": "needs_drink_mask"}),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[8].kind == "blocked"


def test_step7_attention_when_drink_mask_needed(tmp_path):
    """Step 7 is 'attention' when animals are flagged needs_drink_mask."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok", psd_status={"default": "needs_drink_mask"}),
            "A002": dict(sleep_qc="ok", psd_status={"default": "needs_drink_mask"}),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    s7 = statuses[8]
    assert s7.kind == "attention"
    assert "2" in s7.description


def test_step7_done_when_drink_masks_applied(tmp_path):
    """Step 7 is 'done' with count when all flagged animals have masks applied."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok", psd_status={"default": "drink_mask_applied"}),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    s7 = statuses[8]
    assert s7.kind == "done"
    assert "1" in s7.description


def test_step7_done_none_needed_when_all_ok(tmp_path):
    """Step 7 is 'done (none needed)' when final PKL exists and no animals need a drink mask."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok", psd_status={"default": "ok"}),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    s7 = statuses[8]
    assert s7.kind == "done"
    assert "no drink masks needed" in s7.description.lower()


# ---------------------------------------------------------------------------
# Regression guard — merged_pkl absent despite reviewed animals
# ---------------------------------------------------------------------------


def test_step6_blocked_when_merged_pkl_absent_despite_reviewed_animals(tmp_path):
    """Step 6 is 'blocked' when no run directories exist even if psd_status flags are set."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok", psd_status={"default": "ok"}),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[7].kind == "blocked"


def test_excluded_unreviewed_animal_does_not_make_psd_review_attention(tmp_path):
    """An excluded animal has no PSD status and is not queued, so it cannot hold up step 7."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok", psd_status={"default": "ok"}),
            "A002": dict(sleep_qc="excluded"),
        },
    )
    assert len(m.all_pending_psd_review()) == 0
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[7].kind != "attention"


# ---------------------------------------------------------------------------
# Step 6 must not show "done" when an animal needs drink mask
# ---------------------------------------------------------------------------


def test_step6_not_done_when_animal_needs_drink_mask(tmp_path):
    """Step 6 must not show 'done' when an animal is flagged needs_drink_mask."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok", psd_status={"default": "needs_drink_mask"}),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[7].kind != "done"


def test_step6_done_when_all_reviewed_no_pending_work(tmp_path):
    """Step 6 is 'done' when all PSDs are reviewed and no drink masks pending."""
    _setup_with_final_pkl(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(
        tmp_path,
        {
            "A001": dict(sleep_qc="ok", psd_status={"default": "ok"}),
        },
    )
    statuses = compute_pipeline_status(tmp_path, m)
    assert statuses[7].kind == "done"


# ---------------------------------------------------------------------------
# Step 4: Reclassify (index 3, between Spindle Upload and Sleep QC)
# ---------------------------------------------------------------------------


def test_reclassify_blocked_until_spindle_outputs_exist(tmp_path):
    m = _make_manifest(tmp_path, {"A001": {}})
    statuses = compute_pipeline_status(tmp_path, m)
    assert len(statuses) == 9
    assert statuses[3].kind == "blocked"


def _write_csv(tmp_path: Path, name: str, *, final_state: bool) -> None:
    d = tmp_path / "spindle_outputs" / "LFC_RSC"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("state,final_state\nw,w\n" if final_state else "state\nw\n")


def test_reclassify_active_when_outputs_exist_but_none_reclassified(tmp_path):
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    _write_csv(tmp_path, "A001_labels.csv", final_state=False)
    m = _make_manifest(tmp_path, {"A001": {}})
    assert compute_pipeline_status(tmp_path, m)[3].kind == "active"


def test_reclassify_attention_when_some_csvs_lack_final_state(tmp_path):
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    _write_csv(tmp_path, "A001_labels.csv", final_state=True)
    _write_csv(tmp_path, "A002_labels.csv", final_state=False)
    _write_csv(tmp_path, "A003_labels.csv", final_state=False)
    m = _make_manifest(tmp_path, {"A001": {}, "A002": {}, "A003": {}})
    s = compute_pipeline_status(tmp_path, m)[3]
    assert s.kind == "attention"
    assert "2 of 3" in s.description


def test_reclassify_done_reports_gate_count(tmp_path):
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    _write_csv(tmp_path, "A001_labels.csv", final_state=True)
    _write_csv(tmp_path, "A002_labels.csv", final_state=True)
    m = _make_manifest(
        tmp_path,
        {"A001": dict(reclass_gate_applied=True), "A002": dict(reclass_gate_applied=False)},
    )
    s = compute_pipeline_status(tmp_path, m)[3]
    assert s.kind == "done"
    assert "2 reclassified" in s.description and "gate on 1" in s.description


def test_reclassify_ignores_stale_manifest_flag_when_csv_lost_its_column(tmp_path):
    """Re-downloading a CSV from SleepyRat drops final_state; the manifest flag is stale."""
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    _write_csv(tmp_path, "A001_labels.csv", final_state=False)
    m = _make_manifest(tmp_path, {"A001": dict(reclass_gate_applied=True)})
    assert compute_pipeline_status(tmp_path, m)[3].kind == "active"


# ---------------------------------------------------------------------------
# Step 4b: SWD Review (index 4, optional)
# ---------------------------------------------------------------------------


def _reclassified_project(tmp_path, animals: dict, *, swd_for=()):
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    for name in animals:
        _write_csv(tmp_path, f"{name}_labels.csv", final_state=True)
    (tmp_path / "swd").mkdir(exist_ok=True)
    for name in swd_for:
        (tmp_path / "swd" / f"{name}_swd.mat").touch()
    m = _make_manifest(tmp_path, animals)
    return m


def test_swd_review_off_by_default(tmp_path):
    m = _reclassified_project(tmp_path, {"A001": dict(reclass_gate_applied=False)})
    s = compute_pipeline_status(tmp_path, m)[4]
    assert s.kind == "off" and "Not enabled" in s.description


def test_swd_review_blocked_until_reclassified(tmp_path):
    _setup_filesystem(tmp_path, combos=["LFC_RSC"])
    m = _make_manifest(tmp_path, {"A001": {}})
    m.swd_review_enabled = True
    assert compute_pipeline_status(tmp_path, m)[4].kind == "blocked"


def test_swd_review_progress_states(tmp_path):
    animals = {"A001": dict(reclass_gate_applied=False), "A002": dict(reclass_gate_applied=False)}
    m = _reclassified_project(tmp_path, animals, swd_for=["A001", "A002"])
    m.swd_review_enabled = True
    s = compute_pipeline_status(tmp_path, m)[4]
    assert s.kind == "active" and "Ready" in s.description

    m.get("A001").swd_reviewed, m.get("A001").swd_total = 3, 3
    s = compute_pipeline_status(tmp_path, m)[4]
    assert s.kind == "attention" and "1 of 2" in s.description

    m.get("A002").swd_reviewed, m.get("A002").swd_total = 1, 3  # started, not finished
    s = compute_pipeline_status(tmp_path, m)[4]
    assert s.kind == "attention" and "1 in progress" in s.description

    m.get("A002").swd_reviewed = 3
    assert compute_pipeline_status(tmp_path, m)[4].kind == "done"


def test_swd_review_needs_a_file_or_a_confirmation_for_every_animal(tmp_path):
    animals = {"A001": dict(reclass_gate_applied=False), "A002": dict(reclass_gate_applied=False)}
    m = _reclassified_project(tmp_path, animals, swd_for=["A001"])  # A002 has no SWD file
    m.swd_review_enabled = True
    m.get("A001").swd_reviewed, m.get("A001").swd_total = 2, 2

    s = compute_pipeline_status(tmp_path, m)[4]
    assert s.kind == "attention" and "1 without an SWD file" in s.description

    m.get("A002").swd_waived = True  # user confirmed it needs none
    assert compute_pipeline_status(tmp_path, m)[4].kind == "done"


def test_swd_review_all_animals_missing_files_is_attention(tmp_path):
    m = _reclassified_project(tmp_path, {"A001": dict(reclass_gate_applied=False)})
    m.swd_review_enabled = True
    s = compute_pipeline_status(tmp_path, m)[4]
    assert s.kind == "attention" and "without an SWD file" in s.description


def test_swd_review_empty_swd_file_has_nothing_to_review(tmp_path):
    m = _reclassified_project(tmp_path, {"A001": dict(reclass_gate_applied=False)}, swd_for=["A001"])
    m.swd_review_enabled = True
    m.get("A001").swd_reviewed, m.get("A001").swd_total = 0, 0  # empty .mat: no SWD epochs
    assert compute_pipeline_status(tmp_path, m)[4].kind == "done"


def test_excluded_sleep_qc_cell_is_labelled_and_carries_the_reason(qapp):
    from ebb_viewer.pages.home import HomePage

    cell = HomePage._build_sleep_qc_cell(None, "excluded", True, "Excluded (Sleep QC): lost signal")
    assert cell.text() == "Excluded"
    assert cell.toolTip() == "Excluded (Sleep QC): lost signal"
    assert HomePage._build_sleep_qc_cell(None, "ok", True, "x").toolTip() == ""
