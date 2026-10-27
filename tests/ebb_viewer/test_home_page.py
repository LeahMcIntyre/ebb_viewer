"""Tests for ``pages/home.py`` — HomePage smoke + PSD-status precedence.

The pure-logic ``compute_pipeline_status`` is covered separately in
``test_compute_pipeline_status.py``. These tests focus on the UI-side
table-rendering logic, particularly the PSD Status column's "best-wins"
precedence across multi-run manifests.
"""

from __future__ import annotations

from pathlib import Path

from ebb_viewer.pages.home import _COL_NOTES, _COL_PSD_STATUS, _COL_SLEEP_QC, _COL_SWD
from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry


def _make_page(qapp, tmp_path: Path):
    from ebb_viewer.pages.home import HomePage

    return HomePage(project_root=tmp_path)


def _seed_manifest(
    tmp_path: Path,
    psd_status: dict[str, str],
    *,
    sleep_qc: str | None = "ok",
) -> None:
    """One animal with the given per-run psd_status dict."""
    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        has_spindle=True,
        sleep_qc=sleep_qc,
        psd_status=psd_status,
    )
    m.save()


def _psd_status_cell(page) -> str:
    """Read the PSD Status column text for the first row."""
    item = page.table.item(0, _COL_PSD_STATUS)
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
# PSD-status column "best-wins" precedence
#
# Precedence (analysis-readiness, highest wins):
#   drink_mask_applied > ok > needs_drink_mask
#
# Rationale: the column reflects the analysis-ready state for the animal.
# Pending-work signal is surfaced separately via the attention card
# (Manifest.all_needs_drink_mask) and per-run PSD Review.
# ---------------------------------------------------------------------------


def test_psd_status_drink_mask_applied_beats_needs_drink_mask(qapp, tmp_path: Path):
    """If any PSD run has drink_mask_applied, the column reads as such even
    when other runs still need the mask."""
    _seed_manifest(
        tmp_path,
        psd_status={
            "default": "drink_mask_applied",
            "dark_phase": "needs_drink_mask",
        },
    )
    page = _make_page(qapp, tmp_path)
    assert _psd_status_cell(page) == "mask applied — verify"


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
    assert _psd_status_cell(page) == "mask applied — verify"


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
    # Without an on-disk drink-mask npy, the cell reads "needs mask".
    assert _psd_status_cell(page) == "needs mask"


def test_psd_status_empty_dict_falls_through_to_dash(qapp, tmp_path: Path):
    """No PSD runs at all → column reads "—" (no psd_file_ok, no status)."""
    _seed_manifest(tmp_path, psd_status={})
    page = _make_page(qapp, tmp_path)
    assert _psd_status_cell(page) == "—"


# ---------------------------------------------------------------------------
# _open_windows must shrink when an opened window is destroyed.
# ---------------------------------------------------------------------------


def test_open_windows_prunes_on_destroy(qapp, tmp_path: Path):
    """Closing an EDF viewer window must drop it from ``_open_windows`` so
    its (potentially large) recording data can be garbage-collected."""
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QWidget

    page = _make_page(qapp, tmp_path)
    fake_win = QWidget()
    # Wire the same way _open_edf_for_animal does.
    fake_win.destroyed.connect(lambda _, w=fake_win: page._on_window_closed(w))
    page._open_windows.append(fake_win)
    assert len(page._open_windows) == 1

    fake_win.deleteLater()
    # Drain the DeferredDelete event queue so the destroyed signal actually
    # fires within the test rather than at GC time.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert len(page._open_windows) == 0


def test_on_window_closed_handles_unknown_window(qapp, tmp_path: Path):
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
# Sleep QC cell — pending / dash / needs_review branches.
# ---------------------------------------------------------------------------


def _sleep_qc_cell(page) -> str:
    """Read the Sleep QC column text for the first row."""
    item = page.table.item(0, _COL_SLEEP_QC)
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


