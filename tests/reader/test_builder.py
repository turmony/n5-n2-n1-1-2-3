import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
