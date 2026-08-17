"""Process-level locks for Tao Agent OS read-modify-write state updates."""

from __future__ import annotations

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows hosts
    fcntl = None
try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on Unix hosts
    msvcrt = None
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def state_lock(path: Path) -> Iterator[None]:
    """Serialize one state file's complete read-modify-write transaction."""

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_name = f"{path.name}.lock" if path.name.startswith(".") else f".{path.name}.lock"
    lock_path = path.with_name(lock_name)
    with lock_path.open("a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            lock_file.seek(0)
            lock_file.write(b"0")
            lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:  # pragma: no cover - unsupported platform
            raise OSError("no supported process lock backend")
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            else:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def project_state_lock(project: Path) -> Iterator[None]:
    """Serialize a multi-file runtime state snapshot or mutation."""

    return state_lock(project.resolve() / ".tao" / ".state.lock")
