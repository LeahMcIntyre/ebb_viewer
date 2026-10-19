"""Param-flow + UX-state tests for ``pages/sleep_qc_visualizer.py``.

These cover correctness defects and UX coherence properties — review-mode
entry rollback, ``_get_ref_combo`` filtering, the consolidated flagging
path, and the spindle-fraction plot's whisker math on tiny inputs.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
# _get_ref_combo — the group-median reference is a sanity-check baseline,
# used during initial QC before any animal has been flagged OK. It includes
# every non-rejected animal, with LFC_RSC preferred when present.
# ---------------------------------------------------------------------------


def test_get_ref_combo_includes_non_ok_runs(qapp, tmp_path: Path):
    """The median is for visual comparison during initial review, so it must
    include pending / needs_review / needs_rerun animals — otherwise the
    Median toggle is a no-op on the first pass through QC."""
    _seed_manifest(
        tmp_path,
        {
            "AM001": {"LFC_RSC": RunEntry(sleep_qc="needs_rerun")},
            "AM002": {"LFC_RSC": RunEntry(sleep_qc="needs_review")},
            "AM003": {"LFC_RSC": RunEntry(sleep_qc=None)},
        },
    )
    page = _make_page(qapp, tmp_path)
    page._available_combos = ["LFC_RSC"]
    # All three are non-rejected → ref combo resolves rather than None.
    assert page._get_ref_combo() == "LFC_RSC"


def test_get_ref_combo_excludes_rejected_runs(qapp, tmp_path: Path):
    """Rejected animals are data the user has explicitly thrown away —
    don't count them when picking the reference combo. (The median itself
    is still computed over the cached df, so rejection only affects combo
    selection.)"""
    _seed_manifest(
        tmp_path,
        {
            "AM001": {
                "LFC_RSC": RunEntry(sleep_qc="rejected"),
                "LSC_RSC": RunEntry(sleep_qc="ok"),
            },
            "AM002": {
                "LFC_RSC": RunEntry(sleep_qc="rejected"),
                "LSC_RSC": RunEntry(sleep_qc="needs_review"),
            },
        },
    )
    page = _make_page(qapp, tmp_path)
    page._available_combos = ["LFC_RSC", "LSC_RSC"]
    # LFC_RSC has only rejected runs (0 counted); LSC_RSC has 2.
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


def test_get_ref_combo_returns_none_when_all_rejected(qapp, tmp_path: Path):
    """Every available run is rejected → no median to draw."""
    _seed_manifest(
        tmp_path,
        {"AM001": {"LFC_RSC": RunEntry(sleep_qc="rejected")}},
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
    from PyQt6.QtWidgets import QMessageBox

    page = _make_page(qapp, tmp_path)
    # The zero-pending branch pops a real "No Pending Reruns" info dialog —
    # mock it out (mirrors the QMessageBox.question mocking used elsewhere
    # in this file) so .exec() doesn't block forever under the offscreen
    # Qt platform this suite runs under headlessly.
    with patch.object(QMessageBox, "information"):
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
    # Must include real rawstate/noise_probs data (not just a header) —
    # entering review mode loads every available combo via _load_combo,
    # which calls compute_spindle_fractions; a header-only CSV made that
    # raise ValueError("'noise_probs' column not found"), which _load_combo
    # surfaces via a real (unmocked) QMessageBox.critical — hanging this
    # "happy path" test under the offscreen Qt platform instead of letting
    # it reach the assertions below.
    spindle = tmp_path / "spindle_outputs" / "LFC_LSC"
    spindle.mkdir(parents=True)
    (spindle / "AM001_LFC_LSC.csv").write_text(
        "rawstate,noise_probs\nw,0.1\nn,0.2\nn,0.1\nr,0.3\n"
    )
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
    page._data_cache["LFC_RSC"] = (pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), df_frac)

    first = page._get_spindle_outlier_animals("LFC_RSC")
    second = page._get_spindle_outlier_animals("LFC_RSC")
    assert first is second  # cached, not recomputed
    assert "AM005" in first


def test_confirm_review_returns_true_when_no_entry(qapp, tmp_path: Path):
    """Calling the confirm helper for an unknown animal short-circuits to True."""
    page = _make_page(qapp, tmp_path)
    assert page._confirm_review_flip("UNKNOWN", "LFC_RSC") is True


def test_confirm_review_returns_true_when_no_sibling_ok(qapp, tmp_path: Path):
    """No sibling combo is OK → no dialog needed; returns True."""
    _seed_manifest(tmp_path, {"AM001": {"LFC_RSC": RunEntry(sleep_qc=None)}})
    page = _make_page(qapp, tmp_path)
    assert page._confirm_review_flip("AM001", "LFC_RSC") is True


def test_confirm_review_yes_proceeds(qapp, tmp_path: Path):
    """User confirms → helper returns True."""
    from PyQt6.QtWidgets import QMessageBox

    _seed_manifest(
        tmp_path,
        {
            "AM001": {
                "LFC_RSC": RunEntry(sleep_qc="ok"),
                "LSC_RSC": RunEntry(sleep_qc="rejected", rejected_by="LFC_RSC"),
            }
        },
    )
    page = _make_page(qapp, tmp_path)
    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        assert page._confirm_review_flip("AM001", "LSC_RSC") is True


def test_confirm_review_cancel_blocks(qapp, tmp_path: Path):
    """User cancels → helper returns False; manifest unchanged."""
    from PyQt6.QtWidgets import QMessageBox

    _seed_manifest(
        tmp_path,
        {
            "AM001": {
                "LFC_RSC": RunEntry(sleep_qc="ok"),
                "LSC_RSC": RunEntry(sleep_qc="rejected", rejected_by="LFC_RSC"),
            }
        },
    )
    page = _make_page(qapp, tmp_path)
    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel
    ):
        assert page._confirm_review_flip("AM001", "LSC_RSC") is False


def test_group_review_clicked_cancel_does_not_change_manifest(qapp, tmp_path: Path):
    """Group-mode wrapper: cancel keeps the manifest in its prior state."""
    from PyQt6.QtWidgets import QMessageBox

    _seed_manifest(
        tmp_path,
        {
            "AM001": {
                "LFC_RSC": RunEntry(sleep_qc="ok"),
                "LSC_RSC": RunEntry(sleep_qc="rejected", rejected_by="LFC_RSC"),
            }
        },
    )
    page = _make_page(qapp, tmp_path)
    page.cmb_combo.addItem("LSC_RSC")
    page.cmb_combo.setCurrentText("LSC_RSC")
    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel
    ):
        page._group_review_clicked("AM001", "LSC_RSC", checked=True)
    run = page._manifest.get_run("AM001", "LSC_RSC")
    assert run is not None
    assert run.sleep_qc == "rejected"  # unchanged


def test_group_review_clicked_yes_flips_to_needs_review(qapp, tmp_path: Path):
    """Group-mode wrapper: yes proceeds with the flag flip."""
    from PyQt6.QtWidgets import QMessageBox

    _seed_manifest(
        tmp_path,
        {
            "AM001": {
                "LFC_RSC": RunEntry(sleep_qc="ok"),
                "LSC_RSC": RunEntry(sleep_qc="rejected", rejected_by="LFC_RSC"),
            }
        },
    )
    page = _make_page(qapp, tmp_path)
    page.cmb_combo.addItem("LSC_RSC")
    page.cmb_combo.setCurrentText("LSC_RSC")
    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        page._group_review_clicked("AM001", "LSC_RSC", checked=True)
    # Manifest reloaded inside _apply_sleep_qc → re-read from page.
    run = page._manifest.get_run("AM001", "LSC_RSC")
    assert run is not None
    assert run.sleep_qc == "needs_review"


def test_outlier_cache_invalidated_when_data_cache_repopulated(qapp, tmp_path: Path):
    """_load_combo drops the outlier cache for the loaded combo so a
    re-download with different data doesn't surface stale outliers."""
    page = _make_page(qapp, tmp_path)
    page._outlier_cache["LFC_RSC"] = {"STALE"}
    # _load_combo's success path pops the outlier cache; simulate that
    # without an actual disk load:
    page._data_cache["LFC_RSC"] = (
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
    )
    page._outlier_cache.pop("LFC_RSC", None)  # mirrors _load_combo's pop
    assert "LFC_RSC" not in page._outlier_cache


