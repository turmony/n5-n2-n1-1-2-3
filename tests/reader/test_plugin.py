import json
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mkdocs.commands.build import build
from mkdocs.config import load_config


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

            html = (site / "card/index.html").read_text(encoding="utf-8")
            self.assertIn("N5-G-0001｜～です", html)
            self.assertIn("jlpt-meta", html)
            self.assertIn('<h2 id="核心">核心</h2>', html)
            self.assertIn('href="#核心"', html)
            self.assertFalse((site / "events.jsonl").is_file())
            self.assertTrue((site / "events.jsonl/index.html").exists())
            manifest = json.loads((site / "reader-version.json").read_text(encoding="utf-8"))
            self.assertIn("card/", manifest["pages"])

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

            html = (site / "unsafe/index.html").read_text(encoding="utf-8")
            article = html.split('<article class="md-content__inner md-typeset">', 1)[1].split("</article>", 1)[0]
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
            self.assertEqual(first["pages"]["card/"], sha256((docs / "card.md").read_bytes()).hexdigest())
            self.assertEqual(len(first["version"]), 64)


if __name__ == "__main__":
    unittest.main()
