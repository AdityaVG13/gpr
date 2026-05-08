"""File locking with PID-aware stale-lock recovery.

Cross-platform: POSIX uses fcntl.flock for advisory exclusive locking;
Windows uses msvcrt.locking on the first byte of the file. Each lock
file holds the PID of the holder. On acquire failure, we check whether
the holder PID is alive; if not, we steal the lock (handles SIGKILLed
processes that didn't release).
"""

from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_IS_WINDOWS = os.name == "nt"

if _IS_WINDOWS:
    import msvcrt  # type: ignore[import-not-found]
else:
    import fcntl


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
    except OSError:
        # Windows raises OSError for invalid PIDs in some cases.
        return False


def _lock_fd(fd: int) -> bool:
    """Try to acquire an exclusive non-blocking lock on fd. Return True on
    success, False if already held."""
    if _IS_WINDOWS:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EDEADLK):
                return False
            raise
    else:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                return False
            raise


def _unlock_fd(fd: int) -> None:
    if _IS_WINDOWS:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


def _try_acquire(path: Path) -> int | None:
    """Open path, try to lock. Return fd on success, close + return None
    if the file is already locked."""
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if not _lock_fd(fd):
            os.close(fd)
            return None
    except OSError:
        os.close(fd)
        raise
    # Reserve the first byte (Windows needs the file to have ≥ 1 byte
    # before msvcrt.locking can lock it).
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    if _IS_WINDOWS:
        # Re-lock byte 0 in case the truncate cleared the lock.
        os.lseek(fd, 0, os.SEEK_SET)
    os.fsync(fd)
    return fd


def _read_holder_pid(path: Path) -> int | None:
    try:
        with open(path, "r") as f:
            text = f.read().strip()
        return int(text) if text else None
    except (FileNotFoundError, ValueError, PermissionError):
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
            except (FileNotFoundError, PermissionError):
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
            _unlock_fd(fd)
        finally:
            os.close(fd)
            try:
                path.unlink()
            except (FileNotFoundError, PermissionError):
                pass
