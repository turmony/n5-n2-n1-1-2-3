"""Build and publish disposable, read-only reader site generations."""

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from threading import RLock

from mkdocs.commands.build import build
from mkdocs.config import load_config


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
        self._lock = RLock()

    @property
    def current(self) -> Path | None:
        with self._lock:
            return self._current

    def activate(self, site_dir: Path) -> None:
        """Atomically publish a complete new generation.

        The generation older than the immediately previous one is discarded
        only after the replacement has been verified.
        """
        candidate = site_dir.resolve(strict=True)
        if not candidate.is_dir() or not (candidate / "index.html").is_file():
            raise ValueError("A reader site must contain index.html before activation")
        if not _is_below(candidate, self._session_root):
            raise ValueError("Reader sites must be contained by the session directory")
        with self._lock:
            if candidate == self._current:
                return
            obsolete = self._previous
            self._previous = self._current
            self._current = candidate
            if obsolete is not None and obsolete != candidate:
                shutil.rmtree(obsolete, ignore_errors=True)

    def resolve(self, request_path: str) -> Path | None:
        """Return an existing regular active-site file for a relative request."""
        with self._lock:
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

    def close(self) -> None:
        """Release published paths; the owning temporary session removes files."""
        with self._lock:
            self._current = None
            self._previous = None
