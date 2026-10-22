"""Tests for marking excluded animals in sealed outputs (final PSD pkl, Prism workbook)."""

import csv
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from ebb.io import exclusions as ex
from ebb.io.psd_export import export_psds_to_xlsx
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
