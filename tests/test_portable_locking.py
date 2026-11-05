from faultevolve.common.locking import lock_exclusive, unlock
import pytest


def test_exclusive_lock_rejects_competing_writer_and_releases(tmp_path):
    path = tmp_path / "run.lock"
    with path.open("a") as first, path.open("a") as second:
        lock_exclusive(first)
        with pytest.raises(BlockingIOError):
            lock_exclusive(second)
        unlock(first)
        lock_exclusive(second)
        unlock(second)


def test_close_releases_lock(tmp_path):
    path = tmp_path / "run.lock"
    with path.open("a") as first:
        lock_exclusive(first)
    with path.open("a") as second:
        lock_exclusive(second)
        unlock(second)
