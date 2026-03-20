"""Save/load PSD computation parameters to psd/psd_params.json."""

import json
from pathlib import Path
from typing import Optional


def save(project_root: Path, params: dict) -> Path:
    """Write params to <project_root>/psd/psd_params.json and return its path."""
    out_dir = Path(project_root) / "psd"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "psd_params.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(params, indent=2))
    tmp.replace(path)
    return path


def load(project_root: Path) -> Optional[dict]:
    """Return saved params dict, or None if psd_params.json does not exist."""
    path = Path(project_root) / "psd" / "psd_params.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None