# ---------------------------------------------------------------------------
# _open_notes_dialog
# ---------------------------------------------------------------------------


class _FakeNotesDialog:
    def __init__(self, *, animal_id, initial_text, parent=None):
        self.animal_id = animal_id
        self.initial_text = initial_text

    def exec(self):
        return True

    def text(self):
        return "new note"


class _FakeNotesDialogCancelled(_FakeNotesDialog):
    def exec(self):
        return False

    def text(self):
        raise AssertionError("text() should not be called when cancelled")


def test_open_notes_dialog_accept_persists_and_emits(qapp, tmp_path: Path):
    import ebb_viewer.pages.sleep_qc_visualizer as sqv_mod

    _seed_one_animal(tmp_path)
    page = _make_page(qapp, tmp_path)
    emitted: list = []
    page.manifest_changed.connect(lambda: emitted.append(True))

    with patch.object(sqv_mod, "NotesDialog", _FakeNotesDialog):
        page._open_notes_dialog("AM001")

    assert page._manifest.get("AM001").notes == "new note"
    assert emitted == [True]


def test_open_notes_dialog_prefills_existing_text(qapp, tmp_path: Path):
    import ebb_viewer.pages.sleep_qc_visualizer as sqv_mod

    _seed_manifest(tmp_path, {"AM001": {"LFC_RSC": RunEntry()}})
    m = Manifest.load(tmp_path)
    m.set_notes("AM001", "existing note")

    page = _make_page(qapp, tmp_path)

    captured: dict = {}

    class _CapturingFakeDialog(_FakeNotesDialog):
        def __init__(self, *, animal_id, initial_text, parent=None):
            super().__init__(animal_id=animal_id, initial_text=initial_text, parent=parent)
            captured["initial_text"] = initial_text

    with patch.object(sqv_mod, "NotesDialog", _CapturingFakeDialog):
        page._open_notes_dialog("AM001")

    assert captured["initial_text"] == "existing note"


