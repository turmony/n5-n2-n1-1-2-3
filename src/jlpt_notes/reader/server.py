"""Serve only published reader output over a strictly read-only HTTP boundary."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
import os
from pathlib import PurePosixPath
from threading import Event, Lock, Thread, current_thread
from urllib.parse import unquote, urlsplit

from .builder import SiteStore


_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; connect-src 'self'"
)


class ReadOnlyServer:
    """Run a generated-site-only HTTP server on a background thread."""

    def __init__(self, store: SiteStore, host: str, port: int) -> None:
        self._httpd = _JoinableRequestServer((host, port), _handler_for(store))
        self._thread = Thread(
            target=self._httpd.serve_forever,
            name="jlpt-reader-http",
            daemon=True,
        )
        self._lifecycle_lock = Lock()
        self._started = False
        self._stop_owner: Thread | None = None
        self._stop_complete = Event()

    @property
    def bound_port(self) -> int:
        """Return the actual port, including an OS-selected ephemeral port."""
        return int(self._httpd.server_address[1])

    def start(self) -> None:
        """Start accepting requests once."""
        with self._lifecycle_lock:
            if self._stop_owner is not None:
                raise RuntimeError("A stopped reader server cannot be restarted")
            if self._started:
                return
            self._started = True
            self._thread.start()

    def stop(self) -> None:
        """Stop accepting requests and release the listening socket."""
        caller = current_thread()
        if caller is self._thread:
            raise RuntimeError("The reader serve thread cannot stop itself")
        with self._lifecycle_lock:
            owner = self._stop_owner
            if owner is None:
                self._stop_owner = caller
                started = self._started
                owns_shutdown = True
            elif owner is caller and not self._stop_complete.is_set():
                raise RuntimeError("Recursive reader server shutdown is not allowed")
            else:
                started = False
                owns_shutdown = False
        if not owns_shutdown:
            self._stop_complete.wait()
            return
        try:
            if started:
                self._httpd.shutdown()
                self._thread.join()
        finally:
            try:
                self._httpd.server_close()
            finally:
                self._stop_complete.set()


class _JoinableRequestServer(ThreadingHTTPServer):
    """Track request workers so closing waits for every open site response."""

    daemon_threads = False
    block_on_close = True


def _handler_for(store: SiteStore) -> type[BaseHTTPRequestHandler]:
    class GeneratedSiteHandler(BaseHTTPRequestHandler):
        def parse_request(self) -> bool:
            # BaseHTTPRequestHandler deliberately collapses a leading `//` to
            # `/`. Preserve the request-target first so our stricter path
            # boundary can reject every multiple-leading-slash form.
            self._raw_request_target = _raw_request_target(self.raw_requestline)
            return super().parse_request()

        def do_GET(self) -> None:
            self._serve(send_body=True)

        def do_HEAD(self) -> None:
            self._serve(send_body=False)

        def __getattr__(self, name: str):
            # BaseHTTPRequestHandler otherwise turns unimplemented methods into
            # 501.  This server deliberately has one uniform non-read boundary.
            if name.startswith("do_"):
                return self._method_not_allowed
            raise AttributeError(name)

        def _method_not_allowed(self) -> None:
            self.send_response(405)
            self.send_header("Allow", "GET, HEAD")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _serve(self, *, send_body: bool) -> None:
            request_path = _request_file(self._raw_request_target)
            if request_path is None:
                self.send_error(404)
                return

            with store.lease(request_path) as file_path:
                if file_path is None:
                    self.send_error(404)
                    return
                headers_sent = False
                try:
                    with file_path.open("rb") as source:
                        length = os.fstat(source.fileno()).st_size
                        content_type = mimetypes.guess_type(file_path.name)[0]
                        self.send_response(200)
                        self.send_header("Content-Type", content_type or "application/octet-stream")
                        self.send_header("Content-Length", str(length))
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
                        if file_path.suffix.casefold() in {".html", ".json"}:
                            self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        headers_sent = True
                        if send_body:
                            _copy_response(source, self.wfile)
                except (BrokenPipeError, ConnectionResetError):
                    return
                except OSError:
                    # The store protects a generation from its own cleanup. If
                    # another process removes a file before headers are sent,
                    # expose only a normal missing-page response.
                    if not headers_sent:
                        self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:
            # Query strings and local study paths must not leak to stderr.
            return

    return GeneratedSiteHandler


def _request_file(request_target: str) -> str | None:
    """Convert a URL request target to a safe site-relative POSIX path."""
    if request_target.startswith("//"):
        return None
    try:
        split = urlsplit(request_target)
        decoded = unquote(split.path, errors="strict")
    except (UnicodeError, ValueError):
        return None
    if split.scheme or split.netloc:
        return None
    if not decoded.startswith("/") or decoded.startswith("//"):
        return None
    if "\\" in decoded or "\x00" in decoded:
        return None

    raw_parts = decoded[1:].split("/")
    if any(part == ".." for part in raw_parts):
        return None
    # Colons cover drive-qualified paths and NTFS alternate data streams.
    if any(":" in part for part in raw_parts):
        return None

    relative = PurePosixPath(decoded[1:])
    if relative.is_absolute() or ".." in relative.parts:
        return None
    if decoded.endswith("/"):
        relative /= "index.html"
    return relative.as_posix()


def _raw_request_target(request_line: bytes) -> str:
    words = request_line.rstrip(b"\r\n").split()
    if len(words) < 2:
        return ""
    return words[1].decode("iso-8859-1")


def _copy_response(source, destination) -> None:
    while chunk := source.read(64 * 1024):
        destination.write(chunk)
