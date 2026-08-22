"""Write validated answers into the blank answer area of quiz papers.

The reader remains strictly read-only everywhere else; this module is the
single narrow write surface, confined to existing papers under
``quizzes/papers`` and to the fenced block under their ``## 答案填写区``
heading.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import tempfile
from pathlib import Path
from threading import Lock


ANSWER_HEADING = "## 答案填写区"
MAX_REQUEST_BYTES = 8192
SUBMIT_PATH = "/reader/submit-answers"

_PART_HEADING = re.compile(r"^##\s*第(.+?)部分")
_QUESTION_HEADING = re.compile(r"^#{3,4}\s*(\d+)[\.．]")
_OPTION_LINE = re.compile(r"^\d+[\.．]\s+\S")
# 假设答案区内容只含服务端格式的「题号-数字」（可带前置 * 不确定标记），
# 因此占位符如 `1-__` 不会命中，仍视为空白。
_REAL_ANSWER = re.compile(r"^\s*\*?\d+-\d", re.MULTILINE)


@dataclass(frozen=True)
class PaperQuestion:
    """One quiz question discovered from the paper's own structure."""

    number: int
    kind: str  # "choice" or "ordering"
    option_count: int


# ordinal (第X部分), title line, question numbers
PaperPart = tuple[str, str, tuple[int, ...]]


def parse_paper_structure(text: str) -> tuple[tuple[PaperQuestion, ...], tuple[PaperPart, ...]]:
    """Parse questions and part groupings from a paper, stopping at the answer area."""
    questions: list[PaperQuestion] = []
    parts: list[PaperPart] = []
    current_part_index: int | None = None
    current_numbers: list[int] = []

    def flush() -> None:
        nonlocal current_part_index, current_numbers
        if current_part_index is not None:
            ordinal, title, _ = parts[current_part_index]
            parts[current_part_index] = (ordinal, title, tuple(current_numbers))
        current_part_index = None
        current_numbers = []

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == ANSWER_HEADING:
            break
        part_match = _PART_HEADING.match(line)
        if part_match:
            flush()
            parts.append((part_match.group(1), line.strip(), ()))
            current_part_index = len(parts) - 1
            current_numbers = []
            index += 1
            continue
        question_match = _QUESTION_HEADING.match(line)
        if question_match:
            number = int(question_match.group(1))
            stem = line
            option_count = 0
            scan = index + 1
            while scan < len(lines):
                candidate = lines[scan]
                if candidate.startswith("#") or candidate.strip() == ANSWER_HEADING:
                    break
                if _PART_HEADING.match(candidate):
                    break
                if _QUESTION_HEADING.match(candidate):
                    break
                stem += "\n" + candidate
                if _OPTION_LINE.match(candidate):
                    option_count += 1
                scan += 1
            kind = "ordering" if "★" in stem.splitlines()[0] else "choice"
            questions.append(PaperQuestion(number=number, kind=kind, option_count=option_count))
            if current_part_index is None:
                parts.append(("一", "作答", ()))
                current_part_index = len(parts) - 1
                current_numbers = []
            current_numbers.append(number)
        index += 1
    flush()
    return tuple(questions), tuple(parts)


def find_answer_block(text: str) -> tuple[int, int, str] | None:
    """Locate the fenced code block under the answer-area heading.

    Returns ``(block_start, block_end, inner)`` covering the whole fence
    including the ``` markers, or None when the heading or fence is absent.

    ``block_end`` is exclusive; offsets are measured against text read by
    the caller with ``newline=""`` so original line endings are preserved.
    """
    lines = text.splitlines(keepends=True)
    heading_index = None
    for i, line in enumerate(lines):
        if line.strip() == ANSWER_HEADING:
            heading_index = i
            break
    if heading_index is None:
        return None
    fence_start = None
    for i in range(heading_index + 1, len(lines)):
        if lines[i].startswith("#"):
            break
        if lines[i].lstrip().startswith("```"):
            fence_start = i
            break
    if fence_start is None:
        return None
    fence_end = None
    for i in range(fence_start + 1, len(lines)):
        if lines[i].lstrip().startswith("```"):
            fence_end = i
            break
    if fence_end is None:
        return None
    inner = "".join(lines[fence_start + 1 : fence_end])
    start = sum(len(line) for line in lines[: fence_start])
    end = start + len(lines[fence_start]) + len(inner) + len(lines[fence_end])
    return start, end, inner


def is_blank_answer_area(inner: str) -> bool:
    """True when the area holds only placeholders, headers, and whitespace."""
    return _REAL_ANSWER.search(inner) is None


_PAPER_NAME = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*\.md$")
_CHOICE_VALUE = re.compile(r"^[1-9]$")
_ORDERING_VALUE = re.compile(r"^\d+$")

_submit_lock = Lock()


