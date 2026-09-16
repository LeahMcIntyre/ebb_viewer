import csv
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from scipy.io import loadmat, savemat

from ebb.io.combine import combine_annotations, combine_edf, combine_swd, locate, pair


# ---------------------------------------------------------------------------
# Fake EDF Reader / Writer infrastructure
#
# combine_edf and locate go through openseize's edf.Reader / edf.Writer.
# Building real EDFs for tests requires constructing valid openseize Header
# objects, which is fragile and slow. Instead, we patch the Reader/Writer
# symbols inside ebb.io.combine and feed them tiny fakes whose behaviour is
# driven by a per-path registry filled in by `_register_fake_edf`. This lets
# every test focus on the orchestration logic (sort order, length cap,
# num_records arithmetic, naming, overwrite guard) rather than EDF I/O.
# ---------------------------------------------------------------------------


_FAKE_EDF_REGISTRY: dict[Path, dict] = {}


class _FakeHeader(dict):
    """Header double: attribute access for start_date / start_time /
    samples_per_record, dict assignment for num_records (matches openseize's
    mixed API)."""

    def __init__(
        self,
        *,
        start_date: str,
        start_time: str,
        samples_per_record: list[int],
    ):
        super().__init__()
        self.start_date = start_date
        self.start_time = start_time
        self.samples_per_record = list(samples_per_record)
        self["num_records"] = 0


class _FakeReader:
    """Stand-in for openseize.file_io.edf.Reader.

    Instantiated with a path; looks up its data + metadata from the registry.
    Supports both bare instantiation (used in combine_edf) and context-manager
    use (used in locate).
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        entry = _FAKE_EDF_REGISTRY[self.path]
        self._data: np.ndarray = entry["data"]
        self.header = _FakeHeader(
            start_date=entry["start_date"],
            start_time=entry["start_time"],
            samples_per_record=entry["samples_per_record"],
        )
        self.channels = entry["channels"]

    @property
    def shape(self) -> tuple[int, ...]:
        return self._data.shape

    def read(self, start: int, stop: int) -> np.ndarray:
        return self._data[..., start:stop]

    def close(self) -> None:
        pass

    def __enter__(self) -> "_FakeReader":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class _FakeWriter:
    """Stand-in for openseize.file_io.edf.Writer.

    Records the header/array/channels handed to write() into the registry so
    tests can inspect what would have been written.
    """

    written: list[dict] = []

    def __init__(self, path: Path):
        self.path = Path(path)

    def __enter__(self) -> "_FakeWriter":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def write(self, header, arr, channels, verbose: bool = True) -> None:
        # Persist a marker file so combine_edf's overwrite check sees it.
        self.path.write_bytes(b"")
        _FakeWriter.written.append(
            {
                "path": self.path,
                "header": header,
                "arr": np.asarray(arr).copy(),
                "channels": list(channels),
            }
        )


def _register_fake_edf(
    path: Path,
    *,
    data: np.ndarray,
    start_date: str = "01.01.26",
    start_time: str = "00.00.00",
    samples_per_record: list[int] | None = None,
    channels: list[int] | None = None,
) -> Path:
    """Register a fake EDF on disk: writes an empty marker file at `path`
    and stashes the shape/data/header info in the registry."""
    path = Path(path)
    path.write_bytes(b"")
    if samples_per_record is None:
        # Default: 1 record's worth of samples per channel. Pick 1 so any
        # combined total is divisible (combine_edf checks arr.shape[-1] % spr).
        samples_per_record = [1] * data.shape[0]
    if channels is None:
        channels = list(range(data.shape[0]))
    _FAKE_EDF_REGISTRY[path] = {
        "data": np.asarray(data),
        "start_date": start_date,
        "start_time": start_time,
        "samples_per_record": samples_per_record,
        "channels": channels,
    }
    return path


@pytest.fixture(autouse=True)
def _reset_fake_edf_state():
    _FAKE_EDF_REGISTRY.clear()
    _FakeWriter.written.clear()
    yield
    _FAKE_EDF_REGISTRY.clear()
    _FakeWriter.written.clear()


@pytest.fixture
def fake_edf_io():
    """Patch ebb.io.combine's edf.Reader and edf.Writer with the fakes above."""
    with (
        patch("ebb.io.combine.edf.Reader", _FakeReader),
        patch("ebb.io.combine.edf.Writer", _FakeWriter),
    ):
        yield


def test_pair_groups_by_token(tmp_path: Path):
    # token = "CW0DA2" (everything before first underscore)
    p1 = tmp_path / "CW0DA2_P096_part1.edf"
    p2 = tmp_path / "CW0DA2_P096_part2.edf"
    p3 = tmp_path / "CW0DA2_P096_part3.edf"
    q1 = tmp_path / "OTHER_P001_part1.edf"
    q2 = tmp_path / "OTHER_P001_part2.edf"

    # files do not need to exist for pair(); it uses stem strings
    paths = [p1, p2, p3, q1, q2]

    groups = pair(paths, pattern=r"[^_]+")  # default behavior

    # Convert to sorted lists of stems for stable comparisons
    grouped_stems = [sorted([p.stem for p in g]) for g in groups]

    assert sorted(grouped_stems) == sorted(
        [
            sorted([p1.stem, p2.stem, p3.stem]),
            sorted([q1.stem, q2.stem]),
        ]
    )


