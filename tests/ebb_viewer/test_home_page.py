"""Tests for ``pages/home.py`` — HomePage smoke + PSD-status precedence.

The pure-logic ``compute_pipeline_status`` is covered separately in
``test_compute_pipeline_status.py``. These tests focus on the UI-side
table-rendering logic, particularly the PSD Status column's "best-wins"
precedence across multi-run manifests.
"""

from __future__ import annotations

from pathlib import Path

from ebb_viewer.pipeline.manifest import (
    Manifest,
    ManifestEntry,
    RunEntry,
)

# Column index for "PSD Status" in the Pipeline Summary table.
_PSD_STATUS_COL = 8


def _make_page(qapp, tmp_path: Path):
    from ebb_viewer.pages.home import HomePage

    return HomePage(project_root=tmp_path)


def _seed_manifest(
    tmp_path: Path,
    psd_status: dict[str, str],
    *,
    sleep_qc: str | None = "ok",
) -> None:
    """One animal, one combo, with the given per-run psd_status dict."""
    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        runs={"LFC_RSC": RunEntry(sleep_qc=sleep_qc, psd_status=psd_status)},
    )
    m.save()


def _psd_status_cell(page) -> str:
    """Read the PSD Status column text for the first row."""
    item = page.table.item(0, _PSD_STATUS_COL)
    return item.text() if item is not None else ""


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


def test_page_constructs_with_empty_project(qapp, tmp_path: Path):
    """HomePage builds and refreshes on an empty project without exception."""
    page = _make_page(qapp, tmp_path)
    assert page is not None
    # Table should exist with 0 rows (no animals in manifest).
    assert page.table.rowCount() == 0


# ---------------------------------------------------------------------------
# B4 — PSD-status column "best-wins" precedence
#
# Precedence (analysis-readiness, highest wins):
#   drink_mask_applied > ok > needs_drink_mask
#
# Rationale: the column reflects the analysis-ready state for the
# (animal, combo). Pending-work signal is surfaced separately via the
# attention card (Manifest.all_needs_drink_mask) and per-run PSD Review.
# ---------------------------------------------------------------------------


def test_psd_status_drink_mask_applied_beats_needs_drink_mask(qapp, tmp_path: Path):
    """If any PSD run has drink_mask_applied, the column reads as such even
    when other runs still need the mask. Pre-fix the column showed
    'needs drink mask' here."""
    _seed_manifest(
        tmp_path,
        psd_status={
            "default": "drink_mask_applied",
            "dark_phase": "needs_drink_mask",
        },
    )
    page = _make_page(qapp, tmp_path)
    assert _psd_status_cell(page) == "drink mask applied"


def test_psd_status_drink_mask_applied_beats_ok(qapp, tmp_path: Path):
    """drink_mask_applied is the cleanest analysis-ready state."""
    _seed_manifest(
        tmp_path,
        psd_status={
            "default": "drink_mask_applied",
            "dark_phase": "ok",
        },
    )
    page = _make_page(qapp, tmp_path)
    assert _psd_status_cell(page) == "drink mask applied"


def test_psd_status_ok_beats_needs_drink_mask(qapp, tmp_path: Path):
    """A clean ok run still indicates analysis-readiness over a pending mask."""
    _seed_manifest(
        tmp_path,
        psd_status={
            "default": "ok",
            "dark_phase": "needs_drink_mask",
        },
    )
    page = _make_page(qapp, tmp_path)
    assert _psd_status_cell(page) == "ok"


def test_psd_status_needs_drink_mask_alone(qapp, tmp_path: Path):
    """All runs pending → column reflects the pending state."""
    _seed_manifest(
        tmp_path,
        psd_status={"default": "needs_drink_mask"},
    )
    page = _make_page(qapp, tmp_path)
    # Without an on-disk drink-mask npy, the cell reads "needs drink mask".
    assert _psd_status_cell(page) == "needs drink mask"


def test_psd_status_empty_dict_falls_through_to_dash(qapp, tmp_path: Path):
    """No PSD runs at all → column reads "—" (no psd_file_ok, no status)."""
    _seed_manifest(tmp_path, psd_status={})
    page = _make_page(qapp, tmp_path)
    assert _psd_status_cell(page) == "—"


# ---------------------------------------------------------------------------
# B3 — compute_pipeline_status: step 5 must distinguish "rerun accepted"
# from "rerun rejected" (target combo's sleep_qc must be ok, not rejected).
# ---------------------------------------------------------------------------


