import json
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import unquote, urljoin, urlsplit

from mkdocs.commands.build import build
from mkdocs.config import load_config

from jlpt_notes.reader.plugin import _render_card_pager, _refresh_reused_generation, _sanitize_html


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


class _CodeTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self._code_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "code":
            self._code_depth += 1
            if self._code_depth == 1:
                self.blocks.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "code":
            self._code_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._code_depth:
            self.blocks[-1] += data


class _DocumentContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.metas: list[dict[str, str | None]] = []
        self.resources: list[str] = []
        self.page_state: dict[str, str | None] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "meta":
            self.metas.append(attributes)
        if tag == "script" and attributes.get("src"):
            self.resources.append(attributes["src"] or "")
        link_relations = (attributes.get("rel") or "").split()
        if tag == "link" and attributes.get("href") and set(link_relations) & {
            "stylesheet",
            "icon",
            "apple-touch-icon",
        }:
            self.resources.append(attributes["href"] or "")
        if tag == "div" and "jlpt-page-state" in (attributes.get("class") or "").split():
            self.page_state = attributes


def _assert_local_resources_exist(test: unittest.TestCase, site: Path, page: Path, html: str) -> None:
    parser = _DocumentContractParser()
    parser.feed(html)
    resources = list(parser.resources)
    config_match = re.search(r'<script id="__config" type="application/json">(.*?)</script>', html)
    test.assertIsNotNone(config_match)
    assert config_match is not None
    resources.append(json.loads(config_match.group(1))["search"])
    page_url = f"https://reader.invalid/{page.relative_to(site).as_posix()}"
    for resource in resources:
        if resource.startswith("data:"):
            continue
        parsed = urlsplit(urljoin(page_url, resource))
        test.assertEqual(parsed.netloc, "reader.invalid", resource)
        target = site / unquote(parsed.path).lstrip("/")
        test.assertTrue(target.is_file(), f"Missing generated resource {resource!r} -> {target}")


def _article(html: str) -> str:
    return html.split('<article class="md-content__inner md-typeset">', 1)[1].split("</article>", 1)[0]


