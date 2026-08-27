from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ebb.io import sleepyrat_auth as auth


def _resp(json_data: dict) -> MagicMock:
    m = MagicMock()
    m.json.return_value = json_data
    m.raise_for_status.return_value = None
    return m


# ---------------------------------------------------------------- load/save


def test_load_token_missing_file_returns_none(tmp_path: Path):
    assert auth.load_token(tmp_path / "sleepyrat.json") is None


def test_save_then_load_round_trips(tmp_path: Path):
    config_path = tmp_path / "nested" / "sleepyrat.json"
    token = {"access_token": "sr_at_abc", "expires_at": "2999-01-01T00:00:00Z"}
    auth.save_token(token, config_path)
    assert auth.load_token(config_path) == token


def test_load_token_expired_returns_none(tmp_path: Path):
    config_path = tmp_path / "sleepyrat.json"
    auth.save_token(
        {"access_token": "sr_at_abc", "expires_at": "2000-01-01T00:00:00Z"}, config_path
    )
    assert auth.load_token(config_path) is None


def test_save_token_leaves_no_tmp_file_behind(tmp_path: Path):
    config_path = tmp_path / "sleepyrat.json"
    auth.save_token({"access_token": "x", "expires_at": "2999-01-01T00:00:00Z"}, config_path)
    assert not config_path.with_suffix(".json.tmp").exists()


# ------------------------------------------------------------ request_pairing


@patch("ebb.io.sleepyrat_auth.requests.post")
def test_request_pairing_posts_client_name_and_scopes(mock_post: MagicMock):
    mock_post.return_value = _resp(
        {
            "device_code": "dc123",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://sleepyrat.ai/pair",
            "verification_uri_complete": "https://sleepyrat.ai/pair?code=ABCD-EFGH",
            "expires_in": 600,
            "interval": 5,
        }
    )
    result = auth.request_pairing(
        base_url="https://sleepyrat.ai/api/v1", client_name="ebb", scopes=("projects:read",)
    )
    mock_post.assert_called_once_with(
        "https://sleepyrat.ai/api/v1/agent-sessions",
        json={"client_name": "ebb", "scopes": ["projects:read"]},
    )
    assert result["device_code"] == "dc123"


# -------------------------------------------------------------- poll_for_token


@patch("ebb.io.sleepyrat_auth.time.sleep", return_value=None)
@patch("ebb.io.sleepyrat_auth.requests.post")
def test_poll_for_token_returns_once_approved(mock_post: MagicMock, mock_sleep: MagicMock):
    pending = _resp({"status": "authorization_pending", "interval": 1})
    approved = _resp(
        {"status": "approved", "access_token": "sr_at_xyz", "expires_at": "2999-01-01T00:00:00Z"}
    )
    mock_post.side_effect = [pending, pending, approved]
    result = auth.poll_for_token("https://sleepyrat.ai/api/v1", "dc123", interval=1, expires_in=60)
    assert result["access_token"] == "sr_at_xyz"
    assert mock_post.call_count == 3


@patch("ebb.io.sleepyrat_auth.time.sleep", return_value=None)
@patch("ebb.io.sleepyrat_auth.time.monotonic")
@patch("ebb.io.sleepyrat_auth.requests.post")
def test_poll_for_token_raises_timeout_if_never_approved(
    mock_post: MagicMock, mock_monotonic: MagicMock, mock_sleep: MagicMock
):
    mock_post.return_value = _resp({"status": "authorization_pending", "interval": 1})
    # start=0 -> deadline=60; one loop iteration (10 < 60); then 70 >= 60 exits the loop.
    mock_monotonic.side_effect = [0, 10, 70]
    with pytest.raises(TimeoutError):
        auth.poll_for_token("https://sleepyrat.ai/api/v1", "dc123", interval=1, expires_in=60)
    assert mock_post.call_count == 1


# ------------------------------------------------------------------------ pair


@patch("ebb.io.sleepyrat_auth.webbrowser.open")
@patch("ebb.io.sleepyrat_auth.poll_for_token")
@patch("ebb.io.sleepyrat_auth.request_pairing")
def test_pair_opens_browser_and_persists_token(
    mock_request_pairing: MagicMock, mock_poll: MagicMock, mock_open: MagicMock, tmp_path: Path
):
    mock_request_pairing.return_value = {
        "device_code": "dc123",
        "verification_uri_complete": "https://sleepyrat.ai/pair?code=ABCD-EFGH",
        "interval": 5,
        "expires_in": 600,
    }
    mock_poll.return_value = {"access_token": "sr_at_xyz", "expires_at": "2999-01-01T00:00:00Z"}
    config_path = tmp_path / "sleepyrat.json"

    token = auth.pair(config_path=config_path)

    assert token == "sr_at_xyz"
    mock_open.assert_called_once_with("https://sleepyrat.ai/pair?code=ABCD-EFGH")
    assert auth.load_token(config_path)["access_token"] == "sr_at_xyz"


@patch("ebb.io.sleepyrat_auth.webbrowser.open")
@patch("ebb.io.sleepyrat_auth.poll_for_token")
@patch("ebb.io.sleepyrat_auth.request_pairing")
def test_pair_skips_browser_when_disabled(
    mock_request_pairing: MagicMock, mock_poll: MagicMock, mock_open: MagicMock, tmp_path: Path
):
    mock_request_pairing.return_value = {
        "device_code": "dc123",
        "verification_uri_complete": "https://sleepyrat.ai/pair?code=ABCD-EFGH",
        "interval": 5,
        "expires_in": 600,
    }
    mock_poll.return_value = {"access_token": "sr_at_xyz", "expires_at": "2999-01-01T00:00:00Z"}

    auth.pair(config_path=tmp_path / "sleepyrat.json", open_browser=False)

    mock_open.assert_not_called()


# -------------------------------------------------------------------- get_token


def test_get_token_returns_cached_without_pairing(tmp_path: Path):
    config_path = tmp_path / "sleepyrat.json"
    auth.save_token({"access_token": "cached", "expires_at": "2999-01-01T00:00:00Z"}, config_path)

    with patch("ebb.io.sleepyrat_auth.pair") as mock_pair:
        result = auth.get_token(config_path=config_path)

    assert result == "cached"
    mock_pair.assert_not_called()


def test_get_token_pairs_when_no_cache(tmp_path: Path):
    config_path = tmp_path / "sleepyrat.json"

    with patch("ebb.io.sleepyrat_auth.pair", return_value="fresh_token") as mock_pair:
        result = auth.get_token(config_path=config_path)

    assert result == "fresh_token"
    mock_pair.assert_called_once()
