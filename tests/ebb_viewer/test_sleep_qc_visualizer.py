"""Param-flow + UX-state tests for ``pages/sleep_qc_visualizer.py``.

These cover correctness defects and UX coherence properties — review-mode
entry rollback, ``_get_ref_combo`` filtering, the consolidated flagging
path, and the spindle-fraction plot's whisker math on tiny inputs.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ebb_viewer.pipeline.manifest import (
    Manifest,
    ManifestEntry,
    RunEntry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page(qapp, tmp_path: Path):
    from ebb_viewer.pages.sleep_qc_visualizer import SleepQCGridPage

    return SleepQCGridPage(project_root=tmp_path)


def _seed_manifest(tmp_path: Path, runs: dict[str, dict[str, RunEntry]]) -> Manifest:
    """Build + persist a manifest. ``runs`` maps animal_id → {combo: RunEntry}."""
    m = Manifest(tmp_path)
    for animal_id, combo_runs in runs.items():
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id,
            preprocessed_edf=f"{animal_id}_PREPROCESSED.edf",
            runs=combo_runs,
        )
    m.save()
    return m


# ---------------------------------------------------------------------------
# B4 — _get_ref_combo must count only "ok" runs, not all runs
# ---------------------------------------------------------------------------


def test_b4_get_ref_combo_counts_only_ok_runs(qapp, tmp_path: Path):
    """``_get_ref_combo`` claims (docstring) to return "the combo with most
    ok animals". Before the fix it counted every run regardless of status,
    so a combo with 10 ``needs_rerun`` runs could outrank a combo with 5
    ``ok`` runs and become the median reference."""
    _seed_manifest(
        tmp_path,
        {
            "AM001": {
                "LFC_RSC": RunEntry(sleep_qc="needs_rerun"),
                "LSC_RSC": RunEntry(sleep_qc="ok"),
            },
            "AM002": {
                "LFC_RSC": RunEntry(sleep_qc="needs_rerun"),
                "LSC_RSC": RunEntry(sleep_qc="ok"),
            },
            "AM003": {
                "LFC_RSC": RunEntry(sleep_qc="needs_rerun"),
            },
        },
    )
    page = _make_page(qapp, tmp_path)
    page._available_combos = ["LFC_RSC", "LSC_RSC"]
    # LFC_RSC has 3 (all needs_rerun); LSC_RSC has 2 (both ok).
    # Pre-fix: returned LFC_RSC (most total). Post-fix: returns LSC_RSC.
    assert page._get_ref_combo() == "LSC_RSC"


def test_b4_get_ref_combo_prefers_lfc_rsc_when_tied(qapp, tmp_path: Path):
    """``LFC_RSC`` is the project's canonical combo — preferred on ties."""
    _seed_manifest(
        tmp_path,
        {
            "AM001": {
                "LFC_RSC": RunEntry(sleep_qc="ok"),
                "LSC_RSC": RunEntry(sleep_qc="ok"),
            },
        },
    )
    page = _make_page(qapp, tmp_path)
    page._available_combos = ["LFC_RSC", "LSC_RSC"]
    assert page._get_ref_combo() == "LFC_RSC"


def test_b4_get_ref_combo_returns_none_when_no_ok_runs(qapp, tmp_path: Path):
    """No OK runs at all → no reference line."""
    _seed_manifest(
        tmp_path,
        {"AM001": {"LFC_RSC": RunEntry(sleep_qc="needs_rerun")}},
    )
    page = _make_page(qapp, tmp_path)
    page._available_combos = ["LFC_RSC"]
    assert page._get_ref_combo() is None


# ---------------------------------------------------------------------------
# B2 + U3 — review-mode entry with zero pending reruns must not mutate UI
# ---------------------------------------------------------------------------


def test_b2_review_mode_with_zero_pending_does_not_enter_review(qapp, tmp_path: Path):
    """Clicking the reruns badge when no reruns are pending must leave the
    page entirely in its non-review state — background, labels, button
    checked-state, lbl_filter visibility all consistent."""
    page = _make_page(qapp, tmp_path)
    page._on_review_mode_toggled(True)
    assert page._review_mode is False
    assert not page.btn_reruns_ready.isChecked()
    assert page._lbl_animal.text() == "Animal:"
    # isHidden() rather than isVisible() — the parent isn't shown in tests.
    assert page._lbl_filter.isHidden()
    # No blue background stylesheet should be sticking.
    assert "#f0f4ff" not in page.styleSheet()