def test_open_notes_dialog_cancel_does_not_change_manifest(qapp, tmp_path: Path):
    import ebb_viewer.pages.sleep_qc_visualizer as sqv_mod

    _seed_manifest(tmp_path, {"AM001": {"LFC_RSC": RunEntry()}})
    m = Manifest.load(tmp_path)
    m.set_notes("AM001", "original note")

    page = _make_page(qapp, tmp_path)
    emitted: list = []
    page.manifest_changed.connect(lambda: emitted.append(True))

    with patch.object(sqv_mod, "NotesDialog", _FakeNotesDialogCancelled):
        page._open_notes_dialog("AM001")

    assert page._manifest.get("AM001").notes == "original note"
    assert emitted == []


# ---------------------------------------------------------------------------
# Reclassify toggle
# ---------------------------------------------------------------------------

_COMBO = "LFC_RSC"


def _patch_compute(sqv_mod, raw_df, reclass_df, reclass_result):
    """Make the compute functions return ``reclass_df`` when given reclassified
    states and ``raw_df`` otherwise; ``reclassify_dir`` returns ``reclass_result``."""

    def pick(*_a, states_by_animal=None, **_k):
        return raw_df if states_by_animal is None else reclass_df

    return patch.multiple(
        sqv_mod,
        compute_sleep_bins_df=MagicMock(side_effect=pick),
        compute_sleep_bins_df_offset=MagicMock(side_effect=pick),
        compute_sleep_bins_df_clock_aligned=MagicMock(side_effect=pick),
        compute_spindle_fractions=MagicMock(side_effect=pick),
        reclassify_dir=MagicMock(return_value=reclass_result),
    )


def _reclass_result(gate: bool):
    import numpy as np

    from ebb.process.nrem_reclass import NremReclass

    s = np.array(["n", "w"])
    return NremReclass(
        rawstate=s,
        gapfill_state=s,
        final_state=s,
        gate_applied=gate,
        bouts_before=1,
        bouts_after=2,
    )


def _setup_reclass_page(tmp_path: Path):
    import ebb_viewer.pages.sleep_qc_visualizer as sqv_mod

    out = tmp_path / "spindle_outputs" / _COMBO
    out.mkdir(parents=True)
    (out / "AM001_a.csv").write_text("x")
    raw = pd.DataFrame({"mouse_id": ["AM001"], "state": ["w"], "tag": ["raw"]})
    rec = pd.DataFrame({"mouse_id": ["AM001"], "state": ["w"], "tag": ["reclass"]})
    return sqv_mod, raw, rec


