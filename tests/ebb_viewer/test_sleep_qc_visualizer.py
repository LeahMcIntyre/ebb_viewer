"""Param-flow + UX-state tests for ``pages/sleep_qc_visualizer.py``.

These cover the single-combo data cache, the consolidated flagging path,
the animal dropdown ordering, and the overview wiring (thresholds, flagging).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page(qapp, tmp_path: Path):
    from ebb_viewer.pages.sleep_qc_visualizer import SleepQCGridPage

    return SleepQCGridPage(project_root=tmp_path)


def _seed_manifest(tmp_path: Path, sleep_qc: dict[str, str | None]) -> Manifest:
    """Build + persist a manifest. ``sleep_qc`` maps animal_id → status."""
    m = Manifest(tmp_path)
    for animal_id, status in sleep_qc.items():
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id,
            preprocessed_edf=f"{animal_id}_PREPROCESSED.edf",
            has_spindle=True,
            sleep_qc=status,
        )
    m.save()
    return m


def _seed_one_animal(tmp_path: Path, status: str | None = None) -> None:
    _seed_manifest(tmp_path, {"AM001": status})


# ---------------------------------------------------------------------------
# Data loading — cached until the CSV folder changes
# ---------------------------------------------------------------------------


def test_ensure_data_reloads_only_when_csvs_change(qapp, tmp_path: Path):
    import ebb_viewer.pages.sleep_qc_visualizer as sqv_mod

    out = tmp_path / "spindle_outputs" / "LFC_RSC"
    out.mkdir(parents=True)
    (out / "AM001_a.csv").write_text("state\nw\n")
    df = pd.DataFrame({"mouse_id": ["AM002", "AM001"], "state": ["w", "w"]})
    compute = MagicMock(return_value=df)

    with patch.multiple(
        sqv_mod,
        compute_sleep_bins_df=compute,
        compute_sleep_bins_df_offset=MagicMock(return_value=df),
        compute_sleep_bins_df_clock_aligned=MagicMock(return_value=df),
        metrics_table=MagicMock(return_value=df),
    ):
        page = _make_page(qapp, tmp_path)
        assert page._ensure_data() is True
        assert page._mouse_ids == ["AM001", "AM002"]

        assert page._ensure_data() is False  # nothing changed on disk
        assert compute.call_count == 1

        (out / "AM002_a.csv").write_text("state\nw\n")
        assert page._ensure_data() is True
        assert compute.call_count == 2


def test_ensure_data_without_output_folder_leaves_no_data(qapp, tmp_path: Path):
    page = _make_page(qapp, tmp_path)
    page._ensure_data()
    assert page._data is None
    assert page._mouse_ids == []


# ---------------------------------------------------------------------------
# Animal dropdown — unreviewed animals first
# ---------------------------------------------------------------------------


def test_animal_dropdown_lists_unreviewed_first(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, {"AM001": "ok", "AM002": None, "AM003": "needs_review", "AM004": None})
    page = _make_page(qapp, tmp_path)
    page._mouse_ids = ["AM001", "AM002", "AM003", "AM004"]

    page._refresh_animal_combo()

    items = [page.cmb_animal.itemText(i) for i in range(page.cmb_animal.count())]
    assert items == ["AM002", "AM004", "AM001", "AM003"]


# ---------------------------------------------------------------------------
# Flagging — one path for group mode, animal mode and the overview
# ---------------------------------------------------------------------------


def test_flag_sleep_qc_ok_sets_ok_and_emits(qapp, tmp_path: Path):
    _seed_one_animal(tmp_path)
    page = _make_page(qapp, tmp_path)
    emitted: list = []
    page.manifest_changed.connect(lambda: emitted.append(True))

    page._flag_sleep_qc("AM001", "ok")

    assert page._manifest.get("AM001").sleep_qc == "ok"
    assert Manifest.load(tmp_path).get("AM001").sleep_qc == "ok"
    assert emitted == [True]


def test_flag_sleep_qc_none_resets(qapp, tmp_path: Path):
    _seed_one_animal(tmp_path, status="ok")
    page = _make_page(qapp, tmp_path)

    page._flag_sleep_qc("AM001", None)

    assert page._manifest.get("AM001").sleep_qc is None


def test_flag_sleep_qc_needs_review(qapp, tmp_path: Path):
    _seed_one_animal(tmp_path)
    page = _make_page(qapp, tmp_path)

    page._flag_sleep_qc("AM001", "needs_review")

    assert page._manifest.get("AM001").sleep_qc == "needs_review"


def test_flag_sleep_qc_unknown_animal_is_noop(qapp, tmp_path: Path):
    _seed_one_animal(tmp_path)
    page = _make_page(qapp, tmp_path)
    emitted: list = []
    page.manifest_changed.connect(lambda: emitted.append(True))

    page._flag_sleep_qc("NOPE", "ok")

    assert emitted == []


def test_overview_flag_requested_flags_needs_review(qapp, tmp_path: Path):
    _seed_one_animal(tmp_path)
    page = _make_page(qapp, tmp_path)

    page._on_overview_flag_requested("AM001")

    assert page._manifest.get("AM001").sleep_qc == "needs_review"


# ---------------------------------------------------------------------------
# Nav hint
# ---------------------------------------------------------------------------


def test_nav_hint_points_home_when_any_animal_needs_review(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, {"AM001": "ok", "AM002": "needs_review"})
    page = _make_page(qapp, tmp_path)
    page._update_nav_hint()
    assert page._nav_hint_dest == "home"
    assert not page._hint_frame.isHidden()


def test_nav_hint_points_to_psd_when_all_ok(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, {"AM001": "ok", "AM002": "ok"})
    page = _make_page(qapp, tmp_path)
    page._update_nav_hint()
    assert page._nav_hint_dest == "psd_compute"
    assert not page._hint_frame.isHidden()


def test_nav_hint_hidden_while_animals_pending(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, {"AM001": "ok", "AM002": None})
    page = _make_page(qapp, tmp_path)
    page._update_nav_hint()
    assert page._hint_frame.isHidden()


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

    _seed_one_animal(tmp_path)
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

    _seed_one_animal(tmp_path)
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
# Reclassified-by-default view + "Show original" toggle (reads final_state)
# ---------------------------------------------------------------------------


# Fixture CSVs: original state is ["w", "n"], final_state is ["n", "w"] (see
# _setup_reclass_page), so the compute call that received final_state is identifiable.
_FINAL = ["n", "w"]


def _is_reclass(states_by_animal) -> bool:
    return states_by_animal is not None and any(
        list(v) == _FINAL for v in states_by_animal.values()
    )


def _patch_compute(sqv_mod, raw_df, reclass_df):
    """Make the compute functions return ``reclass_df`` when given states that include
    final_state and ``raw_df`` for the original states."""

    def pick(*_a, states_by_animal=None, **_k):
        return reclass_df if _is_reclass(states_by_animal) else raw_df

    return patch.multiple(
        sqv_mod,
        compute_sleep_bins_df=MagicMock(side_effect=pick),
        compute_sleep_bins_df_offset=MagicMock(side_effect=pick),
        compute_sleep_bins_df_clock_aligned=MagicMock(side_effect=pick),
        metrics_table=MagicMock(side_effect=pick),
    )


def _setup_reclass_page(qapp, tmp_path: Path, gates: dict[str, bool] | None = None):
    """CSVs with a ``final_state`` column + manifest gate flags, one per animal in ``gates``."""
    import ebb_viewer.pages.sleep_qc_visualizer as sqv_mod

    gates = {"AM001": False} if gates is None else gates
    out = tmp_path / "spindle_outputs" / "LFC_RSC"
    out.mkdir(parents=True)
    for animal in gates:
        (out / f"{animal}_a.csv").write_text("state,final_state\nw,n\nn,w\n")
    m = _seed_manifest(tmp_path, dict.fromkeys(gates))
    for animal, gate in gates.items():
        m._entries[animal].reclass_gate_applied = gate
    m.save()
    raw = pd.DataFrame({"mouse_id": ["AM001"], "state": ["w"], "tag": ["raw"]})
    rec = pd.DataFrame({"mouse_id": ["AM001"], "state": ["w"], "tag": ["reclass"]})
    return sqv_mod, raw, rec


def _reclass_calls(sqv_mod) -> list:
    """``states_by_animal`` of each reclassified (non-raw) compute call."""
    return [
        c.kwargs["states_by_animal"]
        for c in sqv_mod.metrics_table.call_args_list
        if _is_reclass(c.kwargs.get("states_by_animal"))
    ]


def test_reclassified_is_default_and_show_original_swaps_both_views(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(qapp, tmp_path, {"AM001": True})
    with _patch_compute(sqv_mod, raw, rec):
        page = _make_page(qapp, tmp_path)
        page._ensure_data()
        assert page._reclass_active  # reclassified without touching anything
        assert not page.btn_original.isChecked() and page.btn_original.isEnabled()
        assert page._get_df()["tag"].iloc[0] == "reclass"  # Sleep view
        assert page._get_flag_table()["tag"].iloc[0] == "reclass"  # Overview
        assert not page.lbl_reclass.isHidden()
        assert "1 of 1" in page.lbl_reclass.text()
        assert "AM001" in page.lbl_reclass.toolTip()

        page.btn_original.setChecked(True)  # fires _on_original_toggled
        assert not page._reclass_active
        assert page._get_df()["tag"].iloc[0] == "raw"
        assert page._get_flag_table()["tag"].iloc[0] == "raw"
        assert "original" in page.lbl_reclass.text().lower()

        page.btn_original.setChecked(False)
        assert page._get_df()["tag"].iloc[0] == "reclass"


def test_final_state_read_once_and_writes_nothing(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(qapp, tmp_path)
    csv_path = tmp_path / "spindle_outputs" / "LFC_RSC" / "AM001_a.csv"
    before = csv_path.read_text()
    with _patch_compute(sqv_mod, raw, rec):
        page = _make_page(qapp, tmp_path)
        page._ensure_data()
        page.btn_original.setChecked(True)
        page.btn_original.setChecked(False)
        page.btn_original.setChecked(True)
        assert _reclass_calls(sqv_mod) == [{"AM001": _FINAL}]
    assert csv_path.read_text() == before


def test_animals_without_final_state_stay_original_and_are_reported(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(qapp, tmp_path)
    (tmp_path / "spindle_outputs" / "LFC_RSC" / "AM002_a.csv").write_text("state\nw\n")
    with _patch_compute(sqv_mod, raw, rec):
        page = _make_page(qapp, tmp_path)
        page._ensure_data()
        page._mouse_ids = ["AM001", "AM002"]
        page._update_reclass_label()
        states = _reclass_calls(sqv_mod)[0]
        assert states["AM001"] == _FINAL and states["AM002"] == ["w"]  # AM002: original states
        assert "1 not reclassified" in page.lbl_reclass.text()


def test_no_final_state_column_falls_back_with_loud_label(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(qapp, tmp_path, {})
    out = tmp_path / "spindle_outputs" / "LFC_RSC"
    (out / "AM001_a.csv").write_text("state\nw\n")  # no final_state column
    with _patch_compute(sqv_mod, raw, rec):
        page = _make_page(qapp, tmp_path)
        page._ensure_data()
        assert not page._reclass_active
        assert not page.btn_original.isEnabled()  # nothing to compare against
        assert page._get_df()["tag"].iloc[0] == "raw"
        assert not page.lbl_reclass.isHidden()
        assert "Not reclassified" in page.lbl_reclass.text()


def test_reclassified_data_dropped_and_rebuilt_when_csvs_change(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(qapp, tmp_path)
    out = tmp_path / "spindle_outputs" / "LFC_RSC"
    with _patch_compute(sqv_mod, raw, rec):
        page = _make_page(qapp, tmp_path)
        page._ensure_data()
        assert len(_reclass_calls(sqv_mod)) == 1

        (out / "AM002_a.csv").write_text("state,final_state\nw,w\n")  # new CSV lands
        assert page._ensure_data() is True
        assert page._reclass_active
        calls = _reclass_calls(sqv_mod)
        assert len(calls) == 2 and set(calls[1]) == {"AM001", "AM002"}  # rebuilt


# ---------------------------------------------------------------------------
# EMG-gate indicators
# ---------------------------------------------------------------------------


def _legend_texts(page) -> str:
    from PyQt6.QtWidgets import QLabel

    return " ".join(lbl.text() for lbl in page.findChildren(QLabel))


def test_gated_animals_empty_while_showing_original(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(qapp, tmp_path, {"AM001": True, "AM002": False})
    with _patch_compute(sqv_mod, raw, rec):
        page = _make_page(qapp, tmp_path)
        page._ensure_data()
        assert page._gated_animals() == {"AM001"}
        assert "EMG gate" in page._gate_tag_html("AM001")
        assert page._gate_tag_html("AM002") == ""

        page.btn_original.setChecked(True)
        assert page._gated_animals() == set()
        assert page._gate_tag_html("AM001") == ""


def test_legend_rows_tag_gated_animals_in_group_and_animal_views(qapp, tmp_path: Path):
    sqv_mod, raw, rec = _setup_reclass_page(qapp, tmp_path, {"AM001": True})
    with _patch_compute(sqv_mod, raw, rec):
        page = _make_page(qapp, tmp_path)
        page._ensure_data()
        page._flagged_animals = lambda: {}  # the mocked flag table has no metric columns

        page._update_legend_group(["AM001"], {"AM001": "#123456"})
        assert "[EMG gate]" in _legend_texts(page)

        page.cmb_animal.addItem("AM001")
        page.cmb_animal.setCurrentText("AM001")
        page._update_legend_animal()
        assert "[EMG gate]" in _legend_texts(page)

        page.btn_original.setChecked(True)
        page._update_legend_group(["AM001"], {"AM001": "#123456"})
        page._update_legend_animal()
        from PyQt6.QtCore import QCoreApplication, QEvent

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # drop old rows
        assert "[EMG gate]" not in _legend_texts(page)


def test_unreclassified_project_loads_original_states_without_error(qapp, tmp_path: Path):
    """No CSV has final_state: the page must not raise NotReclassifiedError, and the
    compute functions get the original states explicitly."""
    import ebb_viewer.pages.sleep_qc_visualizer as sqv_mod

    out = tmp_path / "spindle_outputs" / "LFC_RSC"
    out.mkdir(parents=True)
    (out / "AM001_a.csv").write_text("state,noise_prob\nw,0.0\nn,0.0\n")
    _seed_one_animal(tmp_path)
    df = pd.DataFrame({"mouse_id": ["AM001"], "state": ["w"], "tag": ["raw"]})
    with (
        _patch_compute(sqv_mod, df, df),
        patch.object(sqv_mod.QMessageBox, "critical") as critical,
    ):
        page = _make_page(qapp, tmp_path)
        page._ensure_data()
        assert not critical.called
        sent = sqv_mod.metrics_table.call_args.kwargs["states_by_animal"]
        assert sent == {"AM001": ["w", "n"]}
        assert not page._reclass_active


# ---------------------------------------------------------------------------
# Overview — flagging metrics and thresholds
# ---------------------------------------------------------------------------


def _flag_table() -> pd.DataFrame:
    base = {"nrem_short": 100, "dark_bouts_h": 5, "pct_rem": 8, "pct_nrem": 50,
            "pct_wake": 42, "max_bin_rem": 10}
    return pd.DataFrame({"AM001": base, "AM002": {**base, "nrem_short": 500}}).T.rename_axis("animal")


def test_flagged_animals_uses_manifest_thresholds(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, {"AM001": None, "AM002": None})
    page = _make_page(qapp, tmp_path)
    page._data = (pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), _flag_table())

    assert page._flagged_animals() == {"AM002": ["nrem_short"]}
    assert "Short" in page._flag_tag_html("AM002")
    assert page._flag_tag_html("AM001") == ""

    page._manifest.flag_thresholds["nrem_short"] = 600
    assert page._flagged_animals() == {}


def test_overview_shows_flag_table_with_statuses(qapp, tmp_path: Path):
    _seed_manifest(tmp_path, {"AM001": "ok", "AM002": "needs_review"})
    page = _make_page(qapp, tmp_path)
    page._data = (pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), _flag_table())

    page._refresh_overview()

    assert page._overview.flagged_animals() == {"AM002": ["nrem_short"]}
    page._on_overview_animal_selected("AM002")
    assert page._overview.selected == "AM002"
