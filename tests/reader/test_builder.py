import unittest
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jlpt_notes.reader.builder import SiteStore, build_site


class ReaderBuilderTests(unittest.TestCase):
    def test_build_uses_external_destination_and_preserves_source(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "notes"
            source.mkdir()
            card = source / "card.md"
            card.write_text("# 卡片\n", encoding="utf-8")
            before = (card.read_bytes(), card.stat().st_mtime_ns)
            destination = base / "site"

            result = build_site(source, project / "reader/mkdocs.yml", destination)

            self.assertTrue(result.success, result.error)
            self.assertTrue((destination / "index.html").is_file())
            self.assertIsNotNone(result.version)
            self.assertEqual((card.read_bytes(), card.stat().st_mtime_ns), before)

    def test_build_resolves_config_relative_paths_without_stdin(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "notes"
            source.mkdir()
            (source / "card.md").write_text("# 卡片\n", encoding="utf-8")
            destination = base / "site"

            # The GUI launcher (pythonw from Explorer) starts with no standard
            # handles, so sys.stdin is None; MkDocs must still resolve every
            # config-relative path (theme custom_dir, plugin assets) correctly.
            real_stdin = sys.stdin
            sys.stdin = None
            try:
                result = build_site(source, project / "reader/mkdocs.yml", destination)
            finally:
                sys.stdin = real_stdin

            self.assertTrue(result.success, result.error)
            self.assertTrue((destination / "index.html").is_file())
            self.assertTrue(
                (destination / "assets" / "reader.css").is_file(),
                "plugin assets must resolve relative to the config file",
            )

    def test_failed_build_writes_log_beside_temporary_site_not_in_source(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "notes"
            source.mkdir()

            result = build_site(source, base / "missing.yml", base / "site-failed")

            self.assertFalse(result.success)
            self.assertIsNotNone(result.log_path)
            assert result.log_path is not None
            self.assertEqual(result.log_path.parent, base.resolve())
            self.assertTrue(result.log_path.is_file())
            self.assertFalse((source / "build.log").exists())
            self.assertFalse((base / "site-failed").exists())

    def test_incremental_build_reuses_unchanged_pages_and_keeps_search_complete(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "notes"
            source.mkdir()
            changed = source / "changed.md"
            unchanged = source / "unchanged.md"
            changed.write_text("# Changed\n\nold searchable text\n", encoding="utf-8")
            unchanged.write_text("# Unchanged\n\nstable searchable text\n", encoding="utf-8")
            first_site = base / "site-1"
            first = build_site(source, project / "reader/mkdocs.yml", first_site)
            self.assertTrue(first.success, first.error)
            first_state = {
                path.relative_to(first_site).as_posix(): path.read_bytes()
                for path in first_site.rglob("*")
                if path.is_file()
            }
            changed.write_text("# Changed\n\nnew searchable text\n", encoding="utf-8")

            try:
                second = build_site(
                    source,
                    project / "reader/mkdocs.yml",
                    base / "site-2",
                    previous_site=first_site,
                )
            except TypeError as error:
                self.fail(f"build_site has no safe incremental publication path: {error}")

            self.assertTrue(second.success, second.error)
            self.assertGreaterEqual(second.reused_pages, 2)
            self.assertEqual(second.rendered_pages, 1)
            second_site = base / "site-2"
            search = json.loads(
                (second_site / "search/search_index.json").read_text(encoding="utf-8")
            )
            search_text = "\n".join(str(document) for document in search["docs"])
            self.assertIn("new searchable text", search_text)
            self.assertNotIn("old searchable text", search_text)
            self.assertIn("stable searchable text", search_text)
            clean_site = base / "site-clean-reference"
            clean = build_site(source, project / "reader/mkdocs.yml", clean_site)
            self.assertTrue(clean.success, clean.error)
            clean_search = json.loads(
                (clean_site / "search/search_index.json").read_text(encoding="utf-8")
            )
            document_key = lambda document: json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
            )
            self.assertEqual(
                sorted(map(document_key, search["docs"])),
                sorted(map(document_key, clean_search["docs"])),
            )
            manifest = json.loads(
                (second_site / "reader-version.json").read_text(encoding="utf-8")
            )
            unchanged_html = next(
                path.read_text(encoding="utf-8")
                for path in second_site.rglob("index.html")
                if "stable searchable text" in path.read_text(encoding="utf-8")
            )
            self.assertIn(f'data-generation="{manifest["version"]}"', unchanged_html)
            self.assertIn(
                f'<meta name="jlpt-generation" content="{manifest["version"]}">',
                unchanged_html,
            )
            self.assertEqual(
                {
                    path.relative_to(first_site).as_posix(): path.read_bytes()
                    for path in first_site.rglob("*")
                    if path.is_file()
                },
                first_state,
            )

    def test_incremental_build_falls_back_when_its_named_config_changes(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "notes"
            source.mkdir()
            (source / "card.md").write_text("# Card\n\nbody\n", encoding="utf-8")
            config_root = base / "reader-config"
            shutil.copytree(project / "reader", config_root)
            config = config_root / "reader-custom.yml"
            shutil.move(config_root / "mkdocs.yml", config)
            original = config.read_text(encoding="utf-8")
            config.write_text(
                original.replace("site_name: JLPT 学习资料", "site_name: FIRST SITE"),
                encoding="utf-8",
            )
            first_site = base / "site-1"
            first = build_site(source, config, first_site)
            self.assertTrue(first.success, first.error)
            config.write_text(
                original.replace("site_name: JLPT 学习资料", "site_name: SECOND SITE"),
                encoding="utf-8",
            )

            second = build_site(
                source,
                config,
                base / "site-2",
                previous_site=first_site,
            )

            self.assertTrue(second.success, second.error)
            self.assertEqual(second.reused_pages, 0)
            self.assertEqual(second.rendered_pages, 2)
            html = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (base / "site-2").rglob("index.html")
            )
            self.assertIn("SECOND SITE", html)
            self.assertNotIn("FIRST SITE", html)

    def test_incremental_build_cleans_stale_routes_after_a_source_is_deleted(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "notes"
            source.mkdir()
            (source / "kept.md").write_text("# Kept\n\nstill here\n", encoding="utf-8")
            removed_source = source / "removed.md"
            removed_source.write_text(
                "# Removed\n\nunique removed search text\n",
                encoding="utf-8",
            )
            first_site = base / "site-1"
            first = build_site(source, project / "reader/mkdocs.yml", first_site)
            self.assertTrue(first.success, first.error)
            first_manifest = json.loads(
                (first_site / "reader-version.json").read_text(encoding="utf-8")
            )
            removed_source.unlink()

            second_site = base / "site-2"
            second = build_site(
                source,
                project / "reader/mkdocs.yml",
                second_site,
                previous_site=first_site,
            )

            self.assertTrue(second.success, second.error)
            self.assertEqual(second.reused_pages, 0)
            self.assertEqual(second.rendered_pages, 2)
            second_manifest = json.loads(
                (second_site / "reader-version.json").read_text(encoding="utf-8")
            )
            removed_urls = set(first_manifest["pages"]) - set(second_manifest["pages"])
            self.assertEqual(len(removed_urls), 1)
            removed_url = removed_urls.pop()
            removed_output = second_site / removed_url
            if removed_url.endswith("/"):
                removed_output /= "index.html"
            self.assertFalse(removed_output.exists())
            search = (second_site / "search/search_index.json").read_text(encoding="utf-8")
            self.assertNotIn("unique removed search text", search)

    def test_site_store_keeps_one_previous_site_until_the_next_activation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, third = (root / name for name in ("site-1", "site-2", "site-3"))
            for site in (first, second, third):
                site.mkdir()
                (site / "index.html").write_text(site.name, encoding="utf-8")
            store = SiteStore(root)

            store.activate(first)
            store.activate(second)
            self.assertTrue(first.exists())
            store.activate(third)

            self.assertFalse(first.exists())
            self.assertEqual(store.current, third.resolve())
            self.assertEqual(store.resolve("index.html"), (third / "index.html").resolve())

    def test_site_store_rejects_paths_outside_the_active_site(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("home", encoding="utf-8")
            (root / "outside.txt").write_text("private", encoding="utf-8")
            store = SiteStore(root)
            store.activate(site)

            self.assertIsNone(store.resolve("../outside.txt"))
            self.assertIsNone(store.resolve("missing.html"))

    def test_site_store_keeps_a_leased_generation_readable_until_released(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, third = (root / name for name in ("site-1", "site-2", "site-3"))
            for site in (first, second, third):
                site.mkdir()
                (site / "index.html").write_text(site.name, encoding="utf-8")
            store = SiteStore(root)
            store.activate(first)

            with store.lease("index.html") as leased:
                self.assertEqual(leased, (first / "index.html").resolve())
                store.activate(second)
                store.activate(third)

                self.assertTrue(first.exists())
                assert leased is not None
                self.assertEqual(leased.read_text(encoding="utf-8"), "site-1")

            self.assertFalse(first.exists())
            self.assertTrue(second.exists())
            self.assertTrue(third.exists())
            self.assertEqual(store.current, third.resolve())

    def test_site_store_refuses_publication_after_persistent_cleanup_backlog(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sites = tuple(root / f"site-{number}" for number in range(1, 6))
            for site in sites:
                site.mkdir()
                (site / "index.html").write_text(site.name, encoding="utf-8")
            store = SiteStore(root)
            store.activate(sites[0])
            store.activate(sites[1])

            with patch(
                "jlpt_notes.reader.builder.shutil.rmtree",
                side_effect=PermissionError("locked generation"),
            ):
                store.activate(sites[2])
                store.activate(sites[3])
                with self.assertRaisesRegex(RuntimeError, "cleanup backlog limit"):
                    store.activate(sites[4])

            self.assertEqual(store.current, sites[3].resolve())
            active = store.resolve("index.html")
            assert active is not None
            self.assertEqual(active.read_text(encoding="utf-8"), "site-4")
            self.assertEqual(len(store.cleanup_errors), 2)
            self.assertTrue(all("PermissionError" in error for error in store.cleanup_errors))

    def test_rejected_candidate_is_registered_and_future_builds_are_preflight_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sites = tuple(root / f"site-{number}" for number in range(1, 6))
            for site in sites:
                site.mkdir()
                (site / "index.html").write_text(site.name, encoding="utf-8")
            store = SiteStore(root)
            store.activate(sites[0])
            store.activate(sites[1])

            with patch(
                "jlpt_notes.reader.builder.shutil.rmtree",
                side_effect=PermissionError("locked generation"),
            ):
                store.activate(sites[2])
                store.activate(sites[3])
                with self.assertRaisesRegex(RuntimeError, "cleanup backlog limit"):
                    store.activate(sites[4])

                self.assertTrue(
                    hasattr(store, "discard"),
                    "SiteStore cannot own cleanup of a never-published candidate",
                )
                self.assertTrue(
                    hasattr(store, "prepare"),
                    "SiteStore cannot block a build before another candidate is created",
                )
                store.discard(sites[4])
                for number in range(6, 12):
                    destination = root / f"site-{number}"
                    with self.assertRaisesRegex(RuntimeError, "cleanup backlog limit"):
                        store.prepare(destination)
                    self.assertFalse(destination.exists())

            self.assertEqual(store.current, sites[3].resolve())
            active = store.resolve("index.html")
            assert active is not None
            self.assertEqual(active.read_text(encoding="utf-8"), "site-4")
            self.assertEqual(len(list(root.glob("site-*"))), 5)
            self.assertEqual(len(store.cleanup_errors), 3)


if __name__ == "__main__":
    unittest.main()
