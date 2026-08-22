"""Behavioral tests for the quiz answer submission boundary."""

import json
import pathlib
import tempfile
import unittest

from jlpt_notes.reader.submissions import (
    MAX_REQUEST_BYTES,
    SubmissionResult,
    apply_submission,
    find_answer_block,
    is_blank_answer_area,
    parse_paper_structure,
    render_answer_area,
)

PAPER = """# 测试卷

## 作答说明

- 每题只有一个最佳答案。

## 第一部分：形式选择（1–2）

### 1. 問題一（　）。

1. 甲
2. 乙
3. 丙
4. 丁

### 2. 問題二（　）。

1. 甲
2. 乙
3. 丙
4. 丁

## 第二部分：排序（3）

### 3. 昨日、＿＿ ★ ＿＿ ＿＿ 話しました。

1. 先輩が
2. 教えてくれた
3. 店について
4. 友だちに

## 答案填写区

```text
第一部分（1–2）：
_1_ , _1_

第二部分（3，请提交完整语序，如“3：1234”）：
_1_
```
"""


class ParsePaperStructureTests(unittest.TestCase):
    def test_parses_questions_with_kind_and_option_count(self):
        questions, _ = parse_paper_structure(PAPER)
        self.assertEqual(
            [(q.number, q.kind, q.option_count) for q in questions],
            [(1, "choice", 4), (2, "choice", 4), (3, "ordering", 4)],
        )

    def test_groups_questions_into_parts_and_stops_at_answer_area(self):
        _, parts = parse_paper_structure(PAPER)
        self.assertEqual(
            [(ordinal, numbers) for ordinal, _, numbers in parts],
            [("一", (1, 2)), ("二", (3,))],
        )

    def test_questions_before_any_part_heading_get_a_default_part(self):
        text = "# 卷\n\n### 1. 题（　）。\n\n1. 甲\n2. 乙\n3. 丙\n4. 丁\n"
        questions, parts = parse_paper_structure(text)
        self.assertEqual([q.number for q in questions], [1])
        self.assertEqual([(ordinal, numbers) for ordinal, _, numbers in parts], [("一", (1,))])


    def test_parses_nested_h4_question_headings_in_cloze_part(self):
        text = (
            "# 试卷\n\n"
            "## 第三部分：完形（3–4）\n\n"
            "### 文章一：某个干扰标题\n\n"
            "#### 3. 问题三（　）。\n\n"
            "1. 甲\n2. 乙\n3. 丙\n4. 丁\n\n"
            "#### 4. 问题四（　）。\n\n"
            "1. 甲\n2. 乙\n3. 丙\n4. 丁\n\n"
            "## 答案填写区\n\n"
            "```text\n第三部分（3–4）：\n_1_ , _1_\n```\n"
        )
        questions, parts = parse_paper_structure(text)
        self.assertEqual(
            [(q.number, q.kind, q.option_count) for q in questions],
            [(3, "choice", 4), (4, "choice", 4)],
        )
        self.assertEqual(
            [(ordinal, numbers) for ordinal, _, numbers in parts],
            [("三", (3, 4))],
        )


class AnswerBlockTests(unittest.TestCase):
    def test_finds_the_inner_text_of_the_answer_fence(self):
        inner = find_answer_block(PAPER)[2]
        self.assertIsNotNone(inner)
        self.assertIn("_1_", inner)

    def test_returns_none_when_the_heading_or_fence_is_missing(self):
        self.assertIsNone(find_answer_block("# 卷\n\n没有答案区\n"))
        self.assertIsNone(find_answer_block("# 卷\n\n## 答案填写区\n\n没有围栏\n"))

    def test_placeholder_only_area_is_blank(self):
        self.assertTrue(is_blank_answer_area("第一部分（1–2）：\n_1_ , _1_\n\n"))
        self.assertTrue(is_blank_answer_area("\n  \n"))

    def test_any_real_answer_makes_the_area_not_blank(self):
        self.assertFalse(is_blank_answer_area("1-1 , 2-3\n"))
        self.assertFalse(is_blank_answer_area("_1_\n*3-1234\n"))

    def test_part_headers_are_not_mistaken_for_answers(self):
        self.assertTrue(is_blank_answer_area("第一部分（1–20）：\n_1_ , _1_\n"))

    def test_offsets_span_exactly_the_whole_fence_including_marker_lines(self):
        start, end, inner = find_answer_block(PAPER)
        block = PAPER[start:end]
        self.assertEqual(block, "```text\n" + inner + "```\n")
        self.assertTrue(block.startswith("```text\n"))
        self.assertTrue(block.endswith("```\n"))
        self.assertIn("_1_", inner)

    def test_offsets_stay_exact_under_crlf_line_endings(self):
        lf_start, lf_end, lf_inner = find_answer_block(PAPER)
        crlf_paper = PAPER.replace("\n", "\r\n")
        found = find_answer_block(crlf_paper)
        self.assertIsNotNone(found)
        start, end, inner = found
        self.assertEqual(crlf_paper[start:end], "```text\r\n" + inner + "```\r\n")
        self.assertEqual(inner.replace("\r\n", "\n"), lf_inner)
        # 围栏内每行多一个 \r，块长度相应增加；块前的行同理。
        fence_lines = lf_inner.count("\n") + 2
        self.assertEqual(end - start, (lf_end - lf_start) + fence_lines)
        lines_before = crlf_paper[:start].count("\n")
        self.assertEqual(start, lf_start + lines_before)

    def test_real_placeholder_shapes_are_treated_as_blank(self):
        self.assertTrue(
            is_blank_answer_area("第一部分（1–20）：\n1-__ , 2-__ , 21-____\n")
        )
        self.assertFalse(is_blank_answer_area("1-3 , 21-1234\n"))


