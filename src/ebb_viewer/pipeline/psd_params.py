"""Save/load PSD computation parameters, keyed by named run."""

import json
import re
from pathlib import Path

from ebb.process.state_presets import DEFAULT_STATES, STATE_PRESETS

RUN_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def states_from_params(params: dict | None) -> list[str]:
    """Return the list of state preset keys saved in params.

    Falls back to the canonical default (wake/nrem/rem) when params is None
    or its "states" field is empty. Unknown keys are filtered so that a typo
    in a hand-edited json file doesn't crash loading — consumers should
    re-validate before using.
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


def load(project_root: Path, run_name: str) -> dict | None:
    """Return saved params for run_name, or None if not found."""
    path = _run_dir(project_root, run_name) / "psd_params.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_runs(project_root: Path) -> list[str]:
    """Return sorted list of run names that have a psd_params.json."""
    psd_dir = Path(project_root) / "psd"
    if not psd_dir.is_dir():
        return []
    return sorted(
        d.name for d in psd_dir.iterdir() if d.is_dir() and (d / "psd_params.json").exists()
    )
