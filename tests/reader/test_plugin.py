import json
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from mkdocs.commands.build import build
from mkdocs.config import load_config


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def _article(html: str) -> str:
    return html.split('<article class="md-content__inner md-typeset">', 1)[1].split("</article>", 1)[0]


def _site_article_containing(site: Path, text: str) -> str:
    return _article(_site_page_containing(site, text))


def _site_page_containing(site: Path, text: str) -> str:
    for page in site.rglob("index.html"):
        html = page.read_text(encoding="utf-8")
        if text in _article(html):
            return html
    raise AssertionError(f"No generated article contains {text!r}")


def _primary_navigation(html: str) -> str:
    return html.split('<div class="md-sidebar md-sidebar--primary"', 1)[1].split(
        '<div class="md-sidebar md-sidebar--secondary"', 1
    )[0]


def _write_reader_config(base: Path) -> tuple[Path, Path, Path]:
    docs = base / "jlpt-notes"
    docs.mkdir()
    assets = base / "assets"
    assets.mkdir()
    (assets / "reader.css").write_text("", encoding="utf-8")
    (assets / "reader.js").write_text("", encoding="utf-8")
    config_file = base / "mkdocs.yml"
    config_file.write_text(
        "site_name: JLPT\ntheme:\n  name: material\nmarkdown_extensions:\n  - pymdownx.superfences\nplugins:\n  - jlpt_reader:\n      assets_dir: assets\n",
        encoding="utf-8",
    )
    return docs, config_file, base / "site"


