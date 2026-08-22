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
_QUESTION_HEADING = re.compile(r"^###\s*(\d+)[\.．]")
_OPTION_LINE = re.compile(r"^\d+[\.．]\s+\S")


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
