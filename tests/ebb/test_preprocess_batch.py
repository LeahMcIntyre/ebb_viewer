from pathlib import Path
from unittest.mock import patch, MagicMock
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
    def noop(path, *, savedir, **k): return savedir  # won't be called
    outs = batch(
        noop,
        tmp_path,
        use_multiprocessing=False,
        verbose=False,
    )
    assert outs == []


def test_batch_multiprocessing_uses_spawn_context(tmp_path: Path):
    """batch() uses get_context('spawn') instead of the default fork Pool,
    avoiding deadlocks when called from a multi-threaded Qt process."""
    (tmp_path / "a.edf").touch()
    (tmp_path / "b.edf").touch()

    fake_pool = MagicMock()
    fake_pool.__enter__ = lambda s: s
    fake_pool.__exit__ = lambda *_: None
    fake_pool.map.return_value = [tmp_path / "a_OUT.edf", tmp_path / "b_OUT.edf"]

    fake_ctx = MagicMock()
    fake_ctx.Pool.return_value = fake_pool

    def dummy(path, *, savedir, **kwargs):
        return savedir / Path(path).name

    with patch("ebb.preprocess.edf.multiprocessing.get_context", return_value=fake_ctx) as mock_get_ctx, \
         patch("ebb.preprocess.edf.set_cores", return_value=2):
        batch(dummy, tmp_path, use_multiprocessing=True, verbose=False)

    mock_get_ctx.assert_called_once_with("spawn")
    fake_ctx.Pool.assert_called_once_with(2)


def test_batch_sequential_does_not_use_spawn_context(tmp_path: Path):
    """When workers == 1, get_context is never called — no Pool is created."""
    (tmp_path / "a.edf").touch()

    def dummy(path, *, savedir, **kwargs):
        out = savedir / Path(path).name
        out.touch()
        return out

    with patch("ebb.preprocess.edf.multiprocessing.get_context") as mock_get_ctx, \
         patch("ebb.preprocess.edf.set_cores", return_value=1):
        batch(dummy, tmp_path, use_multiprocessing=True, verbose=False)

    mock_get_ctx.assert_not_called()
