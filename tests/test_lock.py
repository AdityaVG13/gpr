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
    code = (
        "import sys, time;"
        "sys.path.insert(0, %r);"
        "from lib.state.lock import file_lock;"
        "f = file_lock(%r, timeout=2);"
        "f.__enter__();"
        "time.sleep(0.6);"
        "f.__exit__(None, None, None)"
    ) % (str(tmp_project.parent.parent.parent.parents[0]) if False else
          os.path.dirname(os.path.dirname(os.path.abspath(__file__))), str(lp))
    proc = subprocess.Popen([sys.executable, "-c", code])
    time.sleep(0.2)
    with pytest.raises(LockTimeout):
        with file_lock(lp, timeout=0.2, poll=0.05):
            pass
    proc.wait(timeout=3)


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
