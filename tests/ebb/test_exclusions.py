"""Tests for marking excluded animals in sealed outputs (final PSD pkl, sleep export, Prism workbook)."""

import csv
import pickle
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from ebb.io import exclusions as ex
from ebb.io.psd_export import export_psds_to_xlsx
from ebb.io.sleep_export import export_sleep
from ebb.process.psd_compute import build_run_final_pkl

EXCLUDED = {"AM002": "signal lost"}


def _rec(animal: str, state: str = "wake") -> dict:
    return {
        "path": Path(f"/data/{animal}_x_PROCESSED.edf"),
        "channels": (0,),
        "behavior": (state,),
        "freqs": np.array([1.0, 2.0, 3.0]),
        "psd": np.array([[1.0, 2.0, 3.0]]),
    }


def _write_pkl(path: Path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(records, f)


def _read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="") as f:
        return list(csv.reader(f))


# --- helpers ---------------------------------------------------------------


def test_annotate_records_marks_each_record_by_animal():
    items = [_rec("AM001"), _rec("AM002"), _rec("AM002", "nrem")]
    ex.annotate_records(items, EXCLUDED)
    assert [r["excluded"] for r in items] == [False, True, True]
    assert [r["exclusion_reason"] for r in items] == ["", "signal lost", "signal lost"]


def test_annotate_records_accepts_a_single_dict():
    rec = ex.annotate_records(_rec("AM002"), EXCLUDED)
    assert rec["excluded"] is True and rec["exclusion_reason"] == "signal lost"


def test_annotate_table_adds_columns_without_touching_the_input():
    df = pd.DataFrame({"mouse_id": ["AM001", "AM002"], "frac_time": [0.1, 0.2]})
    out = ex.annotate_table(df, EXCLUDED)
    assert list(out["excluded"]) == [False, True]
    assert list(out["exclusion_reason"]) == ["", "signal lost"]
    assert "excluded" not in df.columns


def test_annotate_table_handles_empty_tables():
    out = ex.annotate_table(pd.DataFrame(columns=["mouse_id", "state"]), EXCLUDED)
    assert list(out.columns) == ["mouse_id", "state", "excluded", "exclusion_reason"]


def test_excluded_list_is_always_written_header_only_when_empty(tmp_path):
    path = ex.write_excluded_animals(tmp_path, {})
    assert _read_csv(path) == [["animal", "reason"]]
    path = ex.write_excluded_animals(tmp_path, {"B": "x", "A": "y, with comma"})
    assert _read_csv(path) == [["animal", "reason"], ["A", "y, with comma"], ["B", "x"]]


# --- final PSD pkl -----------------------------------------------------------


def test_final_pkl_keeps_excluded_animals_and_marks_them(tmp_path):
    psd_dir = tmp_path / "psd" / "default"
    _write_pkl(psd_dir / "psds_LFC_RSC.pkl", [_rec("AM001"), _rec("AM002")])

    out = build_run_final_pkl(tmp_path, "LFC_RSC", excluded=EXCLUDED)

    with open(out, "rb") as f:
        records = pickle.load(f)
    assert len(records) == 2  # nothing dropped
    assert [(r["excluded"], r["exclusion_reason"]) for r in records] == [
        (False, ""),
        (True, "signal lost"),
    ]
    assert _read_csv(psd_dir / "excluded_animals.csv") == [["animal", "reason"], ["AM002", "signal lost"]]


def test_final_pkl_with_no_exclusions_is_marked_false_and_list_is_header_only(tmp_path):
    psd_dir = tmp_path / "psd" / "default"
    _write_pkl(psd_dir / "psds_LFC_RSC.pkl", [_rec("AM001")])
    out = build_run_final_pkl(tmp_path, "LFC_RSC", excluded={})
    with open(out, "rb") as f:
        assert pickle.load(f)[0]["excluded"] is False
    assert _read_csv(psd_dir / "excluded_animals.csv") == [["animal", "reason"]]


def test_refinalizing_reflects_exclusions_changed_since(tmp_path):
    psd_dir = tmp_path / "psd" / "default"
    _write_pkl(psd_dir / "psds_LFC_RSC.pkl", [_rec("AM002")])
    build_run_final_pkl(tmp_path, "LFC_RSC", excluded=EXCLUDED)
    out = build_run_final_pkl(tmp_path, "LFC_RSC", excluded={})  # un-excluded in the meantime
    with open(out, "rb") as f:
        assert pickle.load(f)[0]["excluded"] is False


