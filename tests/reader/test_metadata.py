import unittest
from pathlib import Path

from jlpt_notes.reader.metadata import parse_markdown, render_metadata_block


class ReaderMetadataTests(unittest.TestCase):
    def test_formal_card_uses_full_id_and_title(self) -> None:
        text = '''---
{"id":"N5-G-0001","level":"N5","kind":"grammar","title":"～です","status":"confirmed","tags":["丁寧体"],"next_review":"2026-08-25"}
---

# 核心用法
正文
'''
        parsed = parse_markdown(Path("grammar/n5/N5-G-0001.md"), text)
        self.assertEqual(parsed.metadata.display_title, "N5-G-0001｜～です")
        self.assertEqual(parsed.metadata.level, "N5")
        self.assertEqual(parsed.metadata.content_type, "grammar")
        self.assertEqual(parsed.metadata.tags, ("丁寧体",))
        self.assertEqual(parsed.body, "# 核心用法\n正文\n")

    def test_draft_reads_nested_proposal(self) -> None:
        text = '''---
{"draft_id":"draft-20260805-n4-g-0055","confirmed":true,"proposal":{"id":"N4-G-0055","level":"N4","kind":"grammar","title":"～ように言います","status":"confirmed"}}
---

## 学习者原始输出
正文
'''
        parsed = parse_markdown(Path("drafts/draft-20260805-n4-g-0055.md"), text)
        self.assertEqual(parsed.metadata.display_title, "N4-G-0055｜草稿｜～ように言います")
        self.assertEqual(parsed.metadata.content_type, "draft")

    def test_report_uses_level_date_and_heading_without_inventing_id(self) -> None:
        text = "# 2026-07-27 N5 全语法综合诊断卷（二）：作答报告\n\n正文\n"
        parsed = parse_markdown(
            Path("quizzes/results/2026-07-27-n5-comprehensive-test-2-result.md"), text
        )
        self.assertEqual(
            parsed.metadata.display_title,
            "N5｜2026-07-27｜全语法综合诊断卷（二）：作答报告",
        )
        self.assertIsNone(parsed.metadata.source_id)

    def test_malformed_frontmatter_keeps_body_and_returns_warning(self) -> None:
        parsed = parse_markdown(Path("drafts/broken.md"), "---\n{bad json}\n---\n\n# 可读正文\n")
        self.assertIn("元数据无法解析", parsed.warning or "")
        self.assertIn("# 可读正文", parsed.body)

    def test_metadata_block_escapes_values(self) -> None:
        parsed = parse_markdown(
            Path("grammar/n5/x.md"),
            '---\n{"id":"N5-G-9999","level":"N5","kind":"grammar","title":"<script>x</script>","tags":[]}\n---\n\n正文\n',
        )
        block = render_metadata_block(parsed.metadata)
        self.assertNotIn("<script>", block)
        self.assertIn("&lt;script&gt;", block)
