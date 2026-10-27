"""The user-facing analysis scripts: they parse, and they refuse to run on placeholder settings."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ANALYSIS_SCRIPTS = ["sleep_by_hour", "psd_analysis"]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ANALYSIS_SCRIPTS)
def test_script_stops_on_placeholder_settings(name, capsys):
    module = _load(name)
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 1
    assert "CANNOT RUN YET" in capsys.readouterr().out


def test_sleep_script_rejects_a_folder_without_manifest(tmp_path, capsys):
    module = _load("sleep_by_hour")
    module.PROJECT_ROOT = tmp_path
    with pytest.raises(SystemExit):
        module.check_settings()
    assert "no manifest.json" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("apply_notch", "ranges", "expected"),
    [
        (True, [[58, 62], [118, 122]], "used the 60 Hz notch"),
        (False, [[56, 64], [118, 122]], "WITHOUT the notch"),
        (True, [[56, 64], [118, 122]], None),
        (False, [[58, 62], [118, 122]], None),
    ],
)
def test_psd_script_warns_when_interp_ranges_do_not_match_the_notch(
    tmp_path, capsys, apply_notch, ranges, expected
):
    run_dir = tmp_path / "psd" / "default"
    run_dir.mkdir(parents=True)
    (run_dir / "psds_final.pkl").write_bytes(b"")
    (run_dir / "psd_params.json").write_text(json.dumps({"apply_notch": apply_notch}))
    module = _load("psd_analysis")
    module.RUNS = {"pre": run_dir / "psds_final.pkl"}
    module.INTERP_RANGES = ranges
    module.check_settings()
    out = capsys.readouterr().out
    if expected:
        assert expected in out
    else:
        assert "WARNING" not in out