def test_sleep_qc_cell_needs_review(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, psd_status={}, sleep_qc="needs_review")
    page = _make_page(qapp, tmp_path)
    assert _sleep_qc_cell(page) == "Review EDF"


# ---------------------------------------------------------------------------
# PSD-run filter dropdown — picking a specific run filters PSD File / PSD
# Status cells to that run rather than aggregating with best-wins.
# ---------------------------------------------------------------------------


def _seed_two_run_project(tmp_path: Path, *, psd_status_by_run: dict[str, str]) -> None:
    """Create a project with two named PSD runs registered on disk plus a
    matching manifest entry. ``psd_status_by_run`` is written into the
    single animal's ``psd_status``."""
    import json

    for run_name in ("default", "dark_phase"):
        run_dir = tmp_path / "psd" / run_name
        run_dir.mkdir(parents=True)
        (run_dir / "psd_params.json").write_text(json.dumps({}))

    _seed_manifest(tmp_path, psd_status=psd_status_by_run)


def test_run_filter_hidden_when_fewer_than_two_runs(qapp, tmp_path: Path):
    """0 or 1 PSD runs → dropdown stays hidden ("All runs (best)" and a single
    run render identically, so the control would have no effect)."""
    _seed_manifest(tmp_path, psd_status={"default": "ok"})
    page = _make_page(qapp, tmp_path)
    assert not page.cmb_run_filter.isVisible()
    assert not page._run_filter_lbl.isVisible()


def test_run_filter_visible_with_two_runs(qapp, tmp_path: Path):
    _seed_two_run_project(
        tmp_path,
        psd_status_by_run={"default": "ok", "dark_phase": "needs_drink_mask"},
    )
    page = _make_page(qapp, tmp_path)
    page.show()  # visibility flags require the parent to be shown
    try:
        # The dropdown should have "All runs (best)" + 2 run names.
        assert page.cmb_run_filter.count() == 3
        assert page.cmb_run_filter.itemText(0) == "All runs (best)"
        assert page.cmb_run_filter.currentData() is None  # default
    finally:
        page.hide()


def test_run_filter_default_uses_best_wins(qapp, tmp_path: Path):
    """With "All runs (best)" selected (default), ok beats needs_drink_mask
    — same as the existing aggregate behavior."""
    _seed_two_run_project(
        tmp_path,
        psd_status_by_run={"default": "ok", "dark_phase": "needs_drink_mask"},
    )
    page = _make_page(qapp, tmp_path)
    assert _psd_status_cell(page) == "ok"


def test_run_filter_specific_run_overrides_best_wins(qapp, tmp_path: Path):
    """Selecting "dark_phase" shows that run's status ("needs mask")
    even though "default" is ok — this is exactly the visibility the
    dropdown is meant to enable."""
    _seed_two_run_project(
        tmp_path,
        psd_status_by_run={"default": "ok", "dark_phase": "needs_drink_mask"},
    )
    page = _make_page(qapp, tmp_path)
    idx = page.cmb_run_filter.findData("dark_phase")
    page.cmb_run_filter.setCurrentIndex(idx)
    assert _psd_status_cell(page) == "needs mask"


def test_run_filter_specific_run_with_no_entry_shows_dash(qapp, tmp_path: Path):
    """If the chosen run has no psd_status for this animal and the on-disk
    pkl is missing, the cell shows "—" rather than the best-wins state from
    other runs."""
    _seed_two_run_project(
        tmp_path,
        psd_status_by_run={"default": "ok"},  # dark_phase has no entry
    )
    page = _make_page(qapp, tmp_path)
    idx = page.cmb_run_filter.findData("dark_phase")
    page.cmb_run_filter.setCurrentIndex(idx)
    # No psd_status entry for "dark_phase" and no pkl on disk → "—".
    assert _psd_status_cell(page) == "—"


