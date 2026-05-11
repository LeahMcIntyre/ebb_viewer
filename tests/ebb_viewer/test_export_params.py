"""Tests for ebb_viewer.pipeline.export_params save/load/list."""

import json
from pathlib import Path

from ebb_viewer.pipeline import export_params


def test_save_creates_file_and_dir(tmp_path: Path):
    out = export_params.save(tmp_path, "run_a", {"nstd": 5, "states": ["wake"]})
    assert out == tmp_path / "exports" / "run_a" / "export_params.json"
    assert out.is_file()


def test_save_load_roundtrip(tmp_path: Path):
    params = {
        "nstd": 5.0,
        "winsize": 180,
        "radius": 0.5,
        "noise_thresh": 0.5,
        "states": ["wake", "nrem", "rem"],
        "use_drink_mask": True,
        "use_swd_mask": False,
        "drink_pad": 2,
        "swd_pad": 0,
        "hour_windows": [[6.0, 18.0]],
        "selected_days": [0, 1, 2],
        "ann_enabled": True,
        "ann_keywords": "drink, artifact",
        "ann_match_mode": "contains",
        "ann_pad_before": 0.0,
        "ann_pad_after": 10.0,
    }
    export_params.save(tmp_path, "full", params)
    loaded = export_params.load(tmp_path, "full")
    assert loaded == params


def test_save_is_atomic_no_leftover_tmp(tmp_path: Path):
    export_params.save(tmp_path, "run_a", {"nstd": 5})
    cfg_dir = tmp_path / "exports" / "run_a"
    leftovers = list(cfg_dir.glob("*.tmp"))
    assert leftovers == []


def test_save_overwrites_existing(tmp_path: Path):
    export_params.save(tmp_path, "run_a", {"nstd": 5})
    export_params.save(tmp_path, "run_a", {"nstd": 7})
    loaded = export_params.load(tmp_path, "run_a")
    assert loaded == {"nstd": 7}


def test_load_returns_none_when_missing(tmp_path: Path):
    assert export_params.load(tmp_path, "nonexistent") is None


def test_load_returns_none_on_malformed_json(tmp_path: Path):
    cfg_dir = tmp_path / "exports" / "bad"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "export_params.json").write_text("{not json}")
    assert export_params.load(tmp_path, "bad") is None


def test_list_configs_empty_when_no_dir(tmp_path: Path):
    assert export_params.list_configs(tmp_path) == []


def test_list_configs_returns_only_dirs_with_params_json(tmp_path: Path):
    export_params.save(tmp_path, "run_a", {"x": 1})
    export_params.save(tmp_path, "run_b", {"x": 2})
    # An exports dir with no params json should be skipped (e.g. half-written export output)
    (tmp_path / "exports" / "partial").mkdir(parents=True)
    assert export_params.list_configs(tmp_path) == ["run_a", "run_b"]


def test_list_configs_sorted(tmp_path: Path):
    for name in ["zeta", "alpha", "mu"]:
        export_params.save(tmp_path, name, {"x": 1})
    assert export_params.list_configs(tmp_path) == ["alpha", "mu", "zeta"]


def test_valid_run_name_is_reexport_of_psd_params(tmp_path: Path):
    # Sanity: same constraints as PSD run names (a-zA-Z0-9_-, max 64).
    assert export_params.valid_run_name("good_name-1")
    assert not export_params.valid_run_name("bad name")
    assert not export_params.valid_run_name("a" * 65)


def test_save_writes_indented_json_for_human_review(tmp_path: Path):
    """Saved configs are user-readable in a text editor."""
    export_params.save(tmp_path, "run_a", {"nstd": 5, "states": ["wake"]})
    text = (tmp_path / "exports" / "run_a" / "export_params.json").read_text()
    assert "\n" in text  # indented, not single-line
    assert json.loads(text) == {"nstd": 5, "states": ["wake"]}
