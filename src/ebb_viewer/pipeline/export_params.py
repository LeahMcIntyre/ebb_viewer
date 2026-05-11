"""Save/load reusable mask-export parameter sets, keyed by named config.

Mirror of :mod:`ebb_viewer.pipeline.psd_params` but for the Export Masks
page's "build params manually" mode. Configs live at
``exports/<run_name>/export_params.json`` alongside the export output dir.
"""

import json
from pathlib import Path

from ebb_viewer.pipeline.psd_params import valid_run_name

__all__ = ["valid_run_name", "save", "load", "list_configs"]


def _config_dir(project_root: Path, run_name: str) -> Path:
    return Path(project_root) / "exports" / run_name


def save(project_root: Path, run_name: str, params: dict) -> Path:
    """Write params to exports/<run_name>/export_params.json and return its path."""
    out_dir = _config_dir(project_root, run_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "export_params.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(params, indent=2))
    tmp.replace(path)
    return path


def load(project_root: Path, run_name: str) -> dict | None:
    """Return saved params for run_name, or None if missing/unparseable."""
    path = _config_dir(project_root, run_name) / "export_params.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_configs(project_root: Path) -> list[str]:
    """Return sorted list of config names with a saved export_params.json."""
    root = Path(project_root) / "exports"
    if not root.is_dir():
        return []
    return sorted(
        d.name for d in root.iterdir() if d.is_dir() and (d / "export_params.json").exists()
    )