class ReaderPluginTests(unittest.TestCase):
    def test_build_uses_display_title_and_does_not_copy_raw_sources(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            docs = base / "jlpt-notes"
            docs.mkdir()
            (docs / "card.md").write_text(
                '---\n{"id":"N5-G-0001","level":"N5","kind":"grammar","title":"～です"}\n---\n\n# 核心\n正文\n',
                encoding="utf-8",
            )
            (docs / "events.jsonl").write_text('{"id":"e1"}\n', encoding="utf-8")
            assets = base / "assets"
            assets.mkdir()
            (assets / "reader.css").write_text(".jlpt-meta{}", encoding="utf-8")
            (assets / "reader.js").write_text("", encoding="utf-8")
            config_file = base / "mkdocs.yml"
            config_file.write_text(
                "site_name: JLPT\ntheme:\n  name: material\nplugins:\n  - jlpt_reader:\n      assets_dir: assets\n  - search\n",
                encoding="utf-8",
            )
            site = base / "site"
            config = load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site))
            build(config)

            html = _site_article_containing(site, "正文")
            self.assertIn("N5-G-0001｜～です", html)
            self.assertIn("jlpt-meta", html)
            self.assertIn('<h2 id="核心">核心</h2>', html)
            self.assertFalse((site / "events.jsonl").is_file())
            manifest = json.loads((site / "reader-version.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["pages"]), 3)
            for url in manifest["pages"]:
                self.assertTrue((site / url / "index.html").is_file(), url)

    def test_build_preserves_warnings_and_removes_active_source_html(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            docs = base / "jlpt-notes"
            docs.mkdir()
            source_text = (
                "---\nnot-json\n---\n\n# 安全性\n"
                '<div class="safe" data-reader-state="open" onclick="alert(1)">正常</div>\n'
                '<a href="javascript:alert(1)">危险链接</a>\n'
                '<script>alert("run")</script><iframe src="https://bad.example">嵌入</iframe>\n'
                "<details><summary>展开</summary><span tabindex=\"0\">内容</span></details>\n"
            )
            (docs / "unsafe.md").write_text(source_text, encoding="utf-8")
            assets = base / "assets"
            assets.mkdir()
            (assets / "reader.css").write_text("", encoding="utf-8")
            (assets / "reader.js").write_text("", encoding="utf-8")
            config_file = base / "mkdocs.yml"
            config_file.write_text(
                "site_name: JLPT\ntheme:\n  name: material\nplugins:\n  - jlpt_reader:\n      assets_dir: assets\n",
                encoding="utf-8",
            )
            site = base / "site"
            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            article = _site_article_containing(site, "正常")
            self.assertIn("元数据无法解析；正文仍以只读方式显示。", article)
            self.assertIn('class="safe"', article)
            self.assertIn('data-reader-state="open"', article)
            self.assertIn("<details>", article)
            self.assertIn("<summary>展开</summary>", article)
            self.assertNotIn("<script", article)
            self.assertNotIn("alert(1)", article)
            self.assertNotIn("<iframe", article)
            self.assertNotIn("onclick=", article)
            self.assertNotIn("javascript:", article)

    def test_manifest_hashes_source_bytes_and_has_stable_version(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            docs = base / "jlpt-notes"
            docs.mkdir()
            source_text = "# 卡片\n"
            (docs / "card.md").write_text(source_text, encoding="utf-8")
            assets = base / "assets"
            assets.mkdir()
            (assets / "reader.css").write_text("", encoding="utf-8")
            (assets / "reader.js").write_text("", encoding="utf-8")
            config_file = base / "mkdocs.yml"
            config_file.write_text(
                "site_name: JLPT\ntheme:\n  name: material\nplugins:\n  - jlpt_reader:\n      assets_dir: assets\n",
                encoding="utf-8",
            )
            site = base / "site"

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))
            first = json.loads((site / "reader-version.json").read_text(encoding="utf-8"))
            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))
            second = json.loads((site / "reader-version.json").read_text(encoding="utf-8"))

            self.assertEqual(first, second)
            self.assertIn(sha256((docs / "card.md").read_bytes()).hexdigest(), first["pages"].values())
            self.assertEqual(len(first["version"]), 64)

    def test_catalog_links_use_each_page_final_virtual_route(self) -> None:
        with TemporaryDirectory() as directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            (docs / "grammar").mkdir()
            (docs / "grammar/N5-G-0001.md").write_text("# 卡片\n", encoding="utf-8")
            (docs / "events.jsonl").write_text('{"id":"event"}\n', encoding="utf-8")

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            parser = _HrefParser()
            parser.feed(_article((site / "index.html").read_text(encoding="utf-8")))
            self.assertEqual(len(parser.hrefs), 2)
            for href in parser.hrefs:
                self.assertTrue((site / href / "index.html").is_file(), href)

    def test_colliding_source_names_all_get_unique_pages_and_manifest_entries(self) -> None:
        with TemporaryDirectory() as directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            (docs / "README.md").write_text("# Readme\n", encoding="utf-8")
            (docs / "index.md").write_text("# Source index\n", encoding="utf-8")
            (docs / "foo").mkdir()
            (docs / "foo.md").write_text("# Flat foo\n", encoding="utf-8")
            (docs / "foo/index.md").write_text("# Nested foo\n", encoding="utf-8")
            (docs / "events.jsonl").write_text('{"id":"json"}\n', encoding="utf-8")
            (docs / "events.jsonl.md").write_text("# Markdown event\n", encoding="utf-8")

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            manifest = json.loads((site / "reader-version.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["pages"]), 7)
            self.assertEqual(len(set(manifest["pages"])), 7)
            for url in manifest["pages"]:
                self.assertTrue((site / url / "index.html").is_file(), url)

    def test_nav_uses_chinese_folder_labels_and_structured_ordering(self) -> None:
        with TemporaryDirectory() as directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            grammar = docs / "grammar"
            grammar.mkdir()
            (grammar / "N5-G-0010.md").write_text('# 十\n', encoding="utf-8")
            (grammar / "N5-G-0002.md").write_text('# 二\n', encoding="utf-8")
            history = docs / "history"
            history.mkdir()
            (history / "2026-07-26.md").write_text('# 旧\n', encoding="utf-8")
            (history / "2026-07-27.md").write_text('# 新\n', encoding="utf-8")
            (docs / "drafts").mkdir()
            (docs / "drafts/a.md").write_text('# 草稿\n', encoding="utf-8")
            (docs / "quizzes").mkdir()
            (docs / "quizzes/a.md").write_text('# 测试\n', encoding="utf-8")
            (docs / "reviews").mkdir()
            (docs / "reviews/a.md").write_text('# 复习\n', encoding="utf-8")

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            html = (site / "index.html").read_text(encoding="utf-8")
            for label in ("正式语法卡", "草稿", "测试", "复习记录", "修改历史"):
                self.assertIn(label, html)
            self.assertLess(html.index("N5-G-0002｜二"), html.index("N5-G-0010｜十"))
            self.assertLess(html.index("新"), html.index("旧"))

    def test_generated_title_is_only_h1_without_touching_code_examples(self) -> None:
        with TemporaryDirectory() as directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            (docs / "forms.md").write_text(
                "   # 缩进 ATX\n\nSetext\n======\n\n> # 引用标题\n\n> > # 嵌套引用标题\n\n"
                "> 引用 Setext\n> =====\n\n"
                '<h1 class="raw">原始 H1</h1>\n\n```markdown\n# code sample\n```\n\n'
                "````markdown\n```\n# FENCED_SENTINEL\n```\n````\n\n    # indented code\n"
                "> ```markdown\n> # BLOCKQUOTE_FENCED_CODE\n> ```\n\n"
                ">     # BLOCKQUOTE_INDENTED_CODE\n\n"
                "inline `<h1>INLINE_CODE</h1>`\n\n"
                "```invalid`info\nnot a valid opener\n```\n\n# REAL_H1_AFTER_INVALID_FENCE\n",
                encoding="utf-8",
            )

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            page_html = _site_page_containing(site, "# code sample")
            article = _article(page_html)
            self.assertEqual(article.count("<h1"), 1)
            self.assertIn("<h2", article)
            self.assertIn("# code sample", article)
            self.assertIn("# FENCED_SENTINEL", article)
            self.assertIn("# indented code", article)
            self.assertIn('<code class="language-markdown"># BLOCKQUOTE_FENCED_CODE', article)
            self.assertIn("<code># BLOCKQUOTE_INDENTED_CODE", article)
            self.assertIn("&lt;h1&gt;INLINE_CODE&lt;/h1&gt;", article)
            self.assertIn("REAL_H1_AFTER_INVALID_FENCE", article)
            self.assertIn('href="#REAL_H1_AFTER_INVALID_FENCE"', page_html)

    def test_navigation_hoists_root_folders_and_orders_date_bearing_papers_newest_first(self) -> None:
        with TemporaryDirectory() as directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            grammar = docs / "grammar"
            grammar.mkdir()
            (grammar / "N5-G-0001.md").write_text("# Grammar sentinel\n", encoding="utf-8")
            papers = docs / "quizzes/papers"
            papers.mkdir(parents=True)
            (papers / "2026-07-26.md").write_text("# PAPER_OLD_SENTINEL\n", encoding="utf-8")
            (papers / "2026-07-27.md").write_text("# PAPER_NEW_SENTINEL\n", encoding="utf-8")

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            html = (site / "index.html").read_text(encoding="utf-8")
            navigation = _primary_navigation(html)
            self.assertIn("正式语法卡", navigation)
            self.assertIn("测试", navigation)
            self.assertNotRegex(navigation, r'<span class="md-ellipsis">\s*资料库\s*</span>')
            self.assertLess(navigation.index("PAPER_NEW_SENTINEL"), navigation.index("PAPER_OLD_SENTINEL"))


if __name__ == "__main__":
    unittest.main()
