from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ebb.io.sleepyrat import SleepyRatAPI


def _resp(json_data=None, text=None, status_ok=True):
    m = MagicMock()
    if json_data is not None:
        m.json.return_value = json_data
    if text is not None:
        m.text = text
    m.raise_for_status.return_value = None
    return m


@pytest.fixture
def api():
    with patch("ebb.io.sleepyrat.sleepyrat_auth.get_token", return_value="sr_at_test"):
        return SleepyRatAPI()


# --------------------------------------------------------------------- auth


def test_init_uses_paired_token_by_default():
    with patch(
        "ebb.io.sleepyrat.sleepyrat_auth.get_token", return_value="sr_at_paired"
    ) as mock_get_token:
        client = SleepyRatAPI()
    mock_get_token.assert_called_once()
    assert client.headers["Authorization"] == "Bearer sr_at_paired"


def test_init_accepts_explicit_token_without_pairing():
    with patch("ebb.io.sleepyrat.sleepyrat_auth.get_token") as mock_get_token:
        client = SleepyRatAPI(token="sr_at_explicit")
    mock_get_token.assert_not_called()
    assert client.headers["Authorization"] == "Bearer sr_at_explicit"


# ----------------------------------------------------------------- projects


@patch("ebb.io.sleepyrat.requests.get")
def test_get_projects_populates_id_cache(mock_get, api):
    mock_get.return_value = _resp({"projects": [{"id": 4, "name": "Temporary"}]})
    names = api.project_names()
    assert names == ["Temporary"]
    assert api._project_ids == {"Temporary": 4}


@patch("ebb.io.sleepyrat.requests.post")
def test_create_project_sends_product_code_and_idempotency_key(mock_post, api):
    mock_post.return_value = _resp({"project": {"id": 9, "name": "New"}})
    project = api.create_project("New", description="desc")
    assert project == {"id": 9, "name": "New"}
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"name": "New", "description": "desc", "product_code": "sleepyrat"}
    assert "Idempotency-Key" in kwargs["headers"]
    assert api._project_ids["New"] == 9


@patch("ebb.io.sleepyrat.requests.get")
def test_project_id_resolves_lazily_and_caches(mock_get, api):
    mock_get.return_value = _resp({"projects": [{"id": 4, "name": "Temporary"}]})
    assert api._project_id("Temporary") == 4
    assert api._project_id("Temporary") == 4
    assert mock_get.call_count == 1  # second lookup hit the cache


@patch("ebb.io.sleepyrat.requests.get")
def test_project_id_raises_for_unknown_project(mock_get, api):
    mock_get.return_value = _resp({"projects": [{"id": 4, "name": "Temporary"}]})
    with pytest.raises(ValueError, match="not found"):
        api._project_id("Nonexistent")


# ------------------------------------------------------------------ folders


@patch("ebb.io.sleepyrat.requests.get")
def test_get_folders_populates_id_cache(mock_get, api):
    api._project_ids["Temporary"] = 4
    mock_get.return_value = _resp({"folders": [{"id": 104, "name": "combo_LFC_RSC"}]})
    names = api.folder_names("Temporary")
    assert names == ["combo_LFC_RSC"]
    assert api._folder_ids[(4, "combo_LFC_RSC")] == 104


@patch("ebb.io.sleepyrat.requests.post")
def test_create_folder_sends_idempotency_key(mock_post, api):
    api._project_ids["Temporary"] = 4
    mock_post.return_value = _resp({"folder": {"id": 104, "name": "combo_LFC_RSC"}})
    folder = api.create_folder("Temporary", "combo_LFC_RSC")
    assert folder["id"] == 104
    _, kwargs = mock_post.call_args
    assert "Idempotency-Key" in kwargs["headers"]
    assert api._folder_ids[(4, "combo_LFC_RSC")] == 104


@patch("ebb.io.sleepyrat.requests.get")
def test_folder_id_raises_for_unknown_folder(mock_get, api):
    api._project_ids["Temporary"] = 4
    mock_get.return_value = _resp({"folders": []})
    with pytest.raises(ValueError, match="not found"):
        api._folder_id("Temporary", "missing")


# --------------------------------------------------------------- submissions


@patch("ebb.io.sleepyrat.requests.post")
def test_upload_edf_posts_multipart_with_idempotency_key(mock_post, api, tmp_path):
    api._project_ids["Temporary"] = 4
    api._folder_ids[(4, "combo_LFC_RSC")] = 104
    edf_path = tmp_path / "Animal1.edf"
    edf_path.write_bytes(b"fake edf bytes")
    mock_post.return_value = _resp({"submission_id": "sub-1", "status": "queued"})

    result = api.upload_edf("Temporary", "combo_LFC_RSC", edf_path)

    assert result["status"] == "queued"
    args, kwargs = mock_post.call_args
    assert args[0] == (
        "https://sleepyrat.ai/api/v1/products/sleepyrat/projects/4/folders/104/submissions"
    )
    assert "Idempotency-Key" in kwargs["headers"]
    assert "file" in kwargs["files"]