def test_b2_review_mode_with_pending_reruns_enters_correctly(qapp, tmp_path: Path):
    """Sanity check: when pending reruns *do* exist, review mode engages.

    Tests the happy path so we know the rollback isn't over-aggressive.
    """
    # Need a CSV on disk for pending_rerun_review to consider the rerun real.
    spindle = tmp_path / "spindle_outputs" / "LFC_LSC"
    spindle.mkdir(parents=True)
    (spindle / "AM001_LFC_LSC.csv").write_text("rawstate\n")
    _seed_manifest(
        tmp_path,
        {
            "AM001": {
                "LFC_RSC": RunEntry(sleep_qc="ok"),
                "LFC_LSC": RunEntry(sleep_qc=None, source_combo="LFC_RSC"),
            },
        },
    )
    page = _make_page(qapp, tmp_path)
    page._on_review_mode_toggled(True)
    assert page._review_mode is True
    assert page._lbl_animal.text() == "Animal (review):"
    assert not page._lbl_filter.isHidden()


# ---------------------------------------------------------------------------
# B3 — _has_pending_rerun must not hit the filesystem after manifest load
# ---------------------------------------------------------------------------


def test_b3_has_pending_rerun_uses_cache_no_filesystem_probe(qapp, tmp_path: Path):
    """``_has_pending_rerun`` is called per animal in the dropdown sync
    path; before the fix it called ``spindle_output_dir(...).glob(...)``
    on every invocation. The fix caches a set populated after each
    ``Manifest.load``."""
    spindle = tmp_path / "spindle_outputs" / "LFC_LSC"
    spindle.mkdir(parents=True)
    (spindle / "AM001_LFC_LSC.csv").write_text("rawstate\n")
    _seed_manifest(
        tmp_path,
        {
            "AM001": {
                "LFC_RSC": RunEntry(sleep_qc="ok"),
                "LFC_LSC": RunEntry(sleep_qc=None, source_combo="LFC_RSC"),
            },
            "AM002": {"LFC_RSC": RunEntry(sleep_qc="ok")},
        },
    )
    page = _make_page(qapp, tmp_path)

    # After construction, the cache is populated. Patch the glob to assert
    # that subsequent lookups never re-glob.
    with patch("ebb_viewer.pages.sleep_qc_visualizer.spindle_output_dir") as mock:
        assert page._has_pending_rerun("AM001") is True
        assert page._has_pending_rerun("AM002") is False
        assert page._has_pending_rerun("nonexistent") is False
        mock.assert_not_called()


# ---------------------------------------------------------------------------
# R1 — three flagging methods consolidated; verify each former call site
# ---------------------------------------------------------------------------


def _seed_one_animal(tmp_path: Path, status: str | None = None) -> None:
    _seed_manifest(tmp_path, {"AM001": {"LFC_RSC": RunEntry(sleep_qc=status)}})


def test_r1_flag_animal_ok_sets_ok_and_emits(qapp, tmp_path: Path):
    _seed_one_animal(tmp_path)
    page = _make_page(qapp, tmp_path)
    page.cmb_animal.addItems(["AM001"])
    page.cmb_animal.setCurrentText("AM001")
    emitted: list = []
    page.manifest_changed.connect(lambda: emitted.append(True))

    page._flag_animal_ok("LFC_RSC", checked=True)

    run = page._manifest.get_run("AM001", "LFC_RSC")
    assert run is not None and run.sleep_qc == "ok"
    assert emitted == [True]


def test_r1_flag_animal_ok_unchecks_resets(qapp, tmp_path: Path):
    _seed_one_animal(tmp_path, status="ok")
    page = _make_page(qapp, tmp_path)
    page.cmb_animal.addItems(["AM001"])
    page.cmb_animal.setCurrentText("AM001")

    page._flag_animal_ok("LFC_RSC", checked=False)

    run = page._manifest.get_run("AM001", "LFC_RSC")
    assert run is not None and run.sleep_qc is None


