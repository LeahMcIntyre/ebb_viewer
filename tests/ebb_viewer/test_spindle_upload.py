"""Tests for the ``SleepyRatWorker`` upload/download orchestration.

``SleepyRatWorker`` is a plain ``QObject`` — ``run()`` is called directly and
synchronously here (no QThread/event loop needed), with ``SleepyRatAPI``
mocked out.
"""

from unittest.mock import MagicMock, patch

from ebb_viewer.pages.spindle_upload import SleepyRatWorker, sanitize_sleepyrat_name


def test_sanitize_sleepyrat_name_replaces_spaces():
    assert sanitize_sleepyrat_name("My Project") == "My_Project"
    assert sanitize_sleepyrat_name("no_spaces") == "no_spaces"
    assert sanitize_sleepyrat_name("multi   space") == "multi___space"


def _make_api(*, existing_folders=(), existing_submissions=()):
    api = MagicMock()
    api.folder_names.return_value = list(existing_folders)
    api.get_submission_names.return_value = []
    api.get_submissions.return_value = {
        "submissions": [{"name": n, "id": i} for i, n in enumerate(existing_submissions)]
    }
    return api


@patch("ebb_viewer.pages.spindle_upload.SleepyRatAPI")
def test_run_creates_remote_folder_when_missing(mock_api_cls, tmp_path):
    api = _make_api(existing_folders=[], existing_submissions=["a.edf"])
    mock_api_cls.return_value = api
    upload_dir = tmp_path / "spindle_edfs"
    upload_dir.mkdir()
    (upload_dir / "a.edf").touch()

    worker = SleepyRatWorker("proj", "new_folder", tmp_path / "out", upload_dir=upload_dir)
    worker.run()

    api.create_folder.assert_called_once_with("proj", "new_folder")


@patch("ebb_viewer.pages.spindle_upload.SleepyRatAPI")
def test_run_skips_folder_creation_when_already_present(mock_api_cls, tmp_path):
    api = _make_api(existing_folders=["existing_folder"], existing_submissions=["a.edf"])
    mock_api_cls.return_value = api
    upload_dir = tmp_path / "spindle_edfs"
    upload_dir.mkdir()
    (upload_dir / "a.edf").touch()

    worker = SleepyRatWorker("proj", "existing_folder", tmp_path / "out", upload_dir=upload_dir)
    worker.run()

    api.create_folder.assert_not_called()