def test_pair_raises_if_no_match(tmp_path: Path):
    # Only one file with token "LONE" -> should raise
    lone = tmp_path / "LONE_P999_part1.edf"
    other = tmp_path / "DIFF_P001_part1.edf"

    with pytest.raises(ValueError, match="No match found"):
        pair([lone, other], pattern=r"[^_]+")


def test_pair_does_not_match_token_prefix(tmp_path: Path):
    # Regression: previously `pair` used substring containment (`token in
    # other.stem`), which silently grouped "CW1" with "CW10..." files.
    # Now match must be exact on the regex token.
    a1 = tmp_path / "CW1_P001_part1.edf"
    a2 = tmp_path / "CW1_P001_part2.edf"
    b1 = tmp_path / "CW10_P002_part1.edf"
    b2 = tmp_path / "CW10_P002_part2.edf"

    groups = pair([a1, a2, b1, b2], pattern=r"[^_]+")

    grouped_stems = sorted(sorted(p.stem for p in g) for g in groups)
    assert grouped_stems == sorted(
        [
            sorted([a1.stem, a2.stem]),
            sorted([b1.stem, b2.stem]),
        ]
    )


def test_combine_swd_shifts_and_stacks_intervals(tmp_path: Path):
    # Names must satisfy:
    # - pair() token pattern default: r"final_ts_([^_]+)" -> token "ANIMAL"
    # - extract_pnum requires "_P###" somewhere in name
    p1 = tmp_path / "final_ts_ANIMAL_P001.mat"
    p2 = tmp_path / "final_ts_ANIMAL_P002.mat"

    # intervals in seconds
    swds1 = np.array([[10.0, 20.0], [100.0, 110.0]])
    swds2 = np.array([[5.0, 7.0], [200.0, 205.0]])

    savemat(p1, {"final_ts": swds1})
    savemat(p2, {"final_ts": swds2})

    # amount_hours=1 -> amount_sec=3600; second file should be shifted by +3600
    created = combine_swd(
        tmp_path,
        amount_hours=1,
        pattern=r"final_ts_([^_]+)",
        verbose=False,
        label_preference="final_ts",
        overwrite=False,
    )

    assert len(created) == 1
    out_path = created[0]
    assert out_path.exists()
    assert out_path.stem.endswith("_COMBINED")

    out = loadmat(out_path, squeeze_me=True, struct_as_record=False)
    out_swds = np.asarray(out["final_ts"])

    expected = np.vstack(
        [
            swds1,
            swds2 + 3600.0,  # shifted by one chunk
        ]
    )

    # combine_swd sorts by start time; expected is already sorted
    assert out_swds.shape == expected.shape
    assert np.allclose(out_swds, expected)


def test_combine_swd_truncates_events_straddling_boundary(tmp_path: Path):
    # Regression: events whose start is within [0, amount_sec) but whose stop
    # exceeds amount_sec must have their stop clamped to the boundary so
    # they do not overlap the next file's timespan after shifting.
    p1 = tmp_path / "final_ts_ANIMAL_P001.mat"
    p2 = tmp_path / "final_ts_ANIMAL_P002.mat"

    # second event starts before boundary (3500) but ends after (3700)
    swds1 = np.array([[10.0, 20.0], [3500.0, 3700.0]])
    swds2 = np.array([[5.0, 7.0]])

    savemat(p1, {"final_ts": swds1})
    savemat(p2, {"final_ts": swds2})

    created = combine_swd(
        tmp_path,
        amount_hours=1,  # amount_sec = 3600
        pattern=r"final_ts_([^_]+)",
        verbose=False,
        label_preference="final_ts",
        overwrite=False,
    )

    out = loadmat(created[0], squeeze_me=True, struct_as_record=False)
    out_swds = np.asarray(out["final_ts"])

    expected = np.array(
        [
            [10.0, 20.0],
            [3500.0, 3600.0],  # straddling event clamped at 3600
            [3605.0, 3607.0],  # second file's event shifted by +3600
        ]
    )

    assert out_swds.shape == expected.shape
    assert np.allclose(out_swds, expected)


def test_combine_swd_empty_dir_returns_empty(tmp_path: Path):
    """No .mat files → no work, empty list (verbose path covered)."""
    assert combine_swd(tmp_path, verbose=False) == []


def test_combine_swd_refuses_to_overwrite_by_default(tmp_path: Path):
    p1 = tmp_path / "final_ts_ANIMAL_P001.mat"
    p2 = tmp_path / "final_ts_ANIMAL_P002.mat"
    savemat(p1, {"final_ts": np.array([[10.0, 20.0]])})
    savemat(p2, {"final_ts": np.array([[5.0, 7.0]])})

    # Pre-create the would-be combined output as a valid .mat. combine_swd
    # filters _COMBINED stems out of its input glob (so re-runs don't try to
    # re-combine prior outputs), but the per-tuple existence check still
    # raises before overwriting.
    out_path = p1.with_stem(p1.stem + "_COMBINED")
    savemat(out_path, {"final_ts": np.zeros((0, 2))})

    with pytest.raises(FileExistsError):
        combine_swd(tmp_path, amount_hours=1, verbose=False)


