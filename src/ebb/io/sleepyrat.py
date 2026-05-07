"""HTTP client for the SleepyRat sleep-staging service.

Wraps the project / folder / submission endpoints used by the ebb pipeline:
upload preprocessed EDFs, wait for remote processing, and download the
predicted state labels as CSVs.
"""

import time
from pathlib import Path
from typing import Any

import requests

# TODO(security): credentials are hardcoded as defaults. Repo is currently
# private, but this is fragile — a public fork, sale, or accidental
# visibility flip leaks them. The password cannot be rotated at the moment;
# move to env vars / a credentials file once it can.


class SleepyRatAPI:
    """Thin wrapper around the SleepyRat REST API.

    Calls `raise_for_status` on every response, so HTTP errors surface as
    `requests.HTTPError` rather than being silently returned as error JSON.
    """

    def __init__(
        self,
        username: str = "REDACTED_1",
        password: str = "REDACTED_2",
        base_url: str = "https://sleepyrat.ai/api",
    ) -> None:
        self.base_url = base_url
        self.token = self._login(username, password)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _login(self, username: str, password: str) -> str:
        response = requests.post(
            f"{self.base_url}/login", json={"username": username, "password": password}
        )
        response.raise_for_status()
        return response.json()["access_token"]

    # -- Projects --

    def get_projects(self) -> list[dict[str, Any]]:
        """Return the raw project objects available to this account."""
        response = requests.get(f"{self.base_url}/projects", headers=self.headers)
        response.raise_for_status()
        return response.json()

    def project_names(self) -> list[str]:
        """Return just the project names from `get_projects()`."""
        return [p["name"] for p in self.get_projects()]

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/projects",
            headers=self.headers,
            json={"name": name, "description": description},
        )
        response.raise_for_status()
        return response.json()

    # -- Folders --

    def get_folders(self, project: str) -> list[str]:
        """Return the folder names within `project`.

        Note: the SleepyRat endpoint already returns a flat list of folder
        name strings, not folder objects, so this and `folder_names` are
        equivalent. `folder_names` is the canonical accessor.
        """
        response = requests.get(
            f"{self.base_url}/projects/{project}/folders", headers=self.headers
        )
        response.raise_for_status()
        return response.json()

    def folder_names(self, project: str) -> list[str]:
        """Return a list of folder names for `project` (canonical accessor)."""
        return self.get_folders(project)

    def create_folder(self, project: str, folder_name: str) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/projects/{project}/folders",
            headers=self.headers,
            json={"folder_name": folder_name},
        )
        response.raise_for_status()
        return response.json()

    # -- Submissions (uploads) --

    def upload_edf(self, project: str, folder: str, file_path: str | Path) -> dict[str, Any]:
        with open(file_path, "rb") as f:
            response = requests.post(
                f"{self.base_url}/projects/{project}/folders/{folder}/submissions",
                headers=self.headers,
                files={"file": f},
            )
        response.raise_for_status()
        return response.json()

    def upload_dir(self, project: str, folder: str, dir_path: str | Path) -> None:
        """Upload every `*.edf` in `dir_path` to `project/folder`."""
        for p in Path(dir_path).glob("*.edf"):
            self.upload_edf(project, folder, p)

    def get_submissions(self, project: str, folder: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/projects/{project}/folders/{folder}/submissions",
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()

    def get_submission_names(self, project: str, folder: str) -> list[str]:
        """Return submission file names within `project/folder`."""
        return [s["name"] for s in self.get_submissions(project, folder)["submissions"]]

    # -- Labels (results) --

    def download_labels(
        self, project: str, folder: str, submission: str, threshold: float = 0.5
    ) -> str:
        """Return the labels CSV text for one submission."""
        response = requests.get(
            f"{self.base_url}/projects/{project}/folders/{folder}"
            f"/files/{submission}/labels/{threshold}",
            headers=self.headers,
        )
        response.raise_for_status()
        return response.text

    def download_labels_all(
        self,
        project: str,
        folder: str,
        outdir: str | Path,
        threshold: float = 0.5,
    ) -> None:
        """Download labels for every submission in `project/folder` into `outdir`.

        Skips submissions whose `<stem>_labels.csv` already exists in `outdir`.
        """
        outdir = Path(outdir)
        outdir.mkdir(exist_ok=True)
        for name in self.get_submission_names(project, folder):
            new_path = outdir / (Path(name).stem + "_labels.csv")
            if new_path.exists():
                continue
            labels = self.download_labels(project, folder, name, threshold=threshold)
            new_path.write_text(labels)

    def wait_for_processing(self, project: str, folder: str, max_wait: int = 10000) -> bool:
        """Poll until every submission in `folder` has finished processing.

        Args:
            max_wait: maximum number of seconds to wait before giving up.

        Returns:
            True if all submissions completed, False if `max_wait` elapsed.
        """
        # NOTE: prints status to stdout. Could move to logging — see TODO.md.
        start_time = time.time()
        while time.time() - start_time < max_wait:
            submissions = self.get_submissions(project, folder)
            pending = [s for s in submissions["submissions"] if s.get("msg") != ""]
            if not pending:
                return True
            print(f"Waiting for {len(pending)} files to complete processing...")
            time.sleep(30)
        return False
