"""File locking: acquire, release, stale-PID steal, contention."""

from __future__ import annotations

import os

import pytest

from lib.state.lock import LockTimeout, file_lock

_IS_WINDOWS = os.name == "nt"


def test_acquire_release(tmp_project):
    lp = tmp_project / "x.lock"
    with file_lock(lp, timeout=2):
        assert lp.exists()
    assert not lp.exists()


def test_stale_pid_stolen(tmp_project):
    lp = tmp_project / "x.lock"
    lp.write_text("999999\n")
    with file_lock(lp, timeout=2):
        pass


def test_concurrent_acquire_blocks(tmp_project):
    import subprocess
    import sys
    import time

    lp = tmp_project / "x.lock"
    ready = tmp_project / "x.ready"
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Subprocess: acquire the lock, write the ready sentinel, hold for 2s.
    # The parent waits for the sentinel before attempting acquire so the
    # test isn't racing the subprocess startup.
    code = (
        "import sys, time;"
        "sys.path.insert(0, %r);"
        "from lib.state.lock import file_lock;"
        "f = file_lock(%r, timeout=5);"
        "f.__enter__();"
        "open(%r, 'w').write('go');"
        "time.sleep(2.0);"
        "f.__exit__(None, None, None)"
    ) % (repo_root, str(lp), str(ready))
    proc = subprocess.Popen([sys.executable, "-c", code])

    deadline = time.monotonic() + 5.0
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert ready.exists(), "subprocess never acquired the lock"

    with pytest.raises(LockTimeout):
        with file_lock(lp, timeout=0.3, poll=0.05):
            pass

    proc.wait(timeout=5)


@pytest.mark.skipif(
    _IS_WINDOWS,
    reason="Windows msvcrt.locking is mandatory — readers blocked while held. "
    "On POSIX fcntl.flock is advisory; PID record is readable. "
    "Behaviour difference is by design.",
)
def test_self_pid_recorded(tmp_project):
    lp = tmp_project / "x.lock"
    with file_lock(lp, timeout=2):
        recorded = int(lp.read_text().strip())
        assert recorded == os.getpid()