def test_run_filter_selection_preserved_across_refresh(qapp, tmp_path: Path):
    """Refresh repopulates the dropdown but keeps the user's selection
    when the chosen run still exists."""
    _seed_two_run_project(
        tmp_path,
        psd_status_by_run={"default": "ok", "dark_phase": "needs_drink_mask"},
    )
    page = _make_page(qapp, tmp_path)
    idx = page.cmb_run_filter.findData("dark_phase")
    page.cmb_run_filter.setCurrentIndex(idx)
    page._refresh()
    assert page.cmb_run_filter.currentData() == "dark_phase"


def test_run_filter_falls_back_when_selection_disappears(qapp, tmp_path: Path):
    """If the selected run is removed from disk between refreshes, the
    dropdown falls back to "All runs (best)"."""
    import shutil

    _seed_two_run_project(
        tmp_path,
        psd_status_by_run={"default": "ok", "dark_phase": "needs_drink_mask"},
    )
    page = _make_page(qapp, tmp_path)
    idx = page.cmb_run_filter.findData("dark_phase")
    page.cmb_run_filter.setCurrentIndex(idx)

    shutil.rmtree(tmp_path / "psd" / "dark_phase")
    page._refresh()
    assert page.cmb_run_filter.currentData() is None


# ---------------------------------------------------------------------------
# Needs Attention cards
# ---------------------------------------------------------------------------


def _attention_button_texts(page) -> list[str]:
    from PyQt6.QtWidgets import QPushButton

    return [b.text() for b in page._attn_container.findChildren(QPushButton)]


def test_review_card_offers_open_ok_and_exclude_only(qapp, tmp_path: Path):
    """A needs_review animal gets a card with Open EDF / OK / Exclude — no rerun controls."""
    from PyQt6.QtWidgets import QComboBox

    _seed_manifest(tmp_path, psd_status={}, sleep_qc="needs_review")
    page = _make_page(qapp, tmp_path)
    assert _attention_button_texts(page) == ["Open EDF", "✓ OK", "Exclude"]
    assert page._attn_container.findChildren(QComboBox) == []


def test_review_card_ok_button_flags_animal_ok(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, psd_status={}, sleep_qc="needs_review")
    page = _make_page(qapp, tmp_path)
    emitted: list = []
    page.manifest_changed.connect(lambda: emitted.append(True))

    page._queue_flag_ok("AM001")

    assert Manifest.load(tmp_path).get("AM001").sleep_qc == "ok"
    assert emitted == [True]


def test_drink_mask_card_links_to_drink_mask_page(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, psd_status={"default": "needs_drink_mask"})
    (tmp_path / "psd" / "default").mkdir(parents=True)
    (tmp_path / "psd" / "default" / "psd_params.json").write_text("{}")
    (tmp_path / "psd" / "default" / "psds_LFC_RSC.pkl").touch()
    page = _make_page(qapp, tmp_path)
    assert "→ Drink Mask page" in _attention_button_texts(page)


# ---------------------------------------------------------------------------
# _on_cell_double_clicked must use the cached row list (matching what the
# user sees), not re-derive from a fresh manifest load.
# ---------------------------------------------------------------------------


def test_double_click_uses_cached_rendered_rows(qapp, tmp_path: Path):
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
    )
    m2._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        has_spindle=True,
        sleep_qc="ok",
    )
    m2.save()

    # The cached rows still describe what the table actually shows.
    cached_animal_ids = [e.animal_id for e in page._table_rows]
    assert "AM000" not in cached_animal_ids


# ---------------------------------------------------------------------------
# Notes column
# ---------------------------------------------------------------------------


def _seed_notes_animal(tmp_path: Path, notes: str = "") -> None:
    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001", preprocessed_edf="AM001_PREPROCESSED.edf", notes=notes
    )
    m.save()


def test_notes_cell_dash_when_empty(qapp, tmp_path: Path):
    _seed_notes_animal(tmp_path)

    page = _make_page(qapp, tmp_path)
    item = page.table.item(0, _COL_NOTES)
    assert item.text() == "—"
    assert item.toolTip() == ""