def _code_texts(html: str) -> list[str]:
    parser = _CodeTextParser()
    parser.feed(html)
    return parser.blocks


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
    def test_cached_generation_refresh_changes_only_generation_markers(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "index.html"
            old = "old-generation"
            new = "new-generation"
            path.write_text(
                '<meta name="jlpt-generation" content="old-generation">\n'
                '<div class="jlpt-page-state" data-page-key="./" '
                'data-generation="old-generation"></div>\n'
                '<p>old-generation is learner content</p>\n',
                encoding="utf-8",
            )

            _refresh_reused_generation(path, new, old)

            refreshed = path.read_text(encoding="utf-8")
            self.assertIn('content="new-generation"', refreshed)
            self.assertIn('data-generation="new-generation"', refreshed)
            self.assertIn("old-generation is learner content", refreshed)

    def test_theme_asset_retention_does_not_reintroduce_linked_source_files(self) -> None:
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside_directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            external = Path(outside_directory) / "outside.md"
            external.write_text("# OUTSIDE_SOURCE_SENTINEL\n", encoding="utf-8")
            try:
                (docs / "linked.md").symlink_to(external)
            except OSError:
                self.skipTest("当前环境不允许创建符号链接")
            (docs / "kept.md").write_text("# KEPT_SOURCE_SENTINEL\n", encoding="utf-8")

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            self.assertFalse((site / "linked.md").exists())
            self.assertFalse(any("OUTSIDE_SOURCE_SENTINEL" in path.read_text(encoding="utf-8") for path in site.rglob("*.html")))
            self.assertIn("KEPT_SOURCE_SENTINEL", _site_page_containing(site, "KEPT_SOURCE_SENTINEL"))

    def test_shipped_reader_theme_builds_a_private_ipad_document_contract(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        config_file = project_root / "reader/mkdocs.yml"
        with TemporaryDirectory() as directory:
            base = Path(directory)
            docs = base / "jlpt-notes"
            docs.mkdir()
            (docs / "N3-G-0042.md").write_text(
                '---\n{"id":"N3-G-0042","level":"N3","kind":"grammar","title":"～うちに"}\n---\n\n# 核心\n正文\n',
                encoding="utf-8",
            )
            site = base / "site"

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            html = _site_page_containing(site, "正文")
            parser = _DocumentContractParser()
            parser.feed(html)
            metadata = {item.get("name"): item.get("content") for item in parser.metas}
            self.assertEqual(metadata["robots"], "noindex, nofollow")
            self.assertEqual(metadata["apple-mobile-web-app-capable"], "yes")
            self.assertEqual(metadata["apple-mobile-web-app-title"], "JLPT 阅读")
            self.assertTrue(metadata["jlpt-page-key"])
            self.assertTrue((site / "assets/reader.css").is_file())
            self.assertTrue((site / "assets/reader.js").is_file())
            self.assertTrue(any("reader.css" in resource for resource in parser.resources))
            self.assertTrue(any("reader.js" in resource for resource in parser.resources))
            self.assertTrue(any("assets/javascripts/bundle." in resource for resource in parser.resources))
            self.assertFalse(
                [resource for resource in parser.resources if resource.startswith(("http://", "https://", "//"))]
            )
            self.assertIn('data-level="N3"', (site / "index.html").read_text(encoding="utf-8"))
            self.assertIsNotNone(parser.page_state)
            manifest = json.loads((site / "reader-version.json").read_text(encoding="utf-8"))
            assert parser.page_state is not None
            page_key = parser.page_state["data-page-key"] or ""
            self.assertEqual(parser.page_state["data-page-hash"], manifest["pages"][page_key])
            self.assertEqual(parser.page_state["data-generation"], manifest["version"])
            page_file = next(page for page in site.rglob("index.html") if page.read_text(encoding="utf-8") == html)
            _assert_local_resources_exist(self, site, page_file, html)

            reader_css = (site / "assets/reader.css").read_text(encoding="utf-8")
            reader_js = (site / "assets/reader.js").read_text(encoding="utf-8")
            self.assertIn("safe-area-inset", reader_css)
            self.assertIn("prefers-reduced-motion", reader_css)
            for storage_key in (
                "jlpt-reader-theme",
                "jlpt-reader-font-scale",
                "jlpt-reader-last-page",
                "jlpt-reader-scroll:",
            ):
                self.assertIn(storage_key, reader_js)
            self.assertIn("reader-version.json", reader_js)
            self.assertIn('cache: "no-store"', reader_js)
            self.assertIn("未标记", reader_js)
            self.assertIn("正式语法", reader_js)
            self.assertIn("标签", reader_js)
            self.assertNotIn("serviceWorker.register", reader_js)
            self.assertNotIn("fonts.googleapis.com", reader_css + reader_js)
            self.assertNotRegex(reader_js, r"fetch\(\s*['\"]https?://")

            catalog_html = (site / "index.html").read_text(encoding="utf-8")
            self.assertIn('data-jlpt-fulltext=""', catalog_html)
            self.assertIn('for="jlpt-fulltext-query"', catalog_html)
            self.assertIn('id="jlpt-fulltext-query"', catalog_html)
            self.assertIn('type="search"', catalog_html)
            self.assertIn('aria-describedby="jlpt-fulltext-status"', catalog_html)
            self.assertIn('aria-live="polite"', catalog_html)
            self.assertRegex(catalog_html, r'id="jlpt-fulltext-query"[^>]+disabled')
            self.assertIn('id="jlpt-fulltext-status"', catalog_html)
            self.assertIn('role="status"', catalog_html)
            self.assertTrue((site / "search/search_index.json").is_file())

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
                "````markdown\n```\n# FENCED_SENTINEL\n```\n````\n\n    # indented code\n\n"
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
            self.assertIn("# BLOCKQUOTE_FENCED_CODE\n", _code_texts(article))
            self.assertIn("# BLOCKQUOTE_INDENTED_CODE\n", _code_texts(article))
            self.assertIn("&lt;h1&gt;INLINE_CODE&lt;/h1&gt;", article)
            self.assertIn("REAL_H1_AFTER_INVALID_FENCE", article)
            self.assertIn('href="#REAL_H1_AFTER_INVALID_FENCE"', page_html)

    def test_superfences_preserves_significant_whitespace_in_blockquoted_code(self) -> None:
        with TemporaryDirectory() as directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            (docs / "quoted-code.md").write_text(
                "> ```text\n"
                ">   TWO_SPACE_SENTINEL\n"
                "> ```\n",
                encoding="utf-8",
            )

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            article = _site_article_containing(site, "TWO_SPACE_SENTINEL")
            self.assertIn("  TWO_SPACE_SENTINEL\n", _code_texts(article))

    def test_superfences_keeps_quoted_fence_example_literal_inside_longer_fence(self) -> None:
        with TemporaryDirectory() as directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            (docs / "literal-fence.md").write_text(
                "````markdown\n"
                "> ```markdown\n"
                "> # QUOTED_FENCE_LITERAL\n"
                "> ```\n"
                "````\n",
                encoding="utf-8",
            )

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            article = _site_article_containing(site, "QUOTED_FENCE_LITERAL")
            self.assertIn(
                "> ```markdown\n> # QUOTED_FENCE_LITERAL\n> ```\n",
                _code_texts(article),
            )

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

    def test_card_pager_render_outputs_both_sides_with_escaped_titles(self) -> None:
        html = _render_card_pager(
            (
                "library/grammar/n4/N4-G-0001.md.__reader_markdown__/",
                "N4-G-0001｜「～までに」：截止时限",
            ),
            (
                "library/grammar/n4/N4-G-0003.md.__reader_markdown__/",
                "N4-G-0003｜「～やすい」：容易 \"与\" 易发生",
            ),
        )

        self.assertIn('<nav class="jlpt-card-pager"', html)
        self.assertIn('class="jlpt-card-pager__link jlpt-card-pager__link--prev"', html)
        self.assertIn('class="jlpt-card-pager__link jlpt-card-pager__link--next"', html)
        self.assertIn("← 上一张卡", html)
        self.assertIn("下一张卡 →", html)
        self.assertIn('href="library/grammar/n4/N4-G-0001.md.__reader_markdown__/"', html)

        cleaned = _sanitize_html(html)
        self.assertIn('jlpt-card-pager__link--prev', cleaned)
        self.assertIn('href="library/grammar/n4/N4-G-0001.md.__reader_markdown__/"', cleaned)
        self.assertIn("&quot;与&quot;", cleaned)
        self.assertNotIn("<script", cleaned)

    def test_card_pager_render_hides_missing_sides_and_empty_sequence(self) -> None:
        one_sided = _render_card_pager(None, ("library/x/", "N4-G-0002｜次"))

        self.assertNotIn("jlpt-card-pager__link--prev", one_sided)
        self.assertIn("jlpt-card-pager__link--next", one_sided)
        self.assertEqual(_render_card_pager(None, None), "")


if __name__ == "__main__":
    unittest.main()
