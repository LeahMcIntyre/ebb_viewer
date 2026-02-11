import requests
import json
import time
from pathlib import Path
from typing import Optional, List


class SleepyRatAPI:
    def __init__(self, username="REDACTED_1", password="REDACTED_2", base_url="https://sleepyrat.ai/api"):
        self.base_url = base_url
        self.token = self._login(username, password)
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def _login(self, username, password):
        response = requests.post(f"{self.base_url}/login", 
                               json={"username": username, "password": password})
        response.raise_for_status()
        return response.json()["access_token"]

    # Returns a list of projects in account
    def get_projects(self):
        response = requests.get(f"{self.base_url}/projects",
                                headers=self.headers)
        return response.json()

    def project_names(self) -> list[str]:
        """Return a simple list of project names from get_projects()."""
        data = self.get_projects()
        return [p['name'] for p in data]

    def create_project(self, name, description=""):
        response = requests.post(f"{self.base_url}/projects",
                               headers=self.headers,
                               json={"name": name, "description": description})
        return response.json()
    
    # Returns a list of folders in account 
    def get_folders(self, project):
        response = requests.get(f"{self.base_url}/projects/{project}/folders",
                                headers=self.headers)
        return response.json() 

    def create_folder(self, project, folder_name):
        response = requests.post(f"{self.base_url}/projects/{project}/folders",
                               headers=self.headers,
                               json={"folder_name": folder_name})
        return response.json()
    
    def upload_edf(self, project, folder, file_path):
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = requests.post(
                f"{self.base_url}/projects/{project}/folders/{folder}/submissions",
                headers=self.headers, 
                files=files
            )
        return response.json()
    
    # Upload all edfs in dir_path to sleepy rat in project/folder
    def upload_dir(self, project, folder, dir_path):
        edf_paths = list(Path(dir_path).glob('*.edf'))
        for p in edf_paths:
            self.upload_edf(project, folder, p)
    
    def get_submissions(self, project, folder):
        response = requests.get(
            f"{self.base_url}/projects/{project}/folders/{folder}/submissions",
            headers=self.headers
        )
        return response.json()
    
    # Returns a list of submission names in project/folder
    def get_submission_names(self, project, folder):
        submissions = self.get_submissions(project, folder)["submissions"]
        return [s["name"] for s in submissions]
    
    def download_labels(self, project, folder, submission, threshold=0.5):
        response = requests.get(
            f"{self.base_url}/projects/{project}/folders/{folder}/files/{submission}/labels/{threshold}",
            headers=self.headers
        )
        return response.text
    
    def download_labels_all(self, project, folder, outdir, threshold=0.5):
        outdir = Path(outdir)
        outdir.mkdir(exist_ok=True)
        names = self.get_submission_names(project, folder)
        for name in names: 
            new_path = Path(outdir, Path(name).stem + "_labels.csv")
            labels = self.download_labels(project, folder, name, threshold=threshold)
            with open(new_path, "w") as f:
                f.write(labels)
            

    def wait_for_processing(self, project, folder, max_wait=10000):
        """Wait for all files in folder to finish processing"""
        start_time = time.time()
        while time.time() - start_time < max_wait:
            submissions = self.get_submissions(project, folder)
            pending = [s for s in submissions["submissions"] if s.get("msg") != ""]
            if not pending:
                return True
            print(f"Waiting for {len(pending)} files to complete processing...")
            time.sleep(30)
        return False





"""# Usage example
api = SleepyRatAPI("your_username", "your_password")

# Create project structure
api.create_project("my_study", "Automated sleep analysis")
api.create_folder("my_study", "experiment_1")

# Process files
api.upload_edf("my_study", "experiment_1", "mouse001.edf")
api.upload_edf("my_study", "experiment_1", "mouse002.edf")

# Wait for processing
if api.wait_for_processing("my_study", "experiment_1"):
    # Download results
    results1 = api.download_labels("my_study", "experiment_1", "mouse001", 0.5)
    with open("mouse001_results.csv", "w") as f:
        f.write(results1)
    print("Results downloaded successfully!")
else:
    print("Processing timed out")"""