def test_notes_cell_shows_icon_and_tooltip_when_present(qapp, tmp_path: Path):
    _seed_notes_animal(tmp_path, notes="noisy EMG channel")

    page = _make_page(qapp, tmp_path)
    item = page.table.item(0, _COL_NOTES)
    assert item.text() == "📝"
    assert item.toolTip() == "noisy EMG channel"


def test_double_click_notes_column_persists_and_emits(qapp, tmp_path: Path, monkeypatch):
    """Double-clicking the Notes cell opens the editor and persists the text."""
    import ebb_viewer.pages.home as home_mod

    _seed_notes_animal(tmp_path)

    page = _make_page(qapp, tmp_path)
    row_idx = next(i for i, e in enumerate(page._table_rows) if e.animal_id == "AM001")

    class FakeNotesDialog:
        def __init__(self, *, animal_id, initial_text, parent=None):
            self.animal_id = animal_id
            self.initial_text = initial_text

        def exec(self):
            return True

        def text(self):
            return "new note"

    monkeypatch.setattr(home_mod, "NotesDialog", FakeNotesDialog)

    emitted: list = []
    page.manifest_changed.connect(lambda: emitted.append(True))

    page._on_cell_double_clicked(row_idx, _COL_NOTES)

    assert Manifest.load(tmp_path).get("AM001").notes == "new note"
    assert emitted == [True]


def test_double_click_notes_column_cancel_does_not_change_manifest(
    qapp, tmp_path: Path, monkeypatch
):
    import ebb_viewer.pages.home as home_mod

    _seed_notes_animal(tmp_path, notes="original note")

    page = _make_page(qapp, tmp_path)
    row_idx = next(i for i, e in enumerate(page._table_rows) if e.animal_id == "AM001")

    class FakeNotesDialog:
        def __init__(self, *, animal_id, initial_text, parent=None):
            pass

        def exec(self):
            return False  # Cancel

        def text(self):
            raise AssertionError("text() should not be called when cancelled")

    monkeypatch.setattr(home_mod, "NotesDialog", FakeNotesDialog)

    emitted: list = []
    page.manifest_changed.connect(lambda: emitted.append(True))

    page._on_cell_double_clicked(row_idx, _COL_NOTES)

    assert Manifest.load(tmp_path).get("AM001").notes == "original note"
    assert emitted == []


def test_excluded_animal_psd_status_is_a_dash_not_pending(qapp, tmp_path: Path):
    """Excluded animals are never PSD-reviewed, so the cell must not read "pending"."""
    _seed_manifest(tmp_path, psd_status={}, sleep_qc="excluded")
    page = _make_page(qapp, tmp_path)
    assert _psd_status_cell(page) == "—"


# ---------------------------------------------------------------------------
# Layout: next-step banner, attention-only filter
# ---------------------------------------------------------------------------


def test_attention_only_filter_hides_finished_animals(qapp, tmp_path: Path):
    """Only animals with outstanding work stay in the table when the filter is on."""
    m = Manifest(tmp_path)
    for animal_id, qc in (("AM001", "ok"), ("AM002", "needs_review"), ("AM003", "excluded")):
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id, preprocessed_edf="", has_spindle=True, sleep_qc=qc
        )
    m.save()
    page = _make_page(qapp, tmp_path)
    assert page.table.rowCount() == 3
    page.chk_attention_only.setChecked(True)
    assert [e.animal_id for e in page._table_rows] == ["AM002"]
    assert page.table.rowCount() == 1


def test_attention_zone_hidden_when_nothing_needs_attention(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, psd_status={}, sleep_qc="ok")
    page = _make_page(qapp, tmp_path)
    assert page._attn_content_px == 0
    assert page._attn_scroll.isHidden()


