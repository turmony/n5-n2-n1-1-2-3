import http.client
from contextlib import contextmanager
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch

from jlpt_notes.reader.builder import SiteStore
from jlpt_notes.reader.server import ReadOnlyServer


class _BlockingLeaseStore(SiteStore):
    """Expose deterministic synchronization around a real generation lease."""

    def __init__(self, session_root: Path) -> None:
        super().__init__(session_root)
        self.lease_entered = Event()
        self.lease_exited = Event()
        self.release_response = Event()

    @contextmanager
    def lease(self, request_path: str):
        try:
            with super().lease(request_path) as path:
                self.lease_entered.set()
                if not self.release_response.wait(timeout=5):
                    raise TimeoutError("test did not release the HTTP response")
                yield path
        finally:
            self.lease_exited.set()


class ReaderServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.site = self.root / "site-1"
        (self.site / "guide").mkdir(parents=True)
        (self.site / "assets").mkdir()
        (self.site / "index.html").write_text("<h1>JLPT</h1>", encoding="utf-8")
        (self.site / "guide" / "index.html").write_text("<h1>Guide</h1>", encoding="utf-8")
        (self.site / "reader-version.json").write_text('{"version":"v1"}', encoding="utf-8")
        (self.site / "assets" / "reader.css").write_text("body{}", encoding="utf-8")
        (self.site / "語法 card.html").write_text("encoded path", encoding="utf-8")
        (self.root / "source-card.md").write_text("# private source", encoding="utf-8")
        self.store = SiteStore(self.root)
        self.store.activate(self.site)
        self.server = ReadOnlyServer(self.store, "127.0.0.1", 0)
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()
        self.temporary.cleanup()

    def request(self, method: str, target: str, body: bytes | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.bound_port, timeout=5)
        connection.request(method, target, body=body)
        response = connection.getresponse()
        payload = response.read()
        headers = dict(response.getheaders())
        status = response.status
        connection.close()
        return status, headers, payload

    def raw_request(self, target: bytes) -> bytes:
        with socket.create_connection(("127.0.0.1", self.server.bound_port), timeout=5) as client:
            client.sendall(
                b"GET "
                + target
                + b" HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            )
            chunks = []
            while chunk := client.recv(64 * 1024):
                chunks.append(chunk)
        return b"".join(chunks)

    def test_get_and_head_serve_files_with_matching_metadata(self) -> None:
        status, get_headers, body = self.request("GET", "/")
        head_status, head_headers, head_body = self.request("HEAD", "/")

        self.assertEqual(status, 200)
        self.assertEqual(body, b"<h1>JLPT</h1>")
        self.assertEqual(head_status, 200)
        self.assertEqual(head_body, b"")
        for name in (
            "Content-Type",
            "Content-Length",
            "X-Content-Type-Options",
            "Content-Security-Policy",
            "Cache-Control",
        ):
            self.assertEqual(head_headers[name], get_headers[name])
        self.assertEqual(get_headers["Content-Length"], str(len(body)))
        self.assertEqual(get_headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(get_headers["Cache-Control"], "no-cache")
        self.assertEqual(
            get_headers["Content-Security-Policy"],
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'",
        )

    def test_trailing_slash_maps_to_index_without_directory_listing(self) -> None:
        status, _, body = self.request("GET", "/guide/?from=ipad")
        directory_status, _, directory_body = self.request("GET", "/guide")

        self.assertEqual(status, 200)
        self.assertEqual(body, b"<h1>Guide</h1>")
        self.assertEqual(directory_status, 404)
        self.assertNotIn(b"index.html", directory_body)

    def test_valid_percent_encoded_paths_are_served(self) -> None:
        status, _, body = self.request(
            "GET",
            "/%E8%AA%9E%E6%B3%95%20card.html?view=reader",
        )

        self.assertEqual(status, 200)
        self.assertEqual(body, b"encoded path")

    def test_raw_multiple_leading_slashes_are_rejected_before_base_normalization(self) -> None:
        normal = self.raw_request(b"/")
        self.assertIn(b" 200 ", normal.split(b"\r\n", 1)[0])
        self.assertIn(b"JLPT", normal)

        for target in (b"//", b"///", b"////guide/"):
            with self.subTest(target=target):
                response = self.raw_request(target)
                self.assertIn(b" 404 ", response.split(b"\r\n", 1)[0])
                self.assertNotIn(b"JLPT", response)

    def test_mime_types_and_no_cache_for_json_but_not_static_css(self) -> None:
        json_status, json_headers, _ = self.request("GET", "/reader-version.json")
        css_status, css_headers, _ = self.request("GET", "/assets/reader.css")

        self.assertEqual(json_status, 200)
        self.assertIn("application/json", json_headers["Content-Type"])
        self.assertEqual(json_headers["Cache-Control"], "no-cache")
        self.assertEqual(css_status, 200)
        self.assertIn("text/css", css_headers["Content-Type"])
        self.assertNotIn("Cache-Control", css_headers)

    def test_every_non_read_method_returns_405_with_allow_header(self) -> None:
        before = (self.site / "index.html").read_bytes()
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT", "BREW"):
            with self.subTest(method=method):
                status, headers, _ = self.request(method, "/", body=b"ignored")
                self.assertEqual(status, 405)
                self.assertEqual(headers["Allow"], "GET, HEAD")
        self.assertEqual((self.site / "index.html").read_bytes(), before)

    def test_traversal_filesystem_syntax_and_raw_sources_are_not_served(self) -> None:
        unsafe_targets = (
            "/../source-card.md",
            "/%2e%2e/source-card.md",
            "/..%2fsource-card.md",
            "/%2e%2e%5csource-card.md",
            "/%5c%5cserver%5cshare%5cfile.txt",
            "/C:/Windows/win.ini",
            "/index.html:%24DATA",
            "/nul%00byte.txt",
            "/source-card.md",
        )
        for target in unsafe_targets:
            with self.subTest(target=target):
                status, _, _ = self.request("GET", target)
                self.assertEqual(status, 404)

    def test_active_generation_is_leased_until_http_response_finishes(self) -> None:
        self.server.stop()
        blocking_store = _BlockingLeaseStore(self.root)
        blocking_store.activate(self.site)
        self.server = ReadOnlyServer(blocking_store, "127.0.0.1", 0)
        self.server.start()

        result: list[tuple[int, bytes]] = []

        def read_page() -> None:
            connection = http.client.HTTPConnection("127.0.0.1", self.server.bound_port, timeout=5)
            connection.request("GET", "/")
            response = connection.getresponse()
            result.append((response.status, response.read()))
            connection.close()

        request_thread = Thread(target=read_page, name="test-reader-client")
        request_thread.start()
        self.assertTrue(blocking_store.lease_entered.wait(timeout=5))

        second = self.root / "site-2"
        third = self.root / "site-3"
        for number, site in ((2, second), (3, third)):
            site.mkdir()
            (site / "index.html").write_text(f"site-{number}", encoding="utf-8")
        blocking_store.activate(second)
        blocking_store.activate(third)
        self.assertTrue(self.site.exists())

        blocking_store.release_response.set()
        request_thread.join(timeout=5)
        self.assertFalse(request_thread.is_alive())
        self.assertEqual(result, [(200, b"<h1>JLPT</h1>")])
        self.assertTrue(blocking_store.lease_exited.wait(timeout=5))
        self.assertFalse(self.site.exists())

    def test_concurrent_stop_callers_wait_for_complete_shutdown(self) -> None:
        shutdown_entered = Event()
        release_shutdown = Event()
        second_started = Event()
        second_finished = Event()
        close_finished = Event()
        real_shutdown = self.server._httpd.shutdown
        real_server_close = self.server._httpd.server_close

        def blocking_shutdown() -> None:
            shutdown_entered.set()
            if not release_shutdown.wait(timeout=5):
                raise TimeoutError("test did not release server shutdown")
            real_shutdown()

        def tracked_server_close() -> None:
            real_server_close()
            close_finished.set()

        def stop_second() -> None:
            second_started.set()
            self.server.stop()
            second_finished.set()

        with (
            patch.object(self.server._httpd, "shutdown", side_effect=blocking_shutdown),
            patch.object(self.server._httpd, "server_close", side_effect=tracked_server_close),
        ):
            first = Thread(target=self.server.stop, name="test-first-stop")
            second = Thread(target=stop_second, name="test-second-stop")
            first.start()
            self.assertTrue(shutdown_entered.wait(timeout=5))
            second.start()
            try:
                self.assertTrue(second_started.wait(timeout=5))
                self.assertFalse(second_finished.wait(timeout=0.2))
            finally:
                release_shutdown.set()
                first.join(timeout=5)
                second.join(timeout=5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertTrue(second_finished.is_set())
        self.assertTrue(close_finished.is_set())
        self.assertFalse(self.server._thread.is_alive())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.server.bound_port), timeout=0.2)

    def test_stop_waits_for_an_inflight_response_to_release_its_site_lease(self) -> None:
        self.server.stop()
        blocking_store = _BlockingLeaseStore(self.root)
        blocking_store.activate(self.site)
        self.server = ReadOnlyServer(blocking_store, "127.0.0.1", 0)
        self.server.start()
        response: list[tuple[int, bytes]] = []

        def read_page() -> None:
            connection = http.client.HTTPConnection(
                "127.0.0.1", self.server.bound_port, timeout=5
            )
            try:
                connection.request("GET", "/")
                reply = connection.getresponse()
                response.append((reply.status, reply.read()))
            finally:
                connection.close()

        client = Thread(target=read_page, name="test-inflight-client")
        client.start()
        self.assertTrue(blocking_store.lease_entered.wait(timeout=5))

        stop_finished = Event()

        def stop_server() -> None:
            self.server.stop()
            stop_finished.set()

        stopping = Thread(target=stop_server, name="test-inflight-stop")
        stopping.start()
        try:
            self.assertFalse(
                stop_finished.wait(timeout=1.0),
                "shutdown returned while a response still held the active generation",
            )
            self.assertFalse(blocking_store.lease_exited.is_set())
        finally:
            blocking_store.release_response.set()
            stopping.join(timeout=5)
            client.join(timeout=5)

        self.assertFalse(stopping.is_alive())
        self.assertFalse(client.is_alive())
        self.assertTrue(blocking_store.lease_exited.is_set())
        self.assertEqual(response, [(200, b"<h1>JLPT</h1>")])


if __name__ == "__main__":
    unittest.main()
