"""SwdReviewPage: opt-in checkbox, per-animal table, opening the review window."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from scipy.io import savemat

from ebb_viewer.pages.swd_review import SwdReviewPage, find_swd_file
from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry


def _project(tmp_path: Path, *, reclassified=True, swd=True) -> Path:
    out = tmp_path / "spindle_outputs" / "LFC_RSC"
    out.mkdir(parents=True)
    header = "state,reclass_state\n" if reclassified else "state\n"
    body = "w,w\nn,n\nn,n\nw,w\n" if reclassified else "w\nn\nn\nw\n"
    (out / "A1_x.csv").write_text(header + body)
    if swd:
        (tmp_path / "swd").mkdir()
        savemat(tmp_path / "swd" / "A1_swd.mat", {"DEL_ts": [[1.0, 2.0], [5.0, 6.0]]})
    m = Manifest(tmp_path)
    m._entries["A1"] = ManifestEntry("A1", "standard/A1_PREPROCESSED.edf", has_spindle=True)
    m.save()
    return tmp_path


def test_find_swd_file_accepts_the_names_used_in_real_projects(tmp_path):
    swd = tmp_path / "swd"
    swd.mkdir()
    for name in (
        "Mice-1256.mat",  # bare animal ID
        "JK1011_P063_DEL_ts.mat",  # animal_..._DEL_ts
        "A10_swd.mat",
    ):
        (swd / name).touch()

    assert find_swd_file(tmp_path, "Mice-1256").name == "Mice-1256.mat"
    assert find_swd_file(tmp_path, "JK1011").name == "JK1011_P063_DEL_ts.mat"
    assert find_swd_file(tmp_path, "A10").name == "A10_swd.mat"


def test_find_swd_file_does_not_confuse_prefix_animals_or_missing_dir(tmp_path):
    assert find_swd_file(tmp_path, "A1") is None  # no swd/ folder
    (tmp_path / "swd").mkdir()
    (tmp_path / "swd" / "A10_swd.mat").touch()
    assert find_swd_file(tmp_path, "A1") is None  # A10 is a different animal
    assert find_swd_file(tmp_path, "A2") is None


def test_off_by_default_hides_table_and_checkbox_enables(qapp, tmp_path):
    page = SwdReviewPage(project_root=_project(tmp_path))
    emitted: list = []
    page.manifest_changed.connect(lambda: emitted.append(True))
    assert not page.chk_enable.isChecked()
    assert page.table.isHidden() and "off" in page.lbl_status.text()

    page.chk_enable.setChecked(True)

    assert Manifest.load(tmp_path).swd_review_enabled is True
    assert emitted == [True]
    assert not page.table.isHidden() and page.table.rowCount() == 1


def test_table_shows_swd_epoch_count_and_enables_review(qapp, tmp_path):
    root = _project(tmp_path)
    Manifest.load(root).set_swd_review_enabled(True)
    page = SwdReviewPage(project_root=root)
    cells = [page.table.item(0, c).text() for c in range(4)]
    assert cells[0] == "A1" and cells[1] == "A1_swd.mat"
    assert cells[2] == "2"  # intervals at 1-2 s and 5-6 s -> epochs 0 and 1
    assert cells[3] == "—"
    assert page.table.cellWidget(0, 4).isEnabled()


def test_review_disabled_without_swd_file_or_reclassification(qapp, tmp_path):
    root = _project(tmp_path / "a", swd=False)
    Manifest.load(root).set_swd_review_enabled(True)
    assert not SwdReviewPage(project_root=root).table.cellWidget(0, 4).isEnabled()

    root = _project(tmp_path / "b", reclassified=False)
    Manifest.load(root).set_swd_review_enabled(True)
    page = SwdReviewPage(project_root=root)
    assert page.table.item(0, 2).text() == "run Reclassify"
    assert not page.table.cellWidget(0, 4).isEnabled()


def test_open_review_launches_window_and_saving_marks_manifest(qapp, tmp_path):
    root = _project(tmp_path)
    Manifest.load(root).set_swd_review_enabled(True)
    page = SwdReviewPage(project_root=root)
    emitted: list = []
    page.manifest_changed.connect(lambda: emitted.append(True))
    fake_win = MagicMock()

    with patch("ebb_viewer.pages.swd_review.launch_swd_review", return_value=fake_win) as launch:
        page._open_review("A1")

    args, kwargs = launch.call_args
    assert args[0] == root / "standard/A1_PREPROCESSED.edf"
    assert args[1].name == "A1_x.csv" and args[2].name == "A1_swd.mat"
    fake_win.show.assert_called_once()

    kwargs["on_saved"]("A1")  # what the window calls after Save
    assert Manifest.load(root).get("A1").swd_reviewed is True
    assert emitted and page.table.item(0, 3).text() == "✓"


def test_open_review_error_is_reported_not_raised(qapp, tmp_path):
    root = _project(tmp_path)
    Manifest.load(root).set_swd_review_enabled(True)
    page = SwdReviewPage(project_root=root)
    with (
        patch("ebb_viewer.pages.swd_review.launch_swd_review", side_effect=ValueError("bad edf")),
        patch("ebb_viewer.pages.swd_review.QMessageBox.critical") as critical,
    ):
        page._open_review("A1")
    assert critical.called and "bad edf" in critical.call_args.args[2]