def test_next_banner_points_at_first_unfinished_step(qapp, tmp_path: Path):
    """With an animal under review the banner offers the Sleep QC page."""
    (tmp_path / "standard").mkdir()
    (tmp_path / "standard" / "AM001_PREPROCESSED.edf").touch()
    _seed_manifest(tmp_path, psd_status={}, sleep_qc="needs_review")
    page = _make_page(qapp, tmp_path)
    assert page._next_page is not None
    assert page._next_page != "preprocess"


def test_swd_column_hidden_without_swd_files(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, psd_status={})
    page = _make_page(qapp, tmp_path)
    assert page.table.isColumnHidden(_COL_SWD)


def test_swd_column_shows_found_and_missing(qapp, tmp_path: Path):
    """With some .mat files present, an animal without one is flagged missing."""
    m = Manifest(tmp_path)
    for animal_id in ("AM001", "AM002"):
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id, preprocessed_edf="", has_spindle=True, sleep_qc="ok"
        )
    m.save()
    (tmp_path / "swd").mkdir()
    (tmp_path / "swd" / "AM001.mat").touch()
    page = _make_page(qapp, tmp_path)
    assert not page.table.isColumnHidden(_COL_SWD)
    assert page.table.item(0, _COL_SWD).text() == "✓"
    assert page.table.item(1, _COL_SWD).text() == "missing"


def test_review_card_shows_why_it_was_flagged(qapp, tmp_path: Path):
    from PyQt6.QtWidgets import QLabel

    _seed_manifest(tmp_path, psd_status={}, sleep_qc="needs_review")
    m = Manifest.load(tmp_path)
    m.flag_sleep_qc("AM001", "needs_review", ["nrem_short_h", "pct_wake"])
    page = _make_page(qapp, tmp_path)
    texts = [lbl.text() for lbl in page._attn_container.findChildren(QLabel)]
    assert "Flagged: short NREM bouts, high wake" in texts


# ---------------------------------------------------------------------------
# Combo label and the empty-table hint
# ---------------------------------------------------------------------------


def test_combo_text_says_default_until_spindle_edfs_are_written(tmp_path: Path):
    from ebb_viewer.pages.home import combo_text

    assert "default" in combo_text(tmp_path, "LFC_RSC")
    d = tmp_path / "spindle_edfs" / "LFC_RSC"
    d.mkdir(parents=True)
    (d / "AM001_SPINDLE.edf").write_text("")
    assert combo_text(tmp_path, "LFC_RSC") == "Channel combo: LFC_RSC"


def test_empty_animals_hint_counts_raw_edfs(tmp_path: Path):
    from ebb_viewer.pages.home import empty_animals_hint

    assert "no EDF files" in empty_animals_hint(tmp_path, 0)
    (tmp_path / "AM001_a.edf").write_text("")
    (tmp_path / "AM002_a.edf").write_text("")
    assert "Found 2 EDF files" in empty_animals_hint(tmp_path, 0)
    assert empty_animals_hint(tmp_path, 3) is None


def test_home_page_shows_hint_and_combo_for_a_fresh_project(qapp, tmp_path: Path):
    (tmp_path / "AM001_a.edf").write_text("")
    page = _make_page(qapp, tmp_path)
    page._refresh()
    assert not page._empty_lbl.isHidden()
    assert "1. Preprocess" in page._empty_lbl.text()
    assert "Channel combo: LFC_RSC" in page._combo_lbl.text()


def test_home_page_hides_hint_once_animals_exist(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, {})
    page = _make_page(qapp, tmp_path)
    page._refresh()
    assert page._empty_lbl.isHidden()


# ---------------------------------------------------------------------------
# Which step excluded an animal
# ---------------------------------------------------------------------------


def test_excluded_cell_names_the_step_that_excluded_the_animal(qapp, tmp_path: Path):
    page = _make_page(qapp, tmp_path)
    notes_qc = "Excluded (Sleep QC): noisy EMG"
    notes_psd = "Excluded (Sleep QC): noisy\nExcluded (PSD review): extra bad"
    assert page._build_sleep_qc_cell("excluded", True, notes_qc).text() == "Excluded (Sleep QC)"
    assert page._build_sleep_qc_cell("excluded", True, notes_psd).text() == "Excluded (PSD review)"
    # No reason recorded (manifest edited by hand): just "Excluded".
    assert page._build_sleep_qc_cell("excluded", True, "").text() == "Excluded"