def test_combine_swd_overwrites_when_flag_set(tmp_path: Path):
    p1 = tmp_path / "final_ts_ANIMAL_P001.mat"
    p2 = tmp_path / "final_ts_ANIMAL_P002.mat"
    swds1 = np.array([[10.0, 20.0]])
    swds2 = np.array([[5.0, 7.0]])
    savemat(p1, {"final_ts": swds1})
    savemat(p2, {"final_ts": swds2})

    # First pass populates the combined file…
    created = combine_swd(tmp_path, amount_hours=1, verbose=False)
    assert len(created) == 1

    # …second pass with overwrite=True must succeed and rewrite it.
    created2 = combine_swd(tmp_path, amount_hours=1, verbose=False, overwrite=True)
    assert created2 == created


def test_combine_swd_label_preference_fallback(tmp_path: Path):
    """If `label_preference` isn't present in the .mat, fall back to first
    non-dunder key — and write the combined output under that fallback key."""
    p1 = tmp_path / "final_ts_ANIMAL_P001.mat"
    p2 = tmp_path / "final_ts_ANIMAL_P002.mat"
    # Use a non-default key so 'final_ts' is missing in both files.
    savemat(p1, {"swd_events": np.array([[10.0, 20.0]])})
    savemat(p2, {"swd_events": np.array([[5.0, 7.0]])})

    created = combine_swd(
        tmp_path,
        amount_hours=1,
        verbose=False,
        label_preference="final_ts",  # absent → falls back to "swd_events"
    )

    assert len(created) == 1
    out = loadmat(created[0], squeeze_me=True, struct_as_record=False)
    assert "swd_events" in out
    out_swds = np.asarray(out["swd_events"])
    expected = np.vstack([np.array([[10.0, 20.0]]), np.array([[5.0, 7.0]]) + 3600.0])
    assert np.allclose(out_swds, expected)


def test_combine_swd_handles_1d_single_event(tmp_path: Path):
    """A .mat containing a single (start, stop) row stored as a 1-D length-2
    array must be coerced to (1, 2) before stacking."""
    p1 = tmp_path / "final_ts_ANIMAL_P001.mat"
    p2 = tmp_path / "final_ts_ANIMAL_P002.mat"
    # Single event: scipy.io collapses a (1,2) array to shape (2,) on
    # round-trip when squeeze_me=True. We mimic that by saving 1-D.
    savemat(p1, {"final_ts": np.array([10.0, 20.0])})
    savemat(p2, {"final_ts": np.array([5.0, 7.0])})

    created = combine_swd(tmp_path, amount_hours=1, verbose=False)
    assert len(created) == 1

    out = loadmat(created[0], squeeze_me=True, struct_as_record=False)
    out_swds = np.asarray(out["final_ts"])
    expected = np.array([[10.0, 20.0], [3605.0, 3607.0]])
    assert out_swds.shape == expected.shape
    assert np.allclose(out_swds, expected)


def test_combine_swd_writes_empty_file_when_no_events_within_window(tmp_path: Path):
    """If every event in every file of a group has start >= amount_sec, the
    function still writes a _COMBINED.mat for that group, with an empty
    event array, rather than skipping the output."""
    p1 = tmp_path / "final_ts_ANIMAL_P001.mat"
    p2 = tmp_path / "final_ts_ANIMAL_P002.mat"
    # amount_sec at amount_hours=1 is 3600. Every event starts beyond that.
    savemat(p1, {"final_ts": np.array([[5000.0, 5010.0], [6000.0, 6010.0]])})
    savemat(p2, {"final_ts": np.array([[4000.0, 4010.0]])})

    created = combine_swd(tmp_path, amount_hours=1, verbose=False)
    assert len(created) == 1
    out_path = created[0]
    assert out_path.name == "final_ts_ANIMAL_P001_COMBINED.mat"

    data = loadmat(out_path, squeeze_me=True, struct_as_record=False)
    out_swds = np.asarray(data["final_ts"])
    assert out_swds.size == 0


def test_combine_swd_three_file_group(tmp_path: Path):
    """A 3-file group (P001/P002/P003) sorts by P-number and shifts each by
    idx * amount_sec."""
    p1 = tmp_path / "final_ts_ANIMAL_P001.mat"
    p2 = tmp_path / "final_ts_ANIMAL_P002.mat"
    p3 = tmp_path / "final_ts_ANIMAL_P003.mat"
    swds1 = np.array([[10.0, 20.0]])
    swds2 = np.array([[100.0, 110.0]])
    swds3 = np.array([[200.0, 210.0]])
    # Save out of P-order to ensure sorting is on P-number, not file mtime.
    savemat(p3, {"final_ts": swds3})
    savemat(p1, {"final_ts": swds1})
    savemat(p2, {"final_ts": swds2})

    created = combine_swd(tmp_path, amount_hours=1, verbose=False)
    assert len(created) == 1

    out = loadmat(created[0], squeeze_me=True, struct_as_record=False)
    out_swds = np.asarray(out["final_ts"])
    expected = np.vstack(
        [
            swds1,
            swds2 + 3600.0,
            swds3 + 2 * 3600.0,
        ]
    )
    assert out_swds.shape == expected.shape
    assert np.allclose(out_swds, expected)