def test_b3_step5_blocked_when_rerun_target_was_rejected(tmp_path: Path):
    """A needs_rerun original whose rerun target ended up rejected (not ok)
    must NOT show step 5 as ``done`` — there's no accepted rerun to take
    forward. Pre-fix the count-only check incorrectly marked it done."""
    from ebb_viewer.pages.home import compute_pipeline_status

    # Set up minimal filesystem so step 3 passes.
    (tmp_path / "standard").mkdir()
    (tmp_path / "standard" / "AM001.edf").write_text("")
    edf_dir = tmp_path / "spindle_edfs" / "LFC_RSC"
    edf_dir.mkdir(parents=True)
    (edf_dir / "AM001_LFC_RSC_spindle.edf").write_text("")
    out_dir = tmp_path / "spindle_outputs" / "LFC_RSC"
    out_dir.mkdir(parents=True)
    (out_dir / "AM001_LFC_RSC.csv").write_text("rawstate\n")

    # AM001: LFC_RSC needs_rerun → rerun_combo LSC_RSC was rejected.
    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        runs={
            "LFC_RSC": RunEntry(sleep_qc="needs_rerun", rerun_combo="LSC_RSC"),
            "LSC_RSC": RunEntry(sleep_qc="rejected"),
        },
    )
    m.save()

    statuses = compute_pipeline_status(tmp_path, m)
    # Step indices are 0-based.
    s5 = statuses[4]
    assert s5.kind != "done", (
        f"Step 5 must not be done when rerun target was rejected. Got: {s5}"
    )


def test_b3_step5_done_when_rerun_target_ok(tmp_path: Path):
    """Happy path: rerun target accepted as ok → step 5 done."""
    from ebb_viewer.pages.home import compute_pipeline_status

    (tmp_path / "standard").mkdir()
    (tmp_path / "standard" / "AM001.edf").write_text("")
    edf_dir = tmp_path / "spindle_edfs" / "LFC_RSC"
    edf_dir.mkdir(parents=True)
    (edf_dir / "AM001_LFC_RSC_spindle.edf").write_text("")
    out_dir = tmp_path / "spindle_outputs" / "LFC_RSC"
    out_dir.mkdir(parents=True)
    (out_dir / "AM001_LFC_RSC.csv").write_text("rawstate\n")

    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        runs={
            "LFC_RSC": RunEntry(sleep_qc="needs_rerun", rerun_combo="LSC_RSC"),
            "LSC_RSC": RunEntry(sleep_qc="ok"),
        },
    )
    m.save()

    statuses = compute_pipeline_status(tmp_path, m)
    s5 = statuses[4]
    assert s5.kind == "done", f"Step 5 should be done when rerun target is ok. Got: {s5}"


# ---------------------------------------------------------------------------
# B1 — _open_windows must shrink when an opened window is destroyed.
# ---------------------------------------------------------------------------


def test_b1_open_windows_prunes_on_destroy(qapp, tmp_path: Path):
    """Closing an EDF viewer window must drop it from ``_open_windows`` so
    its (potentially large) recording data can be garbage-collected."""
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QWidget

    page = _make_page(qapp, tmp_path)
    fake_win = QWidget()
    # Wire the same way _open_edf_for_animal does after the fix.
    fake_win.destroyed.connect(lambda _, w=fake_win: page._on_window_closed(w))
    page._open_windows.append(fake_win)
    assert len(page._open_windows) == 1

    fake_win.deleteLater()
    # Drain the DeferredDelete event queue so the destroyed signal actually
    # fires within the test rather than at GC time.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert len(page._open_windows) == 0


def test_b1_on_window_closed_handles_unknown_window(qapp, tmp_path: Path):
    """Calling _on_window_closed with a window that was never in the list
    must not raise — the slot is connected via lambda and may fire after
    the list was already cleared (e.g. during page teardown)."""
    from PyQt6.QtWidgets import QWidget

    page = _make_page(qapp, tmp_path)
    stranger = QWidget()
    # Should not raise.
    page._on_window_closed(stranger)
    assert page._open_windows == []


# ---------------------------------------------------------------------------
# B4 — _on_cell_double_clicked must use the cached row list (matching what
# the user sees), not re-derive from a fresh manifest load.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Row-builder Sleep QC cell — covers the rerun → done / pending / needs_rerun
# branches that previously lived inline in _refresh.
# ---------------------------------------------------------------------------


def _sleep_qc_cell(page) -> str:
    """Read the Sleep QC column text for the first row (column index 6)."""
    item = page.table.item(0, 6)
    return item.text() if item is not None else ""