# ---------------------------------------------------------------------------
# Needs Attention card: EMG gate
# ---------------------------------------------------------------------------


def _card_texts(page, entry) -> list[str]:
    from PyQt6.QtWidgets import QLabel

    card = page._make_review_card(entry)  # keep a reference: the card has no parent
    return [w.text() for w in card.findChildren(QLabel)]


def test_review_card_shows_emg_gate_in_brackets_when_it_was_applied(qapp, tmp_path: Path):
    page = _make_page(qapp, tmp_path)

    def entry(animal, gate):
        return ManifestEntry(
            animal_id=animal,
            preprocessed_edf="x.edf",
            has_spindle=True,
            sleep_qc="needs_review",
            flag_reasons=["nrem_short_h"],
            reclass_gate_applied=gate,
        )

    assert "[EMG gate]" in _card_texts(page, entry("AM001", True))
    assert "[EMG gate]" not in _card_texts(page, entry("AM002", False))
    assert "[EMG gate]" not in _card_texts(page, entry("AM003", None))
    assert any(t.startswith("Flagged:") for t in _card_texts(page, entry("AM001", True)))


def test_swd_chip_stays_visible_and_marked_optional_when_review_is_off(qapp, tmp_path: Path):
    from ebb_viewer.pages.home import _SWD_STEP_IDX

    page = _make_page(qapp, tmp_path)
    chip = page._chips[_SWD_STEP_IDX]
    assert not chip.isHidden()
    assert "(optional)" in chip.text()


def test_double_click_animal_column_opens_that_animals_viewer(qapp, tmp_path: Path, monkeypatch):
    _seed_notes_animal(tmp_path)
    page = _make_page(qapp, tmp_path)
    row_idx = next(i for i, e in enumerate(page._table_rows) if e.animal_id == "AM001")
    opened = []
    monkeypatch.setattr(page, "_open_edf_for_animal", opened.append)

    page._on_cell_double_clicked(row_idx, home_mod_col("Animal"))

    assert [e.animal_id for e in opened] == ["AM001"]


def home_mod_col(name: str) -> int:
    from ebb_viewer.pages.home import _COLUMNS

    return _COLUMNS.index(name)


def test_review_card_exclude_records_reason_and_emits(qapp, tmp_path: Path, monkeypatch):
    import ebb_viewer.pages.home as home_mod

    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        has_spindle=True,
        sleep_qc="needs_review",
    )
    m.save()
    page = _make_page(qapp, tmp_path)
    emitted = []
    page.manifest_changed.connect(lambda: emitted.append(1))

    def fake_exclude(parent, manifest, animal_id, stage):
        manifest.exclude_sleep_qc(animal_id, "bad EMG", stage)
        return True

    monkeypatch.setattr(home_mod, "exclude_with_reason", fake_exclude)
    page._queue_exclude("AM001")

    entry = Manifest.load(tmp_path).get("AM001")
    assert entry.sleep_qc == "excluded" and "bad EMG" in entry.notes
    assert emitted


def test_review_card_exclude_cancelled_changes_nothing(qapp, tmp_path: Path, monkeypatch):
    import ebb_viewer.pages.home as home_mod

    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001",
        preprocessed_edf="AM001_PREPROCESSED.edf",
        has_spindle=True,
        sleep_qc="needs_review",
    )
    m.save()
    page = _make_page(qapp, tmp_path)
    monkeypatch.setattr(home_mod, "exclude_with_reason", lambda *a: False)
    page._queue_exclude("AM001")
    assert Manifest.load(tmp_path).get("AM001").sleep_qc == "needs_review"