# ---------------------------------------------------------------------------
# locate
# ---------------------------------------------------------------------------


def test_locate_empty_dir_returns_empty(tmp_path: Path, fake_edf_io):
    assert locate(tmp_path, fs=250, expected_hours=72) == []


def test_locate_ignores_non_edf_files(tmp_path: Path, fake_edf_io):
    (tmp_path / "notes.txt").write_text("not an edf")
    (tmp_path / "subdir").mkdir()
    assert locate(tmp_path, fs=250, expected_hours=72) == []


def test_locate_returns_only_short_files(tmp_path: Path, fake_edf_io):
    # fs=250, so 72h = 250*3600*72 = 64_800_000 samples. Use small fs (1)
    # to keep arrays tiny: 1 Hz * 3600 * 72 = 259_200 samples for nominal.
    fs = 1
    nominal = 72  # hours
    nominal_samples = int(fs * 3600 * nominal)

    short1 = _register_fake_edf(
        tmp_path / "A_SHORT.edf",
        data=np.zeros((1, nominal_samples - 100), dtype=np.float32),
    )
    long1 = _register_fake_edf(
        tmp_path / "B_LONG.edf",
        data=np.zeros((1, nominal_samples), dtype=np.float32),  # exactly nominal
    )
    short2 = _register_fake_edf(
        tmp_path / "C_SHORT.edf",
        data=np.zeros((1, nominal_samples // 2), dtype=np.float32),
    )

    result = locate(tmp_path, fs=fs, expected_hours=nominal)

    assert long1 not in result
    assert sorted(result) == sorted([short1, short2])


def test_locate_returns_empty_when_all_files_meet_length(tmp_path: Path, fake_edf_io):
    fs = 1
    nominal = 4
    nominal_samples = int(fs * 3600 * nominal)
    _register_fake_edf(
        tmp_path / "A.edf",
        data=np.zeros((1, nominal_samples + 5), dtype=np.float32),
    )
    _register_fake_edf(
        tmp_path / "B.edf",
        data=np.zeros((1, nominal_samples), dtype=np.float32),
    )
    assert locate(tmp_path, fs=fs, expected_hours=nominal) == []


# ---------------------------------------------------------------------------
# combine_edf
# ---------------------------------------------------------------------------


def test_combine_edf_no_short_files_returns_empty(tmp_path: Path, fake_edf_io):
    """No files in dir → no work, no exception, empty list."""
    out = combine_edf(tmp_path, fs=1, nominal_hours=2, verbose=False)
    assert out == []


def test_combine_edf_sorts_by_start_date_then_concatenates(tmp_path: Path, fake_edf_io):
    """Readers are sorted by header.start_date before reading + concatenating.

    File on disk has the *later* date in its name so that lexical filename
    sort would put it first; combine_edf must instead order by start_date.
    """
    fs = 1
    nominal_hours = 4  # so each "amount" chunk is 1h = 3600 samples
    amount_hours = 1
    amount_samples = int(amount_hours * fs * 3600)

    # Both files are shorter than nominal_hours so they're picked up by locate.
    # Each contains amount_samples of distinct data so we can identify which
    # chunk landed in which position of the concatenation.
    data_early = np.arange(amount_samples, dtype=np.float32).reshape(1, -1)
    data_late = np.arange(
        amount_samples, 2 * amount_samples, dtype=np.float32
    ).reshape(1, -1)

    # File whose stem sorts *first* alphabetically gets the *later* date.
    # If combine_edf were sorting by filename, "A_..." would come first; the
    # correct date-based sort puts B first.
    _register_fake_edf(
        tmp_path / "ANIMAL_A.edf",
        data=data_late,
        start_date="05.01.26",
    )
    _register_fake_edf(
        tmp_path / "ANIMAL_B.edf",
        data=data_early,
        start_date="01.01.26",
    )

    created = combine_edf(
        tmp_path,
        fs=fs,
        amount_hours=amount_hours,
        nominal_hours=nominal_hours,
        verbose=False,
    )

    assert len(created) == 1
    payload = _FakeWriter.written[0]
    # The earlier-dated file's data must come first in the concat.
    expected = np.concatenate([data_early, data_late], axis=-1)
    assert payload["arr"].shape == expected.shape
    assert np.array_equal(payload["arr"], expected)


def test_combine_edf_sorts_correctly_across_month_boundary(
    tmp_path: Path, fake_edf_io
):
    """Regression: lex-sorting the raw "DD.MM.YY" string puts May 31 *after*
    June 1 (because "31" > "01"). combine_edf must parse to a real datetime
    so May 31 sorts first."""
    fs = 1
    amount_hours = 1
    amount_samples = int(amount_hours * fs * 3600)

    data_may = np.full((1, amount_samples), 7.0, dtype=np.float32)
    data_jun = np.full((1, amount_samples), 9.0, dtype=np.float32)

    _register_fake_edf(
        tmp_path / "ANIMAL_a.edf",
        data=data_jun,
        start_date="01.06.26",  # June 1
    )
    _register_fake_edf(
        tmp_path / "ANIMAL_b.edf",
        data=data_may,
        start_date="31.05.26",  # May 31 — earlier date
    )

    combine_edf(
        tmp_path, fs=fs, amount_hours=amount_hours, nominal_hours=4, verbose=False
    )

    payload = _FakeWriter.written[0]
    # May 31's data (value 7.0) must come before June 1's (value 9.0).
    assert payload["arr"][0, 0] == 7.0
    assert payload["arr"][0, -1] == 9.0


def test_combine_edf_caps_each_read_at_reader_length(tmp_path: Path, fake_edf_io):
    """Each file shorter than amount_hours contributes its full length only.

    Regression: if combine_edf called read(0, samples) without capping, the
    openseize Reader pads past-end with NaN by default, silently producing
    a longer-than-real combined file. The current implementation caps with
    min(samples, r.shape[-1]); this test pins that behaviour.
    """
    fs = 1
    amount_hours = 1  # 3600 sample chunks
    amount_samples = int(amount_hours * fs * 3600)
    nominal_hours = 4

    # One file is *shorter* than amount_samples — should contribute its real
    # length (1500), not amount_samples (3600).
    short_len = 1500
    full_len = amount_samples
    data1 = np.full((1, short_len), 1.0, dtype=np.float32)
    data2 = np.full((1, full_len), 2.0, dtype=np.float32)

    _register_fake_edf(
        tmp_path / "X_A.edf", data=data1, start_date="01.01.26"
    )
    _register_fake_edf(
        tmp_path / "X_B.edf", data=data2, start_date="02.01.26"
    )

    combine_edf(
        tmp_path,
        fs=fs,
        amount_hours=amount_hours,
        nominal_hours=nominal_hours,
        verbose=False,
    )

    payload = _FakeWriter.written[0]
    # No NaN padding; total = short_len + full_len.
    assert payload["arr"].shape == (1, short_len + full_len)
    assert not np.any(np.isnan(payload["arr"]))


def test_combine_edf_sets_num_records_correctly(tmp_path: Path, fake_edf_io):
    """header['num_records'] = total_samples // samples_per_record[0]."""
    fs = 1
    amount_hours = 1
    amount_samples = int(amount_hours * fs * 3600)
    samples_per_record = 100  # arbitrary but divides amount_samples evenly

    data = np.zeros((1, amount_samples), dtype=np.float32)
    _register_fake_edf(
        tmp_path / "Y_A.edf",
        data=data,
        start_date="01.01.26",
        samples_per_record=[samples_per_record],
    )
    _register_fake_edf(
        tmp_path / "Y_B.edf",
        data=data,
        start_date="02.01.26",
        samples_per_record=[samples_per_record],
    )

    combine_edf(
        tmp_path, fs=fs, amount_hours=amount_hours, nominal_hours=4, verbose=False
    )

    payload = _FakeWriter.written[0]
    expected_records = (2 * amount_samples) // samples_per_record
    assert payload["header"]["num_records"] == expected_records


def test_combine_edf_raises_when_total_not_multiple_of_samples_per_record(
    tmp_path: Path, fake_edf_io
):
    """If the combined sample count isn't divisible by samples_per_record[0],
    refuse to write a corrupt EDF."""
    fs = 1
    amount_hours = 1
    spr = 7  # deliberately doesn't divide 3600 evenly

    data = np.zeros((1, int(amount_hours * fs * 3600)), dtype=np.float32)
    _register_fake_edf(
        tmp_path / "Z_A.edf", data=data, start_date="01.01.26",
        samples_per_record=[spr],
    )
    _register_fake_edf(
        tmp_path / "Z_B.edf", data=data, start_date="02.01.26",
        samples_per_record=[spr],
    )

    with pytest.raises(ValueError, match="not a multiple of"):
        combine_edf(
            tmp_path, fs=fs, amount_hours=amount_hours, nominal_hours=4,
            verbose=False,
        )


def test_combine_edf_uses_combined_suffix_on_first_reader(
    tmp_path: Path, fake_edf_io
):
    """Output path is the *date-earliest* reader's stem + '_COMBINED'."""
    fs = 1
    amount_hours = 1

    data = np.zeros((1, int(amount_hours * fs * 3600)), dtype=np.float32)
    _register_fake_edf(
        tmp_path / "ANIMAL_late.edf", data=data, start_date="05.01.26"
    )
    early = _register_fake_edf(
        tmp_path / "ANIMAL_early.edf", data=data, start_date="01.01.26"
    )

    created = combine_edf(
        tmp_path, fs=fs, amount_hours=amount_hours, nominal_hours=4, verbose=False
    )

    assert created == [early.with_stem(early.stem + "_COMBINED")]


def test_combine_edf_refuses_to_overwrite_by_default(tmp_path: Path, fake_edf_io):
    fs = 1
    amount_hours = 1
    nominal_hours = 4
    data = np.zeros((1, int(amount_hours * fs * 3600)), dtype=np.float32)
    early = _register_fake_edf(
        tmp_path / "ANIMAL_a.edf", data=data, start_date="01.01.26"
    )
    _register_fake_edf(
        tmp_path / "ANIMAL_b.edf", data=data, start_date="02.01.26"
    )

    # Pre-register the would-be combined output as a *long* EDF so locate()
    # does not classify it as short and try to combine it again. Marker file
    # is written by _register_fake_edf so the overwrite check trips on it.
    out_path = early.with_stem(early.stem + "_COMBINED")
    _register_fake_edf(
        out_path,
        data=np.zeros((1, int(fs * 3600 * nominal_hours)), dtype=np.float32),
        start_date="01.01.26",
    )

    with pytest.raises(FileExistsError):
        combine_edf(
            tmp_path, fs=fs, amount_hours=amount_hours,
            nominal_hours=nominal_hours, verbose=False,
        )


def test_combine_edf_overwrites_when_flag_set(tmp_path: Path, fake_edf_io):
    fs = 1
    amount_hours = 1
    nominal_hours = 4
    data = np.zeros((1, int(amount_hours * fs * 3600)), dtype=np.float32)
    early = _register_fake_edf(
        tmp_path / "ANIMAL_a.edf", data=data, start_date="01.01.26"
    )
    _register_fake_edf(
        tmp_path / "ANIMAL_b.edf", data=data, start_date="02.01.26"
    )

    out_path = early.with_stem(early.stem + "_COMBINED")
    _register_fake_edf(
        out_path,
        data=np.zeros((1, int(fs * 3600 * nominal_hours)), dtype=np.float32),
        start_date="01.01.26",
    )

    created = combine_edf(
        tmp_path,
        fs=fs,
        amount_hours=amount_hours,
        nominal_hours=nominal_hours,
        verbose=False,
        overwrite=True,
    )

    assert created == [out_path]
    assert _FakeWriter.written, "writer should have been invoked"


def test_combine_edf_move_short_files_relocates_inputs(tmp_path: Path, fake_edf_io):
    fs = 1
    amount_hours = 1
    data = np.zeros((1, int(amount_hours * fs * 3600)), dtype=np.float32)
    a = _register_fake_edf(
        tmp_path / "ANIMAL_a.edf", data=data, start_date="01.01.26"
    )
    b = _register_fake_edf(
        tmp_path / "ANIMAL_b.edf", data=data, start_date="02.01.26"
    )

    combine_edf(
        tmp_path,
        fs=fs,
        amount_hours=amount_hours,
        nominal_hours=4,
        verbose=False,
        move_short_files=True,
        short_dirname="archived",
    )

    archive = tmp_path / "archived"
    assert archive.is_dir()
    assert (archive / a.name).exists()
    assert (archive / b.name).exists()
    assert not a.exists()
    assert not b.exists()


# ---------------------------------------------------------------------------
# combine_annotations
# ---------------------------------------------------------------------------
#
# Pinnacle annotation files look like:
#   <6 metadata lines>            ← preserved verbatim
#   Annotation\tTime From Start\tStart Time\tEnd Time\tChannel   ← CSV header
#   drink\t10.0\t10/15/25 10:30:00.000\t10/15/25 10:30:01.000\tEEG1   ← rows
#
# We mimic just enough of that to exercise the round-trip.


_ANN_FIELDS = ["Annotation", "Time From Start", "Start Time", "End Time", "Channel"]


def _write_pinnacle_txt(
    path: Path,
    rows: list[dict[str, str]],
    *,
    header_rows: int = 6,
) -> None:
    """Write a minimal Pinnacle-style annotation .txt at `path`."""
    lines: list[str] = [f"# meta line {i + 1}\n" for i in range(header_rows)]
    lines.append("\t".join(_ANN_FIELDS) + "\n")
    for r in rows:
        lines.append("\t".join(r.get(c, "") for c in _ANN_FIELDS) + "\n")
    path.write_text("".join(lines), encoding="utf-8")


def _read_pinnacle_data_rows(
    path: Path, header_rows: int = 6
) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        for _ in range(header_rows):
            next(f)
        return list(csv.DictReader(f, delimiter="\t"))


def test_combine_annotations_empty_dir_returns_empty(tmp_path: Path):
    assert combine_annotations(tmp_path, verbose=False) == []


def test_combine_annotations_shifts_and_stacks(tmp_path: Path):
    """Second file's Time From Start values must be shifted by amount_sec."""
    p1 = tmp_path / "ANIMAL_P001.txt"
    p2 = tmp_path / "ANIMAL_P002.txt"
    _write_pinnacle_txt(
        p1,
        [
            {
                "Annotation": "drink",
                "Time From Start": "10.0",
                "Start Time": "01/01/26 10:00:10.000",
                "End Time": "01/01/26 10:00:11.000",
                "Channel": "EEG1",
            },
            {
                "Annotation": "drink",
                "Time From Start": "100.0",
                "Start Time": "01/01/26 10:01:40.000",
                "End Time": "01/01/26 10:01:41.000",
                "Channel": "EEG1",
            },
        ],
    )
    _write_pinnacle_txt(
        p2,
        [
            {
                "Annotation": "drink",
                "Time From Start": "50.0",
                "Start Time": "01/01/26 11:00:50.000",
                "End Time": "01/01/26 11:00:51.000",
                "Channel": "EEG1",
            },
        ],
    )

    created = combine_annotations(tmp_path, amount_hours=1, verbose=False)
    assert len(created) == 1
    out = created[0]
    assert out.stem.endswith("_COMBINED")

    rows = _read_pinnacle_data_rows(out)
    times = [float(r["Time From Start"]) for r in rows]
    assert times == [10.0, 100.0, 3650.0]


def test_combine_annotations_drops_rows_outside_window(tmp_path: Path):
    """Rows whose Time From Start >= amount_sec must be dropped, matching
    combine_swd's behaviour."""
    p1 = tmp_path / "ANIMAL_P001.txt"
    p2 = tmp_path / "ANIMAL_P002.txt"
    _write_pinnacle_txt(
        p1,
        [
            {"Annotation": "x", "Time From Start": "100.0",
             "Start Time": "", "End Time": "", "Channel": ""},
            # Past the 1h window — should be dropped.
            {"Annotation": "x", "Time From Start": "4000.0",
             "Start Time": "", "End Time": "", "Channel": ""},
        ],
    )
    _write_pinnacle_txt(
        p2,
        [
            {"Annotation": "x", "Time From Start": "50.0",
             "Start Time": "", "End Time": "", "Channel": ""},
            # Past file-2's local 1h window — should be dropped too.
            {"Annotation": "x", "Time From Start": "5000.0",
             "Start Time": "", "End Time": "", "Channel": ""},
        ],
    )

    created = combine_annotations(tmp_path, amount_hours=1, verbose=False)
    rows = _read_pinnacle_data_rows(created[0])
    times = [float(r["Time From Start"]) for r in rows]
    assert times == [100.0, 3650.0]


def test_combine_annotations_preserves_preheader_and_columns(tmp_path: Path):
    """First file's 6 metadata lines and CSV header must be carried through
    unchanged; non-time columns must round-trip verbatim."""
    p1 = tmp_path / "ANIMAL_P001.txt"
    p2 = tmp_path / "ANIMAL_P002.txt"
    _write_pinnacle_txt(
        p1,
        [
            {
                "Annotation": "drink",
                "Time From Start": "10.0",
                "Start Time": "01/01/26 10:00:10.000",
                "End Time": "01/01/26 10:00:11.000",
                "Channel": "EEG1",
            },
        ],
    )
    _write_pinnacle_txt(
        p2,
        [
            {
                "Annotation": "drink",
                "Time From Start": "20.0",
                "Start Time": "01/01/26 11:00:20.000",
                "End Time": "01/01/26 11:00:21.000",
                "Channel": "EEG1",
            },
        ],
    )

    created = combine_annotations(tmp_path, amount_hours=1, verbose=False)
    out_text = created[0].read_text(encoding="utf-8")
    lines = out_text.splitlines()

    # Preheader: same 6 metadata lines from file 1.
    assert lines[:6] == [f"# meta line {i + 1}" for i in range(6)]
    # CSV header: identical column order.
    assert lines[6].split("\t") == _ANN_FIELDS

    rows = _read_pinnacle_data_rows(created[0])
    # Non-time columns preserved exactly as the originals.
    assert rows[0]["Annotation"] == "drink"
    assert rows[0]["Start Time"] == "01/01/26 10:00:10.000"
    assert rows[0]["End Time"] == "01/01/26 10:00:11.000"
    assert rows[0]["Channel"] == "EEG1"
    # File-2's wall-clock cols also kept untouched (they reflect real times).
    assert rows[1]["Start Time"] == "01/01/26 11:00:20.000"
    assert rows[1]["End Time"] == "01/01/26 11:00:21.000"


def test_combine_annotations_refuses_to_overwrite_by_default(tmp_path: Path):
    p1 = tmp_path / "ANIMAL_P001.txt"
    p2 = tmp_path / "ANIMAL_P002.txt"
    _write_pinnacle_txt(
        p1,
        [{"Annotation": "x", "Time From Start": "10.0",
          "Start Time": "", "End Time": "", "Channel": ""}],
    )
    _write_pinnacle_txt(
        p2,
        [{"Annotation": "x", "Time From Start": "20.0",
          "Start Time": "", "End Time": "", "Channel": ""}],
    )

    out_path = p1.with_stem(p1.stem + "_COMBINED")
    out_path.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        combine_annotations(tmp_path, amount_hours=1, verbose=False)


def test_combine_annotations_overwrites_when_flag_set(tmp_path: Path):
    p1 = tmp_path / "ANIMAL_P001.txt"
    p2 = tmp_path / "ANIMAL_P002.txt"
    _write_pinnacle_txt(
        p1,
        [{"Annotation": "x", "Time From Start": "10.0",
          "Start Time": "", "End Time": "", "Channel": ""}],
    )
    _write_pinnacle_txt(
        p2,
        [{"Annotation": "x", "Time From Start": "20.0",
          "Start Time": "", "End Time": "", "Channel": ""}],
    )

    out_path = p1.with_stem(p1.stem + "_COMBINED")
    out_path.write_text("stale", encoding="utf-8")

    created = combine_annotations(
        tmp_path, amount_hours=1, verbose=False, overwrite=True
    )

    assert created == [out_path]
    rows = _read_pinnacle_data_rows(out_path)
    assert [float(r["Time From Start"]) for r in rows] == [10.0, 3620.0]


def test_combine_annotations_three_file_group(tmp_path: Path):
    """Three-file group is sorted by P-number; each idx shifted by idx*amount."""
    p1 = tmp_path / "ANIMAL_P001.txt"
    p2 = tmp_path / "ANIMAL_P002.txt"
    p3 = tmp_path / "ANIMAL_P003.txt"
    # Write out of P-order.
    _write_pinnacle_txt(
        p3,
        [{"Annotation": "x", "Time From Start": "200.0",
          "Start Time": "", "End Time": "", "Channel": ""}],
    )
    _write_pinnacle_txt(
        p1,
        [{"Annotation": "x", "Time From Start": "10.0",
          "Start Time": "", "End Time": "", "Channel": ""}],
    )
    _write_pinnacle_txt(
        p2,
        [{"Annotation": "x", "Time From Start": "100.0",
          "Start Time": "", "End Time": "", "Channel": ""}],
    )

    created = combine_annotations(tmp_path, amount_hours=1, verbose=False)
    rows = _read_pinnacle_data_rows(created[0])
    times = [float(r["Time From Start"]) for r in rows]
    assert times == [10.0, 100.0 + 3600.0, 200.0 + 2 * 3600.0]


def test_combine_annotations_skips_group_when_all_outside_window(tmp_path: Path):
    """If every row in every file of a group is past the per-file window,
    emit nothing for that group (no _COMBINED.txt left behind)."""
    p1 = tmp_path / "ANIMAL_P001.txt"
    p2 = tmp_path / "ANIMAL_P002.txt"
    _write_pinnacle_txt(
        p1,
        [{"Annotation": "x", "Time From Start": "9999.0",
          "Start Time": "", "End Time": "", "Channel": ""}],
    )
    _write_pinnacle_txt(
        p2,
        [{"Annotation": "x", "Time From Start": "8888.0",
          "Start Time": "", "End Time": "", "Channel": ""}],
    )

    created = combine_annotations(tmp_path, amount_hours=1, verbose=False)
    assert created == []
    assert not any(p.name.endswith("_COMBINED.txt") for p in tmp_path.glob("*.txt"))


def test_combine_annotations_skips_existing_combined_on_rerun(tmp_path: Path):
    """A previously-written *_COMBINED.txt must not be re-picked up as a
    short file on a second pass (mirrors combine_swd / combine_edf)."""
    p1 = tmp_path / "ANIMAL_P001.txt"
    p2 = tmp_path / "ANIMAL_P002.txt"
    _write_pinnacle_txt(
        p1,
        [{"Annotation": "x", "Time From Start": "10.0",
          "Start Time": "", "End Time": "", "Channel": ""}],
    )
    _write_pinnacle_txt(
        p2,
        [{"Annotation": "x", "Time From Start": "20.0",
          "Start Time": "", "End Time": "", "Channel": ""}],
    )

    # First pass writes the combined file.
    combine_annotations(tmp_path, amount_hours=1, verbose=False)

    # Second pass: with overwrite=True the existing combined file is
    # filtered out of the input glob, so we cleanly rewrite it instead of
    # raising "no match found" from pair() (which would happen if the
    # combined file were grouped with the originals).
    created = combine_annotations(
        tmp_path, amount_hours=1, verbose=False, overwrite=True
    )
    assert len(created) == 1
    assert created[0].stem.endswith("_COMBINED")


def test_combine_annotations_roundtrips_through_pinnacle_reader(tmp_path: Path):
    """The combined .txt must be readable by openseize.file_io.annotations.Pinnacle
    (which is the path mask code uses) and yield the shifted ann.time values."""
    from openseize.file_io import annotations as oz_ann

    p1 = tmp_path / "ANIMAL_P001.txt"
    p2 = tmp_path / "ANIMAL_P002.txt"
    _write_pinnacle_txt(
        p1,
        [
            {
                "Annotation": "drink",
                "Time From Start": "10.0",
                "Start Time": "01/01/26 10:00:10.000",
                "End Time": "01/01/26 10:00:11.000",
                "Channel": "EEG1",
            },
        ],
    )
    _write_pinnacle_txt(
        p2,
        [
            {
                "Annotation": "drink",
                "Time From Start": "50.0",
                "Start Time": "01/01/26 11:00:50.000",
                "End Time": "01/01/26 11:00:51.000",
                "Channel": "EEG1",
            },
        ],
    )

    created = combine_annotations(tmp_path, amount_hours=1, verbose=False)

    with oz_ann.Pinnacle(created[0], start=6) as reader:
        annotes = reader.read()

    times = [a.time for a in annotes]
    assert times == [10.0, 3650.0]
    # Per-row durations are still computed from Start/End wall-clock cols,
    # which we left untouched. Each row's own clock window remains valid:
    # 1.0 second in both cases.
    durations = [a.duration for a in annotes]
    assert all(d == pytest.approx(1.0) for d in durations)
