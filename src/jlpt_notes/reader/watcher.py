"""Polling, debounced, read-only change detection for reader sources."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
import time
from typing import Callable

from .sources import iter_supported_visible_source_files


@dataclass(frozen=True, order=True)
class FileStamp:
    """The minimal, deterministic state used to identify one source file."""

    path: str
    size: int
    modified_ns: int


def snapshot_sources(root: Path) -> tuple[FileStamp, ...]:
    """Return a stable stamp for each visible Markdown or JSONL source.

    The function only enumerates and stats files.  It does not follow symlinks
    or create any files, so observing a learner's source directory is safe.
    Files that disappear during an editor's save operation are skipped and are
    picked up on the following poll.
    """
    resolved = root.resolve(strict=True)
    stamps: list[FileStamp] = []
    for path in iter_supported_visible_source_files(resolved):
        try:
            stat = path.stat()
        except OSError:
            # A rename/atomic editor-save can legitimately win this race.
            continue
        stamps.append(
            FileStamp(
                path.relative_to(resolved).as_posix(),
                stat.st_size,
                stat.st_mtime_ns,
            )
        )
    return tuple(sorted(stamps, key=lambda stamp: _name_sort_key(stamp.path)))


def _name_sort_key(value: str) -> tuple[str, str]:
    return (value.casefold(), value)


class ChangeDetector:
    """Convert changing snapshots into one callback after a settle period."""

    def __init__(self, debounce_seconds: float) -> None:
        if not math.isfinite(debounce_seconds) or debounce_seconds < 0:
            raise ValueError("debounce_seconds must be a non-negative finite number")
        self._debounce_seconds = debounce_seconds
        self._latest: tuple[FileStamp, ...] | None = None
        self._changed_at: float | None = None

    def observe(self, snapshot: tuple[FileStamp, ...], now: float) -> bool:
        """Observe one snapshot and report whether its change has settled."""
        if self._latest is None:
            self._latest = snapshot
            return False
        if snapshot != self._latest:
            self._latest = snapshot
            self._changed_at = now
            return False
        if self._changed_at is None or now - self._changed_at < self._debounce_seconds:
            return False
        self._changed_at = None
        return True


class SourceWatcher:
    """Poll a source tree and report settled reader-relevant changes.

    The background worker is daemonized because it is a convenience of the
    manual launcher, but :meth:`stop` joins it promptly through ``Event.wait``.
    ``clock`` and ``snapshotter`` are injectable to keep tests deterministic.
    """

    def __init__(
        self,
        root: Path,
        on_change: Callable[[], None],
        interval_seconds: float = 0.5,
        debounce_seconds: float = 0.5,
        *,
        on_error: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        snapshotter: Callable[[Path], tuple[FileStamp, ...]] = snapshot_sources,
        initial_snapshot: tuple[FileStamp, ...] | None = None,
    ) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("interval_seconds must be a positive finite number")
        self._root = root
        self._on_change = on_change
        self._on_error = on_error
        self._interval_seconds = interval_seconds
        self._clock = clock
        self._snapshotter = snapshotter
        self._detector = ChangeDetector(debounce_seconds)
        if initial_snapshot is not None:
            self._detector.observe(initial_snapshot, 0.0)
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start polling, or leave an already-running watcher unchanged."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(target=self._run, name="jlpt-reader-watcher", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Request shutdown and wait for the polling worker to finish."""
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not current_thread():
            thread.join()
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def poll_once(self, now: float | None = None) -> bool:
        """Perform one poll and return whether it delivered a settled change.

        This small public seam is also useful to the controller's deterministic
        tests; normal launcher use goes through :meth:`start`.
        """
        try:
            snapshot = self._snapshotter(self._root)
            changed = self._detector.observe(snapshot, self._clock() if now is None else now)
        except Exception as error:
            self._report_error("source snapshot failed", error)
            return False
        if not changed:
            return False
        try:
            self._on_change()
        except Exception as error:
            self._report_error("on_change callback failed", error)
            return False
        return True

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(self._interval_seconds)

    def _report_error(self, context: str, error: Exception) -> None:
        if self._on_error is None:
            return
        message = f"{context}: {type(error).__name__}: {error}"
        try:
            self._on_error(message)
        except Exception:
            # Diagnostics must never take down the watcher either.
            pass