def test_final_pkl_does_not_modify_the_computed_pkl(tmp_path):
    psd_dir = tmp_path / "psd" / "default"
    _write_pkl(psd_dir / "psds_LFC_RSC.pkl", [_rec("AM002")])
    build_run_final_pkl(tmp_path, "LFC_RSC", excluded=EXCLUDED)
    with open(psd_dir / "psds_LFC_RSC.pkl", "rb") as f:
        assert "excluded" not in pickle.load(f)[0]


# --- Prism workbook ---------------------------------------------------------


def test_prism_workbook_gets_an_excluded_sheet_only_when_marked(tmp_path):
    marked = tmp_path / "marked.pkl"
    _write_pkl(marked, ex.annotate_records([_rec("AM001"), _rec("AM002")], EXCLUDED))
    plain = tmp_path / "plain.pkl"
    _write_pkl(plain, [_rec("AM001"), _rec("AM002")])
    unmarked = tmp_path / "unmarked.pkl"
    _write_pkl(unmarked, ex.annotate_records([_rec("AM001")], {}))

    sheets = lambda p: pd.ExcelFile(p).sheet_names  # noqa: E731
    out = export_psds_to_xlsx(marked, tmp_path / "marked.xlsx")
    assert "excluded_animals" in sheets(out)
    df = pd.read_excel(out, sheet_name="excluded_animals")
    assert df.to_dict("records") == [{"animal": "AM002", "reason": "signal lost"}]
    data_sheet = next(n for n in sheets(out) if n != "excluded_animals")
    assert "AM002" in pd.read_excel(out, sheet_name=data_sheet).columns  # still in the data
    assert "excluded_animals" not in sheets(export_psds_to_xlsx(plain, tmp_path / "plain.xlsx"))
    assert "excluded_animals" not in sheets(export_psds_to_xlsx(unmarked, tmp_path / "unmarked.xlsx"))


# --- sleep export -----------------------------------------------------------


def _sleep_project(tmp_path: Path) -> tuple[Path, Path]:
    state_dir, edf_dir = tmp_path / "chosen", tmp_path / "standard"
    state_dir.mkdir()
    edf_dir.mkdir()
    for animal in ("AM001", "AM002"):
        with (state_dir / f"{animal}_LFC_RSC.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["rawstate", "final_state"])
            for s in ["w"] * 900 + ["n"] * 900:
                w.writerow([s, s])
        (edf_dir / f"{animal}_PREPROCESSED.edf").write_bytes(b"")
    return state_dir, edf_dir


def test_sleep_export_marks_excluded_animals_in_every_table(tmp_path):
    state_dir, edf_dir = _sleep_project(tmp_path)
    out = tmp_path / "sleep_export"
    with patch("ebb.process.sleep_compute.read_edf_start_datetime", return_value=datetime(2024, 1, 1, 6)):
        written = export_sleep(state_dir, edf_dir, out, excluded=EXCLUDED)

    for name in ("sleep_bins", "sleep_bins_avg", "sleep_whole_file"):
        df = pd.read_csv(written[name], keep_default_na=False)
        assert set(df["mouse_id"]) == {"AM001", "AM002"}  # kept
        flagged = df.groupby("mouse_id")["excluded"].all().to_dict()
        assert flagged == {"AM001": False, "AM002": True}
        assert set(df.loc[df.mouse_id == "AM002", "exclusion_reason"]) == {"signal lost"}
        assert pd.read_excel(written["workbook"], sheet_name=name).shape[1] == df.shape[1]
    assert _read_csv(out / "excluded_animals.csv") == [["animal", "reason"], ["AM002", "signal lost"]]


def test_sleep_export_without_exclusions_argument_adds_nothing(tmp_path):
    state_dir, edf_dir = _sleep_project(tmp_path)
    out = tmp_path / "sleep_export"
    with patch("ebb.process.sleep_compute.read_edf_start_datetime", return_value=datetime(2024, 1, 1, 6)):
        written = export_sleep(state_dir, edf_dir, out)
    assert "excluded" not in pd.read_csv(written["sleep_whole_file"]).columns
    assert not (out / "excluded_animals.csv").exists()
