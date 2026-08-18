"""Own disposable reader sessions and safely collect abandoned generations."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import BinaryIO


_SESSION_PREFIX = "jlpt-reader-"
_OWNER_MARKER = "owner.lock"
_MAX_CLEANUP_ERRORS = 8


class _OwnerLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.file: BinaryIO = path.open("a+b", buffering=0)
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write(b"\0")
        self.file.seek(0)
        self.locked = False

    def try_acquire(self) -> bool:
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self.locked = True
        return True

    def close(self) -> None:
        if self.locked:
            try:
                self.file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            finally:
                self.locked = False
        self.file.close()


class ReaderSessionDirectory:
    """A uniquely owned temp directory whose lock survives for its lifetime."""

    def __init__(self, *, parent: Path | None = None) -> None:
        base = Path(parent) if parent is not None else Path(tempfile.gettempdir())
        self._parent = base.resolve(strict=True)
        if not self._parent.is_dir():
            raise NotADirectoryError(self._parent)
        self.name = tempfile.mkdtemp(prefix=_SESSION_PREFIX, dir=str(self._parent))
        self._path = Path(self.name).resolve(strict=True)
        self._lock_path = _external_lock_path(self._path)
        self._owner = _OwnerLock(self._lock_path)
        if not self._owner.try_acquire():
            self._owner.close()
            shutil.rmtree(self._path, ignore_errors=True)
            raise RuntimeError("Could not acquire ownership of the new reader session")
        try:
            (self._path / _OWNER_MARKER).write_bytes(b"jlpt-reader-session\n")
            self.cleanup_errors = cleanup_stale_reader_sessions(
                self._parent,
                exclude=self._path,
            )
        except Exception:
            self._owner.close()
            self._lock_path.unlink(missing_ok=True)
            shutil.rmtree(self._path, ignore_errors=True)
            raise
        self._cleaned = False

    def cleanup(self) -> None:
        """Delete this owned session; retain ownership if deletion must retry."""
        if self._cleaned:
            return
        shutil.rmtree(self._path)
        self._owner.close()
        self._lock_path.unlink(missing_ok=True)
        self._cleaned = True


def cleanup_stale_reader_sessions(
    parent: Path,
    *,
    exclude: Path | None = None,
) -> tuple[str, ...]:
    """Remove only unlocked, explicitly owned direct child reader sessions."""
    root = Path(parent).resolve(strict=True)
    excluded = Path(exclude).resolve(strict=False) if exclude is not None else None
    errors: list[str] = []
    for candidate in sorted(root.iterdir(), key=lambda path: (path.name.casefold(), path.name)):
        if not candidate.name.startswith(_SESSION_PREFIX):
            continue
        if candidate.is_symlink() or _is_reparse_point(candidate):
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved == excluded or resolved.parent != root or not resolved.is_dir():
            continue
        marker = resolved / _OWNER_MARKER
        if marker.is_symlink() or not marker.is_file():
            continue

        lock = _OwnerLock(_external_lock_path(resolved))
        if not lock.try_acquire():
            lock.close()
            continue
        lock_path = lock.path
        try:
            shutil.rmtree(resolved)
        except OSError as error:
            if len(errors) < _MAX_CLEANUP_ERRORS:
                errors.append(f"{resolved.name}: {type(error).__name__}: {error}")
        finally:
            lock.close()
        if not resolved.exists():
            lock_path.unlink(missing_ok=True)
    return tuple(errors)


def _external_lock_path(session_path: Path) -> Path:
    return session_path.parent / f".{session_path.name}.lock"


def _is_reparse_point(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            if is_junction():
                return True
        except OSError:
            return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