@dataclass(frozen=True)
class SubmissionResult:
    """One submission outcome ready for an HTTP response."""

    status_code: int
    body: dict


def apply_submission(papers_dir: Path, raw_body: bytes) -> SubmissionResult:
    """Validate and apply one answer submission; never touches other files."""
    if len(raw_body) > MAX_REQUEST_BYTES:
        return SubmissionResult(413, {"error": "请求过大"})
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return SubmissionResult(400, {"error": "请求不是有效的 JSON"})
    paper_name = payload.get("paper") if isinstance(payload, dict) else None
    if not isinstance(paper_name, str) or not _PAPER_NAME.fullmatch(paper_name):
        return SubmissionResult(400, {"error": "试卷文件名无效"})
    answers_payload = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers_payload, list):
        return SubmissionResult(400, {"error": "缺少答案列表"})
    with _submit_lock:
        resolved_root = papers_dir.resolve(strict=True)
        target = (resolved_root / paper_name).resolve()
        if target.parent != resolved_root or not target.is_file():
            return SubmissionResult(404, {"error": "试卷不存在"})
        try:
            with target.open("r", encoding="utf-8", newline="") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            return SubmissionResult(404, {"error": "试卷不可读"})
        questions, parts = parse_paper_structure(text)
        block = find_answer_block(text)
        if not questions or block is None:
            return SubmissionResult(400, {"error": "试卷缺少答案填写区"})
        if not is_blank_answer_area(block[2]):
            return SubmissionResult(409, {"error": "该试卷已有作答，不能重复提交"})
        expected_numbers = {question.number for question in questions}
        by_number: dict[int, tuple[str, bool]] = {}
        for item in answers_payload:
            if not isinstance(item, dict):
                return SubmissionResult(400, {"error": "答案条目格式无效"})
            number = item.get("number")
            value = item.get("value")
            uncertain = item.get("uncertain")
            if isinstance(number, bool) or not isinstance(number, int) or number not in expected_numbers:
                return SubmissionResult(400, {"error": f"题号无效：{number!r}"})
            if number in by_number:
                return SubmissionResult(400, {"error": f"题号重复：{number}"})
            if not isinstance(value, str) or not isinstance(uncertain, bool):
                return SubmissionResult(400, {"error": f"第 {number} 题答案格式无效"})
            question = next(q for q in questions if q.number == number)
            if question.kind == "choice":
                if not _CHOICE_VALUE.fullmatch(value) or int(value) > question.option_count:
                    return SubmissionResult(400, {"error": f"第 {number} 题选项无效"})
            else:
                if (
                    not _ORDERING_VALUE.fullmatch(value)
                    or len(value) != question.option_count
                    or sorted(value) != [str(digit) for digit in range(1, question.option_count + 1)]
                ):
                    return SubmissionResult(400, {"error": f"第 {number} 题语序无效"})
            by_number[number] = (value, uncertain)
        if set(by_number) != expected_numbers:
            return SubmissionResult(400, {"error": "答案必须覆盖试卷全部题目"})
        new_inner = render_answer_area(by_number, parts)
        start, end, _inner = block
        new_text = text[:start] + "```text\n" + new_inner + "```" + text[end:]
        fd, temp_name = tempfile.mkstemp(dir=str(resolved_root), suffix=".jlpt-tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(new_text)
            os.replace(temp_name, target)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return SubmissionResult(200, {"status": "saved"})


def render_answer_area(answers: dict[int, tuple[str, bool]], parts: tuple[PaperPart, ...]) -> str:
    """Build the answer-area inner text in the quiz-grade compatible format.

    ``answers`` maps question number to ``(value, uncertain)``.  Uncertain
    answers get ``*`` before the question number, matching historical papers.
    """
    blocks: list[str] = []
    for ordinal, _title, numbers in parts:
        if not numbers:
            continue
        tokens = []
        for number in numbers:
            value, uncertain = answers[number]
            token = f"{number}-{value}"
            if uncertain:
                token = f"*{token}"
            tokens.append(token)
        # 选择题值恒为单个数字，语序串长度 > 1，故以此启发式判断
        # （调用方已先校验值的合法性）。
        has_ordering = any(len(value) > 1 for value, _ in (answers[n] for n in numbers))
        # 单题部分只显示题号（如「（3，…）」），与历史试卷格式一致。
        range_str = str(numbers[0]) if numbers[0] == numbers[-1] else f"{numbers[0]}–{numbers[-1]}"
        if has_ordering:
            header = f"第{ordinal}部分（{range_str}，请提交完整语序，如“{numbers[0]}：1234”）："
        else:
            header = f"第{ordinal}部分（{range_str}）："
        lines = [header]
        for start in range(0, len(tokens), 5):
            lines.append(" , ".join(tokens[start : start + 5]))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