class RenderAnswerAreaTests(unittest.TestCase):
    def test_renders_parts_with_five_answers_per_line_and_star_prefix(self):
        _, parts = parse_paper_structure(PAPER)
        answers = {1: ("1", False), 2: ("3", True), 3: ("2314", False)}
        inner = render_answer_area(answers, parts)
        self.assertEqual(
            inner,
            "第一部分（1–2）：\n1-1 , *2-3\n\n第二部分（3，请提交完整语序，如“3：1234”）：\n3-2314\n",
        )

    def test_wraps_after_every_five_answers(self):
        text = "# 卷\n\n## 第一部分（1–6）\n\n" + "".join(
            f"### {n}. 题（　）。\n\n1. 甲\n2. 乙\n3. 丙\n4. 丁\n\n" for n in range(1, 7)
        )
        _, parts = parse_paper_structure(text)
        answers = {n: (str(n % 4 + 1), False) for n in range(1, 7)}
        inner = render_answer_area(answers, parts)
        self.assertIn("1-2 , 2-3 , 3-4 , 4-1 , 5-2\n6-3\n", inner)


def _papers_dir(tmp: pathlib.Path, text: str = PAPER, name: str = "paper.md") -> pathlib.Path:
    papers = tmp / "quizzes" / "papers"
    papers.mkdir(parents=True)
    (papers / name).write_text(text, encoding="utf-8")
    return papers


class ApplySubmissionTests(unittest.TestCase):
    def _payload(self, **overrides):
        body = {"paper": "paper.md", "answers": [
            {"number": 1, "value": "1", "uncertain": False},
            {"number": 2, "value": "3", "uncertain": True},
            {"number": 3, "value": "2314", "uncertain": False},
        ]}
        body.update(overrides)
        return json.dumps(body).encode("utf-8")

    def test_writes_only_the_answer_block_and_keeps_every_other_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers = _papers_dir(pathlib.Path(tmp))
            original = (papers / "paper.md").read_text(encoding="utf-8")
            block = find_answer_block(original)
            expected = original[: block[0]] + "```text\n" + render_answer_area(
                {1: ("1", False), 2: ("3", True), 3: ("2314", False)},
                parse_paper_structure(original)[1],
            ) + "```" + original[block[1]:]
            result = apply_submission(papers, self._payload())
            self.assertEqual(result.status_code, 200)
            self.assertEqual((papers / "paper.md").read_text(encoding="utf-8"), expected)

    def test_rejects_when_the_answer_area_is_already_filled(self):
        filled = PAPER.replace("_1_ , _1_", "1-1 , 2-1", 1)
        with tempfile.TemporaryDirectory() as tmp:
            papers = _papers_dir(pathlib.Path(tmp), filled)
            before = (papers / "paper.md").read_bytes()
            result = apply_submission(papers, self._payload())
            self.assertEqual(result.status_code, 409)
            self.assertEqual((papers / "paper.md").read_bytes(), before)

    def test_rejects_path_traversal_paper_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers = _papers_dir(pathlib.Path(tmp))
            for evil in ("../evil.md", "a/b.md", "..", "paper.md:stream"):
                result = apply_submission(papers, self._payload(paper=evil))
                self.assertEqual(result.status_code, 400, evil)

    def test_rejects_unknown_paper_with_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers = _papers_dir(pathlib.Path(tmp))
            result = apply_submission(papers, self._payload(paper="missing.md"))
            self.assertEqual(result.status_code, 404)

    def test_rejects_bad_values_and_missing_or_duplicate_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers = _papers_dir(pathlib.Path(tmp))
            before = (papers / "paper.md").read_bytes()
            bad_bodies = [
                self._payload(answers=[{"number": 1, "value": "9", "uncertain": False}]),
                self._payload(answers=[{"number": 3, "value": "1123", "uncertain": False},
                                       {"number": 1, "value": "1", "uncertain": False},
                                       {"number": 2, "value": "2", "uncertain": False}]),
                self._payload(answers=[{"number": 1, "value": "1", "uncertain": False},
                                       {"number": 1, "value": "2", "uncertain": False}]),
                self._payload(answers=[{"number": 1, "value": "1", "uncertain": False}]),
                b"not json",
            ]
            for body in bad_bodies:
                result = apply_submission(papers, body)
                self.assertEqual(result.status_code, 400, body)
            self.assertEqual((papers / "paper.md").read_bytes(), before)

    def test_rejects_oversized_bodies_before_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers = _papers_dir(pathlib.Path(tmp))
            result = apply_submission(papers, b"x" * (MAX_REQUEST_BYTES + 1))
            self.assertEqual(result.status_code, 413)


if __name__ == "__main__":
    unittest.main()
