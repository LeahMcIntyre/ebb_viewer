"""Device-pairing auth for the SleepyRat v1 agent API.

Replaces password login: an agent starts a pairing session, the human
approves it in their browser, and the agent polls for the resulting
scoped, revocable token. The token is cached locally so pairing only
happens once (until it expires or is revoked).
"""

import json
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

DEFAULT_BASE_URL = "https://sleepyrat.ai/api/v1"
DEFAULT_CLIENT_NAME = "ebb"
DEFAULT_SCOPES = (
    "projects:read",
    "projects:write",
    "submissions:write",
    "jobs:read",
    "results:read",
)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "ebb" / "sleepyrat.json"


def _parse_expiry(expires_at: str) -> datetime:
    return datetime.fromisoformat(expires_at.replace("Z", "+00:00"))


def load_token(config_path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any] | None:
    """Return the cached token dict, or None if there isn't one or it has expired."""
    if not config_path.exists():
        return None
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if _parse_expiry(data["expires_at"]) <= datetime.now(timezone.utc):
        return None
    return data


def save_token(token_data: dict[str, Any], config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Atomically persist a token dict (access_token, expires_at, scopes, ...)."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)
    tmp.replace(config_path)


def request_pairing(
    base_url: str = DEFAULT_BASE_URL,
    client_name: str = DEFAULT_CLIENT_NAME,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> dict[str, Any]:
    """Start a pairing session. Returns device_code/user_code/verification_uri/interval/expires_in."""
    response = requests.post(
        f"{base_url}/agent-sessions",
        json={"client_name": client_name, "scopes": list(scopes)},
    )
    response.raise_for_status()
    return response.json()


def poll_for_token(
    base_url: str,
    device_code: str,
    interval: int,
    expires_in: int,
) -> dict[str, Any]:
    """Poll until the human approves pairing in their browser, or the request expires.

    Returns the token payload. Raises TimeoutError if `expires_in` seconds
    elapse without approval.
    """
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        response = requests.post(
            f"{base_url}/agent-sessions/token", json={"device_code": device_code}
        )
        response.raise_for_status()
        body = response.json()
        if body.get("status") == "approved":
            return body
        interval = body.get("interval", interval)
    raise TimeoutError("SleepyRat pairing was not approved before the request expired.")


def pair(
    base_url: str = DEFAULT_BASE_URL,
    client_name: str = DEFAULT_CLIENT_NAME,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
    config_path: Path = DEFAULT_CONFIG_PATH,
    open_browser: bool = True,
) -> str:
    """Run the full device-pairing flow and persist the resulting token.

    Opens the verification URL in the user's browser (unless `open_browser=False`,
    used by tests) so they can approve the request, then polls until approved.
    Returns the new access token.
    """
    session = request_pairing(base_url, client_name, scopes)
    if open_browser:
        webbrowser.open(session["verification_uri_complete"])
    token = poll_for_token(
        base_url, session["device_code"], session["interval"], session["expires_in"]
    )
    save_token(token, config_path)
    return token["access_token"]


def get_token(
    base_url: str = DEFAULT_BASE_URL,
    client_name: str = DEFAULT_CLIENT_NAME,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> str:
    """Return a valid access token, pairing interactively if none is cached or it expired."""
    cached = load_token(config_path)
    if cached is not None:
        return cached["access_token"]
    return pair(base_url, client_name, scopes, config_path)
