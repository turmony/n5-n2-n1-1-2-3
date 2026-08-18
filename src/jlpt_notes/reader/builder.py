"""Build and publish disposable, read-only reader site generations."""

from dataclasses import dataclass
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
from threading import RLock
from typing import Iterator

from mkdocs.commands.build import build
from mkdocs.config import load_config


_MAX_RETIRED_GENERATIONS = 2


@dataclass(frozen=True)
class BuildResult:
    """The observable outcome of building one temporary site generation."""

    success: bool
    version: str | None = None
    error: str | None = None
    log_path: Path | None = None


def build_site(source_root: Path, config_path: Path, destination: Path) -> BuildResult:
    """Build *source_root* into a new external temporary *destination*.

    A failed build removes only the directory created by this call and leaves
    source material and already-published generations untouched.
    """
    source = source_root.resolve(strict=True)
    target = destination.resolve(strict=False)
    created = False
    try:
        if target == source or _is_below(target, source):
            raise ValueError("The temporary site destination must be outside the source directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(exist_ok=False)
        created = True
        config = load_config(
            config_file=str(config_path.resolve(strict=True)),
            docs_dir=str(source),
            site_dir=str(target),
        )
        build(config)
        version = _read_generation_version(target)
        return BuildResult(success=True, version=version)
    except Exception as error:
        if created:
            shutil.rmtree(target, ignore_errors=True)
        message = f"{type(error).__name__}: {error}"
        log_path = target.parent / f"{target.name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(message + "\n", encoding="utf-8")
        return BuildResult(success=False, error=message, log_path=log_path)


def _read_generation_version(destination: Path) -> str:
    if not (destination / "index.html").is_file():
        raise ValueError("MkDocs did not create index.html")
    manifest = json.loads((destination / "reader-version.json").read_text(encoding="utf-8"))
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("reader-version.json does not contain a version")
    return version


def _is_below(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


class SiteStore:
    """Expose a stable active site while keeping one prior generation alive."""

    def __init__(self, session_root: Path) -> None:
        self._session_root = session_root.resolve(strict=False)
        self._current: Path | None = None
        self._previous: Path | None = None
        self._retired: set[Path] = set()
        self._leases: dict[Path, int] = {}
        self._cleanup_errors: dict[Path, str] = {}
        self._lock = RLock()

    @property
    def current(self) -> Path | None:
        with self._lock:
            return self._current

    @property
    def cleanup_errors(self) -> tuple[str, ...]:
        """Return retained cleanup failures for launcher diagnostics."""
        with self._lock:
            return tuple(self._cleanup_errors[path] for path in sorted(self._cleanup_errors))

    def activate(self, site_dir: Path) -> None:
        """Atomically publish a complete new generation.

        The generation older than the immediately previous one is discarded
        only after the replacement has been verified.  If deletion is
        persistently blocked, this raises ``RuntimeError`` *before* changing
        ``current``; callers should report the error and keep serving the
        existing last-good site.  ``cleanup_errors`` supplies diagnostics.
        """
        candidate = site_dir.resolve(strict=True)
        if not candidate.is_dir() or not (candidate / "index.html").is_file():
            raise ValueError("A reader site must contain index.html before activation")
        if not _is_below(candidate, self._session_root):
            raise ValueError("Reader sites must be contained by the session directory")
        with self._lock:
            if candidate == self._current:
                return
            self._collect_retired_locked()
            self._require_publication_capacity_locked()
            obsolete = self._previous
            self._previous = self._current
            self._current = candidate
            self._retired.discard(candidate)
            self._cleanup_errors.pop(candidate, None)
            if obsolete is not None and obsolete != candidate:
                self._retired.add(obsolete)
            self._collect_retired_locked()

    def resolve(self, request_path: str) -> Path | None:
        """Return an active-site file for inspection outside a streaming response.

        HTTP callers must use :meth:`lease` so a later build cannot remove the
        file between path resolution and response transmission.
        """
        with self._lock:
            return self._resolve_current_locked(request_path)

    @contextmanager
    def lease(self, request_path: str) -> Iterator[Path | None]:
        """Lease a resolved active-site file until the response is finished.

        A path outside the active site, or one that does not exist, yields
        ``None``.  A valid path keeps its generation from being cleaned up
        until the context exits.
        """
        with self._lock:
            generation = self._current
            candidate = self._resolve_current_locked(request_path)
            if generation is None or candidate is None:
                generation = None
            else:
                self._leases[generation] = self._leases.get(generation, 0) + 1
        try:
            yield candidate
        finally:
            if generation is not None:
                with self._lock:
                    remaining = self._leases[generation] - 1
                    if remaining:
                        self._leases[generation] = remaining
                    else:
                        del self._leases[generation]
                    self._collect_retired_locked()

    def close(self) -> None:
        """Retire published paths while honouring in-flight response leases."""
        with self._lock:
            self._retired.update(path for path in (self._current, self._previous) if path is not None)
            self._current = None
            self._previous = None
            self._collect_retired_locked()

    def _resolve_current_locked(self, request_path: str) -> Path | None:
        current = self._current
        if current is None:
            return None
        requested = Path(request_path)
        if requested.is_absolute():
            return None
        candidate = (current / requested).resolve(strict=False)
        if not _is_below(candidate, current) or not candidate.is_file():
            return None
        return candidate

    def _collect_retired_locked(self) -> None:
        """Bound retained generations, except ones a response still leases."""
        for path in sorted(tuple(self._retired)):
            if self._leases.get(path, 0):
                continue
            try:
                shutil.rmtree(path)
            except OSError as error:
                self._cleanup_errors[path] = f"{type(error).__name__}: {error}"
                continue
            if path.exists():
                self._cleanup_errors[path] = "CleanupError: retired generation still exists"
                continue
            self._retired.remove(path)
            self._cleanup_errors.pop(path, None)

    def _require_publication_capacity_locked(self) -> None:
        if len(self._retired) < _MAX_RETIRED_GENERATIONS:
            return
        details = "; ".join(self.cleanup_errors)
        message = (
            f"Reader generation cleanup backlog limit ({_MAX_RETIRED_GENERATIONS}) reached; "
            "the last-good site remains active."
        )
        if details:
            message += f" Cleanup errors: {details}"
        raise RuntimeError(message)
