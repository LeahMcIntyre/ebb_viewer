import csv
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ebb_viewer.pipeline.manifest import Manifest, ManifestEntry
from ebb_viewer.pipeline.sleep_finalize import build_sleep_export


def _write_rawstate_csv(path: Path, states: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rawstate", "final_state"])
        for s in states:
            w.writerow([s, s])


def _seed(
    tmp_path: Path, sleep_qc: dict[str, str | None], *, no_spindle: tuple[str, ...] = ()
) -> Manifest:
    m = Manifest(tmp_path)
    for animal_id, status in sleep_qc.items():
        m._entries[animal_id] = ManifestEntry(
            animal_id=animal_id,
            preprocessed_edf=f"{animal_id}_PREPROCESSED.edf",
            has_spindle=animal_id not in no_spindle,
            sleep_qc=status,
        )
    m.save()
    return m


def test_gathers_only_ok_combo_csv(tmp_path: Path):
    per_hr = 3600 // 4
    # Animal1 is ok for the project combo (LFC_RSC); a CSV from another
    # combo's folder also exists on disk and must NOT be gathered.
    _write_rawstate_csv(
        tmp_path / "spindle_outputs" / "LFC_RSC" / "Animal1_run.csv",
        ["w"] * (12 * per_hr) + ["n"] * (12 * per_hr),
    )
    _write_rawstate_csv(
        tmp_path / "spindle_outputs" / "LSC_RSC" / "Animal1_run.csv",
        ["r"] * (24 * per_hr),
    )
    (tmp_path / "standard").mkdir()
    (tmp_path / "standard" / "Animal1_PREPROCESSED.edf").write_bytes(b"")

    _seed(tmp_path, {"Animal1": "ok"})

    fake_start = datetime(2024, 1, 1, 6, 0, 0)
    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=fake_start
    ):
        result = build_sleep_export(tmp_path)

    assert result.exported == ["Animal1"]
    assert result.missing_ok == []
    # Only the project-combo CSV was copied into chosen_csvs.
    gathered = list((result.out_dir / "chosen_csvs").glob("*.csv"))
    assert [p.name for p in gathered] == ["Animal1_run.csv"]
    # Whole-file fractions reflect the LFC_RSC data (half wake, half NREM), not
    # the other combo's all-REM data.
    whole = pd.read_csv(result.written["sleep_whole_file"]).set_index(
        ["mouse_id", "state"]
    )
    assert whole.loc[("Animal1", "w"), "frac_time"] == 0.5
    assert whole.loc[("Animal1", "r"), "frac_time"] == 0.0


def test_reports_animals_not_ok(tmp_path: Path):
    (tmp_path / "standard").mkdir()
    # Animal2 has no spindle files → not counted as missing_ok
    _seed(tmp_path, {"Animal1": "needs_review", "Animal2": None}, no_spindle=("Animal2",))
    result = build_sleep_export(tmp_path)
    assert result.exported == []
    assert result.missing_ok == ["Animal1"]


def test_reports_missing_csv(tmp_path: Path):
    # Manifest says ok, but the CSV isn't on disk.
    (tmp_path / "standard").mkdir()
    _seed(tmp_path, {"Animal1": "ok"})
    result = build_sleep_export(tmp_path)
    assert result.missing_csv == ["Animal1"]
    assert result.exported == []


def test_chosen_csvs_rebuilt_each_run(tmp_path: Path):
    per_hr = 3600 // 4
    _write_rawstate_csv(
        tmp_path / "spindle_outputs" / "LFC_RSC" / "Animal1_run.csv",
        ["w"] * (24 * per_hr),
    )
    (tmp_path / "standard").mkdir()
    # Leave a stale file in chosen_csvs from a hypothetical earlier export.
    stale = tmp_path / "sleep_export" / "chosen_csvs" / "OldAnimal_run.csv"
    _write_rawstate_csv(stale, ["w"] * 10)

    _seed(tmp_path, {"Animal1": "ok"})
    result = build_sleep_export(tmp_path)

    names = {p.name for p in (result.out_dir / "chosen_csvs").glob("*.csv")}
    assert names == {"Animal1_run.csv"}  # stale file gone


def test_excluded_animal_is_still_exported(tmp_path: Path):
    per_hr = 3600 // 4
    for animal in ("Animal1", "Animal2", "Animal3"):
        _write_rawstate_csv(
            tmp_path / "spindle_outputs" / "LFC_RSC" / f"{animal}_run.csv", ["w"] * (24 * per_hr)
        )
    (tmp_path / "standard").mkdir()
    for animal in ("Animal1", "Animal2", "Animal3"):
        (tmp_path / "standard" / f"{animal}_PREPROCESSED.edf").write_bytes(b"")
    _seed(tmp_path, {"Animal1": "ok", "Animal2": "excluded", "Animal3": "needs_review"})

    with patch(
        "ebb.process.sleep_compute.read_edf_start_datetime", return_value=datetime(2024, 1, 1, 6)
    ):
        result = build_sleep_export(tmp_path)

    assert result.exported == ["Animal1", "Animal2"]
    assert result.missing_ok == ["Animal3"]
