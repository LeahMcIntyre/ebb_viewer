"""Tests for the exclude-with-reason flow (dialog, legend button, viewer action)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QWidget

from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry
from ebb_viewer.widgets import exclude_dialog as ed
from ebb_viewer.widgets.exclude_dialog import ExcludeDialog, exclude_with_reason


def _manifest(tmp_path: Path, status: str | None = None, notes: str = "") -> Manifest:
    m = Manifest(tmp_path)
    m._entries["AM001"] = ManifestEntry(
        animal_id="AM001", preprocessed_edf="a.edf", has_spindle=True, sleep_qc=status, notes=notes
    )
    m.save()
    return m


def _accepting(reason: str):
    def fake(self):
        self.edit.setPlainText(reason)
        return 1

    return patch.object(ExcludeDialog, "exec", fake)


def test_exclude_button_needs_a_reason(qapp):
    dlg = ExcludeDialog(animal_id="AM001")
    assert not dlg.btn_exclude.isEnabled()
    dlg.edit.setPlainText("   \n ")
    assert not dlg.btn_exclude.isEnabled()
    dlg.edit.setPlainText(" lost signal ")
    assert dlg.btn_exclude.isEnabled()
    assert dlg.reason() == "lost signal"


def test_accepted_dialog_excludes_and_records_reason(qapp, tmp_path):
    m = _manifest(tmp_path, "needs_review", notes="earlier note")
    with _accepting("seizures all day"):
        assert exclude_with_reason(None, m, "AM001") is True
    assert m.get("AM001").sleep_qc == "excluded"
    assert m.get("AM001").notes == "earlier note\nExcluded: seizures all day"


def test_cancelled_dialog_changes_nothing(qapp, tmp_path):
    m = _manifest(tmp_path, "needs_review")
    with patch.object(ExcludeDialog, "exec", lambda self: 0):
        assert exclude_with_reason(None, m, "AM001") is False
    assert m.get("AM001").sleep_qc == "needs_review"
    assert m.get("AM001").notes == ""


# --- Sleep QC legend -------------------------------------------------------


def _page(qapp, tmp_path):
    from ebb_viewer.pages.sleep_qc_visualizer import SleepQCGridPage

    return SleepQCGridPage(project_root=tmp_path)


def test_page_exclude_sets_status_emits_and_keeps_note(qapp, tmp_path):
    _manifest(tmp_path)
    page = _page(qapp, tmp_path)
    emitted = []
    page.manifest_changed.connect(lambda: emitted.append(True))
    with _accepting("bad file"):
        page._exclude_sleep_qc("AM001", True)
    assert page._manifest.get("AM001").sleep_qc == "excluded"
    assert Manifest.load(tmp_path).get("AM001").notes == "Excluded: bad file"
    assert emitted == [True]


def test_page_cancelled_exclude_leaves_status_and_refreshes_legend(qapp, tmp_path):
    _manifest(tmp_path, "needs_review")
    page = _page(qapp, tmp_path)
    page._refresh_legend = MagicMock()
    with patch.object(ExcludeDialog, "exec", lambda self: 0):
        page._exclude_sleep_qc("AM001", True)
    assert page._manifest.get("AM001").sleep_qc == "needs_review"
    page._refresh_legend.assert_called_once()  # un-pops the toggle


def test_page_unexclude_returns_to_needs_review_and_keeps_note(qapp, tmp_path):
    _manifest(tmp_path)
    page = _page(qapp, tmp_path)
    with _accepting("bad file"):
        page._exclude_sleep_qc("AM001", True)
    page._exclude_sleep_qc("AM001", False)
    assert page._manifest.get("AM001").sleep_qc == "needs_review"
    assert page._manifest.get("AM001").notes == "Excluded: bad file"


def test_legend_row_has_exclude_button_checked_and_greyed_when_excluded(qapp, tmp_path):
    from PyQt6.QtWidgets import QPushButton

    _manifest(tmp_path, "excluded")
    page = _page(qapp, tmp_path)
    page._update_legend_group(["AM001"], {"AM001": (31, 119, 180)})
    buttons = {b.text(): b for b in page.legend_container.findChildren(QPushButton)}
    assert buttons["Exclude"].isChecked()
    assert not buttons["OK"].isChecked() and not buttons["Review"].isChecked()
    row = page.legend_container.findChild(type(page.legend_container), "legendRow")
    assert "#cfcfcf" in row.styleSheet() and "#8a8a8a" in row.styleSheet()


# --- EDF viewer ------------------------------------------------------------


def _viewer_stub(manifest: Manifest):
    """A bare widget carrying the attributes ``_flag_qc_exclude`` uses (it is the dialog's parent)."""
    stub = QWidget()
    stub.manifest, stub.animal_id, stub._update_qc_status = manifest, "AM001", MagicMock()
    return stub


def test_viewer_exclude_action_excludes_with_reason(qapp, tmp_path):
    from ebb_viewer.edf_viewer.eeg_viewer import EegMainWindow

    m = _manifest(tmp_path, "needs_review")
    stub = _viewer_stub(m)
    with _accepting("electrode fell out"):
        EegMainWindow._flag_qc_exclude(stub, True)
    assert m.get("AM001").sleep_qc == "excluded"
    assert "electrode fell out" in m.get("AM001").notes
    stub._update_qc_status.assert_called_once()


def test_viewer_unchecking_exclude_returns_to_needs_review(qapp, tmp_path):
    from ebb_viewer.edf_viewer.eeg_viewer import EegMainWindow

    m = _manifest(tmp_path, "excluded")
    EegMainWindow._flag_qc_exclude(_viewer_stub(m), False)
    assert m.get("AM001").sleep_qc == "needs_review"


def test_viewer_cancelled_exclude_keeps_status(qapp, tmp_path):
    from ebb_viewer.edf_viewer.eeg_viewer import EegMainWindow

    m = _manifest(tmp_path, "needs_review")
    with patch.object(ExcludeDialog, "exec", lambda self: 0):
        EegMainWindow._flag_qc_exclude(_viewer_stub(m), True)
    assert m.get("AM001").sleep_qc == "needs_review"


def test_module_exports_helper():
    assert ed.exclude_with_reason is exclude_with_reason
