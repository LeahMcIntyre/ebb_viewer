from pathlib import Path
from ebb.preprocess.edf import batch

def test_batch_calls_preprocessor_once_per_edf(tmp_path: Path):
    # create fake EDF files
    (tmp_path / "a.edf").touch()
    (tmp_path / "b.edf").touch()
    (tmp_path / "note.txt").touch()

    called = []
    def dummy_preprocessor(path, *, savedir, **kwargs):
        called.append(Path(path).name)
        out = Path(savedir) / (Path(path).stem + "_OUT.edf")
        out.write_text("ok")
        return out

    outs = batch(
        dummy_preprocessor,
        tmp_path,
        use_multiprocessing=False,
        verbose=False,
    )

    assert sorted(called) == ["a.edf", "b.edf"]
    assert len(outs) == 2
    assert all(p.exists() for p in outs)

def test_batch_empty_dir_returns_empty(tmp_path: Path):
    outs = batch(
        lambda path, *, savedir, **k: savedir,  # won't be called
        tmp_path,
        use_multiprocessing=False,
        verbose=False,
    )
    assert outs == []