@patch("ebb.io.sleepyrat.requests.get")
def test_get_submission_names(mock_get, api):
    api._project_ids["Temporary"] = 4
    api._folder_ids[(4, "combo_LFC_RSC")] = 104
    mock_get.return_value = _resp(
        {"submissions": [{"id": "sub-1", "name": "Animal1"}, {"id": "sub-2", "name": "Animal2"}]}
    )
    assert api.get_submission_names("Temporary", "combo_LFC_RSC") == ["Animal1", "Animal2"]


# -------------------------------------------------------------------- labels


@patch("ebb.io.sleepyrat.requests.get")
def test_download_labels_uses_predictions_kind_no_threshold(mock_get, api):
    api._project_ids["Temporary"] = 4
    api._folder_ids[(4, "combo_LFC_RSC")] = 104
    submissions_resp = _resp({"submissions": [{"id": "sub-1", "name": "Animal1"}]})
    predictions_resp = _resp(text="index,state\n0,w\n")
    mock_get.side_effect = [submissions_resp, predictions_resp]

    csv_text = api.download_labels("Temporary", "combo_LFC_RSC", "Animal1")

    assert csv_text == "index,state\n0,w\n"
    predictions_url = mock_get.call_args_list[1].args[0]
    assert predictions_url.endswith(
        "/products/sleepyrat/projects/4/folders/104/submissions/sub-1/predictions"
    )


@patch("ebb.io.sleepyrat.requests.get")
def test_download_labels_raises_for_unknown_submission(mock_get, api):
    api._project_ids["Temporary"] = 4
    api._folder_ids[(4, "combo_LFC_RSC")] = 104
    mock_get.return_value = _resp({"submissions": []})
    with pytest.raises(ValueError, match="not found"):
        api.download_labels("Temporary", "combo_LFC_RSC", "Missing")


@patch("ebb.io.sleepyrat.requests.get")
def test_download_labels_all_skips_existing_files(mock_get, api, tmp_path: Path):
    api._project_ids["Temporary"] = 4
    api._folder_ids[(4, "combo_LFC_RSC")] = 104
    (tmp_path / "Animal1_labels.csv").write_text("already here")
    submissions_resp = _resp(
        {"submissions": [{"id": "sub-1", "name": "Animal1"}, {"id": "sub-2", "name": "Animal2"}]}
    )
    predictions_resp = _resp(text="index,state\n0,n\n")
    mock_get.side_effect = [submissions_resp, predictions_resp]

    api.download_labels_all("Temporary", "combo_LFC_RSC", tmp_path)

    assert (tmp_path / "Animal1_labels.csv").read_text() == "already here"
    assert (tmp_path / "Animal2_labels.csv").read_text() == "index,state\n0,n\n"


# ------------------------------------------------------------ wait_for_processing


@patch("ebb.io.sleepyrat.time.sleep", return_value=None)
@patch("ebb.io.sleepyrat.requests.get")
def test_wait_for_processing_returns_true_once_all_terminal(mock_get, mock_sleep, api):
    api._project_ids["Temporary"] = 4
    api._folder_ids[(4, "combo_LFC_RSC")] = 104
    pending = _resp({"submissions": [{"id": "s1", "name": "Animal1", "status": "processing"}]})
    done = _resp({"submissions": [{"id": "s1", "name": "Animal1", "status": "succeeded"}]})
    mock_get.side_effect = [pending, done]

    assert api.wait_for_processing("Temporary", "combo_LFC_RSC") is True


@patch("ebb.io.sleepyrat.time.sleep", return_value=None)
@patch("ebb.io.sleepyrat.time.time")
@patch("ebb.io.sleepyrat.requests.get")
def test_wait_for_processing_returns_false_on_timeout(mock_get, mock_time, mock_sleep, api):
    api._project_ids["Temporary"] = 4
    api._folder_ids[(4, "combo_LFC_RSC")] = 104
    mock_get.return_value = _resp(
        {"submissions": [{"id": "s1", "name": "Animal1", "status": "processing"}]}
    )
    mock_time.side_effect = [0, 10, 70]  # start=0, deadline=60; 10<60 loop once; 70>=60 exit

    assert api.wait_for_processing("Temporary", "combo_LFC_RSC", max_wait=60) is False


@patch("ebb.io.sleepyrat.time.sleep", return_value=None)
@patch("ebb.io.sleepyrat.requests.get")
def test_wait_for_processing_true_even_when_a_submission_failed(mock_get, mock_sleep, api):
    api._project_ids["Temporary"] = 4
    api._folder_ids[(4, "combo_LFC_RSC")] = 104
    mock_get.return_value = _resp(
        {"submissions": [{"id": "s1", "name": "Animal1", "status": "failed"}]}
    )
    assert api.wait_for_processing("Temporary", "combo_LFC_RSC") is True