def test_sleep_qc_cell_pending_when_spindle_out_exists(qapp, tmp_path: Path):
    """sleep_qc is None and the spindle output CSV exists on disk → 'pending'."""
    (tmp_path / "spindle_outputs" / "LFC_RSC").mkdir(parents=True)
    (tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_LFC_RSC.csv").write_text("")
    _seed_manifest(tmp_path, psd_status={}, sleep_qc=None)
    page = _make_page(qapp, tmp_path)
    assert _sleep_qc_cell(page) == "pending"


def test_sleep_qc_cell_dash_when_no_spindle_output(qapp, tmp_path: Path):
    """sleep_qc is None and no spindle output → '—'."""
    _seed_manifest(tmp_path, psd_status={}, sleep_qc=None)
    page = _make_page(qapp, tmp_path)
    assert _sleep_qc_cell(page) == "—"


def test_sleep_qc_cell_needs_review_shows_sibling_ok_hint(qapp, tmp_path: Path):
    """A needs_review row whose sibling combo is OK should surface the
    relationship inline: e.g. 'Review EDF (LFC_RSC ok)' + a tooltip.

    Background: when the user clicks Review on a cascade-rejected sibling,
    the manifest transitions it to 'needs_review' and *clears* the
    rejected_by metadata. Without a hint in the cell, the summary table
    looks like there are two competing flags for one animal.
    """
    from ebb_viewer.pipeline.manifest import (
        Manifest,
        ManifestEntry,
        RunEntry,
    )

    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        runs={
            "LFC_RSC": RunEntry(sleep_qc="ok"),
            "LSC_RSC": RunEntry(sleep_qc="needs_review"),
        },
    )
    m.save()
    page = _make_page(qapp, tmp_path)

    # Find the LSC_RSC row in the rendered table (order depends on dict
    # insertion order, but both rows are rendered when hide_rejected
    # filters nothing).
    lsc_row = next(
        i for i, (_e, c, _r) in enumerate(page._table_rows) if c == "LSC_RSC"
    )
    cell = page.table.item(lsc_row, 6)
    assert "Review EDF" in cell.text()
    assert "LFC_RSC ok" in cell.text()
    assert "LFC_RSC" in cell.toolTip()


def test_sleep_qc_cell_needs_review_without_sibling_ok_is_terse(qapp, tmp_path: Path):
    """If no sibling is OK, the cell stays terse — just 'Review EDF'."""
    from ebb_viewer.pipeline.manifest import (
        Manifest,
        ManifestEntry,
        RunEntry,
    )

    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        runs={"LSC_RSC": RunEntry(sleep_qc="needs_review")},
    )
    m.save()
    page = _make_page(qapp, tmp_path)

    cell = page.table.item(0, 6)
    assert cell.text() == "Review EDF"
    assert cell.toolTip() == ""


def test_sleep_qc_cell_rerun_done_when_target_ok(qapp, tmp_path: Path):
    """A needs_rerun row whose rerun target is ok → 'rerun done ✓'."""
    from ebb_viewer.pipeline.manifest import (
        Manifest,
        ManifestEntry,
        RunEntry,
    )

    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        runs={
            "LFC_RSC": RunEntry(sleep_qc="needs_rerun", rerun_combo="LSC_RSC"),
            "LSC_RSC": RunEntry(sleep_qc="ok"),
        },
    )
    m.save()
    page = _make_page(qapp, tmp_path)
    # First row in the table is whichever combo iterates first (LFC_RSC).
    assert _sleep_qc_cell(page) == "rerun done ✓"


def test_sleep_qc_cell_rerun_pending_with_edit_hint(qapp, tmp_path: Path):
    """needs_rerun + rerun_combo, no rerun EDF written yet → 'rerun → X  ✎'
    with the double-click-to-change tooltip."""
    from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry, RunEntry

    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        runs={"LFC_RSC": RunEntry(sleep_qc="needs_rerun", rerun_combo="LSC_RSC")},
    )
    m.save()
    page = _make_page(qapp, tmp_path)
    text = _sleep_qc_cell(page)
    assert "rerun → LSC_RSC" in text
    assert "✎" in text
    assert page.table.item(0, 6).toolTip().startswith("Double-click")


def test_b4_double_click_uses_cached_rendered_rows(qapp, tmp_path: Path):
    """After ``_refresh`` renders the table, ``self._table_rows`` reflects
    exactly what was drawn. If the manifest is modified afterward,
    ``_on_cell_double_clicked`` must still resolve row indices against the
    cached snapshot — otherwise a concurrent write can shift the index
    under the user's cursor."""
    _seed_manifest(tmp_path, psd_status={})
    page = _make_page(qapp, tmp_path)
    # _refresh already ran in __init__.
    assert hasattr(page, "_table_rows"), "_refresh must cache _table_rows"
    assert len(page._table_rows) == page.table.rowCount()

    # Simulate a concurrent manifest write that prepends a new animal.
    m2 = Manifest(tmp_path)
    m2._entries["AM000"] = ManifestEntry(  # alphabetically first
        animal_id="AM000",
        preprocessed_edf="AM000_PREPROCESSED.edf",
        runs={},
    )
    m2._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        runs={"LFC_RSC": RunEntry(sleep_qc="ok")},
    )
    m2.save()

    # The cached rows still describe what the table actually shows.
    cached_animal_ids = [r[0].animal_id for r in page._table_rows]
    assert "AM000" not in cached_animal_ids
