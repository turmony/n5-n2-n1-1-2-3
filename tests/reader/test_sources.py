import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jlpt_notes.reader.sources import build_catalog_page, load_source_pages


class ReaderSourceTests(unittest.TestCase):
    def test_discovers_supported_non_hidden_files_without_following_symlinks(self) -> None:
        with TemporaryDirectory() as directory:
            with TemporaryDirectory() as outside_directory:
                root = Path(directory)
                (root / "grammar").mkdir()
                (root / "grammar/card.md").write_text("# N5 卡片\n", encoding="utf-8")
                (root / "events.jsonl").write_text('{"id":"e1","result":"wrong"}\n', encoding="utf-8")
                (root / "secret.txt").write_text("secret", encoding="utf-8")
                (root / ".hidden.md").write_text("hidden", encoding="utf-8")
                (root / ".private").mkdir()
                (root / ".private/hidden.md").write_text("hidden", encoding="utf-8")
                external = Path(outside_directory) / "outside-reader-source.md"
                external.write_text("# 不应读取\n", encoding="utf-8")
                try:
                    (root / "linked.md").symlink_to(external)
                except OSError:
                    self.skipTest("当前环境不允许创建符号链接")

                pages = load_source_pages(root)

                self.assertEqual(
                    [page.relative_path.as_posix() for page in pages],
                    ["events.jsonl", "grammar/card.md"],
                )
                self.assertEqual(pages[0].output_path.as_posix(), "events.jsonl.md")

    def test_discovery_does_not_change_source_content_or_mtime(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "grammar/N5-G-0001.md"
            source.parent.mkdir()
            source.write_text("# 只读卡片\n", encoding="utf-8")
            jsonl = root / "events.jsonl"
            jsonl.write_text('{"id":"e1"}\n', encoding="utf-8")
            before = {
                path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                for path in (source, jsonl)
            }

            load_source_pages(root)

            after = {
                path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                for path in (source, jsonl)
            }
            self.assertEqual(after, before)

    def test_jsonl_bad_line_is_isolated_and_visible(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "events.jsonl").write_text(
                '{"id":"e1"}\nnot-json\n{"id":"e3"}\n', encoding="utf-8"
            )

            page = load_source_pages(root)[0]

            self.assertIn("记录 1", page.markdown)
            self.assertIn("第 2 行无法解析", page.markdown)
            self.assertIn("记录 3", page.markdown)
            self.assertIn("第 2 行无法解析", page.warning or "")

    def test_catalog_contains_filter_data_titles_and_deterministic_order(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cards = root / "grammar/n5"
            cards.mkdir(parents=True)
            (cards / "N5-G-0010.md").write_text(
                '---\n{"id":"N5-G-0010","level":"N5","kind":"grammar","title":"十"}\n---\n\n正文\n',
                encoding="utf-8",
            )
            (cards / "N5-G-0002.md").write_text(
                '---\n{"id":"N5-G-0002","level":"N5","kind":"grammar","title":"二","tags":["接续"]}\n---\n\n正文\n',
                encoding="utf-8",
            )
            results = root / "quizzes/results"
            results.mkdir(parents=True)
            (results / "2026-07-26-result.md").write_text("# 旧报告\n", encoding="utf-8")
            (results / "2026-07-27-result.md").write_text("# 新报告\n", encoding="utf-8")

            catalog = build_catalog_page(load_source_pages(root))

            self.assertEqual(catalog.output_path.as_posix(), "index.md")
            self.assertIn('data-level="N5"', catalog.markdown)
            self.assertIn('data-type="grammar"', catalog.markdown)
            self.assertIn('data-tags="接续"', catalog.markdown)
            self.assertIn("N5-G-0002｜二", catalog.markdown)
            self.assertLess(catalog.markdown.index("N5-G-0002｜二"), catalog.markdown.index("N5-G-0010｜十"))
            self.assertLess(catalog.markdown.index("新报告"), catalog.markdown.index("旧报告"))


if __name__ == "__main__":
    unittest.main()
