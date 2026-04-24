"""Save/load PSD computation parameters, keyed by named run."""

import json
import re
import shutil
from pathlib import Path
from typing import List, Optional

from ebb.process.state_presets import DEFAULT_STATES, STATE_PRESETS


RUN_NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def states_from_params(params: Optional[dict]) -> List[str]:
    """Return the list of state preset keys saved in params.

    Falls back to the canonical default (wake/nrem/rem) for params that
    predate state selection or omit the field. Unknown keys are filtered so
    that a typo in a hand-edited json file doesn't crash loading — consumers
    should re-validate before using.
    """
    if params is None:
        return list(DEFAULT_STATES)
    raw = params.get("states")
    if not raw:
        return list(DEFAULT_STATES)
    return [k for k in raw if k in STATE_PRESETS]


def valid_run_name(name: str) -> bool:
    """Return True if name is a valid run identifier."""
    return bool(RUN_NAME_RE.match(name))


def _run_dir(project_root: Path, run_name: str) -> Path:
    return Path(project_root) / "psd" / run_name


def save(project_root: Path, run_name: str, params: dict) -> Path:
    """Write params to psd/<run_name>/psd_params.json and return its path."""
    out_dir = _run_dir(project_root, run_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "psd_params.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(params, indent=2))
    tmp.replace(path)
    return path


def load(project_root: Path, run_name: str) -> Optional[dict]:
    """Return saved params for run_name, or None if not found."""
    path = _run_dir(project_root, run_name) / "psd_params.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def list_runs(project_root: Path) -> List[str]:
    """Return sorted list of run names that have a psd_params.json.

    Silently migrates legacy flat psd/psd_params.json to psd/default/ on first call.
    """
    _migrate_legacy(project_root)
    psd_dir = Path(project_root) / "psd"
    if not psd_dir.is_dir():
        return []
    runs = sorted(
        d.name for d in psd_dir.iterdir()
        if d.is_dir() and (d / "psd_params.json").exists()
    )
    return runs


def _migrate_legacy(project_root: Path) -> None:
    """Move legacy flat psd/psd_params.json + psds_*.pkl → psd/default/."""
    psd_dir = Path(project_root) / "psd"
    legacy_params = psd_dir / "psd_params.json"
    if not legacy_params.exists():
        return
    default_dir = psd_dir / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    # Move params
    dest_params = default_dir / "psd_params.json"
    if not dest_params.exists():
        shutil.move(str(legacy_params), str(dest_params))
    else:
        legacy_params.unlink()
    # Move any flat pkl files
    for pkl in psd_dir.glob("*.pkl"):
        dest = default_dir / pkl.name
        if not dest.exists():
            shutil.move(str(pkl), str(dest))
