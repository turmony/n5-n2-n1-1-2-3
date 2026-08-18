import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from jlpt_notes.reader.metadata import parse_markdown
from jlpt_notes.reader.sources import SourcePage, build_catalog_page, load_source_pages


class _CatalogEntryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entry_attributes: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":
            self.entry_attributes.append(dict(attrs))


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

    @unittest.skipUnless(os.name == "nt", "NTFS junction behavior is Windows-specific")
    def test_discovery_does_not_traverse_an_ntfs_junction_outside_the_root(self) -> None:
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside_directory:
            root = Path(directory)
            outside = Path(outside_directory)
            (outside / "exposed.md").write_text("# must stay outside\n", encoding="utf-8")
            junction = root / "linked-library"
            completed = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if completed.returncode != 0 or not getattr(junction, "is_junction", lambda: False)():
                self.skipTest("当前测试卷不支持创建 NTFS junction")
            try:
                pages = load_source_pages(root)
            finally:
                os.rmdir(junction)

            self.assertEqual(pages, ())

    def test_discovery_does_not_traverse_a_directory_symlink_outside_the_root(self) -> None:
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside_directory:
            root = Path(directory)
            outside = Path(outside_directory)
            (outside / "exposed.md").write_text("# must stay outside\n", encoding="utf-8")
            linked = root / "linked-library"
            try:
                linked.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("当前环境不允许创建目录符号链接")

            self.assertEqual(load_source_pages(root), ())

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

    def test_jsonl_valid_record_has_escaped_compact_summary_and_full_details(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "events.jsonl").write_text(
                '{"id":"<script>alert(1)</script>","result":"wrong","score":2,"nested":{"x":1}}\n',
                encoding="utf-8",
            )

            page = load_source_pages(root)[0]

            self.assertIn('<dl class="jlpt-json-summary">', page.markdown)
            self.assertIn("<dt>id</dt>", page.markdown)
            self.assertIn("<dt>result</dt>", page.markdown)
            self.assertIn("<dt>score</dt>", page.markdown)
            self.assertIn('<details class="jlpt-json-record">', page.markdown)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page.markdown)
            self.assertNotIn("<script>alert(1)</script>", page.markdown)

    def test_jsonl_attempt_summary_shows_core_attempt_fields_and_full_record(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "attempts.jsonl").write_text(
                '{"question_id":"N5-Q-0001","revision":1,"item_type":"grammar_form",'
                '"selected_option":"<4>","is_correct":false,"uncertain":false,'
                '"error_tags":["接续错误"],"date":"2026-07-26"}\n',
                encoding="utf-8",
            )

            page = load_source_pages(root)[0]

            for field in (
                "question_id",
                "item_type",
                "selected_option",
                "is_correct",
                "uncertain",
                "revision",
            ):
                self.assertIn(f"<dt>{field}</dt>", page.markdown)
            self.assertIn("&lt;4&gt;", page.markdown)
            self.assertNotIn("<4>", page.markdown)
            self.assertIn('<details class="jlpt-json-record">', page.markdown)
            self.assertIn("&quot;question_id&quot;", page.markdown)

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

    def test_catalog_entries_expose_filter_selector_class(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "N5-G-0001.md").write_text("# 卡片\n", encoding="utf-8")

            catalog = build_catalog_page(load_source_pages(root))
            parser = _CatalogEntryParser()
            parser.feed(catalog.markdown)

            self.assertEqual(len(parser.entry_attributes), 1)
            self.assertIn("jlpt-catalog-entry", parser.entry_attributes[0].get("class", "").split())

    def test_casefold_collisions_have_a_stable_original_path_tiebreaker(self) -> None:
        lowercase_path = Path("alpha.md")
        uppercase_path = Path("Alpha.md")
        lowercase = SourcePage(
            lowercase_path,
            lowercase_path,
            "# lower\n",
            parse_markdown(lowercase_path, "# lower\n").metadata,
            "lower",
        )
        uppercase = SourcePage(
            uppercase_path,
            uppercase_path,
            "# upper\n",
            parse_markdown(uppercase_path, "# upper\n").metadata,
            "upper",
        )

        catalog = build_catalog_page((lowercase, uppercase))

        self.assertLess(catalog.markdown.index("Alpha.md"), catalog.markdown.index("alpha.md"))


if __name__ == "__main__":
    unittest.main()
