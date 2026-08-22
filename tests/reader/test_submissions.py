"""Behavioral tests for the quiz answer submission boundary."""

import unittest

from jlpt_notes.reader.submissions import parse_paper_structure

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


if __name__ == "__main__":
    unittest.main()