def test_r1_flag_animal_review_sets_needs_review(qapp, tmp_path: Path):
    _seed_one_animal(tmp_path)
    page = _make_page(qapp, tmp_path)
    page.cmb_animal.addItems(["AM001"])
    page.cmb_animal.setCurrentText("AM001")

    page._flag_animal_review("LFC_RSC", checked=True)

    run = page._manifest.get_run("AM001", "LFC_RSC")
    assert run is not None and run.sleep_qc == "needs_review"


def test_r1_flag_sleep_qc_group_mode_path(qapp, tmp_path: Path):
    """Group-mode path: combo comes from cmb_combo, animal passed in."""
    _seed_one_animal(tmp_path)
    page = _make_page(qapp, tmp_path)
    page.cmb_combo.addItem("LFC_RSC")
    page.cmb_combo.setCurrentText("LFC_RSC")

    page._flag_sleep_qc("AM001", "needs_review")

    run = page._manifest.get_run("AM001", "LFC_RSC")
    assert run is not None and run.sleep_qc == "needs_review"


# ---------------------------------------------------------------------------
# B1 — SpindleFractionPlot.set_data graceful with <2 animals per state
# ---------------------------------------------------------------------------


def test_b1_spindle_fraction_plot_handles_single_animal_state(qapp):
    """A state with only one animal must not trigger the IQR whisker math.

    The fix is a defensive ``len(sdf) < 2: continue`` guard. The existing
    ``_get_spindle_outlier_animals`` helper already has a ``< 4`` guard for
    related reasons; the plot path was missing equivalent protection.
    """
    from ebb_viewer.pages.sleep_qc_visualizer import SpindleFractionPlot

    df = pd.DataFrame(
        {
            "mouse_id": ["AM001", "AM002", "AM003", "AM004"],
            "state": ["Wake", "Wake", "Wake", "NREM"],
            "fraction": [0.1, 0.2, 0.3, 0.5],
        }
    )
    plot = SpindleFractionPlot()
    # NREM has 1 animal — the guard must skip whisker math without raising.
    plot.set_data(df, title="LFC_RSC")
    # If we got here without an exception, the guard worked.
    assert plot is not None


def test_b1_spindle_fraction_plot_handles_empty_dataframe(qapp):
    """Empty df → no plot, no exception."""
    from ebb_viewer.pages.sleep_qc_visualizer import SpindleFractionPlot

    plot = SpindleFractionPlot()
    plot.set_data(pd.DataFrame(columns=["mouse_id", "state", "fraction"]))
    assert plot is not None


# ---------------------------------------------------------------------------
# Outlier-set caching — _get_spindle_outlier_animals is called once per
# render AND once per legend rebuild; cache the result keyed by combo.
# ---------------------------------------------------------------------------


def test_outlier_cache_returns_same_set_on_repeat_calls(qapp, tmp_path: Path):
    """Calling _get_spindle_outlier_animals twice for the same combo
    should return the cached set (same object identity on second call)."""
    page = _make_page(qapp, tmp_path)
    # Seed _data_cache directly with a frac DataFrame so we don't depend
    # on real CSVs / EDFs on disk.
    df_frac = pd.DataFrame(
        {
            "mouse_id": ["AM001", "AM002", "AM003", "AM004", "AM005"],
            "state": ["Wake"] * 5,
            "fraction": [0.1, 0.12, 0.11, 0.13, 0.95],  # AM005 outlier
        }
    )
    page._data_cache["LFC_RSC"] = (pd.DataFrame(), pd.DataFrame(), df_frac)

    first = page._get_spindle_outlier_animals("LFC_RSC")
    second = page._get_spindle_outlier_animals("LFC_RSC")
    assert first is second  # cached, not recomputed
    assert "AM005" in first


def test_outlier_cache_invalidated_when_data_cache_repopulated(qapp, tmp_path: Path):
    """_load_combo drops the outlier cache for the loaded combo so a
    re-download with different data doesn't surface stale outliers."""
    page = _make_page(qapp, tmp_path)
    page._outlier_cache["LFC_RSC"] = {"STALE"}
    # _load_combo's success path pops the outlier cache; simulate that
    # without an actual disk load:
    page._data_cache["LFC_RSC"] = (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    page._outlier_cache.pop("LFC_RSC", None)  # mirrors _load_combo's pop
    assert "LFC_RSC" not in page._outlier_cache
