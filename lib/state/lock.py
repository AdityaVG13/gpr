"""File locking with fcntl + PID-aware stale-lock recovery.

Design: cooperative advisory locking. Each lock file holds the PID of the
holder. On acquire failure, we check whether the holder PID is alive; if
not, we steal the lock. This handles SIGKILLed processes that didn't
release.
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LockTimeout(RuntimeError):
    pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _try_acquire(path: Path) -> int | None:
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
            return None
        raise
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    os.fsync(fd)
    return fd


def _read_holder_pid(path: Path) -> int | None:
    try:
        with open(path, "r") as f:
            text = f.read().strip()
        return int(text) if text else None
    except (FileNotFoundError, ValueError):
        return None


@contextmanager
def file_lock(
    path: str | Path, timeout: float = 30.0, poll: float = 0.1
) -> Iterator[None]:
    """Acquire an exclusive lock on `path`. Steals locks held by dead PIDs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + timeout
    fd: int | None = None
    while True:
        fd = _try_acquire(path)
        if fd is not None:
            break
        holder = _read_holder_pid(path)
        if holder is not None and not _pid_alive(holder):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        if time.monotonic() > deadline:
            raise LockTimeout(
                f"could not acquire {path} within {timeout}s "
                f"(held by pid={holder})"
            )
        time.sleep(poll)

    try:
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