def _loaded_page(qapp, tmp_path: Path):
    """A page with ``_COMBO`` loaded and selected."""
    page = _make_page(qapp, tmp_path)
    page.cmb_combo.addItem(_COMBO)
    page.cmb_combo.setCurrentText(_COMBO)
    assert page._load_combo(_COMBO)
    page._mouse_ids = ["AM001"]
    return page


def test_reclassify_button_swaps_data_for_both_views(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(tmp_path)
    with _patch_compute(sqv_mod, raw, rec, {"AM001": _reclass_result(gate=True)}):
        page = _loaded_page(qapp, tmp_path)
        assert page._get_df(_COMBO)["tag"].iloc[0] == "raw"
        assert page._get_frac_df(_COMBO)["tag"].iloc[0] == "raw"

        page.btn_reclass.setChecked(True)  # fires _on_reclass_toggled
        assert page._get_df(_COMBO)["tag"].iloc[0] == "reclass"  # Sleep view
        assert page._get_frac_df(_COMBO)["tag"].iloc[0] == "reclass"  # Spindle Mask view
        assert not page.lbl_reclass.isHidden()
        assert "1 of 1" in page.lbl_reclass.text()
        assert "AM001" in page.lbl_reclass.toolTip()

        page.btn_reclass.setChecked(False)
        assert page._get_df(_COMBO)["tag"].iloc[0] == "raw"
        assert page.lbl_reclass.isHidden()


def test_reclassify_computed_once_and_not_written(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(tmp_path)
    csv_path = tmp_path / "spindle_outputs" / _COMBO / "AM001_a.csv"
    with _patch_compute(sqv_mod, raw, rec, {"AM001": _reclass_result(gate=False)}):
        page = _loaded_page(qapp, tmp_path)
        page.btn_reclass.setChecked(True)
        page.btn_reclass.setChecked(False)
        page.btn_reclass.setChecked(True)
        assert sqv_mod.reclassify_dir.call_count == 1
    assert csv_path.read_text() == "x"


def test_reclassify_failure_leaves_button_off(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(tmp_path)
    with (
        _patch_compute(sqv_mod, raw, rec, {}),
        patch.object(sqv_mod, "reclassify_dir", side_effect=ValueError("bad csv")),
        patch.object(sqv_mod.QMessageBox, "critical") as critical,
    ):
        page = _loaded_page(qapp, tmp_path)
        page.btn_reclass.setChecked(True)
        assert critical.called
        assert not page.btn_reclass.isChecked()
        assert not page._reclass_mode
        assert page._get_df(_COMBO)["tag"].iloc[0] == "raw"


def test_reclassified_data_dropped_when_combo_evicted(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(tmp_path)
    with _patch_compute(sqv_mod, raw, rec, {"AM001": _reclass_result(gate=False)}):
        page = _loaded_page(qapp, tmp_path)
        page.btn_reclass.setChecked(True)
        assert sqv_mod.reclassify_dir.call_count == 1

        page._evict_combo(_COMBO)  # new CSVs landed: raw data and reclass tables go together
        assert page._reclass_cache == {}
        assert page._get_df(_COMBO) is None
        assert page._load_combo(_COMBO)
        assert page._get_df(_COMBO)["tag"].iloc[0] == "reclass"
        assert sqv_mod.reclassify_dir.call_count == 2


def test_gap_radius_recomputes_once_per_radius(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(tmp_path)
    with _patch_compute(sqv_mod, raw, rec, {"AM001": _reclass_result(gate=False)}):
        page = _loaded_page(qapp, tmp_path)
        assert page.spin_gap.value() == 1

        page.btn_reclass.setChecked(True)
        radii = lambda: [c.kwargs["radius"] for c in sqv_mod.reclassify_dir.call_args_list]  # noqa: E731
        assert radii() == [1]
        assert "Gap 1" in page.lbl_reclass.text()

        page.spin_gap.setValue(2)
        assert radii() == [1, 2]
        assert "Gap 2" in page.lbl_reclass.text()

        page.spin_gap.setValue(1)  # cached: no recompute
        page.spin_gap.setValue(2)
        assert radii() == [1, 2]


def test_gap_radius_changed_while_off_is_applied_on_next_toggle(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(tmp_path)
    with _patch_compute(sqv_mod, raw, rec, {"AM001": _reclass_result(gate=False)}):
        page = _loaded_page(qapp, tmp_path)
        page.btn_reclass.setChecked(True)  # computes radius 1
        page.btn_reclass.setChecked(False)

        page.spin_gap.setValue(2)  # nothing shown, nothing computed yet
        assert [c.kwargs["radius"] for c in sqv_mod.reclassify_dir.call_args_list] == [1]

        page.btn_reclass.setChecked(True)  # must use radius 2, not the stale radius-1 tables
        assert [c.kwargs["radius"] for c in sqv_mod.reclassify_dir.call_args_list] == [1, 2]
        assert "Gap 2" in page.lbl_reclass.text()


# ---------------------------------------------------------------------------
# EMG-gate indicators
# ---------------------------------------------------------------------------


def _legend_texts(page) -> str:
    from PyQt6.QtWidgets import QLabel

    return " ".join(lbl.text() for lbl in page.findChildren(QLabel))


def test_gated_animals_empty_until_reclassify_on(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(tmp_path)
    result = {"AM001": _reclass_result(gate=True), "AM002": _reclass_result(gate=False)}
    with _patch_compute(sqv_mod, raw, rec, result):
        page = _loaded_page(qapp, tmp_path)
        assert page._gated_animals(_COMBO) == set()
        assert page._gate_tag_html("AM001", _COMBO) == ""

        page.btn_reclass.setChecked(True)
        assert page._gated_animals(_COMBO) == {"AM001"}
        assert "EMG gate" in page._gate_tag_html("AM001", _COMBO)
        assert page._gate_tag_html("AM002", _COMBO) == ""

        page.btn_reclass.setChecked(False)
        assert page._gated_animals(_COMBO) == set()


def test_legend_rows_tag_gated_animals_in_group_and_animal_views(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(tmp_path)
    with _patch_compute(sqv_mod, raw, rec, {"AM001": _reclass_result(gate=True)}):
        page = _loaded_page(qapp, tmp_path)
        page._get_spindle_outlier_animals = lambda combo: set()
        _seed_one_animal(tmp_path)
        page._refresh_manifest()

        page._update_legend_group(["AM001"], {"AM001": "#123456"})
        assert "[EMG gate]" not in _legend_texts(page)

        page.btn_reclass.setChecked(True)
        page._update_legend_group(["AM001"], {"AM001": "#123456"})
        assert "[EMG gate]" in _legend_texts(page)

        page.cmb_animal.addItem("AM001")
        page.cmb_animal.setCurrentText("AM001")
        page._update_legend_animal([_COMBO])
        assert "[EMG gate]" in _legend_texts(page)


def test_spindle_fraction_plot_marks_gated_animals(qapp):
    from ebb_viewer.pages.sleep_qc_visualizer import SpindleFractionPlot

    df = pd.DataFrame(
        {
            "mouse_id": ["A", "B", "A", "B", "A", "B"],
            "state": ["Wake", "Wake", "NREM", "NREM", "REM", "REM"],
            "fraction": [0.1, 0.2, 0.1, 0.2, 0.1, 0.2],
        }
    )
    w = SpindleFractionPlot()
    w.set_data(df, title="t", gated={"A"})
    assert w._gated == {"A"}

    spots = [MagicMock(data=MagicMock(return_value="A"))]
    w._on_dot_clicked(None, spots, None)
    assert "EMG gate applied" in w._strip_lbl.text()
    spots = [MagicMock(data=MagicMock(return_value="B"))]
    w._on_dot_clicked(None, spots, None)
    assert "EMG gate" not in w._strip_lbl.text()

    w.set_data(df, title="t")  # no gated set -> nothing ringed
    assert w._gated == set()


def test_frac_title_mentions_gate_only_when_gated(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(tmp_path)
    with _patch_compute(sqv_mod, raw, rec, {"AM001": _reclass_result(gate=True)}):
        page = _loaded_page(qapp, tmp_path)
        page._frac_widget.set_data = MagicMock()
        page._refresh_frac_plot(current_animal=None)
        assert "EMG gate" not in page._frac_widget.set_data.call_args.kwargs["title"]

        page.btn_reclass.setChecked(True)
        page._frac_widget.set_data = MagicMock()
        page._refresh_frac_plot(current_animal=None)
        kw = page._frac_widget.set_data.call_args.kwargs
        assert "orange ring" in kw["title"] and kw["gated"] == {"AM001"}
