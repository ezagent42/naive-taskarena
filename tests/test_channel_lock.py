from __future__ import annotations

import fcntl
import sys

import pytest

from taskarena.channel import acquire_instance_lock


def test_acquire_lock_succeeds_when_no_other_instance(tmp_path):
    lock_path = tmp_path / "taskarena.lock"
    lock_file = acquire_instance_lock(lock_path)
    assert lock_file is not None
    lock_file.close()


def test_acquire_lock_exits_when_already_locked(tmp_path):
    lock_path = tmp_path / "taskarena.lock"
    # Hold the lock in the current process
    holder = open(lock_path, "w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

    with pytest.raises(SystemExit) as exc_info:
        acquire_instance_lock(lock_path)
    assert exc_info.value.code == 1

    holder.close()


def test_lock_released_after_file_closed(tmp_path):
    lock_path = tmp_path / "taskarena.lock"
    lock_file = acquire_instance_lock(lock_path)
    lock_file.close()

    # Should be acquirable again after close
    lock_file2 = acquire_instance_lock(lock_path)
    assert lock_file2 is not None
    lock_file2.close()
