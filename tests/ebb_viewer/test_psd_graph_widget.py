"""Tests for PSDGridPage's notch-aware interpolation-range default and
manifest-backed notes editing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ebb_viewer.pipeline import psd_params
from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry, RunEntry
from ebb_viewer.widgets.psd_graph_widget import (
    _DEFAULT_INTERP_RANGE,
    _NOTCH_INTERP_RANGE,
    PSDGridPage,
)


class _FakeStore:
    """Minimal PSDStore-like double: no animals, so PSDGridPage skips render."""

    def animals(self):
        return []

    def states(self, animal):
        return []

    def get(self, animal, state):
        return {}


class _FakeStoreWithAnimal(_FakeStore):
    """Fake store with one animal, for exercising per-animal manifest UI."""

    def animals(self):
        return ["AM001"]


def _make_page(
    qapp,
    *,
    project_root=None,
    run_name: str = "default",
    store=None,
    manifest=None,
    run_channels: str | None = None,
) -> PSDGridPage:
    return PSDGridPage(
        store=store or _FakeStore(),
        channel_names=["LFC", "RSC"],
        states=["wake"],
        run_name=run_name,
        project_root=project_root,
        manifest=manifest,
        run_channels=run_channels,
    )


def _seed_manifest(tmp_path: Path, animal_id: str = "AM001") -> Manifest:
    m = Manifest(tmp_path)
    m._entries[animal_id] = ManifestEntry(
        animal_id=animal_id,
        preprocessed_edf=f"{animal_id}_PREPROCESSED.edf",
        runs={"LFC_RSC": RunEntry(sleep_qc="ok")},
    )
    m.save()
    return m


class _FakeNotesDialog:
    def __init__(self, *, animal_id, initial_text="", parent=None):
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


def test_interp_range_defaults_narrow_with_no_project_root(qapp):
    w = _make_page(qapp, project_root=None)
    assert w.interp_range == _DEFAULT_INTERP_RANGE


def test_interp_range_defaults_narrow_with_no_psd_params_file(qapp, tmp_path: Path):
    """A run predating the notch filter has no psd_params.json — treated as
    apply_notch=False."""
    w = _make_page(qapp, project_root=tmp_path, run_name="default")
    assert w.interp_range == _DEFAULT_INTERP_RANGE


def test_interp_range_widens_when_notch_was_applied(qapp, tmp_path: Path):
    psd_params.save(tmp_path, "notched", {"apply_notch": True})
    w = _make_page(qapp, project_root=tmp_path, run_name="notched")
    assert w.interp_range == _NOTCH_INTERP_RANGE


def test_interp_range_stays_narrow_when_notch_was_not_applied(qapp, tmp_path: Path):
    psd_params.save(tmp_path, "unnotched", {"apply_notch": False})
    w = _make_page(qapp, project_root=tmp_path, run_name="unnotched")
    assert w.interp_range == _DEFAULT_INTERP_RANGE


def test_interp_range_stays_narrow_when_apply_notch_key_missing(qapp, tmp_path: Path):
    """A run saved before apply_notch existed as a key — treated as False."""
    psd_params.save(tmp_path, "legacy", {"nstd": 5})
    w = _make_page(qapp, project_root=tmp_path, run_name="legacy")
    assert w.interp_range == _DEFAULT_INTERP_RANGE


# ---------------------------------------------------------------------------
# Notes button — mirrors the manifest-backed notes editor already used on
# the Home page and Sleep QC visualizer (shared ManifestEntry.notes field).
# ---------------------------------------------------------------------------


def test_notes_menu_action_hidden_without_manifest(qapp):
    w = _make_page(qapp, manifest=None)
    assert w._act_menu_notes.isVisible() is False


def test_notes_menu_action_visible_with_manifest(qapp, tmp_path: Path):
    manifest = _seed_manifest(tmp_path)
    w = _make_page(qapp, store=_FakeStoreWithAnimal(), manifest=manifest, run_channels="LFC_RSC")
    assert w._act_menu_notes.isVisible() is True


def test_open_notes_dialog_accept_persists_and_emits(qapp, tmp_path: Path):
    import ebb_viewer.widgets.psd_graph_widget as pgw_mod

    manifest = _seed_manifest(tmp_path)
    w = _make_page(qapp, store=_FakeStoreWithAnimal(), manifest=manifest, run_channels="LFC_RSC")
    emitted: list = []
    w.manifest_changed.connect(lambda: emitted.append(True))

    with patch.object(pgw_mod, "NotesDialog", _FakeNotesDialog):
        w._open_notes_dialog()

    assert manifest.get("AM001").notes == "new note"
    assert emitted == [True]


def test_open_notes_dialog_prefills_existing_text(qapp, tmp_path: Path):
    import ebb_viewer.widgets.psd_graph_widget as pgw_mod

    manifest = _seed_manifest(tmp_path)
    manifest.set_notes("AM001", "existing note")
    w = _make_page(qapp, store=_FakeStoreWithAnimal(), manifest=manifest, run_channels="LFC_RSC")

    captured: dict = {}

    class _CapturingFakeDialog(_FakeNotesDialog):
        def __init__(self, *, animal_id, initial_text, parent=None):
            super().__init__(animal_id=animal_id, initial_text=initial_text, parent=parent)
            captured["initial_text"] = initial_text

    with patch.object(pgw_mod, "NotesDialog", _CapturingFakeDialog):
        w._open_notes_dialog()

    assert captured["initial_text"] == "existing note"


def test_open_notes_dialog_cancel_does_not_change_manifest(qapp, tmp_path: Path):
    import ebb_viewer.widgets.psd_graph_widget as pgw_mod

    manifest = _seed_manifest(tmp_path)
    manifest.set_notes("AM001", "original note")
    w = _make_page(qapp, store=_FakeStoreWithAnimal(), manifest=manifest, run_channels="LFC_RSC")
    emitted: list = []
    w.manifest_changed.connect(lambda: emitted.append(True))

    with patch.object(pgw_mod, "NotesDialog", _FakeNotesDialogCancelled):
        w._open_notes_dialog()

    assert manifest.get("AM001").notes == "original note"
    assert emitted == []


def test_more_button_marked_when_note_present(qapp, tmp_path: Path):
    manifest = _seed_manifest(tmp_path)
    manifest.set_notes("AM001", "has a note")
    w = _make_page(qapp, store=_FakeStoreWithAnimal(), manifest=manifest, run_channels="LFC_RSC")
    assert w._btn_more.text() == "More 📝"
    assert w._btn_more.toolTip() == "has a note"


def test_more_button_plain_when_no_note(qapp, tmp_path: Path):
    manifest = _seed_manifest(tmp_path)
    w = _make_page(qapp, store=_FakeStoreWithAnimal(), manifest=manifest, run_channels="LFC_RSC")
    assert w._btn_more.text() == "More"
    assert w._btn_more.toolTip() == ""
