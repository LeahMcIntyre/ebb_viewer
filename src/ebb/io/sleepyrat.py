"""HTTP client for the SleepyRat v1 sleep-staging service.

Wraps the project / folder / submission endpoints used by the ebb pipeline:
upload preprocessed EDFs, wait for remote processing, and download the
predicted state labels as CSVs. Auth is a paired, scoped agent token (see
`ebb.io.sleepyrat_auth`) rather than a password login.
"""

import time
import uuid
from pathlib import Path
from typing import Any

import requests

from ebb.io import sleepyrat_auth

PRODUCT_CODE = "sleepyrat"
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class SleepyRatAPI:
    """Thin wrapper around the SleepyRat v1 REST API.

    Calls `raise_for_status` on every response, so HTTP errors surface as
    `requests.HTTPError` rather than being silently returned as error JSON.

    Projects and folders are addressed by name everywhere in this class,
    matching the rest of ebb, even though the underlying API is id-based —
    ids are resolved on first use and cached per instance.
    """

    def __init__(
        self,
        base_url: str = sleepyrat_auth.DEFAULT_BASE_URL,
        token: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.token = token or sleepyrat_auth.get_token(base_url=base_url)
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self._project_ids: dict[str, int] = {}
        self._folder_ids: dict[tuple[int, str], int] = {}

    @staticmethod
    def _idempotent(headers: dict[str, str]) -> dict[str, str]:
        return {**headers, "Idempotency-Key": str(uuid.uuid4())}

    # -- Projects --

    def get_projects(self) -> list[dict[str, Any]]:
        """Return the raw project objects available to this account."""
        response = requests.get(f"{self.base_url}/projects", headers=self.headers)
        response.raise_for_status()
        projects = response.json()["projects"]
        self._project_ids = {p["name"]: p["id"] for p in projects}
        return projects

    def project_names(self) -> list[str]:
        """Return just the project names from `get_projects()`."""
        return [p["name"] for p in self.get_projects()]

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/projects",
            headers=self._idempotent(self.headers),
            json={"name": name, "description": description, "product_code": PRODUCT_CODE},
        )
        response.raise_for_status()
        project = response.json()["project"]
        self._project_ids[project["name"]] = project["id"]
        return project

    def _project_id(self, project: str) -> int:
        """Resolve a project name to its id, refreshing the cache once if missing."""
        if project not in self._project_ids:
            self.get_projects()
        if project not in self._project_ids:
            raise ValueError(f"SleepyRat project not found: {project!r}")
        return self._project_ids[project]

    # -- Folders --

    def get_folders(self, project: str) -> list[str]:
        """Return the folder names within `project`."""
        project_id = self._project_id(project)
        response = requests.get(
            f"{self.base_url}/projects/{project_id}/folders", headers=self.headers
        )
        response.raise_for_status()
        folders = response.json()["folders"]
        for f in folders:
            self._folder_ids[(project_id, f["name"])] = f["id"]
        return [f["name"] for f in folders]

    def folder_names(self, project: str) -> list[str]:
        """Return a list of folder names for `project` (canonical accessor)."""
        return self.get_folders(project)

    def create_folder(self, project: str, folder_name: str) -> dict[str, Any]:
        project_id = self._project_id(project)
        response = requests.post(
            f"{self.base_url}/projects/{project_id}/folders",
            headers=self._idempotent(self.headers),
            json={"name": folder_name},
        )
        response.raise_for_status()
        folder = response.json()["folder"]
        self._folder_ids[(project_id, folder["name"])] = folder["id"]
        return folder

    def _folder_id(self, project: str, folder: str) -> int:
        """Resolve a folder name to its id, refreshing the cache once if missing."""
        project_id = self._project_id(project)
        key = (project_id, folder)
        if key not in self._folder_ids:
            self.get_folders(project)
        if key not in self._folder_ids:
            raise ValueError(f"SleepyRat folder not found: {folder!r} in project {project!r}")
        return self._folder_ids[key]

    # -- Submissions (uploads) --

    def upload_edf(self, project: str, folder: str, file_path: str | Path) -> dict[str, Any]:
        project_id = self._project_id(project)
        folder_id = self._folder_id(project, folder)
        with open(file_path, "rb") as f:
            response = requests.post(
                f"{self.base_url}/products/{PRODUCT_CODE}/projects/{project_id}"
                f"/folders/{folder_id}/submissions",
                headers=self._idempotent(self.headers),
                files={"file": f},
            )
        response.raise_for_status()
        return response.json()

    def upload_dir(self, project: str, folder: str, dir_path: str | Path) -> None:
        """Upload every `*.edf` in `dir_path` to `project/folder`."""
        for p in Path(dir_path).glob("*.edf"):
            self.upload_edf(project, folder, p)

    def get_submissions(self, project: str, folder: str) -> dict[str, Any]:
        project_id = self._project_id(project)
        folder_id = self._folder_id(project, folder)
        response = requests.get(
            f"{self.base_url}/products/{PRODUCT_CODE}/projects/{project_id}"
            f"/folders/{folder_id}/submissions",
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()

    def get_submission_names(self, project: str, folder: str) -> list[str]:
        """Return submission names within `project/folder`."""
        return [s["name"] for s in self.get_submissions(project, folder)["submissions"]]

    # -- Labels (results) --

    def _download_predictions(self, project_id: int, folder_id: int, submission_id: str) -> str:
        response = requests.get(
            f"{self.base_url}/products/{PRODUCT_CODE}/projects/{project_id}"
            f"/folders/{folder_id}/submissions/{submission_id}/predictions",
            headers=self.headers,
        )
        response.raise_for_status()
        return response.text

    def download_labels(self, project: str, folder: str, submission: str) -> str:
        """Return the labels CSV text for one submission (matched by name).

        Uses the `predictions` download kind. The v1 API computes the state
        label server-side — there is no client-adjustable threshold anymore
        (the old `threshold` parameter is gone, not just defaulted).
        """
        project_id = self._project_id(project)
        folder_id = self._folder_id(project, folder)
        submissions = self.get_submissions(project, folder)["submissions"]
        for s in submissions:
            if s["name"] == submission:
                return self._download_predictions(project_id, folder_id, s["id"])
        raise ValueError(f"SleepyRat submission not found: {submission!r} in {project}/{folder}")

    def download_labels_all(self, project: str, folder: str, outdir: str | Path) -> None:
        """Download labels for every submission in `project/folder` into `outdir`.

        Skips submissions whose `<stem>_labels.csv` already exists in `outdir`.
        """
        outdir = Path(outdir)
        outdir.mkdir(exist_ok=True)
        project_id = self._project_id(project)
        folder_id = self._folder_id(project, folder)
        for s in self.get_submissions(project, folder)["submissions"]:
            new_path = outdir / (Path(s["name"]).stem + "_labels.csv")
            if new_path.exists():
                continue
            labels = self._download_predictions(project_id, folder_id, s["id"])
            new_path.write_text(labels)

    def wait_for_processing(self, project: str, folder: str, max_wait: int = 10000) -> bool:
        """Poll until every submission in `folder` reaches a terminal state.

        Args:
            max_wait: maximum number of seconds to wait before giving up.

        Returns:
            True once every submission has reached a terminal state
            (succeeded, failed, or cancelled) — not necessarily that all
            succeeded; failures are printed with their `failure_code`.
            False if `max_wait` elapsed with submissions still pending.
        """
        # NOTE: prints status to stdout. Could move to logging — see TODO.md.
        start_time = time.time()
        while time.time() - start_time < max_wait:
            submissions = self.get_submissions(project, folder)["submissions"]
            pending = [s for s in submissions if s["status"] not in _TERMINAL_STATUSES]
            if not pending:
                failed = [s for s in submissions if s["status"] != "succeeded"]
                if failed:
                    print(
                        f"{len(failed)}/{len(submissions)} submission(s) did not succeed: "
                        + ", ".join(f"{s['name']} ({s['status']})" for s in failed)
                    )
                return True
            print(f"Waiting for {len(pending)} files to complete processing...")
            time.sleep(30)
        return False
