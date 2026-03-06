"""Persists SleepyRat upload settings (project name + remote folder) per channel combo.

Stored as project_root/sleepyrat_config.json:
{
    "LFC_RSC": {"project": "My Project", "remote_folder": "PHP_6w_LFC_RSC"},
    ...
}
"""

import json
from pathlib import Path

_FILENAME = "sleepyrat_config.json"


def _path(project_root: Path) -> Path:
    return project_root / _FILENAME


def load(project_root: Path) -> dict:
    p = _path(project_root)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_combo(project_root: Path, combo: str, project: str, remote_folder: str) -> None:
    cfg = load(project_root)
    cfg[combo] = {"project": project, "remote_folder": remote_folder}
    p = _path(project_root)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    tmp.replace(p)


def get_combo(project_root: Path, combo: str) -> dict | None:
    """Return {"project": ..., "remote_folder": ...} for combo, or None if not saved."""
    return load(project_root).get(combo)
