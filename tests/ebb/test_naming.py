"""Tests for ebb.core.naming.parse_animal_id."""

from pathlib import Path

import pytest

from ebb.core.naming import files_for_animal, parse_animal_id


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("AM0185_6wk_whatever", "AM0185"),
        ("CW0DA2_P096_KO_foo", "CW0DA2"),
        ("XYZ123_something", "XYZ123"),
        ("Mice-1234_tester", "Mice-1234"),  # hyphenated IDs preserved
        ("noidfile", "noidfile"),  # no underscore → whole stem
        ("AM001_PREPROCESSED", "AM001"),  # standard EDF stem
        ("AM001_2024_01_15", "AM001"),  # date suffixes
        ("AM001", "AM001"),  # bare animal ID
    ],
)
def test_parse_animal_id_typical_inputs(stem, expected):
    assert parse_animal_id(Path(f"/some/dir/{stem}.edf")) == expected


def test_parse_animal_id_accepts_string_path():
    assert parse_animal_id("AM001_PREPROCESSED.edf") == "AM001"


def test_parse_animal_id_strips_extension():
    assert parse_animal_id("AM001_foo.csv") == "AM001"
    assert parse_animal_id("AM001_foo.npy") == "AM001"
    assert parse_animal_id("AM001_foo.mat") == "AM001"


def test_parse_animal_id_handles_nested_paths():
    assert parse_animal_id("/a/b/c/AM001_foo.edf") == "AM001"
    assert parse_animal_id(Path("/a/b/c/AM001_foo.edf")) == "AM001"


def test_parse_animal_id_handles_degenerate_leading_underscore():
    # Pathological: stem starts with `_`. Regex match fails, fall back to
    # the full stem rather than returning empty string.
    assert parse_animal_id("_foo.edf") == "_foo"


def test_files_for_animal_does_not_match_longer_ids(tmp_path):
    for name in ("GF1192_a_labels.csv", "GF1192m_a_labels.csv", "GF1192.txt", "GF1192m.txt", "GF11923_b.txt"):
        (tmp_path / name).write_text("")
    assert [p.name for p in files_for_animal(tmp_path, "GF1192")] == [
        "GF1192.txt",
        "GF1192_a_labels.csv",
    ]
    assert [p.name for p in files_for_animal(tmp_path, "GF1192m", ".txt")] == ["GF1192m.txt"]


def test_files_for_animal_orders_by_ending_and_handles_missing_dir(tmp_path):
    for name in ("A1_x.csv", "A1_x.txt", "A1_y.tsv"):
        (tmp_path / name).write_text("")
    got = files_for_animal(tmp_path, "A1", ".txt", ".csv", ".tsv")
    assert [p.name for p in got] == ["A1_x.txt", "A1_x.csv", "A1_y.tsv"]
    assert files_for_animal(tmp_path / "nope", "A1", ".txt") == []
